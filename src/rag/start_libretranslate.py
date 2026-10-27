#!/usr/bin/env python
# encoding: utf-8
"""Avvio automatico di un'istanza locale di LibreTranslate.

Usa `uvx` per eseguire LibreTranslate in un ambiente isolato: non installa
nulla dentro `.venv`. Se il servizio risponde già su `/health` non fa nulla.
"""

import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_LANGUAGES = "en,it,uk,tl,bn,ar,zh"
LIBRETRANSLATE_URL = os.getenv("LIBRETRANSLATE_URL", "http://localhost:5000").rstrip("/")
LIBRETRANSLATE_LANGUAGES = os.getenv(
    "LIBRETRANSLATE_LANGUAGES", DEFAULT_LANGUAGES
).strip()
LIBRETRANSLATE_TIMEOUT = float(os.getenv("LIBRETRANSLATE_TIMEOUT", "2.0"))
LIBRETRANSLATE_MAX_START_ATTEMPTS = int(
    os.getenv("LIBRETRANSLATE_MAX_START_ATTEMPTS", "150")
)
LIBRETRANSLATE_START_DELAY = float(os.getenv("LIBRETRANSLATE_START_DELAY", "0.2"))
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def is_service_running(
    url: str = LIBRETRANSLATE_URL,
    timeout: float = LIBRETRANSLATE_TIMEOUT,
) -> bool:
    """Verifica se LibreTranslate è già in esecuzione."""
    try:
        request = urllib.request.Request(f"{url}/health", method="GET")
        with urllib.request.urlopen(request, timeout=timeout):
            return True
    except Exception:
        return False


def _local_address():
    parsed = urlparse(LIBRETRANSLATE_URL)
    if parsed.hostname not in LOCAL_HOSTS:
        return None
    return parsed.port or 5000


def _language_list() -> list[str]:
    return [
        code.strip()
        for code in LIBRETRANSLATE_LANGUAGES.split(",")
        if code.strip()
    ]


def start_libretranslate_process() -> subprocess.Popen | None:
    """Avvia LibreTranslate via `uvx`, senza toccare l'ambiente del progetto."""
    if is_service_running():
        return None

    port = _local_address()
    if port is None:
        print(
            "[rag] LIBRETRANSLATE_URL non punta a localhost: "
            "nessun avvio automatico.",
            file=sys.stderr,
        )
        return None

    uvx = shutil.which("uvx")
    if uvx is None:
        print(
            "[rag] uvx non trovato: avvia LibreTranslate manualmente.",
            file=sys.stderr,
        )
        return None

    command = [
        uvx,
        "libretranslate",
        "--load-only",
        ",".join(_language_list()),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    print(
        "[rag] Avvio LibreTranslate "
        f"({LIBRETRANSLATE_LANGUAGES}) su 127.0.0.1:{port}...",
        file=sys.stderr,
    )
    try:
        return subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
    except OSError as exc:
        print(
            f"[rag] Impossibile avviare LibreTranslate: {exc}",
            file=sys.stderr,
        )
        return None


def wait_for_service(
    process: subprocess.Popen,
    max_wait: float = 10.0,
    check_interval: float = LIBRETRANSLATE_START_DELAY,
) -> bool:
    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline:
        if is_service_running():
            return True
        if process.poll() is not None:
            return False
        time.sleep(check_interval)
    return is_service_running()


def ensure_libretranslate_running() -> bool:
    """Assicura che LibreTranslate sia in esecuzione."""
    if is_service_running():
        return True

    process = start_libretranslate_process()
    if process is None:
        return False

    ready = wait_for_service(
        process,
        max_wait=LIBRETRANSLATE_MAX_START_ATTEMPTS
        * LIBRETRANSLATE_START_DELAY,
    )
    if not ready:
        print(
            "[rag] LibreTranslate non è ancora pronto (primo avvio o "
            "download modelli); continuo senza traduzione.",
            file=sys.stderr,
        )
    return ready
