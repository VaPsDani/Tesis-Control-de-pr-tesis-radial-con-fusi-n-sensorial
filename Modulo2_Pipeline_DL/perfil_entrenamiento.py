"""
perfil_entrenamiento.py - Donde se va el tiempo de un pliegue
==============================================================
Pregunta: con 38% de utilizacion de GPU a batch 32, la GPU es el cuello
de botella? Si el computo de GPU es menos de la mitad del tiempo, mudar a
una GPU mas potente no acelera casi nada y conviene optimizar el pipeline.

QUE SE MIDE
  Fase 1, el pliegue real: el mismo entrenamiento que entrenamiento_cv.py
  (normalizacion 'sujeto', validacion interna, mismos callbacks) con
  cronometro POR EPOCA: entrenamiento, validacion y callbacks.

  No se cronometra por batch a proposito: un callback con ganchos por
  batch obliga a Keras a volver a Python en cada paso y cambia justo lo
  que se quiere medir. El desglose por paso sale de la fase 2.

  Fase 2, bancos de prueba aislados con el mismo modelo:
    pipeline      el tf.data real (augmentation incluida) sin modelo
    fit_trivial   el mismo bucle de fit con una entrada ya en memoria y sin
                  augmentation: la diferencia con el fit real es el coste de
                  la carga de datos dentro del entrenamiento
    gpu_bsN       train_on_batch con el batch ya en la GPU: forward +
                  backward + optimizador, sin carga ni copia host->GPU.
                  Con varios N, la ordenada en el origen de ms/paso frente
                  al batch es el coste FIJO por paso, independiente del
                  volumen de datos
    host_bs32     lo mismo con el batch en RAM: anade la copia host->GPU

  Fase 3, sondas de optimizacion (informativas, no cambian nada del
  pipeline de produccion):
    spe32         compile(steps_per_execution=32): la misma matematica, 32
                  pasos por llamada, amortiza el coste fijo por paso
    xla           compile(jit_compile=True): fusiona kernels
    sin_auc       sin la metrica AUC, que calcula 200 umbrales por paso

  Muestreo continuo durante todo el proceso:
    nvidia-smi    utilizacion y memoria cada 100 ms; PCIe cada 1 s (dmon)
    /proc         CPU total, nucleos del proceso, hilo mas cargado, paginas
                  de swap y fallos de pagina mayores

  utilization.gpu es la fraccion del intervalo en que habia al menos un
  kernel ejecutandose. Promediada en el tiempo es la fraccion del tiempo
  de pared que la GPU estuvo calculando.

Uso:
  python perfil_entrenamiento.py --mat ~/data/NinaPro_DB5 --cache ~/cache_ninapro.npz
  python perfil_entrenamiento.py --solo_analizar resultados_cv/perfil
"""

import argparse
import json
import multiprocessing as mp
import os
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime

import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
VRAM_TOTAL_MB = 8188


