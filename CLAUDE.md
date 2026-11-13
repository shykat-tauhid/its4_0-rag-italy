# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

"Totem": a touch-screen kiosk that helps foreign residents of Rome with registry-office (anagrafe) procedures. The user picks a language, asks a question (voice or on-screen keyboard) and gets a written and spoken answer from a RAG chatbot. Code comments, prompts, logs and corpus are mostly in **Italian**; keep new user-facing strings and comments in Italian to match.

Two independent projects, no root build tooling and no git repo at the root:

| Folder | Stack | Notes |
| --- | --- | --- |
| `backend/` | Python 3.13, `uv`, FastAPI, Chroma, sentence-transformers, OpenAI client (Gemini / Ollama) | Has its own detailed `backend/CLAUDE.md` (config env vars, retrieval pipeline, import quirks) — read it before touching the backend. |
| `frontend/frontend/` | Angular 21 (standalone components, signals), Vitest | The real Angular app is nested one level deeper than `frontend/`. |
| `frontend/kiosk/` | PowerShell | Launches Chrome in `--kiosk` mode. |

Windows/PowerShell environment.

## Commands

Backend (from `backend/`):

```powershell
uv sync
uv run uvicorn rag.endpoint:app --reload     # API on :8000
uv run pytest                                # all tests
uv run pytest tests/test_llm.py::test_name   # single test
```

Frontend (from `frontend/frontend/`):

```powershell
npm install
npm start                                    # ng serve on :4200
npm run build                                # production build -> dist/
npm test                                     # ng test (Vitest, jsdom)
npx ng test --include src/app/chatbot.component/chatbot.component.spec.ts   # single spec file
```

Run `ng test` from a path with an upper-case drive letter (`C:\...`): from `c:\...` Vitest loads twice and every spec fails with "Vitest failed to find the runner".

Prettier config: `printWidth: 100`, `singleQuote: true`.

Kiosk: run `frontend/kiosk/avvia-totem.bat` (Chrome kiosk on `http://localhost:4200/`, dedicated profile in `%LOCALAPPDATA%\TotemKiosk`; exit with Alt+F4).

## Frontend ↔ backend contract

The frontend base URL is hard-coded in `frontend/frontend/src/app/api.config.ts` (`http://localhost:8000`); the backend's CORS allow-list comes from `ANGULAR_ORIGINS` (default `http://localhost:4200`). Kiosk endpoints live in `backend/src/rag/endpoint.py`, with their logic in `kiosk.py` and `printer.py`:

| Endpoint | Contract |
| --- | --- |
| `POST /api/chat/stream` | `{message, language, service, session_id}` → NDJSON lines `{type: "token", text}`, `{type: "sources", sources, forms}`, `{type: "done"}` or `{type: "error", message}`. The answer is sent as a single `token` event (no token-level streaming). History and follow-up handling are kept in memory per `session_id` (`kiosk.SessionStore`), mirroring the REPL. `service` is accepted but unused (the corpus covers only anagrafe). |
| `GET /api/embeddable?url=` | `{embeddable: bool}` from `X-Frame-Options` / CSP `frame-ancestors`. |
| `GET /api/pdf?url=` | Proxies an external PDF (≤15 MB, must start with `%PDF`). |
| `POST /api/print` | `{pages: [dataURL…]}` → 204, or 503 if the printer is unreachable. ESC/POS raster (`GS v 0`) over the Bluetooth serial port of the Phomemo A282M. |
| `GET /documents/<file>` | Corpus files from `backend/data/docs/` (`DOCUMENTS_DIR`). Each page source gets `url` = original portal page and `copy` = its saved Markdown here (shown when the portal refuses frames); `forms` are the page's linked PDFs (`forms` in `data/sources.json`) served locally, so the viewer can render and print them without `/api/pdf`. |
| `POST /api/conversation/pdf` | `{messages: [{role, content}…]}` → PDF for the office operator: user's language on the left, Italian translation (done by the chat model, one call per conversation) on the right. Used by the chat's "Stampa conversazione" button, which renders the pages with pdf.js (`renderPdfData`) and sends them to `/api/print`. |
| `POST /api/chat`, `GET /api/health` | Older stateless endpoints, not used by the frontend. |

`/api/embeddable` and `/api/pdf` fetch arbitrary URLs on behalf of the browser, so `kiosk.check_public_url` rejects non-http(s) schemes and non-public IPs (redirects included). Keep that check on any new server-side fetch.

## Frontend architecture

- **No router**: `app.routes.ts` is empty. Navigation is a step state machine in `AppStateService` (`currentStep` signal: `welcome → language → choice → services → chatbot | webapp`), together with `selectedLanguage`, `activeService` (`anagrafica` | `affitto`), `chatMessages` and a per-session `sessionId`. Components render based on these signals.
- **i18n**: not Angular i18n. All UI strings live in `src/assets/translation.json` (key → language → text), loaded at startup and read via `state.t(key)`. Arabic switches the layout to RTL via `state.dir()`.
- **Web app (`public/webapp/`)**: a separate vanilla-JS site (offices/CAF map, own `i18n.js`, `accessibility.js`) served as a static asset and embedded in an iframe by `webapp.component`. It talks to the Angular shell via `postMessage` (`tramite:back`, `tramite:lang`, `tramite:open`). Its office data is pre-downloaded from OpenStreetMap by `public/webapp/scripts/aggiorna-dati.mjs` into `dati/sedi-precaricate.js`.
- **Link viewer**: the kiosk has no tabs or browser chrome, so external links/sources open in an in-app viewer (`link-viewer.component`, `pdf-pages.ts` using `pdfjs-dist`), with a saved text copy as fallback when a site can't be embedded. Printing goes through the backend, never the browser print dialog.
- **Virtual keyboard**: `simple-keyboard` with per-language layouts, plus a custom Pinyin IME for Chinese (`pinyin-ime.ts`, dictionary `public/ime/zh-pinyin.txt` generated by `scripts/build-pinyin-dict.mjs`).
- **Accessibility**: `AccessibilityService` + `accessibility.css` (incl. OpenDyslexic font). `storage.ts` wraps `localStorage` in try/catch — use it instead of `localStorage` directly.
- Production budgets in `angular.json` are tight (component styles warn at 4kB, error at 8kB).
