"""Ejecución de Tesseract OCR sobre las variantes preprocesadas y selección de mejor variante."""
from __future__ import annotations

import logging
import math
import shutil
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pytesseract
from pytesseract import Output

logger = logging.getLogger(__name__)


class OCRError(Exception):
    """Error accionable durante la ejecución de Tesseract OCR."""


@dataclass
class OCRWord:
    """Palabra individual detectada por Tesseract con su confianza y geometría."""

    text: str
    conf: float
    left: int
    top: int
    width: int
    height: int
    block_num: int
    par_num: int
    line_num: int


@dataclass
class OCRLine:
    """Línea reconstruida a partir de palabras de Tesseract."""

    text: str
    words: List[OCRWord]
    avg_conf: float
    max_height: int
    top: int


@dataclass
class OCRVariantResult:
    """Resultado de OCR sobre una variante y configuración PSM específica."""

    variante: str
    psm: int
    lang_usado: str
    texto: str
    confianza_media: float
    cantidad_palabras: int
    puntaje_ponderado: float
    palabras: List[OCRWord] = field(default_factory=list)
    lineas: List[OCRLine] = field(default_factory=list)
    advertencias: List[str] = field(default_factory=list)


def verificar_tesseract_instalado(requerir_spa: bool = False) -> Tuple[bool, List[str], Optional[str]]:
    """Verifica si el binario tesseract y el idioma 'spa' están disponibles."""
    if shutil.which("tesseract") is None:
        return (
            False,
            [],
            "No se encontró el programa Tesseract OCR instalado en el sistema. "
            "Instalalo con 'sudo apt-get install tesseract-ocr tesseract-ocr-spa' (Debian/Ubuntu) "
            "o 'brew install tesseract tesseract-lang' (macOS).",
        )
    try:
        langs = pytesseract.get_languages(config="")
    except Exception as exc:
        logger.error("Error consultando idiomas de Tesseract: %s", type(exc).__name__)
        return (
            False,
            [],
            "Tesseract está instalado pero no respondió correctamente al consultar idiomas disponibles.",
        )

    if requerir_spa and "spa" not in langs:
        return (
            False,
            langs,
            "Falta el paquete de idioma español ('spa') en Tesseract. "
            "Instalalo con 'sudo apt-get install tesseract-ocr-spa' para mejorar el reconocimiento de acentos y ñ.",
        )
    return True, langs, None


def _resolver_lang(permitir_fallback_eng: bool = True) -> Tuple[str, Optional[str]]:
    """Determina la cadena de idioma para Tesseract ('spa+eng' o fallback 'eng' con advertencia)."""
    ok, langs, msg = verificar_tesseract_instalado(requerir_spa=False)
    if not ok:
        raise OCRError(msg or "Tesseract OCR no está disponible.")

    if "spa" in langs and "eng" in langs:
        return "spa+eng", None
    if "spa" in langs:
        return "spa", None
    if "eng" in langs and permitir_fallback_eng:
        return (
            "eng",
            "El paquete de idioma español ('spa') de Tesseract no está instalado en este entorno; "
            "se ejecutó OCR con idioma 'eng'. Instalá 'tesseract-ocr-spa' para óptima precisión.",
        )
    raise OCRError(
        "Falta el paquete de idioma español ('spa') en Tesseract. "
        "Instalalo con 'sudo apt-get install tesseract-ocr-spa'."
    )


