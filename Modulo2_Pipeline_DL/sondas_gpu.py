"""
sondas_gpu.py - De donde sale el coste fijo por paso
=====================================================
perfil_entrenamiento.py mostro un paso de ~20 ms a batch 32 que casi no
crece con el batch (128 ventanas cuestan ~27 ms), con la GPU ~60% ociosa
y la CPU tambien ociosa, y que no mejora con steps_per_execution ni con
XLA. Este script separa las dos explicaciones candidatas:

  1. La BiLSTM no usa el kernel cuDNN y se ejecuta como un bucle de 40
     pasos por direccion, con cientos de kernels pequenos por paso.
     -> se mide el paso con el LSTM en modo auto, cuDNN forzado, generico
        forzado, y sin LSTM.

  2. Lanzar cada kernel es caro en este sistema (WSL2 comunica la GPU a
     traves de una capa de paravirtualizacion).
     -> cadenas de 1, 10, 100 y 1000 tanh sobre un tensor pequeno: la
        pendiente es el coste por kernel, casi sin computo. Se compara con
        una multiplicacion de matrices grande, que mide la capacidad bruta
        de la GPU.

Tambien separa forward de backward + optimizador en el modelo real.
Todas las medidas sincronizan con el host en cada iteracion (.numpy()),
igual que train_on_batch, para que el tiempo incluya la ejecucion en GPU.
"""

import argparse
import json
import os
import time

import numpy as np
import tensorflow as tf
from tensorflow.keras import Model, layers
from tensorflow.keras.regularizers import l2

from entrenamiento_cv import LABEL_SMOOTHING, cargar_dataset
from modelo import MecanismoAtencion, construir_modelo

AQUI = os.path.dirname(os.path.abspath(__file__))


def ms_por_iter(fn, n, calentar=10):
    for _ in range(calentar):
        fn()
    t0 = time.perf_counter()
    for _ in range(n):
        fn()
    return 1000 * (time.perf_counter() - t0) / n


def variante(forma, nclases, lstm="auto", atencion=True, reg=1e-4):
    """La misma arquitectura que modelo.construir_modelo, con el LSTM configurable."""
    x_in = layers.Input(shape=forma)
    x = layers.Conv1D(64, 3, padding="same", activation="relu", kernel_regularizer=l2(reg))(x_in)
    x = layers.BatchNormalization()(x)
    x = layers.Conv1D(128, 3, padding="same", activation="relu", kernel_regularizer=l2(reg))(x)
    x = layers.BatchNormalization()(x)
    if lstm != "ninguno":
        uso = {"auto": "auto", "cudnn": True, "generico": False}[lstm]
        x = layers.Bidirectional(layers.LSTM(32, return_sequences=atencion,
                                             kernel_regularizer=l2(reg), use_cudnn=uso))(x)
    if atencion:
        x = MecanismoAtencion(units=64)(x)
    elif lstm == "ninguno":
        x = layers.GlobalAveragePooling1D()(x)
    x = layers.Dense(64, activation="relu", kernel_regularizer=l2(reg))(x)
    x = layers.Dropout(0.5)(x)
    out = layers.Dense(nclases, activation="softmax")(x)
    return Model(x_in, out)


