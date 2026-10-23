"""Validadores de campos, aritmética de importes, fechas, longitudes y duplicados."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence

from app.config import ARITHMETIC_TOLERANCE, CONFIDENCE_THRESHOLD_P2, MIN_VALID_DATE
from app.locale_ar import validar_cuit
from app.models import AlertaValidacion, Comprobante, ItemImpuesto, ItemIVA, Resultado, TODOS_LOS_CAMPOS


def validar_cuit_campo(cuit: Optional[str]) -> AlertaValidacion:
    """Valida formato y dígito verificador de CUIT."""
    if cuit is None or str(cuit).strip() == "":
        return AlertaValidacion(
            codigo="CUIT_VACIO",
            severidad="ADVERTENCIA",
            mensaje="No se detectó el CUIT del proveedor.",
            campo="proveedor_cuit",
        )
    es_valido, msg = validar_cuit(str(cuit))
    if not es_valido:
        return AlertaValidacion(
            codigo="CUIT_INVALIDO",
            severidad="ERROR",
            mensaje=msg,
            campo="proveedor_cuit",
        )
    return AlertaValidacion(
        codigo="CUIT_OK",
        severidad="OK",
        mensaje="CUIT del proveedor válido.",
        campo="proveedor_cuit",
    )


def validar_fecha_campo(
    fecha_val: Optional[date],
    hoy: Optional[date] = None,
    min_date: date = MIN_VALID_DATE,
) -> AlertaValidacion:
    """Valida que la fecha sea válida, no futura (> hoy + 1 día) y no anterior a min_date."""
    if fecha_val is None:
        return AlertaValidacion(
            codigo="FECHA_VACIA",
            severidad="ADVERTENCIA",
            mensaje="No se detectó la fecha de emisión.",
            campo="fecha_emision",
        )
    if isinstance(fecha_val, str):
        try:
            fecha_val = date.fromisoformat(fecha_val)
        except ValueError:
            return AlertaValidacion(
                codigo="FECHA_FORMATO_INVALIDO",
                severidad="ERROR",
                mensaje=f"La fecha '{fecha_val}' no tiene un formato ISO válido.",
                campo="fecha_emision",
            )

    ref_hoy = hoy or date.today()
    if fecha_val > ref_hoy + timedelta(days=1):
        return AlertaValidacion(
            codigo="FECHA_FUTURA",
            severidad="ERROR",
            mensaje=f"La fecha de emisión ({fecha_val.isoformat()}) es futura respecto de la fecha actual.",
            campo="fecha_emision",
        )
    if fecha_val < min_date:
        return AlertaValidacion(
            codigo="FECHA_ANTERIOR_LIMITE",
            severidad="ERROR",
            mensaje=f"La fecha de emisión ({fecha_val.isoformat()}) es anterior al límite permitido ({min_date.isoformat()}).",
            campo="fecha_emision",
        )
    return AlertaValidacion(
        codigo="FECHA_OK",
        severidad="OK",
        mensaje="Fecha de emisión válida.",
        campo="fecha_emision",
    )


def validar_aritmetica_importes(
    neto: Optional[Decimal],
    iva_items: Sequence[ItemIVA],
    otros_items: Sequence[ItemImpuesto],
    total: Optional[Decimal],
    tolerancia: Decimal = Decimal(ARITHMETIC_TOLERANCE),
) -> List[AlertaValidacion]:
    """Verifica cierre aritmético neto + sum(iva) + sum(otros) == total y coherencia alícuota/importe."""
    alertas: List[AlertaValidacion] = []

    if total is None:
        alertas.append(
            AlertaValidacion(
                codigo="TOTAL_VACIO",
                severidad="ADVERTENCIA",
                mensaje="No se detectó el importe total del comprobante.",
                campo="importe_total",
            )
        )
        return alertas

    suma_iva = sum((item.importe for item in iva_items), Decimal("0.00"))
    suma_otros = sum((item.importe for item in otros_items), Decimal("0.00"))

    # Validar coherencia de cada alícuota respecto del neto gravado cuando existe un único ítem de IVA
    # o cuando la suma de alícuotas permite verificar contra el neto
    if neto is not None and len(iva_items) == 1:
        item = iva_items[0]
        esperado = (neto * item.alicuota / Decimal("100")).quantize(Decimal("0.01"))
        if abs(item.importe - esperado) > tolerancia:
            alertas.append(
                AlertaValidacion(
                    codigo="IVA_ALICUOTA_INCOHERENTE",
                    severidad="ADVERTENCIA",
                    mensaje=(
                        f"El importe de IVA ({item.importe}) al {item.alicuota}% no coincide con el cálculo "
                        f"sobre el neto gravado ({neto} * {item.alicuota}% = {esperado})."
                    ),
                    campo="iva",
                )
            )

    if neto is not None and (len(iva_items) > 0 or len(otros_items) > 0):
        suma_calculada = (neto + suma_iva + suma_otros).quantize(Decimal("0.01"))
        diferencia = abs(suma_calculada - total)
        if diferencia > tolerancia:
            alertas.append(
                AlertaValidacion(
                    codigo="ARITMETICA_NO_CIERRA",
                    severidad="ERROR",
                    mensaje=(
                        f"La suma de neto ({neto}) + IVA ({suma_iva}) + otros impuestos ({suma_otros}) "
                        f"es {suma_calculada}, que difiere del total ({total}) en {diferencia}."
                    ),
                    campo="importe_total",
                )
            )
        else:
            alertas.append(
                AlertaValidacion(
                    codigo="ARITMETICA_OK",
                    severidad="OK",
                    mensaje="El cierre aritmético de importes es consistente.",
                    campo="importe_total",
                )
            )

    return alertas


def validar_letra_e_iva(letra: Optional[str], iva_items: Sequence[ItemIVA]) -> AlertaValidacion:
    """En facturas B o C no debería discriminarse IVA; si aparece, emite alerta informativa (ADVERTENCIA)."""
    if letra in ("B", "C") and len(iva_items) > 0:
        return AlertaValidacion(
            codigo="IVA_DISCRIMINADO_EN_B_O_C",
            severidad="ADVERTENCIA",
            mensaje=(
                f"Se detectó IVA discriminado en un comprobante clase '{letra}'. "
                "Verificá si corresponde a régimen de transparencia fiscal o si fue una lectura errónea."
            ),
            campo="iva",
        )
    return AlertaValidacion(
        codigo="LETRA_IVA_OK",
        severidad="OK",
        mensaje="Relación entre clase de comprobante e IVA válida.",
        campo="letra",
    )


def validar_longitudes(
    punto_venta: Optional[str],
    numero_comprobante: Optional[str],
    cae: Optional[str],
) -> List[AlertaValidacion]:
    """Valida longitudes y caracteres numéricos de punto de venta (<=5), número (<=8) y CAE (14)."""
    alertas: List[AlertaValidacion] = []

    if punto_venta is not None and str(punto_venta).strip() != "":
        pv = str(punto_venta).strip()
        if not pv.isdigit() or not (1 <= len(pv) <= 5):
            alertas.append(
                AlertaValidacion(
                    codigo="PUNTO_VENTA_INVALIDO",
                    severidad="ERROR",
                    mensaje="El punto de venta debe ser numérico y tener hasta 5 dígitos.",
                    campo="punto_venta",
                )
            )

    if numero_comprobante is not None and str(numero_comprobante).strip() != "":
        nro = str(numero_comprobante).strip()
        if not nro.isdigit() or not (1 <= len(nro) <= 8):
            alertas.append(
                AlertaValidacion(
                    codigo="NUMERO_COMPROBANTE_INVALIDO",
                    severidad="ERROR",
                    mensaje="El número de comprobante debe ser numérico y tener hasta 8 dígitos.",
                    campo="numero_comprobante",
                )
            )

    if cae is not None and str(cae).strip() != "":
        cae_s = str(cae).strip()
        if not cae_s.isdigit() or len(cae_s) != 14:
            alertas.append(
                AlertaValidacion(
                    codigo="CAE_LONGITUD_INVALIDA",
                    severidad="ERROR",
                    mensaje="El CAE debe contener exactamente 14 dígitos numéricos.",
                    campo="cae",
                )
            )

    return alertas


def validar_duplicado(
    comprobante: Comprobante,
    hash_imagen: str,
    historial_existente: Sequence[Dict[str, Any]],
    id_actual: Optional[str] = None,
) -> Optional[AlertaValidacion]:
    """Verifica si ya existe un registro con igual hash_imagen o misma clave fiscal (CUIT+tipo+letra+PV+número)."""
    cuit = comprobante.proveedor_cuit.valor
    tipo = (comprobante.tipo_comprobante.valor or "").strip().lower()
    letra = (comprobante.letra.valor or "").strip().upper()
    pv = (comprobante.punto_venta.valor or "").strip().zfill(5) if comprobante.punto_venta.valor else ""
    nro = (
        (comprobante.numero_comprobante.valor or "").strip().zfill(8)
        if comprobante.numero_comprobante.valor
        else ""
    )

    for reg in historial_existente:
        if id_actual and reg.get("id") == id_actual:
            continue
        if hash_imagen and reg.get("hash_imagen") == hash_imagen:
            return AlertaValidacion(
                codigo="DUPLICADO_HASH_IMAGEN",
                severidad="ADVERTENCIA",
                mensaje="Esta misma imagen ya fue cargada anteriormente en el historial.",
                campo=None,
            )

        reg_cuit = (reg.get("proveedor_cuit") or "").strip()
        reg_tipo = (reg.get("tipo_comprobante") or "").strip().lower()
        reg_letra = (reg.get("letra") or "").strip().upper()
        reg_pv = str(reg.get("punto_venta") or "").strip().zfill(5) if reg.get("punto_venta") else ""
        reg_nro = (
            str(reg.get("numero_comprobante") or "").strip().zfill(8)
            if reg.get("numero_comprobante")
            else ""
        )

        if cuit and pv and nro and cuit == reg_cuit and pv == reg_pv and nro == reg_nro:
            if (not tipo or not reg_tipo or tipo == reg_tipo) and (
                not letra or not reg_letra or letra == reg_letra
            ):
                return AlertaValidacion(
                    codigo="DUPLICADO_CLAVE_FISCAL",
                    severidad="ADVERTENCIA",
                    mensaje=(
                        f"Ya existe en el historial un comprobante con el mismo CUIT ({cuit}), "
                        f"punto de venta ({pv}) y número ({nro})."
                    ),
                    campo="numero_comprobante",
                )
    return None


def ejecutar_validaciones(
    resultado: Resultado,
    historial_existente: Optional[Sequence[Dict[str, Any]]] = None,
    umbral_confianza_p2: float = CONFIDENCE_THRESHOLD_P2,
    hoy: Optional[date] = None,
    min_date: date = MIN_VALID_DATE,
) -> Resultado:
    """Ejecuta todos los validadores sobre un Resultado, actualiza flags 'revisar' y pobla alertas."""
    comp = resultado.comprobante.normalize_types()
    detalles: List[AlertaValidacion] = []

    # Preservar alertas previas generadas durante OCR/extracción/fusión (ej. CUIT ambiguo o LLM caído)
    alertas_previas = list(resultado.alertas)

    detalles.append(validar_cuit_campo(comp.proveedor_cuit.valor))
    detalles.append(validar_fecha_campo(comp.fecha_emision.valor, hoy=hoy, min_date=min_date))
    detalles.extend(
        validar_aritmetica_importes(
            neto=comp.importe_neto_gravado.valor,
            iva_items=comp.iva.valor or [],
            otros_items=comp.otros_impuestos.valor or [],
            total=comp.importe_total.valor,
        )
    )
    detalles.append(validar_letra_e_iva(comp.letra.valor, comp.iva.valor or []))
    detalles.extend(
        validar_longitudes(
            punto_venta=comp.punto_venta.valor,
            numero_comprobante=comp.numero_comprobante.valor,
            cae=comp.cae.valor,
        )
    )

    if historial_existente:
        dup = validar_duplicado(
            comprobante=comp,
            hash_imagen=resultado.hash_imagen,
            historial_existente=historial_existente,
            id_actual=resultado.id,
        )
        if dup is not None:
            detalles.append(dup)

    # Marcar campos a revisar según umbral P2 o alertas de error/advertencia
    campos_con_alerta = {
        d.campo for d in detalles if d.severidad in ("ERROR", "ADVERTENCIA") and d.campo is not None
    }
    for nombre_campo in TODOS_LOS_CAMPOS:
        campo_obj = getattr(comp, nombre_campo)
        if nombre_campo in ("iva", "otros_impuestos"):
            tiene_valor = bool(campo_obj.valor)
        else:
            tiene_valor = campo_obj.valor is not None and str(campo_obj.valor).strip() != ""

        if nombre_campo in campos_con_alerta:
            campo_obj.revisar = True
        elif tiene_valor and campo_obj.confianza < umbral_confianza_p2 and campo_obj.fuente != "manual":
            campo_obj.revisar = True

    mensajes_nuevos = [
        f"[{d.severidad}] {d.mensaje}" for d in detalles if d.severidad in ("ADVERTENCIA", "ERROR")
    ]
    todas_alertas: List[str] = []
    for msg in alertas_previas + mensajes_nuevos:
        if msg not in todas_alertas:
            todas_alertas.append(msg)

    resultado.alertas = todas_alertas
    resultado.alertas_detalle = detalles
    return resultado
