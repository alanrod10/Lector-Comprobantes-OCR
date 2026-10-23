"""Extracción determinista por reglas y expresiones regulares sobre texto y metadatos OCR."""
from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal
from typing import List, Optional, Sequence, Tuple

from app.config import MIN_VALID_DATE
from app.locale_ar import (
    ALICUOTAS_IVA_VALIDAS,
    LETRAS_VALIDAS,
    PALABRAS_EXCLUIDAS_PROVEEDOR,
    REGEX_CAE,
    REGEX_CUIT,
    REGEX_PV_EXPLICITO,
    REGEX_PV_NRO_GUION,
    TIPOS_COMPROBANTE_MAP,
    corregir_digitos_ocr_token,
    detectar_moneda,
    normalizar_monto,
    parsear_fecha_espanol,
    quitar_acentos,
    validar_cuit,
)
from app.models import Campo, Comprobante, ItemImpuesto, ItemIVA, campo_vacio
from app.ocr import OCRLine, OCRWord


def _calcular_confianza_fragmento(
    fragmento: str,
    palabras_ocr: Optional[Sequence[OCRWord]] = None,
    confianza_base_ocr: float = 85.0,
    ambiguo: bool = False,
) -> float:
    """
    Calcula la confianza de un campo extraído como:
    (confianza OCR media de las palabras involucradas / 100) * (0.9 si hay ambigüedad, sino 1.0).
    """
    if palabras_ocr:
        tokens_frag = [
            re.sub(r"[^\w]", "", t.lower())
            for t in fragmento.split()
            if re.sub(r"[^\w]", "", t.lower())
        ]
        confs: List[float] = []
        if tokens_frag:
            for w in palabras_ocr:
                w_clean = re.sub(r"[^\w]", "", w.text.lower())
                if w_clean and any(
                    t in w_clean or w_clean in t for t in tokens_frag
                ):
                    if w.conf > 0:
                        confs.append(w.conf)
        if not confs:
            confs = [w.conf for w in palabras_ocr if w.conf > 0]
        media = sum(confs) / len(confs) if confs else confianza_base_ocr
    else:
        media = confianza_base_ocr

    conf = max(0.0, min(1.0, (media / 100.0) * (0.9 if ambiguo else 1.0)))
    return round(conf, 4)


def _extraer_fecha(
    lineas_texto: Sequence[str],
    palabras_ocr: Optional[Sequence[OCRWord]],
    confianza_base: float,
    hoy: Optional[date] = None,
) -> Campo:
    ref_hoy = hoy or date.today()
    max_fecha = ref_hoy + timedelta(days=1)

    candidatas_prioritarias: List[Tuple[date, str]] = []
    candidatas_generales: List[Tuple[date, str]] = []

    patron_etiqueta_fecha = re.compile(
        r"\b(?:fecha\s+de\s+emisi[oó]n|fecha\s+emisi[oó]n|fecha)\b",
        re.IGNORECASE,
    )
    patron_vencimiento = re.compile(
        r"\b(?:vto|vencimiento|venc|inicio\s+de\s+actividades|inic\.?\s*act)\b",
        re.IGNORECASE,
    )

    for idx, linea in enumerate(lineas_texto):
        fechas_en_linea = parsear_fecha_espanol(linea)
        if not fechas_en_linea:
            continue
        es_prioritaria = bool(patron_etiqueta_fecha.search(linea))
        if not es_prioritaria and idx > 0 and patron_etiqueta_fecha.search(lineas_texto[idx - 1]):
            es_prioritaria = True
        es_venc_o_inicio = bool(patron_vencimiento.search(linea))

        for f_val, _ in fechas_en_linea:
            if not (MIN_VALID_DATE <= f_val <= max_fecha):
                continue
            origen = linea.strip()
            if es_prioritaria and not es_venc_o_inicio:
                candidatas_prioritarias.append((f_val, origen))
            elif not es_venc_o_inicio:
                candidatas_generales.append((f_val, origen))

    if candidatas_prioritarias:
        elegida, origen = candidatas_prioritarias[0]
        ambiguo = len({f for f, _ in candidatas_prioritarias}) > 1
        return Campo(
            valor=elegida,
            confianza=_calcular_confianza_fragmento(origen, palabras_ocr, confianza_base, ambiguo=ambiguo),
            fuente="reglas",
            texto_origen=origen,
            revisar=ambiguo,
        )

    if candidatas_generales:
        elegida, origen = candidatas_generales[0]
        ambiguo = len({f for f, _ in candidatas_generales}) > 1
        return Campo(
            valor=elegida,
            confianza=_calcular_confianza_fragmento(origen, palabras_ocr, confianza_base, ambiguo=ambiguo),
            fuente="reglas",
            texto_origen=origen,
            revisar=ambiguo,
        )

    return campo_vacio()


