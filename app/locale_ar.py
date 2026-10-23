"""Reglas, patrones, constantes y funciones específicas de comprobantes argentinos (SUPUESTO S1)."""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Tuple

MESES_ES: Dict[str, int] = {
    "enero": 1,
    "ene": 1,
    "febrero": 2,
    "feb": 2,
    "marzo": 3,
    "mar": 3,
    "abril": 4,
    "abr": 4,
    "mayo": 5,
    "may": 5,
    "junio": 6,
    "jun": 6,
    "julio": 7,
    "jul": 7,
    "agosto": 8,
    "ago": 8,
    "septiembre": 9,
    "setiembre": 9,
    "sep": 9,
    "set": 9,
    "octubre": 10,
    "oct": 10,
    "noviembre": 11,
    "nov": 11,
    "diciembre": 12,
    "dic": 12,
}

PESOS_CUIT: Tuple[int, ...] = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)

ALICUOTAS_IVA_VALIDAS: Tuple[Decimal, ...] = (
    Decimal("21"),
    Decimal("10.5"),
    Decimal("27"),
    Decimal("5"),
    Decimal("2.5"),
    Decimal("0"),
)

TIPOS_COMPROBANTE_MAP: Tuple[Tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bNOTA\s+DE\s+CR[EÉ]DITO\b", re.IGNORECASE), "Nota de crédito"),
    (re.compile(r"\bNOTA\s+DE\s+D[EÉ]BITO\b", re.IGNORECASE), "Nota de débito"),
    (re.compile(r"\bTIQUE\s+FACTURA\b|\bTICKET\s+FACTURA\b", re.IGNORECASE), "Ticket Factura"),
    (re.compile(r"\bFACTURA\b", re.IGNORECASE), "Factura"),
    (re.compile(r"\bTICKET\b|\bTIQUE\b", re.IGNORECASE), "Ticket"),
    (re.compile(r"\bREMITO\b", re.IGNORECASE), "Remito"),
    (re.compile(r"\bRECIBO\b", re.IGNORECASE), "Recibo"),
)

LETRAS_VALIDAS = {"A", "B", "C", "M", "X"}

PALABRAS_EXCLUIDAS_PROVEEDOR = {
    "FACTURA",
    "ORIGINAL",
    "DUPLICADO",
    "TRIPLICADO",
    "COD",
    "CODIGO",
    "TICKET",
    "TIQUE",
    "REMITO",
    "RECIBO",
    "NOTA DE CREDITO",
    "NOTA DE DEBITO",
    "CONSUMIDOR FINAL",
    "RESPONSABLE INSCRIPTO",
    "IVA RESPONSABLE INSCRIPTO",
    "RESPONSABLE MONOTRIBUTO",
    "DOCUMENTO NO VALIDO COMO FACTURA",
    "FECHA",
    "CUIT",
    "INGRESOS BRUTOS",
    "INICIO DE ACTIVIDADES",
    "PUNTO DE VENTA",
}

SUFIJOS_SOCIETARIOS_REGEX = re.compile(
    r"\b(?:s\.?\s*a\.?\s*u\.?|s\.?\s*a\.?\s*s\.?|s\.?\s*r\.?\s*l\.?|s\.?\s*a\.?|"
    r"s\.?\s*c\.?\s*a\.?|s\.?\s*h\.?|sociedad\s+anonima|sociedad\s+de\s+responsabilidad\s+limitada)\b",
    re.IGNORECASE,
)

# Expresiones regulares argentinas
REGEX_CUIT = re.compile(r"(?<!\d)(\d{2})[-.\s]?(\d{8})[-.\s]?(\d)(?!\d)")
REGEX_PV_NRO_GUION = re.compile(r"(?<!\d)(\d{4,5})\s*-\s*(\d{8})(?!\d)")
REGEX_PV_EXPLICITO = re.compile(
    r"(?:P(?:un)?to\.?\s*(?:de\s*)?V(?:en)?ta\.?|P\.?\s*V\.?)\s*[:N°ºo.]*\s*(\d{1,5})"
    r".*?(?:Comp(?:robante)?\.?\s*(?:N(?:ro|úm|[°ºo.])*)?|N(?:ro|úm|[°ºo.])+)\s*[:.]*\s*(\d{1,8})",
    re.IGNORECASE,
)
REGEX_CAE = re.compile(
    r"\bC\.?A\.?E\.?\s*(?:N[°ºo.]*)?\s*:?\s*(\d{14})\b",
    re.IGNORECASE,
)


