import base64
import io
from email.message import Message

import pytest
from PIL import Image

import kiosk
import printer


CORPUS = {
    "residenza": {"id": "residenza", "title": "Cambio di residenza", "kind": "pagina",
                  "file": "residenza.md", "url": "https://example.org/residenza",
                  "forms": ["modulo-residenza"]},
    "residenza-costi": {"id": "residenza-costi", "title": "Residenza: costi", "kind": "pagina",
                        "file": "residenza costi.md", "url": None, "forms": []},
    "modulo-residenza": {"id": "modulo-residenza", "title": "Dichiarazione di residenza",
                         "kind": "modulo", "file": "modulo-residenza.pdf", "url": None, "forms": []},
    "guida": {"id": "guida", "title": "Guida online", "kind": "guida",
              "file": "guida.pdf", "url": None, "forms": []},
}


def _headers(**values):
    message = Message()
    for name, value in values.items():
        message[name.replace("_", "-")] = value
    return message


def test_build_sources_una_fonte_per_pagina_e_moduli_collegati():
    metadatas = [
        {"type": "pagina", "source_id": "residenza", "chunk_index": 0},
        {"type": "pagina", "source_id": "residenza", "chunk_index": 1},
        {"type": "pagina", "source_id": "residenza-costi", "chunk_index": 0},
        {"type": "guida", "source_id": "guida"},
        {"type": "modulo", "source_id": "modulo-residenza"},
        {"type": "pagina", "source_id": "sconosciuta"},
    ]

    sources, forms = kiosk.build_sources(metadatas, CORPUS, "http://localhost:8000/documents/")

    base = "http://localhost:8000/documents"
    assert sources == [
        {"number": 1, "title": "Cambio di residenza", "kind": "pagina",
         "url": "https://example.org/residenza", "copy": f"{base}/residenza.md"},
        {"number": 2, "title": "Residenza: costi", "kind": "pagina",
         "url": f"{base}/residenza%20costi.md", "copy": f"{base}/residenza%20costi.md"},
    ]
    assert forms == [
        {"id": "modulo-residenza", "title": "Dichiarazione di residenza",
         "url": f"{base}/modulo-residenza.pdf"},
        {"id": "guida", "title": "Guida online", "url": f"{base}/guida.pdf"},
    ]


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({}, True),
        ({"X_Frame_Options": "DENY"}, False),
        ({"X_Frame_Options": "SAMEORIGIN"}, False),
        ({"Content_Security_Policy": "default-src 'self'; frame-ancestors 'self'"}, False),
        ({"Content_Security_Policy": "frame-ancestors *"}, True),
        ({"Content_Security_Policy": "default-src 'self'"}, True),
    ],
)
def test_frame_allowed(headers, expected):
    assert kiosk.frame_allowed(_headers(**headers)) is expected


@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "ftp://example.org/x", "http://127.0.0.1:8000/", "http://localhost/", "http://192.168.1.1/"],
)
def test_check_public_url_blocca_indirizzi_interni(url):
    with pytest.raises(kiosk.BlockedUrlError):
        kiosk.check_public_url(url)


def test_download_pdf_rifiuta_file_non_pdf(monkeypatch):
    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(kiosk, "open_url", lambda url: FakeResponse(b"<html></html>"))
    with pytest.raises(kiosk.NotAPdfError):
        kiosk.download_pdf("https://example.org/a.pdf")

    monkeypatch.setattr(kiosk, "open_url", lambda url: FakeResponse(b"%PDF-1.7 ..."))
    assert kiosk.download_pdf("https://example.org/a.pdf").startswith(b"%PDF")


def test_session_store_conserva_e_scade(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(kiosk.time, "monotonic", lambda: clock[0])
    store = kiosk.SessionStore(ttl=10, limit=2)

    first = store.get("a")
    first.remember("domanda", "risposta")
    assert store.get("a") is first

    clock[0] += 11
    assert store.get("a") is not first
    assert store.get(None) is not store.get(None)


def test_session_history_resta_breve():
    session = kiosk.Session()
    for index in range(5):
        session.remember(f"d{index}", f"r{index}")
    assert len(session.history) == kiosk.MAX_HISTORY_TURNS * 2
    assert session.history[-1] == {"role": "assistant", "content": "r4"}


def _fake_query(results):
    calls = []

    def query(text, n_results, with_score):
        calls.append(text)
        return results.get(text, ([], [], None))

    return query, calls


def test_retrieve_usa_la_domanda_precedente_se_non_trova_nulla():
    query, calls = _fake_query({
        "cambio residenza e i documenti?": (["doc B", "doc A"], [{"service": "B"}, {"service": "A"}], None),
    })
    session = kiosk.Session()
    session.last_question = "cambio residenza"
    session.last_services = ["A"]

    documents, metadatas, merged = kiosk.retrieve(query, "e i documenti?", session, 8)

    assert calls == ["e i documenti?", "cambio residenza e i documenti?"]
    assert merged is True
    assert documents == ["doc A", "doc B"]


def test_retrieve_sceglie_il_risultato_con_punteggio_migliore():
    session = kiosk.Session()
    session.last_question = "certificato di residenza online"
    query, _ = _fake_query({
        "costa qualcosa?": (["costi CIE"], [{"service": "CIE"}], -1.9),
        "certificato di residenza online costa qualcosa?": (["costi certificati"], [{"service": "Cert"}], -0.8),
    })
    assert kiosk.retrieve(query, "costa qualcosa?", session, 8)[:2] == (["costi certificati"], [{"service": "Cert"}])

    query, _ = _fake_query({
        "costa qualcosa?": (["costi CIE"], [{"service": "CIE"}], 2.0),
        "certificato di residenza online costa qualcosa?": (["costi certificati"], [{"service": "Cert"}], -0.8),
    })
    documents, _metadatas, merged = kiosk.retrieve(query, "costa qualcosa?", session, 8)
    assert documents == ["costi CIE"] and merged is False


def test_retrieve_senza_domanda_precedente_fa_una_sola_ricerca():
    query, calls = _fake_query({"ciao": (["x"], [{"service": "S"}], 1.0)})
    kiosk.retrieve(query, "ciao", kiosk.Session(), 8)
    assert calls == ["ciao"]


def _data_url(image):
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def test_raster_page_genera_comandi_gs_v_0():
    image = Image.new("L", (100, 50), "white")
    image.paste(0, (0, 0, 100, 25))  # metà superiore nera

    commands = printer.raster_page(printer.decode_page(_data_url(image)), width=16)

    assert commands.startswith(b"\x1dv0\x00\x02\x00\x08\x00")
    data = commands[8:8 + 16]
    assert data[:2] == b"\xff\xff"  # prima riga: tutto nero
    assert data[-2:] == b"\x00\x00"  # ultima riga: bianco
    assert commands.endswith(b"\x1bd" + bytes([printer.PRINTER_FEED]))


def test_decode_page_rifiuta_dati_non_immagine():
    with pytest.raises(printer.PrinterError):
        printer.decode_page("data:text/plain;base64,aGVsbG8=")
    with pytest.raises(printer.PrinterError):
        printer.decode_page("data:image/png;base64,non-base64!")


def test_print_pages_senza_stampante(monkeypatch):
    monkeypatch.setattr(printer, "find_port", lambda: (_ for _ in ()).throw(printer.PrinterError("assente")))
    with pytest.raises(printer.PrinterError):
        printer.print_pages([_data_url(Image.new("L", (8, 8), "white"))])
