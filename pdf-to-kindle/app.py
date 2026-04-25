"""
Streamlit frontend for the PDF → Kindle EPUB converter.

Run:
    streamlit run app.py
"""

import os
import tempfile
from pathlib import Path

import streamlit as st

from extractor import PDFExtractor
from builder import EPUBBuilder


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
    .stat-box {
        background: #f8f9fa;
        border-radius: 8px;
        padding: 0.8rem 1.2rem;
        margin-bottom: 0.5rem;
        border-left: 4px solid #FF9900;
    }
</style>
""", unsafe_allow_html=True)

st.title("📚 PDF → Kindle")
st.caption("Convierte papers académicos a EPUB optimizado para Kindle — reordena columnas, escala imágenes y extrae tablas.")

st.divider()

# ── Upload ────────────────────────────────────────────────────────────────────

uploaded = st.file_uploader(
    "Arrastrá tu PDF aquí",
    type=["pdf"],
    help="Soporta papers en doble columna, con tablas e imágenes.",
)

# ── Options ───────────────────────────────────────────────────────────────────

with st.expander("Opciones avanzadas"):
    col1, col2 = st.columns(2)
    with col1:
        page_from = st.number_input("Desde página", min_value=1, value=1, step=1)
    with col2:
        page_to = st.number_input(
            "Hasta página", min_value=1, value=999, step=1,
            help="Dejá en 999 para convertir todo el documento.",
        )

# ── Convert ───────────────────────────────────────────────────────────────────

if uploaded:
    convert_btn = st.button("Convertir a EPUB", type="primary", use_container_width=True)

    if convert_btn:
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write PDF to disk
            pdf_path = os.path.join(tmpdir, uploaded.name)
            with open(pdf_path, "wb") as f:
                f.write(uploaded.getbuffer())

            epub_name = Path(uploaded.name).stem + ".epub"
            epub_path = os.path.join(tmpdir, epub_name)

            # Step 1 – parse
            progress = st.progress(0, text="Analizando PDF…")
            try:
                extractor = PDFExtractor(pdf_path)
                doc = extractor.extract()
            except Exception as e:
                st.error(f"Error al leer el PDF: {e}")
                st.stop()

            # Apply page range
            total_pages = len(doc.pages)
            if page_from > 1 or page_to < 999:
                doc.pages = [
                    p for p in doc.pages
                    if page_from <= p.number + 1 <= page_to
                ]

            if not doc.pages:
                st.error("El rango de páginas seleccionado no contiene contenido.")
                st.stop()

            progress.progress(40, text="Construyendo EPUB…")

            # Step 2 – build
            try:
                builder = EPUBBuilder(doc)
                builder.build(epub_path)
            except Exception as e:
                st.error(f"Error al generar el EPUB: {e}")
                st.stop()

            progress.progress(100, text="¡Listo!")

            # Stats
            n_images = len(builder._images)
            n_blocks = sum(len(p.blocks) for p in doc.pages)
            epub_kb = os.path.getsize(epub_path) // 1024

            st.success(f"Conversión exitosa")

            cols = st.columns(4)
            stats = [
                ("Título", doc.title[:30] + ("…" if len(doc.title) > 30 else "")),
                ("Páginas", f"{len(doc.pages)} / {total_pages}"),
                ("Imágenes", str(n_images)),
                ("Tamaño", f"{epub_kb} KB"),
            ]
            for col, (label, value) in zip(cols, stats):
                col.metric(label, value)

            # Download
            st.divider()
            with open(epub_path, "rb") as f:
                epub_bytes = f.read()

            st.download_button(
                label="⬇️  Descargar EPUB",
                data=epub_bytes,
                file_name=epub_name,
                mime="application/epub+zip",
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