def _extraer_cuit(
    lineas_texto: Sequence[str],
    palabras_ocr: Optional[Sequence[OCRWord]],
    confianza_base: float,
) -> Tuple[Campo, Optional[str]]:
    """Extrae el CUIT del proveedor (emisor) y devuelve además alerta si hay ambigüedad emisor/receptor."""
    idx_corte_emisor = len(lineas_texto)
    for idx, linea in enumerate(lineas_texto):
        if re.search(
            r"\b(?:ingresos\s+brutos|i\.?\s*i\.?\s*b\.?\s*b\.?|inicio\s+de\s+actividades)\b",
            linea,
            re.IGNORECASE,
        ):
            idx_corte_emisor = min(idx_corte_emisor, idx + 2)
        if idx > 2 and re.search(
            r"\b(?:cliente|receptor|se[ñn]or(?:es)?|destinatario|a\s+consumidor\s+final)\b",
            linea,
            re.IGNORECASE,
        ):
            idx_corte_emisor = min(idx_corte_emisor, idx)

    cuits_encabezado: List[Tuple[str, str, bool]] = []
    cuits_resto: List[Tuple[str, str, bool]] = []

    for idx, linea in enumerate(lineas_texto):
        es_linea_cliente = bool(
            re.search(r"\b(?:cliente|receptor|se[ñn]or(?:es)?|comprador)\b", linea, re.IGNORECASE)
        )
        tiene_etiqueta_cuit = bool(re.search(r"\bC\.?U\.?I\.?T\.?\b", linea, re.IGNORECASE))
        # Evitar confundir el número de Ingresos Brutos de 11 dígitos con el CUIT si la línea solo dice Ingresos Brutos
        es_solo_iibb = bool(
            re.search(r"\b(?:ingresos\s+brutos|i\.?\s*i\.?\s*b\.?\s*b\.?)\b", linea, re.IGNORECASE)
            and not tiene_etiqueta_cuit
        )
        if es_solo_iibb:
            continue

        for m in REGEX_CUIT.finditer(linea):
            cuit_str = f"{m.group(1)}{m.group(2)}{m.group(3)}"
            es_valido, _ = validar_cuit(cuit_str)
            item = (cuit_str, linea.strip(), es_valido)
            if idx <= idx_corte_emisor and not es_linea_cliente and (tiene_etiqueta_cuit or idx <= 8):
                cuits_encabezado.append(item)
            else:
                cuits_resto.append(item)

    todos = cuits_encabezado + cuits_resto
    if not todos:
        return campo_vacio(), None

    validos_enc = [c for c in cuits_encabezado if c[2]]
    validos_todos_list = [c for c in todos if c[2]]

    alerta_ambiguedad: Optional[str] = None
    ambiguo = False

    if len({c[0] for c in validos_enc}) > 1:
        ambiguo = True
        alerta_ambiguedad = "CUIT ambiguo entre emisor y receptor"
        elegido = validos_enc[0]
    elif len(validos_enc) == 1:
        elegido = validos_enc[0]
    elif len({c[0] for c in validos_todos_list}) > 1:
        ambiguo = True
        alerta_ambiguedad = "CUIT ambiguo entre emisor y receptor"
        elegido = validos_todos_list[0]
    elif len(validos_todos_list) == 1:
        elegido = validos_todos_list[0]
    else:
        elegido = todos[0]
        ambiguo = True

    conf = _calcular_confianza_fragmento(
        elegido[1], palabras_ocr, confianza_base, ambiguo=ambiguo
    )
    if ambiguo:
        conf = min(conf, 0.65)

    return (
        Campo(
            valor=elegido[0],
            confianza=conf,
            fuente="reglas",
            texto_origen=elegido[1],
            revisar=ambiguo or not elegido[2],
        ),
        alerta_ambiguedad,
    )


