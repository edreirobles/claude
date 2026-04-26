"""Local EPUB library backed by SQLite."""

import sqlite3
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

DB_PATH = Path(__file__).parent / "library.db"


# ── DB init ───────────────────────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def init_db() -> None:
    with _conn() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS books (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                title          TEXT    NOT NULL,
                author         TEXT    DEFAULT '',
                original_path  TEXT    UNIQUE NOT NULL,
                converted_path TEXT,
                size_kb        INTEGER DEFAULT 0,
                date_added     TEXT,
                date_converted TEXT,
                date_sent      TEXT
            )
        """)


# ── EPUB metadata ─────────────────────────────────────────────────────────────

def epub_metadata(path: str) -> dict:
    try:
        with zipfile.ZipFile(path) as z:
            xml_str = z.read("META-INF/container.xml").decode("utf-8", errors="replace")
            root = ET.fromstring(xml_str)
            ns_c = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
            opf_path = root.find(".//c:rootfile", ns_c).get("full-path")
            opf_xml = z.read(opf_path).decode("utf-8", errors="replace")
            opf = ET.fromstring(opf_xml)
            ns_dc = {"dc": "http://purl.org/dc/elements/1.1/"}
            t = opf.find(".//dc:title", ns_dc)
            a = opf.find(".//dc:creator", ns_dc)
            return {
                "title":  (t.text or "").strip() or Path(path).stem,
                "author": (a.text or "").strip() if a is not None else "",
            }
    except Exception:
        return {"title": Path(path).stem, "author": ""}


# ── Folder scanning ───────────────────────────────────────────────────────────

def scan_folder(folder: str, recursive: bool = False) -> list[Path]:
    p = Path(folder)
    if not p.is_dir():
        return []
    pattern = "**/*.epub" if recursive else "*.epub"
    return sorted(p.glob(pattern), key=lambda f: f.name.lower())


# ── Library CRUD ──────────────────────────────────────────────────────────────

def add_book(epub_path: str) -> bool:
    """Returns True if newly added, False if already in library."""
    init_db()
    meta = epub_metadata(epub_path)
    size_kb = Path(epub_path).stat().st_size // 1024
    now = datetime.now().isoformat(timespec="seconds")
    try:
        with _conn() as db:
            db.execute(
                """INSERT INTO books (title, author, original_path, size_kb, date_added)
                   VALUES (?, ?, ?, ?, ?)""",
                (meta["title"], meta["author"], str(Path(epub_path).resolve()), size_kb, now),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def add_books(paths: list[Path]) -> tuple[int, int]:
    """Bulk add. Returns (new, duplicates)."""
    new = sum(1 for p in paths if add_book(str(p)))
    return new, len(paths) - new


def mark_converted(book_id: int, azw3_path: str) -> None:
    with _conn() as db:
        db.execute(
            "UPDATE books SET converted_path=?, date_converted=? WHERE id=?",
            (str(Path(azw3_path).resolve()), datetime.now().isoformat(timespec="seconds"), book_id),
        )


def mark_sent(book_id: int) -> None:
    with _conn() as db:
        db.execute(
            "UPDATE books SET date_sent=? WHERE id=?",
            (datetime.now().isoformat(timespec="seconds"), book_id),
        )


def delete_books(ids: list[int]) -> None:
    with _conn() as db:
        db.executemany("DELETE FROM books WHERE id=?", [(i,) for i in ids])


def get_all() -> pd.DataFrame:
    init_db()
    with _conn() as db:
        rows = db.execute("""
            SELECT id, title, author, original_path, converted_path,
                   size_kb, date_added, date_converted, date_sent
            FROM books ORDER BY date_added DESC
        """).fetchall()

    columns = ["id", "Título", "Autor", "EPUB", "AZW3",
               "KB", "Agregado", "Convertido", "Enviado"]
    df = pd.DataFrame([dict(r) for r in rows], columns=columns)

    # Shorten datetime strings for display
    for col in ("Agregado", "Convertido", "Enviado"):
        df[col] = df[col].apply(
            lambda v: v[:16].replace("T", " ") if isinstance(v, str) else ""
        )
    return df
