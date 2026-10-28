"""Accesso condiviso al modello Gemini per API e REPL.

Centralizza prompt, modello, timeout e retry: l'API e il REPL non possono più
divergere (prima il system prompt era duplicato in due file).
"""

import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from types import SimpleNamespace

from dotenv import load_dotenv
from openai import APIConnectionError, APITimeoutError, OpenAI, OpenAIError

load_dotenv()

MODEL = "gemini-3.6-flash"
BASE_URL = os.getenv(
    "GEMINI_BASE_URL",
    "https://generativelanguage.googleapis.com/v1beta/openai/",
).strip()

# Local model fallback configuration
LOCAL_MODEL_NAME = os.getenv("LOCAL_MODEL_NAME", "").strip()
LOCAL_MODEL_URL = os.getenv("LOCAL_MODEL_URL", "").strip()
# Il modello locale è molto più lento di Gemini: timeout e retry separati.
LOCAL_MODEL_TIMEOUT_SECONDS = float(os.getenv("LOCAL_MODEL_TIMEOUT", "300"))
LOCAL_MODEL_ATTEMPTS = max(1, int(os.getenv("LOCAL_MODEL_ATTEMPTS", "1")))
LOCAL_MODEL_MAX_TOKENS = int(os.getenv("LOCAL_MODEL_MAX_TOKENS", "0")) or None
# Temperatura bassa: per un RAG servono risposte fedeli al contesto, non creative.
LOCAL_MODEL_TEMPERATURE = float(os.getenv("LOCAL_MODEL_TEMPERATURE", "0.2"))
# Finestra di contesto (token) per Ollama. Se > 0 il modello locale è chiamato
# tramite l'API nativa di Ollama, l'unica che accetta `num_ctx`: l'endpoint
# OpenAI-compatibile la ignora e usa 4096 token, che prompt e ragionamento
# esauriscono prima che il modello scriva la risposta. 0 = endpoint /v1.
LOCAL_MODEL_CONTEXT = max(0, int(os.getenv("LOCAL_MODEL_CONTEXT", "0")))
# Con il contesto completo il modello locale va in timeout: usa meno documenti
# e nessun metadato JSON.
LOCAL_CONTEXT_DOCUMENTS = max(1, int(os.getenv("LOCAL_CONTEXT_DOCUMENTS", "3")))
# Inverte la priorità: il modello locale diventa primario e Gemini il fallback.
LOCAL_MODEL_PRIMARY = os.getenv("LOCAL_MODEL_PRIMARY", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
    "local",
}

REQUEST_TIMEOUT_SECONDS = float(os.getenv("GEMINI_TIMEOUT", "60"))
MAX_ATTEMPTS = max(1, int(os.getenv("GEMINI_MAX_ATTEMPTS", "3")))
RETRY_BASE_DELAY = float(os.getenv("GEMINI_RETRY_DELAY", "0.8"))
# Vuota = temperatura predefinita di Gemini: per i modelli Gemini 3 Google
# sconsiglia di abbassarla (rischio di ripetizioni e risposte degradate).
GEMINI_TEMPERATURE = (
    float(os.getenv("GEMINI_TEMPERATURE")) if os.getenv("GEMINI_TEMPERATURE") else None
)
RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}

# Regole comuni ai due prompt, scritte dopo gli errori visti nei test
# multilingua (sigle tradotte male, norme citate in modo generico).
_COMMON_RULES = """
Non tradurre le sigle italiane (CIE, PEC, AIRE, ANPR, SPID, URP): lasciale
come sono. Se le spieghi, usa solo questi significati:
- CIE: Carta d'Identità Elettronica;
- PEC: Posta Elettronica Certificata;
- AIRE: Anagrafe degli Italiani Residenti all'Estero (non è un registro degli
  stranieri);
- ANPR: Anagrafe Nazionale della Popolazione Residente;
- SPID: Sistema Pubblico di Identità Digitale.

Quando citi una norma, indicala accanto all'informazione a cui si riferisce,
con tipo, numero e anno (es. "D.P.R. 223/1989, art. 33"). Se il testo della
norma rimanda ad altre disposizioni (es. "articoli 75 e 76 del D.P.R.
445/2000"), riporta quei riferimenti invece di espressioni generiche come
"previste dalla legge". Non aggiungere in fondo una sezione che riassume le
norme già citate.

Se una norma dice che un regolamento futuro "dovrà prevedere" o "prevede"
qualcosa, non presentarlo come regola già in vigore: spiega che la norma
rimanda a un regolamento.
"""

