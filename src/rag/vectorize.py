import hashlib
import json
import math
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if __package__ in (None, ""):
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

import chromadb
from chromadb.utils import embedding_functions
from data.anagrafe import docs

try:
    from .translate import translate_to_italian
except ImportError:  # importato come modulo piatto (call_model_openai.py)
    from src.rag.translate import translate_to_italian


chromadb_path = str(Path(__file__).parent.parent / "chromadb")
COLLECTION_NAME = "comune_roma"
INDEX_VERSION = "3"

# I prefissi "passage: "/"query: " sono quelli della famiglia multilingual-e5:
# cambiando modello (es. intfloat/multilingual-e5-large) l'indice si ricostruisce
# da solo perché il nome del modello entra nel fingerprint.
EMBEDDING_MODEL = (
    os.getenv("EMBEDDING_MODEL", "").strip() or "intfloat/multilingual-e5-base"
)
PASSAGE_PREFIX = "passage: "
QUERY_PREFIX = "query: "

CHUNK_MAX_WORDS = 200
CHUNK_OVERLAP_WORDS = 30
DEFAULT_N_RESULTS = 8
REGULATION_QUOTA = 3
CANDIDATE_POOL = 30
LEXICAL_CANDIDATES = 30
RRF_K = 60

RERANK_MODEL = os.getenv(
    "RERANK_MODEL", "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
).strip()
RERANK_ENABLED = RERANK_MODEL.lower() not in {"", "0", "off", "none", "false"}
RERANK_SCORE_MARGIN = 5.0
RERANK_SCORE_MARGIN_MIN = 2.5
MIN_RERANK_SCORE = -1.5
MAX_DENSE_DISTANCE = 0.65


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_optional_float(name: str, default: float | None):
    raw = os.getenv(name)
    if raw is None:
        return default
    if raw.strip().lower() in {"", "off", "none", "false"}:
        return None
    try:
        return float(raw)
    except ValueError:
        return default


CANDIDATE_POOL = _env_int("CANDIDATE_POOL", CANDIDATE_POOL)
LEXICAL_CANDIDATES = _env_int("LEXICAL_CANDIDATES", LEXICAL_CANDIDATES)
REGULATION_QUOTA = _env_int("REGULATION_QUOTA", REGULATION_QUOTA)
RERANK_SCORE_MARGIN = _env_float("RERANK_SCORE_MARGIN", RERANK_SCORE_MARGIN)
RERANK_SCORE_MARGIN_MIN = _env_float(
    "RERANK_SCORE_MARGIN_MIN", RERANK_SCORE_MARGIN_MIN
)
MIN_RERANK_SCORE = _env_optional_float("MIN_RERANK_SCORE", MIN_RERANK_SCORE)
MAX_DENSE_DISTANCE = _env_float("MAX_DENSE_DISTANCE", MAX_DENSE_DISTANCE)


def _index_fingerprint() -> str:
    payload = {
        "index_version": INDEX_VERSION,
        "chunk_max_words": CHUNK_MAX_WORDS,
        "chunk_overlap_words": CHUNK_OVERLAP_WORDS,
        "embedding_model": EMBEDDING_MODEL,
        "docs": docs,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


INDEX_FINGERPRINT = _index_fingerprint()


ef = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name=EMBEDDING_MODEL,
    normalize_embeddings=True,
)

client = chromadb.PersistentClient(
    path=chromadb_path
)


def _create_collection():
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=ef,  # pyright:ignore
        metadata={
            "index_version": INDEX_VERSION,
            "index_fingerprint": INDEX_FINGERPRINT,
        },
    )


def _open_collection(reset: bool = False):
    if reset:
        try:
            client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass

    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=ef,  # pyright:ignore
    )
    metadata = collection.metadata or {}
    stored_version = str(metadata.get("index_version", ""))
    stored_fingerprint = str(metadata.get("index_fingerprint", ""))
    if (
        stored_version != INDEX_VERSION
        or stored_fingerprint != INDEX_FINGERPRINT
    ):
        try:
            client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass
        collection = _create_collection()
    return collection


