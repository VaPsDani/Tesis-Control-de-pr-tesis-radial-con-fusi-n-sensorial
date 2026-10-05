"""
entrenar_modelo.py - Entrenamiento de produccion del CNN-BiLSTM-Attention
=========================================================================
Protesis transradial - Fusion sensorial y Deep Learning

EL MISMO MECANISMO QUE LA ABLACION DE LA IMU:
  - Datos: produccion/preprocesamiento.py, preparar_sesiones(). Fases,
    repeticiones descartadas fuera, y normalizacion con la calibracion de
    cada sesion, igual que el firmware: LMG en z, acelerometro en g menos
    la media. Es la misma funcion que usa la ablacion (A18).
  - Particion: GroupKFold por sujeto, k = 5 (8 sujetos entrenan y 2 son
    de prueba), o LOSO como complemento (A14). Con verificacion de fuga.
  - Dentro de cada pliegue: 1 sujeto del entrenamiento se separa para la
    detencion temprana (7 + 1 + 2), con start_from_epoch = 10, y despues
    se reentrena con los 8 reproduciendo las epocas y el calendario de
    tasa de aprendizaje elegidos. El test no interviene en ninguna
    decision.
  - Pesos por clase calculados con las ventanas de entrenamiento de cada
    pliegue (A13).
  - Keras 2 (tf_keras), que es con lo que la LSTM cuantiza a INT8.

ANTES ESTE SCRIPT partia las ventanas 80/20 en orden temporal mezclando
sujetos, no normalizaba, y detenia el entrenamiento mirando el test.

MODOS:
  cv      GroupKFold por sujeto, k = 5. La cifra principal.
  loso    un pliegue por sujeto. Complemento.
  final   el modelo que se despliega: entrena con todos los sujetos menos
          los de --excluir, con la misma seleccion de epocas por
          validacion interna y reentreno. Guarda el .keras y la lista de
          sujetos de entrenamiento, que es de donde sale el representative
          dataset de la conversion INT8 (A23). Para la prueba en linea
          (A28) se excluye al participante que la va a hacer.

USO:
  python entrenar_modelo.py --sesiones "../sesiones/*.csv" --modo cv
  python entrenar_modelo.py --sesiones "..." --modo loso
  python entrenar_modelo.py --sesiones "..." --modo final --excluir 3
"""

# Rutas del Modulo 2: common/ tiene el codigo compartido y produccion/ el
# pipeline del modelo que se despliega.
import os as _os
import sys as _sys
_M2 = _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                     ".."))
for _d in (_M2, _os.path.join(_M2, "common"), _os.path.join(_M2, "produccion")):
    if _d not in _sys.path:
        _sys.path.insert(0, _d)

import keras_legado                              # noqa: E402
keras_legado.activar()                           # antes de importar tensorflow

import argparse                                  # noqa: E402
import json                                      # noqa: E402
import os                                        # noqa: E402
import time                                      # noqa: E402
from datetime import datetime                    # noqa: E402

import numpy as np                               # noqa: E402
import pandas as pd                              # noqa: E402

import preprocesamiento as P                     # noqa: E402
from metricas import (graficar_matriz_confusion, metricas,  # noqa: E402
                      por_sujeto)
from validacion import autotest_verificador, generar_particiones  # noqa: E402

NUM_CLASES = len(P.NOMBRES_CLASES)


def matriz(v_y, X, composicion):
    """Canales de la composicion y etiquetas en one-hot."""
    cols = [P.COLUMNAS_MODELO.index(c) for c in P.COMPOSICIONES[composicion]]
    return X[:, :, cols], np.eye(NUM_CLASES, dtype=np.float32)[v_y]


def validacion_cruzada(v, args, n_pliegues):
    """GroupKFold por sujeto con validacion interna y reentreno."""
    from entrenamiento import entrenar_con_validacion_interna
    X, Y = matriz(v.y, v.X, args.composicion)
    print(autotest_verificador(v.sujeto, seed=args.seed))

    prob = np.zeros((len(v), NUM_CLASES), dtype=np.float32)
    pliegue_de = np.full(len(v), -1, dtype=np.int16)
    roles = []
    for k, (tr, te) in enumerate(generar_particiones(
            X, v.y, v.repeticion, v.sujeto, "sujeto",
            n_splits=n_pliegues, seed=args.seed)):
        _, p, m = entrenar_con_validacion_interna(
            X[tr], Y[tr], v.sujeto[tr], X[te], Y[te], v.sujeto[te], k,
            args.epochs, args.batch_size, args.lr,
            early_stopping_start=args.early_stopping_start, seed=args.seed,
            num_clases=NUM_CLASES, nombres_clases=P.NOMBRES_CLASES,
            pesos_por_clase=True)
        prob[te] = p
        pliegue_de[te] = k
        val = sorted(int(s) for s in m["grupos_validacion"])
        entrena = sorted(set(int(s) for s in np.unique(v.sujeto[tr])) - set(val))
        prueba = sorted(int(s) for s in np.unique(v.sujeto[te]))
        assert not set(prueba) & (set(entrena) | set(val))
        roles.append({"pliegue": k, "entrenamiento": entrena,
                      "validacion": val, "prueba": prueba,
                      "epocas_reentreno": m["epochs"],
                      "pesos_por_clase": m["pesos_por_clase"]})
        print(f"[ROLES] pliegue {k + 1}: {len(entrena)} + {len(val)} + "
              f"{len(prueba)}  prueba {prueba}  validacion {val}")

    y_pred = prob.argmax(axis=1)
    global_ = metricas(v.y, y_pred, P.NOMBRES_CLASES, todas_las_clases=True)
    sujetos = por_sujeto(v.y, y_pred, v.sujeto, P.NOMBRES_CLASES,
                         todas_las_clases=True)
    condiciones = {c: metricas(v.y[v.condicion == c], y_pred[v.condicion == c],
                               P.NOMBRES_CLASES, todas_las_clases=True)
                   for c in P.CONDICIONES_POSTURALES}
    f1s = np.array([m["f1_macro"] for m in sujetos.values()])
    return {"global": global_, "por_condicion": condiciones,
            "por_sujeto": sujetos, "roles_por_pliegue": roles,
            "f1_macro_media_por_sujeto": float(f1s.mean()),
            "f1_macro_sd_por_sujeto": float(f1s.std(ddof=1)) if len(f1s) > 1 else None}


