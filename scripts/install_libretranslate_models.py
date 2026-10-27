"""Preinstalla i modelli Argos necessari a LibreTranslate.

Serve per l'avvio senza Docker. I modelli richiesti dipendono da
`LIBRETRANSLATE_LANGUAGES` (default: en,it,uk,tl,bn,ar,zh):

    uv run --with libretranslate python scripts/install_libretranslate_models.py

Argos non offre modelli diretti da ogni lingua verso l'italiano: per le lingue
extra serve `X->en` e `en->it`; `translate.py` fa il pivot via inglese.
I modelli finiscono nella cache utente di Argos, condivisa con
`uvx libretranslate`.
"""

import os
import sys
from pathlib import Path

import argostranslate.package as package
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_LANGUAGES = "en,it,uk,tl,bn,ar,zh"


def _languages() -> list[str]:
    raw = os.getenv("LIBRETRANSLATE_LANGUAGES", DEFAULT_LANGUAGES)
    return [code.strip() for code in raw.split(",") if code.strip()]


def _required_pairs(languages: list[str]) -> tuple[set, set]:
    """Ritorna (coppie necessarie, coppie dirette opzionali)."""
    required = {("en", "it"), ("it", "en")}
    optional = set()
    for code in languages:
        if code in {"en", "it"}:
            continue
        required.add((code, "en"))
        optional.add((code, "it"))
    return required, optional


def main() -> None:
    languages = _languages()
    required, optional = _required_pairs(languages)

    installed = {
        (installed.from_code, installed.to_code)
        for installed in package.get_installed_packages()
    }
    missing_required = required - installed
    missing_optional = optional - installed
    if not missing_required and not missing_optional:
        print("Modelli Argos già installati.")
        return

    print(
        f"Lingue richieste: {', '.join(languages)}. "
        "Aggiorno l'indice dei modelli Argos..."
    )
    package.update_package_index()
    available = {
        (available.from_code, available.to_code): available
        for available in package.get_available_packages()
    }

    failed = []
    for pair in sorted(missing_required):
        model = available.get(pair)
        if model is None:
            failed.append(pair)
            print(
                f"[modelli] richiesto {pair[0]}->{pair[1]}: non disponibile",
                file=sys.stderr,
            )
            continue
        print(f"[modelli] installo {pair[0]}->{pair[1]}...")
        model.install()

    for pair in sorted(missing_optional):
        model = available.get(pair)
        if model is None:
            # Nessun modello diretto: translate.py userà il pivot via inglese.
            continue
        print(f"[modelli] installo anche {pair[0]}->{pair[1]} (diretto)...")
        model.install()

    if failed:
        raise SystemExit(
            "Modelli necessari non trovati nell'indice: "
            + ", ".join(f"{a}->{b}" for a, b in failed)
        )


if __name__ == "__main__":
    main()