def _extraer_tipo_y_letra(
    lineas_texto: Sequence[str],
    palabras_ocr: Optional[Sequence[OCRWord]],
    confianza_base: float,
) -> Tuple[Campo, Campo]:
    campo_tipo = campo_vacio()
    campo_letra = campo_vacio()

    zona_encabezado = lineas_texto[:15]
    for linea in list(zona_encabezado) + list(lineas_texto[15:]):
        for regex, nombre_norm in TIPOS_COMPROBANTE_MAP:
            if regex.search(linea):
                campo_tipo = Campo(
                    valor=nombre_norm,
                    confianza=_calcular_confianza_fragmento(linea, palabras_ocr, confianza_base),
                    fuente="reglas",
                    texto_origen=linea.strip(),
                )
                break
        if campo_tipo.valor is not None:
            break

    patron_tipo_letra = re.compile(
        r"\b(?:FACTURA|TIQUE\s+FACTURA|TICKET\s+FACTURA|NOTA\s+DE\s+CR[EÉ]DITO|NOTA\s+DE\s+D[EÉ]BITO|REMITO|CLASE|TIPO)\s+"
        r"(?:CLASE\s+|TIPO\s+)?([ABCMX])\b(?!\s*\.)",
        re.IGNORECASE,
    )
    patron_cod_letra = re.compile(
        r"(?:\b([ABCMX])\s+C[OÓ]D\.?\s*\d{1,3}\b|\bC[OÓ]D\.?\s*\d{1,3}\s+([ABCMX])\b)",
        re.IGNORECASE,
    )

    for idx, linea in enumerate(zona_encabezado):
        m1 = patron_tipo_letra.search(linea)
        if m1:
            letra_val = m1.group(1).upper()
            if letra_val in LETRAS_VALIDAS:
                campo_letra = Campo(
                    valor=letra_val,
                    confianza=_calcular_confianza_fragmento(linea, palabras_ocr, confianza_base),
                    fuente="reglas",
                    texto_origen=linea.strip(),
                )
                break

        m2 = patron_cod_letra.search(linea)
        if m2:
            letra_val = (m2.group(1) or m2.group(2)).upper()
            if letra_val in LETRAS_VALIDAS:
                campo_letra = Campo(
                    valor=letra_val,
                    confianza=_calcular_confianza_fragmento(linea, palabras_ocr, confianza_base),
                    fuente="reglas",
                    texto_origen=linea.strip(),
                )
                break

        limpia = linea.strip().upper()
        if limpia in LETRAS_VALIDAS and idx < 8:
            campo_letra = Campo(
                valor=limpia,
                confianza=_calcular_confianza_fragmento(linea, palabras_ocr, confianza_base, ambiguo=True),
                fuente="reglas",
                texto_origen=linea.strip(),
            )
            break

    return campo_tipo, campo_letra


