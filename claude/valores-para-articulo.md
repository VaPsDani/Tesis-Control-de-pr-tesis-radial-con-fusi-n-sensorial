# Valores para el artículo

Verificación del código contra las afirmaciones A1 a A30 de la sección de
método. Estado de `main` al 2026-10-05, después de las Etapas 0 a 5.

Rutas abreviadas: `M1` es `Modulo1_Adquisicion_Datos`, `M2` es
`Modulo2_Pipeline_DL` y `M3` es `Modulo3_Inferencia_Control`.

**Todavía no hay datos reales.** Los conteos de ventanas y el reporte por
repetición de este documento salen de 10 sesiones sintéticas. Sirven para
mostrar el formato y comprobar que el código funciona, no para el artículo.
Las cifras de resultados (F1, pérdida INT8, latencia, MAE de fuerza, prueba
en línea, banco) no existen todavía y no aparecen aquí.

## 1. Tabla A1 a A30

| # | Cumple | Dónde | Nota |
|---|---|---|---|
| A1 | Sí | `M2/captura/interfaz.py:639` | El campo `brazo_registrado` viene en "derecho". Que sean diestros lo controla el reclutamiento y queda en `mano_dominante`. |
| A2 | Sí | `M2/captura/config_captura.py:120`, `M2/captura/interfaz.py:352` | En las posiciones dinámicas la app dice "sin girar el antebrazo" (`config_captura.py:156`), porque con el brazo al costado la palma no mira hacia abajo. |
| A3 | Sí | `M2/captura/config_captura.py:44-47, 76, 84`, `M2/captura/interfaz.py:360` | 15 s, 3 + 10 + 8 s, 6 repeticiones, barra de 1 s, "con fuerza moderada". |
| A4 | Sí | `M2/captura/config_captura.py:98`, `M2/captura/protocolo.py:265, 296` | Orden sorteado con semilla `subject_id`. |
| A5 | Parcial | `M2/captura/protocolo.py:233, 362`, `M2/captura/interfaz.py:351` | El punto de partida rota entre repeticiones. Ver la sección 5. |
| A6 | Sí | `M2/captura/protocolo.py:129, 437` | `bloque_tipo = reposo_dinamico`, etiqueta Rest, uno en cada tercio de la sesión. La sesión dura 582 s (9.7 min). |
| A7 | Sí | `M2/captura/interfaz.py:639-643` | Edad, sexo, mano dominante, brazo, longitud y circunferencia del antebrazo, posición del brazalete, punto de cierre de la correa y observaciones. |
| A8 | Sí | `M2/produccion/preprocesamiento.py:158, 187-204`, `M3/calibracion.h:36` | Igual en Python y en el firmware. |
| A9 | Sí | `M2/produccion/preprocesamiento.py:193-203`, `M3/calibracion.h:42`, `M1/config.h:149` | g menos la media de calibración, sin dividir. ±2 g, 16384 LSB/g. |
| A10 | Sí | `M2/produccion/preprocesamiento.py:173, 218` | La calibración solo da media y desviación. |
| A11 | Sí | `M2/produccion/preprocesamiento.py:121-122` | 20 muestras, paso 2, a 100 Hz. |
| A12 | Sí, con la base dinámica cambiada | `M2/produccion/fases.py:115, 142-168`, `M2/produccion/preprocesamiento.py:207-224`, `M2/produccion/anotar_fases.py:143` | Detector versión 4. La línea base de las dinámicas es el final de la preparación. Ver la sección 5. |
| A13 | Sí | `M2/common/entrenamiento.py:56, 212` | Pesos calculados solo con las ventanas de entrenamiento de cada pliegue, pasados como `sample_weight`. Activados en ablación (`ablacion_imu.py:246, 276, 296`) y producción (`entrenar_modelo.py:94, 147`). |
| A14 | Sí | `M2/common/validacion.py:35`, `M2/common/entrenamiento.py:141, 179`, `M2/experimentos/ablacion_imu/ablacion_imu.py:223`, `M2/produccion/entrenar_modelo.py:163` | 7 + 1 + 2 con 10 sujetos y k = 5. Un `assert` comprueba en cada pliegue que ningún sujeto de prueba tenga otro rol. LOSO con `--modo loso` y `--loso`. |
| A15 | Parcial | `M2/common/modelo.py:172-175`, `M2/common/entrenamiento.py:168` | Adam y entropía cruzada categórica, con suavizado de etiquetas 0.1. Ver la sección 5. |
| A16 | Sí | `M2/produccion/preprocesamiento.py:115-117` | Mismas ventanas, etiquetas y particiones, solo cambian las columnas. |
| A17 | Sí | `M2/experimentos/ablacion_imu/ablacion_imu.py:39, 234` | Modo mixto evaluado por condición, y modo `estatica_a_dinamica`. |
| A18 | Sí | `M2/experimentos/ablacion_imu/datos.py:39-42` | La ablación llama a `preparar_sesiones` de producción. No tiene ventaneo propio. |
| A19 | Sí | `M2/common/metricas.py:47-58` | Exactitud = diagonal / total. Las 5 clases fijas. Precisión, recall y F1 por clase y macro. |
| A20 | Sí | `M2/common/metricas.py:83`, `M2/experimentos/ablacion_imu/estadistica.py:63, 133, 198, 343` | Wilcoxon y d_z en cada contraste. |
| A21 | Sí | `M2/produccion/perdida_cuantizacion.py:54, 106` | Diferencia de F1 macro por pliegue sobre los mismos sujetos de prueba. Valor pendiente de datos reales. |
| A22 | Sí, con un desempate añadido | `M2/experimentos/ablacion_imu/ablacion_imu.py:493-515` | Si empatan a 4 decimales, gana la de menos canales. Ver la sección 5. |
| A23 | Sí | `M2/produccion/convertir_tflite.py:78, 291-297`, `M2/produccion/entrenar_modelo.py:150` | 1000 ventanas al azar, con semilla, solo de los sujetos de entrenamiento guardados con el modelo. |
| A24 | Sí | `M3/config.h:340-341`, `M3/Modulo3_Inferencia_Control.ino:732-735` | Núcleo 0 adquiere cada 10 ms. Núcleo 1 infiere. Ver la sección 5. |
| A25 | Sí | `M3/Modulo3_Inferencia_Control.ino:461-462`, `M3/control_servos.h:27`, `M3/config.h:292, 477-480` | Tabla en la sección 4. |
| A26 | Sí, con un matiz | `M3/Modulo3_Inferencia_Control.ino:98-108, 466, 501` | Comando `L`. Ver la sección 5. Valores pendientes de la placa. |
| A27 | Sí | `M3/Modulo3_Inferencia_Control.ino:549`, `M2/produccion/calibrar_fsr.py:46, 58, 94` | Comando `F`, ajuste lineal y potencial, MAE en newtons. Ver la sección 5. Valores pendientes de medir. |
| A28 | Sí | `M2/produccion/prueba_en_linea.py:58, 65, 81`, `M2/produccion/planilla_agarres.csv` | El modelo de cada participante se entrena con `entrenar_modelo.py --modo final --excluir <id>`. |
| A29 | Sí, con un matiz | `M2/requirements.txt:1, 30` | Un solo entorno para todo lo que dice A29. Ver la sección 5. |
| A30 | Parcial | `M2/banco_modulos/banco.py:84, 92, 147, 276, 597, 675`, `M2/banco_modulos/parametros_banco.json` | Φe en lugar de Φv, y corriente media por PWM. Ver la sección 5. |

