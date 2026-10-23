"""Persistencia local en SQLite, registro de correcciones manuales, ajustes y gestión de privacidad."""
from __future__ import annotations

import json
import logging
import shutil
import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.config import (
    CONFIDENCE_THRESHOLD_P2,
    DB_PATH,
    ENABLE_LLM_DEFAULT,
    IMAGES_DIR,
    MIN_VALID_DATE,
    SAVE_ORIGINAL_IMAGE_DEFAULT,
)
from app.models import TODOS_LOS_CAMPOS, Campo, Comprobante, Resultado

logger = logging.getLogger(__name__)


def _serializar_valor_simple(nombre_campo: str, val: Any) -> str:
    """Serializa el valor de un campo a string canónico para comparar y guardar en 'correcciones'."""
    if val is None:
        return ""
    if isinstance(val, date):
        return val.isoformat()
    if isinstance(val, Decimal):
        return str(val.quantize(Decimal("0.01")))
    if nombre_campo in ("iva", "otros_impuestos"):
        if not val:
            return "[]"
        lista_serial = []
        for item in val:
            if hasattr(item, "model_dump"):
                d = item.model_dump(mode="json")
            elif isinstance(item, dict):
                d = {k: str(v) for k, v in item.items()}
            else:
                d = str(item)
            lista_serial.append(d)
        return json.dumps(lista_serial, ensure_ascii=False, sort_keys=True)
    return str(val).strip()


