"""Pruebas unitarias de métricas de evaluación: normalización, falsos positivos, omisiones e importes exactos."""
from __future__ import annotations

from decimal import Decimal

from app.models import Campo, Comprobante, ItemIVA
from eval.metrics import (
    comparar_campo,
    evaluar_predicciones_metodo,
    normalizar_valor_para_eval,
)


def test_normalizacion_campos_fiscales_y_fechas():
    assert normalizar_valor_para_eval("fecha_emision", "2026-10-15") == "2026-10-15"
    assert normalizar_valor_para_eval("proveedor_cuit", "30-71001122-8") == "30710011228"
    assert normalizar_valor_para_eval("punto_venta", "4") == "00004"
    assert normalizar_valor_para_eval("numero_comprobante", "15892") == "00015892"
    assert normalizar_valor_para_eval("letra", "a") == "A"
    assert normalizar_valor_para_eval("moneda", "ars") == "ARS"


def test_comparacion_exacta_importes_sin_tolerancia():
    # Igualdad al centavo
    cat_ok, _, _ = comparar_campo("importe_total", "1210.00", Decimal("1210.00"))
    assert cat_ok == "coincidencia"

    # Diferencia de 1 centavo debe ser error (sin tolerancia en la evaluación)
    cat_err, _, _ = comparar_campo("importe_total", "1210.00", Decimal("1210.01"))
    assert cat_err == "error"


def test_comparacion_proveedor_difusa_vs_exacta():
    # Con sufijo S.R.L. y orden de palabras / pequeño cambio
    esp = "DISTRIBUIDORA DEL NORTE S.R.L."
    obt = "Distribuidora del Norte"
    cat_fuzzy, _, _ = comparar_campo("proveedor_razon_social", esp, obt, umbral_p1=90)
    assert cat_fuzzy == "coincidencia"

    # Con error de 1 letra donde ratio >= 90 pero igualdad exacta da error
    obt_typo = "Distribuidora del Nortes"
    cat_fuzzy2, _, _ = comparar_campo("proveedor_razon_social", esp, obt_typo, umbral_p1=90)
    cat_exact2, _, _ = comparar_campo("proveedor_razon_social_exacto", esp, obt_typo, umbral_p1=100)
    assert cat_fuzzy2 == "coincidencia"
    assert cat_exact2 == "error"


def test_comparacion_conjunto_iva():
    esp = [{"alicuota": "21", "importe": "210.00"}, {"alicuota": "10.5", "importe": "105.00"}]
    obt = [
        ItemIVA(alicuota=Decimal("10.5"), importe=Decimal("105.00")),
        ItemIVA(alicuota=Decimal("21.00"), importe=Decimal("210.00")),
    ]
    cat, _, _ = comparar_campo("iva", esp, obt)
    assert cat == "coincidencia"


def test_falsos_positivos_omisiones_y_exactitud_comprobante():
    gt = [
        {
            "archivo": "comp_01.jpg",
            "notas": ["termico", "sombra"],
            "campos": {
                "fecha_emision": "2026-10-15",
                "proveedor_razon_social": "PANADERIA EL SOL S.A.",
                "proveedor_cuit": "30710011228",
                "tipo_comprobante": "Ticket",
                "letra": "B",
                "punto_venta": "0001",
                "numero_comprobante": "00001234",
                "importe_neto_gravado": None,
                "iva": [],
                "otros_impuestos": [],
                "importe_total": "4500.00",
                "moneda": "ARS",
                "cae": None,
            },
        }
    ]
    # Predicción con:
    # - cae inventado -> falso positivo
    # - fecha_emision nula -> omisión (y falla campo crítico)
    # - importe_total distinto -> error
    pred = {
        "comp_01.jpg": Comprobante(
            fecha_emision=Campo(valor=None, confianza=0.0, fuente="ninguna"),
            proveedor_razon_social=Campo(valor="PANADERIA EL SOL", confianza=0.9, fuente="reglas"),
            proveedor_cuit=Campo(valor="30710011228", confianza=0.95, fuente="reglas"),
            tipo_comprobante=Campo(valor="Ticket", confianza=0.9, fuente="reglas"),
            letra=Campo(valor="B", confianza=0.9, fuente="reglas"),
            punto_venta=Campo(valor="00001", confianza=0.9, fuente="reglas"),
            numero_comprobante=Campo(valor="00001234", confianza=0.9, fuente="reglas"),
            importe_total=Campo(valor=Decimal("4500.50"), confianza=0.65, fuente="reglas"),
            moneda=Campo(valor="ARS", confianza=0.9, fuente="reglas"),
            cae=Campo(valor="74123456789012", confianza=0.70, fuente="reglas"),
        )
    }

    resumen = evaluar_predicciones_metodo("reglas", gt, pred)
    assert resumen.por_campo["cae"].falsos_positivos == 1
    assert resumen.por_campo["fecha_emision"].omisiones == 1
    assert resumen.por_campo["importe_total"].errores == 1
    assert resumen.por_campo["proveedor_cuit"].coincidencias == 1
    assert resumen.exactitud_nivel_comprobante == 0.0
    assert "termico" in resumen.por_nota