comune_roma_collection = _open_collection()
_lexical_index = None
_lexical_index_size = -1
_cross_encoder = None
_cross_encoder_failed = False


def _make_unique_id(*parts):
    text = "_".join(str(part) for part in parts if part is not None)
    return re.sub(r"[^a-zA-Z0-9_]+", "_", text).strip("_").lower()


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _build_regulation_document(regulation, article):
    return (
        f"Normativa: {regulation['type']} {regulation['number']} "
        f"del {regulation['date']}\n"
        f"Titolo: {regulation['title']}\n"
        f"Fonte: {regulation['source']}\n"
        f"Articolo {article['number']}:\n"
        f"{article['content']}"
    )


def _regulation_year(date: str) -> str | None:
    match = re.search(r"\b(?:19|20)\d{2}\b", date)
    return match.group(0) if match else None


_HEADING_HINTS = {
    "costi",
    "tempi",
    "tempi di rilascio",
    "documenti",
    "documentazione",
    "documenti necessari",
    "requisiti",
    "modalita",
    "modalità",
    "modulistica",
    "come accedere",
    "come richiedere",
    "dove",
    "quando",
    "cosa serve",
    "procedura",
    "note",
}


def _is_heading(line: str) -> bool:
    if not line or len(line) > 90:
        return False
    if line.endswith(":"):
        return True
    return line.rstrip(":").strip().lower() in _HEADING_HINTS


def _paragraphs_with_sections(text: str):
    section = "Descrizione"
    paragraphs = []
    for raw_line in text.splitlines():
        line = _normalize_text(raw_line)
        if not line:
            continue
        if _is_heading(line):
            section = line.rstrip(":").strip() or section
            continue
        paragraphs.append((section, line))
    return paragraphs


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _split_long_paragraph(paragraph: str, max_words: int):
    if len(paragraph.split()) <= max_words:
        return [paragraph]

    pieces = []
    for sentence in _SENTENCE_SPLIT_RE.split(paragraph):
        words = sentence.split()
        if not words:
            continue
        if len(words) <= max_words:
            pieces.append(sentence)
            continue
        for start in range(0, len(words), max_words):
            pieces.append(" ".join(words[start : start + max_words]))
    return pieces


def _chunk_text(
    text: str,
    max_words: int = CHUNK_MAX_WORDS,
    overlap_words: int = CHUNK_OVERLAP_WORDS,
):
    chunks = []
    buffer = []
    buffer_section = "Descrizione"

    def emit():
        nonlocal buffer
        if buffer:
            chunks.append((buffer_section, " ".join(buffer)))

    for section, paragraph in _paragraphs_with_sections(text):
        if section != buffer_section:
            emit()
            buffer = []
            buffer_section = section

        for piece in _split_long_paragraph(paragraph, max_words):
            words = piece.split()
            if not words:
                continue
            if buffer and len(buffer) + len(words) > max_words:
                emit()
                buffer = buffer[-overlap_words:] if overlap_words else []
            buffer.extend(words)

    emit()

    unique_chunks = []
    for section, chunk in chunks:
        if not unique_chunks or unique_chunks[-1][1] != chunk:
            unique_chunks.append((section, chunk))
    return unique_chunks


def _service_chunks(doc):
    chunks = _chunk_text(doc["description"])
    total = len(chunks)
    for index, (section, chunk) in enumerate(chunks):
        document = (
            f"Servizio: {doc['name']}\n"
            f"Categoria: {doc['category']}\n"
            f"Sezione: {section}\n"
            f"{chunk}"
        )
        metadata = {
            "category": doc["category"],
            "source": doc["source"],
            "service": doc["name"],
            "type": "service",
            "section": section,
            "chunk_index": index,
            "chunk_total": total,
        }
        yield document, metadata


