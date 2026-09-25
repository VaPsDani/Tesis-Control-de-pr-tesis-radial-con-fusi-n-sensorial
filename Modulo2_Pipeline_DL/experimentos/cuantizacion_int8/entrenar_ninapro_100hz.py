"""
entrenar_ninapro_100hz.py - Etapa 1: NinaPro DB5 con la forma de produccion
===========================================================================
Protesis transradial - Fusion sensorial y Deep Learning

Entrena UN pliegue del modelo de produccion sobre NinaPro DB5 remuestreado
a 100 Hz, para medir despues la perdida de la cuantizacion INT8 con datos
reales (cuantizar_evaluar.py). No sustituye a la validacion preliminar,
que se queda como esta en su entorno original.

DIFERENCIAS FRENTE A validacion_preliminar_emg/ (a proposito):
  - 100 Hz en vez de 200 Hz: ventana de 200 ms = 20 muestras y paso de
    20 ms = 2 muestras, la forma exacta de produccion (20, 8).
    EMG y ACC se diezman x2 con filtro antialias FIR de fase cero sobre la
    senal CONTINUA de cada archivo, antes de filtrar filas por etiqueta.
  - El ACC no pasa por la simulacion de 50 Hz: el firmware lee el MPU6050
    a 100 Hz, y el ACC de DB5 ya trae el ancho de banda de un IMU de 50 Hz.
  - Keras 2 (tf_keras), el entorno de produccion.
IGUAL QUE EL PROTOCOLO CORREGIDO:
  canales EMG[:5] + ACC[:3], mapeo de etiquetas por ejercicio, submuestreo
  de Rest, GroupKFold k=5 por SUJETO, normalizacion por sujeto, validacion
  interna con un sujeto del train + reentreno con todo el train, semilla 42,
  100 epocas maximo, lote 32, lr 1e-3, early_stopping_start 10.

USO (entorno de produccion, requirements-produccion.txt):
  python entrenar_ninapro_100hz.py --mat ~/data/NinaPro_DB5 --pliegue 0 \
      --cache ~/cache_ninapro_100hz.npz --output_dir resultados
"""

import os as _os
import sys as _sys
_M2 = _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                     "..", ".."))
for _d in (_M2, _os.path.join(_M2, "common"), _os.path.join(_M2, "produccion"),
           _os.path.join(_M2, "experimentos", "validacion_preliminar_emg")):
    if _d not in _sys.path:
        _sys.path.insert(0, _d)

import keras_legado
keras_legado.activar()          # antes de importar tensorflow (entrenamiento.py)

import argparse                 # noqa: E402
import json                     # noqa: E402
import os                       # noqa: E402

import numpy as np              # noqa: E402
from scipy.signal import decimate  # noqa: E402

from cargar_ninapro import (    # noqa: E402
    MAPEO_E1, MAPEO_E2, MAPEO_E3, NOMBRES_GESTOS, NUM_CLASES,
    CargadorNinaProDB5, SlidingWindowNinaPro, mapear_etiquetas,
    seleccionar_canales, submuestrear_clase_0,
)
from normalizacion import normalizar, verificar_normalizacion  # noqa: E402
from validacion import generar_particiones                    # noqa: E402

TASA_DB5 = 200
FACTOR = 2                      # 200 Hz -> 100 Hz
TASA = TASA_DB5 // FACTOR
VENTANA = int(200 * TASA / 1000)    # 20 muestras
PASO = int(20 * TASA / 1000)        # 2 muestras


def diezmar(x: np.ndarray) -> np.ndarray:
    """Antialias FIR de fase cero + submuestreo x2, por columnas."""
    return decimate(x.astype(np.float64), FACTOR, ftype="fir", zero_phase=True, axis=0)


