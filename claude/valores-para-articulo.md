# Valores para el artículo (OMG con QRE1113)

Afirmaciones del método del artículo nuevo, cada una con el archivo y la línea
del código de donde sale. Estado de `main` al 2026-11-13, después de la
migración a QRE1113/OMG. La versión de la etapa LMG de este documento está en
el tag `lmg-final-2026-11-13`.

Rutas abreviadas: `M1` es `Modulo1_Adquisicion_Datos` y `M2` es
`Modulo2_Pipeline_DL`.

**Pendiente de medir** marca lo que solo se sabe con la placa armada. Esos
valores no se inventan: se llenan con la salida de `T`, `C` y `X`.

## 1. Adquisición

| Afirmación | Valor | Dónde | Estado |
|---|---|---|---|
| Sensor | 8 módulos QRE1113GR (LED IR de 940 nm y fototransistor en el mismo encapsulado), en contacto con la piel, sin silicona | `M1/config.h:52-61` | Código listo |
| Conversión | ADC interno del ESP32, 12 bits, atenuación de 11 dB, lectura calibrada (`analogReadMilliVolts`) | `M1/config.h:94`, `M1/optica_omg.cpp:13, 40` | Código listo |
| Promedio por lectura | 4 lecturas, descartando la primera tras cambiar de canal | `M1/config.h:96, 100` | **Provisional** |
| Circuito de cada módulo | LED con R1 = 100 Ω a GND, colector con R2 = 47 kΩ a VCC = 3,3 V | `M1/config.h:85-87` | PCB del asesor |
| Pines | OUT de los módulos 1 a 8 en GPIO 36, 39, 34, 35, 32, 33, 25, 26. IR en GPIO 13, 27, 23, 19, 18, 17, 16, 4 | `M1/config.h:78-79` | **Pendiente de confirmar contra el cableado** |
| IMU | MPU6050 por I2C (SDA 21, SCL 22, 400 kHz), ±2 g (16 384 LSB/g), filtro interno DLPF_CFG = 4 (21 Hz, 8,5 ms de retardo) | `M1/config.h:47-49, 148-149` | Código listo. Confirmación en la placa pendiente (línea `[IMU]`) |
| Frecuencia de muestreo | 100 Hz, ciclo de 10 ms contra un reloj fijo | `M1/config.h:136`, `M1/Modulo1_Adquisicion_Datos.ino:260` | Ciclo medido **pendiente** (`T`) |
| Orden de la trama | 1. LED apagados, espera T_OFF_US, lee los 8 (V_apag). 2. LED encendidos a la vez, espera T_ON_US, lee los 8 (V_enc), apaga. 3. IMU | `M1/optica_omg.cpp:44-64` | Código listo |
| Señal óptica | v = V_apag − V_enc en mV, positiva y mayor con más luz. amb = V_apag | `M1/Modulo1_Adquisicion_Datos.ino:72, 77` | Código listo |
| T_ON_US y T_OFF_US | 1000 µs provisionales, a fijar en t99 + 20 % con `C` | `M1/config.h:132-133` | **Pendiente de medir** |
| Capacidad de salida de los LED | GPIO_DRIVE_CAP_2, la misma en los 8, fijada a mano | `M1/config.h:107`, `M1/optica_omg.cpp:25` | Código listo |
| Enlace serie | 921 600 baudios. Línea de ~182 bytes en el peor caso, 18 200 B/s, ~20 % del enlace | `M1/config.h:32-42` | Calculado |

## 2. Formato del CSV

El firmware emite 23 campos por línea:

```
timestamp_ms, v1..v8, ax, ay, az, gx, gy, gz, amb1..amb8
```

La app de captura agrega las columnas del protocolo: `subject_id`,
`repetition_id`, `label`, `bloque_tipo`, `en_margen`, `es_calibracion`,
`condicion_postural`, `id_participante`, `posicion_brazo`, `ts_pc_ms`,
`descartada`, con `amb1..amb8` al final (`M2/captura/adquisicion.py`).

| Qué | Dónde |
|---|---|
| Nombres y orden de los canales, única fuente de verdad | `M2/common/canales.py:14-23` |
| `static_assert` de 8 + 3 canales al modelo y 22 señales al CSV | `M1/config.h:160-164` |
| Rechazo de los CSV del firmware LMG (5 canales, o versión sin QRE) | `M2/produccion/preprocesamiento.py:142` |

## 3. Preprocesamiento y modelo

| Afirmación | Valor | Dónde |
|---|---|---|
| Canales al modelo | Configuración A (`solo_omg`) = 8 ópticos. B (`omg_imu`) = 8 ópticos + ax, ay, az = 11 | `M2/produccion/preprocesamiento.py:96, 125-127` |
| Normalización | Ópticos en z con media y desviación del bloque de calibración. Acelerómetro en g menos la media, sin dividir | `M2/produccion/preprocesamiento.py:231-248` |
| Ventana | 200 ms (20 muestras), paso 20 ms (2 muestras) | `M2/produccion/preprocesamiento.py:131-132` |
| Etiquetado | Fases versión 4, variante `dinamica_meseta` | `M2/produccion/fases.py:115` |
| Parámetros | **76 933** con 8 canales y **77 509** con 11. Solo la primera Conv1D depende de C (3 × C × 64 + 64) | `M2/tests/test_modelo.py`, `M2/ARQUITECTURA.md` |
| Arquitectura | Conv1D 64 y Conv1D 128 (núcleo 3, ReLU, BN), BiLSTM 32 + 32, atención aditiva, Dense 64, Dropout 0,5, softmax 5 | `M2/common/modelo.py:130-164` |

