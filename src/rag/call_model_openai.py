import os
import importlib
import subprocess
import sys

from dotenv import load_dotenv
from openai import OpenAIError

try:
    from .llm import (
        NO_INFORMATION_ANSWER,
        ModelUnavailableError,
        ask,
        create_client,
        create_fallback_client,
        primary_model_name,
    )
    from .vectorize import populate_db, query_collection
    from .translate import localize
    from .conversation_pdf import save_conversation_pdf
except ImportError:
    llm = importlib.import_module("llm")
    NO_INFORMATION_ANSWER = llm.NO_INFORMATION_ANSWER
    ModelUnavailableError = llm.ModelUnavailableError
    ask = llm.ask
    create_client = llm.create_client
    create_fallback_client = llm.create_fallback_client
    primary_model_name = llm.primary_model_name
    vectorize = importlib.import_module("vectorize")
    populate_db = vectorize.populate_db
    query_collection = vectorize.query_collection
    # Stesso modulo usato da vectorize: condivide cache e circuit breaker.
    localize = importlib.import_module("src.rag.translate").localize
    save_conversation_pdf = importlib.import_module(
        "src.rag.conversation_pdf"
    ).save_conversation_pdf

load_dotenv()
populate_db(reset=os.getenv("RESET_CHROMA", "").lower() in ["1", "true", "yes"])

subprocess.run("cls", shell=True)

MAX_HISTORY_TURNS = 2
MAX_QUESTION_LENGTH = 2000
N_RESULTS = 8

conversation = []
transcript = []  # intera conversazione, per i PDF finali
last_question = None
last_services = []


def retrieve(question):
    documents, metadatas = query_collection(question, n_results=N_RESULTS)
    if documents or not last_question:
        return documents, metadatas, False
    documents, metadatas = query_collection(
        f"{last_question} {question}", n_results=N_RESULTS
    )
    return documents, metadatas, True


def prioritize_known_services(documents, metadatas):
    """Porta davanti i servizi già emersi nel turno precedente."""
    if not last_services:
        return documents, metadatas
    order = {service: index for index, service in enumerate(last_services)}
    paired = sorted(
        zip(documents, metadatas),
        key=lambda item: order.get(item[1].get("service"), len(order)),
    )
    return (
        [document for document, _ in paired],
        [metadata for _, metadata in paired],
    )


def remember_services(metadatas):
    services = []
    for metadata in metadatas:
        service = metadata.get("service")
        if service and service not in services:
            services.append(service)
    return services


try:
    client = create_client()
    fallback_client = create_fallback_client()
except RuntimeError as exc:
    print(f"[rag] {exc}")
    sys.exit(1)

while True:
    try:
        question = input(
            "\nFai una domanda (o digita 'exit' o 'q' per uscire): "
        ).strip()
    except (EOFError, KeyboardInterrupt):
        print("\nArrivederci!")
        break

    if not question:
        continue
    if question.lower() in ["exit", "q", "stop"]:
        print("Arrivederci!")
        break
    if len(question) > MAX_QUESTION_LENGTH:
        print(
            f"La domanda è troppo lunga (massimo {MAX_QUESTION_LENGTH} "
            "caratteri). Prova a sintetizzarla.\n"
        )
        continue

    documents, metadatas, merged = retrieve(question)
    documents, metadatas = prioritize_known_services(documents, metadatas)
    if not documents:
        print(
            f"{primary_model_name()}: "
            f"{localize(NO_INFORMATION_ANSWER, question)}\n"
        )
        continue

    # Ancoraggio al tema appena recuperato: vale anche se la generazione
    # fallisce, così la domanda successiva ("e le normative?") non resta orfana.
    if not merged:
        last_question = question
        last_services = remember_services(metadatas) or last_services

    try:
        assistant = ask(
            client,
            question,
            documents,
            metadatas,
            history=conversation,
            fallback_client=fallback_client,
        )
    except ModelUnavailableError as exc:
        print(f"{primary_model_name()}: {exc} Riprova tra poco.\n")
        continue
    except OpenAIError as exc:
        print(
            f"{primary_model_name()}: errore nella comunicazione con il "
            f"servizio AI ({exc}). Riprova.\n"
        )
        continue

    print(f"{primary_model_name()}:", assistant, "\n")

    conversation.append({"role": "user", "content": question})
    conversation.append({"role": "assistant", "content": assistant})
    del conversation[:-MAX_HISTORY_TURNS * 2]
    transcript.append({"role": "user", "content": question})
    transcript.append({"role": "assistant", "content": assistant})

if transcript:
    try:
        pdf_path = save_conversation_pdf(transcript)
        print(f"PDF salvati:\n  {italian_pdf}\n  {original_pdf}")
    except Exception as exc:
        print(f"[rag] Impossibile creare i PDF: {exc}")
