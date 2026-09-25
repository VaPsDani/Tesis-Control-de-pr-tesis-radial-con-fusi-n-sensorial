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

## Entorno

Hay dos entornos, y cada resultado se reproduce en el suyo.

| Entorno | Para qué | Keras |
|---|---|---|
| `~/venv-tflite-viab`, `requirements-produccion.txt` (versiones exactas) | **Desde 2026-09-25:** todo entrenamiento nuevo de producción y de ablación con datos propios, y la conversión a TFLite INT8 | **Keras 2 (`tf_keras`)**, forzado por `common/keras_legado.py` |
| `~/venv-tesis`, `requirements.txt` | La validación preliminar sobre NinaPro y los análisis del dataset público de LMG, tal como se obtuvieron | Keras 3 |

El entorno de producción usa Keras 2 porque con Keras 3 la LSTM no se convierte en la operación
nativa de TFLite y la cuantización INT8 falla. Así, el modelo que se evalúa es el mismo que se
despliega (`claude/viabilidad-tflite-micro.md`). Por ahora es solo CPU.

```bash
python3.12 -m venv ~/venv-tflite-viab
~/venv-tflite-viab/bin/pip install -r Modulo2_Pipeline_DL/requirements-produccion.txt
```

`requirements-tflm.txt` describe un tercer entorno, solo de validación (Python 3.13), con el
intérprete oficial de TensorFlow Lite Micro para PC.

### Entorno de la validación preliminar (venv-tesis)

WSL2 con Ubuntu, Python 3.12 y una GPU NVIDIA con controladores recientes.

```bash
python -m venv ~/venv-tesis
source ~/venv-tesis/bin/activate
pip install -r Modulo2_Pipeline_DL/requirements.txt
```

TensorFlow necesita encontrar las librerías CUDA del propio entorno. Conviene
dejarlo en un archivo y hacerle `source` en cada sesión.

```bash
V=~/venv-tesis/lib/python3.12/site-packages/nvidia
export LD_LIBRARY_PATH=$V/cuda_runtime/lib:$V/cublas/lib:$V/cudnn/lib:$V/cufft/lib:$V/curand/lib:$V/cusolver/lib:$V/cusparse/lib:$V/nccl/lib:$V/nvjitlink/lib
```

Con varios entrenamientos en paralelo sobre la misma GPU hace falta además
esto, porque si no el primer proceso reserva casi toda la VRAM.

```bash
export TF_FORCE_GPU_ALLOW_GROWTH=true
```

Comprobación de que la GPU se ve.

```bash
python -c "import tensorflow as tf; print(tf.config.list_physical_devices('GPU'))"
```

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