## 2. Acelerómetro (MPU6050)

| | Valor | Dónde |
|---|---|---|
| Rango | ±2 g (`AFS_SEL = 0`) | `M1/config.h:149` |
| Sensibilidad | 16384 LSB/g | `M1/config.h:149` |
| Filtro paso bajo interno | `DLPF_CFG = 4`: 21 Hz en el acelerómetro con 8.5 ms de retardo, 20 Hz en el giroscopio con 8.3 ms | `M1/config.h:148` |
| Comprobación | El firmware relee los registros del chip y no arranca si no coinciden | `M1/sensor_imu.cpp:27-32` |

Los Módulos 1 y 3 lo configuran igual. **Falta la confirmación en la
placa:** la línea que tiene que salir al pulsar `T` es
`[IMU] CONFIG=0x04 (DLPF_CFG=4) GYRO_CONFIG=0x00 ACCEL_CONFIG=0x00 (AFS_SEL=0) OK`.

El retardo de 8.5 ms es menor que una muestra a 100 Hz.

## 3. Ventanas por clase y reporte por repetición

**Datos sintéticos, 10 participantes.** Salen de
`experimentos/ablacion_imu/datos.py` y de
`produccion/reporte_preprocesamiento.py`, con el mismo preprocesamiento del
modelo (fases versión 4). Con el piloto real se corre así:

