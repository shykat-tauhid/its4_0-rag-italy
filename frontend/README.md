# Totem

Digital kiosk that helps foreign residents of Rome with the regulations and forms of the city registry office (anagrafe). The user picks a language, asks a question by voice or on a touch keyboard, and gets a written and spoken answer.

## Repository layout

| Folder                        | Content                           | Stack                    |
| ----------------------------- | --------------------------------- | ------------------------ |
| [`../backend/`](../backend/) | RAG chatbot API, PDF and printing | Python 3.13, FastAPI, uv |
| [`frontend/`](frontend/)     | Kiosk user interface              | Angular 21               |
| [`kiosk/`](kiosk/)           | Launches Chrome in kiosk mode     | PowerShell               |

## Starting the totem, step by step

All commands are for PowerShell on Windows. Paths are relative to the repository root (the folder that contains `backend/` and `frontend/`).

### 1. Prerequisites (once)

- [uv](https://docs.astral.sh/uv/) (it installs Python 3.13 by itself).
- Node.js 24 with npm.
- Google Chrome.
- A language model, at least one of:
  - a Gemini API key;
  - [Ollama](https://ollama.com/) with a chat model, e.g. `ollama pull gemma4:e4b`. Embedding models such as `bge-m3` cannot answer questions.
- For printing: the Phomemo A282M printer, paired with Windows over Bluetooth.

### 2. Configure the backend (once)

Create `backend\.env`. With Gemini:

```
VALERIO_API=your-gemini-key
```

With Ollama only (no Gemini key: the local model becomes the only model):

```
LOCAL_MODEL_NAME=gemma4:e4b
LOCAL_MODEL_URL=http://localhost:11434/v1
LOCAL_MODEL_CONTEXT=8192
```

With both, Gemini answers first and Ollama is the fallback (add `LOCAL_MODEL_PRIMARY=1` to swap them). Do not repeat the same variable twice in the file. The printer is found by its Bluetooth address; if it differs from the default, add `TOTEM_PRINTER_ADDRESS=...`, or set the port directly with `TOTEM_PRINTER_PORT=COM5`. See [`../backend/README.md`](../backend/README.md) for every option.

### 3. Install the dependencies (once, and after every update)

```powershell
cd backend
uv sync
cd ..\frontend\frontend
npm install
```

Optional but recommended: `uv add uharfbuzz` in `backend\`. Without it, Arabic and Bengali text in the printed conversation has broken letter shapes (the Italian column is always fine).

### 4. Start Ollama (only if you use it)

Ollama usually runs in the background after installation. Check it with `ollama list`; if it does not answer, start it with `ollama serve` in a separate window.

### 5. Start the backend (window 1)

```powershell
cd backend
uv run uvicorn rag.endpoint:app --reload
```

The first start downloads the embedding and rerank models and builds the search index: it takes a few minutes. Wait for `Application startup complete`, then check that http://localhost:8000/api/health returns `{"status":"ok"}`.

### 6. Start the frontend (window 2)

```powershell
cd frontend\frontend
npm start
```

Wait for the compilation to finish. During development you can stop here and open http://localhost:4200 in a normal browser.

### 7. Open the kiosk

Double-click [`kiosk/avvia-totem.bat`](kiosk/avvia-totem.bat), or run:

```powershell
.\frontend\kiosk\avvia-totem.bat
```

Chrome opens full screen on `http://localhost:4200/`, with a dedicated profile in `%LOCALAPPDATA%\TotemKiosk`. Do not use F11 instead: in `--kiosk` mode there is no exit button on the touch screen.

### Stopping

- Kiosk: `Alt+F4`.
- Backend and frontend: `Ctrl+C` in their windows.

### If something does not work

| Symptom                                            | Check                                                                                          |
| -------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| The chat answers "connection error"                | The backend window: the backend must be running, and Ollama reachable or the Gemini key valid. |
| The backend stops at startup about `VALERIO_API` | `backend\.env` has neither a Gemini key nor `LOCAL_MODEL_NAME` + `LOCAL_MODEL_URL`.      |
| Empty or cut answers with Ollama                   | Raise `LOCAL_MODEL_CONTEXT` (e.g. `16384`).                                                |
| Printing fails                                     | The printer is on, paired over Bluetooth, and its address or COM port matches `.env`.        |
| Answers take minutes                               | Normal on a PC without GPU running a local model.                                              |

## Printing

Printing never goes through the browser's print dialog: the backend sends the pages to the kiosk's printer, a Phomemo A282M paired over Bluetooth. It finds the printer's serial port by its Bluetooth address (`TOTEM_PRINTER_ADDRESS`, default `B7F5E10BBCFE`) and sends it the pages as raster images.

- **Forms**: the print button of the PDF viewer.
- **Conversation**: the "Stampa conversazione" button in the chat prints a two-column PDF for the office operator, with the user's language on the left and the Italian translation on the right. The language model writes the translation, so with a local model on a PC without GPU it takes a couple of minutes.

See [`frontend/README.md`](frontend/README.md) for the frontend build and test commands.
