# Pérdida de la cuantización INT8 con datos reales (NinaPro DB5)

**Pregunta que responde:** ¿cuánta exactitud se pierde al convertir el modelo a INT8 para el ESP32?
Se mide con datos reales antes de tener datos propios.

La respuesta sale del mismo código que genera el modelo del ESP32: `produccion/convertir_tflite.py`,
con Keras 2 y el entorno de `requirements-produccion.txt`. **No sustituye a la validación
preliminar** (`validacion_preliminar_emg/`), que sigue tal cual en su entorno original.

## Qué cambia frente a la validación preliminar, y qué no

| | Aquí | Validación preliminar |
|---|---|---|
| Frecuencia | **100 Hz**: ventana 20 × 8, la forma exacta de producción | 200 Hz, ventana 40 × 8 |
| Remuestreo | EMG y ACC diezmados ×2 (FIR antialias, fase cero) sobre la señal continua de cada archivo | ACC 200 → 50 → 200 Hz |
| Keras | 2 (`tf_keras`) | 3 |
| Canales, mapeo, submuestreo de Rest | igual | |
| Partición | GroupKFold k = 5 por **sujeto**; se entrena **un pliegue** (el 1) | los 5 |
| Normalización | por sujeto | |
| Validación | interna (un sujeto del train) + reentreno con todo el train | |
| Semilla, épocas, lote, lr, `early_stopping_start` | 42, 100, 32, 1e-3, 10 | |

El pliegue 1 (sujetos 3 y 6 en test) es el más difícil también a 200 Hz: 56.4 % frente a una media de
70.0 %. Aquí solo importa la diferencia entre coma flotante e INT8 sobre **el mismo** test.

## Resultados, pliegue 1 (10 746 ventanas de test)

| Variante | Exactitud | F1 macro | Pérdida | Coincide con float | En TFLite Micro | Tamaño |
|---|---|---|---|---|---|---|
| Keras, coma flotante | 49.92 % | 0.478 | — | — | — | — |
| TFLite float32, sin cuantizar (control) | 49.92 % | 0.478 | 0.00 pt | 100 % | 49.92 % | 310 KB |
| **INT8, calibración de producción** (1000 primeras ventanas) | **49.52 %** | 0.472 | **0.40 pt** | 96.6 % | 49.51 % | 97.6 KB |
| INT8, 1000 ventanas al azar | 49.18 % | 0.469 | 0.74 pt | 94.8 % | 49.21 % | 97.6 KB |

- **La pérdida INT8 es de 0.40 puntos, por debajo del umbral de 2.** No hace falta cuantizar a 16 bits
  ni QAT.
- La diferencia es pequeña pero no es ruido: 95 ventanas empeoran y 52 mejoran (McNemar exacto,
  p = 0.0005). El p-valor es optimista, porque las ventanas solapadas no son independientes.
- Por capa, el error de cuantización es menor de medio paso en todas; el máximo está en las dos LSTM
  (0.48 y 0.47).
- Calibrar con 2000 ventanas no mejora (49.23 %), y dejar la peor LSTM en float tampoco (49.52 %).
- TFLite Micro oficial da la misma clase que TFLite en PC en el 99.8 % de las ventanas.
- La librería de Arduino (Chirale, compilada en PC con el `REVERSE_V2` propio) da 49.68 %, con la
  misma clase en el 98.0 %.

### Activaciones de 16 bits: no disponibles para la LSTM

- El conversor de TensorFlow 2.21 **no genera** el modelo 16x8: *"Quantization to 16x8-bit not yet
  supported for op: UNIDIRECTIONAL_SEQUENCE_LSTM"*.
- La LSTM INT8 ya usa internamente un estado de celda de 16 bits (variante 8x8→16).
- La LSTM de Chirale_TensorFLowLite 2.0.0 solo acepta ese esquema o float.
- Con 0.40 puntos de pérdida no hace falta.

## Hallazgo: la LSTM de TFLite conserva su estado entre inferencias

La operación `UNIDIRECTIONAL_SEQUENCE_LSTM` guarda h y c en **tensores variables que persisten entre
llamadas a `invoke()`**. Si no se reinician, cada ventana arranca con el estado que dejó la anterior.
Eso no es lo que se entrenó: en Keras cada ventana empieza de cero.

| Sin reiniciar el estado | Exactitud |
|---|---|
| TFLite float32 | 47.78 % (en vez de 49.92 %) |
| INT8 | 47.54 % (en vez de 49.52 %) |

- Sin reiniciar, la pérdida aparente era de 2.4 puntos, y casi toda venía de esto y no de la
  cuantización.
- Los scripts reinician antes de cada ventana: `reset_all_variables()` en TFLite y `reset()` en
  TFLite Micro.
- **El firmware también**: `MotorInferencia::predecir()` llama a `Reset()` antes de `Invoke()`.

## Reproducir

```bash
# entorno de produccion (requirements-produccion.txt)
P=~/venv-tflite-viab/bin/python
$P entrenar_ninapro_100hz.py --mat ~/data/NinaPro_DB5 --pliegue 0 \
    --cache ~/cache_ninapro_100hz.npz --output_dir resultados
$P cuantizar_evaluar.py --pliegue 1 --resultados resultados      # --16x8 para forzar el intento
$P diagnostico_int8.py --pliegue 1 --resultados resultados
# interprete de TFLite Micro (requirements-tflm.txt)
~/venv-tflm313/bin/python tflm_evaluar.py --pliegue 1 --resultados resultados
```

En `resultados/` solo se versionan los JSON. El modelo, los `.tflite` y las predicciones se
regeneran.
