"""Esporta l'intera conversazione in due PDF: uno in italiano e uno nella
lingua dell'utente (quella in cui sono state scritte domande e risposte)."""

from datetime import datetime
import os
from pathlib import Path
import sys

from fpdf import FPDF
from fpdf.fonts import FontFace

try:
    from .translate import translate_to_italian
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from src.rag.translate import translate_to_italian

PDF_FONT = os.getenv("PDF_FONT", "").strip()
PDF_OUTPUT_DIR = Path(os.getenv("PDF_OUTPUT_DIR", "conversazioni"))

# Font Unicode cercati in ordine; PDF_FONT ha la precedenza. I font di sistema
# coprono latino e cirillico; per cinese, bengalese ecc. impostare PDF_FONT su
# un font che contenga quei glifi (es. Noto Sans).
_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
]

ROLE_LABELS = {"user": "Utente", "assistant": "Assistente"}
TITLE = "Conversazione - Anagrafe Roma Capitale"
HEADERS = ("Italiano", "Lingua originale")


def _find_font() -> str | None:
    for candidate in [PDF_FONT, *_FONT_CANDIDATES]:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def to_italian(text: str) -> str:
    """Traduce in italiano; se il testo è già italiano (o la traduzione non è
    disponibile) restituisce l'originale."""
    return translate_to_italian(text) or text


def build_pdf(messages: list[dict]) -> bytes:
    """Costruisce un unico PDF con la conversazione in una tabella: a sinistra
    domande/risposte in italiano, a destra nella lingua originale."""
    font_path = _find_font()
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    if font_path:
        pdf.add_font("body", fname=font_path)
        family = "body"
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
        for message in messages:
            label = ROLE_LABELS.get(message["role"], message["role"])
            original = message["content"]
            row = table.row()
            row.cell(clean(f"{label}:\n{to_italian(original)}"))
            row.cell(clean(f"{label}:\n{original}"))

    return bytes(pdf.output())


def save_conversation_pdf(messages: list[dict], directory: Path | None = None) -> Path:
    """Scrive il PDF tabellato e ne restituisce il percorso."""
    directory = Path(directory or PDF_OUTPUT_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"conversazione_{datetime.now():%Y%m%d_%H%M%S}.pdf"
    path.write_bytes(build_pdf(messages))
    return path
