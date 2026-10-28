from types import SimpleNamespace

import pytest
from openai import APIConnectionError, APIStatusError, OpenAIError

import llm


class FakeStatusError(OpenAIError):
    """Errore con status HTTP, per esercitare la logica di retry."""

    def __init__(self, status_code: int):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class FakeClient:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0
        self.messages = None
        self.models = []
        self.requests = []
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create)
        )

    def _create(self, model, messages, **kwargs):
        self.calls += 1
        self.models.append(model)
        self.messages = messages
        self.requests.append({"model": model, "messages": messages, **kwargs})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=outcome))]
        )


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda _seconds: None)


@pytest.fixture(autouse=True)
def gemini_primary(monkeypatch):
    """Il `.env` locale può attivare il modello locale: qui parte Gemini."""
    monkeypatch.setattr(llm, "LOCAL_MODEL_PRIMARY", False)


def documents():
    return (["Documento di prova"], [{"service": "CIE", "type": "service"}])


def test_ask_returns_answer_without_retry():
    client = FakeClient(["risposta"])
    assert llm.ask(client, "domanda", *documents()) == "risposta"
    assert client.calls == 1


def test_ask_retries_transient_status_then_succeeds():
    client = FakeClient([FakeStatusError(503), FakeStatusError(429), "ok"])
    assert llm.ask(client, "domanda", *documents()) == "ok"
    assert client.calls == 3


def test_ask_gives_up_after_max_attempts():
    client = FakeClient([FakeStatusError(503)] * llm.MAX_ATTEMPTS)
    with pytest.raises(llm.ModelUnavailableError):
        llm.ask(client, "domanda", *documents())
    assert client.calls == llm.MAX_ATTEMPTS


def test_ask_retries_connection_errors():
    client = FakeClient([APIConnectionError(request=None), "ok"])
    assert llm.ask(client, "domanda", *documents()) == "ok"
    assert client.calls == 2


def test_ask_does_not_retry_client_errors():
    client = FakeClient([FakeStatusError(400)])
    with pytest.raises(FakeStatusError):
        llm.ask(client, "domanda", *documents())
    assert client.calls == 1


def test_ask_falls_back_to_local_model(monkeypatch):
    monkeypatch.setattr(llm, "LOCAL_MODEL_NAME", "modello-locale")
    primary = FakeClient([FakeStatusError(503)] * llm.MAX_ATTEMPTS)
    fallback = FakeClient(["risposta locale"])

    assert (
        llm.ask(
            primary,
            "domanda",
            *documents(),
            fallback_client=fallback,
        )
        == "risposta locale"
    )
    assert primary.calls == llm.MAX_ATTEMPTS
    assert fallback.models == ["modello-locale"]


def test_ask_falls_back_on_non_retryable_error(monkeypatch):
    monkeypatch.setattr(llm, "LOCAL_MODEL_NAME", "modello-locale")
    primary = FakeClient([FakeStatusError(400)])
    fallback = FakeClient(["ok locale"])

    assert (
        llm.ask(primary, "domanda", *documents(), fallback_client=fallback)
        == "ok locale"
    )
    assert primary.calls == 1


def test_ask_raises_when_both_models_fail(monkeypatch):
    monkeypatch.setattr(llm, "LOCAL_MODEL_NAME", "modello-locale")
    primary = FakeClient([FakeStatusError(503)] * llm.MAX_ATTEMPTS)
    fallback = FakeClient([FakeStatusError(503)] * llm.MAX_ATTEMPTS)

    with pytest.raises(llm.ModelUnavailableError):
        llm.ask(primary, "domanda", *documents(), fallback_client=fallback)
    assert fallback.calls == llm.LOCAL_MODEL_ATTEMPTS


