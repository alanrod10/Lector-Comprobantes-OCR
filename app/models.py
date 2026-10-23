"""Modelos de datos tipados con Pydantic (compatible con Pydantic v2 y shim v1)."""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Generic, List, Literal, Optional, TypeVar

import pydantic
from pydantic import BaseModel, Field

PYDANTIC_V2 = int(pydantic.__version__.split(".")[0]) >= 2

FuenteType = Literal["reglas", "llm", "manual", "ninguna"]
LetraType = Literal["A", "B", "C", "M", "X"]
MetodoType = Literal["reglas", "reglas+llm"]
EstadoType = Literal["pendiente_revision", "confirmado"]
SeveridadType = Literal["OK", "ADVERTENCIA", "ERROR"]

T = TypeVar("T")


class CompatBaseModel(BaseModel):
    """Clase base que garantiza API de Pydantic v2 incluso si se ejecuta en entorno con Pydantic 1.x."""

    if not PYDANTIC_V2:
        class Config:
            json_encoders = {
                Decimal: lambda v: str(v),
                date: lambda v: v.isoformat(),
                datetime: lambda v: v.isoformat(),
            }

        def model_dump(self, mode: str = "python", **kwargs: Any) -> Dict[str, Any]:
            if mode == "json":
                return json.loads(self.json(**kwargs))
            return self.dict(**kwargs)

        def model_dump_json(self, **kwargs: Any) -> str:
            return self.json(**kwargs)

        @classmethod
        def model_validate(cls, obj: Any) -> "CompatBaseModel":
            return cls.parse_obj(obj)

        @classmethod
        def model_validate_json(cls, raw_json: str) -> "CompatBaseModel":
            return cls.parse_raw(raw_json)

        @classmethod
        def model_json_schema(cls) -> Dict[str, Any]:
            return cls.schema()


class ItemIVA(CompatBaseModel):
    """Detalle de alícuota e importe de IVA discriminado."""

    alicuota: Decimal = Field(..., description="Alícuota de IVA en porcentaje (ej. 21, 10.5, 27)")
    importe: Decimal = Field(..., description="Importe en moneda correspondiente a la alícuota")


class ItemImpuesto(CompatBaseModel):
    """Detalle de otros impuestos, percepciones o tasas."""

    descripcion: str = Field(..., description="Descripción del impuesto o percepción")
    importe: Decimal = Field(..., description="Importe del impuesto")


class Campo(CompatBaseModel):
    """Contenedor genérico de un campo extraído con su trazabilidad y confianza."""

    valor: Any = Field(default=None, description="Valor tipado del campo o null si no es visible")
    confianza: float = Field(default=0.0, ge=0.0, le=1.0, description="Confianza entre 0.0 y 1.0")
    fuente: FuenteType = Field(default="ninguna", description="Origen del valor: reglas, llm, manual o ninguna")
    texto_origen: Optional[str] = Field(
        default=None,
        description="Fragmento exacto del texto OCR que respalda el valor, o null",
    )
    revisar: bool = Field(
        default=False,
        description="True si requiere revisión por baja confianza, conflicto o error de validación",
    )
    sugerencia_llm: Any = Field(
        default=None,
        description="Valor alternativo propuesto por el LLM cuando difiere de reglas",
    )
    sugerencia_texto_origen: Optional[str] = Field(
        default=None,
        description="Fragmento de origen del valor alternativo propuesto por el LLM",
    )


def campo_vacio() -> Campo:
    """Crea un campo vacío conforme a la regla de no inventar valores no visibles."""
    return Campo(valor=None, confianza=0.0, fuente="ninguna", texto_origen=None, revisar=False)


