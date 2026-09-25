# Viabilidad de TensorFlow Lite Micro en el ESP32 (Módulo 3)

Fecha: 2026-09-25. Modelo: CNN-BiLSTM-Attention de `Modulo2_Pipeline_DL/common/modelo.py`
(origin/main, a00f17d), entrada (20, 8), 5 clases, **76 933 parámetros**. Arquitectura sin
cambios.

## Qué se probó y con qué datos

- **No existe todavía un modelo entrenado ni datos reales del hardware**: no hay ningún
  `.keras`, `.tflite` ni CSV de captura del brazalete en el disco.
- Se construyó el modelo con `construir_modelo()` de producción y se entrenó 4 épocas sobre un
  **CSV sintético** con el esquema de producción: v1..v5 en voltios (0.05–2.0), ax..az en g,
  bloques contiguos, 5 clases.
- Sirve para comprobar la conversión, las operaciones, la memoria y el tiempo, que dependen de
  la arquitectura y no de los pesos. **No sirve para medir la precisión real**: hay que repetir la
  conversión con el modelo entrenado sobre datos reales.
- Entornos (WSL):
  - `~/venv-tesis`: TF 2.16.1 + Keras 3.15.1, el de la tesis. Solo se leyó.
  - `~/venv-tflite-viab`, nuevo: TF 2.21.0 + tf_keras 2.21.
  - `~/venv-tflm313`, nuevo: Python 3.13 + tflite-micro 0.dev20260923, el intérprete oficial
    de TFLite Micro.
- Scripts y resultados de la prueba: carpeta de trabajo fuera del repo
  (`scratchpad/m/Modulo2_Pipeline_DL/tf_viab/`).

## 1. Conversión con el script de producción

`produccion/convertir_tflite.py` **no funciona tal como está**. Hubo tres fallos, en orden:

| # | Fallo | Causa | Arreglo aplicado en la prueba (copia, no en el repo) |
|---|---|---|---|
| 1 | `Could not locate class 'MecanismoAtencion'` al cargar el `.keras` | `custom_objects={"MecanismoAtencion": None}` no registra la clase | `custom_objects={"MecanismoAtencion": MecanismoAtencion}` |
| 2 | Con Keras 3 (venv-tesis): el conversor aborta (TF 2.16) o falla (TF 2.21) | **Keras 3 exporta la LSTM como un bucle WHILE** con GATHER/SLICE, que no se fusiona en la LSTM nativa de TFLite. La cuantización INT8 de ese bucle **revienta el proceso (segfault)** en TF 2.16.1 y en TF 2.21.0, con cualquier opción del cuantizador | Entrenar y convertir con **Keras 2 (`tf_keras`, `TF_USE_LEGACY_KERAS=1`)**. Con él la LSTM sale como la operación nativa `UNIDIRECTIONAL_SEQUENCE_LSTM` |
| 3 | `TensorListReserve ... element_shape to be static` | `from_keras_model` convierte con lote variable y la LSTM no se puede fusionar | Convertir con **lote fijo de 1** (`from_concrete_functions` con `TensorSpec([1, 20, 8])`). El ESP32 infiere una ventana cada vez |

Además, el script copia el `.h` a `../Modulo3_Inferencia_Control/` relativo a la carpeta desde
la que se ejecuta: solo acierta si se lanza desde `Modulo2_Pipeline_DL/`.

Con los arreglos 1–3, y **los mismos ajustes de cuantización de producción** (`Optimize.DEFAULT`,
1000 primeras ventanas de calibración, `TFLITE_BUILTINS_INT8`, entrada y salida float32), la
conversión funciona: **modelo INT8 de 99 936 bytes (97.6 KB)**.

## 2. Operaciones del modelo INT8 y soporte

| Operación | Veces | Tipo | TFLite Micro oficial (2026-09-23) | Chirale_TensorFLowLite 2.0.0 |
|---|---|---|---|---|
| QUANTIZE (entrada float → int8) | 1 | float32 → int8 | sí | sí |
| RESHAPE | 4 | int8 | sí | sí |
| CONV_2D (las dos Conv1D) | 2 | int8 | sí | sí |
| MUL (BatchNorm y atención) | 3 | int8 | sí | sí |
| ADD (BatchNorm) | 2 | int8 | sí | sí |
| **REVERSE_V2** (rama hacia atrás de la BiLSTM) | 2 | int8 | sí | **NO** |
| UNIDIRECTIONAL_SEQUENCE_LSTM (BiLSTM = 2) | 2 | int8, estado de celda int16 | sí | sí (`EvalInteger8x8_16Lstm`) |
| CONCATENATION | 1 | int8 | sí | sí |
| FULLY_CONNECTED (atención ×2, Dense ×2) | 4 | int8 | sí | sí |
| TANH (atención) | 1 | int8 | sí | sí |
| SOFTMAX (atención y salida) | 2 | int8 | sí | sí |
| SUM (atención) | 1 | int8 | sí | sí |
| DEQUANTIZE (salida int8 → float) | 1 | int8 → float32 | sí | sí |

- **BiLSTM:** se convierte en dos `UNIDIRECTIONAL_SEQUENCE_LSTM` más dos `REVERSE_V2` y una
  `CONCATENATION`. Todo INT8, con el estado interno de 16 bits que usa TFLite para las LSTM.