def populate_db(reset=False):
    global comune_roma_collection
    global _lexical_index, _lexical_index_size

    comune_roma_collection = _open_collection(reset=reset)

    try:
        existing_items = comune_roma_collection.count()
    except Exception:
        comune_roma_collection = _open_collection(reset=True)
        existing_items = comune_roma_collection.count()

    if existing_items > 0:
        _lexical_index = None
        _lexical_index_size = -1
        return

    ids = []
    documents = []
    metadatas = []

    for doc in docs:

        # Chunk della descrizione del servizio
        for document, metadata in _service_chunks(doc):
            ids.append(
                _make_unique_id(doc["id"], "description", metadata["chunk_index"])
            )
            documents.append(document)
            metadatas.append(metadata)

        # Chunk delle normative
        for regulation in doc["regulations"]:

            year = _regulation_year(regulation["date"])

            for article in regulation["articles"]:

                ids.append(
                    _make_unique_id(
                        doc["id"],
                        regulation["type"],
                        regulation["number"],
                        regulation["date"],
                        "art",
                        article["number"],
                    )
                )

                documents.append(_build_regulation_document(regulation, article))

                metadata = {
                    "category": doc["category"],
                    "source": doc["source"],
                    "service": doc["name"],
                    "type": "regulation",
                    "regulation_type": regulation["type"],
                    "regulation_number": str(regulation["number"]),
                    "regulation_date": regulation["date"],
                    "regulation_title": regulation["title"],
                    "regulation_source": regulation["source"],
                    "article": str(article["number"]),
                }
                if year:
                    metadata["regulation_year"] = year
                metadatas.append(metadata)

        # Chunk dei documenti necessari
        for needed_doc in doc["needed_docs"]:

            ids.append(
                _make_unique_id(doc["id"], "needed_doc", needed_doc)
            )

            documents.append(
                f"Servizio: {doc['name']}\n"
                f"Documento necessario: {needed_doc}"
            )

            metadatas.append({
                "category": doc["category"],
                "source": doc["source"],
                "service": doc["name"],
                "type": "needed_document",
                "document_name": needed_doc,
                "document_path": f"documents/{needed_doc}",
            })

    if ids:
        comune_roma_collection.upsert(
            ids=ids,
            documents=[PASSAGE_PREFIX + document for document in documents],
            metadatas=metadatas,
        )

    _lexical_index = None
    _lexical_index_size = -1


def _clean_document(document: str) -> str:
    if document.startswith(PASSAGE_PREFIX):
        return document[len(PASSAGE_PREFIX) :]
    return document


def _record_text(document: str, metadata) -> str:
    clean = _clean_document(document)
    parts = []
    service = metadata.get("service")
    if service and not clean.startswith("Servizio:"):
        parts.append(f"Servizio: {service}")
    if metadata.get("section") and "Sezione:" not in clean[:120]:
        parts.append(f"Sezione: {metadata['section']}")
    if metadata.get("type") == "needed_document":
        parts.append(f"Documento: {metadata.get('document_name', '')}")
    if metadata.get("type") == "regulation" and not clean.startswith("Normativa:"):
        parts.append(
            "Normativa: "
            f"{metadata.get('regulation_type', '')} "
            f"{metadata.get('regulation_number', '')} "
            f"del {metadata.get('regulation_date', '')}"
        )
    parts.append(clean)
    return "\n".join(parts)


def _embed_query(question: str):
    embeddings = ef([QUERY_PREFIX + question])
    return embeddings[0].tolist()


_REGULATION_FULL_RE = re.compile(
    r"\b(?:(d\.?\s*p\.?\s*r\.?|d\.?\s*l\.?\s*g\.?|d\.?\s*l\.?|l\.?|"
    r"legge|decreto\s+legge|decreto\s+legislativo)\s*)?"
    r"(\d{1,4})\s*/\s*(\d{4})\b",
    re.IGNORECASE,
)
_REGULATION_SHORT_RE = re.compile(
    r"\b(d\.?\s*p\.?\s*r\.?|d\.?\s*l\.?\s*g\.?|d\.?\s*l\.?|l\.?|"
    r"legge|decreto\s+legge|decreto\s+legislativo)\s*(\d{1,4})\b(?!\s*/)",
    re.IGNORECASE,
)


