"""Configuración central y lectura de variables de entorno."""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("COMPROBANTES_DATA_DIR", str(BASE_DIR / "data")))
DB_PATH = Path(os.getenv("COMPROBANTES_DB_PATH", str(DATA_DIR / "comprobantes.db")))
IMAGES_DIR = DATA_DIR / "imagenes"

# PARAMETRO_PENDIENTE P1: umbral de similitud para comparar proveedor en la evaluación.
# Valor inicial configurable: 90 (rapidfuzz.fuzz.token_sort_ratio). Debe recalibrarse con el dataset real.
PROVEEDOR_SIMILARITY_THRESHOLD_P1: int = int(os.getenv("PROVEEDOR_SIMILARITY_P1", "90"))

# PARAMETRO_PENDIENTE P2: umbral de confianza por campo para marcar "revisar".
# Valor inicial configurable: 0.80. Debe recalibrarse con el dataset real.
CONFIDENCE_THRESHOLD_P2: float = float(os.getenv("CONFIDENCE_THRESHOLD_P2", "0.80"))

# PARAMETRO_PENDIENTE P3: proveedor de LLM concreto seleccionable por variable de entorno.
# Valores soportados: "gemini", "openai", "fake".
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
LLM_API_KEY: str = os.getenv("LLM_API_KEY", "").strip()
LLM_MODEL: str = os.getenv("LLM_MODEL", "gemini-2.5-flash").strip()
LLM_TIMEOUT_SECONDS: int = int(os.getenv("LLM_TIMEOUT_SECONDS", "25"))

# Límites de validación y preprocesado
MIN_VALID_DATE: date = date.fromisoformat(os.getenv("MIN_VALID_DATE", "2000-01-01"))
ARITHMETIC_TOLERANCE: str = os.getenv("ARITHMETIC_TOLERANCE", "0.02")
MAX_IMAGE_MB: int = int(os.getenv("MAX_IMAGE_MB", "15"))
MAX_IMAGE_DIMENSION: int = int(os.getenv("MAX_IMAGE_DIMENSION", "2200"))

# Política de fusión en caso de conflicto ("reglas" conserva el valor de reglas y sugiere LLM;
# "llm" conserva el valor de LLM si pasa anclaje y sugiere reglas).
MERGE_CONFLICT_PREFERENCE: str = os.getenv("MERGE_CONFLICT_PREFERENCE", "reglas").strip().lower()

# Privacidad por defecto
SAVE_ORIGINAL_IMAGE_DEFAULT: bool = os.getenv("SAVE_ORIGINAL_IMAGE", "false").strip().lower() == "true"
ENABLE_LLM_DEFAULT: bool = os.getenv("ENABLE_LLM", "false").strip().lower() == "true"