SYSTEM_PROMPT = """
Sei l'assistente informativo di un totem per i servizi della Pubblica
Amministrazione.

Rispondi alla domanda dell'utente utilizzando esclusivamente le informazioni
presenti nel contesto. Se il contesto non contiene informazioni sufficienti,
dichiaralo. Non inventare procedure, documenti, scadenze, costi o riferimenti
normativi.

Usa un linguaggio semplice e comprensibile anche a chi non conosce la
terminologia della Pubblica Amministrazione.

Rispondi nella stessa lingua usata dall'utente; 
se non è chiara, rispondi in italiano.
Mantieni anche il sistema di scrittura usato dall'utente, quando la lingua
prevede più sistemi di scrittura.

Usa i passaggi del contesto che rispondono direttamente alla domanda. Non
confondere informazioni di servizi diversi o le modalità di prenotazione con
i documenti da presentare. Cita una norma solo se il contesto collega
chiaramente quella norma all'informazione riportata; non attribuire alla norma
regole descritte separatamente come modalità del servizio. Non dire "sulla
base del contesto" o "nei documenti forniti"; rispondi direttamente alla
domanda.
""" + _COMMON_RULES

# Prompt ridotto per il fallback locale: i modelli piccoli seguono meglio
# istruzioni brevi e con il contesto compatto restano nei tempi.
LOCAL_SYSTEM_PROMPT = """
Sei l'assistente di un totem per i servizi anagrafici di Roma Capitale.

Rispondi solo con le informazioni presenti nel CONTESTO. Se non bastano,
dillo. Non inventare procedure, documenti, scadenze, costi o normative.

Indica una normativa solo se riguarda direttamente quello che l'utente ha
chiesto, e descrivi brevemente cosa stabilisce. Non aggiungere una sezione
sulla normativa se nessuna norma del contesto risponde alla domanda.

Usa frasi brevi e un linguaggio semplice. Rispondi OBBLIGATORIAMENTE nella
stessa lingua della DOMANDA DELL'UTENTE.
Mantieni anche il sistema di scrittura usato dall'utente, quando la lingua
prevede più sistemi di scrittura.

Non confondere informazioni di servizi diversi o le modalità di prenotazione
con i documenti da presentare. Cita una norma solo se il contesto collega
chiaramente quella norma all'informazione riportata; non attribuire alla norma
regole descritte separatamente come modalità del servizio.
Non copiare il testo italiano del contesto.
""" + _COMMON_RULES

NO_INFORMATION_ANSWER = (
    "Non ho trovato informazioni sufficienti per rispondere a questa domanda. "
    "Prova a riformularla indicando il servizio o il documento di interesse."
)


class ModelUnavailableError(RuntimeError):
    """Il servizio AI non ha prodotto una risposta dopo i tentativi previsti."""


class OllamaChatClient:
    """Client minimo per l'API nativa di Ollama (`/api/chat`).

    Espone la stessa interfaccia `chat.completions.create` del client OpenAI
    usata da `_ask_with_client`, ma permette di impostare `num_ctx`.
    """

    def __init__(self, url: str, context_length: int, timeout: float):
        base = url.rstrip("/")
        if base.endswith("/v1"):
            base = base[: -len("/v1")]
        self.base_url = base
        self.context_length = context_length
        self.timeout = timeout
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create)
        )

    def _create(self, model, messages, max_tokens=None):
        options = {"num_ctx": self.context_length}
        if max_tokens:
            options["num_predict"] = max_tokens
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": options,
        }
        request = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise ModelUnavailableError(
                f"Ollama non raggiungibile ({self.base_url}): {exc}"
            ) from exc

        message = SimpleNamespace(content=(data.get("message") or {}).get("content"))
        choice = SimpleNamespace(
            message=message,
            finish_reason=data.get("done_reason"),
        )
        return SimpleNamespace(choices=[choice])