def _extract_regulation_refs(question: str):
    refs = []
    seen = set()
    full_matches = []

    for match in _REGULATION_FULL_RE.finditer(question):
        full_matches.append(match.span())
        number, year = match.group(2), match.group(3)
        if number == "0":
            continue
        key = (number, year)
        if key not in seen:
            seen.add(key)
            refs.append({"number": number, "year": year})

    for match in _REGULATION_SHORT_RE.finditer(question):
        start, end = match.span()
        if any(
            start >= full_start and end <= full_end
            for full_start, full_end in full_matches
        ):
            continue
        number = match.group(2)
        if number == "0":
            continue
        key = (number, None)
        if key not in seen:
            seen.add(key)
            refs.append({"number": number, "year": None})

    return refs


def _merge_regulation_refs(*questions: str):
    """Unisce i riferimenti normativi estratti da più versioni della domanda.

    La traduzione può perdere o alterare un riferimento: quelli trovati nel
    testo originale restano validi.
    """
    refs = []
    seen = set()
    for question in questions:
        if not question:
            continue
        for ref in _extract_regulation_refs(question):
            key = (ref["number"], ref["year"])
            if key in seen:
                continue
            seen.add(key)
            refs.append(ref)
    return refs


def _query_results(result) -> list[dict[str, Any]]:
    ids = (result.get("ids") or [[]])[0] or []
    documents = (result.get("documents") or [[]])[0] or []
    metadatas = (result.get("metadatas") or [[]])[0] or []
    distances = (result.get("distances") or [[]])[0] or [None] * len(ids)

    records = []
    for item_id, document, metadata, distance in zip(
        ids, documents, metadatas, distances
    ):
        records.append(
            {
                "id": item_id,
                "document": document,
                "metadata": metadata or {},
                "distance": distance,
            }
        )
    return records


def _dense_search(collection, question: str, limit: int):
    available = collection.count()
    if available == 0:
        return []

    results = collection.query(
        query_embeddings=[_embed_query(question)],
        n_results=min(limit, available),
        include=["documents", "metadatas", "distances"],
    )
    records = _query_results(results)
    if MAX_DENSE_DISTANCE > 0:
        records = [
            record
            for record in records
            if record["distance"] is None
            or record["distance"] <= MAX_DENSE_DISTANCE
        ]
    return records


def _exact_regulation_search(collection, question: str, refs):
    available = collection.count()
    if available == 0 or not refs:
        return []

    records = []
    for ref in refs:
        conditions = [
            {"type": {"$eq": "regulation"}},
            {"regulation_number": {"$eq": ref["number"]}},
        ]
        if ref["year"]:
            conditions.append({"regulation_year": {"$eq": ref["year"]}})

        results = collection.query(
            query_embeddings=[_embed_query(question)],
            n_results=min(20, available),
            where={"$and": conditions},
            include=["documents", "metadatas", "distances"],
        )
        records.extend(_query_results(results))

    records.sort(key=lambda record: record["distance"] or 0.0)
    return records


_TOKEN_RE = re.compile(
    r"[a-zàèéìòóù0-9"
    r"\u0400-\u04FF"  # Ukrainian (Cyrillic)
    r"\u0980-\u09FF"  # Bengali
    r"\u0600-\u06FF"  # Arabic
    r"\u4E00-\u9FFF"  # Chinese (CJK Unified Ideographs)
    r"]+",
    re.IGNORECASE,
)
_STOPWORDS = {
    # Italian
    "a",
    "ad",
    "al",
    "alla",
    "alle",
    "allo",
    "anche",
    "che",
    "chi",
    "come",
    "con",
    "da",
    "dal",
    "dalla",
    "delle",
    "dei",
    "del",
    "della",
    "di",
    "e",
    "è",
    "ed",
    "gli",
    "ha",
    "ho",
    "i",
    "il",
    "in",
    "io",
    "la",
    "le",
    "lo",
    "ma",
    "mi",
    "ne",
    "nel",
    "nella",
    "no",
    "non",
    "o",
    "per",
    "più",
    "posso",
    "qual",
    "quale",
    "quali",
    "quando",
    "quanto",
    "se",
    "si",
    "sono",
    "su",
    "sul",
    "sulla",
    "tra",
    "un",
    "una",
    "uno",
    "vorrei",
    # Ukrainian (Cyrillic)
    "і",
    "та",
    "така",
    "це",
    "яка",
    "який",
    "які",
    "що",
    "ібо",
    # Bengali (Bangla script)
    "এ",
    "ও",
    "ক",
    "হ",
    "ছ",
    "ত",
    "থ",
    "দ",
    "ধ",
    "ন",
    "প",
    "ফ",
    "ব",
    "ভ",
    "ম",
    "য",
    "র",
    "ল",
    "শ",
    "ষ",
    "স",
    "হ",
    # Arabic
    "و",
    "في",
    "أن",
    "على",
    "من",
    "إلى",
    # Chinese (CJK)
    "的",
    "一",
    "是",
    "在",
    "了",
    "有",
    "和",
    "不",
    "人",
    "个",
    # Filipino (additional Latin-based terms)
    "kahit",
    "lang",
    "mga",
    "ng",
    "sa",
    "para",
    "ay",
    "ito",
    "iyan",
    "min",
}