def _extraer_punto_venta_y_numero(
    lineas_texto: Sequence[str],
    palabras_ocr: Optional[Sequence[OCRWord]],
    confianza_base: float,
) -> Tuple[Campo, Campo]:
    for linea in lineas_texto:
        m_exp = REGEX_PV_EXPLICITO.search(linea)
        if m_exp:
            pv = m_exp.group(1).zfill(4) if len(m_exp.group(1)) < 4 else m_exp.group(1)
            nro = m_exp.group(2).zfill(8)
            conf = _calcular_confianza_fragmento(linea, palabras_ocr, confianza_base)
            return (
                Campo(valor=pv, confianza=conf, fuente="reglas", texto_origen=linea.strip()),
                Campo(valor=nro, confianza=conf, fuente="reglas", texto_origen=linea.strip()),
            )

        m_guion = REGEX_PV_NRO_GUION.search(linea)
        if m_guion:
            pv = m_guion.group(1)
            nro = m_guion.group(2)
            conf = _calcular_confianza_fragmento(linea, palabras_ocr, confianza_base)
            return (
                Campo(valor=pv, confianza=conf, fuente="reglas", texto_origen=linea.strip()),
                Campo(valor=nro, confianza=conf, fuente="reglas", texto_origen=linea.strip()),
            )

    pv_campo = campo_vacio()
    nro_campo = campo_vacio()
    patron_pv_solo = re.compile(
        r"\b(?:P(?:un)?to\.?\s*(?:de\s*)?V(?:en)?ta\.?|P\.?\s*V\.?)\s*[:N°ºo.]*\s*(\d{1,5})\b",
        re.IGNORECASE,
    )
    patron_nro_solo = re.compile(
        r"\b(?:Comp(?:robante)?\.?\s*(?:N(?:ro|úm|[°ºo.])*)?|N(?:ro|úm|[°ºo.])+\s*(?:de\s*Comp(?:robante)?)?)\s*[:.]*\s*(\d{5,8})\b",
        re.IGNORECASE,
    )
    for linea in lineas_texto:
        if pv_campo.valor is None:
            m_pv = patron_pv_solo.search(linea)
            if m_pv:
                pv_val = m_pv.group(1)
                pv_val = pv_val.zfill(4) if len(pv_val) < 4 else pv_val
                pv_campo = Campo(
                    valor=pv_val,
                    confianza=_calcular_confianza_fragmento(linea, palabras_ocr, confianza_base),
                    fuente="reglas",
                    texto_origen=linea.strip(),
                )
        if nro_campo.valor is None and not REGEX_CAE.search(linea):
            m_nro = patron_nro_solo.search(linea)
            if m_nro:
                nro_val = m_nro.group(1).zfill(8)
                nro_campo = Campo(
                    valor=nro_val,
                    confianza=_calcular_confianza_fragmento(linea, palabras_ocr, confianza_base),
                    fuente="reglas",
                    texto_origen=linea.strip(),
                )

    return pv_campo, nro_campo