- **Atención:** se convierte en FULLY_CONNECTED + TANH + FULLY_CONNECTED + SOFTMAX + MUL + SUM, todas
  INT8.
- **En el intérprete oficial de TFLite Micro el modelo completo corre**:
  - las 300 ventanas de prueba dan la misma clase que TFLite INT8 (300/300; diferencia máxima de
    probabilidad 0.039);
  - arena necesaria **16 128 bytes** (medida en PC, 64 bits).
- **Única operación no soportada por la librería de Arduino: `REVERSE_V2`.**
  - Alternativa aplicada, sin tocar arquitectura ni librería: kernel propio `reverse_v2_lmg.cpp`
    en el sketch, registrado con un *resolver* propio (`ResolverModeloLMG` en `inferencia.cpp`).
  - Otras alternativas, no aplicadas: vendorizar una versión más nueva de TFLite Micro, o
    esp-tflite-micro de Espressif, que además trae ESP-NN para acelerar conv y FC.

## 3. Precisión INT8 frente a float (datos sintéticos, orientativo)

| | Acierto en 300 ventanas |
|---|---|
| float (Keras) | 88.3 % |
| INT8, calibrado con las 1000 primeras ventanas (producción) | 73.3 % |
| INT8, calibrado con 1000 ventanas al azar | 73.3 % |

- El INT8 coincide con el float en el 84 % de las ventanas. El docstring de producción promete
  una pérdida < 2 %; **con este modelo de prueba es de 15 puntos**.
- **Por capa el error es normal:** menos de 1 paso de cuantización en todas, con el máximo en la
  LSTM hacia atrás (0.77) y en el MUL de la atención (0.63). No hay una capa rota: el error se
  acumula.
- **Hay que medirlo con el modelo real.** Si se confirma, hay dos alternativas que no cambian la
  arquitectura:
  - **(i)** entrenamiento con cuantización simulada (QAT);
  - **(ii)** activaciones de 16 bits (cuantización 16x8), comprobando antes que TFLite Micro
    tenga todas las operaciones en esa variante.

## 4. Compilación de Modulo3 con el modelo real (sintético)

Rama `firmware-dos-ads1115`. `inferencia.cpp` pasa de TensorFlowLite_ESP32 1.0.0 (no compila con
el core esp32 3.x) a **Chirale_TensorFLowLite 2.0.0**, con un resolver de 13 operaciones en lugar
de AllOpsResolver. Core esp32 3.3.11, placa `esp32:esp32:esp32`.

| Memoria | Uso | Límite |
|---|---|---|
| Flash (programa + modelo) | **550 195 B (41 %)**; el modelo ocupa 99 936 B | 1 310 720 B |
| RAM estática | **26 592 B (8 %)** | 327 680 B |
| Arena de TFLite Micro | reservada al arrancar: 40 KB (`TENSOR_ARENA_SIZE`); el modelo necesita ~16 KB (PC) | del heap |

**Validación en PC antes de grabar la placa.** Se compiló la misma librería Chirale, con los
mismos kernels CMSIS-NN que usa el ESP32 y con `reverse_v2_lmg.cpp` y el resolver del sketch, y se
ejecutaron las 300 ventanas de prueba:

- Arena usada: **17 648 bytes**.
- Misma clase que TFLite Micro oficial en **299 de 300** ventanas.
  - La diferencia de probabilidad es 0 en la mediana, y solo 3 ventanas difieren en más de 0.1.
  - Probablemente se debe a que la LSTM de la librería es una versión anterior de la de TFLite
    Micro; no está demostrado.
- La validación encontró un caso real: tras la LSTM hacia atrás, la entrada y la salida de
  `REVERSE_V2` tienen **escalas distintas en un 0.07 %**. El kernel lo acepta hasta un 1 % (error
  menor de 0.1 paso) y rechaza diferencias mayores con un mensaje claro.

**El `modelo_gestos_tflite.h` que hay ahora en `Modulo3_Inferencia_Control/` es el de prueba**
(datos sintéticos). Está en `.gitignore` y lleva un aviso en su cabecera. **No clasifica gestos
reales.**

## 5. Tiempo de inferencia

**No medido en el ESP32: no había ninguna placa conectada.** El sketch ya lo mide
(`tInferenciaUs` alrededor de `tflite.predecir()`), y `tflite.info()` imprime la arena
realmente usada al arrancar.

Estimación gruesa, para saber qué esperar. El modelo hace unas **1.43 millones de
multiplicaciones-suma por ventana**:

| Parte | Multiplicaciones-suma | Proporción |
|---|---|---|
| Conv1D 1 y 2 | 0.52 M | 36 % |
| BiLSTM (2 × 20 pasos) | 0.82 M | 57 % |
| Atención y Dense | 0.09 M | 7 % |

- Con los kernels en C portable de la librería (sin aceleración ESP-NN), el orden esperable en un
  ESP32 a 240 MHz es de **decenas de milisegundos**.
- El firmware pide una inferencia cada **20 ms** (`INTERVALO_INFERENCIA_MS`). **Es probable que no
  quepa**: hay que medirlo en la placa antes de decidir nada.
