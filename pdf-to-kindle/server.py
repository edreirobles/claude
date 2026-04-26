#!/usr/bin/env python3
"""PDF → Kindle — servidor local Flask.

Uso: py server.py
Abre http://localhost:5000 en el navegador.
"""

import os
import string
import tempfile
import threading
import webbrowser
from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory

import config as cfg_module
import library as lib
from azw3 import calibre_available, epub_to_azw3
from builder import EPUBBuilder
from extractor import PDFExtractor
from sender import send_to_kindle, SMTP_PRESETS

app = Flask(__name__, static_folder="static")
LIBRARY_DIR = Path(__file__).parent / "epub_library"
LIBRARY_DIR.mkdir(exist_ok=True)


# ── Static ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


# ── File system browser ───────────────────────────────────────────────────────

@app.route("/api/browse")
def browse():
    path = request.args.get("path", "")

    if not path:
        if os.name == "nt":
            drives = [
                {"name": f"{l}:", "path": f"{l}:\\", "is_dir": True, "is_epub": False}
                for l in string.ascii_uppercase
                if Path(f"{l}:\\").exists()
            ]
            return jsonify({"path": "", "parent": None, "items": drives})
        path = "/"

    p = Path(path)
    if not p.is_dir():
        return jsonify({"error": "No es un directorio"}), 400

    items = []
    try:
        entries = sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        for entry in entries:
            if entry.name.startswith(".") or entry.name == "__pycache__":
                continue
            items.append({
                "name": entry.name,
                "path": str(entry),
                "is_dir": entry.is_dir(),
                "is_epub": entry.suffix.lower() == ".epub",
            })
    except PermissionError:
        pass

    parent = str(p.parent) if str(p.parent) != str(p) else None
    return jsonify({"path": str(p), "parent": parent, "items": items})


# ── Library ───────────────────────────────────────────────────────────────────

@app.route("/api/library")
def get_library():
    df = lib.get_all()
    return jsonify(df.to_dict(orient="records"))


@app.route("/api/library/add", methods=["POST"])
def add_to_library():
    paths = request.json.get("paths", [])
    new, dupes = lib.add_books([Path(p) for p in paths])
    return jsonify({"new": new, "duplicates": dupes})


@app.route("/api/library/<int:book_id>", methods=["DELETE"])
def delete_book(book_id):
    lib.delete_books([book_id])
    return jsonify({"ok": True})


@app.route("/api/library/convert", methods=["POST"])
def convert_library():
    ids = request.json.get("ids", [])
    if not calibre_available():
        return jsonify({"error": "Calibre no instalado"}), 400

    df = lib.get_all()
    results = []
    for book_id in ids:
        rows = df[df["id"] == book_id]
        if rows.empty:
            continue
        row = rows.iloc[0]
        epub_path = row["EPUB"]
        if not Path(str(epub_path)).exists():
            results.append({"id": book_id, "error": f"Archivo no encontrado: {epub_path}"})
            continue
        azw3_path = str(Path(epub_path).with_suffix(".azw3"))
        try:
            epub_to_azw3(epub_path, azw3_path)
            lib.mark_converted(int(book_id), azw3_path)
            results.append({"id": book_id, "ok": True})
        except Exception as e:
            results.append({"id": book_id, "error": str(e)})

    return jsonify({"results": results})


@app.route("/api/library/send", methods=["POST"])
def send_library():
    ids = request.json.get("ids", [])
    cfg = cfg_module.load()
    if not cfg_module.is_configured(cfg):
        return jsonify({"error": "Email no configurado — andá a Configuración"}), 400

    df = lib.get_all()
    results = []
    for book_id in ids:
        rows = df[df["id"] == book_id]
        if rows.empty:
            continue
        row = rows.iloc[0]
        azw3 = row.get("AZW3")
        epub = row.get("EPUB")
        send_path = azw3 if (azw3 and Path(str(azw3)).exists()) else epub
        if not send_path or not Path(str(send_path)).exists():
            results.append({"id": book_id, "error": f"Archivo no encontrado: {row.get('Título')}"})
            continue
        try:
            send_to_kindle(
                str(send_path),
                cfg["kindle_email"], cfg["sender_email"],
                cfg["sender_password"], cfg["smtp_host"], int(cfg["smtp_port"]),
            )
            lib.mark_sent(int(book_id))
            results.append({"id": book_id, "ok": True})
        except Exception as e:
            results.append({"id": book_id, "error": str(e)})

    return jsonify({"results": results})