class StorageManager:
    """Gestor de almacenamiento SQLite para resultados, correcciones manuales y ajustes."""

    def __init__(
        self,
        db_path: Path = DB_PATH,
        images_dir: Path = IMAGES_DIR,
    ) -> None:
        self.db_path = Path(db_path)
        self.images_dir = Path(images_dir)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS resultados (
                    id TEXT PRIMARY KEY,
                    creado_en TEXT NOT NULL,
                    hash_imagen TEXT NOT NULL,
                    texto_ocr_crudo TEXT NOT NULL,
                    ocr_confianza_media REAL NOT NULL,
                    variante_preprocesado TEXT NOT NULL,
                    metodo TEXT NOT NULL,
                    alertas_json TEXT NOT NULL,
                    alertas_detalle_json TEXT NOT NULL,
                    estado TEXT NOT NULL,
                    comprobante_json TEXT NOT NULL,
                    tiempos_json TEXT NOT NULL,
                    fecha_emision TEXT,
                    proveedor_razon_social TEXT,
                    proveedor_cuit TEXT,
                    tipo_comprobante TEXT,
                    letra TEXT,
                    punto_venta TEXT,
                    numero_comprobante TEXT,
                    importe_neto_gravado TEXT,
                    importe_total TEXT,
                    moneda TEXT,
                    cae TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_resultados_hash ON resultados(hash_imagen);
                CREATE INDEX IF NOT EXISTS idx_resultados_fecha ON resultados(fecha_emision);
                CREATE INDEX IF NOT EXISTS idx_resultados_cuit ON resultados(proveedor_cuit);

                CREATE TABLE IF NOT EXISTS correcciones (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    resultado_id TEXT NOT NULL,
                    campo TEXT NOT NULL,
                    valor_extraido TEXT,
                    valor_final TEXT,
                    fuente TEXT NOT NULL,
                    creado_en TEXT NOT NULL,
                    FOREIGN KEY (resultado_id) REFERENCES resultados(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_correcciones_resultado ON correcciones(resultado_id);
                CREATE INDEX IF NOT EXISTS idx_correcciones_campo ON correcciones(campo);

                CREATE TABLE IF NOT EXISTS ajustes (
                    clave TEXT PRIMARY KEY,
                    valor TEXT NOT NULL
                );
                """
            )
            # Inicializar ajustes por defecto si no existen
            defaults = {
                "enable_llm": json.dumps(ENABLE_LLM_DEFAULT),
                "umbral_p2": json.dumps(CONFIDENCE_THRESHOLD_P2),
                "min_valid_date": json.dumps(MIN_VALID_DATE.isoformat()),
                "save_original_image": json.dumps(SAVE_ORIGINAL_IMAGE_DEFAULT),
            }
            for k, v in defaults.items():
                conn.execute(
                    "INSERT OR IGNORE INTO ajustes (clave, valor) VALUES (?, ?)",
                    (k, v),
                )
            conn.commit()

    def obtener_ajustes(self) -> Dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute("SELECT clave, valor FROM ajustes").fetchall()
        out: Dict[str, Any] = {}
        for r in rows:
            try:
                out[r["clave"]] = json.loads(r["valor"])
            except Exception:
                out[r["clave"]] = r["valor"]
        return out

    def guardar_ajuste(self, clave: str, valor: Any) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO ajustes (clave, valor) VALUES (?, ?) "
                "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
                (clave, json.dumps(valor)),
            )
            conn.commit()

    def guardar_resultado(
        self,
        resultado: Resultado,
        comprobante_original_extraido: Optional[Comprobante] = None,
        imagen_bytes: Optional[bytes] = None,
        extension_imagen: str = "jpg",
        guardar_imagen_original: Optional[bool] = None,
    ) -> None:
        """
        Persiste el Resultado en SQLite. Si se provee comprobante_original_extraido,
        calcula y registra los campos modificados manualmente en la tabla 'correcciones'.
        """
        comp = resultado.comprobante.normalize_types()

        if comprobante_original_extraido is not None:
            orig = comprobante_original_extraido.normalize_types()
            ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
            nuevas_correcciones: List[Tuple[str, str, str, str, str, str]] = []

            for nombre_campo in TODOS_LOS_CAMPOS:
                c_orig: Campo = getattr(orig, nombre_campo)
                c_fin: Campo = getattr(comp, nombre_campo)
                s_orig = _serializar_valor_simple(nombre_campo, c_orig.valor)
                s_fin = _serializar_valor_simple(nombre_campo, c_fin.valor)
                if s_orig != s_fin:
                    c_fin.fuente = "manual"
                    c_fin.confianza = 1.0
                    c_fin.revisar = False
                    nuevas_correcciones.append(
                        (
                            resultado.id,
                            nombre_campo,
                            s_orig,
                            s_fin,
                            c_orig.fuente,
                            ahora,
                        )
                    )
        else:
            nuevas_correcciones = []

        comp_json = comp.model_dump_json()
        alertas_json = json.dumps(resultado.alertas, ensure_ascii=False)
        alertas_det_json = json.dumps(
            [a.model_dump(mode="json") for a in resultado.alertas_detalle],
            ensure_ascii=False,
        )
        tiempos_json = json.dumps(resultado.tiempos_ms, ensure_ascii=False)

        fecha_str = (
            comp.fecha_emision.valor.isoformat()
            if isinstance(comp.fecha_emision.valor, date)
            else (str(comp.fecha_emision.valor) if comp.fecha_emision.valor else None)
        )
        neto_str = (
            str(comp.importe_neto_gravado.valor)
            if comp.importe_neto_gravado.valor is not None
            else None
        )
        total_str = (
            str(comp.importe_total.valor)
            if comp.importe_total.valor is not None
            else None
        )

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO resultados (
                    id, creado_en, hash_imagen, texto_ocr_crudo, ocr_confianza_media,
                    variante_preprocesado, metodo, alertas_json, alertas_detalle_json,
                    estado, comprobante_json, tiempos_json,
                    fecha_emision, proveedor_razon_social, proveedor_cuit,
                    tipo_comprobante, letra, punto_venta, numero_comprobante,
                    importe_neto_gravado, importe_total, moneda, cae
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    estado = excluded.estado,
                    alertas_json = excluded.alertas_json,
                    alertas_detalle_json = excluded.alertas_detalle_json,
                    comprobante_json = excluded.comprobante_json,
                    fecha_emision = excluded.fecha_emision,
                    proveedor_razon_social = excluded.proveedor_razon_social,
                    proveedor_cuit = excluded.proveedor_cuit,
                    tipo_comprobante = excluded.tipo_comprobante,
                    letra = excluded.letra,
                    punto_venta = excluded.punto_venta,
                    numero_comprobante = excluded.numero_comprobante,
                    importe_neto_gravado = excluded.importe_neto_gravado,
                    importe_total = excluded.importe_total,
                    moneda = excluded.moneda,
                    cae = excluded.cae
                """,
                (
                    resultado.id,
                    resultado.creado_en,
                    resultado.hash_imagen,
                    resultado.texto_ocr_crudo,
                    resultado.ocr_confianza_media,
                    resultado.variante_preprocesado,
                    resultado.metodo,
                    alertas_json,
                    alertas_det_json,
                    resultado.estado,
                    comp_json,
                    tiempos_json,
                    fecha_str,
                    comp.proveedor_razon_social.valor,
                    comp.proveedor_cuit.valor,
                    comp.tipo_comprobante.valor,
                    comp.letra.valor,
                    comp.punto_venta.valor,
                    comp.numero_comprobante.valor,
                    neto_str,
                    total_str,
                    comp.moneda.valor,
                    comp.cae.valor,
                ),
            )
            if nuevas_correcciones:
                conn.executemany(
                    """
                    INSERT INTO correcciones (
                        resultado_id, campo, valor_extraido, valor_final, fuente, creado_en
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    nuevas_correcciones,
                )
            conn.commit()

        debe_guardar_img = (
            guardar_imagen_original
            if guardar_imagen_original is not None
            else bool(self.obtener_ajustes().get("save_original_image", False))
        )
        if debe_guardar_img and imagen_bytes and resultado.hash_imagen:
            self.images_dir.mkdir(parents=True, exist_ok=True)
            ext_limpia = extension_imagen.lower().lstrip(".") or "jpg"
            ruta_img = self.images_dir / f"{resultado.hash_imagen}.{ext_limpia}"
            ruta_img.write_bytes(imagen_bytes)

        logger.info("Resultado persistido id=%s estado=%s", resultado.id, resultado.estado)

    def _row_to_resultado(self, row: sqlite3.Row) -> Resultado:
        comp = Comprobante.model_validate_json(row["comprobante_json"]).normalize_types()
        alertas = json.loads(row["alertas_json"] or "[]")
        alertas_det = json.loads(row["alertas_detalle_json"] or "[]")
        tiempos = json.loads(row["tiempos_json"] or "{}")
        return Resultado(
            id=row["id"],
            creado_en=row["creado_en"],
            hash_imagen=row["hash_imagen"],
            texto_ocr_crudo=row["texto_ocr_crudo"],
            ocr_confianza_media=float(row["ocr_confianza_media"]),
            variante_preprocesado=row["variante_preprocesado"],
            metodo=row["metodo"],
            alertas=alertas,
            alertas_detalle=alertas_det,
            estado=row["estado"],
            comprobante=comp,
            tiempos_ms=tiempos,
        )

    def obtener_resultado(self, resultado_id: str) -> Optional[Resultado]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM resultados WHERE id = ?", (resultado_id,)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_resultado(row)

    def listar_resultados(
        self,
        fecha_desde: Optional[date] = None,
        fecha_hasta: Optional[date] = None,
        proveedor_filtro: Optional[str] = None,
        estado_filtro: Optional[str] = None,
    ) -> List[Resultado]:
        query = "SELECT * FROM resultados WHERE 1=1"
        params: List[Any] = []

        if fecha_desde is not None:
            query += " AND (fecha_emision IS NOT NULL AND fecha_emision >= ?)"
            params.append(fecha_desde.isoformat())
        if fecha_hasta is not None:
            query += " AND (fecha_emision IS NOT NULL AND fecha_emision <= ?)"
            params.append(fecha_hasta.isoformat())
        if proveedor_filtro and proveedor_filtro.strip():
            query += " AND (LOWER(COALESCE(proveedor_razon_social, '')) LIKE ? OR COALESCE(proveedor_cuit, '') LIKE ?)"
            patron = f"%{proveedor_filtro.strip().lower()}%"
            params.extend([patron, patron])
        if estado_filtro and estado_filtro not in ("Todos", "todos", ""):
            query += " AND estado = ?"
            params.append(estado_filtro)

        query += " ORDER BY creado_en DESC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_resultado(r) for r in rows]

    def listar_claves_historial(self) -> List[Dict[str, Any]]:
        """Retorna resumen liviano de comprobantes guardados para chequeo de duplicados."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, hash_imagen, proveedor_cuit, tipo_comprobante,
                       letra, punto_venta, numero_comprobante
                FROM resultados
                """
            ).fetchall()
        return [dict(r) for r in rows]

    def eliminar_resultado(self, resultado_id: str) -> None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT hash_imagen FROM resultados WHERE id = ?", (resultado_id,)
            ).fetchone()
            conn.execute("DELETE FROM correcciones WHERE resultado_id = ?", (resultado_id,))
            conn.execute("DELETE FROM resultados WHERE id = ?", (resultado_id,))
            conn.commit()
            if row and row["hash_imagen"] and self.images_dir.exists():
                for img_file in self.images_dir.glob(f"{row['hash_imagen']}.*"):
                    try:
                        img_file.unlink()
                    except OSError:
                        pass
        logger.info("Resultado eliminado id=%s", resultado_id)

    def borrar_todos_los_datos(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM correcciones")
            conn.execute("DELETE FROM resultados")
            conn.commit()
        if self.images_dir.exists():
            shutil.rmtree(self.images_dir, ignore_errors=True)
        logger.info("Todos los datos del historial e imágenes fueron eliminados.")

    def obtener_metricas_correccion_manual(self) -> List[Dict[str, Any]]:
        """
        Calcula la tasa de corrección manual en producción por campo:
        (cantidad de comprobantes confirmados donde el campo fue editado por el usuario)
        / (total de comprobantes confirmados).
        """
        with self._connect() as conn:
            total_confirmados = conn.execute(
                "SELECT COUNT(*) AS c FROM resultados WHERE estado = 'confirmado'"
            ).fetchone()["c"]

            rows = conn.execute(
                """
                SELECT c.campo, COUNT(DISTINCT c.resultado_id) AS editados
                FROM correcciones c
                JOIN resultados r ON r.id = c.resultado_id
                WHERE r.estado = 'confirmado'
                GROUP BY c.campo
                """
            ).fetchall()

        mapa_editados = {r["campo"]: int(r["editados"]) for r in rows}
        salida: List[Dict[str, Any]] = []
        for campo in TODOS_LOS_CAMPOS:
            editados = mapa_editados.get(campo, 0)
            tasa = (editados / total_confirmados) if total_confirmados > 0 else 0.0
            salida.append(
                {
                    "campo": campo,
                    "comprobantes_confirmados": int(total_confirmados),
                    "campos_editados_manualmente": editados,
                    "tasa_correccion_manual": round(tasa, 4),
                }
            )
        return salida
