# Módulo 2, pipeline de aprendizaje profundo

Preprocesamiento, entrenamiento, validación y exportación del modelo que corre
en el Módulo 3.

## Estructura

| Carpeta | Qué contiene |
|---|---|
| `common/` | Código compartido por todos los experimentos: partición y verificación de fuga, normalización, bucle de entrenamiento, métricas y arquitectura |
| `experimentos/` | Un experimento por carpeta, cada uno con su README y su pregunta |
| `produccion/` | El pipeline que genera el modelo desplegado, sobre datos propios |
| `captura/` | Aplicación de sesión de captura, con `captura_sesion.py` como entrada |
| `herramientas/` | Perfilado de GPU, colas de trabajos y análisis auxiliares |
| `tests/` | Pruebas de las piezas que no deben romperse en silencio |

Los experimentos importan de `common/` con imports planos. Cada script añade a
`sys.path` la raíz del módulo, `common/` y `produccion/`, así que se ejecutan
directamente sin instalar nada ni fijar `PYTHONPATH`.

## Experimentos

| Carpeta | Pregunta que responde |
|---|---|
| `ablacion_imu/` | ¿Aporta la IMU sobre la LMG sola, y cambia eso con el brazo en movimiento? Es la comparación central del trabajo |
| `validacion_preliminar_emg/` | ¿El pipeline funciona, antes de tener datos propios? Validación algorítmica sobre NinaPro DB5 |
| `lmg_wavelength/` | Ventana, canales, longitud de onda y modelos clásicos, sobre el dataset público de LMG |
| `ablacion_fases/` | ¿Qué tramo del gesto conviene que entre al entrenamiento? |
| `optica_espaciador/` | ¿LED verde con espaciador o infrarrojo en contacto? |
| `cuantizacion_int8/` | ¿Cuánta exactitud se pierde al pasar el modelo a INT8 para el ESP32? |

## Entorno

**Un solo entorno para todo** (A29): entrenamiento, validación, estadística y
conversión INT8, con TensorFlow 2.21.0 y Keras 2 (`tf_keras` 2.21.0), con GPU.
Keras 2 porque con Keras 3 la LSTM no se convierte en la operación nativa de
TFLite y la cuantización INT8 falla (`claude/viabilidad-tflite-micro.md`).

WSL2 con Ubuntu, Python 3.12 y una GPU NVIDIA con controladores recientes.

```bash
python3.12 -m venv ~/venv-tesis-221
```

```bash
~/venv-tesis-221/bin/pip install -r Modulo2_Pipeline_DL/requirements.txt
```

```bash
cat Modulo2_Pipeline_DL/herramientas/rutas_cuda_venv.sh >> ~/venv-tesis-221/bin/activate
```

```bash
source ~/venv-tesis-221/bin/activate
```

El tercer paso se hace una sola vez. Agrega al `activate` del entorno las
carpetas de CUDA que instala pip y fija Keras 2. Sin él, TensorFlow no
encuentra `libcusolver.so.11` y entrena en CPU sin avisar más que con un
warning. Comprobación:

```bash
python -c "import tensorflow as tf; print(tf.config.list_physical_devices('GPU'))"
```

Con varios entrenamientos en paralelo sobre la misma GPU hace falta además
`export TF_FORCE_GPU_ALLOW_GROWTH=true`, porque si no el primer proceso reserva
casi toda la VRAM.

Quedan aparte, a propósito:

| Archivo | Para qué |
|---|---|
| `requirements-tflm.txt` | El intérprete de TensorFlow Lite Micro para PC, que exige Python 3.13. Solo verifica la conversión |
| `requirements-captura.txt` | La computadora de captura, sin TensorFlow |
| `requirements-tf216-historico.txt` | Registro del entorno con TF 2.16 y Keras 3 con que salieron los resultados preliminares ya publicados. No se mantiene |

## Qué modelo se despliega (A22)

Se despliega la configuración, A (`solo_lmg`) o B (`lmg_imu`), con **mayor F1
macro fuera de línea**. Ese número es, para cada configuración, la media sobre
los participantes de prueba del F1 macro de 5 clases calculado con todas sus
ventanas de evaluación, las de las dos condiciones juntas, en la corrida mixta
de `experimentos/ablacion_imu` (GroupKFold k = 5 por sujeto). Si las dos medias
coinciden en cuatro decimales, gana la de menos canales.

La regla está en código, no solo aquí: `regla_de_despliegue()` en
`ablacion_imu.py` la aplica y deja el resultado en `regla_de_despliegue` del
JSON de la ablación. Después, `produccion/entrenar_modelo.py --modo final
--composicion <la elegida>` entrena el modelo que se convierte a INT8.

La regla se fijó antes de ver resultados con datos propios. El desempate por
número de canales es una propuesta de la sesión de implementación que el
artículo no menciona.

## Datos

| Dataset | Dónde va | Nota |
|---|---|---|
| NinaPro DB5 | `~/data/NinaPro_DB5/`, 30 archivos .mat | Descarga en https://ninapro.hevs.ch/instructions/DB5.html |
| `lmg_wavelength_dataset` | `~/data/lmg_wavelength_dataset/` | Clonar de New Dexterity |
| Sesiones propias | `Modulo2_Pipeline_DL/sesiones/` | Las escribe la app de captura |

Ninguno se versiona: todos están excluidos por `.gitignore`.

## Pruebas

```bash
python -m pytest Modulo2_Pipeline_DL/tests -q
```

Cubren la verificación de fuga entre sujetos, la normalización y la
construcción del protocolo de captura. Son rápidas y no necesitan GPU ni
datasets.
