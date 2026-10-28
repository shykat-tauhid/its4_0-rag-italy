from contextlib import asynccontextmanager
import logging
import os
from typing import Annotated, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAIError
from pydantic import BaseModel, ConfigDict, Field

from .llm import (
    NO_INFORMATION_ANSWER,
    ModelUnavailableError,
    ask,
    create_client,
    create_fallback_client,
)
from .conversation_pdf import build_pdf
from .vectorize import populate_db, query_collection
from .start_libretranslate import ensure_libretranslate_running
from .translate import localize


load_dotenv()

logger = logging.getLogger(__name__)

MODEL_UNAVAILABLE_DETAIL = "Errore nella comunicazione con il servizio AI."
PDF_ERROR_DETAIL = "Impossibile generare il PDF della conversazione."
# Tetto sul testo totale: ogni messaggio viene tradotto per il PDF in italiano.
PDF_MAX_TOTAL_CHARS = 60000


class ChatRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    question: Annotated[str, Field(min_length=1, max_length=2000)]


class ChatResponse(BaseModel):
    answer: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.model_client = create_client()
    app.state.fallback_model_client = create_fallback_client()
    populate_db(reset=os.getenv("RESET_CHROMA", "").lower() in {"1", "true", "yes"})

    # Avvio automatico LibreTranslate all'avvio dell'applicazione
    logger.info("Controllo servizio LibreTranslate...")
    app.state.libretranslate_available = ensure_libretranslate_running()
    if app.state.libretranslate_available:
        logger.info("LibreTranslate attivo: traduzioni automatiche abilitate")
    else:
        logger.warning(
            "LibreTranslate non disponibile: uso il glossario interno per la traduzione"
        )

    yield


app = FastAPI(
    title="Anagrafe RAG API",
    description="API per porre domande sui servizi anagrafici e sulle normative.",
    version="1.0.0",
    lifespan=lifespan,
)

allowed_origins = [
    origin.strip()
    for origin in os.getenv("ANGULAR_ORIGINS", "http://localhost:4200").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
    expose_headers=["Content-Disposition"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


class PdfMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: Annotated[str, Field(min_length=1, max_length=20000)]


class PdfRequest(BaseModel):
    messages: Annotated[list[PdfMessage], Field(min_length=1, max_length=200)]


@app.post("/api/conversation/pdf")
def conversation_pdf(payload: PdfRequest):
    """PDF tabellato dell'intera conversazione (l'API non ha stato: la invia il
    client): italiano a sinistra, lingua dell'utente a destra."""
    messages = [message.model_dump() for message in payload.messages]
    if sum(len(message["content"]) for message in messages) > PDF_MAX_TOTAL_CHARS:
        raise HTTPException(
            status_code=413,
            detail="La conversazione è troppo lunga per essere esportata in PDF.",
        )
    try:
        pdf = build_pdf(messages)
    except Exception as exc:
        logger.exception("Generazione PDF fallita")
        raise HTTPException(status_code=500, detail=PDF_ERROR_DETAIL) from exc
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="conversazione.pdf"'
        },
    )


@app.post("/api/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    documents, metadatas = query_collection(payload.question, n_results=8)
    if not documents:
        return ChatResponse(
            answer=localize(NO_INFORMATION_ANSWER, payload.question)
        )

    try:
        answer = ask(
            request.app.state.model_client,
            payload.question,
            documents,
            metadatas,
            fallback_client=request.app.state.fallback_model_client,
        )
    except (ModelUnavailableError, OpenAIError) as exc:
        raise HTTPException(
            status_code=502,
            detail=MODEL_UNAVAILABLE_DETAIL,
        ) from exc

    return ChatResponse(answer=answer)
