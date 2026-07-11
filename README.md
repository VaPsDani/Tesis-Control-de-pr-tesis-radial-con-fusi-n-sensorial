# Control de prótesis radial con fusión sensorial

## Requisitos

- WSL2 con Ubuntu (recomendado para GPU)
- Miniconda dentro de WSL
- NVIDIA GPU con drivers recientes (para TensorFlow con CUDA)

## Instalación del entorno

```bash
# Desde WSL (Ubuntu)
conda create -n tf python=3.12 -y
conda activate tf
pip install tensorflow[and-cuda]==2.16.1
pip install numpy==1.26.4 pandas scikit-learn matplotlib seaborn scipy
```

## Variables de entorno

TensorFlow necesita encontrar las librerías CUDA:

```bash
export LD_LIBRARY_PATH=/home/tu_usuario/miniconda3/envs/tf/lib/python3.12/site-packages/nvidia/cuda_runtime/lib:/home/tu_usuario/miniconda3/envs/tf/lib/python3.12/site-packages/nvidia/cublas/lib:/home/tu_usuario/miniconda3/envs/tf/lib/python3.12/site-packages/nvidia/cudnn/lib:/home/tu_usuario/miniconda3/envs/tf/lib/python3.12/site-packages/nvidia/cufft/lib:/home/tu_usuario/miniconda3/envs/tf/lib/python3.12/site-packages/nvidia/curand/lib:/home/tu_usuario/miniconda3/envs/tf/lib/python3.12/site-packages/nvidia/cusolver/lib:/home/tu_usuario/miniconda3/envs/tf/lib/python3.12/site-packages/nvidia/cusparse/lib:/home/tu_usuario/miniconda3/envs/tf/lib/python3.12/site-packages/nvidia/nccl/lib:/home/tu_usuario/miniconda3/envs/tf/lib/python3.12/site-packages/nvidia/nvjitlink/lib
```

## Dataset

El dataset NinaPro DB5 debe estar en `Modulo2_Pipeline_DL/NinaPro_DB5/`.
Contiene 30 archivos .mat (10 sujetos × 3 ejercicios).

## Cómo ejecutar

### Verificar GPU

```bash
python -c "import tensorflow as tf; print(tf.config.list_physical_devices('GPU'))"
```

### Entrenar modelo

```bash
cd Modulo2_Pipeline_DL
python ../codigo_simple/entrenamiento_simple.py --mat ./NinaPro_DB5 --epochs 100 --batch_size 32
```

El entrenamiento corre validación cruzada con 5 folds y guarda los resultados en `resultados_preliminares/`.

### Versión simplificada vs completa

La carpeta `codigo_simple/` contiene el mismo pipeline pero sin comentarios y con código más directo. Lo generamos para resumir.

## Archivos del proyecto

```
Modulo2_Pipeline_DL/
  entrenamiento.py        (original, comentado)
  modelo.py               (original, comentado)
  preprocesamiento.py     (original, comentado)
  requirements.txt
  NinaPro_DB5/            (dataset, no incluido en git)
codigo_simple/
  entrenamiento_simple.py (versión simplificada)
  modelo_simple.py        (versión simplificada)
  preprocesamiento_simple.py (versión simplificada)
```