# ── Config ────────────────────────────────────────────────────────────────────

@app.route("/api/config")
def get_config():
    cfg = cfg_module.load()
    safe = dict(cfg)
    if safe.get("sender_password"):
        safe["sender_password"] = "••••••••••••••••"
    safe["calibre_available"] = calibre_available()
    safe["smtp_presets"] = list(SMTP_PRESETS.keys())
    return jsonify(safe)


@app.route("/api/config", methods=["POST"])
def save_config():
    data = request.json
    current = cfg_module.load()
    # Keep existing password if placeholder was sent
    if data.get("sender_password", "").startswith("•"):
        data["sender_password"] = current.get("sender_password", "")
    cfg_module.save({**current, **data})
    return jsonify({"ok": True})


# ── PDF conversion ────────────────────────────────────────────────────────────

@app.route("/api/pdf/convert", methods=["POST"])
def convert_pdf():
    if "file" not in request.files:
        return jsonify({"error": "No se recibió ningún archivo"}), 400

    f = request.files["file"]
    fmt = request.form.get("format", "epub")
    page_from = int(request.form.get("page_from", 1))
    page_to = int(request.form.get("page_to", 9999))
    do_send = request.form.get("send_to_kindle") == "1"

    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = os.path.join(tmpdir, f.filename)
        f.save(pdf_path)

        stem = Path(f.filename).stem
        epub_path = os.path.join(tmpdir, f"{stem}.epub")
        out_path = os.path.join(tmpdir, f"{stem}.{fmt}")

        try:
            extractor = PDFExtractor(pdf_path)
            doc = extractor.extract()
        except Exception as e:
            return jsonify({"error": f"Error al leer PDF: {e}"}), 500

        if page_from > 1 or page_to < 9999:
            doc.pages = [p for p in doc.pages if page_from <= p.number + 1 <= page_to]
        if not doc.pages:
            return jsonify({"error": "Sin contenido en el rango de páginas"}), 400

        try:
            builder = EPUBBuilder(doc)
            builder.build(epub_path)
        except Exception as e:
            return jsonify({"error": f"Error al generar EPUB: {e}"}), 500

        if fmt == "azw3":
            if not calibre_available():
                return jsonify({"error": "Calibre no instalado"}), 400
            try:
                epub_to_azw3(epub_path, out_path)
            except RuntimeError as e:
                return jsonify({"error": str(e)}), 500
        else:
            out_path = epub_path

        if do_send:
            cfg = cfg_module.load()
            if not cfg_module.is_configured(cfg):
                return jsonify({"error": "Email no configurado"}), 400
            try:
                send_to_kindle(
                    out_path, cfg["kindle_email"], cfg["sender_email"],
                    cfg["sender_password"], cfg["smtp_host"], int(cfg["smtp_port"]),
                )
                return jsonify({"ok": True, "sent_to": cfg["kindle_email"]})
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        mime = "application/epub+zip" if fmt == "epub" else "application/x-mobi8-ebook"
        return send_file(
            out_path,
            as_attachment=True,
            download_name=f"{stem}.{fmt}",
            mimetype=mime,
        )


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    url = "http://localhost:5000"
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f"\n  PDF → Kindle  →  {url}\n  Cerrá esta ventana para detener el servidor.\n")
    app.run(host="127.0.0.1", port=5000, debug=False)