def _extraer_importes_iva_neto_total(
    lineas_texto: Sequence[str],
    palabras_ocr: Optional[Sequence[OCRWord]],
    confianza_base: float,
) -> Tuple[Campo, Campo, Campo, Campo]:
    """Extrae importe_neto_gravado, iva, otros_impuestos e importe_total."""
    neto_candidatos: List[Tuple[Decimal, str]] = []
    total_candidatos: List[Tuple[Decimal, str]] = []
    iva_items: List[ItemIVA] = []
    iva_origenes: List[str] = []
    otros_items: List[ItemImpuesto] = []
    otros_origenes: List[str] = []

    patron_neto = re.compile(
        r"\b(?:importe\s+neto\s+gravado|neto\s+gravado|importe\s+neto|subtotal\s+neto|subtotal)\b",
        re.IGNORECASE,
    )
    patron_total = re.compile(
        r"\b(?:importe\s+total|total\s+a\s+pagar|total\s+general|total)\b",
        re.IGNORECASE,
    )
    patron_excluir_total = re.compile(
        r"\b(?:subtotal|sub-total|total\s+iva|total\s+impuestos|total\s+neto|total\s+unidades|total\s+bultos)\b",
        re.IGNORECASE,
    )
    patron_iva = re.compile(
        r"\bI\.?V\.?A\.?\s*(?:INSCRIPTO\s*)?\(?(\d{1,2}(?:[.,]\d{1,2})?)\s*%\)?\s*[:$]?\s*(.+)$",
        re.IGNORECASE,
    )
    patron_otros = re.compile(
        r"\b(percepci[oó]n\s+i\.?i\.?b\.?b\.?|percepci[oó]n\s+iva|imp(?:uesto)?s?\s+internos?|tasa\s+municipal|otros\s+tributos|otros\s+impuestos)\b\s*[:$]?\s*(.+)$",
        re.IGNORECASE,
    )

    def _ultimo_monto_en_texto(s: str) -> Optional[Decimal]:
        tokens = re.findall(r"[-+]?[0-9OIlS][0-9OIlS.,]*", s)
        for tok in reversed(tokens):
            val = normalizar_monto(tok)
            if val is not None:
                return val
        return None

    for linea in lineas_texto:
        m_iva = patron_iva.search(linea)
        if m_iva:
            alic_raw = m_iva.group(1).replace(",", ".")
            try:
                alic_dec = Decimal(alic_raw)
            except Exception:
                alic_dec = None
            monto_iva = _ultimo_monto_en_texto(m_iva.group(2))
            if (
                alic_dec is not None
                and alic_dec in ALICUOTAS_IVA_VALIDAS
                and monto_iva is not None
                and monto_iva > Decimal("0")
            ):
                iva_items.append(ItemIVA(alicuota=alic_dec, importe=monto_iva))
                iva_origenes.append(linea.strip())
                continue

        m_otros = patron_otros.search(linea)
        if m_otros:
            desc = m_otros.group(1).strip()
            monto_otro = _ultimo_monto_en_texto(m_otros.group(2))
            if monto_otro is not None and monto_otro > Decimal("0"):
                otros_items.append(ItemImpuesto(descripcion=desc, importe=monto_otro))
                otros_origenes.append(linea.strip())
                continue

        if patron_neto.search(linea):
            m_pos = patron_neto.search(linea)
            sub_derecha = linea[m_pos.end() :] if m_pos else linea
            monto_n = _ultimo_monto_en_texto(sub_derecha)
            if monto_n is not None:
                neto_candidatos.append((monto_n, linea.strip()))

        if patron_total.search(linea) and not patron_excluir_total.search(linea):
            m_pos = patron_total.search(linea)
            sub_derecha = linea[m_pos.end() :] if m_pos else linea
            monto_t = _ultimo_monto_en_texto(sub_derecha)
            if monto_t is not None:
                total_candidatos.append((monto_t, linea.strip()))

    campo_neto = campo_vacio()
    if neto_candidatos:
        con_gravado = [c for c in neto_candidatos if "neto" in c[1].lower()]
        elegido_n = con_gravado[-1] if con_gravado else neto_candidatos[-1]
        campo_neto = Campo(
            valor=elegido_n[0],
            confianza=_calcular_confianza_fragmento(elegido_n[1], palabras_ocr, confianza_base),
            fuente="reglas",
            texto_origen=elegido_n[1],
        )

    campo_total = campo_vacio()
    if total_candidatos:
        elegido_t = total_candidatos[-1]
        ambiguo_t = False
        if campo_neto.valor is not None and (iva_items or otros_items):
            esperado_t = (
                campo_neto.valor
                + sum((i.importe for i in iva_items), Decimal("0.00"))
                + sum((o.importe for o in otros_items), Decimal("0.00"))
            )
            if abs(elegido_t[0] - esperado_t) > Decimal("0.02"):
                ambiguo_t = True
        campo_total = Campo(
            valor=elegido_t[0],
            confianza=_calcular_confianza_fragmento(
                elegido_t[1], palabras_ocr, confianza_base, ambiguo=ambiguo_t
            ),
            fuente="reglas",
            texto_origen=elegido_t[1],
            revisar=ambiguo_t,
        )

    if (
        campo_neto.valor is not None
        and campo_total.valor is not None
        and campo_neto.valor == campo_total.valor
        and not iva_items
        and "neto" not in (campo_neto.texto_origen or "").lower()
    ):
        campo_neto = campo_vacio()

    campo_iva = Campo(
        valor=iva_items,
        confianza=(
            _calcular_confianza_fragmento(" ".join(iva_origenes), palabras_ocr, confianza_base)
            if iva_items
            else 0.0
        ),
        fuente="reglas" if iva_items else "ninguna",
        texto_origen=" | ".join(iva_origenes) if iva_origenes else None,
    )

    campo_otros = Campo(
        valor=otros_items,
        confianza=(
            _calcular_confianza_fragmento(" ".join(otros_origenes), palabras_ocr, confianza_base)
            if otros_items
            else 0.0
        ),
        fuente="reglas" if otros_items else "ninguna",
        texto_origen=" | ".join(otros_origenes) if otros_origenes else None,
    )

    return campo_neto, campo_iva, campo_otros, campo_total