# ============================================================
# MUESTREO DE CPU (proceso aparte, arrancado antes de importar TF)
# ============================================================
def muestreador_cpu(pid, ruta, parar, periodo=0.5):
    tck = os.sysconf("SC_CLK_TCK")

    def cpu_total():
        with open("/proc/stat") as f:
            v = [int(x) for x in f.readline().split()[1:]]
        return sum(v), v[3] + v[4]

    def hilos():
        d = {}
        base = f"/proc/{pid}/task"
        for tid in os.listdir(base):
            try:
                with open(f"{base}/{tid}/stat") as f:
                    s = f.read()
                c = s[s.rfind(")") + 2:].split()
                with open(f"{base}/{tid}/comm") as f:
                    nombre = f.read().strip()
                d[tid] = (int(c[11]) + int(c[12]), nombre)
            except OSError:
                pass
        return d

    def memoria():
        v = {}
        with open("/proc/vmstat") as f:
            for linea in f:
                k, x = linea.split()
                if k in ("pswpin", "pswpout"):
                    v[k] = int(x)
        with open(f"/proc/{pid}/stat") as f:
            s = f.read()
        c = s[s.rfind(")") + 2:].split()
        with open(f"/proc/{pid}/status") as f:
            rss = next(int(l.split()[1]) for l in f if l.startswith("VmRSS"))
        return v["pswpin"], v["pswpout"], int(c[9]), rss

    with open(ruta, "w") as out:
        out.write("t,cpu_total_pct,proc_nucleos,hilo1_nucleos,hilo1,hilo2_nucleos,"
                  "hilo2,hilos_activos,swap_in,swap_out,fallos_mayores,rss_mb\n")
        t_prev = time.time()
        tot_prev, idle_prev = cpu_total()
        h_prev = hilos()
        m_prev = memoria()
        while not parar.is_set():
            time.sleep(periodo)
            try:
                t = time.time()
                tot, idle = cpu_total()
                h = hilos()
                m = memoria()
            except (OSError, StopIteration):
                break
            dt = t - t_prev
            cpu_pct = 100.0 * (1 - (idle - idle_prev) / max(tot - tot_prev, 1))
            uso = sorted(((h[k][0] - h_prev[k][0]) / tck / dt, h[k][1])
                         for k in h if k in h_prev)[::-1]
            proc = sum(u for u, _ in uso)
            h1 = uso[0] if uso else (0.0, "")
            h2 = uso[1] if len(uso) > 1 else (0.0, "")
            activos = sum(1 for u, _ in uso if u > 0.1)
            out.write(f"{t:.3f},{cpu_pct:.1f},{proc:.2f},{h1[0]:.2f},{h1[1]},"
                      f"{h2[0]:.2f},{h2[1]},{activos},{m[0]-m_prev[0]},"
                      f"{m[1]-m_prev[1]},{m[2]-m_prev[2]},{m[3]/1024:.0f}\n")
            out.flush()
            t_prev, tot_prev, idle_prev, h_prev, m_prev = t, tot, idle, h, m


