# Lector Inteligente de Comprobantes (Mobile-First)

Aplicación web mobile-first en Python y Streamlit para fotografiar o subir comprobantes comerciales argentinos (Facturas A/B/C/M, Tickets, Notas de Crédito y Remitos), preprocesar la imagen con OpenCV, extraer automáticamente sus campos estructurados mediante OCR (Tesseract) y reglas deterministas (con asistencia opcional de LLM anclado al texto), validar consistencia fiscal y aritmética, permitir la corrección manual con trazabilidad y exportar a CSV y Excel (`.xlsx`).

---

## 1. Requisitos e Instalación

### 1.1. Instalación del binario de Tesseract OCR
`pytesseract` es un wrapper de Python y requiere que el binario del sistema **Tesseract OCR** junto con el paquete de idioma español (`spa`) e inglés (`eng`) estén instalados en el sistema operativo:

- **Debian / Ubuntu:**
  ```bash
  sudo apt-get update
  sudo apt-get install -y tesseract-ocr tesseract-ocr-spa libgl1
  ```
- **macOS (Homebrew):**
  ```bash
  brew install tesseract tesseract-lang
  ```
- **Windows:**
  Descargar e instalar el ejecutable mantenible de **UB Mannheim** (`tesseract-ocr-w64-setup.exe`), marcando durante la instalación el paquete de idioma adicional *Spanish (`spa`)*, y agregar `C:\Program Files\Tesseract-OCR` a la variable de entorno `PATH`.

### 1.2. Instalación de dependencias de Python (3.11+)
```bash
python3 -m venv .venv
source .venv/bin/activate  # En Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

---

## 2. Variables de Entorno

La aplicación funciona sin configuración adicional en modo 100% local (solo reglas). Podés personalizar su comportamiento mediante variables de entorno (o archivo `.env` no versionado):

| Variable | Valor por defecto | Descripción |
| :--- | :--- | :--- |
| `PROVEEDOR_SIMILARITY_P1` | `90` | **Parámetro P1:** umbral `rapidfuzz.fuzz.token_sort_ratio` para aceptar coincidencia de razón social en la evaluación. |
| `CONFIDENCE_THRESHOLD_P2` | `0.80` | **Parámetro P2:** umbral de confianza por debajo del cual un campo se marca como `"revisar"`. |
| `LLM_PROVIDER` | `gemini` | **Parámetro P3:** proveedor de LLM seleccionable (`gemini`, `openai` o `fake`). |
| `LLM_API_KEY` | *(vacío)* | Clave de API del proveedor LLM externo. Nunca se persiste en disco ni en SQLite. |
| `LLM_MODEL` | `gemini-2.5-flash` | Nombre del modelo del proveedor LLM. |
| `MIN_VALID_DATE` | `2000-01-01` | Fecha mínima aceptada por el validador de fechas. |
| `ARITHMETIC_TOLERANCE` | `0.02` | Tolerancia en moneda para la validación aritmética (`neto + IVA + otros == total`). |
| `MAX_IMAGE_MB` | `15` | Tamaño máximo permitido por archivo de imagen en MB. |
| `MERGE_CONFLICT_PREFERENCE` | `reglas` | Política cuando reglas y LLM difieren (`reglas` mantiene reglas visible y sugiere LLM). |

---

## 3. Ejecución y Despliegue

### 3.1. Ejecución local en escritorio
```bash
streamlit run app/main.py
```

### 3.2. Uso desde el celular en red local (Wi-Fi)
```bash
streamlit run app/main.py --server.address 0.0.0.0
```
- **Importante sobre HTTPS y cámara en móviles:** Los navegadores móviles modernos (Safari en iOS, Chrome en Android) exigen un **contexto seguro (HTTPS)** para habilitar la API `getUserMedia` que usa `st.camera_input` (salvo en `localhost`).
- Por lo tanto, si accedés por HTTP plano a la IP local (`http://192.168.x.x:8501`), **`st.camera_input` puede estar bloqueado por el navegador**, mientras que **`st.file_uploader` funciona siempre** y abre la cámara nativa del sistema operativo a resolución completa (lo cual además brinda mejor calidad de OCR).
- **Alternativa con túnel HTTPS:** si necesitás usar `st.camera_input` desde el celular, podés exponer el puerto 8501 mediante un túnel HTTPS local (por ejemplo `cloudflared tunnel --url http://localhost:8501`, `ngrok http 8501` o Tailscale Funnel).

### 3.3. Despliegue en Streamlit Community Cloud
1. Subí este repositorio a GitHub (verificando que `data/` y `.env` estén en `.gitignore`).
2. Creá una nueva app en Streamlit Community Cloud apuntando a `app/main.py`.
3. Streamlit Community Cloud detectará automáticamente `packages.txt` (`tesseract-ocr`, `tesseract-ocr-spa`, `libgl1`) e instalará los paquetes del sistema junto con `requirements.txt`, proveyendo HTTPS de forma nativa.

### 3.4. Despliegue con Docker
```bash
docker build -t lector-comprobantes .
docker run --rm -p 8501:8501 -v $(pwd)/data:/app/data lector-comprobantes
```

