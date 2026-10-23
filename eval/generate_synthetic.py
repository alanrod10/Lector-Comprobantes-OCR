"""Generador de al menos 30 comprobantes sintéticos argentinos con degradaciones móviles y ground_truth.json."""
from __future__ import annotations

import io
import json
import random
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.locale_ar import calcular_digito_verificador_cuit

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoMono-Regular.ttf",
]

PROVEEDORES_POOL = [
    ("DISTRIBUIDORA DEL NORTE S.R.L.", "3071001122"),
    ("FERRETERIA INDUSTRIAL SAN MARTIN S.A.", "3061112224"),
    ("MAYORISTA ALIMENTICIO JUJUY S.A.", "3050001234"),
    ("PANIFICADORA CENTRAL S.R.L.", "3071122334"),
    ("SUPERMERCADO EL SOL S.A.", "3058889991"),
    ("PAPELERA DEL NOA S.A.", "3070998877"),
    ("SERVICIOS GRAFICOS ANDINOS", "2031223344"),
    ("CORRALON EL PUENTE S.A.", "3071234567"),
    ("LACTEOS DEL VALLE S.R.L.", "3070112233"),
    ("INSUMOS GASTRONOMICOS SUR S.A.S.", "3071556677"),
    ("FARMACIA AVENIDA S.C.S.", "3068887771"),
    ("LIBRERIA COMERCIAL BELGRANO", "2729887766"),
]