```bash
python Modulo2_Pipeline_DL/produccion/reporte_preprocesamiento.py sesiones/s00_*.csv --salida informes/
```

### Ventanas por clase

| Rest | Pinch | Tripod | Power | Finger_Ext |
|---|---|---|---|---|
| 94 908 | 26 966 | 27 375 | 27 575 | 27 676 |

Del total de Rest, 14 730 ventanas vienen del reposo en movimiento.
Rest / clase activa media = 3.46. Rest / todas las de gesto = 0.87. Ninguna
ventana de preparación entra como gesto.

### Reporte por repetición, resumen

Son 270 repeticiones: 240 de gesto y 30 de reposo en movimiento. Ninguna
quedó marcada, es decir, ninguna tiene menos del 80 % de las ventanas
esperadas ni una reacción mayor que 1.5 s.

| Condición | Repeticiones | Reacción, mediana | Reacción, p90 | Ventanas, mediana | % esperadas, mínimo | Anticipación | IMU no confirma |
|---|---|---|---|---|---|---|---|
| Estática | 120 | 685 ms | 831 ms | 456.5 | 90.2 % | 0 % | 82.5 % |
| Dinámica | 120 | 670 ms | 872 ms | 457 | 89.2 % | 0 % | 69.2 % |

Las ventanas esperadas son 491, las de un bloque de 10 s entero. "IMU no
confirma" es informativo, y con datos sintéticos su valor no dice nada.

### Reporte por repetición, muestra (participante S10)

| Gesto | Condición | Rep | Reacción | Ventanas | % esperadas | Anticipación | IMU no confirma |
|---|---|---|---|---|---|---|---|
| Pinch | dinámica | 1 | 1060 ms | 438 | 89.2 | no | no |
| Tripod | estática | 1 | 820 ms | 450 | 91.6 | no | no |
| Finger_Ext | dinámica | 1 | 450 ms | 468 | 95.3 | no | sí |
| Rest_mov | dinámica | 1 | no aplica | 491 | 100.0 | no | no |
| Power | estática | 3 | 630 ms | 459 | 93.5 | no | sí |

### Rango de los canales normalizados

| | LMG en z | Acelerómetro en g |
|---|---|---|
| Reposo, p1 a p99 | -2.3 a 3.8 | -1.0 a 1.0 |
| Gesto, p1 a p99 | 2.6 a 15.6 | -1.0 a 1.0 |
| Máximo absoluto | 19.4 | 1.08 |

La razón de unas 18 veces importa para la escala única de la entrada INT8.
El valor real lo da el piloto. Regla acordada: si la pérdida INT8 de
`lmg_imu` supera 1 punto de F1 macro, se aplica una ganancia fija al
acelerómetro en Python y en el firmware a la vez, y se declara el factor.

## 4. Acción de la mano por clase (A25)

| Clase | Acción | Dedos con FSR activo |
|---|---|---|
| Reposo | Mantiene la posición actual | ninguno |
| Extensión | Abre los cinco dedos a 0° | ninguno |
| Pinza | Pulgar e índice avanzan hacia 180° y 120° | pulgar e índice |
| Trípode | Pulgar, índice y medio hacia 180°, 150° y 120° | pulgar, índice y medio |
| Puño | Los cinco hacia 180°, 170°, 170°, 150° y 140° | los cinco |