def cargar_100hz(ruta_mat: str):
    cargador = CargadorNinaProDB5(ruta_mat)
    archivos = cargador.cargar_todos()
    vent = SlidingWindowNinaPro(window_size_samples=VENTANA, stride_samples=PASO)
    Xs, ys, gs, ss = [], [], [], []
    for idx, (emg_raw, acc_raw, labels, repetition, sujeto, _) in enumerate(archivos):
        nombre = cargador.archivos[idx].name
        mapeo = MAPEO_E2 if "E2" in nombre else MAPEO_E3 if "E3" in nombre else MAPEO_E1
        emg, acc = seleccionar_canales(emg_raw, acc_raw)
        # Diezmado sobre la senal continua; etiquetas y repeticiones se toman
        # en las mismas muestras (y[k] <-> x[2k] con fase cero)
        emg, acc = diezmar(emg), diezmar(acc)
        labels, repetition = labels[::FACTOR], repetition[::FACTOR]
        n = min(len(emg), len(labels))
        emg, acc, labels, repetition = emg[:n], acc[:n], labels[:n], repetition[:n]
        mask, lab = mapear_etiquetas(labels, mapeo)
        if mask.sum() == 0:
            continue
        X, y, g, s = vent.generar_ventanas(emg[mask], acc[mask], lab[mask],
                                           repetition[mask], sujeto)
        Xs.append(X); ys.append(y); gs.append(g); ss.append(s)
    X, y, g, s = (np.concatenate(a) for a in (Xs, ys, gs, ss))
    return submuestrear_clase_0(X, y, g, s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mat", required=True)
    ap.add_argument("--pliegue", type=int, default=0)
    ap.add_argument("--cache", default=None)
    ap.add_argument("--output_dir", default="resultados")
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    os.makedirs(args.output_dir, exist_ok=True)
    from entrenamiento import entrenar_con_validacion_interna   # importa TF

    if args.cache and os.path.exists(os.path.expanduser(args.cache)):
        d = np.load(os.path.expanduser(args.cache))
        X, y, grupos, sujetos = d["X"], d["y"], d["grupos"], d["sujetos"]
    else:
        X, y, grupos, sujetos = cargar_100hz(os.path.expanduser(args.mat))
        if args.cache:
            np.savez_compressed(os.path.expanduser(args.cache), X=X, y=y, grupos=grupos, sujetos=sujetos)
    assert X.shape[1:] == (VENTANA, 8), X.shape
    print(f"[DATOS] {X.shape[0]} ventanas de forma {X.shape[1:]} a {TASA} Hz, "
          f"sujetos {sorted(np.unique(sujetos).tolist())}")

    y_int = y.argmax(1)
    particiones = generar_particiones(X, y_int, grupos, sujetos, agrupamiento="sujeto",
                                      n_splits=5, estratificado=False)
    idx_tr, idx_te = particiones[args.pliegue]
    X_tr, X_te, y_tr, y_te = X[idx_tr], X[idx_te], y[idx_tr], y[idx_te]
    s_tr, s_te = sujetos[idx_tr], sujetos[idx_te]
    X_tr, X_te, info = normalizar(X_tr, X_te, s_tr, s_te, y_tr, y_te, modo="sujeto")
    print(" ", verificar_normalizacion(X_tr, s_tr, "sujeto"), "[train]")
    print(" ", verificar_normalizacion(X_te, s_te, "sujeto"), "[test]")
    print(f"[PLIEGUE {args.pliegue + 1}] test = sujetos {sorted(np.unique(s_te).tolist())}")

    ruta_modelo = os.path.join(args.output_dir, f"modelo_float_pliegue{args.pliegue + 1}.keras")
    _, p_float, metricas = entrenar_con_validacion_interna(
        X_tr, y_tr, s_tr, X_te, y_te, s_te, args.pliegue,
        args.epochs, 32, 1e-3, early_stopping_start=10, seed=args.seed,
        modo="interna", val_grupos=1, reentrenar=True,
        num_clases=NUM_CLASES, nombres_clases=NOMBRES_GESTOS,
        guardar_modelo_en=ruta_modelo)

    # Conjuntos de calibracion para la cuantizacion, SOLO del train:
    #  - 'produccion': las 1000 primeras ventanas, como convertir_tflite.py
    #  - 'azar': 1000 ventanas al azar del train
    rng = np.random.default_rng(args.seed)
    np.savez_compressed(
        os.path.join(args.output_dir, f"datos_pliegue{args.pliegue + 1}.npz"),
        X_test=X_te.astype(np.float32), y_test=y_te.argmax(1).astype(np.int16),
        sujetos_test=s_te, p_float=p_float.astype(np.float32),
        calib_produccion=X_tr[:1000].astype(np.float32),
        calib_azar=X_tr[rng.choice(len(X_tr), 1000, replace=False)].astype(np.float32))
    resumen = {"pliegue": args.pliegue + 1, "tasa_hz": TASA, "forma": [VENTANA, 8],
               "n_train": int(len(idx_tr)), "n_test": int(len(idx_te)),
               "sujetos_test": sorted(np.unique(s_te).tolist()),
               "accuracy_float": metricas["accuracy"], "f1_macro_float": metricas["f1_macro"],
               "epocas_reentreno": metricas["epochs"], "epoca_restaurada": metricas["epoca_restaurada"],
               "normalizacion": "sujeto", "validacion": metricas["validacion"],
               "grupos_validacion": metricas["grupos_validacion"]}
    with open(os.path.join(args.output_dir, f"entrenamiento_pliegue{args.pliegue + 1}.json"), "w") as f:
        json.dump(resumen, f, indent=2)
    print("[RESUMEN]", json.dumps(resumen))


if __name__ == "__main__":
    main()
