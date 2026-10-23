"""Fusión de resultados de reglas y LLM con verificación estricta de anclaje en el texto OCR."""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Any, List, Optional, Tuple

from app.config import MERGE_CONFLICT_PREFERENCE
from app.locale_ar import (
    REGEX_CUIT,
    TIPOS_COMPROBANTE_MAP,
    detectar_moneda,
    normalizar_monto,
    normalizar_razon_social_para_comparacion,
    parsear_fecha_espanol,
    validar_cuit,
)
from app.models import TODOS_LOS_CAMPOS, Campo, Comprobante, campo_vacio
from app.validators import validar_fecha_campo, validar_longitudes


def _normalizar_espacios_mayus(texto: str) -> str:
    return re.sub(r"\s+", " ", texto.strip()).upper()


def _tiene_valor(campo: Campo, nombre_campo: str) -> bool:
    if nombre_campo in ("iva", "otros_impuestos"):
        return bool(campo.valor) and len(campo.valor) > 0
    return campo.valor is not None and str(campo.valor).strip() != ""


def _valores_iguales_normalizados(nombre_campo: str, val_a: Any, val_b: Any) -> bool:
    if val_a is None or val_b is None:
        return val_a is None and val_b is None

    if nombre_campo == "fecha_emision":
        fa = val_a.isoformat() if isinstance(val_a, date) else str(val_a).strip()
        fb = val_b.isoformat() if isinstance(val_b, date) else str(val_b).strip()
        return fa == fb

    if nombre_campo == "proveedor_cuit":
        ca = re.sub(r"\D", "", str(val_a))
        cb = re.sub(r"\D", "", str(val_b))
        return ca == cb

    if nombre_campo == "punto_venta":
        pa = re.sub(r"\D", "", str(val_a)).zfill(5)
        pb = re.sub(r"\D", "", str(val_b)).zfill(5)
        return pa == pb

    if nombre_campo == "numero_comprobante":
        na = re.sub(r"\D", "", str(val_a)).zfill(8)
        nb = re.sub(r"\D", "", str(val_b)).zfill(8)
        return na == nb

    if nombre_campo in ("importe_neto_gravado", "importe_total"):
        try:
            da = Decimal(str(val_a)).quantize(Decimal("0.01"))
            db = Decimal(str(val_b)).quantize(Decimal("0.01"))
            return da == db
        except Exception:
            return False

    if nombre_campo == "proveedor_razon_social":
        return normalizar_razon_social_para_comparacion(str(val_a)) == normalizar_razon_social_para_comparacion(str(val_b))

    if nombre_campo == "iva":
        set_a = {
            (Decimal(str(i.alicuota)).quantize(Decimal("0.01")), Decimal(str(i.importe)).quantize(Decimal("0.01")))
            for i in (val_a or [])
        }
        set_b = {
            (Decimal(str(i.alicuota)).quantize(Decimal("0.01")), Decimal(str(i.importe)).quantize(Decimal("0.01")))
            for i in (val_b or [])
        }
        return set_a == set_b

    if nombre_campo == "otros_impuestos":
        set_a = {
            (_normalizar_espacios_mayus(i.descripcion), Decimal(str(i.importe)).quantize(Decimal("0.01")))
            for i in (val_a or [])
        }
        set_b = {
            (_normalizar_espacios_mayus(i.descripcion), Decimal(str(i.importe)).quantize(Decimal("0.01")))
            for i in (val_b or [])
        }
        return set_a == set_b

    return _normalizar_espacios_mayus(str(val_a)) == _normalizar_espacios_mayus(str(val_b))


