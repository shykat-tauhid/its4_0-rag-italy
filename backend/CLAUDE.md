# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

RAG chatbot answering questions about Roma Capitale registry services (anagrafe), built on pages saved from the Roma Capitale portal. The corpus, code comments, prompts, log messages and README are in **Italian**; keep new user-facing strings and comments in Italian to match.

## Commands

Python 3.13, managed with `uv` (Windows/PowerShell environment; `.editorconfig` uses CRLF line endings).

```powershell
uv sync                                              # install deps (incl. dev group: pytest)
uv run uvicorn rag.endpoint:app --reload             # HTTP API on :8000 (/api/chat, /api/health, /docs)
uv run python src/rag/call_model_openai.py           # interactive terminal REPL (with short conversation history)
uv run python src/rag/vectorize.py                   # (re)populate the Chroma index only
uv run pytest                                        # all tests
uv run pytest tests/test_llm.py::test_name           # single test
uv run python scripts/demo_questions.py [--answers] [--language uk]   # run data/demo_questions.json (retrieved pages/forms, optionally answers)
```

The Angular frontend lives in `../frontend/frontend/`; its default origin `http://localhost:4200` is allowed via CORS. It uses the kiosk endpoints (`/api/chat/stream`, `/api/embeddable`, `/api/pdf`, `/api/print`, `/documents/*`) — see the root `CLAUDE.md` for their contract. `kiosk.py` and `printer.py` do not import `vectorize`, so their tests (`tests/test_kiosk.py`) are fast.

Note: `pyproject.toml` declares the script `rag = "rag:main"`, but `rag/__init__.py` defines no `main`, so the `rag` console script is broken.

## Configuration

Read from `.env` in the project root via `python-dotenv`. Key variables:
- `VALERIO_API` — Gemini API key (Gemini is called through its OpenAI-compatible endpoint with the `openai` client; model constant `MODEL` in `llm.py`).
- `LOCAL_MODEL_NAME` / `LOCAL_MODEL_URL` / `LOCAL_MODEL_PRIMARY` / `LOCAL_MODEL_TIMEOUT` / `LOCAL_MODEL_MAX_TOKENS` (keep `0`: Ollama counts reasoning tokens, low limits truncate answers) / `LOCAL_CONTEXT_DOCUMENTS` / `LOCAL_MODEL_API_KEY` / `LOCAL_MODEL_CONTEXT` — local OpenAI-compatible model (e.g. Ollama). `LOCAL_MODEL_CONTEXT>0` switches the local client to Ollama's native `/api/chat` (`OllamaChatClient`) because `/v1` ignores `num_ctx` and caps at 4096 tokens, which thinking models exhaust before answering (empty content, `finish_reason=length`). `LOCAL_MODEL_PRIMARY=1` swaps the order (local first, Gemini as fallback). Without `VALERIO_API` the local model is the only model.
- `GEMINI_TIMEOUT` / `GEMINI_MAX_ATTEMPTS` / `GEMINI_RETRY_DELAY` — retry/backoff tuning.
- Kiosk: `DOCUMENTS_DIR` (files served under `/documents`, default `data/docs/`), `SESSION_TTL` (seconds, default 1800), `FETCH_TIMEOUT`; printer: `TOTEM_PRINTER_ADDRESS` (Bluetooth address, default `B7F5E10BBCFE`, resolved to a COM port via the Windows registry `BTHENUM` keys), `TOTEM_PRINTER_PORT` (explicit COM port, skips lookup), `TOTEM_PRINTER_DOTS` (print width in dots, default 1728), `TOTEM_PRINTER_FEED`, `TOTEM_PRINTER_TIMEOUT`.
- `ANGULAR_ORIGINS` (CORS, comma-separated), `RESET_CHROMA=1` (rebuild index at startup), `HF_HUB_OFFLINE=1` (offline with cached models).
- `EMBEDDING_MODEL` (default `intfloat/multilingual-e5-base`; must be an e5-family model because of the `passage: `/`query: ` prefixes). Changing it triggers an automatic reindex via the fingerprint.
- Retrieval tuning env vars in `vectorize.py`: `CANDIDATE_POOL`, `LEXICAL_CANDIDATES`, `REGULATION_QUOTA`, `RERANK_MODEL` (set to `off`/`0` to disable), `RERANK_SCORE_MARGIN`, `MIN_RERANK_SCORE`, `MAX_DENSE_DISTANCE`, etc.

Many module-level constants are read from env **at import time**; tests override them with `monkeypatch.setattr(module, "CONST", ...)`.