def _local_client(url: str):
    if LOCAL_MODEL_CONTEXT:
        return OllamaChatClient(
            url, LOCAL_MODEL_CONTEXT, LOCAL_MODEL_TIMEOUT_SECONDS
        )
    return OpenAI(
        api_key=os.getenv("LOCAL_MODEL_API_KEY", "local"),
        base_url=url,
        timeout=LOCAL_MODEL_TIMEOUT_SECONDS,
        max_retries=0,
    )


def _local_model() -> tuple[str, str] | None:
    name = os.getenv("LOCAL_MODEL_NAME", "").strip()
    url = os.getenv("LOCAL_MODEL_URL", "").strip()
    if name and url:
        return name, url
    return None


def local_primary_enabled() -> bool:
    """True quando il modello locale è configurato ed è il modello primario."""
    return LOCAL_MODEL_PRIMARY and bool(LOCAL_MODEL_NAME)


def primary_model_name() -> str:
    """Nome del modello primario, per log e prompt dei clienti."""
    return LOCAL_MODEL_NAME if local_primary_enabled() else MODEL


def fallback_model_name() -> str | None:
    """Nome del modello di riserva, o None se non è disponibile."""
    if local_primary_enabled():
        return MODEL if os.getenv("VALERIO_API") else None
    return LOCAL_MODEL_NAME or None


def _gemini_client(api_key: str) -> OpenAI:
    return OpenAI(
        api_key=api_key,
        base_url=BASE_URL,
        timeout=REQUEST_TIMEOUT_SECONDS,
        max_retries=0,  # i retry sono gestiti qui, con backoff e jitter
    )


def create_client() -> OpenAI:
    local = _local_model()

    if local_primary_enabled() and local:
        return _local_client(local[1])

    api_key = os.getenv("VALERIO_API")

    if not api_key and local:
        return _local_client(local[1])

    if not api_key:
        raise RuntimeError("La variabile d'ambiente VALERIO_API non è configurata e nessun modello locale è stato specificato.")

    return _gemini_client(api_key)


def create_fallback_client() -> OpenAI | None:
    """Client di riserva: locale se Gemini è il primario, Gemini se è il contrario."""
    api_key = os.getenv("VALERIO_API")

    if local_primary_enabled():
        if not api_key:
            return None
        return _gemini_client(api_key)

    if not api_key:
        return None
    local = _local_model()
    if local is None:
        return None
    return _local_client(local[1])


def build_context(documents, metadatas, include_metadata=True) -> str:
    context_items = []
    for index, document in enumerate(documents):
        if include_metadata:
            metadata = metadatas[index]
            context_items.append(
                f"Metadati:\n{json.dumps(metadata, ensure_ascii=False, indent=2)}\n\n"
                f"Documento Estratto:\n{document}"
            )
        else:
            header = _compact_source(metadatas[index] if index < len(metadatas) else None)
            context_items.append(f"{header}Documento Estratto:\n{document}")
    return "\n\n---\n\n".join(context_items)


def _compact_source(metadata) -> str:
    """Riga di provenienza per il contesto compatto, al posto del JSON.

    Il testo delle norme non dice a quale servizio si riferiscono: senza questa
    riga il modello locale non sa collegare la norma al servizio giusto.
    """
    if not metadata or metadata.get("type") != "regulation":
        return ""
    service = metadata.get("service")
    return f"Norma collegata al servizio: {service}\n" if service else ""


def build_messages(question, documents, metadatas, history=None, compact=False):
    if compact:
        documents = list(documents)[:LOCAL_CONTEXT_DOCUMENTS]
        metadatas = list(metadatas)[:LOCAL_CONTEXT_DOCUMENTS]
        system_prompt = LOCAL_SYSTEM_PROMPT
        context = build_context(documents, metadatas, include_metadata=False)
    else:
        system_prompt = SYSTEM_PROMPT
        context = build_context(documents, metadatas)

    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history)
    messages.append(
        {
            "role": "user",
            "content": (
                f"CONTESTO:\n{context}\n\n"
                f"DOMANDA DELL'UTENTE:\n{question}\n\n"
                "Rispondi nella stessa lingua della domanda dell'utente."
            ),
        }
    )
    return messages


def _is_retryable(exc: OpenAIError) -> bool:
    if isinstance(exc, (APIConnectionError, APITimeoutError)):
        return True
    return getattr(exc, "status_code", None) in RETRYABLE_STATUS


