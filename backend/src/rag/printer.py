"""Stampa delle pagine sulla stampante termica Bluetooth del totem.

Il frontend invia le pagine già disegnate (immagini PNG come data URL); qui
vengono convertite in bianco e nero e mandate alla porta seriale Bluetooth
della stampante con il comando raster ESC/POS `GS v 0`.

NOTA: il protocollo è quello ESC/POS generico usato dalle stampanti Phomemo;
larghezza in punti e avanzamento carta vanno verificati sulla A282M reale
(`TOTEM_PRINTER_DOTS`, `TOTEM_PRINTER_FEED`).
"""

import base64
import binascii
import io
import os
import sys
import threading

PRINTER_ADDRESS = (
    os.getenv("TOTEM_PRINTER_ADDRESS", "B7F5E10BBCFE").replace(":", "").strip().upper()
)
# Porta esplicita (es. COM5): salta la ricerca per indirizzo Bluetooth.
PRINTER_PORT = os.getenv("TOTEM_PRINTER_PORT", "").strip()
# Larghezza di stampa in punti (multiplo di 8). 1728 = 216 mm a 203 dpi (A4).
PRINTER_DOTS = max(8, int(os.getenv("TOTEM_PRINTER_DOTS", "1728")) // 8 * 8)
# Righe di carta da far avanzare dopo ogni pagina.
PRINTER_FEED = max(0, min(255, int(os.getenv("TOTEM_PRINTER_FEED", "4"))))
PRINTER_TIMEOUT = float(os.getenv("TOTEM_PRINTER_TIMEOUT", "30"))

MAX_PAGES = 20
BAND_LINES = 256  # righe per comando raster: il buffer della stampante è piccolo

_print_lock = threading.Lock()


class PrinterError(RuntimeError):
    """Stampante non trovata, non raggiungibile o pagine non valide."""


def find_port(address: str = PRINTER_ADDRESS) -> str:
    """Porta COM della stampante, cercata nel registro di Windows.

    Windows crea per ogni dispositivo Bluetooth seriale una voce
    `HKLM\\SYSTEM\\CurrentControlSet\\Enum\\BTHENUM\\...\\<istanza con
    l'indirizzo>\\Device Parameters` con il valore `PortName`.
    """
    if PRINTER_PORT:
        return PRINTER_PORT
    if sys.platform != "win32":
        raise PrinterError("Imposta TOTEM_PRINTER_PORT: la ricerca automatica funziona solo su Windows.")

    import winreg

    root = r"SYSTEM\CurrentControlSet\Enum\BTHENUM"
    try:
        bthenum = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, root)
    except OSError as exc:
        raise PrinterError("Nessun dispositivo Bluetooth registrato.") from exc

    with bthenum:
        for device in _subkeys(bthenum):
            with winreg.OpenKey(bthenum, device) as device_key:
                for instance in _subkeys(device_key):
                    if address not in instance.upper():
                        continue
                    try:
                        with winreg.OpenKey(device_key, rf"{instance}\Device Parameters") as params:
                            port, _ = winreg.QueryValueEx(params, "PortName")
                    except OSError:
                        continue
                    if port:
                        return str(port)
    raise PrinterError(f"Stampante Bluetooth {address} non associata al PC.")


def _subkeys(key):
    import winreg

    index = 0
    while True:
        try:
            yield winreg.EnumKey(key, index)
        except OSError:
            return
        index += 1


def decode_page(data_url: str):
    from PIL import Image

    header, _, payload = data_url.partition(",")
    if not header.startswith("data:image/") or ";base64" not in header:
        raise PrinterError("Pagina non valida: serve un'immagine in data URL base64.")
    try:
        image = Image.open(io.BytesIO(base64.b64decode(payload, validate=True)))
        image.load()
    except (binascii.Error, OSError, ValueError) as exc:
        raise PrinterError("Pagina non valida: immagine illeggibile.") from exc
    return image


def raster_page(image, width: int = PRINTER_DOTS) -> bytes:
    """Comandi ESC/POS per una pagina, ridimensionata alla larghezza di stampa."""
    from PIL import Image

    if image.mode in ("RGBA", "LA", "P"):
        background = Image.new("RGBA", image.size, "white")
        background.alpha_composite(image.convert("RGBA"))
        image = background
    image = image.convert("L")
    height = max(1, round(image.height * width / image.width))
    image = image.resize((width, height), Image.LANCZOS)
    # In modalità "1" Pillow applica il dithering; i bit a 0 sono il nero,
    # mentre per la stampante 1 = punto stampato: si inverte.
    bits = image.convert("1").tobytes()
    data = bytes(~byte & 0xFF for byte in bits)

    bytes_per_line = width // 8
    commands = bytearray()
    for top in range(0, height, BAND_LINES):
        lines = min(BAND_LINES, height - top)
        commands += b"\x1dv0\x00"
        commands += bytes([bytes_per_line & 0xFF, bytes_per_line >> 8, lines & 0xFF, lines >> 8])
        commands += data[top * bytes_per_line : (top + lines) * bytes_per_line]
    commands += b"\x1bd" + bytes([PRINTER_FEED])
    return bytes(commands)


def print_pages(pages: list[str]) -> None:
    if not pages:
        raise PrinterError("Nessuna pagina da stampare.")
    if len(pages) > MAX_PAGES:
        raise PrinterError(f"Troppe pagine (massimo {MAX_PAGES}).")
    # Le pagine si convertono prima di aprire la porta: un errore non lascia
    # la stampante a metà foglio.
    job = b"\x1b@" + b"".join(raster_page(decode_page(page)) for page in pages)

    import serial

    with _print_lock:
        port = find_port()
        try:
            with serial.Serial(port, 115200, timeout=PRINTER_TIMEOUT, write_timeout=PRINTER_TIMEOUT) as connection:
                connection.write(job)
                connection.flush()
        except serial.SerialException as exc:
            raise PrinterError(f"Stampante su {port} non raggiungibile: {exc}") from exc