## Architecture

Request flow: `endpoint.py` (FastAPI) or `call_model_openai.py` (REPL) → `vectorize.query_collection()` → `llm.ask()`.

- **Corpus** (`corpus.py`) — `data/sources.json` lists every file in `data/docs/` with `id`, `title`, `kind` (`pagina` = Markdown page of the portal, indexed; `modulo`/`guida` = PDF, only the title is indexed), `file`, `url` (original portal page) and, for pages, `forms` (ids of linked forms). `load_corpus()` validates it (missing files, unknown form ids → `CorpusError` at startup) and strips the portal's trailing boilerplate ("Ti è stata utile questa pagina?") and inline HTML tags. `data/demo_questions.json` holds multilingual test questions with expected behaviour (`meaning`).
- **Indexing** (`vectorize.py`) — Runs heavy work at import: loads the `intfloat/multilingual-e5-base` embedder (with `passage: `/`query: ` prefixes), opens the persistent Chroma DB at `src/chromadb/` (collection `comune_roma`), and auto-drops/rebuilds it when the fingerprint (hash of `INDEX_VERSION`, chunking params, embedding model and the whole loaded corpus, page text included) changes. So editing anything in `data/` triggers a reindex automatically; bump `INDEX_VERSION` when changing chunking/document-building logic that the fingerprint does not capture. Pages are chunked by Markdown headings (`#`…`######`, plus the old `_HEADING_HINTS` heuristics) and by words; metadata carries `type` (= kind), `source_id`, `service` (= page title), `section`, `chunk_index`.
- **Retrieval** (`query_collection`) — hybrid, with no machine translation (the e5 embedder is multilingual): the question is enriched with Italian terms from `_EN_IT_GLOSSARY`/`_IT_MULTILINGUAL_GLOSSARY`; regulation references extracted by regex (e.g. "DPR 445/2000", from the glossary-enriched text) are looked up as `number/year` substrings in chunk text (`where_document`) and get a reserved quota (`REGULATION_QUOTA`); dense Chroma search + in-memory BM25 (`_BM25Index`, uses original + glossary tokens) are fused with RRF, deduped, then reranked by a sentence-transformers cross-encoder with score thresholds. Returns `(documents, metadatas)` (plus the best rerank score with `with_score=True`); empty result → `NO_INFORMATION_ANSWER` without calling the model. `MIN_RERANK_SCORE` (-3.5) was calibrated on `demo_questions.json`: relevant questions score above it, off-topic questions and greetings below about -4.3. Re-check it with the demo script after large corpus changes.
- **Generation** (`llm.py`) — `create_client()` / `create_fallback_client()` build primary and fallback OpenAI clients depending on env; `ask()` tries primary then fallback, with retry + exponential backoff and jitter on retryable statuses (408/409/429/5xx/timeouts) and raises `ModelUnavailableError` when all fail (API maps it to HTTP 502). Local models use a compact prompt (`LOCAL_SYSTEM_PROMPT`, fewer documents, no JSON metadata). The model is instructed to answer in the user's language; model answers are not translated. Only the fixed `NO_INFORMATION_ANSWER` is localized, from the static `NO_INFORMATION_ANSWERS` table via `no_information_answer(language)` using the kiosk language (`/api/chat/stream`); without a language (`/api/chat`, REPL) it stays Italian.
- **Translation** — LibreTranslate was removed on purpose: do not reintroduce an external translation service; improve non-Italian retrieval by extending the glossaries. The only machine translation left is for the operator's conversation PDF (`conversation_pdf.py`: original language | Italian, two columns): `llm.translate_to_italian(client, texts, fallback_client)` sends the whole conversation as a JSON array in one model call (primary, then fallback, also on malformed JSON) and is injected into `build_pdf(messages, translate)`; on failure the Italian column shows "(traduzione non disponibile)" instead of failing the PDF.

### Import quirks

Modules support both package imports (`from .llm import ...`) and flat imports (`import llm`) via `try/except ImportError`. `tests/conftest.py` puts `src/rag` on `sys.path`, so tests import modules flat (`import llm`, `import vectorize`). Preserve this dual-import pattern when adding modules that the REPL or tests import. 
Follow-up questions: the REPL and `/api/chat/stream` keep the last question and services. `kiosk.retrieve` (stream API) runs both the bare question and `last question + question` and keeps the one with the higher rerank score; the REPL only falls back to the merged query when the bare one finds nothing. `/api/chat` is stateless.
