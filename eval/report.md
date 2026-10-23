# Reporte de Evaluación de Extracción de Comprobantes

> **Advertencia metodológica:** Los resultados medidos sobre el dataset sintético (`eval/dataset/`) evalúan la robustez del pipeline ante rotaciones, variaciones de contraste, sombras simuladas y ruido, pero **no reemplazan comprobantes reales autorizados**. La exactitud sobre comprobantes sintéticos sobrestima la exactitud real en producción con papel térmico físico deteriorado.

## Parámetros de la corrida

- **Comprobantes evaluados:** 30
- **Idiomas Tesseract disponibles en el entorno:** `eng, osd`
- **Configuración LLM:** Modo sin red por defecto (`FakeLLMExtractor` desactivado; `reglas+llm` refleja base solo reglas)
- **Umbral de similitud de proveedor (P1):** `90` (`token_sort_ratio`)
- **Umbral de confianza para revisión (P2):** `0.80`

## Exactitud a nivel comprobante (campos críticos)

- **Campos críticos considerados:** `fecha_emision, proveedor_cuit, numero_comprobante, importe_total`
- **Método `reglas`:** 28 / 30 (93.3%)
- **Método `reglas+llm`:** 28 / 30 (93.3%)

## Métricas por campo (`reglas` vs. `reglas+llm`)

| Campo | Ref. no nula | Coincidencias (Reglas) | Exactitud (Reglas) | Falsos Pos. (Reglas) | Omisiones (Reglas) | Errores (Reglas) | Exactitud (Reglas+LLM) |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `fecha_emision` | 30 | 30 | 100.0% | 0 | 0 | 0 | 100.0% |
| `proveedor_razon_social` | 30 | 30 | 100.0% | 0 | 0 | 0 | 100.0% |
| `proveedor_cuit` | 30 | 28 | 93.3% | 0 | 2 | 0 | 93.3% |
| `tipo_comprobante` | 30 | 28 | 93.3% | 0 | 2 | 0 | 93.3% |
| `letra` | 30 | 21 | 70.0% | 0 | 9 | 0 | 70.0% |
| `punto_venta` | 30 | 30 | 100.0% | 0 | 0 | 0 | 100.0% |
| `numero_comprobante` | 30 | 30 | 100.0% | 0 | 0 | 0 | 100.0% |
| `importe_neto_gravado` | 12 | 12 | 100.0% | 0 | 0 | 0 | 100.0% |
| `iva` | 12 | 12 | 100.0% | 0 | 0 | 0 | 100.0% |
| `otros_impuestos` | 3 | 3 | 100.0% | 0 | 0 | 0 | 100.0% |
| `importe_total` | 30 | 30 | 100.0% | 0 | 0 | 0 | 100.0% |
| `moneda` | 30 | 30 | 100.0% | 0 | 0 | 0 | 100.0% |
| `cae` | 28 | 28 | 100.0% | 0 | 0 | 0 | 100.0% |
| `proveedor_razon_social_exacto` | 30 | 30 | 100.0% | 0 | 0 | 0 | 100.0% |

## Exactitud desagregada por etiqueta de condición (`notas`)

| Condición de la imagen (`notas`) | Campos correctos | Campos con ref. no nula | Exactitud (Reglas) |
| :--- | ---: | ---: | ---: |
| `arrugado` | 122 | 128 | 95.3% |
| `buena_calidad` | 13 | 13 | 100.0% |
| `desenfocado` | 91 | 95 | 95.8% |
| `inclinado` | 153 | 160 | 95.6% |
| `sombra` | 192 | 199 | 96.5% |
| `termico` | 44 | 48 | 91.7% |

## Calibración simple de confianza (`>= P2` frente a `< P2`)

| Segmento de confianza | Campos extraídos acertados | Total campos extraídos | Exactitud observada |
| :--- | ---: | ---: | ---: |
| Confianza `>= 0.80` (no requiere revisión por P2) | 292 | 292 | 100.0% |
| Confianza `< 0.80` (marcado revisar) | 20 | 20 | 100.0% |
