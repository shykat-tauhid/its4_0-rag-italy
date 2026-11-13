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

## Corpus (`data/`)

- `data/sources.json`: una voce per file, con `id`, `title`, `kind`
  (`pagina`, `modulo`, `guida`), `file`, `url` (pagina originale sul portale)
  e, per le pagine, `forms` (id dei moduli collegati).
- `data/docs/`: il testo delle pagine in Markdown e i PDF di moduli e guide.
  Il backend li serve al totem sotto `/documents/`. Il totem mostra il testo
  salvato quando il portale non si lascia aprire, e visualizza e stampa i
  moduli senza scaricarli dal sito.
- `data/demo_questions.json`: domande di prova in tutte le lingue del totem.

Le pagine sono divise in chunk per titolo (`###`); la coda delle pagine del
portale ("Ti è stata utile questa pagina?") viene scartata. Dei PDF si
indicizza solo il titolo. Modificando un file in `data/` l'indice Chroma si
ricostruisce da solo al riavvio. All'avvio `sources.json` viene controllato:
un file mancante o un modulo citato ma inesistente blocca l'avvio con un
errore esplicito.

Per provare le domande di prova:

```powershell
uv run python scripts/demo_questions.py              # pagine e moduli recuperati
uv run python scripts/demo_questions.py --answers    # anche le risposte del modello
uv run python scripts/demo_questions.py --language ar
```

## API del totem

Il frontend Angular usa `POST /api/chat/stream` (risposta NDJSON con
sessione per `session_id`), `GET /api/embeddable`, `GET /api/pdf`,
`POST /api/print` e i file sotto `/documents/`. `POST /api/chat` resta
disponibile per altri client.

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
LOCAL_MODEL_CONTEXT=16384        # contesto Ollama; usa l'API nativa /api/chat
```

`LOCAL_MODEL_CONTEXT` serve con Ollama: l'endpoint OpenAI-compatibile `/v1`
ignora la dimensione del contesto e si ferma a 4096 token, che prompt e
ragionamento interno di modelli come gemma esauriscono prima della risposta
(risposta vuota). Con un valore maggiore di 0 il backend chiama l'API nativa
`/api/chat` con `num_ctx`. Lascia `0` per server OpenAI-compatibili diversi da
Ollama.

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

## Domande in altre lingue

Il corpus è in italiano, ma non c'è un servizio di traduzione automatica:
l'embedder (`intfloat/multilingual-e5-base`) è multilingue, quindi la ricerca
semantica funziona anche con domande in altre lingue. Un glossario interno
(`_EN_IT_GLOSSARY` / `_IT_MULTILINGUAL_GLOSSARY` in `vectorize.py`) aggiunge
alla domanda i termini italiani corrispondenti, usati dalla ricerca densa, da
BM25, dal rerank e dalla ricerca dei riferimenti normativi. Per migliorare il
recupero in una lingua, estendi il glossario.

La risposta non viene tradotta: il modello risponde nella lingua della domanda.
Il messaggio fisso "nessuna informazione" ha traduzioni statiche
(`NO_INFORMATION_ANSWERS` in `llm.py`) per le lingue del totem; senza lingua
indicata (`POST /api/chat`, REPL) resta in italiano.

Il PDF della conversazione (`POST /api/conversation/pdf` e uscita dal REPL) è
pensato per l'operatore dell'ufficio: ha due colonne, a sinistra domande e
risposte nella lingua dell'utente e a destra la traduzione in italiano. La
traduzione la fa lo stesso modello delle risposte (Gemini o il modello locale,
con la stessa logica primario/riserva), con una sola chiamata per l'intera
conversazione (`llm.translate_to_italian`). Se nessun modello risponde, il PDF
viene generato lo stesso, con "(traduzione non disponibile)" nella colonna
italiana.

## Robustezza

- **Gemini**: timeout di 60s, fino a 3 tentativi con backoff esponenziale e
  jitter su errori transitori (429, 5xx, timeout). Se il modello resta
  irraggiungibile, `POST /api/chat` risponde `502` e il REPL continua a
  funzionare invece di terminare.
- Variabili di regolazione: `GEMINI_TIMEOUT`, `GEMINI_MAX_ATTEMPTS`,
  `GEMINI_RETRY_DELAY`.
- Se il totem non ha accesso a `huggingface.co` ma i modelli sono già in cache,
  imposta `HF_HUB_OFFLINE=1` per evitare i tentativi di verifica all'avvio.

I test coprono retry e fallback del modello: `uv run pytest`.
