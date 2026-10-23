"""Pruebas unitarias de la política de fusión (Sección 10) y verificación de anclaje del LLM."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.extract_llm import FakeLLMExtractor, extraer_con_llm_con_reintento
from app.locale_ar import calcular_digito_verificador_cuit
from app.merge import fusionar_reglas_y_llm
from app.models import Campo, Comprobante


def _cuit_valido(base10: str) -> str:
    v = calcular_digito_verificador_cuit(base10)
    assert v is not None
    return f"{base10}{v}"


def test_caso_1_solo_reglas_aportan_valor():
    texto_ocr = "FACTURA A\nTOTAL: $ 1.500,00"
    reglas = Comprobante(
        importe_total=Campo(
            valor=Decimal("1500.00"),
            confianza=0.88,
            fuente="reglas",
            texto_origen="TOTAL: $ 1.500,00",
        )
    )
    llm = Comprobante()
    fusionado, alertas = fusionar_reglas_y_llm(reglas, llm, texto_ocr)
    assert fusionado.importe_total.valor == Decimal("1500.00")
    assert fusionado.importe_total.fuente == "reglas"
    assert fusionado.importe_total.confianza == 0.88
    assert not alertas


def test_caso_2a_solo_llm_aporta_valor_con_anclaje_valido():
    cuit = _cuit_valido("3071001122")
    cuit_guion = f"{cuit[:2]}-{cuit[2:10]}-{cuit[10]}"
    texto_ocr = f"LA ESPIGA S.R.L.\nIdentificación Tributaria: {cuit_guion}\nTotal: $ 2.000,00"
    reglas = Comprobante()
    llm = Comprobante(
        proveedor_cuit=Campo(
            valor=cuit,
            confianza=0.91,
            fuente="llm",
            texto_origen=f"Identificación Tributaria: {cuit_guion}",
        )
    )
    fusionado, alertas = fusionar_reglas_y_llm(reglas, llm, texto_ocr)
    assert fusionado.proveedor_cuit.valor == cuit
    assert fusionado.proveedor_cuit.fuente == "llm"
    assert not alertas


def test_caso_2b_solo_llm_aporta_valor_descartado_por_falta_de_anclaje():
    texto_ocr = "LA ESPIGA S.R.L.\nTotal: $ 2.000,00"
    reglas = Comprobante()
    llm = Comprobante(
        cae=Campo(
            valor="74123456789012",
            confianza=0.95,
            fuente="llm",
            texto_origen="CAE: 74123456789012",
        )
    )
    fusionado, alertas = fusionar_reglas_y_llm(reglas, llm, texto_ocr)
    assert fusionado.cae.valor is None
    assert fusionado.cae.fuente == "ninguna"
    assert any("falla de anclaje" in a for a in alertas)


def test_caso_3_ambos_aportan_valores_iguales_sube_confianza():
    texto_ocr = "Fecha de Emisión: 15/10/2026\nIMPORTE TOTAL: $ 3.400,50"
    reglas = Comprobante(
        fecha_emision=Campo(
            valor=date(2026, 10, 15),
            confianza=0.78,
            fuente="reglas",
            texto_origen="Fecha de Emisión: 15/10/2026",
        ),
        importe_total=Campo(
            valor=Decimal("3400.50"),
            confianza=0.82,
            fuente="reglas",
            texto_origen="IMPORTE TOTAL: $ 3.400,50",
        ),
    )
    llm = Comprobante(
        fecha_emision=Campo(
            valor=date(2026, 10, 15),
            confianza=0.94,
            fuente="llm",
            texto_origen="15/10/2026",
        ),
        importe_total=Campo(
            valor=Decimal("3400.50"),
            confianza=0.90,
            fuente="llm",
            texto_origen="IMPORTE TOTAL: $ 3.400,50",
        ),
    )
    fusionado, alertas = fusionar_reglas_y_llm(reglas, llm, texto_ocr)
    assert fusionado.fecha_emision.valor == date(2026, 10, 15)
    assert fusionado.fecha_emision.confianza == 0.94
    assert fusionado.importe_total.confianza == 0.90
    assert not alertas


def test_caso_4_ambos_aportan_valores_distintos_conserva_reglas_y_guarda_sugerencia():
    texto_ocr = "Subtotal: $ 1.000,00\nTOTAL: $ 1.210,00"
    reglas = Comprobante(
        importe_total=Campo(
            valor=Decimal("1210.00"),
            confianza=0.85,
            fuente="reglas",
            texto_origen="TOTAL: $ 1.210,00",
        )
    )
    llm = Comprobante(
        importe_total=Campo(
            valor=Decimal("1000.00"),
            confianza=0.92,
            fuente="llm",
            texto_origen="Subtotal: $ 1.000,00",
        )
    )
    fusionado, alertas = fusionar_reglas_y_llm(reglas, llm, texto_ocr)
    assert fusionado.importe_total.valor == Decimal("1210.00")
    assert fusionado.importe_total.fuente == "reglas"
    assert fusionado.importe_total.revisar is True
    assert fusionado.importe_total.sugerencia_llm == Decimal("1000.00")
    assert fusionado.importe_total.sugerencia_texto_origen == "Subtotal: $ 1.000,00"
    assert any("Discrepancia entre reglas y LLM" in a for a in alertas)


def test_reintento_llm_ante_json_invalido():
    fake = FakeLLMExtractor(
        responses=[
            "ESTO NO ES JSON",
            {
                "importe_total": {
                    "valor": "1500.00",
                    "confianza": 0.9,
                    "texto_origen": "TOTAL $ 1.500,00",
                }
            },
        ]
    )
    comp, alerta = extraer_con_llm_con_reintento("TOTAL $ 1.500,00", fake)
    assert fake.calls == 2
    assert alerta is None
    assert comp is not None
    assert comp.importe_total.valor == Decimal("1500.00")

    fake_fail = FakeLLMExtractor(responses=["mal 1", "mal 2"])
    comp_f, alerta_f = extraer_con_llm_con_reintento("TOTAL $ 1.500,00", fake_fail)
    assert fake_fail.calls == 2
    assert comp_f is None
    assert alerta_f == "LLM no disponible o respuesta inválida"
