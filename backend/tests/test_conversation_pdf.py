import conversation_pdf


MESSAGES = [
    {"role": "user", "content": "Paano ko ire-renew ang ID card?"},
    {"role": "assistant", "content": "Mag-book online."},
]


def test_save_conversation_pdf_crea_file_tabellato(tmp_path):
    path = conversation_pdf.save_conversation_pdf(
        MESSAGES, tmp_path, translate=lambda texts: ["Come rinnovo la CIE?", "Prenota online."]
    )
    assert path.read_bytes().startswith(b"%PDF")


def test_colonna_italiana_usa_la_traduzione():
    assert conversation_pdf._italian_versions(
        MESSAGES, lambda texts: [f"IT: {text}" for text in texts]
    ) == ["IT: Paano ko ire-renew ang ID card?", "IT: Mag-book online."]


def test_pdf_generato_anche_se_la_traduzione_fallisce():
    def failing(_texts):
        raise RuntimeError("modello giù")

    assert conversation_pdf._italian_versions(MESSAGES, failing) == [
        conversation_pdf.TRANSLATION_UNAVAILABLE
    ] * 2
    assert conversation_pdf.build_pdf(MESSAGES, failing).startswith(b"%PDF")
