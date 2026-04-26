"""Calibre-based EPUB → AZW3 conversion helper."""

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional


# Common install locations per platform
_CALIBRE_CANDIDATES = [
    "ebook-convert",                                        # already in PATH
    r"C:\Program Files\Calibre2\ebook-convert.exe",
    r"C:\Program Files (x86)\Calibre2\ebook-convert.exe",
    "/Applications/calibre.app/Contents/MacOS/ebook-convert",
    "/usr/bin/ebook-convert",
    "/usr/local/bin/ebook-convert",
    "/opt/calibre/ebook-convert",
]

CALIBRE_DOWNLOAD_URL = "https://calibre-ebook.com/download"


def find_ebook_convert() -> Optional[str]:
    """Return path to Calibre's ebook-convert, or None if not found."""
    for candidate in _CALIBRE_CANDIDATES:
        found = shutil.which(candidate)
        if found:
            return found
        if Path(candidate).exists():
            return candidate
    return None


def calibre_available() -> bool:
    return find_ebook_convert() is not None


def epub_to_azw3(epub_path: str, azw3_path: str, timeout: int = 120) -> str:
    """
    Convert an EPUB file to AZW3 using Calibre's ebook-convert.

    Raises RuntimeError if Calibre is not installed or conversion fails.
    Returns azw3_path on success.
    """
    converter = find_ebook_convert()
    if not converter:
        raise RuntimeError(
            f"Calibre no está instalado. Descargalo desde {CALIBRE_DOWNLOAD_URL} "
            "y asegurate de que 'ebook-convert' esté en el PATH."
        )

    try:
        result = subprocess.run(
            [converter, epub_path, azw3_path],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("La conversión AZW3 tardó demasiado (timeout).")
    except FileNotFoundError:
        raise RuntimeError(
            f"No se pudo ejecutar ebook-convert en '{converter}'. "
            "Verificá la instalación de Calibre."
        )

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "sin detalle").strip()
        raise RuntimeError(f"ebook-convert falló:\n{detail}")

    if not Path(azw3_path).exists():
        raise RuntimeError("ebook-convert terminó pero no generó el archivo AZW3.")

    return azw3_path