_EN_IT_GLOSSARY = {
    "abroad": ("estero",),
    "address": ("indirizzo", "residenza", "domicilio"),
    "appointment": ("appuntamento", "prenotazione"),
    "appointments": ("appuntamenti", "prenotazione"),
    "birth": ("nascita",),
    "book": ("prenotare", "prenotazione"),
    "booking": ("prenotazione",),
    "card": ("carta", "tessera"),
    "cards": ("carte", "carta"),
    "certificate": ("certificato", "certificati"),
    "certificates": ("certificati", "certificato"),
    "certification": ("certificazione", "autocertificazione"),
    "change": ("cambio", "cambiare"),
    "child": ("minore", "bambino"),
    "children": ("minori", "bambini"),
    "civil": ("civile",),
    "code": ("codice",),
    "cost": ("costo", "costi"),
    "costs": ("costo", "costi"),
    "death": ("morte", "decesso"),
    "declaration": ("dichiarazione",),
    "document": ("documento", "documenti"),
    "documents": ("documenti", "documentazione"),
    "electronic": ("elettronica", "elettronico"),
    "expired": ("scaduta", "scaduto", "scadenza"),
    "expiring": ("scadenza",),
    "expiration": ("scadenza",),
    "expiry": ("scadenza",),
    "family": ("famiglia", "nucleo"),
    "fee": ("costo", "tariffa", "diritto"),
    "fees": ("costi", "tariffa", "diritto"),
    "foreign": ("straniero", "estero"),
    "health": ("sanitaria",),
    "identity": ("identità",),
    "law": ("legge", "normativa"),
    "laws": ("leggi", "normativa"),
    "legal": ("normativa", "legge"),
    "lost": ("smarrita", "smarrimento"),
    "marriage": ("matrimonio",),
    "married": ("matrimonio", "coniugato"),
    "minor": ("minore", "minori"),
    "minors": ("minori", "minore"),
    "move": ("trasferimento", "trasferire"),
    "moving": ("trasferimento",),
    "overseas": ("estero",),
    "paperwork": ("documenti", "documentazione"),
    "pay": ("pagamento", "pagare"),
    "payment": ("pagamento",),
    "photo": ("fototessera", "foto"),
    "price": ("costo", "tariffa"),
    "register": ("anagrafe", "iscrizione"),
    "registration": ("iscrizione", "registrazione"),
    "registry": ("anagrafe",),
    "regulation": ("normativa", "regolamento", "legge"),
    "regulations": ("normativa", "regolamento", "legge"),
    "renew": ("rinnovo", "rinnovare"),
    "renewal": ("rinnovo",),
    "renewed": ("rinnovo",),
    "renewing": ("rinnovo",),
    "requirement": ("requisiti",),
    "requirements": ("requisiti",),
    "reserve": ("prenotare", "prenotazione"),
    "residence": ("residenza",),
    "residency": ("residenza",),
    "self": ("autocertificazione",),
    "status": ("stato",),
    "stolen": ("furto",),
    "tax": ("fiscale",),
}
_IT_MULTILINGUAL_GLOSSARY = {
    # Ukrainian (Cyrillic)
    "квартира": ("appartamento",),
    "дом": ("casa", "abitazione"),
    "мэр": ("sindaco",),
    "район": ("quartiere", "circoscrizione"),
    "паспорт": ("passaporto",),
    "вид": ("permesso", "residenza"),
    "регистрация": ("iscrizione", "registrazione"),
    "документ": ("documento",),
    "закон": ("legge",),
    "номер": ("numero",),
    "дата": ("data",),
    "цена": ("costo",),
    "бесплатно": ("gratuito",),
    "оформление": ("procedura", "domanda"),
    "страница": ("pagina",),
    "подпись": ("firma",),
    "адрес": ("indirizzo",),
    "телефон": ("telefono",),
    "email": ("email",),
    # Filipino
    "passport": ("passaporto",),
    "cedula": ("cedula",),
    "barangay": ("barangay",),
    "certificate": ("certificato",),
    "ID": ("identificazione",),
    "barangay hall": ("sede del barangay",),
    "municipality": ("municipio",),
    "city hall": ("comune",),
    "documentary": ("documentale",),
    "renewal": ("rinnovo",),
    "application": ("domanda", "richiesta"),
    # Bengali
    "নামা": ("নামা",),  # keep as-is since Bangla
    "পাসপোর্ট": ("passaporto",),
    " certific": ("শবাদপত্র", "certificate",),
    "আইডি": ("আইডি",),
    "বই": (" publication",),
    "শিক্ষা": ("istruzione",),
    "ভাড়া": ("costo", "tariffa"),
    "নিবন্ধন": ("registrazione", "iscrizione"),
    " certificated": ("পত্র", "certificate",),
    # Arabic
    "শقة": ("appartamento",),
    "বিত": ("casa", "villa"),
    "জওয়ান স্কিপার্ট": ("passaporto",),
    " ডকুমেন্টো": ("documento",),
    " আইন": ("legge",),
    "রম": ("numero",),
    "তরিখ": ("data",),
    "থমিন": ("costo", "prezzo"),
    "মজানু": ("gratuito",),
    "এ প্রসjár": ("procedura", " pratiche",),
    "পuesto": ("indirizzo",),
    "ফোন": ("telefono",),
    "ইমেল": ("email",),
    # Chinese (CJK)
    "護照": ("passaporto",),
    "居住證": ("certificato di residenza",),
    "辦理": ("fare", "procedura",),
    "費用": ("costo", "tariffa"),
    "免費": ("gratuito",),
    "文件": ("documento",),
    "辦事大廳": ("Sportello",),
    "登記": ("iscrizione", "registrazione"),
    "身份證": ("carta d'identità",),
    "地址": ("indirizzo",),
    "電話": ("telefono",),
    "電子郵件": ("email",),
}


