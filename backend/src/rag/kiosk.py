"""Supporto alle API usate dal frontend del totem.

Sessioni di conversazione, fonti e moduli da mostrare sotto la risposta, e
download controllati di pagine e PDF esterni (il browser del totem non può
leggerli direttamente).
"""

import ipaddress
import os
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from pathlib import Path

try:
    from .corpus import PAGE_KIND
except ImportError:  # importato come modulo piatto (test)
    from corpus import PAGE_KIND

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Pagine Markdown, moduli e guide PDF del corpus, serviti sotto /documents.
DOCUMENTS_DIR = Path(os.getenv("DOCUMENTS_DIR", "").strip() or PROJECT_ROOT / "data" / "docs")

MAX_HISTORY_TURNS = 2
SESSION_TTL_SECONDS = float(os.getenv("SESSION_TTL", "1800"))
MAX_SESSIONS = 500

FETCH_TIMEOUT_SECONDS = float(os.getenv("FETCH_TIMEOUT", "10"))
MAX_PDF_BYTES = 15 * 1024 * 1024
EMBEDDABLE_CACHE_SECONDS = 3600
USER_AGENT = "Mozilla/5.0 (TotemAnagrafe)"


# --- Sessioni -------------------------------------------------------------


class Session:
    def __init__(self):
        self.history: list[dict] = []
        self.last_question: str | None = None
        self.last_services: list[str] = []
        self.touched = time.monotonic()

    def remember(self, question: str, answer: str) -> None:
        self.history.append({"role": "user", "content": question})
        self.history.append({"role": "assistant", "content": answer})
        del self.history[: -MAX_HISTORY_TURNS * 2]


class SessionStore:
    """Sessioni in memoria, una per `session_id` del frontend.

    Il totem è uno solo e le conversazioni sono brevi: basta un dizionario con
    scadenza, senza database.
    """

    def __init__(self, ttl: float = SESSION_TTL_SECONDS, limit: int = MAX_SESSIONS):
        self.ttl = ttl
        self.limit = limit
        self._sessions: OrderedDict[str, Session] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, session_id: str | None) -> Session:
        if not session_id:
            return Session()
        now = time.monotonic()
        with self._lock:
            for key in [k for k, s in self._sessions.items() if now - s.touched > self.ttl]:
                del self._sessions[key]
            session = self._sessions.pop(session_id, None) or Session()
            session.touched = now
            self._sessions[session_id] = session
            while len(self._sessions) > self.limit:
                self._sessions.popitem(last=False)
            return session


def retrieve(query, question: str, session: Session, n_results: int):
    """Recupera i documenti tenendo conto della domanda precedente.

    Una domanda di seguito ("costa qualcosa?") da sola recupera poco o il tema
    sbagliato: se c'è una domanda precedente si prova anche la domanda unita a
    quella e si tiene il risultato con il punteggio del reranker più alto.
    Senza punteggi (reranker spento) si usa l'unione solo se la domanda da
    sola non trova nulla. Restituisce (documenti, metadati, unita_alla_precedente).
    """
    documents, metadatas, score = query(question, n_results=n_results, with_score=True)
    merged = False
    if session.last_question:
        merged_documents, merged_metadatas, merged_score = query(
            f"{session.last_question} {question}", n_results=n_results, with_score=True
        )
        better = (
            not documents
            or (score is not None and merged_score is not None and merged_score > score)
        )
        if merged_documents and better:
            documents, metadatas, merged = merged_documents, merged_metadatas, True

    if session.last_services:
        order = {service: index for index, service in enumerate(session.last_services)}
        paired = sorted(
            zip(documents, metadatas),
            key=lambda item: order.get(item[1].get("service"), len(order)),
        )
        documents = [document for document, _ in paired]
        metadatas = [metadata for _, metadata in paired]
    return documents, metadatas, merged


def services_of(metadatas) -> list[str]:
    services = []
    for metadata in metadatas:
        service = metadata.get("service")
        if service and service not in services:
            services.append(service)
    return services


# --- Fonti e moduli -------------------------------------------------------


