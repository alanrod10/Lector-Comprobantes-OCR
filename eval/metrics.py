"""Normalización estricta y cálculo de métricas de evaluación por campo, por comprobante y calibración."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from app.config import CONFIDENCE_THRESHOLD_P2, PROVEEDOR_SIMILARITY_THRESHOLD_P1
from app.locale_ar import normalizar_monto, normalizar_razon_social_para_comparacion
from app.models import Campo, Comprobante, ItemImpuesto, ItemIVA

try:
    from rapidfuzz import fuzz as _rapidfuzz_fuzz  # type: ignore

    def calcular_token_sort_ratio(a: str, b: str) -> float:
        return float(_rapidfuzz_fuzz.token_sort_ratio(a, b))

except ImportError:

    def calcular_token_sort_ratio(a: str, b: str) -> float:
        """Fallback compatible con rapidfuzz.fuzz.token_sort_ratio cuando rapidfuzz no está instalado en el entorno."""
        tokens_a = " ".join(sorted(a.split()))
        tokens_b = " ".join(sorted(b.split()))
        if not tokens_a and not tokens_b:
            return 100.0
        if not tokens_a or not tokens_b:
            return 0.0
        return round(SequenceMatcher(None, tokens_a, tokens_b).ratio() * 100.0, 2)


CAMPOS_EVALUADOS: Tuple[str, ...] = (
    "fecha_emision",
    "proveedor_razon_social",
    "proveedor_cuit",
    "tipo_comprobante",
    "letra",
    "punto_venta",
    "numero_comprobante",
    "importe_neto_gravado",
    "iva",
    "otros_impuestos",
    "importe_total",
    "moneda",
    "cae",
)

CAMPOS_CRITICOS: Tuple[str, ...] = (
    "fecha_emision",
    "proveedor_cuit",
    "numero_comprobante",
    "importe_total",
)


def normalizar_valor_para_eval(nombre_campo: str, valor: Any) -> Any:
    """
    Normaliza un valor (esperado o predicho) según las reglas de la Sección 14:
    - fecha_emision: ISO YYYY-MM-DD
    - proveedor_cuit: solo dígitos (11)
    - punto_venta: solo dígitos con ceros a la izquierda a longitud 5
    - numero_comprobante: solo dígitos con ceros a la izquierda a longitud 8
    - cae: solo dígitos (14)
    - letra, moneda: mayúsculas
    - importes: Decimal exacto al centavo (0.01)
    - iva: conjunto de pares (Decimal alícuota, Decimal importe)
    - otros_impuestos: conjunto de pares (descripcion normalizada, Decimal importe)
    - proveedor_razon_social: minúsculas, sin acentos, sin puntuación, sin sufijos societarios
    """
    if valor is None:
        return None

    if nombre_campo in ("iva", "otros_impuestos"):
        if not isinstance(valor, (list, tuple, set)) or len(valor) == 0:
            return None
        if nombre_campo == "iva":
            pares: Set[Tuple[Decimal, Decimal]] = set()
            for item in valor:
                if isinstance(item, ItemIVA):
                    alic = Decimal(str(item.alicuota)).quantize(Decimal("0.01"))
                    imp = Decimal(str(item.importe)).quantize(Decimal("0.01"))
                elif isinstance(item, dict):
                    alic = Decimal(str(item["alicuota"])).quantize(Decimal("0.01"))
                    imp = Decimal(str(item["importe"])).quantize(Decimal("0.01"))
                else:
                    continue
                pares.add((alic, imp))
            return pares if pares else None
        else:
            pares_o: Set[Tuple[str, Decimal]] = set()
            for item in valor:
                if isinstance(item, ItemImpuesto):
                    desc = re.sub(r"\s+", " ", item.descripcion.strip().lower())
                    imp = Decimal(str(item.importe)).quantize(Decimal("0.01"))
                elif isinstance(item, dict):
                    desc = re.sub(r"\s+", " ", str(item.get("descripcion", "")).strip().lower())
                    imp = Decimal(str(item["importe"])).quantize(Decimal("0.01"))
                else:
                    continue
                pares_o.add((desc, imp))
            return pares_o if pares_o else None

    s = str(valor).strip()
    if s == "":
        return None

    if nombre_campo == "fecha_emision":
        if isinstance(valor, date):
            return valor.isoformat()
        return date.fromisoformat(s).isoformat()

    if nombre_campo == "proveedor_cuit":
        d = re.sub(r"\D", "", s)
        return d if d else None

    if nombre_campo == "punto_venta":
        d = re.sub(r"\D", "", s)
        return d.zfill(5) if d else None

    if nombre_campo == "numero_comprobante":
        d = re.sub(r"\D", "", s)
        return d.zfill(8) if d else None

    if nombre_campo == "cae":
        d = re.sub(r"\D", "", s)
        return d if d else None

    if nombre_campo in ("letra", "moneda"):
        return s.upper()

    if nombre_campo == "tipo_comprobante":
        s_up = s.upper()
        if "TIQUE" in s_up or "TICKET" in s_up:
            return "TICKET"
        if "NOTA" in s_up and ("CREDITO" in s_up or "CRÉDITO" in s_up):
            return "NOTA DE CREDITO"
        if "NOTA" in s_up and ("DEBITO" in s_up or "DÉBITO" in s_up):
            return "NOTA DE DEBITO"
        if "FACTURA" in s_up:
            return "FACTURA"
        if "REMITO" in s_up:
            return "REMITO"
        return s_up

    if nombre_campo in ("importe_neto_gravado", "importe_total"):
        if isinstance(valor, Decimal):
            return valor.quantize(Decimal("0.01"))
        try:
            return Decimal(s).quantize(Decimal("0.01"))
        except Exception:
            return normalizar_monto(s)

    if nombre_campo in ("proveedor_razon_social", "proveedor_razon_social_exacto"):
        norm = normalizar_razon_social_para_comparacion(s)
        return norm if norm else None

    return s


def comparar_campo(
    nombre_campo: str,
    esperado_raw: Any,
    obtenido_raw: Any,
    umbral_p1: int = PROVEEDOR_SIMILARITY_THRESHOLD_P1,
) -> Tuple[str, Any, Any]:
    """
    Compara el valor esperado contra el obtenido para un campo.
    Retorna (resultado_categoria, esperado_norm, obtenido_norm) donde resultado_categoria es:
    - 'coincidencia': ambos no nulos y equivalentes según regla del campo
    - 'verdadero_negativo': ambos nulos
    - 'falso_positivo': esperado es null y obtenido no es null
    - 'omision': esperado no es null y obtenido es null
    - 'error': ambos no nulos pero distintos
    """
    esp = normalizar_valor_para_eval(nombre_campo, esperado_raw)
    obt = normalizar_valor_para_eval(nombre_campo, obtenido_raw)

    if esp is None and obt is None:
        return "verdadero_negativo", None, None
    if esp is None and obt is not None:
        return "falso_positivo", None, obt
    if esp is not None and obt is None:
        return "omision", esp, None

    # Ambos son no nulos
    if nombre_campo == "proveedor_razon_social":
        sim = calcular_token_sort_ratio(str(esp), str(obt))
        es_igual = sim >= float(umbral_p1)
    elif nombre_campo == "proveedor_razon_social_exacto":
        es_igual = str(esp) == str(obt)
    else:
        es_igual = esp == obt

    return ("coincidencia" if es_igual else "error"), esp, obt


@dataclass
class ConteoCampo:
    """Acumulador de conteos para un campo y método."""

    referencia_no_nula: int = 0
    referencia_nula: int = 0
    coincidencias: int = 0
    falsos_positivos: int = 0
    omisiones: int = 0
    errores: int = 0
    verdaderos_negativos: int = 0

    @property
    def exactitud(self) -> float:
        if self.referencia_no_nula == 0:
            return 0.0
        return round(self.coincidencias / self.referencia_no_nula, 4)


@dataclass
class ErrorDetalle:
    """Registro de discrepancia individual para exportar a eval/errores.csv."""

    metodo: str
    imagen: str
    campo: str
    tipo_discrepancia: str
    esperado: str
    obtenido: str
    texto_origen: str


@dataclass
class ResumenMetodo:
    """Resultado agregado de evaluar un método ('reglas' o 'reglas+llm') sobre todo el dataset."""

    metodo: str
    total_comprobantes: int = 0
    comprobantes_criticos_perfectos: int = 0
    por_campo: Dict[str, ConteoCampo] = field(default_factory=dict)
    por_nota: Dict[str, Tuple[int, int]] = field(default_factory=dict)  # nota -> (campos_correctos, campos_ref_no_nula)
    calibracion_alta: Tuple[int, int] = (0, 0)  # (aciertos, total_evaluados_con_conf_>=_P2)
    calibracion_baja: Tuple[int, int] = (0, 0)  # (aciertos, total_evaluados_con_conf_<_P2)
    errores_detalle: List[ErrorDetalle] = field(default_factory=list)

    @property
    def exactitud_nivel_comprobante(self) -> float:
        if self.total_comprobantes == 0:
            return 0.0
        return round(self.comprobantes_criticos_perfectos / self.total_comprobantes, 4)


def evaluar_predicciones_metodo(
    metodo: str,
    ground_truth_items: Sequence[Dict[str, Any]],
    predicciones_por_archivo: Dict[str, Comprobante],
    umbral_p1: int = PROVEEDOR_SIMILARITY_THRESHOLD_P1,
    umbral_p2: float = CONFIDENCE_THRESHOLD_P2,
) -> ResumenMetodo:
    """Calcula todas las métricas de la Sección 14 para un método dado."""
    resumen = ResumenMetodo(metodo=metodo)
    todos_campos_reporte = list(CAMPOS_EVALUADOS) + ["proveedor_razon_social_exacto"]
    for c_name in todos_campos_reporte:
        resumen.por_campo[c_name] = ConteoCampo()

    alta_ok, alta_tot = 0, 0
    baja_ok, baja_tot = 0, 0

    for item_gt in ground_truth_items:
        archivo = item_gt["archivo"]
        campos_gt = item_gt.get("campos", {})
        notas_raw = item_gt.get("notas", [])
        if isinstance(notas_raw, str):
            notas = [n.strip() for n in notas_raw.split(",") if n.strip()]
        else:
            notas = [str(n).strip() for n in notas_raw if str(n).strip()]

        comp_pred = predicciones_por_archivo.get(archivo, Comprobante()).normalize_types()
        resumen.total_comprobantes += 1

        criticos_ok = True

        for nombre_campo in CAMPOS_EVALUADOS:
            esperado_raw = campos_gt.get(nombre_campo)
            campo_obj: Campo = getattr(comp_pred, nombre_campo)
            obtenido_raw = campo_obj.valor

            cat, esp_n, obt_n = comparar_campo(
                nombre_campo, esperado_raw, obtenido_raw, umbral_p1=umbral_p1
            )
            conteo = resumen.por_campo[nombre_campo]

            if esp_n is not None:
                conteo.referencia_no_nula += 1
            else:
                conteo.referencia_nula += 1

            if cat == "coincidencia":
                conteo.coincidencias += 1
            elif cat == "verdadero_negativo":
                conteo.verdaderos_negativos += 1
            elif cat == "falso_positivo":
                conteo.falsos_positivos += 1
                resumen.errores_detalle.append(
                    ErrorDetalle(
                        metodo=metodo,
                        imagen=archivo,
                        campo=nombre_campo,
                        tipo_discrepancia="falso_positivo",
                        esperado="null",
                        obtenido=_formatear_valor_reporte(obt_n),
                        texto_origen=campo_obj.texto_origen or "",
                    )
                )
            elif cat == "omision":
                conteo.omisiones += 1
                resumen.errores_detalle.append(
                    ErrorDetalle(
                        metodo=metodo,
                        imagen=archivo,
                        campo=nombre_campo,
                        tipo_discrepancia="omision",
                        esperado=_formatear_valor_reporte(esp_n),
                        obtenido="null",
                        texto_origen=campo_obj.texto_origen or "",
                    )
                )
            elif cat == "error":
                conteo.errores += 1
                resumen.errores_detalle.append(
                    ErrorDetalle(
                        metodo=metodo,
                        imagen=archivo,
                        campo=nombre_campo,
                        tipo_discrepancia="error",
                        esperado=_formatear_valor_reporte(esp_n),
                        obtenido=_formatear_valor_reporte(obt_n),
                        texto_origen=campo_obj.texto_origen or "",
                    )
                )

            if nombre_campo in CAMPOS_CRITICOS:
                if cat not in ("coincidencia", "verdadero_negativo"):
                    criticos_ok = False

            # Desagregación por notas sobre campos con referencia no nula
            if esp_n is not None:
                es_acierto = 1 if cat == "coincidencia" else 0
                for etiqueta_nota in notas:
                    prev_ok, prev_tot = resumen.por_nota.get(etiqueta_nota, (0, 0))
                    resumen.por_nota[etiqueta_nota] = (prev_ok + es_acierto, prev_tot + 1)

            # Calibración simple: exactitud en campos extraídos (no nulos) con confianza >= P2 vs < P2
            if obt_n is not None:
                acierto_ext = 1 if cat == "coincidencia" else 0
                if campo_obj.confianza >= umbral_p2:
                    alta_ok += acierto_ext
                    alta_tot += 1
                else:
                    baja_ok += acierto_ext
                    baja_tot += 1

            # Métrica adicional de igualdad exacta para proveedor_razon_social
            if nombre_campo == "proveedor_razon_social":
                cat_ex, esp_ex, obt_ex = comparar_campo(
                    "proveedor_razon_social_exacto",
                    esperado_raw,
                    obtenido_raw,
                    umbral_p1=100,
                )
                conteo_ex = resumen.por_campo["proveedor_razon_social_exacto"]
                if esp_ex is not None:
                    conteo_ex.referencia_no_nula += 1
                else:
                    conteo_ex.referencia_nula += 1
                if cat_ex == "coincidencia":
                    conteo_ex.coincidencias += 1
                elif cat_ex == "verdadero_negativo":
                    conteo_ex.verdaderos_negativos += 1
                elif cat_ex == "falso_positivo":
                    conteo_ex.falsos_positivos += 1
                elif cat_ex == "omision":
                    conteo_ex.omisiones += 1
                elif cat_ex == "error":
                    conteo_ex.errores += 1

        if criticos_ok:
            resumen.comprobantes_criticos_perfectos += 1

    resumen.calibracion_alta = (alta_ok, alta_tot)
    resumen.calibracion_baja = (baja_ok, baja_tot)
    return resumen


def _formatear_valor_reporte(val: Any) -> str:
    if val is None:
        return "null"
    if isinstance(val, set):
        return "; ".join(str(x) for x in sorted(val))
    return str(val)