def _tokenize(text: str):
    return [
        token
        for token in _TOKEN_RE.findall(_clean_document(text).lower())
        if len(token) > 1 and token not in _STOPWORDS
    ]


def _glossary_terms(query: str):
    terms = []
    for token in _tokenize(query):
        # Controlla prima il glossario inglese-italiano, poi quello multilingue.
        for source in (_EN_IT_GLOSSARY, _IT_MULTILINGUAL_GLOSSARY):
            for italian in source.get(token, ()):
                if italian not in terms:
                    terms.append(italian)
    return terms


def _glossary_query(query: str) -> str | None:
    """Termini italiani ricavati dal solo glossario interno, o None."""
    terms = _glossary_terms(query)
    return " ".join(terms) if terms else None


def _query_tokens(query: str, italian: str | None = None):
    tokens = _tokenize(query)
    if italian is None:
        italian = translate_to_italian(query) or _glossary_query(query)
    if italian:
        for token in _tokenize(italian):
            if token not in tokens:
                tokens.append(token)
    return tokens


def _rerank_query(query: str, italian: str | None = None) -> str | None:
    """Testo italiano per il rerank: traduzione, o domanda più glossario."""
    if italian:
        return italian
    glossary = _glossary_query(query)
    if not glossary:
        return None
    return f"{query} {glossary}"


