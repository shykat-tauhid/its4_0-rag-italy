# API per il frontend Angular

Il backend espone un'API HTTP; il frontend Angular può inviare le domande a
`POST /api/chat` e leggere la risposta JSON nel campo `answer`.

```json
{ "question": "Come posso cambiare residenza?" }
```

```json
{ "answer": "..." }
```

## Avvio in sviluppo

Configura `VALERIO_API` nell'ambiente o nel file `.env` nella directory del
progetto. L'origine Angular consentita di default è `http://localhost:4200`;
per modificarla imposta `ANGULAR_ORIGINS`. Sono accettate più origini separate
da virgola.

Avvia l'API dalla directory del progetto:

```powershell
uv sync
uv run uvicorn rag.endpoint:app --reload
```

L'endpoint è disponibile su `http://localhost:8000/api/chat`, la verifica
stato su `http://localhost:8000/api/health` e la documentazione interattiva su
`http://localhost:8000/docs`.

## Modello locale di fallback

Se Gemini non risponde dopo i retry, il backend passa a un modello locale
OpenAI-compatibile (per esempio Ollama). Configurazione nel `.env`:

```powershell
LOCAL_MODEL_NAME=gemma4:e2b
LOCAL_MODEL_URL=http://localhost:11434/v1
LOCAL_MODEL_PRIMARY=1            # modello locale primario, Gemini come riserva
LOCAL_MODEL_API_KEY=local        # solo se il server la richiede
LOCAL_MODEL_TIMEOUT=300          # secondi
LOCAL_MODEL_MAX_TOKENS=0         # 0 = nessun limite (consigliato con Ollama)
LOCAL_CONTEXT_DOCUMENTS=3
```

Con `LOCAL_MODEL_PRIMARY=1` il modello locale risponde per primo e Gemini
interviene solo se il locale fallisce. Senza quella variabile (o con `0`) vale
l'ordine inverso: Gemini primario e modello locale come riserva.

Il modello locale usa sempre un prompt ridotto (3 documenti, senza metadati
JSON) e un timeout dedicato: con il contesto completo un modello piccolo può
superare il timeout pensato per Gemini. Su questa macchina una risposta locale
richiede circa 80–90 secondi. Se nessuno dei due modelli risponde, l'API
restituisce `502`. Se `VALERIO_API` non è impostata, il modello locale diventa
il modello primario e non esiste alcuna riserva.

Non impostare `LOCAL_MODEL_MAX_TOKENS` troppo basso: Ollama conta anche i token
di ragionamento interni, quindi un limite piccolo può troncare la risposta a
metà frase. Lascia `0` e affidati a `LOCAL_MODEL_TIMEOUT`.

## Traduzione delle domande

Le domande in una lingua diversa dall'italiano vengono tradotte in italiano
prima della ricerca, perché il corpus è in italiano. La traduzione usa
LibreTranslate ed è opzionale: se `LIBRETRANSLATE_URL` non è impostata, o il
servizio non risponde entro il timeout, si usa un glossario interno.

La traduzione avviene **una sola volta per domanda** e la versione italiana
alimenta la ricerca semantica, la ricerca delle normative e il rerank; la
ricerca lessicale (BM25) usa sia il testo originale sia quello tradotto, così
sigle e nomi propri restano cercabili. I riferimenti normativi vengono estratti
da entrambe le versioni. La risposta non viene tradotta: il modello risponde
nella lingua della domanda.

Lingue supportate di default (`LIBRETRANSLATE_LANGUAGES`):
`en,it,uk,tl,bn,ar,zh` — inglese, ucraino, filippino (`tl`), bengalese, arabo
e cinese, oltre all'italiano. Argos non ha modelli diretti da tutte le lingue
verso l'italiano: per quelle coperte solo tramite inglese, `translate.py`
traduce prima in inglese (`X->en`) e poi in italiano (`en->it`).

```powershell
$env:LIBRETRANSLATE_URL="http://localhost:5000"   # istanza LibreTranslate
$env:LIBRETRANSLATE_LANGUAGES="en,it,uk,tl,bn,ar,zh"
$env:LIBRETRANSLATE_API_KEY=""                    # solo se richiesta
$env:LIBRETRANSLATE_TIMEOUT="10.0"                # secondi
```

Avvia LibreTranslate in un ambiente isolato (senza aggiungere pacchetti
all'app):

```powershell
$env:PYTHONUTF8="1"   # Windows: evita errori di encoding durante l'update modelli
uvx libretranslate --load-only en,it,uk,tl,bn,ar,zh --host 127.0.0.1 --port 5000
```

Al primo avvio scarica i modelli e può sembrare fermo per alcuni minuti. Per
preinstallare solo quelli necessari (più veloce e con meno RAM):

```powershell
uv run --with libretranslate python scripts/install_libretranslate_models.py
```

Lo script legge `LIBRETRANSLATE_LANGUAGES` e installa `X->en` per ogni lingua
extra, più `en<->it`. Se `LIBRETRANSLATE_URL` punta a `localhost`, l'API avvia
LibreTranslate automaticamente con `uvx` quando parte; in quel caso conviene
comunque lanciare il comando manualmente la prima volta, così si vede il
download dei modelli.

Imposta l'URL nel `.env`:

```powershell
LIBRETRANSLATE_URL=http://localhost:5000
LIBRETRANSLATE_LANGUAGES=en,it,uk,tl,bn,ar,zh
```

Il repo non include un `compose.yaml`: se preferisci Docker, usa l'immagine
ufficiale con `--load-only en,it,uk,tl,bn,ar,zh`. Se l'API gira in un container
diverso, usa il nome del servizio (`http://libretranslate:5000`) al posto di
`localhost`.

Evita `uv add libretranslate`: aggiunge ~170 pacchetti all'ambiente dell'app e
downgrada `numpy` e `requests`. Usa `uvx` o `uv tool install` per tenerlo
separato.

## Robustezza

- **Gemini**: timeout di 60s, fino a 3 tentativi con backoff esponenziale e
  jitter su errori transitori (429, 5xx, timeout). Se il modello resta
  irraggiungibile, `POST /api/chat` risponde `502` e il REPL continua a
  funzionare invece di terminare.
- **LibreTranslate**: timeout di 10s (il primo caricamento dei modelli può
  essere lento) e cache; dopo 3 errori consecutivi il
  servizio viene sospeso per 60s, così un traduttore spento non rallenta ogni
  domanda. In entrambi i casi si usa il glossario interno.
- Variabili di regolazione: `GEMINI_TIMEOUT`, `GEMINI_MAX_ATTEMPTS`,
  `GEMINI_RETRY_DELAY`, `LIBRETRANSLATE_FAILURES`,
  `LIBRETRANSLATE_COOLDOWN`.
- Se il totem non ha accesso a `huggingface.co` ma i modelli sono già in cache,
  imposta `HF_HUB_OFFLINE=1` per evitare i tentativi di verifica all'avvio.

I test coprono retry e circuit breaker: `uv run pytest`.