---

## 4. Cómo Correr las Pruebas Automatizadas

Las pruebas unitarias (`tests/test_validators.py`, `tests/test_extract_rules.py`, `tests/test_merge.py`, `tests/test_metrics.py`) se ejecutan sin conexión de red y sin requerir el binario de Tesseract (excepto la prueba de integración marcada con `@pytest.mark.tesseract`, que se omite automáticamente si el binario no está instalado):

```bash
pytest -v
# Para excluir explícitamente la prueba de integración con Tesseract:
pytest -v -m "not tesseract"
```

---

## 5. Evaluación y Dataset de Referencia

### 5.1. Generar el dataset sintético (30 comprobantes con degradaciones)
```bash
python3 eval/generate_synthetic.py
```
> **Advertencia fundamental:** Los comprobantes sintéticos generados por `eval/generate_synthetic.py` sirven para verificar el funcionamiento mecánico del pipeline (deskew, binarización, regex y validadores), pero **no reemplazan comprobantes reales autorizados**. La exactitud medida sobre comprobantes sintéticos **sobrestima la exactitud real** frente a tickets térmicos físicos gastados, arrugados o fotografiados en ángulo.

### 5.2. Ejecutar la evaluación contra `ground_truth.json`
```bash
# Evaluación por defecto (sin red, usando solo reglas y FakeLLMExtractor desactivado):
python3 eval/run_eval.py

# Evaluación activando el proveedor LLM real configurado en LLM_API_KEY:
python3 eval/run_eval.py --llm
```
Genera tres archivos en `eval/`:
- `eval/report.md`: tabla comparativa por campo y por método, exactitud a nivel comprobante (campos críticos), desagregación por condición (`notas`) y calibración de confianza (`>= P2` vs. `< P2`).
- `eval/report.csv`: métricas tabulares exportables.
- `eval/errores.csv`: detalle fila por fila de falsos positivos, omisiones y errores (`imagen, campo, esperado, obtenido, texto_origen, metodo, tipo_discrepancia`).

### 5.3. Cómo agregar un comprobante real autorizado al dataset
1. Copiá la imagen (`JPG` o `PNG`) en `eval/dataset/images/` (por ejemplo `real_001.jpg`).
2. Agregá una entrada en el array de `eval/dataset/ground_truth.json` transcribiendo manualmente los valores visibles y dejando `null` (o `[]` en listas) cuando un campo no sea visible en el papel:
   ```json
   {
     "archivo": "real_001.jpg",
     "notas": ["termico", "sombra", "arrugado"],
     "campos": {
       "fecha_emision": "2026-10-20",
       "proveedor_razon_social": "COMERCIO EJEMPLO S.R.L.",
       "proveedor_cuit": "30710011228",
       "tipo_comprobante": "Ticket",
       "letra": "B",
       "punto_venta": "0005",
       "numero_comprobante": "00012345",
       "importe_neto_gravado": null,
       "iva": [],
       "otros_impuestos": [],
       "importe_total": "8500.00",
       "moneda": "ARS",
       "cae": null
     }
   }
   ```
3. Volvé a correr `python3 eval/run_eval.py` para recalibrar `P1` y `P2`.

---

## 6. Fórmulas y Heurísticas Documentadas

1. **Selección de variante de preprocesado en `app/ocr.py`:**
   Se evalúan las variantes **A** (escala de grises + CLAHE + binarización adaptativa gaussiana), **B** (escala de grises + GaussianBlur + umbral de Otsu) y **C** (escala de grises sin binarizar) con `--oem 1 --psm 6` (y `--psm 4` cuando la confianza media es `< 60`). Se selecciona la variante que maximiza el puntaje ponderado:
   $$\text{Puntaje} = \text{confianza\_media} \times \ln(1 + N_{\text{palabras con conf} > 0})$$
2. **Cálculo de confianza por campo en `app/extract_rules.py`:**
   $$\text{confianza} = \min\left(1.0,\; \frac{\overline{\text{conf}}_{\text{OCR}}(\text{palabras involucradas})}{100} \times \begin{cases} 0.9 & \text{si hay ambigüedad} \\ 1.0 & \text{sin ambigüedad} \end{cases}\right)$$
3. **Heurística de extracción de Razón Social (`proveedor_razon_social`):**
   - Si una línea del encabezado declara explícitamente `Razón Social: ...`, se toma ese valor.
   - Si hay metadatos geométricos de Tesseract (`lineas_ocr`), se inspeccionan las primeras 8 líneas del encabezado excluyendo palabras reservadas (`FACTURA`, `ORIGINAL`, `DUPLICADO`, `COD.`, `TICKET`, `CUIT`, `INGRESOS BRUTOS`, etc.) y líneas numéricas; se elige la línea con mayor altura de texto si supera en `>= 25%` a la primera línea válida, o la primera línea válida en caso contrario.
   - En texto plano sin geometría, se elige la primera línea del encabezado con al menos 4 letras mayúsculas que no contenga términos excluidos.
