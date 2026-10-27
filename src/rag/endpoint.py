from contextlib import asynccontextmanager
import os
from typing import Annotated

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
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
from .vectorize import populate_db, query_collection
from .start_libretranslate import ensure_libretranslate_running
from .start_libretranslate import ensure_libretranslate_running


load_dotenv()

MODEL_UNAVAILABLE_DETAIL = "Errore nella comunicazione con il servizio AI."


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
    print("[startup] Controllo servizio LibreTranslate...")
    lt_available = ensure_libretranslate_running()
    app.state.libretranslate_available = lt_available
    if lt_available:
        print("[startup] LibreTranslate attivo - traduzioni automatiche enabled")
    else:
        print("[startup] LibreTranslate non disponibile - uso glossario interno per la traduzione")
    
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
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    documents, metadatas = query_collection(payload.question, n_results=8)
    if not documents:
        return ChatResponse(answer=NO_INFORMATION_ANSWER)

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
