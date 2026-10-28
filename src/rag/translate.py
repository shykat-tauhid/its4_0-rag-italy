import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

LIBRETRANSLATE_URL = os.getenv("LIBRETRANSLATE_URL", "").strip().rstrip("/")
LIBRETRANSLATE_API_KEY = os.getenv("LIBRETRANSLATE_API_KEY", "").strip()
TARGET_LANGUAGE = "it"
# Argos non ha modelli diretti X->it per tutte le lingue: quelle non coperte
# passano dall'inglese (X->en, poi en->it).
PIVOT_LANGUAGE = "en"
TIMEOUT_SECONDS = float(os.getenv("LIBRETRANSLATE_TIMEOUT", "10.0"))
MAX_CACHE_ENTRIES = 256
FAILURE_THRESHOLD = max(1, int(os.getenv("LIBRETRANSLATE_FAILURES", "3")))
COOLDOWN_SECONDS = float(os.getenv("LIBRETRANSLATE_COOLDOWN", "60"))

_cache: dict[str, str | None] = {}
_lock = threading.Lock()
_failure_reported = False
_suspension_reported = False
_failures = 0
_disabled_until = 0.0


class _PairUnavailable(Exception):
    """LibreTranslate non ha un modello per la coppia richiesta."""


def _normalize(text: str) -> str:
    return " ".join(text.split()).strip()


def _report_failure(exc: Exception) -> None:
    global _failure_reported
    if _failure_reported:
        return
    _failure_reported = True
    print(
        f"[rag] LibreTranslate non disponibile ({LIBRETRANSLATE_URL}): {exc}. "
        "Uso il glossario interno.",
        file=sys.stderr,
    )


def _record_failure(exc: Exception) -> None:
    global _failures, _disabled_until, _suspension_reported
    _failures += 1
    _report_failure(exc)
    if _failures >= FAILURE_THRESHOLD:
        _failures = 0
        _disabled_until = time.monotonic() + COOLDOWN_SECONDS
        if not _suspension_reported:
            _suspension_reported = True
            print(
                "[rag] LibreTranslate sospeso per "
                f"{COOLDOWN_SECONDS:.0f}s dopo {FAILURE_THRESHOLD} errori.",
                file=sys.stderr,
            )


def _record_success() -> None:
    global _failures, _suspension_reported
    _failures = 0
    _suspension_reported = False


def _post_json(path: str, payload: dict):
    if LIBRETRANSLATE_API_KEY:
        payload = {**payload, "api_key": LIBRETRANSLATE_API_KEY}

    request = urllib.request.Request(
        f"{LIBRETRANSLATE_URL}/{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def _request_translation(
    text: str,
    target: str = TARGET_LANGUAGE,
    source: str = "auto",
) -> str | None:
    payload = {
        "q": text,
        "source": source,
        "target": target,
        "format": "text",
    }
    try:
        data = _post_json("translate", payload)
    except urllib.error.HTTPError as exc:
        if exc.code == 400:
            raise _PairUnavailable(
                f"coppia {source}->{target} non disponibile"
            ) from exc
        raise
    return data.get("translatedText")


def _detect_language(text: str) -> str | None:
    try:
        data = _post_json("detect", {"q": text})
    except (urllib.error.URLError, OSError, ValueError):
        return None
    if isinstance(data, list) and data:
        return data[0].get("language")
    return None


def _translate_to_italian(text: str) -> str | None:
    try:
        return _request_translation(text)
    except _PairUnavailable:
        pass

    detected = _detect_language(text)
    if detected in (None, TARGET_LANGUAGE, PIVOT_LANGUAGE):
        # Italiano: nessuna traduzione necessaria. Inglese: il modello
        # en->it dovrebbe esistere, ma se manca non c'è un pivot sensato.
        raise _PairUnavailable(f"nessuna traduzione per {detected or '?'}")

    english = _normalize(_request_translation(text, target=PIVOT_LANGUAGE) or "")
    if not english:
        raise _PairUnavailable("pivot verso l'inglese non riuscito")
    return _request_translation(english, source=PIVOT_LANGUAGE)


def translate_to_italian(text: str) -> str | None:
    """Traduce `text` in italiano; None se il testo è già italiano o se il
    servizio non è configurato/raggiungibile."""
    if not LIBRETRANSLATE_URL:
        return None
    if time.monotonic() < _disabled_until:
        return None

    key = _normalize(text)
    if not key:
        return None

    with _lock:
        if key in _cache:
            return _cache[key]

    cache_result = True
    try:
        translated = _translate_to_italian(key)
    except _PairUnavailable:
        translated = None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        _record_failure(exc)
        translated = None
        # Un timeout può capitare al primo caricamento del modello: non
        # memorizzare il fallimento, così il prossimo tentativo può riuscire.
        cache_result = False
    else:
        _record_success()

    translated = _normalize(translated or "") or None
    if translated and translated.lower() == key.lower():
        translated = None

    if not cache_result:
        return translated

    with _lock:
        if len(_cache) >= MAX_CACHE_ENTRIES:
            _cache.clear()
        _cache[key] = translated
    return translated


def _translate_from_italian(text: str, target: str) -> str | None:
    try:
        return _request_translation(text, target=target, source=TARGET_LANGUAGE)
    except _PairUnavailable:
        if target == PIVOT_LANGUAGE:
            raise

    english = _normalize(
        _request_translation(text, target=PIVOT_LANGUAGE, source=TARGET_LANGUAGE)
        or ""
    )
    if not english:
        raise _PairUnavailable("pivot verso l'inglese non riuscito")
    return _request_translation(english, target=target, source=PIVOT_LANGUAGE)


def localize(text: str, question: str) -> str:
    """Traduce `text`, scritto in italiano, nella lingua di `question`.

    Serve per i messaggi fissi (per esempio "nessuna informazione") che non
    passano dal modello. Restituisce `text` invariato se la domanda è in
    italiano o se il servizio non è configurato/raggiungibile.
    """
    if not LIBRETRANSLATE_URL or time.monotonic() < _disabled_until:
        return text
    # Domanda già italiana: translate_to_italian non ha nulla da tradurre (e
    # il risultato è in cache). Evita di affidarsi al rilevamento della
    # lingua, poco affidabile sulle domande brevi.
    if translate_to_italian(question) is None:
        return text

    key = f"localize\x00{_normalize(question)}\x00{text}"
    with _lock:
        if key in _cache:
            return _cache[key] or text

    try:
        target = _detect_language(_normalize(question))
        if target in (None, TARGET_LANGUAGE):
            translated = None
        else:
            translated = _translate_from_italian(text, target)
    except _PairUnavailable:
        translated = None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        _record_failure(exc)
        return text
    else:
        _record_success()

    translated = _normalize(translated or "") or None
    with _lock:
        if len(_cache) >= MAX_CACHE_ENTRIES:
            _cache.clear()
        _cache[key] = translated
    return translated or text


def reset_cache() -> None:
    global _failures, _disabled_until, _failure_reported, _suspension_reported
    with _lock:
        _cache.clear()
    _failures = 0
    _disabled_until = 0.0
    _failure_reported = False
    _suspension_reported = False
