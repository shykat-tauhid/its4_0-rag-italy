"""Corpus del chatbot: `data/sources.json` più i file in `data/docs/`.

Ogni voce di `sources.json` descrive un file:
- `pagina`: testo Markdown di una pagina del portale di Roma Capitale, che
  viene indicizzato; `forms` elenca gli id dei moduli collegati;
- `modulo` / `guida`: PDF da mostrare e stampare sul totem (se ne indicizza
  solo il titolo).

`url` è l'indirizzo originale sul portale. I file in `data/docs/` sono serviti
al frontend sotto `/documents/`.
"""

import json
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DOCS_DIR = DATA_DIR / "docs"
SOURCES_FILE = DATA_DIR / "sources.json"

PAGE_KIND = "pagina"
FILE_KINDS = {"modulo", "guida"}

# Coda delle pagine copiate dal portale (valutazione della pagina, chat):
# non contiene informazioni sul servizio.
_BOILERPLATE_RE = re.compile(r"^#{1,6}\s*Ti è stata utile questa pagina\?", re.MULTILINE)
_HTML_TAG_RE = re.compile(r"</?(?:u|b|i|em|strong|span|br)\b[^>]*>", re.IGNORECASE)
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


class CorpusError(ValueError):
    """`sources.json` non valido o file mancanti."""


def clean_markdown(text: str) -> str:
    """Testo della pagina senza coda del portale e senza tag HTML."""
    match = _BOILERPLATE_RE.search(text)
    if match:
        text = text[: match.start()]
    text = _HTML_TAG_RE.sub("", text)
    text = _LINK_RE.sub(lambda m: f"{m.group(1)} ({m.group(2)})", text)
    return text.strip()


def load_corpus(sources_file: Path = SOURCES_FILE, docs_dir: Path = DOCS_DIR) -> list[dict]:
    """Voci di `sources.json`, con il testo pulito (`text`) per le pagine.

    Controlla che ogni file esista e che i moduli citati nelle pagine siano
    voci note: un errore qui è meglio di un indice incompleto.
    """
    try:
        entries = json.loads(Path(sources_file).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CorpusError(f"Impossibile leggere {sources_file}: {exc}") from exc
    if not isinstance(entries, list):
        raise CorpusError(f"{sources_file}: serve una lista di voci.")

    corpus = []
    ids = set()
    for entry in entries:
        missing = [key for key in ("id", "title", "kind", "file") if not entry.get(key)]
        if missing:
            raise CorpusError(f"Voce senza {', '.join(missing)}: {entry}")
        if entry["id"] in ids:
            raise CorpusError(f"Id duplicato: {entry['id']}")
        ids.add(entry["id"])

        path = Path(docs_dir) / entry["file"]
        if not path.is_file():
            raise CorpusError(f"File mancante per '{entry['id']}': {path}")

        item = {
            "id": entry["id"],
            "title": entry["title"],
            "kind": entry["kind"],
            "file": entry["file"],
            "url": entry.get("url") or None,
            "forms": list(entry.get("forms") or []),
        }
        if entry["kind"] == PAGE_KIND:
            item["text"] = clean_markdown(path.read_text(encoding="utf-8"))
        corpus.append(item)

    for item in corpus:
        unknown = [form for form in item["forms"] if form not in ids]
        if unknown:
            raise CorpusError(f"'{item['id']}' cita moduli inesistenti: {unknown}")
    return corpus


def by_id(corpus: list[dict]) -> dict[str, dict]:
    return {item["id"]: item for item in corpus}