def _cargar_fuente(path_list: List[str], size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for p in path_list:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _formatear_pesos_ar(monto: Decimal) -> str:
    s = f"{monto:,.2f}"
    # Convertir 12,345.67 -> 12.345,67
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _aplicar_degradaciones_movil(
    img_pil: Image.Image,
    rng: random.Random,
    np_rng: np.random.Generator,
    es_termico: bool,
) -> Tuple[bytes, List[str]]:
    """
    Aplica degradaciones realistas de captura móvil:
    rotación entre -8° y 8°, perspectiva leve, sombra/iluminación, arrugas, desenfoque y compresión JPEG.
    """
    notas: List[str] = []
    img_np = np.array(img_pil.convert("RGB"), dtype=np.float32)
    h, w, _ = img_np.shape

    if es_termico:
        notas.append("termico")
        # Papel térmico ligeramente grisáceo/cálido y menor contraste de tinta
        img_np = np.clip(img_np * 0.96 + np.array([4.0, 3.0, 0.0]), 0, 255)

    # 1. Arrugas simuladas (bandas sinusoidales sutiles de iluminación)
    if rng.random() < 0.40:
        notas.append("arrugado")
        yy, xx = np.mgrid[0:h, 0:w]
        freq = rng.uniform(0.015, 0.03)
        onda = 10.0 * np.sin(yy * freq + xx * 0.005)
        img_np = np.clip(img_np + onda[:, :, None], 0, 255)

    # 2. Sombra / gradiente de iluminación lateral o diagonal
    if rng.random() < 0.50:
        notas.append("sombra")
        yy, xx = np.mgrid[0:h, 0:w]
        grad = 1.0 - 0.22 * ((xx / float(w)) * 0.6 + (yy / float(h)) * 0.4)
        img_np = np.clip(img_np * grad[:, :, None], 0, 255)

    # 3. Ruido gaussiano suave
    sigma = rng.uniform(2.0, 6.5)
    ruido = np_rng.normal(0.0, sigma, size=img_np.shape)
    img_np = np.clip(img_np + ruido, 0, 255).astype(np.uint8)

    # 4. Perspectiva leve
    if rng.random() < 0.35:
        dx = int(w * rng.uniform(0.01, 0.025))
        dy = int(h * rng.uniform(0.01, 0.025))
        src = np.float32([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]])
        dst = np.float32(
            [[dx, dy], [w - 1 - dx, 0], [w - 1, h - 1 - dy], [0, h - 1]]
        )
        mat_p = cv2.getPerspectiveTransform(src, dst)
        img_np = cv2.warpPerspective(
            img_np,
            mat_p,
            (w, h),
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(245, 245, 245),
        )

    # 5. Rotación entre -8° y 8° (aplicada en un subconjunto para evaluar deskew e inclinación)
    if rng.random() < 0.45:
        angulo = rng.choice([rng.uniform(-7.5, -1.5), rng.uniform(1.5, 7.5)])
        notas.append("inclinado")
        centro = (w // 2, h // 2)
        mat_r = cv2.getRotationMatrix2D(centro, angulo, 1.0)
        img_np = cv2.warpAffine(
            img_np,
            mat_r,
            (w, h),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(248, 248, 248),
        )

    img_out = Image.fromarray(img_np)

    # 6. Desenfoque leve en algunas muestras
    if rng.random() < 0.25:
        notas.append("desenfocado")
        img_out = img_out.filter(ImageFilter.GaussianBlur(radius=0.65))

    if not notas:
        notas.append("buena_calidad")

    calidad_jpeg = rng.randint(75, 92)
    buf = io.BytesIO()
    img_out.save(buf, format="JPEG", quality=calidad_jpeg)
    return buf.getvalue(), notas


def generar_dataset_sintetico(
    dataset_dir: Path,
    cantidad: int = 30,
    seed: int = 42,
) -> List[Dict[str, Any]]:
    """Genera `cantidad` comprobantes sintéticos en `dataset_dir/images` y `dataset_dir/ground_truth.json`."""
    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)

    images_dir = dataset_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    disponibles = [p for p in FONT_CANDIDATES if Path(p).exists()]
    if not disponibles:
        disponibles = FONT_CANDIDATES[:1]

    ground_truth: List[Dict[str, Any]] = []
    fecha_base = date(2026, 10, 18)

    for idx in range(1, cantidad + 1):
        prov_nombre, cuit_base10 = PROVEEDORES_POOL[(idx - 1) % len(PROVEEDORES_POOL)]
        verif = calcular_digito_verificador_cuit(cuit_base10)
        if verif is None:
            cuit_base10 = "3071001122"
            verif = calcular_digito_verificador_cuit(cuit_base10) or 8
        cuit_limpio = f"{cuit_base10}{verif}"
        cuit_formateado = f"{cuit_limpio[:2]}-{cuit_limpio[2:10]}-{cuit_limpio[10]}"

        # Distribución de clases de comprobantes:
        # 1..12: Factura A, 13..20: Factura B, 21..25: Factura C, 26..30: Ticket B
        if idx <= 12:
            tipo_comp = "Factura"
            letra = "A"
            es_termico = False
            tiene_cae = True
        elif idx <= 20:
            tipo_comp = "Factura"
            letra = "B"
            es_termico = False
            tiene_cae = True
        elif idx <= 25:
            tipo_comp = "Factura"
            letra = "C"
            es_termico = False
            tiene_cae = True
        else:
            tipo_comp = "Ticket"
            letra = "B"
            es_termico = True
            tiene_cae = idx % 2 == 0

        fecha_em = fecha_base - timedelta(days=(idx * 2) % 90)
        pv_int = (idx % 9) + 1
        pv_str = f"{pv_int:04d}"
        nro_int = 10000 + idx * 137
        nro_str = f"{nro_int:08d}"

        neto_val = Decimal(str(1500 + idx * 425)).quantize(Decimal("0.01"))
        iva_list: List[Dict[str, str]] = []
        otros_list: List[Dict[str, str]] = []

        if letra == "A":
            alic = Decimal("21") if idx % 3 != 0 else Decimal("10.5")
            iva_imp = (neto_val * alic / Decimal("100")).quantize(Decimal("0.01"))
            iva_list.append({"alicuota": str(alic), "importe": str(iva_imp)})
            if idx % 4 == 0:
                perc_imp = (neto_val * Decimal("0.03")).quantize(Decimal("0.01"))
                otros_list.append({"descripcion": "Percepcion IIBB", "importe": str(perc_imp)})
                total_val = (neto_val + iva_imp + perc_imp).quantize(Decimal("0.01"))
            else:
                total_val = (neto_val + iva_imp).quantize(Decimal("0.01"))
            neto_gt: Optional[str] = str(neto_val)
        else:
            total_val = neto_val
            neto_gt = None

        cae_val = f"74{idx:04d}891045{idx:02d}" if tiene_cae else None

        # Elegir tipografía para esta muestra
        font_path = disponibles[(idx - 1) % len(disponibles)]
        font_header = _cargar_fuente([font_path], 28)
        font_body = _cargar_fuente([font_path], 24)

        ancho_img = 960 if not es_termico else 760
        alto_img = 820
        img = Image.new("RGB", (ancho_img, alto_img), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)

        # Formatos de fecha variados
        if idx % 4 == 0:
            fecha_texto = fecha_em.strftime("%d-%m-%Y")
        elif idx % 5 == 0:
            fecha_texto = fecha_em.strftime("%d.%m.%Y")
        else:
            fecha_texto = fecha_em.strftime("%d/%m/%Y")

        # Formatos de PV y Número variados
        if idx % 2 == 0:
            linea_pv_nro = f"Punto de Venta: {pv_str} Comp. Nro: {nro_str}"
        else:
            linea_pv_nro = f"Nro: {pv_str} - {nro_str}"

        lineas_dibujo: List[Tuple[str, Any]] = [
            (prov_nombre, font_header),
            (f"{tipo_comp.upper()} {letra}   COD. 00{idx % 9 + 1}", font_header),
            (linea_pv_nro, font_body),
            (f"Fecha de Emision: {fecha_texto}", font_body),
            (f"C.U.I.T.: {cuit_formateado}", font_body),
            ("Ingresos Brutos: 901-445566-2", font_body),
            ("Inicio de Actividades: 01/04/2018", font_body),
            ("----------------------------------------------", font_body),
            ("Condicion de Venta: Contado", font_body),
        ]

        if letra == "A":
            lineas_dibujo.append(
                (f"Importe Neto Gravado: $ {_formatear_pesos_ar(neto_val)}", font_body)
            )
            for item_i in iva_list:
                alic_s = item_i["alicuota"].replace(".", ",")
                imp_d = Decimal(item_i["importe"])
                lineas_dibujo.append(
                    (f"IVA {alic_s}%: $ {_formatear_pesos_ar(imp_d)}", font_body)
                )
            for item_o in otros_list:
                imp_o = Decimal(item_o["importe"])
                lineas_dibujo.append(
                    (f"{item_o['descripcion']}: $ {_formatear_pesos_ar(imp_o)}", font_body)
                )
        else:
            lineas_dibujo.append(
                (f"Subtotal: $ {_formatear_pesos_ar(total_val)}", font_body)
            )

        lineas_dibujo.append(
            (f"IMPORTE TOTAL: $ {_formatear_pesos_ar(total_val)}", font_header)
        )
        if cae_val:
            lineas_dibujo.append((f"CAE: {cae_val}", font_body))

        y = 50
        for texto_l, fnt in lineas_dibujo:
            draw.text((55, y), texto_l, fill=(10, 10, 10), font=fnt)
            y += 54

        nombre_img = f"comprobante_{idx:03d}.jpg"
        jpg_bytes, notas = _aplicar_degradaciones_movil(
            img, rng=rng, np_rng=np_rng, es_termico=es_termico
        )
        (images_dir / nombre_img).write_bytes(jpg_bytes)

        ground_truth.append(
            {
                "archivo": nombre_img,
                "notas": notas,
                "campos": {
                    "fecha_emision": fecha_em.isoformat(),
                    "proveedor_razon_social": prov_nombre,
                    "proveedor_cuit": cuit_limpio,
                    "tipo_comprobante": tipo_comp,
                    "letra": letra,
                    "punto_venta": pv_str,
                    "numero_comprobante": nro_str,
                    "importe_neto_gravado": neto_gt,
                    "iva": iva_list,
                    "otros_impuestos": otros_list,
                    "importe_total": str(total_val),
                    "moneda": "ARS",
                    "cae": cae_val,
                },
            }
        )

    gt_path = dataset_dir / "ground_truth.json"
    gt_path.write_text(
        json.dumps(ground_truth, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return ground_truth


if __name__ == "__main__":
    destino = ROOT_DIR / "eval" / "dataset"
    items = generar_dataset_sintetico(destino, cantidad=30, seed=42)
    print(f"Generados {len(items)} comprobantes sintéticos en {destino}")
