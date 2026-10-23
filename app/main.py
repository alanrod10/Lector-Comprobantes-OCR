"""Punto de entrada principal de la aplicación Streamlit Lector Inteligente de Comprobantes."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# Asegurar que la raíz del proyecto esté en sys.path al ejecutar `streamlit run app/main.py`
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import streamlit as st

from app.extract_llm import UI_LLM_PRIVACY_NOTICE
from app.storage import StorageManager
from app.ui import (
    inyectar_css_movil,
    render_tab_ajustes,
    render_tab_escanear,
    render_tab_evaluacion,
    render_tab_historial,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def main() -> None:
    st.set_page_config(
        page_title="Lector Inteligente de Comprobantes",
        page_icon="🧾",
        layout="centered",
        initial_sidebar_state="collapsed",
    )
    inyectar_css_movil()

    storage = StorageManager()

    st.title("🧾 Lector de Comprobantes")

    # Mostrar una vez por sesión el aviso sobre comprobantes ficticios o autorizados y envío de datos LLM
    if not st.session_state.get("aviso_sesion_mostrado", False):
        st.info(
            "🔒 **Aviso de privacidad de la sesión:** Usá esta aplicación únicamente con comprobantes "
            "propios, ficticios o con autorización expresa. Por defecto todo el procesamiento ocurre "
            f"localmente en tu equipo. {UI_LLM_PRIVACY_NOTICE}"
        )
        st.session_state["aviso_sesion_mostrado"] = True

    tab_escanear, tab_historial, tab_eval, tab_ajustes = st.tabs(
        ["📷 Escanear", "🗂️ Historial", "📊 Evaluación", "⚙️ Ajustes"]
    )

    with tab_escanear:
        render_tab_escanear(storage)
    with tab_historial:
        render_tab_historial(storage)
    with tab_eval:
        render_tab_evaluacion(storage)
    with tab_ajustes:
        render_tab_ajustes(storage)


if __name__ == "__main__":
    main()
