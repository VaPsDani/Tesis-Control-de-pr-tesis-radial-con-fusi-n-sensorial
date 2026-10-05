# --- tesis: rutas de CUDA y Keras 2 (agregado por herramientas/rutas_cuda_venv.sh) ---
# Se anade al final de bin/activate del entorno de TF 2.21:
#   cat Modulo2_Pipeline_DL/herramientas/rutas_cuda_venv.sh >> ~/venv-tesis-221/bin/activate
#
# Por que: tensorflow[and-cuda] instala las librerias de CUDA como paquetes
# de pip, dentro del entorno, pero TF 2.21 no las encuentra todas: sin esto
# falla al abrir libcusolver.so.11 y entrena en CPU sin avisar mas que con
# un warning. Se anaden las carpetas nvidia/*/lib del propio entorno.
_tesis_nv=$(ls -d "$VIRTUAL_ENV"/lib/python3*/site-packages/nvidia/*/lib 2>/dev/null | paste -sd: -)
if [ -n "$_tesis_nv" ]; then
    export LD_LIBRARY_PATH="${_tesis_nv}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
unset _tesis_nv
# Todo el proyecto entrena con Keras 2 (tf_keras), que es con lo que la
# LSTM cuantiza a INT8. keras_legado.activar() lo fija tambien en cada
# script, esto es para que un 'import tensorflow' suelto no use Keras 3.
export TF_USE_LEGACY_KERAS=1
# --- fin tesis ---
