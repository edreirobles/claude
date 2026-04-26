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
import library as lib
from extractor import PDFExtractor
from builder import EPUBBuilder
from azw3 import calibre_available, epub_to_azw3, CALIBRE_DOWNLOAD_URL
from sender import send_to_kindle, SMTP_PRESETS


# ── Page config ────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="PDF → Kindle",
    page_icon="📚",
    layout="wide",
)

st.markdown("""
<style>
    section[data-testid="stSidebar"] { min-width: 300px; }
    .stDownloadButton > button {
        width: 100%;
        background-color: #FF9900 !important;
        color: white !important;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

_calibre_ok = calibre_available()

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
        "Para Gmail usá una [App Password]"
        "(https://myaccount.google.com/apppasswords)."
    )

    preset_name = st.selectbox(
        "Proveedor",
        options=list(SMTP_PRESETS.keys()),
        index=list(SMTP_PRESETS.keys()).index(app_cfg.get("smtp_preset", "Gmail")),
    )
    preset = SMTP_PRESETS[preset_name]
    sender_email = st.text_input("Email remitente", value=app_cfg.get("sender_email", ""))
    sender_password = st.text_input(
        "Contraseña / App Password", value=app_cfg.get("sender_password", ""), type="password"
    )

    if preset_name == "Custom":
        smtp_host = st.text_input("SMTP host", value=app_cfg.get("smtp_host", ""))
        smtp_port = st.number_input("Puerto", value=int(app_cfg.get("smtp_port", 587)), step=1)
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
        st.success("Guardado ✓")

    if not cfg_module.is_configured(app_cfg):
        st.warning("Completá la configuración para enviar al Kindle.", icon="⚠️")

    if not _calibre_ok:
        st.warning(
            f"Calibre no encontrado. [Descargar]({CALIBRE_DOWNLOAD_URL}) para habilitar AZW3.",
            icon="⚠️",
        )


# ── Tabs ──────────────────────────────────────────────────────────────────────

tab_pdf, tab_lib = st.tabs(["📄  PDF → Kindle", "📚  Mi Librería"])


# ════════════════════════════════════════════════════════════════════════════════
# TAB 1 — PDF converter
# ════════════════════════════════════════════════════════════════════════════════

with tab_pdf:
    st.title("📄 PDF → Kindle")
    st.caption("Convierte papers académicos — reordena columnas, escala imágenes y extrae tablas.")
    st.divider()

    uploaded = st.file_uploader("Arrastrá tu PDF aquí", type=["pdf"])

    col_fmt, col_p1, col_p2 = st.columns([2, 1, 1])
    with col_fmt:
        fmt_options = ["AZW3 (nativo Kindle)", "EPUB"]
        fmt_choice = st.selectbox(
            "Formato",
            options=fmt_options,
            index=0 if _calibre_ok else 1,
        )
        want_azw3 = fmt_choice.startswith("AZW3") and _calibre_ok
    with col_p1:
        page_from = st.number_input("Desde página", min_value=1, value=1, step=1)
    with col_p2:
        page_to = st.number_input("Hasta página", min_value=1, value=999, step=1)

    if uploaded:
        out_ext = "azw3" if want_azw3 else "epub"
        c1, c2 = st.columns(2)
        with c1:
            convert_btn = st.button(f"Convertir a {out_ext.upper()}", type="primary", use_container_width=True)
        with c2:
            send_btn = st.button(
                "⚡ Convertir y enviar al Kindle",
                type="primary",
                use_container_width=True,
                disabled=not cfg_module.is_configured(app_cfg),
            )

        if convert_btn or send_btn:
            stem = Path(uploaded.name).stem
            out_name = f"{stem}.{out_ext}"

            with tempfile.TemporaryDirectory() as tmpdir:
                pdf_path = os.path.join(tmpdir, uploaded.name)
                with open(pdf_path, "wb") as f:
                    f.write(uploaded.getbuffer())

                epub_path = os.path.join(tmpdir, f"{stem}.epub")
                out_path = os.path.join(tmpdir, out_name)

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

                progress.progress(30, text="Construyendo EPUB…")
                try:
                    builder = EPUBBuilder(doc)
                    builder.build(epub_path)
                except Exception as e:
                    st.error(f"Error al generar el EPUB: {e}")
                    st.stop()

                if want_azw3:
                    progress.progress(60, text="Convirtiendo a AZW3…")
                    try:
                        epub_to_azw3(epub_path, out_path)
                    except RuntimeError as e:
                        st.error(str(e))
                        st.stop()
                else:
                    out_path = epub_path

                if send_btn:
                    progress.progress(85, text="Enviando al Kindle…")
                    loaded = cfg_module.load()
                    try:
                        send_to_kindle(
                            out_path, loaded["kindle_email"], loaded["sender_email"],
                            loaded["sender_password"], loaded["smtp_host"], int(loaded["smtp_port"]),
                        )
                    except Exception as e:
                        st.error(f"Error al enviar: {e}")
                        st.stop()

                progress.progress(100, text="¡Listo!")

                cols = st.columns(4)
                for col, (lbl, val) in zip(cols, [
                    ("Título",   doc.title[:28] + ("…" if len(doc.title) > 28 else "")),
                    ("Páginas",  f"{len(doc.pages)} / {total_pages}"),
                    ("Imágenes", str(len(builder._images))),
                    ("Tamaño",   f"{os.path.getsize(out_path) // 1024} KB"),
                ]):
                    col.metric(lbl, val)

                if send_btn:
                    st.success(f"Enviado a **{cfg_module.load()['kindle_email']}** ✓")

                st.divider()
                mime = "application/x-mobi8-ebook" if want_azw3 else "application/epub+zip"
                with open(out_path, "rb") as f:
                    st.download_button(
                        f"⬇️  Descargar {out_ext.upper()}",
                        f.read(), out_name, mime, use_container_width=True,
                    )
    else:
        st.info("Subí un PDF para comenzar.")


# ════════════════════════════════════════════════════════════════════════════════
# TAB 2 — Library
# ════════════════════════════════════════════════════════════════════════════════

with tab_lib:
    st.title("📚 Mi Librería")

    # ── Folder scanner ────────────────────────────────────────────────────────

    with st.expander("➕  Agregar EPUBs", expanded=True):
        st.caption("Seleccioná uno o varios archivos EPUB — podés usar Ctrl+click para elegir múltiples.")
        uploaded_epubs = st.file_uploader(
            "Archivos EPUB",
            type=["epub"],
            accept_multiple_files=True,
            label_visibility="collapsed",
        )

        if uploaded_epubs:
            import pandas as pd

            # Save uploaded files to a local library folder so we can track paths
            library_dir = Path(__file__).parent / "epub_library"
            library_dir.mkdir(exist_ok=True)

            preview_df = pd.DataFrame({
                "✓": [True] * len(uploaded_epubs),
                "Archivo": [f.name for f in uploaded_epubs],
                "Tamaño": [f"{len(f.getvalue()) // 1024} KB" for f in uploaded_epubs],
            })
            edited_preview = st.data_editor(
                preview_df,
                use_container_width=True,
                hide_index=True,
                column_config={"✓": st.column_config.CheckboxColumn("", width="small")},
                key="upload_editor",
            )
            selected_uploads = [
                uploaded_epubs[i]
                for i, checked in enumerate(edited_preview["✓"])
                if checked
            ]

            if st.button(
                f"Agregar {len(selected_uploads)} archivo(s) a la librería",
                disabled=len(selected_uploads) == 0,
                type="primary",
                use_container_width=True,
            ):
                saved = []
                for f in selected_uploads:
                    dest = library_dir / f.name
                    dest.write_bytes(f.getvalue())
                    saved.append(dest)
                new, dupes = lib.add_books(saved)
                st.success(
                    f"✓ {new} nuevo(s) agregado(s)"
                    + (f" · {dupes} ya existían" if dupes else "")
                )
                st.rerun()

        st.divider()
        st.caption("¿Tenés los EPUBs en una carpeta? Pegá la ruta y escaneá.")
        col_path, col_rec = st.columns([4, 1])
        with col_path:
            folder_input = st.text_input(
                "Ruta",
                placeholder=r"C:\Users\victo\Documents\Libros",
                label_visibility="collapsed",
            )
        with col_rec:
            recursive = st.checkbox("Subcarpetas")

        if st.button("🔍 Escanear carpeta", use_container_width=True) and folder_input:
            found = lib.scan_folder(folder_input.strip(), recursive)
            st.session_state["found_epubs"] = [str(p) for p in found]

        if "found_epubs" in st.session_state:
            found_paths = st.session_state["found_epubs"]
            if not found_paths:
                st.warning("No se encontraron archivos EPUB en esa carpeta.")
            else:
                import pandas as pd
                st.caption(f"Se encontraron **{len(found_paths)}** archivos EPUB:")
                found_df = pd.DataFrame({
                    "✓": [True] * len(found_paths),
                    "Archivo": [Path(p).name for p in found_paths],
                    "Carpeta": [str(Path(p).parent) for p in found_paths],
                })
                edited_found = st.data_editor(
                    found_df,
                    use_container_width=True,
                    hide_index=True,
                    column_config={"✓": st.column_config.CheckboxColumn("", width="small")},
                    key="found_editor",
                )
                selected_paths = [
                    found_paths[i]
                    for i, checked in enumerate(edited_found["✓"])
                    if checked
                ]
                col_add, col_clear = st.columns([3, 1])
                with col_add:
                    if st.button(
                        f"Agregar {len(selected_paths)} archivo(s) a la librería",
                        disabled=len(selected_paths) == 0,
                        type="primary",
                        use_container_width=True,
                    ):
                        new, dupes = lib.add_books([Path(p) for p in selected_paths])
                        st.success(f"✓ {new} nuevo(s)" + (f" · {dupes} ya existían" if dupes else ""))
                        del st.session_state["found_epubs"]
                        st.rerun()
                with col_clear:
                    if st.button("Limpiar", use_container_width=True):
                        del st.session_state["found_epubs"]
                        st.rerun()

    st.divider()

    # ── Library table ─────────────────────────────────────────────────────────

    df = lib.get_all()

    if df.empty:
        st.info("La librería está vacía. Agregá EPUBs desde el panel de arriba.")
    else:
        st.caption(f"**{len(df)} libro(s)** en la librería")

        display_df = df[["Título", "Autor", "KB", "Agregado", "Convertido", "Enviado"]].copy()
        display_df.insert(0, "✓", False)

        edited_lib = st.data_editor(
            display_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "✓":          st.column_config.CheckboxColumn("", width="small"),
                "Título":     st.column_config.TextColumn(width="large"),
                "Autor":      st.column_config.TextColumn(width="medium"),
                "Convertido": st.column_config.TextColumn(width="medium"),
                "Enviado":    st.column_config.TextColumn(width="medium"),
            },
            key="lib_editor",
        )

        selected_ids = df[edited_lib["✓"]]["id"].tolist()
        n_sel = len(selected_ids)

        if n_sel > 0:
            st.caption(f"**{n_sel}** libro(s) seleccionado(s)")
        else:
            st.caption("Seleccioná libros con el checkbox para acciones en bulk.")

        col_conv, col_send, col_del = st.columns(3)

        # ── Bulk convert ──────────────────────────────────────────────────────
        with col_conv:
            conv_lib_btn = st.button(
                f"Convertir a AZW3 ({n_sel})" if n_sel else "Convertir a AZW3",
                disabled=(n_sel == 0 or not _calibre_ok),
                use_container_width=True,
                type="primary",
            )

        # ── Bulk send ─────────────────────────────────────────────────────────
        with col_send:
            send_lib_btn = st.button(
                f"⚡ Enviar al Kindle ({n_sel})" if n_sel else "⚡ Enviar al Kindle",
                disabled=(n_sel == 0 or not cfg_module.is_configured(app_cfg)),
                use_container_width=True,
                type="primary",
            )

        # ── Delete ────────────────────────────────────────────────────────────
        with col_del:
            del_btn = st.button(
                f"🗑️  Eliminar ({n_sel})" if n_sel else "🗑️  Eliminar",
                disabled=n_sel == 0,
                use_container_width=True,
            )

        # ── Actions ───────────────────────────────────────────────────────────

        if del_btn and selected_ids:
            lib.delete_books(selected_ids)
            st.success(f"{n_sel} libro(s) eliminado(s) de la librería.")
            st.rerun()

        if conv_lib_btn and selected_ids:
            selected_rows = df[df["id"].isin(selected_ids)]
            prog = st.progress(0, text="Iniciando conversión…")
            errors = []

            for i, (_, row) in enumerate(selected_rows.iterrows()):
                epub_path = row["EPUB"]
                prog.progress((i) / len(selected_rows), text=f"Convirtiendo: {row['Título'][:50]}…")

                if not Path(epub_path).exists():
                    errors.append(f"Archivo no encontrado: {epub_path}")
                    continue

                azw3_path = str(Path(epub_path).with_suffix(".azw3"))
                try:
                    epub_to_azw3(epub_path, azw3_path)
                    lib.mark_converted(int(row["id"]), azw3_path)
                except Exception as e:
                    errors.append(f"{row['Título']}: {e}")

            prog.progress(1.0, text="¡Conversión completada!")

            if errors:
                for err in errors:
                    st.error(err)
            else:
                st.success(f"✓ {len(selected_rows)} libro(s) convertidos a AZW3.")
            st.rerun()

        if send_lib_btn and selected_ids:
            selected_rows = df[df["id"].isin(selected_ids)]
            loaded_cfg = cfg_module.load()
            prog = st.progress(0, text="Preparando envío…")
            errors = []

            for i, (_, row) in enumerate(selected_rows.iterrows()):
                prog.progress(i / len(selected_rows), text=f"Enviando: {row['Título'][:50]}…")

                # Prefer AZW3 if already converted, else use EPUB
                send_path = row["AZW3"] if (row["AZW3"] and Path(str(row["AZW3"])).exists()) else row["EPUB"]

                if not send_path or not Path(str(send_path)).exists():
                    errors.append(f"Archivo no encontrado: {row['Título']}")
                    continue

                try:
                    send_to_kindle(
                        str(send_path),
                        loaded_cfg["kindle_email"],
                        loaded_cfg["sender_email"],
                        loaded_cfg["sender_password"],
                        loaded_cfg["smtp_host"],
                        int(loaded_cfg["smtp_port"]),
                    )
                    lib.mark_sent(int(row["id"]))
                except Exception as e:
                    errors.append(f"{row['Título']}: {e}")

            prog.progress(1.0, text="¡Envío completado!")

            if errors:
                for err in errors:
                    st.error(err)
            else:
                st.success(
                    f"✓ {len(selected_rows)} libro(s) enviados a **{loaded_cfg['kindle_email']}**."
                )
            st.rerun()