def verificar_anclaje_y_validez_campo_llm(
    nombre_campo: str,
    campo_llm: Campo,
    texto_ocr: str,
) -> Tuple[bool, Optional[str]]:
    if not _tiene_valor(campo_llm, nombre_campo):
        return False, f"El campo '{nombre_campo}' del LLM está vacío."

    origen = (campo_llm.texto_origen or "").strip()
    if not origen:
        return False, f"Se descartó '{nombre_campo}' del LLM porque no informó texto_origen."

    ocr_norm = _normalizar_espacios_mayus(texto_ocr)
    origen_norm = _normalizar_espacios_mayus(origen)
    if origen_norm not in ocr_norm:
        return (
            False,
            f"Se descartó '{nombre_campo}' del LLM por falla de anclaje: el fragmento '{origen}' no existe en el texto OCR.",
        )

    val = campo_llm.valor

    if nombre_campo == "fecha_emision":
        fechas_frag = [f for f, _ in parsear_fecha_espanol(origen)]
        val_date = date.fromisoformat(val) if isinstance(val, str) else val
        if not isinstance(val_date, date) or val_date not in fechas_frag:
            return (
                False,
                f"Se descartó 'fecha_emision' del LLM porque {val} no se puede reconstruir desde '{origen}'.",
            )
        alerta_f = validar_fecha_campo(val_date)
        if alerta_f.severidad == "ERROR":
            return False, f"Se descartó 'fecha_emision' del LLM por validación: {alerta_f.mensaje}"
        return True, None

    if nombre_campo == "proveedor_cuit":
        cuit_limpio = re.sub(r"\D", "", str(val))
        cuits_en_frag = [f"{m.group(1)}{m.group(2)}{m.group(3)}" for m in REGEX_CUIT.finditer(origen)]
        if cuit_limpio not in cuits_en_frag:
            return (
                False,
                f"Se descartó 'proveedor_cuit' del LLM porque {cuit_limpio} no aparece en '{origen}'.",
            )
        es_valido, msg = validar_cuit(cuit_limpio)
        if not es_valido:
            return False, f"Se descartó 'proveedor_cuit' del LLM: {msg}"
        return True, None

    if nombre_campo in ("importe_neto_gravado", "importe_total"):
        try:
            val_dec = Decimal(str(val)).quantize(Decimal("0.01"))
        except Exception:
            return False, f"Se descartó '{nombre_campo}' del LLM por formato numérico inválido."
        tokens = re.findall(r"[-+]?\d[\d.,]*", origen)
        montos_frag = [normalizar_monto(t) for t in tokens]
        if val_dec not in [m for m in montos_frag if m is not None]:
            return (
                False,
                f"Se descartó '{nombre_campo}' del LLM porque el monto {val_dec} no se reconstruye desde '{origen}'.",
            )
        return True, None

    if nombre_campo == "cae":
        cae_str = re.sub(r"\D", "", str(val))
        if cae_str not in origen or len(cae_str) != 14:
            return False, f"Se descartó 'cae' del LLM porque {val} no es un CAE válido en '{origen}'."
        alertas_l = validar_longitudes(None, None, cae_str)
        if alertas_l:
            return False, alertas_l[0].mensaje
        return True, None

    if nombre_campo == "punto_venta":
        pv_str = re.sub(r"\D", "", str(val))
        if not pv_str or pv_str.lstrip("0") not in re.sub(r"\D", " ", origen):
            return False, f"Se descartó 'punto_venta' del LLM porque no se reconstruye desde '{origen}'."
        alertas_l = validar_longitudes(pv_str, None, None)
        if alertas_l:
            return False, alertas_l[0].mensaje
        return True, None

    if nombre_campo == "numero_comprobante":
        nro_str = re.sub(r"\D", "", str(val))
        if not nro_str or nro_str.lstrip("0") not in re.sub(r"\D", " ", origen):
            return (
                False,
                f"Se descartó 'numero_comprobante' del LLM porque no se reconstruye desde '{origen}'.",
            )
        alertas_l = validar_longitudes(None, nro_str, None)
        if alertas_l:
            return False, alertas_l[0].mensaje
        return True, None

    if nombre_campo == "letra":
        letra_s = str(val).strip().upper()
        if letra_s not in ("A", "B", "C", "M", "X") or not re.search(rf"\b{letra_s}\b", origen_norm):
            return False, f"Se descartó 'letra' del LLM porque '{letra_s}' no consta en '{origen}'."
        return True, None

    if nombre_campo == "tipo_comprobante":
        encontrado = False
        for rx, nombre_canon in TIPOS_COMPROBANTE_MAP:
            if rx.search(origen) and _normalizar_espacios_mayus(nombre_canon) == _normalizar_espacios_mayus(str(val)):
                encontrado = True
                break
        if not encontrado and _normalizar_espacios_mayus(str(val)) not in origen_norm:
            return (
                False,
                f"Se descartó 'tipo_comprobante' del LLM porque '{val}' no se reconstruye desde '{origen}'.",
            )
        return True, None

    if nombre_campo == "moneda":
        mon_det, _ = detectar_moneda(origen)
        if mon_det != str(val).strip().upper():
            return False, f"Se descartó 'moneda' del LLM porque '{val}' no se respalda en '{origen}'."
        return True, None

    if nombre_campo == "proveedor_razon_social":
        val_norm = _normalizar_espacios_mayus(str(val))
        if len(val_norm) < 2 or val_norm not in origen_norm:
            return (
                False,
                f"Se descartó 'proveedor_razon_social' del LLM porque '{val}' no aparece en '{origen}'.",
            )
        return True, None

    if nombre_campo == "iva":
        tokens = re.findall(r"[-+]?\d[\d.,]*", origen)
        montos_frag = [normalizar_monto(t) for t in tokens if normalizar_monto(t) is not None]
        for item in val or []:
            imp = Decimal(str(item.importe)).quantize(Decimal("0.01"))
            if imp not in montos_frag:
                return False, f"Se descartó 'iva' del LLM porque el importe {imp} no figura en '{origen}'."
        return True, None

    if nombre_campo == "otros_impuestos":
        tokens = re.findall(r"[-+]?\d[\d.,]*", origen)
        montos_frag = [normalizar_monto(t) for t in tokens if normalizar_monto(t) is not None]
        for item in val or []:
            imp = Decimal(str(item.importe)).quantize(Decimal("0.01"))
            if imp not in montos_frag:
                return (
                    False,
                    f"Se descartó 'otros_impuestos' del LLM porque el importe {imp} no figura en '{origen}'.",
                )
        return True, None

    return True, None


