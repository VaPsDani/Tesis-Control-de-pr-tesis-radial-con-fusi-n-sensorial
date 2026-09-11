"""
analisis_clasicos.py - 1.d  Linea base con clasificadores clasicos
==================================================================
LDA, SVM y Random Forest contra la CNN-BiLSTM-Attention, sobre el MISMO
particionado (GroupKFold k=5 por sujeto, mismos pliegues para todos).

POR QUE HACE FALTA EL NUMERO:
  En la literatura de LMG y de FMG optico el LDA es competitivo y en
  algunos casos gana. Si aqui queda cerca de la CNN no es un problema, es
  un resultado: el merito estaria en la fusion sensorial y no en la
  arquitectura, y el sistema podria desplegarse en hardware mas barato.
  Un LDA cabe en cualquier microcontrolador sin TensorFlow Lite.

MODELOS:
  LDA   shrinkage Ledoit-Wolf ('auto'): 80 caracteristicas correlacionadas.
  SVM   nucleo RBF. Su entrenamiento escala con el cuadrado de las
        muestras, asi que se acota a 20 000 ventanas por pliegue.
  RF    300 arboles.
  CNN   la del proyecto, con el mismo tope de 40 000 ventanas.

  Clasicos: media y desviacion por canal. CNN: ventana cruda.

COMPARACION:
  Ademas de media +/- desviacion por pliegue, test de Wilcoxon pareado
  por sujeto entre cada clasico y la CNN, y coste de despliegue
  (parametros).

  Se evaluan dos conjuntos de canales: los 40 del dataset y los 5 mejores
  de 1.c si ya existe su resultado, que es lo relevante para nuestro
  brazalete de 5 modulos.
"""

import argparse
import json
import os
import sys
import time

import numpy as np
import pandas as pd

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
from datos import (FS_NATIVA, NOMBRES, NUM_CLASES, RUTA_DATASET_DEFECTO,  # noqa
                   parametros_ventana, preparar_config, submuestrear_rest,
                   ventanear)
from evaluacion import (indices_caracteristicas, metricas,  # noqa
                        particiones_por_sujeto, por_sujeto)

from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.ensemble import RandomForestClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

N_MAX_SVM = 20000


def construir(nombre, seed):
    if nombre == "LDA":
        return LinearDiscriminantAnalysis(solver="lsqr", shrinkage="auto")
    if nombre == "SVM":
        return make_pipeline(StandardScaler(),
                             SVC(kernel="rbf", C=10, gamma="scale"))
    if nombre == "RF":
        return RandomForestClassifier(n_estimators=300, n_jobs=-1,
                                      random_state=seed)
    raise ValueError(nombre)


def n_parametros(nombre, m, n_feat):
    if nombre == "LDA":
        return NUM_CLASES * (n_feat + 1)
    if nombre == "SVM":
        return int(m[-1].support_vectors_.size + m[-1].dual_coef_.size)
    if nombre == "RF":
        return int(sum(e.tree_.node_count for e in m.estimators_))
    return None


