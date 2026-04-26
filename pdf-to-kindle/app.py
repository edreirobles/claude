"""
Streamlit frontend for the PDF → Kindle converter.

Run:
    streamlit run app.py
"""

import os
import tempfile
from pathlib import Path

import streamlit as st

import config as cfg_module
from extractor import PDFExtractor
from builder import EPUBBuilder
from azw3 import calibre_available, epub_to_azw3, CALIBRE_DOWNLOAD_URL
from sender import send_to_kindle, SMTP_PRESETS


# ── Page config ────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="PDF → Kindle",
    page_icon="📚",
    layout="centered",
)

st.markdown("""
<style>
    .block-container { max-width: 740px; padding-top: 2rem; }
    .stDownloadButton > button, div[data-testid="stButton"] > button[kind="primary"] {
        width: 100%;
        background-color: #FF9900;
        color: white;
        font-weight: 600;
        font-size: 1.05rem;
        padding: 0.6rem 1rem;
        border: none;
        border-radius: 6px;
    }
</style>
""", unsafe_allow_html=True)

st.title("📚 PDF → Kindle")
st.caption(
    "Convierte papers académicos a formato Kindle — "
    "reordena columnas dobles, escala imágenes y extrae tablas."
)

# ── Sidebar: settings ─────────────────────────────────────────────────────────

with st.sidebar:
    st.header("⚙️ Configuración")

    app_cfg = cfg_module.load()

    kindle_email = st.text_input(
        "Tu email de Kindle",
        value=app_cfg.get("kindle_email", ""),
        placeholder="tuname@kindle.com",
    )

    st.markdown("---")
    st.subheader("Email remitente")
    st.caption(
        "Usá el email desde el que querés enviar. "
        "Para Gmail necesitás una **App Password** "
        "([cómo crearla](https://myaccount.google.com/apppasswords))."
    )

    preset_name = st.selectbox(
        "Proveedor",
        options=list(SMTP_PRESETS.keys()),
        index=list(SMTP_PRESETS.keys()).index(app_cfg.get("smtp_preset", "Gmail")),
    )
    preset = SMTP_PRESETS[preset_name]

    sender_email = st.text_input(
        "Email remitente",
        value=app_cfg.get("sender_email", ""),
        placeholder="tu@gmail.com",
    )
    sender_password = st.text_input(
        "Contraseña / App Password",
        value=app_cfg.get("sender_password", ""),
        type="password",
    )

    if preset_name == "Custom":
        smtp_host = st.text_input("SMTP host", value=app_cfg.get("smtp_host", ""))
        smtp_port = st.number_input("Puerto", value=app_cfg.get("smtp_port", 587), step=1)
    else:
        smtp_host = preset["host"]
        smtp_port = preset["port"]
        st.caption(f"SMTP: `{smtp_host}:{smtp_port}`")

    if st.button("Guardar configuración", use_container_width=True):
        new_cfg = {
            "kindle_email": kindle_email.strip(),
            "sender_email": sender_email.strip(),
            "sender_password": sender_password,
            "smtp_preset": preset_name,
            "smtp_host": smtp_host,
            "smtp_port": int(smtp_port),
        }
        cfg_module.save(new_cfg)
        app_cfg = new_cfg
        st.success("Guardado")

    # Warn if not yet configured
    if not cfg_module.is_configured(app_cfg):
        st.warning("Completá la configuración para poder enviar al Kindle.", icon="⚠️")


# ── Main area ─────────────────────────────────────────────────────────────────

st.divider()

uploaded = st.file_uploader(
    "Arrastrá tu PDF aquí",
    type=["pdf"],
    help="Soporta papers en doble columna, con tablas e imágenes.",
)

_calibre_ok = calibre_available()

col_fmt, col_pages1, col_pages2 = st.columns([2, 1, 1])

with col_fmt:
    fmt_options = ["AZW3 (nativo Kindle)", "EPUB"]
    fmt_choice = st.selectbox(
        "Formato de salida",
        options=fmt_options,
        index=0 if _calibre_ok else 1,
        help=(
            "AZW3 es el formato nativo de Kindle. Requiere Calibre instalado."
            if _calibre_ok
            else f"AZW3 requiere [Calibre]({CALIBRE_DOWNLOAD_URL}). Por ahora solo EPUB."
        ),
    )
    want_azw3 = fmt_choice.startswith("AZW3") and _calibre_ok