En pinza y trípode, los dedos que no participan van a 25°, una flexión
leve de reposo (`M3/control_servos.cpp:23-25`). Cada dedo avanza por rampa
a 180°/s, un paso de 3.6° cada 20 ms, y se
detiene al pasar el umbral de su FSR, que se revisa cada 10 ms. Umbrales:
410 mV en pulgar e índice, 372 mV en medio, anular y meñique.

Los comandos del operador `S` (detener), `A` (autocalibrar) y la señal
háptica de error de calibración sí llevan la mano a una postura fija de
reposo (25°). No son acciones de clase. La señal háptica de error de
calibración da pulsos breves de flexión y la mano vuelve a donde estaba,
también en Reposo (`M3/control_servos.cpp`, `pulsoHaptico`).

## 5. Lo que el artículo dice y el código hace de otra forma

Cada punto lleva una redacción propuesta.

**A5. "En un solo sentido".** El recorrido nunca vuelve atrás, pero el
punto de partida rota entre repeticiones (`protocolo.py:362`). Con un orden
fijo, "abajo" caería siempre en el primer tramo y "arriba" en el último, con
más fatiga, y posición y momento quedarían confundidos.

> "Durante la contracción el brazo recorre tres posiciones, unos 3,3 s
> cada una, sin volver atrás, con un punto de partida que rota entre
> repeticiones."

**A12. Línea base de las dinámicas.** Con la base del reposo previo, el
57 % de las dinámicas sintéticas daba un inicio falso antes de la
indicación, porque el cambio de postura en la preparación ya mueve la señal
óptica.

> "El inicio se detecta contra una línea base que, en las repeticiones
> estáticas, son los 2 s finales del reposo previo sin su último segundo y,
> en las dinámicas, el último segundo de la preparación, con el brazo ya en
> la primera posición y la mano relajada y con la búsqueda desde la
> indicación. El fin de la relajación se detecta en ambas condiciones
> contra los 2 s finales del propio reposo sin su último segundo, con el
> antebrazo ya sobre la mesa."

**A15. Suavizado de etiquetas.**

> "Optimizador Adam y entropía cruzada categórica con suavizado de
> etiquetas de 0,1."

**A22. Desempate.**

> "El modelo desplegado es la configuración con mayor F1 macro fuera de
> línea. Si empatan, la de menos canales."

**A24. Dónde se preprocesa.** Lo que dice el artículo se cumple. Para
precisarlo: la normalización y el armado de la ventana corren en el mismo
núcleo que la adquisición.

> "La adquisición, la normalización y el armado de la ventana corren en un
> núcleo del ESP32 cada 10 ms, y la inferencia en el otro."

**A26. Punto final de la latencia.** En la medición, la orden se escribe al
PCA9685 en el mismo momento en que se lee el resultado. En uso normal sale
en el siguiente paso de la rampa, hasta 20 ms después.

> "La latencia se midió con marcas de tiempo del ESP32 desde el cierre de
> la ventana hasta la escritura de la orden en el PCA9685, sobre 1000
> inferencias consecutivas. En operación normal la orden espera además
> hasta 20 ms al siguiente paso de la rampa de los servos."

**A27. Consigna en newtons.** El firmware detiene cada dedo con un umbral
de lectura en mV. Los newtons se obtienen después con la curva de cada
sensor.

> "La consigna de cada dedo es su umbral de lectura expresado en newtons
> con la curva de su sensor. El error es la diferencia entre la fuerza al
> detenerse y esa consigna."

**A29. Verificación con TFLite Micro.** Todo lo que lista A29 corre en un
solo entorno. Aparte, y solo para verificar en PC que el modelo INT8 corre
con los núcleos de TFLite Micro, hay un entorno con Python 3.13, porque el
paquete `tflite-micro` solo existe para esa versión. Si el artículo
menciona esa verificación:

> "La compatibilidad del modelo INT8 con TFLite Micro se verificó en PC con
> el intérprete oficial (tflite-micro, Python 3.13)."

