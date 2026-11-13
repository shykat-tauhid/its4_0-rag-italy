from contextlib import asynccontextmanager
import json
import logging
import os
import urllib.error
from typing import Annotated, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAIError
from pydantic import BaseModel, ConfigDict, Field

from .llm import (
    ModelUnavailableError,
    ask,
    create_client,
    create_fallback_client,
    no_information_answer,
    translate_to_italian,
)
from .conversation_pdf import build_pdf
from .vectorize import corpus, populate_db, query_collection
from . import kiosk, printer
from .corpus import by_id


load_dotenv()

logger = logging.getLogger(__name__)

MODEL_UNAVAILABLE_DETAIL = "Errore nella comunicazione con il servizio AI."
PDF_ERROR_DETAIL = "Impossibile generare il PDF della conversazione."
# Tetto sul testo totale della conversazione esportata in PDF.
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

# File del corpus (data/docs): testo salvato delle pagine e moduli PDF da
# mostrare e stampare sul totem.
app.mount(
    "/documents",
    StaticFiles(directory=kiosk.DOCUMENTS_DIR, check_dir=False),
    name="documents",
)
sessions = kiosk.SessionStore()
corpus_by_id = by_id(corpus)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


class PdfMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: Annotated[str, Field(min_length=1, max_length=20000)]


class PdfRequest(BaseModel):
    messages: Annotated[list[PdfMessage], Field(min_length=1, max_length=200)]


@app.post("/api/conversation/pdf")
def conversation_pdf(payload: PdfRequest, request: Request):
    """PDF tabellato dell'intera conversazione per l'operatore (l'API non ha
    stato: la invia il client): lingua dell'utente a sinistra, traduzione
    italiana (fatta dal modello) a destra."""
    messages = [message.model_dump() for message in payload.messages]
    if sum(len(message["content"]) for message in messages) > PDF_MAX_TOTAL_CHARS:
        raise HTTPException(
            status_code=413,
            detail="La conversazione è troppo lunga per essere esportata in PDF.",
        )
    try:
        pdf = build_pdf(
            messages,
            lambda texts: translate_to_italian(
                request.app.state.model_client,
                texts,
                fallback_client=request.app.state.fallback_model_client,
            ),
        )
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
        return ChatResponse(answer=no_information_answer())

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


# --- API del totem (frontend Angular) -------------------------------------


class StreamRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    message: Annotated[str, Field(min_length=1, max_length=2000)]
    language: Annotated[str | None, Field(max_length=10)] = None
    service: Annotated[str | None, Field(max_length=40)] = None
    session_id: Annotated[str | None, Field(max_length=100)] = None


def _event(payload: dict) -> bytes:
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")


@app.post("/api/chat/stream")
def chat_stream(payload: StreamRequest, request: Request) -> StreamingResponse:
    """Risposta come eventi NDJSON: `token`, `sources`, `done` (o `error`).

    La conversazione è tenuta in memoria per `session_id`, così le domande di
    seguito ("e quali documenti servono?") hanno il contesto della precedente.
    """
    model_client = request.app.state.model_client
    fallback_client = request.app.state.fallback_model_client
    documents_url = str(request.base_url).rstrip("/") + "/documents"

    def events():
        question = payload.message
        session = sessions.get(payload.session_id)
        try:
            documents, metadatas, merged = kiosk.retrieve(
                query_collection, question, session, n_results=8
            )
            if not documents:
                answer = no_information_answer(payload.language)
                yield _event({"type": "token", "text": answer})
                yield _event({"type": "done"})
                return

            if not merged:
                session.last_question = question
                session.last_services = kiosk.services_of(metadatas) or session.last_services

            answer = ask(
                model_client,
                question,
                documents,
                metadatas,
                history=list(session.history),
                fallback_client=fallback_client,
            )
            session.remember(question, answer)
            yield _event({"type": "token", "text": answer})
            sources, forms = kiosk.build_sources(metadatas, corpus_by_id, documents_url)
            yield _event({"type": "sources", "sources": sources, "forms": forms})
            yield _event({"type": "done"})
        except (ModelUnavailableError, OpenAIError):
            logger.exception("Modello non disponibile")
            yield _event({"type": "error", "message": MODEL_UNAVAILABLE_DETAIL})
        except Exception:
            logger.exception("Errore durante la risposta in streaming")
            yield _event({"type": "error", "message": "Errore interno."})

    return StreamingResponse(events(), media_type="application/x-ndjson")


@app.get("/api/embeddable")
def embeddable(url: Annotated[str, Query(max_length=2000)]) -> dict[str, bool]:
    """Dice se la pagina si può mostrare in un frame del totem."""
    return {"embeddable": kiosk.is_embeddable(url)}


@app.get("/api/pdf")
def pdf_proxy(url: Annotated[str, Query(max_length=2000)]) -> Response:
    """Scarica un PDF di un altro sito per il visualizzatore del totem."""
    try:
        data = kiosk.download_pdf(url)
    except kiosk.BlockedUrlError as exc:
        raise HTTPException(status_code=400, detail="URL non consentito.") from exc
    except kiosk.NotAPdfError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="PDF non raggiungibile.") from exc
    return Response(content=data, media_type="application/pdf")


class PrintRequest(BaseModel):
    pages: Annotated[list[str], Field(min_length=1, max_length=printer.MAX_PAGES)]


@app.post("/api/print", status_code=204)
def print_pages(payload: PrintRequest) -> Response:
    """Stampa le pagine sulla stampante Bluetooth del totem, senza finestre."""
    try:
        printer.print_pages(payload.pages)
    except printer.PrinterError as exc:
        logger.warning("Stampa non riuscita: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(status_code=204)
