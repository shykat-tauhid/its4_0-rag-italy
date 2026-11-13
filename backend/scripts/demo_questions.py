"""Prova le domande di data/demo_questions.json sul chatbot.

Per ogni domanda (e i suoi follow-up, nella stessa sessione) stampa le pagine
recuperate e i moduli proposti; con --answers chiede anche la risposta al
modello configurato nel .env.

Uso:
    uv run python scripts/demo_questions.py            # solo retrieval
    uv run python scripts/demo_questions.py --answers  # anche le risposte
    uv run python scripts/demo_questions.py --language uk
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rag import kiosk  # noqa: E402
from rag.corpus import by_id  # noqa: E402
from rag.vectorize import corpus, populate_db, query_collection  # noqa: E402

N_RESULTS = 8


def _questions(entry):
    yield entry["question"], entry.get("meaning")
    for follow_up in entry.get("follow_up", []):
        if isinstance(follow_up, str):
            yield follow_up, None
        else:
            yield follow_up["question"], follow_up.get("meaning")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--answers", action="store_true", help="chiedi anche la risposta al modello")
    parser.add_argument("--language", help="solo le domande in questa lingua (es. it, uk, zh)")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    entries = json.loads((ROOT / "data" / "demo_questions.json").read_text(encoding="utf-8"))
    if args.language:
        entries = [entry for entry in entries if entry.get("language") == args.language]

    populate_db()
    items = by_id(corpus)
    if args.answers:
        from rag.llm import NO_INFORMATION_ANSWER, ModelUnavailableError, ask, create_client, create_fallback_client

        client, fallback = create_client(), create_fallback_client()

    for number, entry in enumerate(entries, start=1):
        session = kiosk.Session()
        for question, meaning in _questions(entry):
            print(f"\n[{number}] ({entry.get('language', '?')}) {question}")
            if meaning:
                print(f"    = {meaning}")
            documents, metadatas, merged = kiosk.retrieve(query_collection, question, session, N_RESULTS)
            if not merged and documents:
                session.last_question = question
                session.last_services = kiosk.services_of(metadatas) or session.last_services

            sources, forms = kiosk.build_sources(metadatas, items, "/documents")
            if not documents:
                print("    nessun documento recuperato")
            for source in sources:
                print(f"    fonte:  {source['title']}")
            for form in forms:
                print(f"    modulo: {form['title']}")

            if args.answers:
                if not documents:
                    answer = NO_INFORMATION_ANSWER
                else:
                    try:
                        answer = ask(client, question, documents, metadatas,
                                     history=list(session.history), fallback_client=fallback)
                    except ModelUnavailableError as exc:
                        answer = f"(modello non disponibile: {exc})"
                    session.remember(question, answer)
                print("    risposta:", answer.replace("\n", "\n              "))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