class Comprobante(CompatBaseModel):
    """Estructura completa de campos extraídos de un comprobante argentino."""

    fecha_emision: Campo = Field(default_factory=campo_vacio)
    proveedor_razon_social: Campo = Field(default_factory=campo_vacio)
    proveedor_cuit: Campo = Field(default_factory=campo_vacio)
    tipo_comprobante: Campo = Field(default_factory=campo_vacio)
    letra: Campo = Field(default_factory=campo_vacio)
    punto_venta: Campo = Field(default_factory=campo_vacio)
    numero_comprobante: Campo = Field(default_factory=campo_vacio)
    importe_neto_gravado: Campo = Field(default_factory=campo_vacio)
    iva: Campo = Field(
        default_factory=lambda: Campo(
            valor=[], confianza=0.0, fuente="ninguna", texto_origen=None, revisar=False
        )
    )
    otros_impuestos: Campo = Field(
        default_factory=lambda: Campo(
            valor=[], confianza=0.0, fuente="ninguna", texto_origen=None, revisar=False
        )
    )
    importe_total: Campo = Field(default_factory=campo_vacio)
    moneda: Campo = Field(default_factory=campo_vacio)
    cae: Campo = Field(default_factory=campo_vacio)

    def normalize_types(self) -> "Comprobante":
        """Asegura que los valores internos tengan los tipos exactos esperados (date, Decimal, etc.)."""
        if isinstance(self.fecha_emision.valor, str) and self.fecha_emision.valor.strip():
            try:
                self.fecha_emision.valor = date.fromisoformat(self.fecha_emision.valor.strip())
            except ValueError:
                pass

        for dec_field in ("importe_neto_gravado", "importe_total"):
            c: Campo = getattr(self, dec_field)
            if c.valor is not None and not isinstance(c.valor, Decimal):
                try:
                    c.valor = Decimal(str(c.valor))
                except Exception:
                    c.valor = None

        if self.iva.valor is None:
            self.iva.valor = []
        else:
            norm_iva: List[ItemIVA] = []
            for item in self.iva.valor:
                if isinstance(item, ItemIVA):
                    norm_iva.append(item)
                elif isinstance(item, dict):
                    norm_iva.append(
                        ItemIVA(
                            alicuota=Decimal(str(item["alicuota"])),
                            importe=Decimal(str(item["importe"])),
                        )
                    )
            self.iva.valor = norm_iva

        if self.otros_impuestos.valor is None:
            self.otros_impuestos.valor = []
        else:
            norm_otros: List[ItemImpuesto] = []
            for item in self.otros_impuestos.valor:
                if isinstance(item, ItemImpuesto):
                    norm_otros.append(item)
                elif isinstance(item, dict):
                    norm_otros.append(
                        ItemImpuesto(
                            descripcion=str(item["descripcion"]),
                            importe=Decimal(str(item["importe"])),
                        )
                    )
            self.otros_impuestos.valor = norm_otros

        return self


class AlertaValidacion(CompatBaseModel):
    """Resultado individual de una validación sobre uno o varios campos."""

    codigo: str
    severidad: SeveridadType
    mensaje: str
    campo: Optional[str] = None


class Resultado(CompatBaseModel):
    """Entidad completa de procesamiento y persistencia de un comprobante."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    creado_en: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    hash_imagen: str = Field(..., description="SHA-256 del archivo de imagen original")
    texto_ocr_crudo: str = Field(default="", description="Texto reconstruido por OCR")
    ocr_confianza_media: float = Field(default=0.0, ge=0.0, le=100.0)
    variante_preprocesado: str = Field(default="A", description="Variante elegida: A, B o C")
    metodo: MetodoType = Field(default="reglas")
    alertas: List[str] = Field(default_factory=list)
    alertas_detalle: List[AlertaValidacion] = Field(default_factory=list)
    estado: EstadoType = Field(default="pendiente_revision")
    comprobante: Comprobante = Field(default_factory=Comprobante)
    tiempos_ms: Dict[str, float] = Field(default_factory=dict)


CAMPOS_SIMPLES_ORDEN = [
    "fecha_emision",
    "proveedor_razon_social",
    "proveedor_cuit",
    "tipo_comprobante",
    "letra",
    "punto_venta",
    "numero_comprobante",
    "importe_neto_gravado",
    "importe_total",
    "moneda",
    "cae",
]

TODOS_LOS_CAMPOS = CAMPOS_SIMPLES_ORDEN + ["iva", "otros_impuestos"]
