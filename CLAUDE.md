# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

RAG chatbot answering questions about Roma Capitale registry services (anagrafe) and the related regulations. The corpus, code comments, prompts, log messages and README are in **Italian**; keep new user-facing strings and comments in Italian to match.

## Commands

Python 3.13, managed with `uv` (Windows/PowerShell environment; `.editorconfig` uses CRLF line endings).

```powershell
uv sync                                              # install deps (incl. dev group: pytest)
uv run uvicorn rag.endpoint:app --reload             # HTTP API on :8000 (/api/chat, /api/health, /docs)
uv run python src/rag/call_model_openai.py           # interactive terminal REPL (with short conversation history)
uv run python src/rag/vectorize.py                   # (re)populate the Chroma index only
uv run pytest                                        # all tests
uv run pytest tests/test_llm.py::test_name           # single test
```

The Angular frontend that calls `POST /api/chat` (`{"question": ...}` → `{"answer": ...}`) is not in this repo; its default origin `http://localhost:4200` is allowed via CORS.

Note: `pyproject.toml` declares the script `rag = "rag:main"`, but `rag/__init__.py` defines no `main`, so the `rag` console script is broken.

## Configuration

Read from `.env` in the project root via `python-dotenv`. Key variables:
- `VALERIO_API` — Gemini API key (Gemini is called through its OpenAI-compatible endpoint with the `openai` client; model constant `MODEL` in `llm.py`).
- `LOCAL_MODEL_NAME` / `LOCAL_MODEL_URL` / `LOCAL_MODEL_PRIMARY` / `LOCAL_MODEL_TIMEOUT` / `LOCAL_MODEL_MAX_TOKENS` (keep `0`: Ollama counts reasoning tokens, low limits truncate answers) / `LOCAL_CONTEXT_DOCUMENTS` / `LOCAL_MODEL_API_KEY` / `LOCAL_MODEL_CONTEXT` — local OpenAI-compatible model (e.g. Ollama). `LOCAL_MODEL_CONTEXT>0` switches the local client to Ollama's native `/api/chat` (`OllamaChatClient`) because `/v1` ignores `num_ctx` and caps at 4096 tokens, which thinking models exhaust before answering (empty content, `finish_reason=length`). `LOCAL_MODEL_PRIMARY=1` swaps the order (local first, Gemini as fallback). Without `VALERIO_API` the local model is the only model.
- `LIBRETRANSLATE_URL` / `LIBRETRANSLATE_LANGUAGES` (default `en,it,uk,tl,bn,ar,zh`) / `LIBRETRANSLATE_TIMEOUT` / `LIBRETRANSLATE_FAILURES` / `LIBRETRANSLATE_COOLDOWN`.
- `GEMINI_TIMEOUT` / `GEMINI_MAX_ATTEMPTS` / `GEMINI_RETRY_DELAY` — retry/backoff tuning.
- `ANGULAR_ORIGINS` (CORS, comma-separated), `RESET_CHROMA=1` (rebuild index at startup), `HF_HUB_OFFLINE=1` (offline with cached models).
- `EMBEDDING_MODEL` (default `intfloat/multilingual-e5-base`; must be an e5-family model because of the `passage: `/`query: ` prefixes). Changing it triggers an automatic reindex via the fingerprint.
- Retrieval tuning env vars in `vectorize.py`: `CANDIDATE_POOL`, `LEXICAL_CANDIDATES`, `REGULATION_QUOTA`, `RERANK_MODEL` (set to `off`/`0` to disable), `RERANK_SCORE_MARGIN`, `MIN_RERANK_SCORE`, `MAX_DENSE_DISTANCE`, etc.

Many module-level constants are read from env **at import time**; tests override them with `monkeypatch.setattr(module, "CONST", ...)`.

## Architecture

Request flow: `endpoint.py` (FastAPI) or `call_model_openai.py` (REPL) → `vectorize.query_collection()` → `llm.ask()`.

- **Corpus** — `data/anagrafe.py` exports `docs`, a Python list of service dicts (description, needed_docs, regulations with articles). It is the single source of truth; there is no other ingestion step.
- **Indexing** (`vectorize.py`) — Runs heavy work at import: loads the `intfloat/multilingual-e5-base` embedder (with `passage: `/`query: ` prefixes), opens the persistent Chroma DB at `src/chromadb/` (collection `comune_roma`), and auto-drops/rebuilds it when the fingerprint (hash of `INDEX_VERSION`, chunking params, embedding model and the whole `docs` payload) changes. So editing `data/anagrafe.py` triggers a reindex automatically; bump `INDEX_VERSION` when changing chunking/document-building logic that the fingerprint does not capture. Services are chunked by words with section headings; each regulation article becomes its own document.
- **Retrieval** (`query_collection`) — hybrid: translate the question to Italian once (`translate.py`), fall back to `_EN_IT_GLOSSARY`/`_IT_MULTILINGUAL_GLOSSARY` terms; exact regulation lookup from regex-extracted references (e.g. "D.L. 5/2012", from both original and Italian text) gets a reserved quota (`REGULATION_QUOTA`); dense Chroma search + in-memory BM25 (`_BM25Index`, uses original + Italian tokens) are fused with RRF, deduped, then reranked by a sentence-transformers cross-encoder with score thresholds. Returns `(documents, metadatas)`; empty result → `NO_INFORMATION_ANSWER` without calling the model.
- **Generation** (`llm.py`) — `create_client()` / `create_fallback_client()` build primary and fallback OpenAI clients depending on env; `ask()` tries primary then fallback, with retry + exponential backoff and jitter on retryable statuses (408/409/429/5xx/timeouts) and raises `ModelUnavailableError` when all fail (API maps it to HTTP 502). Local models use a compact prompt (`LOCAL_SYSTEM_PROMPT`, fewer documents, no JSON metadata). The model is instructed to answer in the user's language; model answers are not translated. Only the fixed `NO_INFORMATION_ANSWER` is translated into the question's language via `translate.localize()` (API and REPL); Italian questions are detected by `translate_to_italian()` returning `None`, not by language detection.
- **Translation** (`translate.py`) — optional LibreTranslate client using stdlib `urllib`; detects language, translates directly to `it` or pivots via `en`; LRU-style cache plus a circuit breaker (opens after N consecutive failures for a cooldown). Disabled when `LIBRETRANSLATE_URL` is empty. `start_libretranslate.py` is used by the API lifespan to auto-launch LibreTranslate via `uvx` when the URL is local (it defaults to localhost even if unset — a known inconsistency). Never `uv add libretranslate` (pulls ~170 packages and downgrades numpy/requests); `scripts/install_libretranslate_models.py` preinstalls the needed Argos models via `uv run --with libretranslate`.

### Import quirks

Modules support both package imports (`from .llm import ...`) and flat imports (`import llm`) via `try/except ImportError`. `tests/conftest.py` puts `src/rag` on `sys.path`, so tests import modules flat (`import llm`, `import translate`). Preserve this dual-import pattern when adding modules that the REPL or tests import. `vectorize.py` adds the project root to `sys.path` so `data.anagrafe` resolves.

The HTTP API is stateless (no conversation history); only the REPL keeps history and "remembers" the last retrieved services for follow-up questions.