class _BM25Index:
    def __init__(self, ids, documents, metadatas):
        self.ids = ids
        self.documents = documents
        self.metadatas = metadatas
        self.tokens = [
            _tokenize(_record_text(document, metadata))
            for document, metadata in zip(documents, metadatas)
        ]
        self.term_frequencies = [Counter(tokens) for tokens in self.tokens]
        self.doc_lengths = [len(tokens) for tokens in self.tokens]
        self.total_documents = len(documents)
        self.average_length = (
            sum(self.doc_lengths) / self.total_documents
            if self.total_documents
            else 0.0
        )
        self.document_frequencies = Counter()
        for tokens in self.tokens:
            self.document_frequencies.update(set(tokens))

    def search(self, query: str, limit: int, italian: str | None = None):
        query_tokens = _query_tokens(query, italian)
        if not query_tokens or not self.total_documents:
            return []

        k1 = 1.5
        b = 0.75
        scores = []

        for index in range(self.total_documents):
            score = 0.0
            length = self.doc_lengths[index]
            for token in query_tokens:
                frequency = self.term_frequencies[index].get(token, 0)
                if not frequency:
                    continue
                document_frequency = self.document_frequencies.get(token, 0)
                inverse_document_frequency = math.log(
                    1
                    + (
                        self.total_documents
                        - document_frequency
                        + 0.5
                    )
                    / (document_frequency + 0.5)
                )
                length_ratio = (
                    length / self.average_length
                    if self.average_length
                    else 0.0
                )
                denominator = frequency + k1 * (
                    1 - b + b * length_ratio
                )
                score += (
                    inverse_document_frequency
                    * frequency
                    * (k1 + 1)
                    / denominator
                )
            if score > 0:
                scores.append((score, index))

        scores.sort(reverse=True)
        return [
            {
                "id": self.ids[index],
                "document": self.documents[index],
                "metadata": self.metadatas[index],
                "distance": None,
            }
            for _score, index in scores[:limit]
        ]


def _get_lexical_index(collection):
    global _lexical_index, _lexical_index_size

    size = collection.count()
    if _lexical_index is None or _lexical_index_size != size:
        data = collection.get(include=["documents", "metadatas"])
        _lexical_index = _BM25Index(
            data["ids"],
            data.get("documents") or [],
            data.get("metadatas") or [],
        )
        _lexical_index_size = size
    return _lexical_index


def _dedupe_key(metadata):
    kind = metadata.get("type")
    if kind == "regulation":
        return (
            "regulation",
            metadata.get("regulation_type"),
            metadata.get("regulation_number"),
            metadata.get("regulation_date"),
            metadata.get("article"),
        )
    if kind == "needed_document":
        return ("needed_document", metadata.get("document_name"))
    return (
        "service",
        metadata.get("service"),
        metadata.get("section"),
        metadata.get("chunk_index"),
    )