def paso_entrenamiento(m):
    opt = tf.keras.optimizers.Adam(1e-3)
    perdida = tf.keras.losses.CategoricalCrossentropy(label_smoothing=LABEL_SMOOTHING)

    @tf.function
    def paso(x, y):
        with tf.GradientTape() as tape:
            p = m(x, training=True)
            loss = perdida(y, p) + tf.add_n(m.losses)
        g = tape.gradient(loss, m.trainable_variables)
        opt.apply_gradients(zip(g, m.trainable_variables))
        return loss

    @tf.function
    def adelante(x):
        return tf.reduce_sum(m(x, training=True))

    return paso, adelante


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=os.path.expanduser("~/cache_ninapro.npz"))
    ap.add_argument("--mat", default=os.path.expanduser("~/data/NinaPro_DB5"))
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--output", default=os.path.join(AQUI, "resultados_cv", "perfil"))
    args = ap.parse_args()
    os.makedirs(args.output, exist_ok=True)

    X, y, _, _ = cargar_dataset(args.mat, args.cache)
    forma, nclases = X.shape[1:], y.shape[1]
    res = {"forma": list(forma)}
    L = []
    w = L.append

    # ---------- 1. modelo real: forward frente a backward ----------
    w("1. MODELO REAL (construir_modelo): forward frente a paso completo")
    w(f"   {'batch':>6}{'forward ms':>12}{'paso ms':>10}{'backward+Adam':>15}")
    m = construir_modelo(window_size=forma[0], num_features=forma[1], num_clases=nclases)
    paso, adelante = paso_entrenamiento(m)
    for bs in (32, 256):
        with tf.device("/GPU:0"):
            xb, yb = tf.constant(X[:bs]), tf.constant(y[:bs].astype(np.float32))
        f_ms = ms_por_iter(lambda: adelante(xb).numpy(), args.n)
        p_ms = ms_por_iter(lambda: paso(xb, yb).numpy(), args.n)
        res[f"real_bs{bs}"] = dict(forward_ms=f_ms, paso_ms=p_ms)
        w(f"   {bs:>6}{f_ms:12.2f}{p_ms:10.2f}{p_ms - f_ms:15.2f}")
    w("")

    # ---------- 2. variantes del LSTM ----------
    w("2. VARIANTES DE LA ARQUITECTURA (paso completo, ms)")
    w(f"   {'variante':<34}{'bs 32':>9}{'bs 256':>9}{'256/32':>8}")
    for nombre, kw in (("LSTM auto (= produccion)", dict(lstm="auto")),
                       ("LSTM cuDNN forzado", dict(lstm="cudnn")),
                       ("LSTM generico forzado", dict(lstm="generico")),
                       ("sin LSTM (conv + atencion)", dict(lstm="ninguno")),
                       ("BiLSTM sin atencion", dict(lstm="auto", atencion=False))):
        try:
            mv = variante(forma, nclases, **kw)
            pv, _ = paso_entrenamiento(mv)
            t = {}
            for bs in (32, 256):
                with tf.device("/GPU:0"):
                    xb, yb = tf.constant(X[:bs]), tf.constant(y[:bs].astype(np.float32))
                t[bs] = ms_por_iter(lambda: pv(xb, yb).numpy(), args.n)
            res[nombre] = t
            w(f"   {nombre:<34}{t[32]:9.2f}{t[256]:9.2f}{t[256]/t[32]:8.2f}")
        except Exception as e:
            res[nombre] = {"error": str(e)[:300]}
            w(f"   {nombre:<34}  FALLA: {str(e).splitlines()[0][:70]}")
    w("")

    # ---------- 3. capacidad bruta ----------
    w("3. CAPACIDAD BRUTA DE LA GPU")
    with tf.device("/GPU:0"):
        a = tf.random.normal((2048, 2048))
        b = tf.random.normal((2048, 2048))

    @tf.function
    def mm():
        return tf.reduce_sum(tf.matmul(a, b))

    mm_ms = ms_por_iter(lambda: mm().numpy(), 30)
    gflops = 2 * 2048 ** 3 / (mm_ms / 1000) / 1e9
    res["matmul_2048_ms"], res["gflops"] = mm_ms, gflops
    w(f"   matmul 2048x2048 float32: {mm_ms:.2f} ms  ->  {gflops:.0f} GFLOPS")
    w("")

    # ---------- 4. latencia por kernel ----------
    # Grappler podria fusionar la cadena y falsear la cuenta de kernels.
    tf.config.optimizer.set_experimental_options({"disable_meta_optimizer": True})
    w("4. COSTE DE LANZAR KERNELS (cadena de tanh, grappler desactivado)")
    w(f"   {'kernels':>8}{'tensor (32,40,64) ms':>22}{'tensor (256,40,256) ms':>24}")
    ns = [1, 10, 100, 1000]
    tiempos = {"peq": [], "grande": []}
    for forma_t, clave in (((32, 40, 64), "peq"), ((256, 40, 256), "grande")):
        with tf.device("/GPU:0"):
            xt = tf.random.normal(forma_t)
        for n in ns:
            def hacer(n=n):
                @tf.function
                def cadena(x):
                    for _ in range(n):
                        x = tf.tanh(x)
                    return tf.reduce_sum(x)
                return cadena
            f = hacer()
            reps = 200 if n <= 100 else 30
            tiempos[clave].append(ms_por_iter(lambda: f(xt).numpy(), reps, calentar=3))
    for i, n in enumerate(ns):
        w(f"   {n:>8}{tiempos['peq'][i]:22.3f}{tiempos['grande'][i]:24.3f}")
    pend_p = np.polyfit(ns, tiempos["peq"], 1)[0]
    pend_g = np.polyfit(ns, tiempos["grande"], 1)[0]
    res["ms_por_kernel_tensor_pequeno"], res["ms_por_kernel_tensor_grande"] = pend_p, pend_g
    w(f"   coste marginal por kernel: {pend_p*1000:.1f} us con tensor pequeno, "
      f"{pend_g*1000:.1f} us con tensor 128x mayor")
    w("   Si ambos son parecidos, lo que cuesta es LANZAR el kernel, no calcularlo.")
    w("   Referencia orientativa en Linux nativo con CUDA: ~10-30 us por kernel.")

    texto = "\n".join(L)
    print(texto)
    with open(os.path.join(args.output, "sondas_gpu.txt"), "w", encoding="utf-8") as f:
        f.write(texto + "\n")
    with open(os.path.join(args.output, "sondas_gpu.json"), "w") as f:
        json.dump(res, f, indent=2, default=float)
    print("### SONDAS COMPLETAS")


if __name__ == "__main__":
    main()