def fusionar_reglas_y_llm(
    comp_reglas: Comprobante,
    comp_llm: Optional[Comprobante],
    texto_ocr: str,
    preferencia_conflicto: str = MERGE_CONFLICT_PREFERENCE,
) -> Tuple[Comprobante, List[str]]:
    if comp_llm is None:
        return comp_reglas.normalize_types(), []

    comp_reglas = comp_reglas.normalize_types()
    comp_llm = comp_llm.normalize_types()

    alertas_fusion: List[str] = []
    campos_fusionados = {}

    for nombre_campo in TODOS_LOS_CAMPOS:
        c_reg: Campo = getattr(comp_reglas, nombre_campo)
        c_llm: Campo = getattr(comp_llm, nombre_campo)

        tiene_reg = _tiene_valor(c_reg, nombre_campo)
        tiene_llm = _tiene_valor(c_llm, nombre_campo)

        if tiene_reg and not tiene_llm:
            campos_fusionados[nombre_campo] = Campo(**c_reg.model_dump())
            continue

        if not tiene_reg and not tiene_llm:
            campos_fusionados[nombre_campo] = (
                campo_vacio()
                if nombre_campo not in ("iva", "otros_impuestos")
                else Campo(valor=[], confianza=0.0, fuente="ninguna")
            )
            continue

        if not tiene_reg and tiene_llm:
            ok_anclaje, msg_alerta = verificar_anclaje_y_validez_campo_llm(
                nombre_campo, c_llm, texto_ocr
            )
            if ok_anclaje:
                campos_fusionados[nombre_campo] = Campo(
                    valor=c_llm.valor,
                    confianza=c_llm.confianza,
                    fuente="llm",
                    texto_origen=c_llm.texto_origen,
                    revisar=c_llm.revisar,
                )
            else:
                if msg_alerta:
                    alertas_fusion.append(f"[ADVERTENCIA] {msg_alerta}")
                campos_fusionados[nombre_campo] = (
                    campo_vacio()
                    if nombre_campo not in ("iva", "otros_impuestos")
                    else Campo(valor=[], confianza=0.0, fuente="ninguna")
                )
            continue

        if _valores_iguales_normalizados(nombre_campo, c_reg.valor, c_llm.valor):
            campos_fusionados[nombre_campo] = Campo(
                valor=c_reg.valor,
                confianza=max(c_reg.confianza, c_llm.confianza),
                fuente=c_reg.fuente,
                texto_origen=c_reg.texto_origen,
                revisar=c_reg.revisar,
            )
        else:
            ok_anclaje, msg_alerta = verificar_anclaje_y_validez_campo_llm(
                nombre_campo, c_llm, texto_ocr
            )
            if not ok_anclaje:
                if msg_alerta:
                    alertas_fusion.append(f"[ADVERTENCIA] {msg_alerta}")
                campos_fusionados[nombre_campo] = Campo(
                    valor=c_reg.valor,
                    confianza=c_reg.confianza,
                    fuente=c_reg.fuente,
                    texto_origen=c_reg.texto_origen,
                    revisar=c_reg.revisar,
                )
            else:
                alertas_fusion.append(
                    f"[ADVERTENCIA] Discrepancia entre reglas y LLM en '{nombre_campo}': se marcó para revisar."
                )
                if preferencia_conflicto == "llm":
                    campos_fusionados[nombre_campo] = Campo(
                        valor=c_llm.valor,
                        confianza=c_llm.confianza,
                        fuente="llm",
                        texto_origen=c_llm.texto_origen,
                        revisar=True,
                        sugerencia_llm=c_reg.valor,
                        sugerencia_texto_origen=c_reg.texto_origen,
                    )
                else:
                    campos_fusionados[nombre_campo] = Campo(
                        valor=c_reg.valor,
                        confianza=c_reg.confianza,
                        fuente=c_reg.fuente,
                        texto_origen=c_reg.texto_origen,
                        revisar=True,
                        sugerencia_llm=c_llm.valor,
                        sugerencia_texto_origen=c_llm.texto_origen,
                    )

    return Comprobante(**campos_fusionados).normalize_types(), alertas_fusion