def test_local_fallback_uses_compact_context_and_token_budget(monkeypatch):
    monkeypatch.setattr(llm, "LOCAL_MODEL_NAME", "modello-locale")
    monkeypatch.setattr(llm, "LOCAL_CONTEXT_DOCUMENTS", 2)
    monkeypatch.setattr(llm, "LOCAL_MODEL_MAX_TOKENS", 123)
    docs = [f"Documento {index}" for index in range(5)]
    metas = [{"service": f"S{index}", "type": "service"} for index in range(5)]
    primary = FakeClient([FakeStatusError(400)])
    fallback = FakeClient(["ok locale"])

    assert (
        llm.ask(primary, "domanda", docs, metas, fallback_client=fallback)
        == "ok locale"
    )

    system_prompt = fallback.messages[0]["content"]
    content = fallback.messages[-1]["content"]
    assert system_prompt == llm.LOCAL_SYSTEM_PROMPT
    assert "Documento 1" in content
    assert "Documento 2" not in content
    assert "Metadati" not in content
    assert fallback.requests[0]["max_tokens"] == 123


def test_ask_retries_empty_answer():
    client = FakeClient(["   ", "ok"])
    assert llm.ask(client, "domanda", *documents()) == "ok"
    assert client.calls == 2


def test_ask_prefers_local_model_when_primary(monkeypatch):
    monkeypatch.setattr(llm, "LOCAL_MODEL_NAME", "modello-locale")
    monkeypatch.setattr(llm, "LOCAL_MODEL_PRIMARY", True)
    monkeypatch.setattr(llm, "LOCAL_CONTEXT_DOCUMENTS", 1)
    docs = ["Documento 1", "Documento 2"]
    metas = [{"service": "S1"}, {"service": "S2"}]
    primary = FakeClient(["risposta locale"])
    fallback = FakeClient(["risposta gemini"])

    assert (
        llm.ask(primary, "domanda", docs, metas, fallback_client=fallback)
        == "risposta locale"
    )
    assert primary.models == ["modello-locale"]
    assert primary.messages[0]["content"] == llm.LOCAL_SYSTEM_PROMPT
    assert "Documento 2" not in primary.messages[-1]["content"]
    assert fallback.calls == 0


def test_ask_falls_back_to_gemini_when_local_primary_fails(monkeypatch):
    monkeypatch.setattr(llm, "LOCAL_MODEL_NAME", "modello-locale")
    monkeypatch.setattr(llm, "LOCAL_MODEL_PRIMARY", True)
    primary = FakeClient([FakeStatusError(503)] * llm.LOCAL_MODEL_ATTEMPTS)
    fallback = FakeClient(["risposta gemini"])

    assert (
        llm.ask(primary, "domanda", *documents(), fallback_client=fallback)
        == "risposta gemini"
    )
    assert fallback.models == [llm.MODEL]
    assert fallback.messages[0]["content"] == llm.SYSTEM_PROMPT


def test_ask_raises_when_local_primary_and_gemini_both_fail(monkeypatch):
    monkeypatch.setattr(llm, "LOCAL_MODEL_NAME", "modello-locale")
    monkeypatch.setattr(llm, "LOCAL_MODEL_PRIMARY", True)
    primary = FakeClient([FakeStatusError(503)] * llm.LOCAL_MODEL_ATTEMPTS)
    fallback = FakeClient([FakeStatusError(503)] * llm.MAX_ATTEMPTS)

    with pytest.raises(llm.ModelUnavailableError):
        llm.ask(primary, "domanda", *documents(), fallback_client=fallback)
    assert fallback.calls == llm.MAX_ATTEMPTS


