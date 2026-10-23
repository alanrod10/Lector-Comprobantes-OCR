"""Ejecutor de evaluación contra ground_truth.json y generación de report.md, report.csv y errores.csv."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import (
    CONFIDENCE_THRESHOLD_P2,
    LLM_API_KEY,
    LLM_PROVIDER,
    PROVEEDOR_SIMILARITY_THRESHOLD_P1,
)
from app.extract_llm import (
    FakeLLMExtractor,
    construir_extractor_llm,
    extraer_con_llm_con_reintento,
)
from app.extract_rules import extraer_por_reglas
from app.merge import fusionar_reglas_y_llm
from app.models import Comprobante
from app.ocr import ejecutar_ocr_mejores_variantes, verificar_tesseract_instalado
from app.preprocess import preprocesar_bytes
from eval.metrics import (
    CAMPOS_CRITICOS,
    CAMPOS_EVALUADOS,
    ErrorDetalle,
    ResumenMetodo,
    evaluar_predicciones_metodo,
)


def ejecutar_evaluacion_dataset(
    dataset_dir: Path,
    output_dir: Path,
    usar_llm: bool = False,
    umbral_p1: int = PROVEEDOR_SIMILARITY_THRESHOLD_P1,
    umbral_p2: float = CONFIDENCE_THRESHOLD_P2,
) -> Dict[str, ResumenMetodo]:
    """
    Corre el pipeline de preprocesado + OCR + extracción sobre todas las imágenes de `dataset_dir`
    y escribe `report.md`, `report.csv` y `errores.csv` en `output_dir`.
    Por defecto no usa un LLM real salvo que `usar_llm=True` (--llm).
    """
    gt_path = dataset_dir / "ground_truth.json"
    images_dir = dataset_dir / "images"
    if not gt_path.exists():
        raise FileNotFoundError(f"No se encontró ground_truth.json en {gt_path}")

    ground_truth_items: List[Dict[str, Any]] = json.loads(
        gt_path.read_text(encoding="utf-8")
    )

    predicciones_reglas: Dict[str, Comprobante] = {}
    predicciones_reglas_llm: Dict[str, Comprobante] = {}

    extractor_llm = (
        construir_extractor_llm(provider=LLM_PROVIDER, api_key=LLM_API_KEY)
        if usar_llm
        else FakeLLMExtractor(fixed_dict={})
    )

    hoy_eval = date(2026, 10, 22)

    for item in ground_truth_items:
        nombre_archivo = item["archivo"]
        img_path = images_dir / nombre_archivo
        if not img_path.exists():
            predicciones_reglas[nombre_archivo] = Comprobante()
            predicciones_reglas_llm[nombre_archivo] = Comprobante()
            continue

        file_bytes = img_path.read_bytes()
        prep = preprocesar_bytes(file_bytes, filename=nombre_archivo)
        ocr_res = ejecutar_ocr_mejores_variantes(
            prep.variantes, permitir_fallback_eng=True
        )
        comp_reg, _ = extraer_por_reglas(
            texto_ocr=ocr_res.texto,
            palabras_ocr=ocr_res.palabras,
            lineas_ocr=ocr_res.lineas,
            confianza_base_ocr=ocr_res.confianza_media,
            hoy=hoy_eval,
        )
        predicciones_reglas[nombre_archivo] = comp_reg

        if usar_llm and extractor_llm is not None:
            comp_llm, alerta_llm = extraer_con_llm_con_reintento(
                ocr_res.texto, extractor_llm
            )
            if alerta_llm is None and comp_llm is not None:
                comp_merged, _ = fusionar_reglas_y_llm(
                    comp_reg, comp_llm, ocr_res.texto
                )
            else:
                comp_merged = comp_reg
        else:
            # Con FakeLLMExtractor desactivado (comportamiento por defecto sin --llm),
            # la fusión conserva únicamente lo extraído por reglas sin tráfico de red.
            comp_merged, _ = fusionar_reglas_y_llm(comp_reg, None, ocr_res.texto)

        predicciones_reglas_llm[nombre_archivo] = comp_merged

    resumen_reglas = evaluar_predicciones_metodo(
        metodo="reglas",
        ground_truth_items=ground_truth_items,
        predicciones_por_archivo=predicciones_reglas,
        umbral_p1=umbral_p1,
        umbral_p2=umbral_p2,
    )
    resumen_llm = evaluar_predicciones_metodo(
        metodo="reglas+llm",
        ground_truth_items=ground_truth_items,
        predicciones_por_archivo=predicciones_reglas_llm,
        umbral_p1=umbral_p1,
        umbral_p2=umbral_p2,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    _escribir_report_csv(output_dir / "report.csv", [resumen_reglas, resumen_llm])
    _escribir_errores_csv(
        output_dir / "errores.csv",
        resumen_reglas.errores_detalle
        + (resumen_llm.errores_detalle if usar_llm else []),
    )
    _escribir_report_md(
        output_dir / "report.md",
        resumen_reglas=resumen_reglas,
        resumen_llm=resumen_llm,
        usar_llm=usar_llm,
        umbral_p1=umbral_p1,
        umbral_p2=umbral_p2,
    )

    return {"reglas": resumen_reglas, "reglas+llm": resumen_llm}


def _escribir_report_csv(
    ruta_csv: Path, resumenes: List[ResumenMetodo]
) -> None:
    campos_orden = list(CAMPOS_EVALUADOS) + ["proveedor_razon_social_exacto"]
    with ruta_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "metodo",
                "campo",
                "referencia_no_nula",
                "coincidencias",
                "exactitud",
                "falsos_positivos",
                "omisiones",
                "errores",
            ]
        )
        for res in resumenes:
            for c_name in campos_orden:
                cnt = res.por_campo[c_name]
                writer.writerow(
                    [
                        res.metodo,
                        c_name,
                        cnt.referencia_no_nula,
                        cnt.coincidencias,
                        f"{cnt.exactitud:.4f}",
                        cnt.falsos_positivos,
                        cnt.omisiones,
                        cnt.errores,
                    ]
                )


def _escribir_errores_csv(
    ruta_csv: Path, errores: List[ErrorDetalle]
) -> None:
    with ruta_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "imagen",
                "campo",
                "esperado",
                "obtenido",
                "texto_origen",
                "metodo",
                "tipo_discrepancia",
            ]
        )
        for e in errores:
            writer.writerow(
                [
                    e.imagen,
                    e.campo,
                    e.esperado,
                    e.obtenido,
                    e.texto_origen,
                    e.metodo,
                    e.tipo_discrepancia,
                ]
            )


def _escribir_report_md(
    ruta_md: Path,
    resumen_reglas: ResumenMetodo,
    resumen_llm: ResumenMetodo,
    usar_llm: bool,
    umbral_p1: int,
    umbral_p2: float,
) -> None:
    _, langs_disp, _ = verificar_tesseract_instalado(requerir_spa=False)
    nota_llm = (
        f"LLM externo activado (`--llm`, proveedor `{LLM_PROVIDER}`)"
        if usar_llm
        else "Modo sin red por defecto (`FakeLLMExtractor` desactivado; `reglas+llm` refleja base solo reglas)"
    )

    lineas: List[str] = [
        "# Reporte de Evaluación de Extracción de Comprobantes",
        "",
        "> **Advertencia metodológica:** Los resultados medidos sobre el dataset sintético (`eval/dataset/`) "
        "evalúan la robustez del pipeline ante rotaciones, variaciones de contraste, sombras simuladas y ruido, "
        "pero **no reemplazan comprobantes reales autorizados**. La exactitud sobre comprobantes sintéticos "
        "sobrestima la exactitud real en producción con papel térmico físico deteriorado.",
        "",
        "## Parámetros de la corrida",
        "",
        f"- **Comprobantes evaluados:** {resumen_reglas.total_comprobantes}",
        f"- **Idiomas Tesseract disponibles en el entorno:** `{', '.join(langs_disp) if langs_disp else 'N/D'}`",
        f"- **Configuración LLM:** {nota_llm}",
        f"- **Umbral de similitud de proveedor (P1):** `{umbral_p1}` (`token_sort_ratio`)",
        f"- **Umbral de confianza para revisión (P2):** `{umbral_p2:.2f}`",
        "",
        "## Exactitud a nivel comprobante (campos críticos)",
        "",
        f"- **Campos críticos considerados:** `{', '.join(CAMPOS_CRITICOS)}`",
        f"- **Método `reglas`:** {resumen_reglas.comprobantes_criticos_perfectos} / {resumen_reglas.total_comprobantes} "
        f"({resumen_reglas.exactitud_nivel_comprobante * 100:.1f}%)",
        f"- **Método `reglas+llm`:** {resumen_llm.comprobantes_criticos_perfectos} / {resumen_llm.total_comprobantes} "
        f"({resumen_llm.exactitud_nivel_comprobante * 100:.1f}%)",
        "",
        "## Métricas por campo (`reglas` vs. `reglas+llm`)",
        "",
        "| Campo | Ref. no nula | Coincidencias (Reglas) | Exactitud (Reglas) | Falsos Pos. (Reglas) | Omisiones (Reglas) | Errores (Reglas) | Exactitud (Reglas+LLM) |",
        "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    campos_orden = list(CAMPOS_EVALUADOS) + ["proveedor_razon_social_exacto"]
    for c_name in campos_orden:
        cr = resumen_reglas.por_campo[c_name]
        cl = resumen_llm.por_campo[c_name]
        lineas.append(
            f"| `{c_name}` | {cr.referencia_no_nula} | {cr.coincidencias} | "
            f"{cr.exactitud * 100:.1f}% | {cr.falsos_positivos} | {cr.omisiones} | "
            f"{cr.errores} | {cl.exactitud * 100:.1f}% |"
        )

    lineas.extend(
        [
            "",
            "## Exactitud desagregada por etiqueta de condición (`notas`)",
            "",
            "| Condición de la imagen (`notas`) | Campos correctos | Campos con ref. no nula | Exactitud (Reglas) |",
            "| :--- | ---: | ---: | ---: |",
        ]
    )
    for nota, (ok_n, tot_n) in sorted(resumen_reglas.por_nota.items()):
        acc_n = (ok_n / tot_n * 100.0) if tot_n > 0 else 0.0
        lineas.append(f"| `{nota}` | {ok_n} | {tot_n} | {acc_n:.1f}% |")

    alta_ok, alta_tot = resumen_reglas.calibracion_alta
    baja_ok, baja_tot = resumen_reglas.calibracion_baja
    acc_alta = (alta_ok / alta_tot * 100.0) if alta_tot > 0 else 0.0
    acc_baja = (baja_ok / baja_tot * 100.0) if baja_tot > 0 else 0.0

    lineas.extend(
        [
            "",
            "## Calibración simple de confianza (`>= P2` frente a `< P2`)",
            "",
            "| Segmento de confianza | Campos extraídos acertados | Total campos extraídos | Exactitud observada |",
            "| :--- | ---: | ---: | ---: |",
            f"| Confianza `>= {umbral_p2:.2f}` (no requiere revisión por P2) | {alta_ok} | {alta_tot} | {acc_alta:.1f}% |",
            f"| Confianza `< {umbral_p2:.2f}` (marcado revisar) | {baja_ok} | {baja_tot} | {acc_baja:.1f}% |",
            "",
        ]
    )

    ruta_md.write_text("\n".join(lineas), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evalúa la exactitud por campo del lector de comprobantes contra ground_truth.json."
    )
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=ROOT_DIR / "eval" / "dataset",
        help="Ruta a la carpeta del dataset que contiene images/ y ground_truth.json",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT_DIR / "eval",
        help="Carpeta donde se guardarán report.md, report.csv y errores.csv",
    )
    parser.add_argument(
        "--llm",
        action="store_true",
        help="Activa la consulta al proveedor LLM real configurado en variables de entorno.",
    )
    args = parser.parse_args()

    res = ejecutar_evaluacion_dataset(
        dataset_dir=args.dataset_dir,
        output_dir=args.output_dir,
        usar_llm=args.llm,
    )
    reg = res["reglas"]
    print(
        f"Evaluación completada sobre {reg.total_comprobantes} comprobantes. "
        f"Exactitud nivel comprobante (reglas): {reg.exactitud_nivel_comprobante * 100:.1f}%. "
        f"Reportes generados en {args.output_dir}"
    )


if __name__ == "__main__":
    main()
