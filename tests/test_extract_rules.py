"""Pruebas unitarias de extracción por reglas sobre al menos 12 textos OCR representativos."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.extract_rules import extraer_por_reglas
from app.locale_ar import calcular_digito_verificador_cuit


def _cuit_valido(base10: str) -> str:
    v = calcular_digito_verificador_cuit(base10)
    assert v is not None
    return f"{base10[:2]}-{base10[2:]}-{v}"


def test_01_factura_a_completa_estandar():
    cuit_emisor = _cuit_valido("3071001122")
    cuit_cliente = _cuit_valido("3065432198")
    ocr = f"""
    ORIGINAL
    FACTURA A
    COD. 01
    DISTRIBUIDORA DEL NORTE S.R.L.
    Punto de Venta: 0004 Comp. Nro: 00015892
    Fecha de Emisión: 14/09/2026
    C.U.I.T.: {cuit_emisor}
    Ingresos Brutos: 901-123456-7
    Inicio de Actividades: 01/03/2015
    ----------------------------------------
    Cliente: COMERCIO DEL SUR S.A.
    CUIT: {cuit_cliente}
    Condición frente al IVA: Responsable Inscripto
    ----------------------------------------
    Importe Neto Gravado: $ 10.000,00
    IVA 21%: $ 2.100,00
    Importe Total: $ 12.100,00
    CAE N°: 74382910456123
    Fecha de Vto. de CAE: 24/09/2026
    """
    comp, alertas = extraer_por_reglas(ocr, hoy=date(2026, 10, 22))
    assert comp.tipo_comprobante.valor == "Factura"
    assert comp.letra.valor == "A"
    assert comp.proveedor_razon_social.valor == "DISTRIBUIDORA DEL NORTE S.R.L."
    assert comp.proveedor_cuit.valor == cuit_emisor.replace("-", "")
    assert comp.punto_venta.valor == "0004"
    assert comp.numero_comprobante.valor == "00015892"
    assert comp.fecha_emision.valor == date(2026, 9, 14)
    assert comp.importe_neto_gravado.valor == Decimal("10000.00")
    assert len(comp.iva.valor) == 1
    assert comp.iva.valor[0].alicuota == Decimal("21")
    assert comp.iva.valor[0].importe == Decimal("2100.00")
    assert comp.importe_total.valor == Decimal("12100.00")
    assert comp.moneda.valor == "ARS"
    assert comp.cae.valor == "74382910456123"
    assert not alertas


def test_02_factura_a_multiples_alicuotas_y_percepcion():
    cuit_emisor = _cuit_valido("3050001234")
    ocr = f"""
    MAYORISTA ALIMENTICIO S.A.
    FACTURA A   COD. 001
    Nro: 00012 - 00450123
    Fecha: 02-10-2026
    CUIT {cuit_emisor}
    Ingresos Brutos: Exento
    Neto Gravado $ 20.000,00
    IVA 21% $ 2.100,00
    IVA 10,5% $ 1.050,00
    Percepción IIBB $ 400,00
    TOTAL A PAGAR $ 23.550,00
    C.A.E.: 74111222333444
    """
    comp, _ = extraer_por_reglas(ocr, hoy=date(2026, 10, 22))
    assert comp.proveedor_razon_social.valor == "MAYORISTA ALIMENTICIO S.A."
    assert comp.punto_venta.valor == "00012"
    assert comp.numero_comprobante.valor == "00450123"
    assert comp.importe_neto_gravado.valor == Decimal("20000.00")
    assert len(comp.iva.valor) == 2
    assert len(comp.otros_impuestos.valor) == 1
    assert comp.otros_impuestos.valor[0].importe == Decimal("400.00")
    assert comp.importe_total.valor == Decimal("23550.00")


def test_03_factura_b_consumidor_final():
    cuit_emisor = _cuit_valido("3061112224")
    ocr = f"""
    FERRETERIA INDUSTRIAL SAN MARTIN S.R.L.
    FACTURA B
    COD. 06
    0002-00089100
    Fecha de emisión: 12 de octubre de 2026
    C.U.I.T.: {cuit_emisor}
    Ingresos Brutos: 30611122249
    A Consumidor Final
    Subtotal: $ 45.800,50
    IMPORTE TOTAL: $ 45.800,50
    CAE: 74999888777666
    """
    comp, _ = extraer_por_reglas(ocr, hoy=date(2026, 10, 22))
    assert comp.tipo_comprobante.valor == "Factura"
    assert comp.letra.valor == "B"
    assert comp.fecha_emision.valor == date(2026, 10, 12)
    assert comp.importe_total.valor == Decimal("45800.50")
    assert comp.importe_neto_gravado.valor is None
    assert comp.iva.valor == []


def test_04_factura_c_monotributo():
    cuit_emisor = _cuit_valido("2031223344")
    ocr = f"""
    SERVICIOS GRAFICOS JUJUY
    FACTURA C
    COD. 011
    Punto de Venta: 00003 Comp. Nro: 00000412
    Fecha de Emisión: 05.08.2026
    CUIT: {cuit_emisor}
    Responsable Monotributo
    Importe Total: $ 18.500,00
    CAE Nro: 74000111222333
    """
    comp, _ = extraer_por_reglas(ocr, hoy=date(2026, 10, 22))
    assert comp.tipo_comprobante.valor == "Factura"
    assert comp.letra.valor == "C"
    assert comp.proveedor_razon_social.valor == "SERVICIOS GRAFICOS JUJUY"
    assert comp.proveedor_cuit.valor == cuit_emisor.replace("-", "")
    assert comp.fecha_emision.valor == date(2026, 8, 5)
    assert comp.importe_total.valor == Decimal("18500.00")
    assert comp.importe_neto_gravado.valor is None


def test_05_ticket_termico_supermercado_sin_cae():
    cuit_emisor = _cuit_valido("3058889991")
    ocr = f"""
    SUPERMERCADO EL SOL S.A.
    C.U.I.T. {cuit_emisor}
    INGRESOS BRUTOS: CONV. MULT.
    TIQUE FACTURA B
    P.V. NRO. 0015 - 01234567
    FECHA: 19/10/26  HORA: 18:42
    LECHE ENTERA 1L          $ 1.500,00
    PAN LACTEADO             $ 2.800,00
    TOTAL                    $ 4.300,00
    RECIBIDO EFECTIVO        $ 5.000,00
    """
    comp, _ = extraer_por_reglas(ocr, hoy=date(2026, 10, 22))
    assert comp.tipo_comprobante.valor in ("Ticket Factura", "Ticket")
    assert comp.letra.valor == "B"
    assert comp.punto_venta.valor == "0015"
    assert comp.numero_comprobante.valor == "01234567"
    assert comp.fecha_emision.valor == date(2026, 10, 19)
    assert comp.importe_total.valor == Decimal("4300.00")
    assert comp.cae.valor is None
    assert comp.cae.fuente == "ninguna"


def test_06_nota_de_credito_a():
    cuit_emisor = _cuit_valido("3070998877")
    ocr = f"""
    PAPELERA DEL NOA S.A.
    NOTA DE CRÉDITO A
    0001 - 00000987
    Fecha de emisión: 10/10/2026
    CUIT: {cuit_emisor}
    Ingresos Brutos: 907-445566-1
    Importe Neto Gravado: $ 5.000,00
    IVA 21%: $ 1.050,00
    Importe Total: $ 6.050,00
    CAE: 74555666777888
    """
    comp, _ = extraer_por_reglas(ocr, hoy=date(2026, 10, 22))
    assert comp.tipo_comprobante.valor == "Nota de crédito"
    assert comp.letra.valor == "A"
    assert comp.importe_neto_gravado.valor == Decimal("5000.00")
    assert comp.importe_total.valor == Decimal("6050.00")


def test_07_remito_x_sin_importes():
    cuit_emisor = _cuit_valido("3069991112")
    ocr = f"""
    LOGISTICA ANDINA S.R.L.
    REMITO X
    DOCUMENTO NO VALIDO COMO FACTURA
    0005-00043210
    Fecha: 11/10/2026
    CUIT: {cuit_emisor}
    Ingresos Brutos: 123456
    10 CAJAS DE RESMAS A4
    """
    comp, _ = extraer_por_reglas(ocr, hoy=date(2026, 10, 22))
    assert comp.tipo_comprobante.valor == "Remito"
    assert comp.letra.valor == "X"
    assert comp.importe_total.valor is None
    assert comp.importe_total.fuente == "ninguna"
    assert comp.moneda.valor is None
    assert comp.moneda.fuente == "ninguna"


def test_08_ruido_ocr_en_montos_y_cae():
    cuit_emisor = _cuit_valido("3071122334")
    ocr = f"""
    PANIFICADORA CENTRAL S.R.L.
    FACTURA A
    0001-00002345
    Fecha: 15/10/2026
    CUIT: {cuit_emisor}
    Ingresos Brutos: 901-000
    Neto Gravado: $ 1.000,O0
    IVA 21%: $ 2I0,00
    TOTAL: $ 1.210,O0
    CAE: 741234S6789O12
    """
    comp, _ = extraer_por_reglas(ocr, hoy=date(2026, 10, 22))
    assert comp.importe_neto_gravado.valor == Decimal("1000.00")
    assert comp.iva.valor[0].importe == Decimal("210.00")
    assert comp.importe_total.valor == Decimal("1210.00")
    assert comp.cae.valor == "74123456789012"


def test_09_formato_numerico_anglosajon_y_dolares():
    cuit_emisor = _cuit_valido("3071556677")
    ocr = f"""
    CLOUD HOSTING ARGENTINA S.A.S.
    FACTURA A
    0008-00011223
    Fecha de emisión: 01/10/2026
    C.U.I.T.: {cuit_emisor}
    Moneda: USD
    Importe Neto Gravado: USD 1,200.50
    IVA 21%: USD 252.11
    Importe Total: USD 1,452.61
    CAE: 74888777666555
    """
    comp, _ = extraer_por_reglas(ocr, hoy=date(2026, 10, 22))
    assert comp.moneda.valor == "USD"
    assert comp.importe_neto_gravado.valor == Decimal("1200.50")
    assert comp.iva.valor[0].importe == Decimal("252.11")
    assert comp.importe_total.valor == Decimal("1452.61")


def test_10_cuit_ambiguo_emisor_y_receptor_juntos():
    cuit_1 = _cuit_valido("3071001122")
    cuit_2 = _cuit_valido("3065432198")
    ocr = f"""
    PROVEEDOR UNO S.A.
    FACTURA A
    0001-00001111
    Fecha: 18/10/2026
    CUIT: {cuit_1}   CUIT: {cuit_2}
    TOTAL: $ 5.000,00
    """
    comp, alertas = extraer_por_reglas(ocr, hoy=date(2026, 10, 22))
    assert comp.proveedor_cuit.valor == cuit_1.replace("-", "")
    assert comp.proveedor_cuit.revisar is True
    assert any("CUIT ambiguo entre emisor y receptor" in a for a in alertas)


def test_11_varios_totales_elige_el_ultimo():
    cuit_emisor = _cuit_valido("3071234567")
    ocr = f"""
    CORRALON EL PUENTE S.A.
    FACTURA B
    0003-00099887
    Fecha: 16/10/2026
    CUIT: {cuit_emisor}
    TOTAL PARCIAL: $ 8.000,00
    DESCUENTO: $ 500,00
    IMPORTE TOTAL: $ 7.500,00
    """
    comp, _ = extraer_por_reglas(ocr, hoy=date(2026, 10, 22))
    assert comp.importe_total.valor == Decimal("7500.00")


def test_12_factura_m_con_iva_27():
    cuit_emisor = _cuit_valido("3070112233")
    ocr = f"""
    ENERGIA DEL VALLE S.A.
    FACTURA M   COD. 051
    Punto de Venta: 0009 Comp. Nro: 00003344
    Fecha de Emisión: 09/10/2026
    C.U.I.T.: {cuit_emisor}
    Ingresos Brutos: 901-888999-1
    Importe Neto Gravado: $ 10.000,00
    IVA 27%: $ 2.700,00
    Importe Total: $ 12.700,00
    CAE: 74666555444333
    """
    comp, _ = extraer_por_reglas(ocr, hoy=date(2026, 10, 22))
    assert comp.tipo_comprobante.valor == "Factura"
    assert comp.letra.valor == "M"
    assert comp.iva.valor[0].alicuota == Decimal("27")
    assert comp.iva.valor[0].importe == Decimal("2700.00")
    assert comp.importe_total.valor == Decimal("12700.00")


try:
    import pytest
    _tesseract_mark = pytest.mark.tesseract
except ImportError:
    def _tesseract_mark(fn):
        return fn


@_tesseract_mark
def test_integracion_ocr_tesseract_imagen_sintetica():
    import io
    import shutil
    from PIL import Image, ImageDraw, ImageFont
    from app.preprocess import preprocesar_bytes
    from app.ocr import ejecutar_ocr_mejores_variantes

    if shutil.which("tesseract") is None:
        try:
            import pytest
            pytest.skip("Binario tesseract no instalado")
        except ImportError:
            return

    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
    cuit_emisor = _cuit_valido("3071001122")
    img = Image.new("RGB", (1000, 750), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    lineas = [
        "DISTRIBUIDORA DEL NORTE S.R.L.",
        "FACTURA A",
        "Punto de Venta: 0004 Comp. Nro: 00015892",
        "Fecha de Emision: 14/09/2026",
        f"C.U.I.T.: {cuit_emisor}",
        "Ingresos Brutos: 901-123456-7",
        "Importe Neto Gravado: $ 10.000,00",
        "IVA 21%: $ 2.100,00",
        "Importe Total: $ 12.100,00",
        "CAE: 74382910456123",
    ]
    y = 45
    for l in lineas:
        draw.text((55, y), l, fill=(0, 0, 0), font=font)
        y += 55

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    prep = preprocesar_bytes(buf.getvalue(), filename="sintetica.png")
    ocr_res = ejecutar_ocr_mejores_variantes(prep.variantes, permitir_fallback_eng=True)
    comp, _ = extraer_por_reglas(
        ocr_res.texto,
        palabras_ocr=ocr_res.palabras,
        lineas_ocr=ocr_res.lineas,
        confianza_base_ocr=ocr_res.confianza_media,
        hoy=date(2026, 10, 22),
    )
    assert comp.tipo_comprobante.valor == "Factura"
    assert comp.letra.valor == "A"
    assert comp.proveedor_cuit.valor == cuit_emisor.replace("-", "")
    assert comp.importe_total.valor == Decimal("12100.00")
    assert comp.cae.valor == "74382910456123"