def test_local_primary_swaps_client_roles(monkeypatch):
    monkeypatch.setattr(llm, "LOCAL_MODEL_PRIMARY", True)
    monkeypatch.setattr(llm, "LOCAL_MODEL_NAME", "modello-locale")
    monkeypatch.setenv("LOCAL_MODEL_NAME", "modello-locale")
    monkeypatch.setenv("LOCAL_MODEL_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("VALERIO_API", "chiave-finta")

    assert "11434" in str(llm.create_client().base_url)
    assert "googleapis" in str(llm.create_fallback_client().base_url)
    assert llm.primary_model_name() == "modello-locale"


def test_local_primary_without_gemini_has_no_fallback(monkeypatch):
    monkeypatch.setattr(llm, "LOCAL_MODEL_PRIMARY", True)
    monkeypatch.setenv("LOCAL_MODEL_NAME", "modello-locale")
    monkeypatch.setenv("LOCAL_MODEL_URL", "http://localhost:11434/v1")
    monkeypatch.delenv("VALERIO_API", raising=False)

    assert "11434" in str(llm.create_client().base_url)
    assert llm.create_fallback_client() is None
    assert llm.fallback_model_name() is None


def test_messages_include_system_context_and_history():
    history = [
        {"role": "user", "content": "prima domanda"},
        {"role": "assistant", "content": "prima risposta"},
    ]
    messages = llm.build_messages("domanda", *documents(), history=history)

    assert messages[0]["role"] == "system"
    assert messages[1:3] == history
    assert messages[-1]["role"] == "user"
    assert "Documento di prova" in messages[-1]["content"]
    assert "domanda" in messages[-1]["content"]


def test_messages_without_history_are_system_plus_user():
    messages = llm.build_messages("domanda", *documents())
    assert [message["role"] for message in messages] == ["system", "user"]


def test_system_prompts_prevent_conflating_service_rules_and_regulations():
    assert "Cita una norma solo se il contesto collega" in llm.SYSTEM_PROMPT
    assert "modalità di prenotazione" in llm.SYSTEM_PROMPT
    assert "sistema di scrittura usato dall'utente" in llm.SYSTEM_PROMPT
    assert "Cita una norma solo se il contesto collega" in llm.LOCAL_SYSTEM_PROMPT
    assert "modalità di prenotazione" in llm.LOCAL_SYSTEM_PROMPT
    assert "sistema di scrittura usato dall'utente" in llm.LOCAL_SYSTEM_PROMPT


def test_system_prompts_keep_acronyms_and_precise_citations():
    for prompt in (llm.SYSTEM_PROMPT, llm.LOCAL_SYSTEM_PROMPT):
        assert "Anagrafe degli Italiani Residenti all'Estero" in prompt
        assert "Non tradurre le sigle" in prompt
        assert "Non aggiungere in fondo una sezione" in prompt
        assert "regolamento futuro" in prompt


def test_compact_context_names_service_of_regulations():
    docs = ["Normativa: D.L. 5 del 9 febbraio 2012", "Servizio: CIE"]
    metas = [
        {"service": "Cambi di Residenza", "type": "regulation"},
        {"service": "CIE", "type": "service"},
    ]

    context = llm.build_context(docs, metas, include_metadata=False)

    assert "Norma collegata al servizio: Cambi di Residenza" in context
    assert "Norma collegata al servizio: CIE" not in context
    assert "Metadati" not in context


def test_local_model_uses_low_temperature(monkeypatch):
    monkeypatch.setattr(llm, "LOCAL_MODEL_NAME", "modello-locale")
    monkeypatch.setattr(llm, "LOCAL_MODEL_PRIMARY", True)
    monkeypatch.setattr(llm, "LOCAL_MODEL_TEMPERATURE", 0.2)
    client = FakeClient(["ok"])

    llm.ask(client, "domanda", *documents())

    assert client.requests[0]["temperature"] == 0.2


def test_gemini_keeps_default_temperature(monkeypatch):
    monkeypatch.setattr(llm, "GEMINI_TEMPERATURE", None)
    client = FakeClient(["ok"])

    llm.ask(client, "domanda", *documents())

    assert "temperature" not in client.requests[0]


def test_retryable_predicate():
    assert llm._is_retryable(FakeStatusError(503))
    assert llm._is_retryable(APIConnectionError(request=None))
    assert not llm._is_retryable(FakeStatusError(400))
    assert not llm._is_retryable(APIStatusError)