def _es_linea_excluida_proveedor(linea: str) -> bool:
    limpia = quitar_acentos(linea.upper()).strip()
    limpia_alfa = re.sub(r"[^A-Z0-9\s]", " ", limpia)
    limpia_alfa = re.sub(r"\s+", " ", limpia_alfa).strip()
    if len(limpia_alfa) < 4:
        return True
    letras = sum(1 for c in limpia_alfa if c.isalpha())
    digitos = sum(1 for c in limpia_alfa if c.isdigit())
    if letras < 4 or digitos > letras:
        return True

    for excl in PALABRAS_EXCLUIDAS_PROVEEDOR:
        if limpia_alfa == excl or limpia_alfa.startswith(excl + " "):
            return True
    if any(
        k in limpia_alfa
        for k in (
            "CUIT",
            "INGRESOS BRUTOS",
            "IIBB",
            "INICIO DE ACTIVIDADES",
            "IVA RESPONSABLE",
            "CONSUMIDOR FINAL",
            "PUNTO DE VENTA",
            "COMP NRO",
            "DOMICILIO",
            "CONDICION FRENTE AL IVA",
        )
    ):
        return True
    return False


def _limpiar_prefijo_razon_social(linea: str) -> str:
    s = re.sub(r"^(?:raz[oó]n\s+social|emisor|proveedor)\s*:\s*", "", linea.strip(), flags=re.IGNORECASE)
    return s.strip()


def _extraer_proveedor(
    lineas_texto: Sequence[str],
    lineas_ocr: Optional[Sequence[OCRLine]],
    palabras_ocr: Optional[Sequence[OCRWord]],
    confianza_base: float,
) -> Campo:
    zona_enc = lineas_texto[:8]
    for linea in zona_enc:
        m_rs = re.match(r"^\s*raz[oó]n\s+social\s*:\s*(.+)$", linea, flags=re.IGNORECASE)
        if m_rs and len(m_rs.group(1).strip()) >= 3:
            val = m_rs.group(1).strip()
            return Campo(
                valor=val,
                confianza=_calcular_confianza_fragmento(linea, palabras_ocr, confianza_base),
                fuente="reglas",
                texto_origen=linea.strip(),
            )

    if lineas_ocr:
        candidatas_geom: List[Tuple[int, int, OCRLine]] = []
        for idx, l_ocr in enumerate(lineas_ocr[:8]):
            if not _es_linea_excluida_proveedor(l_ocr.text):
                candidatas_geom.append((l_ocr.max_height, -idx, l_ocr))
        if candidatas_geom:
            primera_valida = candidatas_geom[0][2]
            mas_alta = max(candidatas_geom, key=lambda x: (x[0], x[1]))[2]
            elegida_l = (
                mas_alta
                if mas_alta.max_height >= primera_valida.max_height * 1.25
                else primera_valida
            )
            val = _limpiar_prefijo_razon_social(elegida_l.text)
            return Campo(
                valor=val,
                confianza=_calcular_confianza_fragmento(
                    elegida_l.text, palabras_ocr, confianza_base
                ),
                fuente="reglas",
                texto_origen=elegida_l.text.strip(),
            )

    for linea in zona_enc:
        if _es_linea_excluida_proveedor(linea):
            continue
        letras_mayus = sum(1 for c in linea if c.isupper())
        if letras_mayus >= 4:
            val = _limpiar_prefijo_razon_social(linea)
            return Campo(
                valor=val,
                confianza=_calcular_confianza_fragmento(linea, palabras_ocr, confianza_base),
                fuente="reglas",
                texto_origen=linea.strip(),
            )

    return campo_vacio()


