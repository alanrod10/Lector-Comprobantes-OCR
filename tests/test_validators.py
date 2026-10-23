"""Pruebas unitarias de validadores: CUIT (incluidos restos 10 y 11), fechas, aritmética y duplicados."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.locale_ar import calcular_digito_verificador_cuit, normalizar_monto, validar_cuit
from app.models import Campo, Comprobante, ItemImpuesto, ItemIVA, Resultado
from app.validators import (
    ejecutar_validaciones,
    validar_aritmetica_importes,
    validar_cuit_campo,
    validar_duplicado,
    validar_fecha_campo,
    validar_letra_e_iva,
    validar_longitudes,
)


def test_cuit_valido_estandar():
    # 30-71122334-9 -> verifiquemos cálculo
    verif = calcular_digito_verificador_cuit("3071122334")
    assert verif is not None
    cuit = f"30-71122334-{verif}"
    ok, msg = validar_cuit(cuit)
    assert ok is True
    assert "válido" in msg


def test_cuit_caso_resto_11_da_verificador_0():
    # Buscamos una base de 10 dígitos donde suma % 11 == 0 -> verificador = 11 -> 0
    # 20-00000000: 2*5 + 0 = 10 -> si ponemos d9=2 (peso 2 -> 4) y d8=3 (peso 3 -> 9): 10+9+4=23 (mod 11=1)
    # 20-00000060: 2*5 + 6*3 = 28; 20-00000102: 2*5 + 1*4 + 2*2 = 18; 20-00000300: 2*5 + 3*4 = 22 (22 % 11 == 0)
    base_resto_cero = "2000000300"
    assert calcular_digito_verificador_cuit(base_resto_cero) == 0
    ok, _ = validar_cuit(base_resto_cero + "0")
    assert ok is True


def test_cuit_caso_resto_10_es_invalido():
    # Si suma % 11 == 1 -> 11 - 1 = 10 -> inválido para cualquier dígito final
    # 20-00000301 -> 2*5 + 3*4 + 1*2 = 10 + 12 + 2 = 24 (24 % 11 = 2)
    # Para obtener suma = 23 (23 % 11 = 1): 2*5 (10) + 1*7 (7) + 2*3 (6) = 23 -> "2000100020"
    # Verifiquemos pesos: (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
    # indices: 0->2*5=10, 4->1*7=7, 8->2*3=6 -> suma=23 -> 23%11=1 -> 11-1=10
    base_resto_uno = "2000100020"
    assert calcular_digito_verificador_cuit(base_resto_uno) is None
    for digito in range(10):
        ok, msg = validar_cuit(base_resto_uno + str(digito))
        assert ok is False
        assert "10" in msg


def test_cuit_digito_incorrecto_y_longitud():
    verif = calcular_digito_verificador_cuit("3071122334")
    mal_verif = (verif + 1) % 10
    ok, _ = validar_cuit(f"3071122334{mal_verif}")
    assert ok is False
    ok_corto, _ = validar_cuit("30711223")
    assert ok_corto is False


def test_fechas_validas_e_invalidas():
    hoy = date(2026, 10, 22)
    alerta_ok = validar_fecha_campo(date(2026, 10, 15), hoy=hoy)
    assert alerta_ok.severidad == "OK"

    # Hasta hoy + 1 día es aceptado por diferencia horaria
    alerta_maniana = validar_fecha_campo(date(2026, 10, 23), hoy=hoy)
    assert alerta_maniana.severidad == "OK"

    # Futura (> hoy + 1 día)
    alerta_futura = validar_fecha_campo(date(2026, 10, 25), hoy=hoy)
    assert alerta_futura.severidad == "ERROR"
    assert alerta_futura.codigo == "FECHA_FUTURA"

    # Anterior a 2000-01-01
    alerta_vieja = validar_fecha_campo(date(1999, 12, 31), hoy=hoy)
    assert alerta_vieja.severidad == "ERROR"
    assert alerta_vieja.codigo == "FECHA_ANTERIOR_LIMITE"


def test_aritmetica_con_y_sin_tolerancia():
    # Caso exacto
    alertas_ok = validar_aritmetica_importes(
        neto=Decimal("1000.00"),
        iva_items=[ItemIVA(alicuota=Decimal("21"), importe=Decimal("210.00"))],
        otros_items=[ItemImpuesto(descripcion="Percepción IIBB", importe=Decimal("30.00"))],
        total=Decimal("1240.00"),
    )
    assert any(a.codigo == "ARITMETICA_OK" for a in alertas_ok)

    # Caso dentro de tolerancia de 0.02 (diferencia de 0.02)
    alertas_tol = validar_aritmetica_importes(
        neto=Decimal("1000.00"),
        iva_items=[ItemIVA(alicuota=Decimal("21"), importe=Decimal("210.00"))],
        otros_items=[],
        total=Decimal("1210.02"),
    )
    assert any(a.codigo == "ARITMETICA_OK" for a in alertas_tol)

    # Caso fuera de tolerancia (diferencia de 0.05) -> ERROR y marca revisar en ejecutar_validaciones
    comp = Comprobante(
        importe_neto_gravado=Campo(valor=Decimal("1000.00"), confianza=0.95, fuente="reglas"),
        iva=Campo(
            valor=[ItemIVA(alicuota=Decimal("21"), importe=Decimal("210.00"))],
            confianza=0.95,
            fuente="reglas",
        ),
        importe_total=Campo(valor=Decimal("1250.00"), confianza=0.95, fuente="reglas"),
    )
    res = Resultado(hash_imagen="abc123hash", comprobante=comp)
    res = ejecutar_validaciones(res, hoy=date(2026, 10, 22))
    assert res.comprobante.importe_total.revisar is True
    # Verificar que no se corrigió automáticamente el total
    assert res.comprobante.importe_total.valor == Decimal("1250.00")
    assert any("difiere del total" in a for a in res.alertas)


def test_letra_b_con_iva_discriminado_alerta_informativa():
    alerta = validar_letra_e_iva(
        "B", [ItemIVA(alicuota=Decimal("21"), importe=Decimal("210.00"))]
    )
    assert alerta.severidad == "ADVERTENCIA"
    assert alerta.codigo == "IVA_DISCRIMINADO_EN_B_O_C"


def test_longitudes_pv_numero_cae():
    alertas = validar_longitudes(punto_venta="123456", numero_comprobante="123456789", cae="12345")
    codigos = {a.codigo for a in alertas}
    assert "PUNTO_VENTA_INVALIDO" in codigos
    assert "NUMERO_COMPROBANTE_INVALIDO" in codigos
    assert "CAE_LONGITUD_INVALIDA" in codigos


def test_duplicados_por_hash_y_por_clave_fiscal():
    comp = Comprobante(
        proveedor_cuit=Campo(valor="30711223349", confianza=0.9, fuente="reglas"),
        tipo_comprobante=Campo(valor="Factura", confianza=0.9, fuente="reglas"),
        letra=Campo(valor="A", confianza=0.9, fuente="reglas"),
        punto_venta=Campo(valor="0001", confianza=0.9, fuente="reglas"),
        numero_comprobante=Campo(valor="00001234", confianza=0.9, fuente="reglas"),
    )
    historial = [
        {
            "id": "old-1",
            "hash_imagen": "hash-existente",
            "proveedor_cuit": "30711223349",
            "tipo_comprobante": "Factura",
            "letra": "A",
            "punto_venta": "00001",
            "numero_comprobante": "00001234",
        }
    ]
    dup_hash = validar_duplicado(comp, "hash-existente", historial, id_actual="new-1")
    assert dup_hash is not None
    assert dup_hash.codigo == "DUPLICADO_HASH_IMAGEN"

    dup_fiscal = validar_duplicado(comp, "otro-hash", historial, id_actual="new-1")
    assert dup_fiscal is not None
    assert dup_fiscal.codigo == "DUPLICADO_CLAVE_FISCAL"


def test_normalizar_monto_formatos_y_errores_ocr():
    assert normalizar_monto("1.234,56") == Decimal("1234.56")
    assert normalizar_monto("1,234.56") == Decimal("1234.56")
    assert normalizar_monto("$ 15.000,00") == Decimal("15000.00")
    # Errores de OCR dentro de token con mayoría de dígitos: O->0, I/l->1, S->5
    assert normalizar_monto("1.234,S0") == Decimal("1234.50")
    assert normalizar_monto("I2O,00") == Decimal("120.00")
    # Texto no numérico devuelve None
    assert normalizar_monto("SIN MONTO") is None
