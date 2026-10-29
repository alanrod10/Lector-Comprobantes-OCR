"""Componentes de interfaz mobile-first en Streamlit, estilos CSS táctiles y orquestación de vistas."""
from __future__ import annotations

import hashlib
import logging
import time
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

from app.config import (
    BASE_DIR,
    CONFIDENCE_THRESHOLD_P2,
    LLM_API_KEY,
    LLM_PROVIDER,
    MIN_VALID_DATE,
)
from app.export import exportar_csv, exportar_xlsx, resultados_a_filas_planas
from app.extract_llm import (
    UI_LLM_PRIVACY_NOTICE,
    construir_extractor_llm,
    extraer_con_llm_con_reintento,
)
from app.extract_rules import extraer_por_reglas
from app.locale_ar import normalizar_monto
from app.merge import fusionar_reglas_y_llm
from app.models import (
    CAMPOS_SIMPLES_ORDEN,
    Campo,
    Comprobante,
    ItemImpuesto,
    ItemIVA,
    Resultado,
)
from app.ocr import OCRError, ejecutar_ocr_mejores_variantes
from app.preprocess import PreprocessError, PreprocessOutput, preprocesar_bytes
from app.storage import StorageManager
from app.validators import ejecutar_validaciones

logger = logging.getLogger(__name__)

ETIQUETAS_CAMPOS: Dict[str, str] = {
    "fecha_emision": "Fecha de emisión (AAAA-MM-DD)",
    "proveedor_razon_social": "Razón social del proveedor",
    "proveedor_cuit": "CUIT del proveedor (11 dígitos sin guiones)",
    "tipo_comprobante": "Tipo de comprobante",
    "letra": "Letra (A, B, C, M, X)",
    "punto_venta": "Punto de venta (hasta 5 dígitos)",
    "numero_comprobante": "Número de comprobante (hasta 8 dígitos)",
    "importe_neto_gravado": "Importe neto gravado",
    "importe_total": "Importe total",
    "moneda": "Moneda (ISO 4217: ARS, USD, EUR)",
    "cae": "CAE (14 dígitos)",
    "iva": "Desglose de IVA",
    "otros_impuestos": "Otros impuestos y percepciones",
}


