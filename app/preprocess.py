"""Preprocesado de imágenes de comprobantes para optimizar Tesseract OCR en fotos móviles."""
from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageOps

from app.config import MAX_IMAGE_DIMENSION, MAX_IMAGE_MB


class PreprocessError(Exception):
    """Error accionable durante la carga o preprocesado de la imagen."""


@dataclass
class PreprocessOutput:
    """Resultado del preprocesado con imagen original normalizada y variantes A, B y C."""

    original_rgb: np.ndarray
    recortada_rgb: np.ndarray
    variantes: Dict[str, np.ndarray]
    perspectiva_aplicada: bool
    angulo_deskew: float


def cargar_y_normalizar_imagen(
    file_bytes: bytes,
    filename: str = "",
    max_mb: int = MAX_IMAGE_MB,
    max_dim: int = MAX_IMAGE_DIMENSION,
) -> Image.Image:
    """Valida tamaño, convierte HEIC si corresponde, corrige EXIF, pasa a RGB y limita a 2200 px."""
    if not file_bytes:
        raise PreprocessError("El archivo de imagen está vacío.")

    size_mb = len(file_bytes) / (1024 * 1024)
    if size_mb > max_mb:
        raise PreprocessError(
            f"La imagen supera el tamaño máximo permitido de {max_mb} MB ({size_mb:.1f} MB). "
            "Intentá subir una foto más liviana."
        )

    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext in ("heic", "heif"):
        try:
            import pillow_heif  # type: ignore

            pillow_heif.register_heif_opener()
        except ImportError as exc:
            raise PreprocessError(
                "El formato HEIC requiere la librería 'pillow-heif', que no está disponible en este entorno. "
                "Convertí la foto a JPEG o PNG desde tu celular antes de subirla."
            ) from exc

    try:
        img = Image.open(io.BytesIO(file_bytes))
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
    except PreprocessError:
        raise
    except Exception as exc:
        raise PreprocessError(
            "No pudimos abrir la imagen. Verificá que sea un archivo JPEG, PNG o HEIC válido."
        ) from exc

    ancho, alto = img.size
    lado_mayor = max(ancho, alto)
    if lado_mayor > max_dim:
        escala = max_dim / float(lado_mayor)
        nuevo_ancho = max(1, int(round(ancho * escala)))
        nuevo_alto = max(1, int(round(alto * escala)))
        resample = getattr(Image, "Resampling", Image).LANCZOS
        img = img.resize((nuevo_ancho, nuevo_alto), resample=resample)

    return img