def _retry_delay(attempt: int) -> float:
    # Jitter: più totem non riprovano tutti nello stesso istante.
    return RETRY_BASE_DELAY * (2 ** (attempt - 1)) * (0.5 + random.random())


def _ask_with_client(
    client,
    model,
    messages,
    attempts: int = MAX_ATTEMPTS,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> str:
    last_error: Exception | None = None
    request = {"model": model, "messages": messages}
    if max_tokens:
        request["max_tokens"] = max_tokens
    if temperature is not None:
        request["temperature"] = temperature

    for attempt in range(1, attempts + 1):
        try:
            response = client.chat.completions.create(**request)
        except OpenAIError as exc:
            if not _is_retryable(exc):
                raise
            last_error = exc
        else:
            choice = response.choices[0]
            answer = choice.message.content
            if answer and answer.strip():
                return answer
            if getattr(choice, "finish_reason", None) == "length":
                # Tipico dei modelli locali che ragionano: il contesto si
                # esaurisce prima che scrivano la risposta.
                print(
                    f"[rag] {model}: risposta vuota, limite di contesto o di "
                    "token raggiunto (aumenta LOCAL_MODEL_CONTEXT o riduci "
                    "LOCAL_CONTEXT_DOCUMENTS).",
                    file=sys.stderr,
                )
            last_error = ModelUnavailableError(
                "Il servizio AI non ha restituito una risposta."
            )

        if attempt < attempts:
            delay = _retry_delay(attempt)
            print(
                f"[rag] {model} non disponibile (tentativo {attempt}/"
                f"{attempts}), nuovo tentativo tra {delay:.1f}s",
                file=sys.stderr,
            )
            time.sleep(delay)

    raise ModelUnavailableError(
        "Il servizio AI non è disponibile in questo momento."
    ) from last_error


def _target_profile(
    is_local: bool,
) -> tuple[str, bool, int, int | None, float | None]:
    """(modello, contesto compatto, tentativi, max_tokens, temperatura)."""
    if is_local:
        return (
            LOCAL_MODEL_NAME,
            True,
            LOCAL_MODEL_ATTEMPTS,
            LOCAL_MODEL_MAX_TOKENS,
            LOCAL_MODEL_TEMPERATURE,
        )
    return MODEL, False, MAX_ATTEMPTS, None, GEMINI_TEMPERATURE


def ask(
    client,
    question,
    documents,
    metadatas,
    history=None,
    fallback_client=None,
) -> str:
    """Chiede al modello la risposta, ritentando gli errori transitori.

    Con `LOCAL_MODEL_PRIMARY` attivo il modello locale risponde per primo e
    Gemini fa da riserva; altrimenti vale l'ordine inverso. Se entrambi
    falliscono, solleva `ModelUnavailableError`.
    """
    primary_is_local = local_primary_enabled()
    (
        primary_model,
        primary_compact,
        primary_attempts,
        primary_max_tokens,
        primary_temperature,
    ) = _target_profile(primary_is_local)

    messages = build_messages(
        question, documents, metadatas, history, compact=primary_compact
    )

    try:
        return _ask_with_client(
            client,
            primary_model,
            messages,
            attempts=primary_attempts,
            max_tokens=primary_max_tokens,
            temperature=primary_temperature,
        )
    except (ModelUnavailableError, OpenAIError):
        (
            fallback_model,
            fallback_compact,
            fallback_attempts,
            fallback_max_tokens,
            fallback_temperature,
        ) = _target_profile(not primary_is_local)
        if fallback_client is None or not fallback_model:
            raise

        print(
            f"[rag] {primary_model} non disponibile, provo {fallback_model}...",
            file=sys.stderr,
        )
        fallback_messages = build_messages(
            question,
            documents,
            metadatas,
            history,
            compact=fallback_compact,
        )
        try:
            return _ask_with_client(
                fallback_client,
                fallback_model,
                fallback_messages,
                attempts=fallback_attempts,
                max_tokens=fallback_max_tokens,
                temperature=fallback_temperature,
            )
        except (ModelUnavailableError, OpenAIError) as fallback_error:
            raise ModelUnavailableError(
                f"Né {primary_model} né {fallback_model} sono disponibili."
            ) from fallback_error