with col_pages1:
    page_from = st.number_input("Desde página", min_value=1, value=1, step=1)
with col_pages2:
    page_to = st.number_input("Hasta página", min_value=1, value=999, step=1)

if want_azw3 and not _calibre_ok:
    st.warning(
        f"Calibre no encontrado. [Descargar]({CALIBRE_DOWNLOAD_URL}). "
        "Generando EPUB como alternativa.",
        icon="⚠️",
    )

# ── Convert & Send ────────────────────────────────────────────────────────────

if uploaded:
    out_ext = "azw3" if want_azw3 else "epub"
    col_btn1, col_btn2 = st.columns(2)

    with col_btn1:
        convert_btn = st.button(
            f"Convertir a {out_ext.upper()}",
            type="primary",
            use_container_width=True,
        )
    with col_btn2:
        send_btn = st.button(
            "⚡ Convertir y enviar al Kindle",
            type="primary",
            use_container_width=True,
            disabled=not cfg_module.is_configured(app_cfg),
            help="Requiere completar la configuración en el panel izquierdo."
            if not cfg_module.is_configured(app_cfg)
            else None,
        )

    do_convert = convert_btn or send_btn
    do_send = send_btn

    if do_convert:
        stem = Path(uploaded.name).stem
        out_name = f"{stem}.{out_ext}"

        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = os.path.join(tmpdir, uploaded.name)
            with open(pdf_path, "wb") as f:
                f.write(uploaded.getbuffer())

            epub_path = os.path.join(tmpdir, f"{stem}.epub")
            out_path = os.path.join(tmpdir, out_name)

            # Step 1 – parse
            progress = st.progress(0, text="Analizando PDF…")
            try:
                extractor = PDFExtractor(pdf_path)
                doc = extractor.extract()
            except Exception as e:
                st.error(f"Error al leer el PDF: {e}")
                st.stop()

            total_pages = len(doc.pages)
            if page_from > 1 or page_to < 999:
                doc.pages = [p for p in doc.pages if page_from <= p.number + 1 <= page_to]
            if not doc.pages:
                st.error("El rango de páginas no contiene contenido.")
                st.stop()

            # Step 2 – build EPUB
            progress.progress(30, text="Construyendo EPUB…")
            try:
                builder = EPUBBuilder(doc)
                builder.build(epub_path)
            except Exception as e:
                st.error(f"Error al generar el EPUB: {e}")
                st.stop()

            # Step 3 – convert to AZW3
            if want_azw3:
                progress.progress(60, text="Convirtiendo a AZW3 con Calibre…")
                try:
                    epub_to_azw3(epub_path, out_path)
                except RuntimeError as e:
                    st.error(str(e))
                    st.stop()
            else:
                out_path = epub_path

            # Step 4 – send if requested
            if do_send:
                progress.progress(85, text="Enviando al Kindle…")
                loaded_cfg = cfg_module.load()
                try:
                    send_to_kindle(
                        file_path=out_path,
                        kindle_email=loaded_cfg["kindle_email"],
                        sender_email=loaded_cfg["sender_email"],
                        sender_password=loaded_cfg["sender_password"],
                        smtp_host=loaded_cfg["smtp_host"],
                        smtp_port=int(loaded_cfg["smtp_port"]),
                    )
                except Exception as e:
                    st.error(f"Error al enviar: {e}")
                    st.stop()

            progress.progress(100, text="¡Listo!")

            # ── Stats ──────────────────────────────────────────────────────────
            n_images = len(builder._images)
            out_kb = os.path.getsize(out_path) // 1024

            if do_send:
                loaded_cfg = cfg_module.load()
                st.success(
                    f"Enviado a **{loaded_cfg['kindle_email']}** — "
                    "debería aparecer en tu Kindle en unos segundos."
                )
            else:
                st.success("Conversión exitosa")

            cols = st.columns(4)
            for col, (label, value) in zip(cols, [
                ("Título",   doc.title[:28] + ("…" if len(doc.title) > 28 else "")),
                ("Páginas",  f"{len(doc.pages)} / {total_pages}"),
                ("Imágenes", str(n_images)),
                ("Tamaño",   f"{out_kb} KB"),
            ]):
                col.metric(label, value)

            # ── Download button (always shown as fallback) ─────────────────────
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
else:
    st.info("Subí un PDF para comenzar.")