def modelo_final(v, args):
    """El modelo que se despliega, con los sujetos que no se excluyen."""
    from entrenamiento import entrenar_con_validacion_interna
    import tensorflow as tf
    excluir = set(args.excluir or [])
    entrena = ~np.isin(v.sujeto, list(excluir))
    X, Y = matriz(v.y, v.X, args.composicion)
    if excluir:
        X_te, Y_te, g_te = X[~entrena], Y[~entrena], v.sujeto[~entrena]
        nota = f"evaluado sobre los sujetos excluidos {sorted(excluir)}"
    else:
        # Sin sujetos excluidos no hay prueba: se evalua sobre unas pocas
        # ventanas de entrenamiento solo para comprobar que el modelo
        # carga y predice. Esa cifra NO es una metrica.
        X_te, Y_te = X[entrena][:256], Y[entrena][:256]
        g_te = np.full(len(X_te), -1)
        nota = "sin prueba: la evaluacion sobre 256 ventanas de entrenamiento no es una metrica"

    os.makedirs(args.output, exist_ok=True)
    ruta_modelo = os.path.join(args.output, "modelo_final.keras")
    _, _, m = entrenar_con_validacion_interna(
        X[entrena], Y[entrena], v.sujeto[entrena], X_te, Y_te, g_te, 0,
        args.epochs, args.batch_size, args.lr,
        early_stopping_start=args.early_stopping_start, seed=args.seed,
        num_clases=NUM_CLASES, nombres_clases=P.NOMBRES_CLASES,
        guardar_modelo_en=ruta_modelo, pesos_por_clase=True)
    import tf_keras
    return {"modelo": ruta_modelo, "nota": nota,
            "sujetos_entrenamiento": sorted(int(s) for s in np.unique(v.sujeto[entrena])),
            "sujeto_validacion": m["grupos_validacion"],
            "sujetos_excluidos": sorted(int(s) for s in excluir),
            "epocas": m["epochs"], "lr_por_epoca": m["lr_por_epoca"],
            "pesos_por_clase": m["pesos_por_clase"],
            "metricas_evaluacion": {k: m[k] for k in ("accuracy", "f1_macro")},
            "tensorflow": tf.__version__, "tf_keras": tf_keras.__version__}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sesiones", default=os.path.join(_M2, "sesiones", "*.csv"))
    ap.add_argument("--modo", choices=["cv", "loso", "final"], default="cv")
    ap.add_argument("--composicion", choices=list(P.COMPOSICIONES), default="lmg_imu")
    ap.add_argument("--excluir", type=int, nargs="*",
                    help="subject_id que no entran al modelo final")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--batch_size", type=int, default=32)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--early_stopping_start", type=int, default=10)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--output", default=os.path.join(_M2, "produccion", "resultados"))
    args = ap.parse_args()

    import tensorflow as tf                      # tras activar tf_keras
    print(f"[KERAS] tf_keras {keras_legado.verificar()}, TensorFlow {tf.__version__}")

    t0 = time.time()
    v = P.preparar_sesiones(args.sesiones)
    print(f"[DATOS] {len(v)} ventanas, clases "
          f"{ {P.NOMBRES_CLASES[k]: int((v.y == k).sum()) for k in range(NUM_CLASES)} }")

    if args.modo == "final":
        res = modelo_final(v, args)
    else:
        n = int(len(np.unique(v.sujeto))) if args.modo == "loso" else args.folds
        res = validacion_cruzada(v, args, n)
        g = res["global"]
        print(f"\n[{args.modo.upper()}] {args.composicion}: accuracy "
              f"{g['accuracy']:.4f}  F1 macro {g['f1_macro']:.4f}  "
              f"F1 macro por sujeto {res['f1_macro_media_por_sujeto']:.4f}")
        os.makedirs(args.output, exist_ok=True)
        graficar_matriz_confusion(np.array(g["matriz_confusion"]),
                                  f"{args.modo}_{args.composicion}", args.output,
                                  nombres_clases=P.NOMBRES_CLASES)
        filas = [{"sujeto": s, **{k: m[k] for k in
                  ("accuracy", "f1_macro", "f1_macro_activos",
                   "precision_macro", "recall_macro", "n")}}
                 for s, m in res["por_sujeto"].items()]
        pd.DataFrame(filas).to_csv(os.path.join(
            args.output, f"{args.modo}_{args.composicion}_por_sujeto.csv"), index=False)

    res.update({"fecha": datetime.now().isoformat(timespec="seconds"),
                "modo": args.modo, "composicion": args.composicion,
                "sesiones": args.sesiones, "duracion_s": round(time.time() - t0, 1),
                "hiperparametros": {k: getattr(args, k) for k in
                                    ("epochs", "batch_size", "lr",
                                     "early_stopping_start", "seed")}})
    os.makedirs(args.output, exist_ok=True)
    ruta = os.path.join(args.output, f"{args.modo}_{args.composicion}.json")
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2, ensure_ascii=False, default=str)
    print(f"[SALIDA] {ruta}")


if __name__ == "__main__":
    main()