MOBILE_CSS = """
<style>
:root {
    color-scheme: light;
}

/* =========================================================
   1. IDENTIDAD GLOBAL
   Azul noche -> azul profundo -> azul cobalto
   ========================================================= */

.stApp {
    background: #F3F6FC;
    color: #12233F;
}
/* =========================================================
   ENCABEZADO PRINCIPAL — IDENTIDAD VISUAL
   ========================================================= */

.hero-header {
    position: relative;
    isolation: isolate;
    overflow: hidden;
    margin: 0 0 1.6rem;
    padding: clamp(1.5rem, 4vw, 2.75rem);
    border: 1px solid rgba(255, 255, 255, 0.16);
    border-radius: 22px;
    background: linear-gradient(
        118deg,
        #081A33 0%,
        #123E7C 43%,
        #155EEF 76%,
        #2F80ED 100%
    );
    box-shadow: 0 14px 32px rgba(8, 26, 51, 0.18);
    color: #FFFFFF;
}

.hero-header::after {
    content: "";
    position: absolute;
    z-index: -1;
    top: -90px;
    right: -55px;
    width: 250px;
    height: 250px;
    border: 1px solid rgba(255, 255, 255, 0.17);
    border-radius: 50%;
    box-shadow:
        0 0 0 28px rgba(255, 255, 255, 0.035),
        0 0 0 58px rgba(255, 255, 255, 0.025);
    pointer-events: none;
}

.hero-kicker {
    display: inline-block;
    padding: 6px 10px;
    border: 1px solid rgba(255, 255, 255, 0.24);
    border-radius: 7px;
    background: rgba(255, 255, 255, 0.10);
    color: #DCE8FF;
    font-size: 0.75rem;
    font-weight: 750;
    letter-spacing: 0.12em;
    text-transform: uppercase;
}

.hero-title {
    margin: 1rem 0 0.65rem;
    color: #FFFFFF !important;
    font-size: clamp(2rem, 4vw, 3.1rem);
    font-weight: 800;
    letter-spacing: -0.045em;
    line-height: 1.1;
}

.hero-description {
    max-width: 680px;
    margin: 0;
    color: #E5EEFF;
    font-size: clamp(0.95rem, 1.5vw, 1.08rem);
    line-height: 1.7;
}

.hero-accent {
    color: #FFFFFF;
    font-weight: 750;
}

@media (max-width: 768px) {
    .hero-header {
        margin-bottom: 1.2rem;
        padding: 1.35rem;
        border-radius: 16px;
    }

    .hero-header::after {
        top: -105px;
        right: -145px;
    }

    .hero-title {
        font-size: 2rem;
    }

    .hero-description {
        font-size: 0.94rem;
    }
}
[data-testid="stHeader"] {
    background: transparent;
}

[data-testid="stMainBlockContainer"],
.block-container {
    max-width: 1120px !important;
    padding-top: 2rem !important;
    padding-bottom: 3rem !important;
    padding-left: clamp(1rem, 3vw, 2.5rem) !important;
    padding-right: clamp(1rem, 3vw, 2.5rem) !important;
}

/* =========================================================
   2. JERARQUÍA TIPOGRÁFICA
   ========================================================= */

h1, h2, h3 {
    color: #081A33 !important;
    letter-spacing: -0.025em !important;
}

h1 {
    font-weight: 750 !important;
    line-height: 1.15 !important;
}

h1::after {
    content: "";
    display: block;
    width: 84px;
    height: 5px;
    margin-top: 0.7rem;
    border-radius: 999px;
    background: linear-gradient(
        100deg,
        #081A33 0%,
        #123E7C 45%,
        #155EEF 78%,
        #2F80ED 100%
    );
}

h2, h3 {
    font-weight: 700 !important;
}

[data-testid="stCaptionContainer"] {
    color: #64748B !important;
}

label, [data-testid="stWidgetLabel"] p {
    color: #253B59 !important;
    font-weight: 600 !important;
}

/* =========================================================
   3. NAVEGACIÓN PRINCIPAL
   ========================================================= */

[data-testid="stTabs"] {
    margin-top: 1.25rem;
}

[data-testid="stTabs"] [data-baseweb="tab-list"] {
    display: flex;
    gap: 5px;
    padding: 6px;
    border: 1px solid #244B7C;
    border-radius: 14px;
    background: linear-gradient(
        120deg,
        #081A33 0%,
        #123E7C 55%,
        #155EEF 100%
    );
    box-shadow: 0 8px 22px rgba(8, 26, 51, 0.14);
}

[data-testid="stTabs"] button[role="tab"] {
    min-height: 44px;
    padding: 0.65rem 1rem;
    border: 1px solid transparent !important;
    border-radius: 9px;
    background: transparent;
    color: #DCE8F8 !important;
    font-weight: 600;
    transition:
        background-color 160ms ease,
        color 160ms ease,
        box-shadow 160ms ease;
}

[data-testid="stTabs"] button[role="tab"] p {
    color: inherit !important;
    font-weight: inherit !important;
}

[data-testid="stTabs"] button[role="tab"]:hover {
    background: rgba(255, 255, 255, 0.12);
    color: #FFFFFF !important;
}

[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
    background: #FFFFFF !important;
    color: #123E7C !important;
    border-color: #FFFFFF !important;
    box-shadow: 0 2px 8px rgba(8, 26, 51, 0.18);
}

[data-testid="stTabs"] button[role="tab"][aria-selected="true"] p {
    color: #123E7C !important;
}

/* Indicador de pestaña: acento eléctrico */
[data-testid="stTabs"] [data-baseweb="tab-highlight"] {
    background-color: #2F80ED !important;
}

/* =========================================================
   4. TARJETAS, FORMULARIOS Y CONTENEDORES
   ========================================================= */

[data-testid="stVerticalBlockBorderWrapper"],
[data-testid="stForm"],
[data-testid="stExpander"] {
    border-color: #D8E2F0 !important;
    border-radius: 14px !important;
}

[data-testid="stVerticalBlockBorderWrapper"] {
    background: #FFFFFF;
    box-shadow: 0 3px 12px rgba(15, 39, 75, 0.035);
}

[data-testid="stForm"] {
    padding: 1rem;
    background: #FFFFFF;
}

[data-testid="stExpander"] {
    background: #FFFFFF;
    overflow: hidden;
}

[data-testid="stExpander"] summary {
    color: #18385E;
    font-weight: 600;
}

/* =========================================================
   5. CAMPOS DE ENTRADA Y SELECTORES
   ========================================================= */

input,
textarea,
select,
div[data-baseweb="input"] input,
div[data-baseweb="select"] input {
    color: #12233F !important;
    font-size: 16px !important;
}

div[data-baseweb="input"] > div,
div[data-baseweb="textarea"] > div,
div[data-baseweb="select"] > div {
    min-height: 44px;
    border-color: #C9D6E8 !important;
    border-radius: 10px !important;
    background: #FFFFFF !important;
    transition:
        border-color 150ms ease,
        box-shadow 150ms ease;
}

div[data-baseweb="input"] > div:hover,
div[data-baseweb="textarea"] > div:hover,
div[data-baseweb="select"] > div:hover {
    border-color: #7FA9F4 !important;
}

div[data-baseweb="input"] > div:focus-within,
div[data-baseweb="textarea"] > div:focus-within,
div[data-baseweb="select"] > div:focus-within {
    border-color: #2F80ED !important;
    box-shadow: 0 0 0 3px rgba(47, 128, 237, 0.16) !important;
}

/* =========================================================
   6. BOTONES
   ========================================================= */

div.stButton > button,
div.stDownloadButton > button,
div[data-testid="stFormSubmitButton"] > button {
    width: 100%;
    min-height: 46px;
    padding: 0.65rem 1rem;
    border: 1px solid #CDD9EA !important;
    border-radius: 10px !important;
    background: #FFFFFF;
    color: #173A66 !important;
    font-size: 15px !important;
    font-weight: 650 !important;
    box-shadow: 0 2px 5px rgba(8, 26, 51, 0.04);
    transition:
        transform 150ms ease,
        box-shadow 150ms ease,
        border-color 150ms ease,
        background-color 150ms ease;
}

/* Acciones principales */
div.stButton > button[kind="primary"],
div.stDownloadButton > button[kind="primary"],
div[data-testid="stFormSubmitButton"] > button[kind="primary"],
button[data-testid="stBaseButton-primary"] {
    border: 1px solid #155EEF !important;
    background: linear-gradient(
        115deg,
        #123E7C 0%,
        #155EEF 72%,
        #2F80ED 100%
    ) !important;
    color: #FFFFFF !important;
    box-shadow: 0 5px 13px rgba(21, 94, 239, 0.19);
}

div.stButton > button:hover,
div.stDownloadButton > button:hover,
div[data-testid="stFormSubmitButton"] > button:hover {
    border-color: #2F80ED !important;
    box-shadow: 0 5px 13px rgba(21, 94, 239, 0.12);
}

div.stButton > button[kind="primary"]:hover,
button[data-testid="stBaseButton-primary"]:hover {
    background: linear-gradient(
        115deg,
        #123E7C 0%,
        #155EEF 55%,
        #398DFF 100%
    ) !important;
    box-shadow: 0 7px 17px rgba(21, 94, 239, 0.26);
}

div.stButton > button:active,
div.stDownloadButton > button:active {
    transform: translateY(1px);
}

/* =========================================================
   7. CONFIANZA, AVISOS Y ESTADOS
   ========================================================= */

.badge-conf {
    display: inline-block;
    padding: 4px 10px;
    border-radius: 8px;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.01em;
    margin-bottom: 5px;
}

.badge-verde {
    background: #E8F5ED;
    color: #176B49;
    border: 1px solid #B7E1C9;
}

.badge-ambar {
    background: #FFF2DB;
    color: #895414;
    border: 1px solid #F0D39A;
}

.badge-rojo {
    background: #FDECEC;
    color: #A12D35;
    border: 1px solid #F3C3C6;
}

.aviso-fijo {
    background: linear-gradient(110deg, #EDF4FF 0%, #FFFFFF 100%);
    border: 1px solid #C9DBFA;
    border-left: 4px solid #2F80ED;
    padding: 13px 16px;
    border-radius: 10px;
    font-size: 14px;
    line-height: 1.6;
    margin-bottom: 16px;
    color: #18385E;
}

/* Mensajes nativos de Streamlit */
[data-testid="stAlert"] {
    border-radius: 12px !important;
}

/* =========================================================
   8. TABLAS Y RESULTADOS
   ========================================================= */

[data-testid="stDataFrame"],
[data-testid="stTable"] {
    border: 1px solid #D8E2F0;
    border-radius: 10px;
    overflow: hidden;
    background: #FFFFFF;
}

[data-testid="stMetric"] {
    padding: 1rem;
    border: 1px solid #D8E2F0;
    border-radius: 12px;
    background: #FFFFFF;
}

[data-testid="stMetricLabel"] {
    color: #64748B !important;
}

[data-testid="stMetricValue"] {
    color: #123E7C !important;
    font-weight: 700 !important;
}

/* Imágenes de previsualización */
[data-testid="stImage"] img {
    border-radius: 10px;
}

/* Separadores más discretos */
hr {
    border-color: #E0E8F3 !important;
}

/* =========================================================
   9. ACCESIBILIDAD Y DISEÑO RESPONSIVE
   ========================================================= */

:focus-visible {
    outline: 3px solid #2F80ED !important;
    outline-offset: 2px !important;
}

@media (max-width: 768px) {
    [data-testid="stMainBlockContainer"],
    .block-container {
        padding-top: 1.25rem !important;
        padding-bottom: 2rem !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
    }

    [data-testid="stTabs"] [data-baseweb="tab-list"] {
        gap: 3px;
        padding: 4px;
        overflow-x: auto;
        border-radius: 11px;
    }

    [data-testid="stTabs"] button[role="tab"] {
        min-height: 44px;
        padding: 0.55rem 0.75rem;
        white-space: nowrap;
        font-size: 14px;
    }

    [data-testid="stForm"] {
        padding: 0.75rem;
    }

    h1 {
        font-size: 1.8rem !important;
    }
}

@media (prefers-reduced-motion: reduce) {
    *,
    *::before,
    *::after {
        scroll-behavior: auto !important;
        transition-duration: 0.01ms !important;
        animation-duration: 0.01ms !important;
    }
}
</style>
"""