**A30. Φv, corriente y ΔS.** Φv es flujo luminoso, ponderado por la
sensibilidad del ojo, que a 940 nm es casi cero. Lo que tiene sentido es el
flujo radiante Φe en mW. Los 13 mA son corriente media: el LED va por GPIO
y 100 Ω, con unos 18 mA de pico, y el PWM a 100 kHz lo promedia porque el
OPT101 responde hasta unos 14 kHz.

> "Las seis variantes se midieron con una corriente media del LED de
> 13 mA por PWM, con el ciclo de trabajo de cada tipo de LED fijado a
> partir de su corriente al 100 % medida con multímetro. Índice
> I = |ΔS| / (Φe · Rp), en mV/mA, con Φe el flujo radiante del LED a esa
> corriente, en mW, y Rp la responsividad del fotodiodo a 940 nm, en A/W,
> ambos de las hojas de datos. ΔS es la media, sobre las 7 repeticiones, de
> la diferencia entre cada contracción y el reposo que la precede. Se
> eligió la variante de mayor I de pinza sin saturar. Si otra quedaba a
> menos del 10 %, desempataba el menor artefacto por movimiento."

## 6. Versiones

### Entorno único (A29), `~/venv-tesis-221`

| | Versión |
|---|---|
| Python | 3.12.14 |
| TensorFlow | 2.21.0 |
| tf_keras | 2.21.0 |
| NumPy | 2.5.3 |
| SciPy | 1.18.1 |
| scikit-learn | 1.9.1 |
| statsmodels | 0.15.0 |
| pandas | 3.0.6 |
| matplotlib | 3.11.2 |
| CUDA | TensorFlow compilado con 12.5.1, librerías de ejecución 12.9.79 |
| cuDNN | 9.27.0 |
| Controlador NVIDIA | 616.64, RTX 4060, bajo WSL2 |

Fuente: `M2/requirements.txt` y las versiones leídas del entorno.

### Otros entornos

| Entorno | Para qué | Versiones |
|---|---|---|
| `~/venv-tflm313` | Verificar en PC el modelo INT8 con TFLite Micro | Python 3.13.15, tflite-micro 0.dev20260923231500, numpy 2.5.3 |
| PC de captura | App de captura | pyserial 3.5, numpy 1.26.4, pandas 3.0.5, matplotlib 3.11.1 (`M2/requirements-captura.txt`). La versión de Python de esa PC no está registrada. |
| Histórico | Solo como registro de los resultados preliminares ya publicados | `M2/requirements-tf216-historico.txt`, TensorFlow 2.16 |

### Firmware

| | Versión |
|---|---|
| Firmware de adquisición | `M1-2026.10.05` (`M1/config.h:23`) |
| Firmware de control | `M3-2026.10.05` (`M3/config.h:40`) |
| Núcleo ESP32 de Espressif para Arduino | 3.3.11, compilador esp-x32 2601 |
| Arduino IDE | **Sin dato.** No está en esta PC. Pendiente de la PC donde compilas. |
| Adafruit ADS1X15 | 2.6.2 |
| Adafruit BusIO | 1.17.4 (dependencia de la anterior) |
| Adafruit PWM Servo Driver (PCA9685) | 3.0.3 |
| Chirale_TensorFLowLite | 2.0.0 |
| MPU6050 | Sin librería. Driver propio sobre `Wire` (`M1/sensor_imu.cpp`) |

`TensorFlowLite_ESP32` 1.0.0 está instalada en la carpeta de librerías,
pero el firmware no la incluye.

## 7. Pendiente

| Qué | Quién |
|---|---|
| Versión del Arduino IDE | tú |
| Línea `[IMU]` de la placa | tú |
| Compilar los Módulos 1 y 3 completos | tú, en la universidad |
| Salida de `L` (latencia) | tú, con la placa |
| Corriente al 100 % con `W1`, un LED de cada tipo | tú, y yo corro el subcomando `duty` |
| Φe de cada LED y Rp del OPT101 | tú, de las hojas de datos |
| Curvas de los FSR y MAE en newtons | tú mides, `calibrar_fsr.py` calcula |
| Piloto real, conteos y reporte por repetición | después de capturar |
| Corrida completa y pérdida INT8 | `herramientas/corrida_completa.sh` con datos reales |
