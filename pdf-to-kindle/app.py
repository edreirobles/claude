"""
Streamlit frontend for the PDF → Kindle converter.

Run:
    streamlit run app.py
"""

import os
import tempfile
from pathlib import Path

import streamlit as st

from extractor import PDFExtractor
from builder import EPUBBuilder
from azw3 import calibre_available, epub_to_azw3, CALIBRE_DOWNLOAD_URL


# ── Page config ────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="PDF → Kindle",
    page_icon="📚",
    layout="centered",
)

st.markdown("""
<style>
    .block-container { max-width: 720px; padding-top: 2rem; }
    .stDownloadButton > button {
        width: 100%;
        background-color: #FF9900;
        color: white;
        font-weight: 600;
        font-size: 1.05rem;
        padding: 0.6rem 1rem;
        border: none;
        border-radius: 6px;
    }
    .stDownloadButton > button:hover { background-color: #e68a00; }
</style>
""", unsafe_allow_html=True)

st.title("📚 PDF → Kindle")
st.caption(
    "Convierte papers académicos a formato Kindle — "
    "reordena columnas dobles, escala imágenes y extrae tablas."
)

st.divider()

# ── Upload ────────────────────────────────────────────────────────────────────

uploaded = st.file_uploader(
    "Arrastrá tu PDF aquí",
    type=["pdf"],
    help="Soporta papers en doble columna, con tablas e imágenes.",
)

# ── Options ───────────────────────────────────────────────────────────────────

_calibre_ok = calibre_available()

col_fmt, col_pages1, col_pages2 = st.columns([2, 1, 1])

with col_fmt:
    fmt_options = ["AZW3 (nativo Kindle)", "EPUB"]
    fmt_help = (
        "AZW3 es el formato nativo de Kindle. Requiere Calibre instalado."
        if _calibre_ok
        else f"AZW3 requiere Calibre ([descargar]({CALIBRE_DOWNLOAD_URL})). "
             "Por ahora solo está disponible EPUB."
    )
    fmt_choice = st.selectbox(
        "Formato de salida",
        options=fmt_options,
        index=0 if _calibre_ok else 1,
        disabled=not _calibre_ok and True,   # allow selecting but warn below
        help=fmt_help,
    )
    want_azw3 = fmt_choice.startswith("AZW3")

with col_pages1:
    page_from = st.number_input("Desde página", min_value=1, value=1, step=1)
with col_pages2:
    page_to = st.number_input(
        "Hasta página", min_value=1, value=999, step=1,
        help="Dejá en 999 para el documento completo.",
    )

# Warn if AZW3 selected but Calibre missing
if want_azw3 and not _calibre_ok:
    st.warning(
        f"**Calibre no encontrado.** Para generar AZW3 instalá Calibre: "
        f"{CALIBRE_DOWNLOAD_URL}  \n"
        "Podés convertir a EPUB ahora y luego convertir manualmente con Calibre.",
        icon="⚠️",
    )
    want_azw3 = False   # fall back silently to EPUB

# ── Convert ───────────────────────────────────────────────────────────────────

if uploaded:
    btn_label = f"Convertir a {'AZW3' if want_azw3 else 'EPUB'}"
    convert_btn = st.button(btn_label, type="primary", use_container_width=True)

    if convert_btn:
        stem = Path(uploaded.name).stem
        out_ext = "azw3" if want_azw3 else "epub"
        out_name = f"{stem}.{out_ext}"

        with tempfile.TemporaryDirectory() as tmpdir:
            # Save PDF
            pdf_path = os.path.join(tmpdir, uploaded.name)
            with open(pdf_path, "wb") as f:
                f.write(uploaded.getbuffer())

            epub_path = os.path.join(tmpdir, f"{stem}.epub")
            out_path = os.path.join(tmpdir, out_name)

            # Step 1 – parse PDF
            progress = st.progress(0, text="Analizando PDF…")
            try:
                extractor = PDFExtractor(pdf_path)
                doc = extractor.extract()
            except Exception as e:
                st.error(f"Error al leer el PDF: {e}")
                st.stop()

            total_pages = len(doc.pages)
            if page_from > 1 or page_to < 999:
                doc.pages = [
                    p for p in doc.pages
                    if page_from <= p.number + 1 <= page_to
                ]
            if not doc.pages:
                st.error("El rango de páginas no contiene contenido.")
                st.stop()

            # Step 2 – build EPUB
            progress.progress(35, text="Construyendo EPUB…")
            try:
                builder = EPUBBuilder(doc)
                builder.build(epub_path)
            except Exception as e:
                st.error(f"Error al generar el EPUB: {e}")
                st.stop()

            # Step 3 – convert to AZW3 if requested
            if want_azw3:
                progress.progress(70, text="Convirtiendo a AZW3 con Calibre…")
                try:
                    epub_to_azw3(epub_path, out_path)
                except RuntimeError as e:
                    st.error(str(e))
                    st.stop()
            else:
                out_path = epub_path

            progress.progress(100, text="¡Listo!")

            # Stats
            n_images = len(builder._images)
            out_kb = os.path.getsize(out_path) // 1024

            st.success("Conversión exitosa")

            cols = st.columns(4)
            stats = [
                ("Título", doc.title[:28] + ("…" if len(doc.title) > 28 else "")),
                ("Páginas", f"{len(doc.pages)} / {total_pages}"),
                ("Imágenes", str(n_images)),
                ("Tamaño", f"{out_kb} KB"),
            ]
            for col, (label, value) in zip(cols, stats):
                col.metric(label, value)

            # Download button
            st.divider()
            mime = "application/x-mobi8-ebook" if want_azw3 else "application/epub+zip"
            with open(out_path, "rb") as f:
                out_bytes = f.read()

            st.download_button(
                label=f"⬇️  Descargar {out_ext.upper()}",
                data=out_bytes,
                file_name=out_name,
                mime=mime,
                use_container_width=True,
            )

            st.caption(
                "**Cómo enviarlo al Kindle:** "
                "adjuntalo a un email a tu dirección Kindle personal · "
                "o usá la app *Send to Kindle* · "
                "o copialo a la carpeta `documents` por USB."
            )
else:
    st.info("Subí un PDF para comenzar.")