def _extraer_cae(
    lineas_texto: Sequence[str],
    palabras_ocr: Optional[Sequence[OCRWord]],
    confianza_base: float,
) -> Campo:
    for linea in reversed(lineas_texto):
        m = REGEX_CAE.search(linea)
        if m:
            cae_val = m.group(1)
            return Campo(
                valor=cae_val,
                confianza=_calcular_confianza_fragmento(linea, palabras_ocr, confianza_base),
                fuente="reglas",
                texto_origen=linea.strip(),
            )
        m_lax = re.search(
            r"\bC\.?A\.?E\.?\s*(?:N[°ºo.]*)?\s*:?\s*([0-9OIlS]{14})\b",
            linea,
            re.IGNORECASE,
        )
        if m_lax:
            corregido = corregir_digitos_ocr_token(m_lax.group(1))
            if corregido.isdigit() and len(corregido) == 14:
                return Campo(
                    valor=corregido,
                    confianza=_calcular_confianza_fragmento(
                        linea, palabras_ocr, confianza_base, ambiguo=True
                    ),
                    fuente="reglas",
                    texto_origen=linea.strip(),
                )
    return campo_vacio()


def extraer_por_reglas(
    texto_ocr: str,
    palabras_ocr: Optional[Sequence[OCRWord]] = None,
    lineas_ocr: Optional[Sequence[OCRLine]] = None,
    confianza_base_ocr: float = 85.0,
    hoy: Optional[date] = None,
) -> Tuple[Comprobante, List[str]]:
    """Ejecuta la extracción basada en reglas sobre el texto OCR."""
    if not texto_ocr or not texto_ocr.strip():
        return Comprobante(), []

    lineas_texto = [l.strip() for l in texto_ocr.splitlines() if l.strip()]
    alertas: List[str] = []

    fecha_campo = _extraer_fecha(lineas_texto, palabras_ocr, confianza_base_ocr, hoy=hoy)
    cuit_campo, alerta_cuit = _extraer_cuit(lineas_texto, palabras_ocr, confianza_base_ocr)
    if alerta_cuit:
        alertas.append(alerta_cuit)

    tipo_campo, letra_campo = _extraer_tipo_y_letra(lineas_texto, palabras_ocr, confianza_base_ocr)
    pv_campo, nro_campo = _extraer_punto_venta_y_numero(
        lineas_texto, palabras_ocr, confianza_base_ocr
    )
    neto_campo, iva_campo, otros_campo, total_campo = _extraer_importes_iva_neto_total(
        lineas_texto, palabras_ocr, confianza_base_ocr
    )
    prov_campo = _extraer_proveedor(
        lineas_texto, lineas_ocr, palabras_ocr, confianza_base_ocr
    )
    cae_campo = _extraer_cae(lineas_texto, palabras_ocr, confianza_base_ocr)

    moneda_val, moneda_orig = detectar_moneda(texto_ocr)
    if moneda_val is not None:
        moneda_campo = Campo(
            valor=moneda_val,
            confianza=_calcular_confianza_fragmento(
                moneda_orig or "$", palabras_ocr, confianza_base_ocr
            ),
            fuente="reglas",
            texto_origen=moneda_orig,
        )
    else:
        moneda_campo = campo_vacio()

    comp = Comprobante(
        fecha_emision=fecha_campo,
        proveedor_razon_social=prov_campo,
        proveedor_cuit=cuit_campo,
        tipo_comprobante=tipo_campo,
        letra=letra_campo,
        punto_venta=pv_campo,
        numero_comprobante=nro_campo,
        importe_neto_gravado=neto_campo,
        iva=iva_campo,
        otros_impuestos=otros_campo,
        importe_total=total_campo,
        moneda=moneda_campo,
        cae=cae_campo,
    ).normalize_types()

    return comp, alertas
