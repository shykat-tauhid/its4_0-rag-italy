import urllib.error

import pytest

import translate


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setattr(translate, "LIBRETRANSLATE_URL", "http://translate.test")
    monkeypatch.setattr(translate, "FAILURE_THRESHOLD", 3)
    monkeypatch.setattr(translate, "COOLDOWN_SECONDS", 60.0)
    translate.reset_cache()


def test_returns_none_without_url(monkeypatch):
    monkeypatch.setattr(translate, "LIBRETRANSLATE_URL", "")
    assert translate.translate_to_italian("how do I renew?") is None


def test_translates_and_caches(monkeypatch):
    calls = []

    def fake_request(text):
        calls.append(text)
        return "come posso rinnovare?"

    monkeypatch.setattr(translate, "_request_translation", fake_request)
    assert translate.translate_to_italian("how do I renew?") == "come posso rinnovare?"
    assert translate.translate_to_italian("how do I renew?") == "come posso rinnovare?"
    assert calls == ["how do I renew?"]


def test_unchanged_text_counts_as_no_translation(monkeypatch):
    monkeypatch.setattr(
        translate, "_request_translation", lambda text: text
    )
    assert translate.translate_to_italian("quanto costa?") is None


def test_failure_opens_circuit_breaker(monkeypatch):
    calls = []

    def failing(text):
        calls.append(text)
        raise urllib.error.URLError("connessione rifiutata")

    monkeypatch.setattr(translate, "_request_translation", failing)

    for index in range(3):
        assert translate.translate_to_italian(f"domanda {index}") is None
    assert len(calls) == 3

    # Circuito aperto: nessuna nuova richiesta finché non scade il cooldown.
    assert translate.translate_to_italian("domanda nuova") is None
    assert len(calls) == 3


def test_success_resets_failure_counter(monkeypatch):
    outcomes = [
        urllib.error.URLError("giù"),
        urllib.error.URLError("giù"),
        "come posso prenotare?",
        urllib.error.URLError("giù"),
        "risposta",
    ]

    def flaky(text):
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(translate, "_request_translation", flaky)

    assert translate.translate_to_italian("prima") is None
    assert translate.translate_to_italian("seconda") is None
    assert translate.translate_to_italian("terza") == "come posso prenotare?"
    assert translate.translate_to_italian("quarta") is None
    assert translate.translate_to_italian("quinta") == "risposta"


def test_timeout_falls_back(monkeypatch):
    def timeout(text):
        raise TimeoutError("timeout")

    monkeypatch.setattr(translate, "_request_translation", timeout)
    assert translate.translate_to_italian("how do I renew?") is None


def test_cooldown_expiry_retries(monkeypatch):
    monkeypatch.setattr(translate, "_disabled_until", 0.0)
    monkeypatch.setattr(
        translate, "_request_translation", lambda text: "tradotto"
    )
    assert translate.translate_to_italian("testo") == "tradotto"


def test_pivots_non_english_through_english(monkeypatch):
    calls = []

    def fake_translation(text, target="it", source="auto"):
        calls.append((text, target, source))
        if target == "it" and source == "auto":
            raise translate._PairUnavailable("nessun modello diretto")
        if target == "en":
            return "How do I change residence?"
        if target == "it" and source == "en":
            return "Come cambio residenza?"
        raise AssertionError((text, target, source))

    monkeypatch.setattr(translate, "_request_translation", fake_translation)
    monkeypatch.setattr(translate, "_detect_language", lambda text: "uk")

    assert (
        translate.translate_to_italian("Як змінити місце проживання?")
        == "Come cambio residenza?"
    )
    assert calls == [
        ("Як змінити місце проживання?", "it", "auto"),
        ("Як змінити місце проживання?", "en", "auto"),
        ("How do I change residence?", "it", "en"),
    ]


def test_italian_source_is_not_pivoted(monkeypatch):
    targets = []

    def fake_translation(text, target="it", source="auto"):
        targets.append(target)
        raise translate._PairUnavailable("stessa lingua")

    monkeypatch.setattr(translate, "_request_translation", fake_translation)
    monkeypatch.setattr(translate, "_detect_language", lambda text: "it")

    assert translate.translate_to_italian("Come cambio residenza?") is None
    assert targets == ["it"]


def test_failure_is_not_cached(monkeypatch):
    calls = []

    def flaky(text):
        calls.append(text)
        if len(calls) == 1:
            raise TimeoutError("primo caricamento lento")
        return "tradotto"

    monkeypatch.setattr(translate, "_request_translation", flaky)

    assert translate.translate_to_italian("testo") is None
    assert translate.translate_to_italian("testo") == "tradotto"
    assert calls == ["testo", "testo"]


def test_pair_unavailable_does_not_open_circuit(monkeypatch):
    def fake_translation(text, target="it", source="auto"):
        if target == "it" and source == "auto":
            raise translate._PairUnavailable("nessun modello diretto")
        return "tradotto"

    monkeypatch.setattr(translate, "_request_translation", fake_translation)
    monkeypatch.setattr(translate, "_detect_language", lambda text: "it")

    for index in range(translate.FAILURE_THRESHOLD):
        assert translate.translate_to_italian(f"domanda {index}") is None

    # Il circuito non si è aperto: una nuova lingua passa dal pivot.
    monkeypatch.setattr(translate, "_detect_language", lambda text: "uk")
    assert translate.translate_to_italian("нова") == "tradotto"


def test_localize_translates_fixed_message_into_question_language(monkeypatch):
    calls = []

    def fake_translation(text, target="it", source="auto"):
        calls.append((text, source, target))
        if target == "it":
            return "Come pago la tassa sui rifiuti?"
        if (source, target) == ("it", "tl"):
            raise translate._PairUnavailable("it->tl")
        if (source, target) == ("it", "en"):
            return "No information."
        return "Walang impormasyon."

    monkeypatch.setattr(translate, "_request_translation", fake_translation)
    monkeypatch.setattr(translate, "_detect_language", lambda text: "tl")

    question = "Paano ako magbabayad ng buwis sa basura?"
    assert translate.localize("Nessuna informazione.", question) == "Walang impormasyon."
    assert ("No information.", "en", "tl") in calls

    # Seconda chiamata servita dalla cache.
    count = len(calls)
    assert translate.localize("Nessuna informazione.", question) == "Walang impormasyon."
    assert len(calls) == count


def test_localize_keeps_italian_questions_unchanged(monkeypatch):
    monkeypatch.setattr(
        translate, "_request_translation", lambda text, target="it", source="auto": text
    )
    monkeypatch.setattr(
        translate, "_detect_language", lambda text: pytest.fail("non serve rilevare")
    )

    assert translate.localize("Nessuna informazione.", "Come pago la TARI?") == (
        "Nessuna informazione."
    )


def test_localize_returns_original_when_service_fails(monkeypatch):
    def fake_translation(text, target="it", source="auto"):
        if target == "it" and source == "auto":
            return "domanda tradotta"
        raise urllib.error.URLError("giù")

    monkeypatch.setattr(translate, "_request_translation", fake_translation)
    monkeypatch.setattr(translate, "_detect_language", lambda text: "ar")

    assert translate.localize("Nessuna informazione.", "سؤال") == "Nessuna informazione."