def ejecutar_ocr_imagen(
    imagen: np.ndarray,
    variante_nombre: str,
    psm: int = 6,
    lang: str = "spa+eng",
) -> OCRVariantResult:
    """Corre pytesseract.image_to_data sobre una imagen y reconstruye texto, líneas y confianzas."""
    config_str = f"--oem 1 --psm {psm}"
    try:
        data = pytesseract.image_to_data(
            imagen, lang=lang, config=config_str, output_type=Output.DICT
        )
    except pytesseract.TesseractNotFoundError as exc:
        raise OCRError(
            "No se encontró Tesseract OCR en el sistema. Instalá 'tesseract-ocr' y 'tesseract-ocr-spa'."
        ) from exc
    except pytesseract.TesseractError as exc:
        logger.error("TesseractError en variante %s psm %d: %s", variante_nombre, psm, type(exc).__name__)
        raise OCRError(
            "Error al ejecutar Tesseract OCR sobre la imagen. Verificá que el idioma español ('spa') esté instalado."
        ) from exc

    n_items = len(data.get("text", []))
    palabras: List[OCRWord] = []
    grupos_linea: Dict[Tuple[int, int, int], List[OCRWord]] = {}

    for i in range(n_items):
        raw_txt = (data["text"][i] or "").strip()
        try:
            conf_val = float(data["conf"][i])
        except (ValueError, TypeError):
            conf_val = -1.0

        if not raw_txt or conf_val < 0:
            continue

        w = OCRWord(
            text=raw_txt,
            conf=conf_val,
            left=int(data["left"][i]),
            top=int(data["top"][i]),
            width=int(data["width"][i]),
            height=int(data["height"][i]),
            block_num=int(data["block_num"][i]),
            par_num=int(data["par_num"][i]),
            line_num=int(data["line_num"][i]),
        )
        palabras.append(w)
        clave = (w.block_num, w.par_num, w.line_num)
        grupos_linea.setdefault(clave, []).append(w)

    lineas: List[OCRLine] = []
    for _, lista_pal in sorted(grupos_linea.items(), key=lambda kv: (kv[1][0].top, kv[1][0].left)):
        lista_ordenada = sorted(lista_pal, key=lambda x: x.left)
        texto_linea = " ".join(p.text for p in lista_ordenada)
        confs_pos = [p.conf for p in lista_ordenada if p.conf > 0]
        avg_c = sum(confs_pos) / len(confs_pos) if confs_pos else 0.0
        max_h = max((p.height for p in lista_ordenada), default=0)
        top_min = min((p.top for p in lista_ordenada), default=0)
        lineas.append(
            OCRLine(
                text=texto_linea,
                words=lista_ordenada,
                avg_conf=avg_c,
                max_height=max_h,
                top=top_min,
            )
        )

    texto_reconstruido = "\n".join(l.text for l in lineas)
    palabras_conf_pos = [p for p in palabras if p.conf > 0]
    cant_pos = len(palabras_conf_pos)
    conf_media = (
        sum(p.conf for p in palabras_conf_pos) / cant_pos if cant_pos > 0 else 0.0
    )
    puntaje = conf_media * math.log1p(cant_pos) if cant_pos > 0 else 0.0

    return OCRVariantResult(
        variante=variante_nombre,
        psm=psm,
        lang_usado=lang,
        texto=texto_reconstruido,
        confianza_media=round(conf_media, 2),
        cantidad_palabras=cant_pos,
        puntaje_ponderado=round(puntaje, 4),
        palabras=palabras,
        lineas=lineas,
    )


def ejecutar_ocr_mejores_variantes(
    variantes: Dict[str, np.ndarray],
    variante_forzada: Optional[str] = None,
    permitir_fallback_eng: bool = True,
) -> OCRVariantResult:
    """Corre Tesseract (--oem 1 --psm 6 y --psm 4 si conf < 60) sobre variantes y elige la mejor."""
    lang, adv_idioma = _resolver_lang(permitir_fallback_eng=permitir_fallback_eng)

    nombres_a_evaluar = (
        [variante_forzada]
        if variante_forzada and variante_forzada in variantes
        else sorted(variantes.keys())
    )

    candidatos: List[OCRVariantResult] = []
    for nombre in nombres_a_evaluar:
        img = variantes[nombre]
        res_psm6 = ejecutar_ocr_imagen(img, variante_nombre=nombre, psm=6, lang=lang)
        candidatos.append(res_psm6)
        if res_psm6.confianza_media < 60.0:
            res_psm4 = ejecutar_ocr_imagen(img, variante_nombre=nombre, psm=4, lang=lang)
            candidatos.append(res_psm4)

    if not candidatos:
        raise OCRError("No se generaron variantes de imagen para procesar con OCR.")

    mejor = max(candidatos, key=lambda c: (c.puntaje_ponderado, c.confianza_media))
    if adv_idioma:
        mejor.advertencias.append(adv_idioma)

    if not mejor.texto.strip():
        raise OCRError(
            "No se pudo detectar texto legible en la imagen. "
            "Probá tomando la foto con mejor luz, sin sombras y encuadrando bien el comprobante."
        )

    return mejor
