"""Exportación de comprobantes seleccionados a CSV y XLSX con pandas y openpyxl."""
from __future__ import annotations

import io
from decimal import Decimal
from typing import Any, Dict, List, Sequence

import pandas as pd

from app.models import Resultado


def resultados_a_filas_planas(resultados: Sequence[Resultado]) -> List[Dict[str, Any]]:
    """Convierte una lista de objetos Resultado a diccionarios planos aptos para tabla, CSV y XLSX."""
    filas: List[Dict[str, Any]] = []
    for r in resultados:
        c = r.comprobante.normalize_types()
        iva_items = c.iva.valor or []
        otros_items = c.otros_impuestos.valor or []

        suma_iva = sum((i.importe for i in iva_items), Decimal("0.00"))
        suma_otros = sum((o.importe for o in otros_items), Decimal("0.00"))

        iva_detalle = "; ".join(f"{i.alicuota}%: {i.importe}" for i in iva_items)
        otros_detalle = "; ".join(f"{o.descripcion}: {o.importe}" for o in otros_items)

        filas.append(
            {
                "id": r.id,
                "creado_en": r.creado_en,
                "estado": r.estado,
                "metodo": r.metodo,
                "variante_preprocesado": r.variante_preprocesado,
                "ocr_confianza_media": r.ocr_confianza_media,
                "fecha_emision": (
                    c.fecha_emision.valor.isoformat()
                    if hasattr(c.fecha_emision.valor, "isoformat")
                    else c.fecha_emision.valor
                ),
                "proveedor_razon_social": c.proveedor_razon_social.valor,
                "proveedor_cuit": c.proveedor_cuit.valor,
                "tipo_comprobante": c.tipo_comprobante.valor,
                "letra": c.letra.valor,
                "punto_venta": c.punto_venta.valor,
                "numero_comprobante": c.numero_comprobante.valor,
                "moneda": c.moneda.valor,
                "importe_neto_gravado": (
                    float(c.importe_neto_gravado.valor)
                    if c.importe_neto_gravado.valor is not None
                    else None
                ),
                "iva_total": float(suma_iva) if iva_items else None,
                "iva_detalle": iva_detalle or None,
                "otros_impuestos_total": float(suma_otros) if otros_items else None,
                "otros_impuestos_detalle": otros_detalle or None,
                "importe_total": (
                    float(c.importe_total.valor)
                    if c.importe_total.valor is not None
                    else None
                ),
                "cae": c.cae.valor,
                "alertas": " | ".join(r.alertas) if r.alertas else "",
                "hash_imagen": r.hash_imagen,
            }
        )
    return filas


def exportar_csv(resultados: Sequence[Resultado]) -> bytes:
    """Genera un archivo CSV (UTF-8 con BOM para compatibilidad directa con Excel) en memoria."""
    filas = resultados_a_filas_planas(resultados)
    df = pd.DataFrame(filas)
    return df.to_csv(index=False).encode("utf-8-sig")


def exportar_xlsx(resultados: Sequence[Resultado]) -> bytes:
    """Genera un libro Excel (.xlsx) con hoja de comprobantes y hoja de desglose de impuestos."""
    filas = resultados_a_filas_planas(resultados)
    df_principal = pd.DataFrame(filas)

    filas_impuestos: List[Dict[str, Any]] = []
    for r in resultados:
        c = r.comprobante.normalize_types()
        for item_iva in c.iva.valor or []:
            filas_impuestos.append(
                {
                    "resultado_id": r.id,
                    "proveedor_cuit": c.proveedor_cuit.valor,
                    "numero_comprobante": c.numero_comprobante.valor,
                    "categoria": "IVA",
                    "concepto_o_alicuota": f"IVA {item_iva.alicuota}%",
                    "importe": float(item_iva.importe),
                }
            )
        for item_otro in c.otros_impuestos.valor or []:
            filas_impuestos.append(
                {
                    "resultado_id": r.id,
                    "proveedor_cuit": c.proveedor_cuit.valor,
                    "numero_comprobante": c.numero_comprobante.valor,
                    "categoria": "Otro Impuesto",
                    "concepto_o_alicuota": item_otro.descripcion,
                    "importe": float(item_otro.importe),
                }
            )
    df_impuestos = pd.DataFrame(filas_impuestos)

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df_principal.to_excel(writer, sheet_name="Comprobantes", index=False)
        if not df_impuestos.empty:
            df_impuestos.to_excel(writer, sheet_name="Detalle_Impuestos", index=False)
    return buffer.getvalue()