def build_sources(metadatas, corpus_by_id: dict[str, dict], documents_url: str):
    """Fonti (pagine del portale) e moduli PDF per l'evento `sources`.

    Una fonte per pagina, anche se ne sono stati recuperati più chunk; `copy`
    è il testo salvato della pagina, che il totem mostra quando il portale non
    si lascia aprire in un frame. I moduli sono quelli collegati alle pagine
    (`forms` in sources.json) più quelli recuperati direttamente, serviti in
    locale così si possono visualizzare e stampare.
    """
    base = documents_url.rstrip("/")

    def local_url(item):
        return f"{base}/{urllib.parse.quote(item['file'])}"

    sources: list[dict] = []
    forms: list[dict] = []
    seen_pages: set[str] = set()
    seen_forms: set[str] = set()

    def add_form(form_id):
        item = corpus_by_id.get(form_id)
        if item is None or form_id in seen_forms:
            return
        seen_forms.add(form_id)
        forms.append({"id": form_id, "title": item["title"], "url": local_url(item)})

    for metadata in metadatas:
        item = corpus_by_id.get(metadata.get("source_id") or "")
        if item is None:
            continue
        if item["kind"] == PAGE_KIND:
            if item["id"] in seen_pages:
                continue
            seen_pages.add(item["id"])
            sources.append(
                {
                    "number": len(sources) + 1,
                    "title": item["title"],
                    "kind": item["kind"],
                    "url": item["url"] or local_url(item),
                    "copy": local_url(item),
                }
            )
            for form_id in item["forms"]:
                add_form(form_id)
        else:
            add_form(item["id"])

    return sources, forms


# --- Download di pagine e PDF esterni -------------------------------------


class BlockedUrlError(ValueError):
    """URL non consentito: schema diverso da http/https o indirizzo interno."""


def check_public_url(url: str) -> None:
    """Accetta solo URL http(s) verso indirizzi pubblici.

    Il backend scarica pagine per conto del browser: senza questo controllo
    potrebbe essere usato per leggere servizi della rete locale.
    """
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise BlockedUrlError(f"URL non consentito: {url}")
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or None)
    except OSError as exc:
        raise BlockedUrlError(f"Host non risolvibile: {parsed.hostname}") from exc
    for info in infos:
        address = ipaddress.ip_address(info[4][0].split("%")[0])
        if not address.is_global:
            raise BlockedUrlError(f"Indirizzo non pubblico: {address}")


class _CheckedRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_CheckedRedirects())


def open_url(url: str, timeout: float = FETCH_TIMEOUT_SECONDS):
    check_public_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return _opener.open(request, timeout=timeout)


def frame_allowed(headers) -> bool:
    """False se la pagina vieta di essere mostrata in un frame di un altro sito."""
    x_frame = (headers.get("X-Frame-Options") or "").strip().lower()
    if x_frame in ("deny", "sameorigin") or x_frame.startswith("allow-from"):
        return False
    for policy in headers.get_all("Content-Security-Policy") or []:
        for directive in policy.split(";"):
            parts = directive.strip().split()
            if parts and parts[0].lower() == "frame-ancestors":
                # Senza '*' il totem (localhost) non è quasi mai tra le origini ammesse.
                return "*" in parts[1:]
    return True


_embeddable_cache: dict[str, tuple[float, bool]] = {}
_embeddable_lock = threading.Lock()


def is_embeddable(url: str) -> bool:
    now = time.monotonic()
    with _embeddable_lock:
        cached = _embeddable_cache.get(url)
        if cached and now - cached[0] < EMBEDDABLE_CACHE_SECONDS:
            return cached[1]
    try:
        with open_url(url) as response:
            result = frame_allowed(response.headers)
    except BlockedUrlError:
        return False
    except (urllib.error.URLError, OSError, ValueError):
        return False  # risultato non salvato: il sito potrebbe tornare raggiungibile
    with _embeddable_lock:
        if len(_embeddable_cache) > 1000:
            _embeddable_cache.clear()
        _embeddable_cache[url] = (now, result)
    return result


class NotAPdfError(ValueError):
    pass


def download_pdf(url: str, limit: int = MAX_PDF_BYTES) -> bytes:
    with open_url(url) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise NotAPdfError("PDF troppo grande.")
    if not data.lstrip()[:5].startswith(b"%PDF"):
        raise NotAPdfError("Il file non è un PDF.")
    return data