def inyectar_css_movil() -> None:
    """Inyecta las reglas CSS mobile-first en la página actual."""
    st.markdown(MOBILE_CSS, unsafe_allow_html=True)


def ejecutar_pipeline_completo(
    file_bytes: bytes,
    filename: str,
    storage: StorageManager,
    variante_forzada: Optional[str] = None,
    permitir_fallback_eng: bool = True,
) -> Tuple[Resultado, Comprobante, PreprocessOutput]:
    """
    Ejecuta de punta a punta: hash -> preprocesado -> OCR -> reglas -> LLM opcional -> fusión -> validación.
    Retorna (Resultado validado, copia del Comprobante extraído antes de edición manual, PreprocessOutput).
    """
    tiempos: Dict[str, float] = {}
    hash_img = hashlib.sha256(file_bytes).hexdigest()

    ajustes = storage.obtener_ajustes()
    usar_llm = bool(ajustes.get("enable_llm", False))
    umbral_p2 = float(ajustes.get("umbral_p2", CONFIDENCE_THRESHOLD_P2))
    min_date_str = str(ajustes.get("min_valid_date", MIN_VALID_DATE.isoformat()))
    try:
        min_date_val = date.fromisoformat(min_date_str)
    except ValueError:
        min_date_val = MIN_VALID_DATE

    t0 = time.perf_counter()
    prep = preprocesar_bytes(file_bytes, filename=filename)
    tiempos["preprocesado_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)

    t1 = time.perf_counter()
    ocr_res = ejecutar_ocr_mejores_variantes(
        prep.variantes,
        variante_forzada=variante_forzada,
        permitir_fallback_eng=permitir_fallback_eng,
    )
    tiempos["ocr_ms"] = round((time.perf_counter() - t1) * 1000.0, 1)

    t2 = time.perf_counter()
    comp_reglas, alertas_reglas = extraer_por_reglas(
        texto_ocr=ocr_res.texto,
        palabras_ocr=ocr_res.palabras,
        lineas_ocr=ocr_res.lineas,
        confianza_base_ocr=ocr_res.confianza_media,
    )
    tiempos["reglas_ms"] = round((time.perf_counter() - t2) * 1000.0, 1)

    alertas_acumuladas: List[str] = list(ocr_res.advertencias) + list(alertas_reglas)
    metodo_usado = "reglas"
    comp_final = comp_reglas

    if usar_llm:
        t3 = time.perf_counter()
        extractor = construir_extractor_llm(provider=LLM_PROVIDER, api_key=LLM_API_KEY)
        comp_llm, alerta_llm = extraer_con_llm_con_reintento(ocr_res.texto, extractor)
        tiempos["llm_ms"] = round((time.perf_counter() - t3) * 1000.0, 1)
        if alerta_llm:
            alertas_acumuladas.append(f"[ADVERTENCIA] {alerta_llm}")
        elif comp_llm is not None:
            metodo_usado = "reglas+llm"
            comp_final, alertas_merge = fusionar_reglas_y_llm(
                comp_reglas, comp_llm, ocr_res.texto
            )
            alertas_acumuladas.extend(alertas_merge)

    # Copia profunda del comprobante extraído automáticamente para medir tasa de corrección manual al confirmar
    comp_original_extraido = Comprobante.model_validate(comp_final.model_dump(mode="json")).normalize_types()

    t4 = time.perf_counter()
    resultado = Resultado(
        hash_imagen=hash_img,
        texto_ocr_crudo=ocr_res.texto,
        ocr_confianza_media=ocr_res.confianza_media,
        variante_preprocesado=ocr_res.variante,
        metodo=metodo_usado,  # type: ignore[arg-type]
        alertas=alertas_acumuladas,
        estado="pendiente_revision",
        comprobante=comp_final,
        tiempos_ms=tiempos,
    )
    historial_claves = storage.listar_claves_historial()
    resultado = ejecutar_validaciones(
        resultado,
        historial_existente=historial_claves,
        umbral_confianza_p2=umbral_p2,
        min_date=min_date_val,
    )
    resultado.tiempos_ms["validacion_ms"] = round((time.perf_counter() - t4) * 1000.0, 1)

    return resultado, comp_original_extraido, prep


def _render_badge_confianza(
    campo: Campo,
    nombre_campo: str,
    umbral_p2: float,
    campos_con_error: set[str],
) -> str:
    tiene_val = (
        bool(campo.valor)
        if nombre_campo in ("iva", "otros_impuestos")
        else (campo.valor is not None and str(campo.valor).strip() != "")
    )
    if not tiene_val or nombre_campo in campos_con_error:
        clase = "badge-rojo"
        estado_txt = "Vacío / Error" if not tiene_val else "Error de validación"
    elif campo.confianza < umbral_p2 or campo.revisar:
        clase = "badge-ambar"
        estado_txt = "Revisar"
    else:
        clase = "badge-verde"
        estado_txt = "Confiable"

    pct = int(round(campo.confianza * 100))
    return (
        f'<span class="badge-conf {clase}">'
        f"{estado_txt} · Confianza: {pct}% · Fuente: {campo.fuente}"
        f"</span>"
    )


def render_formulario_edicion_comprobante(
    resultado: Resultado,
    umbral_p2: float,
    form_key_prefix: str = "scan",
) -> Tuple[bool, Comprobante]:
    """
    Renderiza un st.form con todos los campos del comprobante.
    Los campos con alertas o marcados para revisar aparecen primero.
    Retorna (submitted, comprobante_editado).
    """
    comp = resultado.comprobante.normalize_types()
    campos_error = {
        a.campo for a in resultado.alertas_detalle if a.severidad == "ERROR" and a.campo
    }
    campos_adv = {
        a.campo
        for a in resultado.alertas_detalle
        if a.severidad == "ADVERTENCIA" and a.campo
    }

    # Ordenar campos simples: primero los que tienen error/advertencia o revisar=True
    def _prioridad_campo(nombre: str) -> int:
        c_obj: Campo = getattr(comp, nombre)
        if nombre in campos_error:
            return 0
        if nombre in campos_adv or c_obj.revisar:
            return 1
        return 2

    campos_ordenados = sorted(CAMPOS_SIMPLES_ORDEN, key=_prioridad_campo)

    with st.form(key=f"{form_key_prefix}_form_comprobante"):
        st.subheader("Revisión y corrección de campos")
        st.caption(
            "Los campos con alertas o baja confianza se muestran primero. "
            "Si un dato no es visible en el comprobante, dejalo vacío."
        )

        valores_ingresados: Dict[str, str] = {}
        for nombre_campo in campos_ordenados:
            c_obj: Campo = getattr(comp, nombre_campo)
            etiqueta = ETIQUETAS_CAMPOS.get(nombre_campo, nombre_campo)
            st.markdown(
                _render_badge_confianza(c_obj, nombre_campo, umbral_p2, campos_error),
                unsafe_allow_html=True,
            )

            val_actual_str = ""
            if c_obj.valor is not None:
                if hasattr(c_obj.valor, "isoformat"):
                    val_actual_str = c_obj.valor.isoformat()
                else:
                    val_actual_str = str(c_obj.valor)

            valores_ingresados[nombre_campo] = st.text_input(
                etiqueta,
                value=val_actual_str,
                key=f"{form_key_prefix}_input_{nombre_campo}_{resultado.id}",
            )

            if c_obj.sugerencia_llm is not None:
                st.caption(
                    f"Sugerencia alternativa del LLM: **{c_obj.sugerencia_llm}** "
                    f"(origen: `{c_obj.sugerencia_texto_origen or 'N/D'}`)"
                )
            st.caption(
                f"Texto origen OCR: `{c_obj.texto_origen if c_obj.texto_origen else 'sin fragmento (no visible)'}`"
            )

        # Tablas dinámicas para IVA y Otros Impuestos
        st.markdown(
            _render_badge_confianza(comp.iva, "iva", umbral_p2, campos_error),
            unsafe_allow_html=True,
        )
        st.markdown(f"**{ETIQUETAS_CAMPOS['iva']}**")
        df_iva_in = pd.DataFrame(
            [
                {"alicuota": str(i.alicuota), "importe": str(i.importe)}
                for i in (comp.iva.valor or [])
            ]
            or [{"alicuota": "", "importe": ""}]
        )
        df_iva_edit = st.data_editor(
            df_iva_in,
            num_rows="dynamic",
            use_container_width=True,
            key=f"{form_key_prefix}_iva_editor_{resultado.id}",
        )
        st.caption(
            f"Texto origen IVA: `{comp.iva.texto_origen if comp.iva.texto_origen else 'sin fragmento'}`"
        )

        st.markdown(
            _render_badge_confianza(
                comp.otros_impuestos, "otros_impuestos", umbral_p2, campos_error
            ),
            unsafe_allow_html=True,
        )
        st.markdown(f"**{ETIQUETAS_CAMPOS['otros_impuestos']}**")
        df_otros_in = pd.DataFrame(
            [
                {"descripcion": str(o.descripcion), "importe": str(o.importe)}
                for o in (comp.otros_impuestos.valor or [])
            ]
            or [{"descripcion": "", "importe": ""}]
        )
        df_otros_edit = st.data_editor(
            df_otros_in,
            num_rows="dynamic",
            use_container_width=True,
            key=f"{form_key_prefix}_otros_editor_{resultado.id}",
        )
        st.caption(
            f"Texto origen otros impuestos: `{comp.otros_impuestos.texto_origen if comp.otros_impuestos.texto_origen else 'sin fragmento'}`"
        )

        submitted = st.form_submit_button("✅ Confirmar y guardar comprobante")

    # Construir el Comprobante resultante a partir de los inputs del formulario
    comp_nuevo = Comprobante.model_validate(comp.model_dump(mode="json")).normalize_types()

    for nombre_campo, raw_str in valores_ingresados.items():
        c_prev: Campo = getattr(comp_nuevo, nombre_campo)
        txt = (raw_str or "").strip()
        if not txt:
            setattr(
                comp_nuevo,
                nombre_campo,
                Campo(valor=None, confianza=0.0, fuente="ninguna", texto_origen=c_prev.texto_origen),
            )
            continue

        nuevo_val: Any = txt
        if nombre_campo in ("importe_neto_gravado", "importe_total"):
            monto_norm = normalizar_monto(txt)
            nuevo_val = monto_norm if monto_norm is not None else txt
        elif nombre_campo == "proveedor_cuit":
            nuevo_val = "".join(ch for ch in txt if ch.isdigit())
        elif nombre_campo in ("letra", "moneda"):
            nuevo_val = txt.upper()

        c_prev.valor = nuevo_val
        setattr(comp_nuevo, nombre_campo, c_prev)

    # Reconstruir lista de IVA desde df_iva_edit
    nuevos_iva: List[ItemIVA] = []
    for _, row in df_iva_edit.iterrows():
        alic_s = str(row.get("alicuota", "") or "").strip().replace(",", ".")
        imp_s = str(row.get("importe", "") or "").strip()
        if not alic_s and not imp_s:
            continue
        try:
            alic_d = Decimal(alic_s)
            imp_d = normalizar_monto(imp_s) or Decimal(imp_s.replace(",", "."))
            nuevos_iva.append(ItemIVA(alicuota=alic_d, importe=imp_d))
        except Exception:
            continue
    comp_nuevo.iva.valor = nuevos_iva
    if not nuevos_iva:
        comp_nuevo.iva.fuente = "ninguna"
        comp_nuevo.iva.confianza = 0.0

    # Reconstruir lista de Otros Impuestos desde df_otros_edit
    nuevos_otros: List[ItemImpuesto] = []
    for _, row in df_otros_edit.iterrows():
        desc_s = str(row.get("descripcion", "") or "").strip()
        imp_s = str(row.get("importe", "") or "").strip()
        if not desc_s and not imp_s:
            continue
        try:
            imp_d = normalizar_monto(imp_s) or Decimal(imp_s.replace(",", "."))
            nuevos_otros.append(ItemImpuesto(descripcion=desc_s or "Impuesto", importe=imp_d))
        except Exception:
            continue
    comp_nuevo.otros_impuestos.valor = nuevos_otros
    if not nuevos_otros:
        comp_nuevo.otros_impuestos.fuente = "ninguna"
        comp_nuevo.otros_impuestos.confianza = 0.0

    return submitted, comp_nuevo.normalize_types()


def render_tab_escanear(storage: StorageManager) -> None:
    """Renderiza la pestaña principal 'Escanear'."""
    st.markdown(
        '<div class="aviso-fijo">📌 <strong>Aviso:</strong> Usá comprobantes propios, ficticios o con autorización.</div>',
        unsafe_allow_html=True,
    )

    st.caption(
        "💡 **¿Cuál conviene usar?** En el celular conviene usar **1. Subir archivo o abrir cámara nativa**, "
        "porque captura la foto a resolución completa del sensor y logra mucha mejor lectura OCR que la captura web del navegador."
    )

    archivo_subido = st.file_uploader(
        "1. Subir foto o tomar con cámara nativa del sistema (JPG, PNG, HEIC)",
        type=["jpg", "jpeg", "png", "heic"],
        key="uploader_comprobante",
    )
    foto_camara = st.camera_input(
        "2. Captura directa en el navegador (menor resolución)",
        key="camera_comprobante",
    )

    with st.expander("📸 Consejos de captura para mejorar la lectura"):
        st.markdown(
            "- **Buena luz:** evitá contraluces y sombras del propio celular sobre el papel.\n"
            "- **Comprobante plano:** alisá arrugas o pliegues antes de fotografiar.\n"
            "- **Encuadre completo:** asegurate de que se vean los 4 bordes del comprobante.\n"
            "- **Cámara paralela:** mantené el celular paralelo al papel para minimizar distorsión de perspectiva."
        )

    fuente_bytes: Optional[bytes] = None
    nombre_archivo: str = "captura.jpg"
    if archivo_subido is not None:
        fuente_bytes = archivo_subido.getvalue()
        nombre_archivo = archivo_subido.name
    elif foto_camara is not None:
        fuente_bytes = foto_camara.getvalue()
        nombre_archivo = "camara.jpg"

    if st.button("🔍 Procesar comprobante", type="primary", disabled=(fuente_bytes is None)):
        if fuente_bytes is not None:
            try:
                with st.spinner("Preprocesando imagen, ejecutando OCR y extrayendo campos..."):
                    res, comp_orig, prep_out = ejecutar_pipeline_completo(
                        fuente_bytes, nombre_archivo, storage
                    )
                st.session_state["scan_resultado"] = res
                st.session_state["scan_comp_original"] = comp_orig
                st.session_state["scan_prep"] = prep_out
                st.session_state["scan_file_bytes"] = fuente_bytes
                st.session_state["scan_filename"] = nombre_archivo
            except (PreprocessError, OCRError) as exc:
                st.error(str(exc))
            except Exception as exc:
                logger.error("Error inesperado en pipeline: %s", type(exc).__name__)
                st.error(
                    "Ocurrió un inconveniente al procesar la imagen. Intentá con otra foto más nítida."
                )

    res_actual: Optional[Resultado] = st.session_state.get("scan_resultado")
    prep_actual: Optional[PreprocessOutput] = st.session_state.get("scan_prep")

    if res_actual is not None:
        tiempos = res_actual.tiempos_ms
        st.info(
            f"⏱️ **Tiempos por etapa:** "
            f"Preprocesado: {tiempos.get('preprocesado_ms', 0)} ms · "
            f"OCR (variante {res_actual.variante_preprocesado}, conf. media {res_actual.ocr_confianza_media:.1f}%): {tiempos.get('ocr_ms', 0)} ms · "
            f"Reglas: {tiempos.get('reglas_ms', 0)} ms · "
            + (f"LLM: {tiempos['llm_ms']} ms · " if "llm_ms" in tiempos else "")
            + f"Validación: {tiempos.get('validacion_ms', 0)} ms"
        )

        if prep_actual is not None:
            with st.expander("🖼️ Ver imagen procesada (Original vs. Preprocesada)"):
                col1, col2 = st.columns(2)
                with col1:
                    st.image(prep_actual.original_rgb, caption="Original normalizada", use_container_width=True)
                with col2:
                    var_img = prep_actual.variantes.get(res_actual.variante_preprocesado)
                    if var_img is not None:
                        st.image(
                            var_img,
                            caption=f"Preprocesada (Variante {res_actual.variante_preprocesado})",
                            use_container_width=True,
                        )
                st.caption(f"Texto OCR crudo extraído:\n```\n{res_actual.texto_ocr_crudo}\n```")

        if res_actual.alertas:
            st.warning("⚠️ **Alertas de validación y lectura:**\n\n" + "\n".join(f"- {a}" for a in res_actual.alertas))
        else:
            st.success("Todas las validaciones aritméticas y de formato cerraron sin alertas.")

        ajustes = storage.obtener_ajustes()
        umbral_p2 = float(ajustes.get("umbral_p2", CONFIDENCE_THRESHOLD_P2))

        confirmado, comp_editado = render_formulario_edicion_comprobante(
            res_actual, umbral_p2=umbral_p2, form_key_prefix="scan"
        )

        if confirmado:
            res_actual.comprobante = comp_editado
            res_actual.estado = "confirmado"
            res_actual = ejecutar_validaciones(
            res_actual,
            historial_existente=storage.listar_claves_historial(),
            umbral_confianza_p2=umbral_p2,
        )
            ext_img = (
                st.session_state.get("scan_filename", "jpg").rsplit(".", 1)[-1]
                if "." in st.session_state.get("scan_filename", "")
                else "jpg"
            )
            storage.guardar_resultado(
                resultado=res_actual,
                comprobante_original_extraido=st.session_state.get("scan_comp_original"),
                imagen_bytes=st.session_state.get("scan_file_bytes"),
                extension_imagen=ext_img,
            )
            st.toast("✅ Comprobante confirmado y guardado en el historial.")
            st.success("Comprobante confirmado y guardado correctamente.")

        st.markdown("#### Acciones adicionales")
        col_rep1, col_rep2, col_desc = st.columns([1, 1, 1])
        with col_rep1:
            variante_manual = st.selectbox(
                "Elegir variante manual",
                options=["A", "B", "C"],
                index=["A", "B", "C"].index(
                    res_actual.variante_preprocesado
                    if res_actual.variante_preprocesado in ("A", "B", "C")
                    else "A"
                ),
                key="select_variante_manual",
            )
        with col_rep2:
            if st.button("🔄 Reprocesar con otro preprocesado"):
                bytes_guardados = st.session_state.get("scan_file_bytes")
                fname_guardado = st.session_state.get("scan_filename", "captura.jpg")
                if bytes_guardados:
                    try:
                        with st.spinner(f"Reprocesando con variante {variante_manual}..."):
                            res_nuevo, comp_orig_nuevo, prep_nuevo = ejecutar_pipeline_completo(
                                bytes_guardados,
                                fname_guardado,
                                storage,
                                variante_forzada=variante_manual,
                            )
                        st.session_state["scan_resultado"] = res_nuevo
                        st.session_state["scan_comp_original"] = comp_orig_nuevo
                        st.session_state["scan_prep"] = prep_nuevo
                        st.rerun()
                    except (PreprocessError, OCRError) as exc:
                        st.error(str(exc))
        with col_desc:
            if st.button("🗑️ Descartar lectura actual"):
                for k in ("scan_resultado", "scan_comp_original", "scan_prep", "scan_file_bytes"):
                    st.session_state.pop(k, None)
                st.toast("Lectura descartada.")
                st.rerun()


def render_tab_historial(storage: StorageManager) -> None:
    """Renderiza la pestaña 'Historial' con filtros, edición, exportación CSV/XLSX y borrado."""
    st.subheader("Historial de comprobantes")

    col_f1, col_f2 = st.columns(2)
    with col_f1:
        usar_rango_fechas = st.checkbox("Filtrar por fecha de emisión", value=False)
        fecha_desde = st.date_input("Desde", value=date(2026, 1, 1), disabled=not usar_rango_fechas)
        fecha_hasta = st.date_input("Hasta", value=date.today(), disabled=not usar_rango_fechas)
    with col_f2:
        proveedor_filtro = st.text_input("Filtrar por proveedor o CUIT", value="")
        estado_filtro = st.selectbox(
            "Filtrar por estado",
            options=["Todos", "confirmado", "pendiente_revision"],
            index=0,
        )

    resultados = storage.listar_resultados(
        fecha_desde=fecha_desde if usar_rango_fechas else None,
        fecha_hasta=fecha_hasta if usar_rango_fechas else None,
        proveedor_filtro=proveedor_filtro,
        estado_filtro=estado_filtro,
    )

    if not resultados:
        st.info("No hay comprobantes guardados que coincidan con los filtros seleccionados.")
        return

    filas = resultados_a_filas_planas(resultados)
    df_hist = pd.DataFrame(filas)
    columnas_vista = [
        "id",
        "fecha_emision",
        "proveedor_razon_social",
        "proveedor_cuit",
        "tipo_comprobante",
        "letra",
        "punto_venta",
        "numero_comprobante",
        "importe_total",
        "moneda",
        "estado",
    ]
    st.dataframe(df_hist[columnas_vista], use_container_width=True, hide_index=True)

    col_exp1, col_exp2 = st.columns(2)
    with col_exp1:
        st.download_button(
            "⬇️ Exportar selección a CSV",
            data=exportar_csv(resultados),
            file_name="comprobantes.csv",
            mime="text/csv",
        )
    with col_exp2:
        st.download_button(
            "⬇️ Exportar selección a Excel (.xlsx)",
            data=exportar_xlsx(resultados),
            file_name="comprobantes.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    st.markdown("#### Abrir o eliminar un registro del historial")
    opciones_id = {
        f"{r.comprobante.fecha_emision.valor or 'S/F'} · {r.comprobante.proveedor_razon_social.valor or 'Sin proveedor'} · $ {r.comprobante.importe_total.valor or '0'} ({r.id[:8]})": r.id
        for r in resultados
    }
    etiqueta_sel = st.selectbox("Seleccioná un comprobante", options=list(opciones_id.keys()))
    id_sel = opciones_id[etiqueta_sel]
    reg_sel = storage.obtener_resultado(id_sel)

    if reg_sel is not None:
        with st.expander("✏️ Editar este comprobante", expanded=False):
            umbral_p2 = float(storage.obtener_ajustes().get("umbral_p2", CONFIDENCE_THRESHOLD_P2))
            guardado_ed, comp_edit = render_formulario_edicion_comprobante(
                reg_sel, umbral_p2=umbral_p2, form_key_prefix=f"hist_{reg_sel.id[:6]}"
            )
            if guardado_ed:
                comp_antes = reg_sel.comprobante
                reg_sel.comprobante = comp_edit
                reg_sel.estado = "confirmado"
                reg_sel = ejecutar_validaciones(
                reg_sel,
                historial_existente=storage.listar_claves_historial(),
                umbral_confianza_p2=umbral_p2,
            )
                storage.guardar_resultado(
                    reg_sel, comprobante_original_extraido=comp_antes
                )
                st.toast("Registro actualizado.")
                st.rerun()

        if st.button("🗑️ Eliminar este comprobante seleccionado"):
            storage.eliminar_resultado(id_sel)
            st.toast("Comprobante eliminado.")
            st.rerun()

    with st.expander("⚠️ Borrado total del historial"):
        conf_total = st.checkbox("Confirmo que quiero borrar todos los comprobantes del historial", key="chk_del_hist")
        if st.button("🚨 Borrar todo el historial", disabled=not conf_total):
            storage.borrar_todos_los_datos()
            st.toast("Se borraron todos los registros.")
            st.rerun()


def render_tab_evaluacion(storage: StorageManager) -> None:
    """Renderiza la pestaña 'Evaluación' contra ground_truth.json y tasa de corrección en producción."""
    st.subheader("Evaluación de exactitud contra referencia")
    st.caption(
        "Compara la extracción automática campo a campo contra `eval/dataset/ground_truth.json`. "
        "Nota: los resultados sobre comprobantes sintéticos no reemplazan comprobantes reales autorizados."
    )

    dataset_dir = BASE_DIR / "eval" / "dataset"
    report_csv_path = BASE_DIR / "eval" / "report.csv"
    errores_csv_path = BASE_DIR / "eval" / "errores.csv"

    if st.button("▶️ Ejecutar evaluación sobre eval/dataset/", type="primary"):
        try:
            from eval.run_eval import ejecutar_evaluacion_dataset

            with st.spinner("Ejecutando evaluación sobre el dataset de referencia..."):
                ejecutar_evaluacion_dataset(
                    dataset_dir=dataset_dir,
                    output_dir=BASE_DIR / "eval",
                    usar_llm=False,
                )
            st.toast("Evaluación finalizada.")
        except Exception as exc:
            logger.error("Error en evaluación: %s", type(exc).__name__)
            st.error(f"No se pudo completar la evaluación: {exc}")

    if report_csv_path.exists():
        st.markdown("#### Exactitud por campo y por método (contra referencia)")
        df_rep = pd.read_csv(report_csv_path)
        st.dataframe(df_rep, use_container_width=True, hide_index=True)

    if errores_csv_path.exists():
        st.markdown("#### Detalle de errores campo a campo (esperado vs. obtenido)")
        df_err = pd.read_csv(errores_csv_path)
        if df_err.empty:
            st.success("No se registraron discrepancias en la última corrida.")
        else:
            st.dataframe(df_err, use_container_width=True, hide_index=True)

    st.markdown("#### Tasa de corrección manual en producción por campo")
    st.caption(
        "Métrica operativa independiente de la evaluación contra referencia: mide la proporción "
        "de comprobantes confirmados por el usuario en los que cada campo fue editado manualmente."
    )
    metricas_prod = storage.obtener_metricas_correccion_manual()
    st.dataframe(pd.DataFrame(metricas_prod), use_container_width=True, hide_index=True)


def render_tab_ajustes(storage: StorageManager) -> None:
    """Renderiza la pestaña 'Ajustes' con configuración de LLM, umbrales, privacidad y borrado."""
    st.subheader("Ajustes y privacidad")
    ajustes = storage.obtener_ajustes()

    st.markdown("#### Extracción asistida por LLM (opcional)")
    st.info(UI_LLM_PRIVACY_NOTICE)
    llm_activo = st.toggle(
        "Activar extracción asistida por LLM",
        value=bool(ajustes.get("enable_llm", False)),
        key="toggle_llm_ajustes",
    )
    if llm_activo and not LLM_API_KEY and LLM_PROVIDER != "fake":
        st.warning(
            "El interruptor está activo, pero no se detectó la variable de entorno `LLM_API_KEY`. "
            "Configurala antes de iniciar la aplicación para usar el proveedor externo."
        )

    st.markdown("#### Umbrales y límites de validación")
    nuevo_p2 = st.slider(
        "Umbral de confianza por campo para marcar 'Revisar' (P2)",
        min_value=0.50,
        max_value=0.99,
        value=float(ajustes.get("umbral_p2", CONFIDENCE_THRESHOLD_P2)),
        step=0.01,
    )
    fecha_min_actual = date.fromisoformat(
        str(ajustes.get("min_valid_date", MIN_VALID_DATE.isoformat()))
    )
    nueva_fecha_min = st.date_input(
        "Fecha mínima de emisión válida",
        value=fecha_min_actual,
    )

    st.markdown("#### Privacidad y almacenamiento local")
    guardar_img = st.toggle(
        "Guardar imagen original en disco local (data/imagenes/)",
        value=bool(ajustes.get("save_original_image", False)),
    )

    if st.button("💾 Guardar ajustes", type="primary"):
        storage.guardar_ajuste("enable_llm", bool(llm_activo))
        storage.guardar_ajuste("umbral_p2", float(nuevo_p2))
        storage.guardar_ajuste("min_valid_date", nueva_fecha_min.isoformat())
        storage.guardar_ajuste("save_original_image", bool(guardar_img))
        st.toast("Ajustes guardados correctamente.")

    st.markdown("#### Zona de borrado total")
    confirmar_borrado = st.checkbox(
        "Entiendo que esta acción eliminará todos los comprobantes, correcciones e imágenes guardadas.",
        key="chk_borrar_todo_ajustes",
    )
    if st.button("🚨 Borrar todos los datos", disabled=not confirmar_borrado):
        storage.borrar_todos_los_datos()
        for k in ("scan_resultado", "scan_comp_original", "scan_prep", "scan_file_bytes"):
            st.session_state.pop(k, None)
        st.toast("Todos los datos locales fueron eliminados.")
        st.success("Se eliminaron todos los datos de la base SQLite y la carpeta de imágenes.")
