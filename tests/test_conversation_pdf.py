import conversation_pdf


def test_save_conversation_pdf_crea_file_tabellato(tmp_path, monkeypatch):
    monkeypatch.setattr(conversation_pdf, "to_italian", lambda text: text)
    messages = [
        {"role": "user", "content": "Come rinnovo la carta d'identità?"},
        {"role": "assistant", "content": "Prenota online."},
    ]
    path = conversation_pdf.save_conversation_pdf(messages, tmp_path)
    assert path.read_bytes().startswith(b"%PDF")