def _dedupe_records(records):
    seen = set()
    unique = []
    for record in records:
        key = _dedupe_key(record["metadata"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(record)
    return unique


def _reciprocal_rank_fusion(*ranked_lists):
    scores: dict[str, float] = {}
    records = {}

    for ranked in ranked_lists:
        for rank, record in enumerate(ranked, start=1):
            record_id = record["id"]
            scores[record_id] = scores.get(record_id, 0.0) + 1 / (RRF_K + rank)
            records.setdefault(record_id, record)

    return sorted(
        records.values(),
        key=lambda record: scores[record["id"]],
        reverse=True,
    )


def _get_cross_encoder():
    global _cross_encoder, _cross_encoder_failed

    if not RERANK_ENABLED or _cross_encoder_failed:
        return None
    if _cross_encoder is None:
        try:
            from sentence_transformers import CrossEncoder

            _cross_encoder = CrossEncoder(RERANK_MODEL)
        except Exception as exc:
            _cross_encoder_failed = True
            print(
                f"[rag] Reranker non disponibile ({RERANK_MODEL}): {exc}",
                file=sys.stderr,
            )
            return None
    return _cross_encoder


def _rerank(question: str, records, limit: int, italian: str | None = None):
    if limit <= 0 or not records:
        return []

    cross_encoder = _get_cross_encoder()
    if cross_encoder is None:
        return records[:limit]

    def score(query_text: str):
        pairs = [
            (query_text, _record_text(record["document"], record["metadata"]))
            for record in records
        ]
        try:
            scores = cross_encoder.predict(
                pairs,
                batch_size=32,
                show_progress_bar=False,
            )
        except Exception as exc:
            print(
                f"[rag] Errore durante il rerank, uso l'ordine RRF: {exc}",
                file=sys.stderr,
            )
            return None
        return sorted(
            zip(scores, records),
            key=lambda item: float(item[0]),
            reverse=True,
        )

    ranked = score(question)
    if ranked is None:
        return records[:limit]

    if MIN_RERANK_SCORE is not None and not any(
        float(item[0]) >= MIN_RERANK_SCORE for item in ranked
    ):
        # Nessun documento pertinente per la domanda così com'è scritta:
        # succede con domande in inglese, dove il reranker confronta parole
        # inglesi con documenti italiani. Riprova con la domanda tradotta in
        # italiano (LibreTranslate, o glossario se il servizio non risponde),
        # invece di rispondere "non lo so".
        translated = _rerank_query(question, italian)
        if translated:
            retried = score(translated)
            if retried is not None:
                ranked = retried

    if MIN_RERANK_SCORE is not None:
        ranked = [
            item
            for item in ranked
            if float(item[0]) >= MIN_RERANK_SCORE
        ]
        if not ranked:
            return []
    if RERANK_SCORE_MARGIN > 0 and ranked:
        best_score = float(ranked[0][0])
        margin = min(
            RERANK_SCORE_MARGIN,
            max(RERANK_SCORE_MARGIN_MIN, 0.7 * max(best_score, 0.0)),
        )
        ranked = [
            item
            for item in ranked
            if float(item[0]) >= best_score - margin
        ]
    return [record for _score, record in ranked[:limit]]


def query_collection(question, n_results=DEFAULT_N_RESULTS):
    collection = comune_roma_collection
    if collection.count() == 0:
        return [], []

    # Una sola traduzione per domanda: la versione italiana alimenta ricerca
    # densa, rerank e riferimenti normativi; BM25 conserva anche i token
    # originali per sigle e nomi propri.
    translated = translate_to_italian(question)
    search_text = translated or _glossary_query(question) or question

    refs = _merge_regulation_refs(question, search_text)

    exact_records = _dedupe_records(
        _exact_regulation_search(collection, search_text, refs)
    )
    exact_selected = _rerank(
        question,
        exact_records,
        min(REGULATION_QUOTA, n_results),
        italian=translated,
    )

    dense_records = _dense_search(collection, search_text, CANDIDATE_POOL)
    lexical_records = _get_lexical_index(collection).search(
        question, LEXICAL_CANDIDATES, italian=search_text
    )
    semantic_records = _dedupe_records(
        _reciprocal_rank_fusion(dense_records, lexical_records)
    )

    exact_keys = {
        _dedupe_key(record["metadata"]) for record in exact_selected
    }
    semantic_records = [
        record
        for record in semantic_records
        if _dedupe_key(record["metadata"]) not in exact_keys
    ]

    semantic_limit = max(0, n_results - len(exact_selected))
    semantic_selected = _rerank(
        question,
        semantic_records[:CANDIDATE_POOL],
        semantic_limit,
        italian=translated,
    )

    selected = exact_selected + semantic_selected

    if len(selected) < n_results:
        selected_keys = {
            _dedupe_key(record["metadata"]) for record in selected
        }
        remaining_exact = [
            record
            for record in exact_records
            if _dedupe_key(record["metadata"]) not in selected_keys
        ]
        selected.extend(
            _rerank(
                question,
                remaining_exact,
                n_results - len(selected),
                italian=translated,
            )
        )

    selected = selected[:n_results]
    documents = [_clean_document(record["document"]) for record in selected]
    metadatas = [record["metadata"] for record in selected]
    return documents, metadatas


if __name__ == "__main__":
    populate_db()
