"""
concurrencia_gpu.py - Cuanto rinde compartir la GPU entre entrenamientos
=========================================================================
El perfil mostro la GPU ociosa ~63% del tiempo y un uso de VRAM de 95 MB
por entrenamiento. Si varios entrenamientos comparten la GPU sin frenarse
entre si, se reparte el tiempo de pared sin cambiar ningun resultado: cada
proceso hace exactamente la misma matematica.

Cada proceso reproduce el entrenamiento real (pipeline con augmentation,
batch 32, mismos callbacks no hacen falta aqui), calienta, espera una senal
comun y cronometra el mismo numero de pasos. Lanzar con concurrencia_gpu.sh.
"""

# Rutas del Modulo 2 tras la reorganizacion: common/ tiene el codigo
# compartido por todos los experimentos y produccion/ el pipeline del
# modelo que se despliega.
import os as _os
import sys as _sys
_M2 = _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                     ".."))
for _d in (_M2, _os.path.join(_M2, "common"), _os.path.join(_M2, "produccion"),
           _os.path.join(_M2, "experimentos", "validacion_preliminar_emg")):
    if _d not in _sys.path:
        _sys.path.insert(0, _d)


import os
import sys
import time

import numpy as np

os.environ.setdefault("TF_FORCE_GPU_ALLOW_GROWTH", "true")
import tensorflow as tf  # noqa: E402

from entrenamiento import (LABEL_SMOOTHING, augmentar_muestra,  # noqa: E402
                           fijar_semilla)
from validar_pipeline import cargar_dataset  # noqa: E402
from modelo import compilar_modelo, construir_modelo  # noqa: E402

bandera, pasos, idx = sys.argv[1], int(sys.argv[2]), sys.argv[3]
X, y, _, _ = cargar_dataset(os.path.expanduser("~/data/NinaPro_DB5"),
                            os.path.expanduser("~/cache_ninapro.npz"))
X, y = X[:40000], y[:40000]
fijar_semilla(42, 0)
m = compilar_modelo(construir_modelo(window_size=X.shape[1], num_features=X.shape[2],
                                     num_clases=y.shape[1]),
                    lr=1e-3, label_smoothing=LABEL_SMOOTHING)
ds = (tf.data.Dataset.from_tensor_slices((X, y))
      .map(augmentar_muestra, num_parallel_calls=tf.data.AUTOTUNE)
      .shuffle(1024).batch(32).repeat().prefetch(tf.data.AUTOTUNE))
m.fit(ds, steps_per_epoch=100, epochs=1, verbose=0)          # calentamiento
print(f"LISTO {idx}", flush=True)
while not os.path.exists(bandera):
    time.sleep(0.05)
t0 = time.perf_counter()
m.fit(ds, steps_per_epoch=pasos, epochs=1, verbose=0)
dt = time.perf_counter() - t0
with open(f"/proc/{os.getpid()}/status") as f:
    rss = next(int(l.split()[1]) for l in f if l.startswith("VmRSS")) / 1024
mem = tf.config.experimental.get_memory_info("GPU:0")["peak"] / 2**20
print(f"RESULTADO {idx} ms_paso={1000*dt/pasos:.2f} rss_mb={rss:.0f} vram_pico_mb={mem:.0f}",
      flush=True)