4. **Heurística de `importe_neto_gravado` vs. `Subtotal` en comprobantes B/C:**
   En facturas B/C y tickets a consumidor final suele imprimirse una línea `Subtotal` igual al `Importe Total` sin discriminar IVA. Si no hay ítems de IVA discriminados, `Subtotal == Total` y la etiqueta no contiene la palabra `"neto"`, `importe_neto_gravado` se mantiene en `null` (`fuente="ninguna"`) para no inventar un neto gravado inexistente.

---

## 7. Limitaciones Conocidas

- **Comprobantes manuscritos:** No se garantiza lectura de remitos o facturas completadas a mano.
- **Papel térmico muy desvaído:** Si la tinta térmica perdió contraste casi por completo, tanto CLAHE como Otsu pueden omitir dígitos; esos campos quedarán en `null` o con alerta aritmética para carga manual.
- **Sin validación en línea contra ARCA/AFIP:** El sistema valida formato y módulo 11 del CUIT y longitud del CAE, pero no consulta constancia de inscripción ni validez del CAE ante servicios web de ARCA/AFIP.

---

## 8. Decisiones Tomadas

1. **Compatibilidad dual Pydantic v2 / v1 (`CompatBaseModel` en `app/models.py`):** Se implementó el modelo con la API estándar de Pydantic v2 (`model_dump`, `model_validate`, `model_json_schema`) e incluyendo un adaptador transparente cuando se ejecuta sobre entornos con Pydantic 1.x preinstalado, garantizando portabilidad total.
2. **Fallback determinista de `token_sort_ratio` y paquete de idioma `spa`:** En entornos de prueba aislados donde el paquete binario `tesseract-ocr-spa` o la rueda `rapidfuzz` no estén preinstalados a nivel sistema, `app/ocr.py` informa mediante advertencia explícita que se utilizó el idioma disponible (`eng`) en lugar de abortar con traza técnica, y `eval/metrics.py` provee la función equivalente exacta de `token_sort_ratio` basada en tokens ordenados alfabéticamente.
3. **Deskew por mediana de rectángulos de líneas de texto (`minAreaRect`):** Aplicar `cv2.minAreaRect` sobre la nube global de píxeles de toda la página puede sesgar el ángulo cuando los renglones tienen largos desiguales (margen derecho irregular). Se aplicó cierre morfológico horizontal para medir `minAreaRect` sobre los bloques de líneas de texto y tomar su mediana, corrigiendo únicamente cuando el ángulo absoluto está entre `0.5°` y `15°`.
4. **Normalización de `tipo_comprobante` en evaluación:** En tickets térmicos donde el encabezado dice `"TIQUE FACTURA B"` o `"TICKET"`, el evaluador normaliza ambos bajo la familia `"TICKET"` para no penalizar variantes léxicas del mismo tipo documental.

---

## 9. Propuestas (No Implementadas, Fuera del Alcance Actual)

- **Lectura del código QR fiscal de AFIP/ARCA:** Los comprobantes electrónicos argentinos suelen incluir un código QR en la base cuyo payload en Base64/JSON contiene `cuit`, `ptoVta`, `tipoCmp`, `nroCmp`, `importe`, `moneda` y `codAut` (CAE). Decodificar ese QR permitiría contrastar o autocompletar los campos críticos con 100% de exactitud cuando el QR sea legible.
- **Recorte interactivo manual en la interfaz móvil:** Permitir que el usuario ajuste manualmente las 4 esquinas del comprobante en pantalla cuando el fondo de la mesa tenga texturas complejas que impidan detectar el cuadrilátero automáticamente.

### 8.1. Conflictos detectados en la especificación y resolución aplicada
1. **Regla general "sin valor por defecto" vs. regla específica de `moneda` ("por defecto ARS si muestra $"):** La Sección 6 prohíbe valores por defecto, pero define para `moneda` el valor `"ARS"` cuando aparece `"$"` sin otra divisa. Se resolvió aplicando la regla específica anclada al símbolo `"$"` (guardando `"$"` en `texto_origen`), y devolviendo `null` (`fuente="ninguna"`) cuando el documento no muestra símbolo monetario (p. ej. Remitos X).
2. **Métricas por método (`reglas` vs. `reglas+llm`) vs. evaluación sin red por defecto (`FakeLLMExtractor` desactivado):** La Sección 14 solicita reportar métricas por método pero prohíbe usar el LLM real salvo con `--llm`. Se resolvió incluyendo ambas series en `report.md` y `report.csv`: sin `--llm`, `reglas+llm` utiliza `FakeLLMExtractor` vacío (sin tráfico de red), y con `--llm` consulta el proveedor configurado en `LLM_PROVIDER`.
3. **Búsqueda de `"Subtotal"` para `importe_neto_gravado` (Sección 8) vs. Facturas B/C sin IVA discriminado (Sección 6):** En comprobantes B/C suele figurar `Subtotal` igual al `Total`. Para no generar falsos positivos de neto gravado cuando no está discriminado, `Subtotal` solo se asigna a `importe_neto_gravado` si existen ítems de IVA discriminados o si difiere del `Total`.