# ============================================================
# FASES 1, 2 Y 3
# ============================================================
def perfilar(args, fases):
    import tensorflow as tf
    from entrenamiento_cv import (LABEL_SMOOTHING, augmentar_muestra,
                                  cargar_dataset, fijar_semilla)
    from modelo import compilar_modelo, construir_modelo
    from normalizacion import normalizar
    from particion import generar_particiones

    @contextmanager
    def fase(nombre, **extra):
        t0 = time.time()
        yield extra
        fases.append(dict(fase=nombre, t0=t0, t1=time.time(), **extra))
        print(f"[FASE] {nombre:<24} {time.time()-t0:8.2f} s", flush=True)

    info = {"gpus": [g.name for g in tf.config.list_physical_devices("GPU")]}

    with fase("carga_dataset"):
        X, y, grupos, sujetos = cargar_dataset(args.mat, args.cache)
    nclases = y.shape[1]

    with fase("particion_normalizacion"):
        parts = generar_particiones(X, y.argmax(axis=1), grupos, sujetos,
                                    agrupamiento="sujeto", n_splits=5)
        tr, te = parts[args.fold]
        X_tr, X_te, y_tr, y_te = X[tr], X[te], y[tr], y[te]
        s_tr, s_te = sujetos[tr], sujetos[te]
        X_tr, X_te, _ = normalizar(X_tr, X_te, s_tr, s_te, y_tr, y_te, modo="sujeto")
        rng = np.random.RandomState(args.seed + 1000 + args.fold)
        gval = sorted(rng.choice(np.unique(s_tr), 1, replace=False).tolist())
        en_val = np.isin(s_tr, gval)
        X_fit, y_fit = X_tr[~en_val], y_tr[~en_val]
        X_mon, y_mon = X_tr[en_val], y_tr[en_val]

    info["forma_ventana"] = list(X.shape[1:])
    info["n_fit"], info["n_val"], info["n_test"] = len(X_fit), len(X_mon), len(X_te)
    info["mb_dataset_total"] = round(X.nbytes / 2**20, 1)
    info["mb_train_fit"] = round(X_fit.nbytes / 2**20, 1)
    info["dtype"] = str(X.dtype)
    bs = args.batch_size
    info["bytes_por_batch"] = int(X_fit[:bs].nbytes + y_fit[:bs].astype(np.float32).nbytes)
    pasos = int(np.ceil(len(X_fit) / bs))
    info["pasos_por_epoca"] = pasos

    def nuevo_modelo(**compile_kw):
        m = construir_modelo(window_size=X_fit.shape[1], num_features=X_fit.shape[2],
                             num_clases=nclases)
        if not compile_kw:
            return compilar_modelo(m, lr=1e-3, label_smoothing=LABEL_SMOOTHING)
        metricas = compile_kw.pop("metrics", ["accuracy", tf.keras.metrics.AUC(name="auc")])
        m.compile(optimizer=tf.keras.optimizers.Adam(learning_rate=1e-3),
                  loss=tf.keras.losses.CategoricalCrossentropy(
                      label_smoothing=LABEL_SMOOTHING),
                  metrics=metricas, **compile_kw)
        return m

    fijar_semilla(args.seed, args.fold)
    with fase("construir_modelo"):
        modelo = nuevo_modelo()
    info["parametros"] = int(modelo.count_params())

    with fase("construir_datasets"):
        train_ds = tf.data.Dataset.from_tensor_slices((X_fit, y_fit))
        train_ds = train_ds.map(augmentar_muestra, num_parallel_calls=tf.data.AUTOTUNE)
        train_ds = train_ds.shuffle(1024).batch(bs).prefetch(tf.data.AUTOTUNE)
        val_ds = tf.data.Dataset.from_tensor_slices((X_mon, y_mon))
        val_ds = val_ds.batch(bs).prefetch(tf.data.AUTOTUNE)

    class Marca(tf.keras.callbacks.Callback):
        """Solo ganchos por epoca: no altera el bucle por batch."""
        def __init__(self, papel, epocas):
            super().__init__()
            self.papel, self.epocas = papel, epocas

        def on_epoch_begin(self, epoch, logs=None):
            if self.papel == "ini":
                self.epocas.append(dict(epoca=epoch + 1, t0=time.time()))

        def on_test_begin(self, logs=None):
            if self.papel == "ini":
                self.epocas[-1]["val_t0"] = time.time()

        def on_test_end(self, logs=None):
            if self.papel == "ini":
                self.epocas[-1]["val_t1"] = time.time()

        def on_epoch_end(self, epoch, logs=None):
            clave = "cb_t0" if self.papel == "ini" else "t1"
            self.epocas[-1][clave] = time.time()

    epocas = []
    callbacks = [
        Marca("ini", epocas),
        tf.keras.callbacks.EarlyStopping(monitor="val_loss", patience=15,
                                         restore_best_weights=True,
                                         start_from_epoch=10, verbose=0),
        tf.keras.callbacks.ReduceLROnPlateau(monitor="val_loss", factor=0.5,
                                             patience=7, min_lr=1e-6, verbose=0),
        Marca("fin", epocas),
    ]

    try:
        tf.config.experimental.reset_memory_stats("GPU:0")
    except Exception:
        pass
    with fase("fit"):
        modelo.fit(train_ds, validation_data=val_ds, epochs=args.epochs,
                   callbacks=callbacks, verbose=0)
    try:
        mem = tf.config.experimental.get_memory_info("GPU:0")
        info["vram_tf_pico_mb"] = round(mem["peak"] / 2**20, 1)
    except Exception as e:
        info["vram_tf_error"] = str(e)

    with fase("evaluate_predict_test"):
        modelo.evaluate(X_te, y_te, verbose=0)
        modelo.predict(X_te, verbose=0)
    info["epocas"] = epocas
    if args.sin_bancos:
        return info

    # ---------- fase 2: bancos de prueba ----------
    bancos = {}
    del modelo
    tf.keras.backend.clear_session()
    fijar_semilla(args.seed, args.fold)
    m2 = nuevo_modelo()
    k = args.pasos_banco

    with fase("banco_pipeline", pasos=pasos):
        n = sum(1 for _ in train_ds)
    bancos["pipeline_ms_batch"] = 1000 * (fases[-1]["t1"] - fases[-1]["t0"]) / n

    n_triv = bs * 256
    triv = (tf.data.Dataset.from_tensor_slices((X_fit[:n_triv], y_fit[:n_triv]))
            .batch(bs, drop_remainder=True).repeat().prefetch(tf.data.AUTOTUNE))

    def banco_fit(nombre, m, pasos_b):
        m.fit(triv, steps_per_epoch=64, epochs=1, verbose=0)          # compilacion
        with fase(nombre, pasos=pasos_b):
            m.fit(triv, steps_per_epoch=pasos_b, epochs=1, verbose=0)
        return 1000 * (fases[-1]["t1"] - fases[-1]["t0"]) / pasos_b

    bancos["fit_trivial_ms_paso"] = banco_fit("banco_fit_trivial", m2, k)

    def banco_paso(nombre, xb, yb, pasos_b):
        for _ in range(20):
            m2.train_on_batch(xb, yb)
        with fase(nombre, pasos=pasos_b):
            for _ in range(pasos_b):
                m2.train_on_batch(xb, yb)
        return 1000 * (fases[-1]["t1"] - fases[-1]["t0"]) / pasos_b

    for b in args.batches_banco:
        xb = X_fit[:b].astype(np.float32)
        yb = y_fit[:b].astype(np.float32)
        with tf.device("/GPU:0"):
            xg, yg = tf.constant(xb), tf.constant(yb)
        bancos[f"gpu_bs{b}_ms_paso"] = banco_paso(f"banco_gpu_bs{b}", xg, yg, k)
        if b == bs:
            bancos[f"host_bs{b}_ms_paso"] = banco_paso(f"banco_host_bs{b}", xb, yb, k)

    # ---------- fase 3: sondas de optimizacion ----------
    k_spe = (k // 32) * 32
    sondas = [
        ("sonda_spe32", dict(steps_per_execution=32)),
        ("sonda_sin_auc", dict(metrics=["accuracy"])),
        ("sonda_xla", dict(jit_compile=True)),
        ("sonda_spe32_xla", dict(steps_per_execution=32, jit_compile=True)),
    ]
    for nombre, kw in sondas:
        tf.keras.backend.clear_session()
        fijar_semilla(args.seed, args.fold)
        try:
            ms = banco_fit(nombre, nuevo_modelo(**kw), k_spe)
            bancos[f"{nombre}_ms_paso"] = ms
        except Exception as e:                       # XLA puede no estar disponible
            bancos[f"{nombre}_error"] = str(e)[:300]
            print(f"[SONDA] {nombre} fallo: {str(e)[:200]}", flush=True)

    info["bancos"] = bancos
    return info


# ============================================================
# ANALISIS
# ============================================================
def _leer_gpu(ruta):
    filas = []
    with open(ruta) as f:
        for linea in f:
            p = [x.strip() for x in linea.split(",")]
            if len(p) < 4:
                continue
            try:
                t = datetime.strptime(p[0], "%Y/%m/%d %H:%M:%S.%f").timestamp()
                filas.append((t, float(p[1]), float(p[2]), float(p[3])))
            except ValueError:
                continue
    return np.array(filas)            # t, util_gpu, util_mem, mem_mb


def _leer_dmon(ruta, fecha):
    """rxpci y txpci de NVML: rx = host->GPU, tx = GPU->host."""
    cols, filas = None, []
    with open(ruta) as f:
        for linea in f:
            if linea.startswith("#"):
                if cols is None and "gpu" in linea:
                    cols = linea.lstrip("#").split()
                continue
            p = linea.split()
            if not cols or len(p) != len(cols):
                continue
            d = dict(zip(cols, p))
            try:
                t = datetime.strptime(f"{fecha} {d['Time']}", "%Y-%m-%d %H:%M:%S").timestamp()
            except (ValueError, KeyError):
                continue
            num = lambda k: float(d[k]) if d.get(k, "-") not in ("-", "") else np.nan  # noqa: E731
            filas.append((t, num("rxpci"), num("txpci")))
    return np.array(filas) if filas else np.zeros((0, 3))


def _media(arr, col, t0, t1):
    if len(arr) == 0:
        return np.nan
    m = (arr[:, 0] >= t0) & (arr[:, 0] <= t1)
    return float(np.nanmean(arr[m, col])) if m.any() else np.nan


def analizar(directorio):
    import pandas as pd

    with open(os.path.join(directorio, "perfil.json")) as f:
        r = json.load(f)
    fases, info, a = r["fases"], r["info"], r["args"]
    F = {f["fase"]: f for f in fases}
    gpu = _leer_gpu(os.path.join(directorio, "gpu_100ms.csv"))
    fecha = datetime.fromtimestamp(fases[0]["t0"]).strftime("%Y-%m-%d")
    pcie = _leer_dmon(os.path.join(directorio, "dmon_1s.csv"), fecha)
    cpu = pd.read_csv(os.path.join(directorio, "cpu_500ms.csv"))
    cpu_a = cpu[["t", "cpu_total_pct", "proc_nucleos", "hilo1_nucleos",
                 "hilos_activos", "swap_in", "swap_out", "fallos_mayores",
                 "rss_mb"]].to_numpy(dtype=float)
    bs = a["batch_size"]
    pasos = info["pasos_por_epoca"]

    L = []
    w = L.append
    w("PERFIL DE UN PLIEGUE - normalizacion 'sujeto', validacion interna")
    w("=" * 76)
    w(f"GPU: {info.get('gpus')}   ventana {info['forma_ventana']} {info['dtype']}   "
      f"parametros {info['parametros']:,}")
    w(f"Ventanas: fit {info['n_fit']}, val {info['n_val']}, test {info['n_test']}   "
      f"pasos/epoca {pasos} (batch {bs})")
    w("")

    # ---- 1. fases ----
    w("1. TIEMPO DE PARED POR FASE Y UTILIZACION MEDIA")
    w(f"   {'fase':<24}{'s':>9}{'% plieg':>9}{'GPU %':>8}{'CPU %':>8}{'nucleos':>9}{'hilo1':>7}")
    t_ini = F["carga_dataset"]["t0"]
    t_fin = F["evaluate_predict_test"]["t1"]
    total = t_fin - t_ini
    for f in fases:
        d = f["t1"] - f["t0"]
        fuera = f["fase"].startswith(("banco", "sonda")) or f["fase"] == "reposo_inicial"
        pct = "" if fuera else f"{100*d/total:.1f}"
        w(f"   {f['fase']:<24}{d:9.1f}{pct:>9}{_media(gpu, 1, f['t0'], f['t1']):8.1f}"
          f"{_media(cpu_a, 1, f['t0'], f['t1']):8.1f}{_media(cpu_a, 2, f['t0'], f['t1']):9.2f}"
          f"{_media(cpu_a, 3, f['t0'], f['t1']):7.2f}")
    gpu_plieg = _media(gpu, 1, t_ini, t_fin)
    gpu_reposo = _media(gpu, 1, F["reposo_inicial"]["t0"], F["reposo_inicial"]["t1"])
    w(f"   {'PLIEGUE COMPLETO':<24}{total:9.1f}{'100.0':>9}{gpu_plieg:8.1f}")
    w(f"   GPU en reposo antes de empezar: {gpu_reposo:.1f}% (escritorio y otros procesos)")
    w("")

    # ---- 2. epocas ----
    ep = pd.DataFrame(info["epocas"])
    ep["total"] = ep.t1 - ep.t0
    ep["entreno"] = ep.val_t0 - ep.t0
    ep["validacion"] = ep.val_t1 - ep.val_t0
    ep["callbacks"] = ep.t1 - ep.cb_t0
    ep["resto"] = ep.total - ep.entreno - ep.validacion - ep.callbacks
    ep["gpu_ent"] = [_media(gpu, 1, x0, x1) for x0, x1 in zip(ep.t0, ep.val_t0)]
    ep["gpu_val"] = [_media(gpu, 1, x0, x1) for x0, x1 in zip(ep.val_t0, ep.val_t1)]
    ep["cpu_pct"] = [_media(cpu_a, 1, x0, x1) for x0, x1 in zip(ep.t0, ep.val_t0)]
    ep["nucleos"] = [_media(cpu_a, 2, x0, x1) for x0, x1 in zip(ep.t0, ep.val_t0)]
    ep["hilo1"] = [_media(cpu_a, 3, x0, x1) for x0, x1 in zip(ep.t0, ep.val_t0)]
    est = ep[ep.epoca >= 2]
    m = est.median(numeric_only=True)
    w(f"2. DESGLOSE POR EPOCA ({len(ep)} epocas hasta early stopping; la 1 incluye "
      f"trazado del grafo)")
    w(f"   {'':<14}{'total s':>8}{'entreno':>9}{'valid.':>8}{'callbk':>8}{'resto':>7}"
      f"{'ms/paso':>9}{'GPU%ent':>8}{'GPU%val':>8}")
    for nombre, fila in (("epoca 1", ep.iloc[0]), ("mediana 2..N", m)):
        w(f"   {nombre:<14}{fila.total:8.2f}{fila.entreno:9.2f}{fila.validacion:8.2f}"
          f"{fila.callbacks:8.3f}{fila.resto:7.3f}{1000*fila.entreno/pasos:9.2f}"
          f"{fila.gpu_ent:8.1f}{fila.gpu_val:8.1f}")
    w(f"   fracciones de la epoca: entrenamiento {100*m.entreno/m.total:.1f}%, "
      f"validacion {100*m.validacion/m.total:.1f}%, callbacks {100*m.callbacks/m.total:.2f}%")
    w("")

    b = info.get("bancos", {})
    if b:
        # ---- 3. paso ----
        real = 1000 * m.entreno / pasos
        triv = b["fit_trivial_ms_paso"]
        g = b[f"gpu_bs{bs}_ms_paso"]
        h = b[f"host_bs{bs}_ms_paso"]
        fg = F[f"banco_gpu_bs{bs}"]
        util_paso = _media(gpu, 1, fg["t0"], fg["t1"])
        util_fit = m.gpu_ent
        gpu_ms = real * util_fit / 100
        carga = real - triv
        w(f"3. DESGLOSE DE UN PASO DE ENTRENAMIENTO (batch {bs})")
        w(f"   paso real dentro de fit (mediana epocas 2..N)   {real:7.2f} ms")
        w(f"   fit con entrada trivial (sin augmentation)       {triv:7.2f} ms")
        w(f"   train_on_batch, batch en RAM                     {h:7.2f} ms")
        w(f"   train_on_batch, batch ya en GPU                  {g:7.2f} ms   "
          f"(GPU ocupada {util_paso:.0f}%)")
        w(f"   pipeline tf.data solo, por batch                 {b['pipeline_ms_batch']:7.2f} ms")
        w("   reparto del paso real:")
        w(f"     carga de datos (augmentation + tf.data)         {max(carga, 0):6.2f} ms "
          f"{100*max(carga, 0)/real:5.1f}%"
          + ("   (medida negativa: indistinguible de cero)" if carga < 0 else ""))
        w(f"     copia host->GPU del batch                        {max(h-g, 0):6.2f} ms "
          f"{100*max(h-g, 0)/real:5.1f}%"
          + ("   (RAM igual o mas rapida que GPU: indistinguible de cero)" if h - g <= 0 else ""))
        w(f"     computo de GPU (utilizacion durante fit x paso)  {gpu_ms:6.2f} ms "
          f"{100*gpu_ms/real:5.1f}%")
        resto = real - max(carga, 0) - max(h - g, 0) - gpu_ms
        w(f"     GPU ociosa dentro del paso: despacho de ops,     {resto:6.2f} ms "
          f"{100*resto/real:5.1f}%")
        w("     lanzamiento de kernels y sincronizacion")
        w("")

        # ---- 4. batch ----
        bb = np.array(a["batches_banco"], float)
        ms = np.array([b[f"gpu_bs{int(x)}_ms_paso"] for x in bb])
        pend, orden = np.polyfit(bb, ms, 1)
        w("4. COSTE FIJO POR PASO (batch ya en GPU)")
        w(f"   {'batch':>7}{'ms/paso':>10}{'ventanas/s':>12}{'GPU %':>8}{'x vs ' + str(bs):>9}")
        base = bs / (g / 1000)
        for x, t in zip(bb, ms):
            fb = F[f"banco_gpu_bs{int(x)}"]
            w(f"   {int(x):>7}{t:10.2f}{x/(t/1000):12.0f}"
              f"{_media(gpu, 1, fb['t0'], fb['t1']):8.1f}{(x/(t/1000))/base:9.2f}")
        w(f"   ajuste lineal: ms/paso = {orden:.2f} + {pend*1000:.2f} x batch/1000")
        w(f"   -> {orden:.1f} ms por paso NO dependen del volumen de datos; a batch {bs} "
          f"son el {100*orden/g:.0f}% del paso")
        w("   (informativo: cambiar el batch cambia la optimizacion y los resultados)")
        w("")

        # ---- 5. sondas ----
        w("5. SONDAS DE OPTIMIZACION (fit con entrada trivial, batch 32)")
        w(f"   {'variante':<34}{'ms/paso':>9}{'x':>7}{'GPU %':>8}   cambia resultados?")
        cambios = {"fit_trivial": "referencia",
                   "sonda_spe32": "no: misma matematica, 32 pasos por llamada",
                   "sonda_sin_auc": "no el modelo; se pierde la AUC reportada",
                   "sonda_xla": "numericamente minimo (fusion de kernels)",
                   "sonda_spe32_xla": "idem"}
        for clave in ("fit_trivial", "sonda_spe32", "sonda_sin_auc", "sonda_xla",
                      "sonda_spe32_xla"):
            nombre_fase = "banco_fit_trivial" if clave == "fit_trivial" else clave
            ms_k = b.get(f"{clave}_ms_paso")
            if ms_k is None:
                w(f"   {clave:<34}{'fallo':>9}   {b.get(clave + '_error', '')[:60]}")
                continue
            fk = F[nombre_fase]
            w(f"   {clave:<34}{ms_k:9.2f}{triv/ms_k:7.2f}"
              f"{_media(gpu, 1, fk['t0'], fk['t1']):8.1f}   {cambios[clave]}")
        w("")

    # ---- 6. memoria ----
    f0, f1 = F["fit"]["t0"], F["fit"]["t1"]
    mfit = (cpu_a[:, 0] >= f0) & (cpu_a[:, 0] <= f1)
    esperado = info["bytes_por_batch"] * (1000 / (1000 * m.entreno / pasos)) / 2**20
    w("6. MEMORIA: CABE EN VRAM O SE PAGINA?")
    w(f"   dataset completo en RAM              {info['mb_dataset_total']:8.1f} MB ({info['dtype']})")
    w(f"   train del pliegue                    {info['mb_train_fit']:8.1f} MB")
    w(f"   VRAM total                           {VRAM_TOTAL_MB:8.0f} MB")
    w(f"   VRAM pico asignada por TF (fit)      {info.get('vram_tf_pico_mb', float('nan')):8.1f} MB")
    w(f"   VRAM segun nvidia-smi (fit)          {_media(gpu, 3, f0, f1):8.0f} MB  "
      f"(TF reserva por adelantado; no es uso)")
    w(f"   RSS del proceso (fit, media)         {np.nanmean(cpu_a[mfit, 8]):8.0f} MB")
    w(f"   paginas de swap in / out (fit)       {int(cpu_a[mfit, 5].sum())} / {int(cpu_a[mfit, 6].sum())}")
    w(f"   fallos de pagina mayores (fit)       {int(cpu_a[mfit, 7].sum())}")
    if len(pcie) and not np.all(np.isnan(pcie[:, 1])):
        w(f"   PCIe host->GPU medido (fit)          {_media(pcie, 1, f0, f1):8.1f} MB/s")
        w(f"   PCIe GPU->host medido (fit)          {_media(pcie, 2, f0, f1):8.1f} MB/s")
        w(f"   datos de entrada esperados           {esperado:8.1f} MB/s  "
          f"(bytes por batch x pasos por segundo)")
    w("")
    w("7. CPU DURANTE EL ENTRENAMIENTO (media epocas 2..N)")
    w(f"   CPU total {est.cpu_pct.mean():.1f}% de {os.cpu_count()} nucleos; proceso "
      f"{est.nucleos.mean():.2f} nucleos; hilo mas cargado {est.hilo1.mean():.2f} nucleos")
    top = cpu.loc[mfit, "hilo1"].value_counts().head(3)
    w("   hilo mas cargado por muestra: " + ", ".join(f"{k} ({v})" for k, v in top.items()))

    texto = "\n".join(L)
    print(texto)
    with open(os.path.join(directorio, "perfil.txt"), "w", encoding="utf-8") as f:
        f.write(texto + "\n")


# ============================================================
def main():
    ap = argparse.ArgumentParser(description="Perfil de tiempo de un pliegue")
    ap.add_argument("--mat", default=os.path.expanduser("~/data/NinaPro_DB5"))
    ap.add_argument("--cache", default=os.path.expanduser("~/cache_ninapro.npz"))
    ap.add_argument("--fold", type=int, default=0)
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--batch_size", type=int, default=32)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--pasos_banco", type=int, default=320)
    ap.add_argument("--batches_banco", type=int, nargs="+", default=[32, 64, 128, 256])
    ap.add_argument("--sin_bancos", action="store_true")
    ap.add_argument("--output", default=os.path.join(AQUI, "resultados_cv", "perfil"))
    ap.add_argument("--solo_analizar", default=None)
    args = ap.parse_args()

    if args.solo_analizar:
        analizar(args.solo_analizar)
        return

    os.makedirs(args.output, exist_ok=True)
    ctx = mp.get_context("fork")
    parar = ctx.Event()
    p_cpu = ctx.Process(target=muestreador_cpu,
                        args=(os.getpid(), os.path.join(args.output, "cpu_500ms.csv"), parar),
                        daemon=True)
    p_cpu.start()
    f_gpu = open(os.path.join(args.output, "gpu_100ms.csv"), "w")
    f_dmon = open(os.path.join(args.output, "dmon_1s.csv"), "w")
    smi = subprocess.Popen(
        ["stdbuf", "-oL", "nvidia-smi",
         "--query-gpu=timestamp,utilization.gpu,utilization.memory,memory.used",
         "--format=csv,noheader,nounits", "-lms", "100"], stdout=f_gpu)
    dmon = subprocess.Popen(["stdbuf", "-oL", "nvidia-smi", "dmon", "-s", "ut", "-o", "T"],
                            stdout=f_dmon)
    fases, info = [], {}
    try:
        t0 = time.time()
        time.sleep(3)                          # linea base de la GPU sin carga
        fases.append(dict(fase="reposo_inicial", t0=t0, t1=time.time()))
        info = perfilar(args, fases)
    finally:
        time.sleep(3)
        parar.set()
        smi.terminate()
        dmon.terminate()
        p_cpu.join(timeout=5)
        f_gpu.close()
        f_dmon.close()
        with open(os.path.join(args.output, "perfil.json"), "w") as f:
            json.dump(dict(args=vars(args), fases=fases, info=info), f, indent=2,
                      default=lambda o: o.item() if hasattr(o, "item") else str(o))
    analizar(args.output)
    print("### PERFIL COMPLETO", flush=True)


if __name__ == "__main__":
    main()