## 4. Entrenamiento

| Hiperparámetro | Valor | Dónde |
|---|---|---|
| Optimizador | Adam, tasa inicial 1e-3 | `M2/common/modelo.py:174`, `--lr` |
| Lote | 32 | `M2/experimentos/ablacion_imu/ablacion_imu.py:534`, `M2/produccion/entrenar_modelo.py:169` |
| Épocas máximas | 100 | `M2/experimentos/ablacion_imu/ablacion_imu.py:533` |
| Pérdida | Entropía cruzada categórica con suavizado de etiquetas 0,1 | `M2/common/entrenamiento.py:37` |
| Pesos por clase | total / (5 × ventanas de la clase), con las ventanas de entrenamiento del pliegue | `M2/common/entrenamiento.py:45-56` |
| Regularización | L2 1e-4, dropout 0,5 | `M2/common/modelo.py:109-110` |
| Parada temprana | `val_loss`, paciencia 15, desde la época 10, restaura los mejores pesos | `M2/common/entrenamiento.py:176-179` |
| ReduceLROnPlateau | factor 0,5, paciencia 7, mínimo 1e-6 | `M2/common/entrenamiento.py:200-204` |
| Aumento de datos | Ruido gaussiano 0,02, escala uniforme 0,95 a 1,05, desplazamiento circular de −1, 0 o +1 muestras | `M2/common/entrenamiento.py:68-73` |
| Barajado | Búfer de 1024 | `M2/common/entrenamiento.py:224` |

## 5. Protocolo

| Afirmación | Valor | Dónde |
|---|---|---|
| Calibración en reposo | 15 s | `M2/captura/config_captura.py:44` |
| Repetición | 3 s de preparación + 10 s de contracción + 8 s de reposo | `M2/captura/config_captura.py:45-47` |
| Gestos | 4 activos × 6 repeticiones, 3 estáticas y 3 dinámicas | `M2/captura/config_captura.py:84, 98` |
| Reposo en movimiento | 3 por sesión | `M2/captura/config_captura.py:110` |
| Barra de subida de fuerza | 1 s | `M2/captura/config_captura.py:76` |
| Duración | 15 + (4 × 6 + 3) × 21 = 582 s | `M2/captura/protocolo.py:18` |

## 6. Validación y estadística

| Afirmación | Valor | Dónde |
|---|---|---|
| Partición | GroupKFold k = 5 por participante: 7 de entrenamiento, 1 de validación y 2 de prueba. LOSO como complemento | `M2/common/validacion.py:89`, `M2/experimentos/ablacion_imu/ablacion_imu.py` |
| Confirmatorio | Dos Wilcoxon pareados de dos colas sobre el F1 macro (aporte de la IMU en estática y en dinámica), corrección de Holm, con d_z | `M2/experimentos/ablacion_imu/estadistica.py:85-86, 90, 124, 137` |
| Pérdida INT8 | Diferencia de F1 macro entre flotante e INT8 sobre los mismos datos de prueba, fuera de línea. Umbral de acción 1 punto | `M2/produccion/perdida_cuantizacion.py:60, 112` |

## 7. Pendiente de medir con la placa

| Qué | Cómo | Para qué afirmación |
|---|---|---|
| Tabla de pines | Comparar las líneas `[PINES]` con el cableado | Pines |
| Ciclo real: media, p95 y máximo | `T` | 100 Hz con el ciclo medido |
| V_enc, V_apag, v y banderas por módulo en reposo | `T` | Caracterización |
| t90, t95 y t99 al encender y al apagar | `C` | T_ON_US y T_OFF_US |
| Diafonía entre módulos | `X` | Modo simultáneo o secuencial |
| Línea `[IMU]` | `T` o `K` | Configuración del MPU6050 |
| ΔS, σ, ΔS/σ y los demás de la tabla 6.1 | `caracterizacion_qre/capturar.py` y `analizar.py` | Caracterización preliminar |
| Pérdida INT8 con datos reales | `perdida_cuantizacion.py` sobre la ablación | Degradación del modelo |

## 8. Versiones

| Componente | Versión |
|---|---|
| Firmware de adquisición | `M1-2026.11.13-QRE` (`M1/config.h:20`) |
| Núcleo esp32 de Espressif para Arduino | 3.3.12 |
| Arduino IDE | 2.3.10 |
| arduino-cli (el que trae el IDE) | 1.5.1 |
| Librerías del firmware | Solo las del núcleo: `Wire`, `Preferences` y `driver/gpio.h`. El MPU6050 con driver propio (`M1/sensor_imu.cpp`) |
| Python | 3.12.14 |
| TensorFlow y tf_keras | 2.21.0 y 2.21.0 |
| NumPy, SciPy | 2.5.3, 1.18.1 |
| scikit-learn, statsmodels | 1.9.1, 0.15.0 |
| pandas, matplotlib | 3.0.6, 3.11.2 |
| CUDA, cuDNN | TF compilado con 12.5.1, ejecución 12.9.79. cuDNN 9.27.0 |

El firmware compila sin advertencias con `--warnings all`.