def corregir_digitos_ocr_token(token: str) -> str:
    """Corrige errores típicos de OCR (O->0, l/I->1, S->5) solo si el token ya tiene mayoría de dígitos."""
    limpio = token.strip()
    if not limpio:
        return limpio
    # Contamos caracteres relevantes (alfanuméricos)
    alfanum = [c for c in limpio if c.isalnum()]
    if not alfanum:
        return limpio
    digitos = sum(1 for c in alfanum if c.isdigit())
    if digitos <= len(alfanum) / 2:
        return limpio
    mapa = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "S": "5", "s": "5"})
    return limpio.translate(mapa)


def normalizar_monto(texto: str) -> Optional[Decimal]:
    """Convierte un string de monto ('1.234,56', '1,234.56', '$ 1234,50', etc.) a Decimal o None."""
    if not texto or not isinstance(texto, str):
        return None

    # Limpiar símbolos de moneda y espacios
    s = texto.strip()
    s = re.sub(r"^(?:ARS|USD|U\$S|US\$|\$)\s*", "", s, flags=re.IGNORECASE).strip()
    # Si hay varios tokens, evaluar corrección OCR sobre el token numérico principal
    s = corregir_digitos_ocr_token(s)

    # Extraer la parte numérica candidata
    m = re.search(r"[-+]?\d[\d.,]*", s)
    if not m:
        return None
    candidato = m.group(0)
    # Verificar que no haya quedado pegado a letras inválidas alrededor
    resto = (s[: m.start()] + s[m.end() :]).strip()
    if any(ch.isalpha() for ch in resto):
        return None

    tiene_punto = "." in candidato
    tiene_coma = "," in candidato

    if tiene_punto and tiene_coma:
        pos_punto = candidato.rfind(".")
        pos_coma = candidato.rfind(",")
        if pos_coma > pos_punto:
            # Formato argentino: 1.234,56
            partes = candidato.split(",")
            if len(partes) != 2:
                return None
            entero = partes[0].replace(".", "")
            decimales = partes[1]
            normalizado = f"{entero}.{decimales}"
        else:
            # Formato anglosajón: 1,234.56
            partes = candidato.split(".")
            if len(partes) != 2:
                return None
            entero = partes[0].replace(",", "")
            decimales = partes[1]
            normalizado = f"{entero}.{decimales}"
    elif tiene_coma:
        partes = candidato.split(",")
        if len(partes) == 2 and len(partes[1]) in (1, 2):
            normalizado = f"{partes[0]}.{partes[1]}"
        elif all(len(p) == 3 for p in partes[1:]):
            normalizado = "".join(partes)
        else:
            return None
    elif tiene_punto:
        partes = candidato.split(".")
        if len(partes) == 2 and len(partes[1]) in (1, 2):
            normalizado = f"{partes[0]}.{partes[1]}"
        elif all(len(p) == 3 for p in partes[1:]):
            normalizado = "".join(partes)
        else:
            return None
    else:
        normalizado = candidato

    try:
        valor = Decimal(normalizado)
        if valor < Decimal("0"):
            return None
        return valor.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def validar_cuit(cuit: str) -> Tuple[bool, str]:
    """Valida formato de 11 dígitos y dígito verificador módulo 11 de un CUIT argentino."""
    if not cuit or not isinstance(cuit, str):
        return False, "El CUIT está vacío."
    limpio = re.sub(r"[-\s.]", "", cuit.strip())
    if not limpio.isdigit() or len(limpio) != 11:
        return False, "El CUIT debe contener exactamente 11 dígitos numéricos."

    suma = sum(int(limpio[i]) * PESOS_CUIT[i] for i in range(10))
    resto = suma % 11
    verificador_calculado = 11 - resto
    if verificador_calculado == 11:
        verificador_calculado = 0
    elif verificador_calculado == 10:
        return False, "Dígito verificador de CUIT inválido (resto módulo 11 igual a 10)."

    if int(limpio[10]) != verificador_calculado:
        return (
            False,
            f"Dígito verificador de CUIT inválido: se esperaba {verificador_calculado} y se encontró {limpio[10]}.",
        )
    return True, "CUIT válido."