def _ordenar_puntos_cuadrilatero(pts: np.ndarray) -> np.ndarray:
    """Ordena 4 puntos como: superior-izquierdo, superior-derecho, inferior-derecho, inferior-izquierdo."""
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]

    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def detectar_y_recortar_documento(img_rgb: np.ndarray) -> Tuple[np.ndarray, bool]:
    """Detecta el mayor cuadrilátero tras Canny + findContours y corrige perspectiva si ocupa >= 30% del área."""
    alto, ancho = img_rgb.shape[:2]
    area_total = float(alto * ancho)
    if area_total <= 0:
        return img_rgb, False

    gris = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2GRAY)
    suave = cv2.GaussianBlur(gris, (5, 5), 0)
    bordes = cv2.Canny(suave, 50, 150)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    bordes = cv2.dilate(bordes, kernel, iterations=1)

    contornos_info = cv2.findContours(bordes, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    contornos = contornos_info[0] if len(contornos_info) == 2 else contornos_info[1]
    contornos = sorted(contornos, key=cv2.contourArea, reverse=True)[:10]

    mejor_cuad: Optional[np.ndarray] = None
    mejor_area = 0.0

    for c in contornos:
        area = cv2.contourArea(c)
        if area < 0.30 * area_total:
            continue
        perimetro = cv2.arcLength(c, True)
        aprox = cv2.approxPolyDP(c, 0.02 * perimetro, True)
        if len(aprox) == 4 and cv2.isContourConvex(aprox):
            if area > 0.96 * area_total:
                continue
            if area > mejor_area:
                mejor_area = area
                mejor_cuad = aprox.reshape(4, 2).astype("float32")

    if mejor_cuad is None:
        return img_rgb, False

    rect = _ordenar_puntos_cuadrilatero(mejor_cuad)
    (tl, tr, br, bl) = rect

    ancho_a = np.linalg.norm(br - bl)
    ancho_b = np.linalg.norm(tr - tl)
    max_ancho = max(int(round(max(ancho_a, ancho_b))), 100)

    alto_a = np.linalg.norm(tr - br)
    alto_b = np.linalg.norm(tl - bl)
    max_alto = max(int(round(max(alto_a, alto_b))), 100)

    dst = np.array(
        [
            [0, 0],
            [max_ancho - 1, 0],
            [max_ancho - 1, max_alto - 1],
            [0, max_alto - 1],
        ],
        dtype="float32",
    )
    matriz = cv2.getPerspectiveTransform(rect, dst)
    warped = cv2.warpPerspective(img_rgb, matriz, (max_ancho, max_alto))
    return warped, True


def aplicar_deskew(img_gris: np.ndarray) -> Tuple[np.ndarray, float]:
    """Estima ángulo de inclinación con minAreaRect sobre píxeles de texto y corrige si está entre 0.5° y 15°."""
    suave = cv2.GaussianBlur(img_gris, (3, 3), 0)
    _, bin_inv = cv2.threshold(suave, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (30, 3))
    conectado = cv2.morphologyEx(bin_inv, cv2.MORPH_CLOSE, kernel)

    contornos_info = cv2.findContours(conectado, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contornos = contornos_info[0] if len(contornos_info) == 2 else contornos_info[1]

    angulos_lineas = []
    for c in contornos:
        if c.shape[0] < 5:
            continue
        (_, (w, h), ang) = cv2.minAreaRect(c)
        if max(w, h) < 50 or min(w, h) < 4:
            continue
        if w < h:
            ang = ang - 90.0
        if ang < -45.0:
            ang += 90.0
        elif ang > 45.0:
            ang -= 90.0
        if max(w, h) / max(min(w, h), 1.0) >= 2.5 and abs(ang) <= 20.0:
            angulos_lineas.append(float(ang))

    if angulos_lineas:
        angulo = float(np.median(angulos_lineas))
    else:
        coords = np.column_stack(np.where(conectado > 0))
        if coords.shape[0] < 100:
            return img_gris, 0.0
        pts_xy = np.fliplr(coords).astype(np.float32)
        (_, (w, h), angulo) = cv2.minAreaRect(pts_xy)
        if w < h:
            angulo = angulo - 90.0
        if angulo < -45.0:
            angulo += 90.0
        elif angulo > 45.0:
            angulo -= 90.0

    if not (0.5 <= abs(angulo) <= 15.0):
        return img_gris, 0.0

    alto, ancho = img_gris.shape[:2]
    centro = (ancho // 2, alto // 2)
    matriz = cv2.getRotationMatrix2D(centro, angulo, 1.0)
    rotada = cv2.warpAffine(
        img_gris,
        matriz,
        (ancho, alto),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return rotada, float(round(angulo, 2))


def generar_variantes(img_rgb: np.ndarray) -> PreprocessOutput:
    """Ejecuta recorte de perspectiva, deskew y construye las variantes A, B y C."""
    recortada_rgb, perspectiva_aplicada = detectar_y_recortar_documento(img_rgb)
    gris_base = cv2.cvtColor(recortada_rgb, cv2.COLOR_RGB2GRAY)
    gris_deskew, angulo = aplicar_deskew(gris_base)

    # Variante A: escala de grises, CLAHE, binarización adaptativa gaussiana
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gris_clahe = clahe.apply(gris_deskew)
    variante_a = cv2.adaptiveThreshold(
        gris_clahe,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        12,
    )

    # Variante B: escala de grises, desenfoque suave, umbral de Otsu
    suave_b = cv2.GaussianBlur(gris_deskew, (5, 5), 0)
    _, variante_b = cv2.threshold(suave_b, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # Variante C: escala de grises sin binarizar (para papel de buena calidad)
    variante_c = gris_deskew.copy()

    return PreprocessOutput(
        original_rgb=img_rgb,
        recortada_rgb=recortada_rgb,
        variantes={"A": variante_a, "B": variante_b, "C": variante_c},
        perspectiva_aplicada=perspectiva_aplicada,
        angulo_deskew=angulo,
    )


def preprocesar_bytes(file_bytes: bytes, filename: str = "") -> PreprocessOutput:
    """Pipeline completo de carga, normalización y generación de variantes A, B y C."""
    pil_img = cargar_y_normalizar_imagen(file_bytes, filename=filename)
    img_rgb = np.array(pil_img)
    return generar_variantes(img_rgb)
