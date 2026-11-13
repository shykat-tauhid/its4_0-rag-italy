"""Esporta l'intera conversazione in un PDF per l'operatore dell'ufficio: a
sinistra domande e risposte nella lingua dell'utente, a destra la traduzione
in italiano."""

from collections.abc import Callable
from datetime import datetime
import os
from pathlib import Path
import sys

from fpdf import FPDF
from fpdf.fonts import FontFace

PDF_FONT = os.getenv("PDF_FONT", "").strip()
PDF_OUTPUT_DIR = Path(os.getenv("PDF_OUTPUT_DIR", "conversazioni"))

# Font Unicode cercati in ordine; PDF_FONT ha la precedenza. Coprono latino,
# cirillico e arabo; le altre scritture del totem usano i font di riserva.
_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
]

# Font di riserva per i caratteri che il font principale non ha: fpdf2 li usa
# carattere per carattere. Per ogni scrittura vale il primo file trovato.
_FALLBACK_FONT_CANDIDATES = {
    "bengalese": [
        r"C:\Windows\Fonts\Nirmala.ttc",
        r"C:\Windows\Fonts\Nirmala.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansBengali-Regular.ttf",
    ],
    "cinese": [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simsun.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ],
    "giapponese": [
        r"C:\Windows\Fonts\YuGothM.ttc",
        r"C:\Windows\Fonts\msgothic.ttc",
    ],
}

try:
    import uharfbuzz  # noqa: F401  (serve a fpdf2 per il text shaping)

    _TEXT_SHAPING = True
except ImportError:
    # Senza shaping l'arabo esce con lettere staccate e il bengalese con le
    # legature sbagliate: installare `uharfbuzz` per stamparli correttamente.
    _TEXT_SHAPING = False

ROLE_LABELS = {"user": "Utente", "assistant": "Assistente"}
TITLE = "Conversazione - Anagrafe Roma Capitale"
HEADERS = ("Lingua originale", "Italiano")
TRANSLATION_UNAVAILABLE = "(traduzione non disponibile)"

# Riceve i testi dei messaggi e restituisce le traduzioni italiane, nello
# stesso ordine; può sollevare eccezioni (modello non disponibile).
Translator = Callable[[list[str]], list[str]]


def _find_font() -> str | None:
    for candidate in [PDF_FONT, *_FONT_CANDIDATES]:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def _add_fallback_fonts(pdf: FPDF) -> None:
    names = []
    for name, candidates in _FALLBACK_FONT_CANDIDATES.items():
        path = next((path for path in candidates if Path(path).is_file()), None)
        if not path:
            continue
        try:
            pdf.add_font(name, fname=path)
        except Exception as exc:  # font danneggiato o formato non supportato
            print(f"[rag] Font di riserva {path} non caricato: {exc}", file=sys.stderr)
            continue
        names.append(name)
    if names:
        pdf.set_fallback_fonts(names)


def _italian_versions(messages: list[dict], translate: Translator | None) -> list[str]:
    """Traduzioni italiane dei messaggi; se la traduzione non riesce il PDF
    viene comunque generato, con un avviso nella colonna italiana."""
    texts = [message["content"] for message in messages]
    if translate is None:
        return [TRANSLATION_UNAVAILABLE] * len(texts)
    try:
        return translate(texts)
    except Exception as exc:
        print(f"[rag] Traduzione del PDF non riuscita: {exc}", file=sys.stderr)
        return [TRANSLATION_UNAVAILABLE] * len(texts)


def build_pdf(messages: list[dict], translate: Translator | None = None) -> bytes:
    """Costruisce il PDF con la conversazione in una tabella: a sinistra il
    testo originale, a destra la traduzione italiana prodotta da `translate`."""
    italian = _italian_versions(messages, translate)

    font_path = _find_font()
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    if font_path:
        pdf.add_font("body", fname=font_path)
        family = "body"
        _add_fallback_fonts(pdf)
        if _TEXT_SHAPING:
            pdf.set_text_shaping(True)
    else:
        # Senza font Unicode restano solo i caratteri latin-1.
        family = "Helvetica"

    def clean(text: str) -> str:
        if font_path:
            return text
        return text.encode("latin-1", "replace").decode("latin-1")

    pdf.set_font(family, size=16)
    pdf.multi_cell(0, 8, clean(TITLE), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(family, size=9)
    pdf.multi_cell(
        0, 5, datetime.now().strftime("%d/%m/%Y %H:%M"), new_x="LMARGIN", new_y="NEXT"
    )
    pdf.ln(4)

    pdf.set_font(family, size=10)
    with pdf.table(
        col_widths=(1, 1),
        text_align="LEFT",
        line_height=5,
        headings_style=FontFace(emphasis=None, fill_color=(230, 230, 230)),
    ) as table:
        header = table.row()
        for title in HEADERS:
            header.cell(title)
        for message, translated in zip(messages, italian):
            label = ROLE_LABELS.get(message["role"], message["role"])
            row = table.row()
            row.cell(clean(f"{label}:\n{message['content']}"))
            row.cell(clean(f"{label}:\n{translated}"))

    return bytes(pdf.output())


def save_conversation_pdf(
    messages: list[dict],
    directory: Path | None = None,
    translate: Translator | None = None,
) -> Path:
    """Scrive il PDF tabellato e ne restituisce il percorso."""
    directory = Path(directory or PDF_OUTPUT_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"conversazione_{datetime.now():%Y%m%d_%H%M%S}.pdf"
    path.write_bytes(build_pdf(messages, translate))
    return path