def calcular_digito_verificador_cuit(prefijo_y_dni_10_digitos: str) -> Optional[int]:
    """Calcula el dígito verificador para una base de 10 dígitos (útil para tests y sintéticos)."""
    if len(prefijo_y_dni_10_digitos) != 10 or not prefijo_y_dni_10_digitos.isdigit():
        return None
    suma = sum(int(prefijo_y_dni_10_digitos[i]) * PESOS_CUIT[i] for i in range(10))
    verif = 11 - (suma % 11)
    if verif == 11:
        return 0
    if verif == 10:
        return None
    return verif


def parsear_fecha_espanol(texto: str) -> List[Tuple[date, str]]:
    """Extrae todas las fechas válidas (día primero) desde un texto junto con su fragmento origen."""
    encontradas: List[Tuple[date, str]] = []
    if not texto:
        return encontradas

    # 1. Patrón numérico dd/mm/aaaa, dd-mm-aaaa, dd.mm.aaaa, dd/mm/aa
    patron_num = re.compile(r"\b(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{2,4})\b")
    for m in patron_num.finditer(texto):
        dia_s, mes_s, anio_s = m.group(1), m.group(2), m.group(3)
        dia, mes, anio = int(dia_s), int(mes_s), int(anio_s)
        if len(anio_s) == 2:
            anio = 2000 + anio if anio < 70 else 1900 + anio
        try:
            f = date(anio, mes, dia)
            encontradas.append((f, m.group(0)))
        except ValueError:
            continue

    # 2. Patrón con mes en texto en español: "12 de octubre de 2026" o "12 oct 2026"
    patron_txt = re.compile(
        r"\b(\d{1,2})\s*(?:de\s+)?([a-záéíóúñ]{3,10})\.?\s*(?:de\s+|del\s+)?(\d{4})\b",
        re.IGNORECASE,
    )
    for m in patron_txt.finditer(texto):
        dia = int(m.group(1))
        mes_nombre = quitar_acentos(m.group(2).lower())
        anio = int(m.group(3))
        if mes_nombre in MESES_ES:
            mes = MESES_ES[mes_nombre]
            try:
                f = date(anio, mes, dia)
                encontradas.append((f, m.group(0)))
            except ValueError:
                continue

    return encontradas


def quitar_acentos(texto: str) -> str:
    """Elimina tildes y diacríticos conservando la letra base."""
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalizar_razon_social_para_comparacion(nombre: str) -> str:
    """Normaliza razón social (minúsculas, sin acentos, sin puntuación, sin sufijos S.A./S.R.L./S.A.S.)."""
    if not nombre:
        return ""
    s = quitar_acentos(nombre.lower())
    s = SUFIJOS_SOCIETARIOS_REGEX.sub(" ", s)
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def detectar_moneda(texto: str) -> Tuple[Optional[str], Optional[str]]:
    """Detecta moneda ISO 4217. Devuelve 'ARS' únicamente si muestra '$' y no indica otra moneda."""
    if not texto:
        return None, None

    # ¿Indica explícitamente dólares u otra moneda extranjera?
    m_usd = re.search(r"\b(?:USD|U\$S|US\$|D[OÓ]LAR(?:ES)?)\b", texto, re.IGNORECASE)
    m_eur = re.search(r"\b(?:EUR|EUROS?)\b|€", texto, re.IGNORECASE)

    if m_usd and not m_eur:
        return "USD", m_usd.group(0)
    if m_eur and not m_usd:
        return "EUR", m_eur.group(0)
    if m_usd and m_eur:
        return None, None

    m_ars_exp = re.search(r"\bARS\b|\bPESOS\b", texto, re.IGNORECASE)
    m_signo_pesos = re.search(r"(?<![A-Z0-9])\$(?![A-Z])", texto)
    if m_signo_pesos:
        return "ARS", m_signo_pesos.group(0)
    if m_ars_exp:
        return "ARS", m_ars_exp.group(0)
    return None, None