def main():
    p = argparse.ArgumentParser(description="1.d Clasicos vs CNN")
    p.add_argument("--config", default="ir")
    p.add_argument("--variante", default="dinamica_meseta")
    p.add_argument("--modelos", default="LDA,SVM,RF,CNN")
    p.add_argument("--n_max", type=int, default=40000)
    p.add_argument("--epochs", type=int, default=100)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--data", default=RUTA_DATASET_DEFECTO)
    p.add_argument("--cache", default="~/cache_lmg")
    p.add_argument("--output", default=os.path.join(AQUI, "resultados"))
    args = p.parse_args()
    os.makedirs(args.output, exist_ok=True)
    modelos = args.modelos.split(",")

    ses, suj, _ = preparar_config(args.config, FS_NATIVA, args.data,
                                  cache_dir=os.path.expanduser(args.cache))
    pv = parametros_ventana(200, 0.9, FS_NATIVA)
    F, X, y, subj = ventanear(ses, suj, pv["w"], pv["stride"], args.variante,
                              con_crudo="CNN" in modelos)
    y, F, X, subj = submuestrear_rest(y, F, X, subj)
    pliegues = particiones_por_sujeto(y, subj)

    conjuntos = {"40 canales": list(range(40))}
    rk = os.path.join(args.output, "canales_exhaustiva.csv")
    if os.path.exists(rk):
        ex = pd.read_csv(rk)
        conjuntos["5 canales (mejor de 1.c)"] = json.loads(
            ex[(ex.k == 5) & (ex.rango == 1)].canales.iloc[0])

    filas, por_suj = [], []
    for nombre_conj, canales in conjuntos.items():
        idx = indices_caracteristicas(canales)
        Fc = F[:, idx]
        Xc = X[:, :, canales] if X is not None else None
        for nombre in modelos:
            rng = np.random.RandomState(args.seed)
            y_pred = np.empty_like(y)
            t_fit, params = 0.0, None
            for k, (tr, te) in enumerate(pliegues):
                t0 = time.time()
                if nombre == "CNN":
                    from entrenamiento_cv import entrenar_pliegue
                    if len(tr) > args.n_max:
                        tr = rng.choice(tr, args.n_max, replace=False)
                    Y = np.eye(NUM_CLASES, dtype=np.float32)[y]
                    _, prob, _ = entrenar_pliegue(
                        Xc[tr], Y[tr], Xc[te], Y[te], k, args.epochs, 32,
                        1e-3, early_stopping_start=10, seed=args.seed)
                    y_pred[te] = prob.argmax(axis=1)
                else:
                    if nombre == "SVM" and len(tr) > N_MAX_SVM:
                        tr = rng.choice(tr, N_MAX_SVM, replace=False)
                    m = construir(nombre, args.seed).fit(Fc[tr], y[tr])
                    y_pred[te] = m.predict(Fc[te])
                    params = n_parametros(nombre, m, Fc.shape[1])
                t_fit += time.time() - t0
                mk = metricas(y[te], y_pred[te])
                filas.append(dict(conjunto=nombre_conj, modelo=nombre,
                                  pliegue=k + 1, **{kk: vv for kk, vv in
                                                    mk.items()
                                                    if kk != "f1_por_clase"},
                                  f1_por_clase=json.dumps(mk["f1_por_clase"]),
                                  n_parametros=params))
            for s, m_s in por_sujeto(y, y_pred, subj).items():
                por_suj.append(dict(conjunto=nombre_conj, modelo=nombre,
                                    subj=s, accuracy=m_s["accuracy"],
                                    f1_macro=m_s["f1_macro"]))
            d = pd.DataFrame([f for f in filas if f["modelo"] == nombre
                              and f["conjunto"] == nombre_conj])
            print(f"  {nombre_conj:<26} {nombre:<4} acc {d.accuracy.mean():.4f}"
                  f" +/- {d.accuracy.std():.4f}  F1 {d.f1_macro.mean():.4f}"
                  f"  ({t_fit:.0f} s)")
            pd.DataFrame(filas).to_csv(
                os.path.join(args.output, "clasicos_por_pliegue.csv"),
                index=False)

    ps = pd.DataFrame(por_suj)
    ps.to_csv(os.path.join(args.output, "clasicos_por_sujeto.csv"), index=False)

    # Wilcoxon pareado por sujeto: cada clasico contra la CNN
    from scipy.stats import wilcoxon
    lineas = ["ANALISIS 1.d - clasicos vs CNN (Wilcoxon pareado por sujeto)"]
    if "CNN" in modelos:
        for conj in conjuntos:
            cnn = ps[(ps.conjunto == conj) & (ps.modelo == "CNN")] \
                .set_index("subj").f1_macro
            for nombre in modelos:
                if nombre == "CNN":
                    continue
                otro = ps[(ps.conjunto == conj) & (ps.modelo == nombre)] \
                    .set_index("subj").f1_macro
                dif = (otro - cnn).dropna()
                w = wilcoxon(dif) if (dif != 0).any() else None
                lineas.append(
                    f"  [{conj}] {nombre} - CNN: diferencia media F1 "
                    f"{dif.mean():+.4f}, p = "
                    f"{w.pvalue if w else float('nan'):.4f}")
    texto = "\n".join(lineas)
    print("\n" + texto)
    with open(os.path.join(args.output, "clasicos_estadistica.txt"), "w",
              encoding="utf-8") as f:
        f.write(texto)


if __name__ == "__main__":
    main()
