"""
analisis_ventana.py - 1.a  Barrido de ventana, solapamiento y muestreo
======================================================================
Objetivo: justificar con datos la eleccion de 200 ms de ventana y 20 ms
de stride, en vez de heredarla de un paper.

REJILLA: ventana {100,150,200,250,300} ms x solapamiento
{50,60,70,75,80,90}% x frecuencia {83.2, 41.6} Hz = 60 combinaciones.

DOS ETAPAS:
  1. LDA sobre la rejilla completa. Es barato y localiza la region buena.
  2. CNN-BiLSTM-Attention solo sobre las mejores combinaciones distintas.

VALIDACION: GroupKFold k=5 por SUJETO, siempre. Con solapamiento alto,
una particion aleatoria pone ventanas casi identicas a ambos lados y la
fuga esta garantizada.

LA PREGUNTA DE FONDO: si el solapamiento alto mejora el resultado, es
por informacion real o solo porque produce mas ventanas? Para separarlo
hay un CONTROL DE N IGUAL: dentro de cada ventana, todas las
configuraciones de solapamiento se reevaluan con el mismo numero de
ventanas de entrenamiento (el del solapamiento mas bajo). Si la ganancia
desaparece a N igual, era tamano de muestra y no informacion. Y en la
etapa CNN el entrenamiento se acota a N_MAX ventanas por pliegue por la
misma razon, ademas de acotar el computo.

VALORES EFECTIVOS: tras redondear a muestras enteras varias celdas
colapsan en la misma configuracion real (a 41.6 Hz, 100 ms son 4
muestras y 90% de solapamiento redondea a 75%). Se reportan los valores
efectivos y se marcan las celdas duplicadas.

LATENCIA DE VENTANEO: el tiempo hasta disponer de la primera ventana
completa tras el inicio del gesto es la duracion de la ventana; el
periodo entre decisiones es el stride. Ambos se reportan.

USO:
  python analisis_ventana.py --etapa lda
  python analisis_ventana.py --etapa cnn --top 6
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
from particion import autotest_verificador, generar_particiones  # noqa

from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.metrics import accuracy_score, f1_score

VENTANAS_MS = [100, 150, 200, 250, 300]
SOLAPAMIENTOS = [0.50, 0.60, 0.70, 0.75, 0.80, 0.90]
FACTORES_FS = [1, 2]            # 83.2 Hz y 41.6 Hz


def particiones_por_sujeto(y, subj, k=5):
    """GroupKFold por sujeto, con la verificacion dura de no fuga."""
    return generar_particiones(np.zeros(len(y)), y, subj, subj,
                               agrupamiento="sujeto", n_splits=k)


def evaluar_lda(F, y, subj, n_train_max=None, seed=42):
    """Metricas por pliegue de un LDA con shrinkage."""
    rng = np.random.RandomState(seed)
    accs, f1s = [], []
    for tr, te in particiones_por_sujeto(y, subj):
        if n_train_max and len(tr) > n_train_max:
            tr = rng.choice(tr, n_train_max, replace=False)
        # shrinkage='auto' (Ledoit-Wolf): con 80 caracteristicas muy
        # correlacionadas la covarianza sin regularizar es inestable.
        m = LinearDiscriminantAnalysis(solver="lsqr", shrinkage="auto")
        m.fit(F[tr], y[tr])
        p = m.predict(F[te])
        accs.append(accuracy_score(y[te], p))
        f1s.append(f1_score(y[te], p, average="macro",
                            labels=range(NUM_CLASES), zero_division=0))
    return accs, f1s


def etapa_lda(args):
    filas = []
    cache = os.path.expanduser(args.cache)
    for factor in FACTORES_FS:
        fs = FS_NATIVA / factor
        print(f"\n=== fs = {fs:.1f} Hz: preparando sesiones ===")
        sesiones, sujetos, _ = preparar_config(args.config, fs, args.data,
                                               cache_dir=cache)
        for vms in VENTANAS_MS:
            for sol in SOLAPAMIENTOS:
                pv = parametros_ventana(vms, sol, fs)
                F, _, y, subj = ventanear(sesiones, sujetos, pv["w"],
                                          pv["stride"], args.variante)
                y, F, subj = submuestrear_rest(y, F, subj)
                t0 = time.time()
                accs, f1s = evaluar_lda(F, y, subj)
                filas.append(dict(
                    fs_hz=round(fs, 1), ventana_ms=vms, solap_nominal=sol,
                    w_muestras=pv["w"], stride_muestras=pv["stride"],
                    ventana_ms_efectiva=round(pv["ventana_ms_efectiva"], 1),
                    stride_ms_efectivo=round(pv["stride_ms_efectivo"], 1),
                    solap_efectivo=round(pv["solapamiento_efectivo"], 3),
                    latencia_ventaneo_ms=round(pv["ventana_ms_efectiva"], 1),
                    periodo_decision_ms=round(pv["stride_ms_efectivo"], 1),
                    n_ventanas=len(y),
                    acc_media=np.mean(accs), acc_std=np.std(accs),
                    f1_media=np.mean(f1s), f1_std=np.std(f1s),
                    acc_por_pliegue=json.dumps([round(a, 4) for a in accs]),
                ))
                print(f"  {vms:>3} ms  sol {sol:.2f}->{pv['solapamiento_efectivo']:.2f}"
                      f"  N={len(y):>7}  acc {np.mean(accs):.4f}  "
                      f"F1 {np.mean(f1s):.4f}  ({time.time()-t0:.1f} s)")

    df = pd.DataFrame(filas)
    # Celdas que colapsan en la misma configuracion efectiva
    clave = ["fs_hz", "w_muestras", "stride_muestras"]
    df["duplicada"] = df.duplicated(clave, keep="first")
    ruta = os.path.join(args.output, "ventana_lda.csv")
    df.to_csv(ruta, index=False)
    print(f"\n[CSV] {ruta}")
    print(f"  celdas nominales: {len(df)}  configuraciones efectivas "
          f"distintas: {(~df.duplicada).sum()}")
    return df


def etapa_lda_igual_n(args):
    """
    CONTROL DE N IGUAL. Para cada (fs, ventana), todas las celdas de
    solapamiento se reevaluan con el mismo numero de ventanas de
    entrenamiento: el de la celda de menor solapamiento. Si la mejora
    con el solapamiento persiste aqui, es informacion; si desaparece,
    era numero de ventanas.
    """
    filas = []
    cache = os.path.expanduser(args.cache)
    for factor in FACTORES_FS:
        fs = FS_NATIVA / factor
        sesiones, sujetos, _ = preparar_config(args.config, fs, args.data,
                                               cache_dir=cache)
        for vms in VENTANAS_MS:
            conjuntos = {}
            for sol in SOLAPAMIENTOS:
                pv = parametros_ventana(vms, sol, fs)
                F, _, y, subj = ventanear(sesiones, sujetos, pv["w"],
                                          pv["stride"], args.variante)
                conjuntos[sol] = submuestrear_rest(y, F, subj) + (pv,)
            # N de entrenamiento comun: el minimo de los pliegues de train
            # de la celda con menos ventanas (80% de sus ventanas aprox.)
            n_min = min(len(c[0]) for c in conjuntos.values())
            n_train = int(0.8 * n_min)
            for sol, (y, F, subj, pv) in conjuntos.items():
                accs, f1s = evaluar_lda(F, y, subj, n_train_max=n_train)
                filas.append(dict(
                    fs_hz=round(fs, 1), ventana_ms=vms, solap_nominal=sol,
                    solap_efectivo=round(pv["solapamiento_efectivo"], 3),
                    n_ventanas_total=len(y), n_train_fijo=n_train,
                    acc_media=np.mean(accs), acc_std=np.std(accs),
                    f1_media=np.mean(f1s), f1_std=np.std(f1s)))
                print(f"  [N igual={n_train}] {fs:.1f} Hz {vms} ms sol "
                      f"{sol:.2f}: F1 {np.mean(f1s):.4f}")
    df = pd.DataFrame(filas)
    ruta = os.path.join(args.output, "ventana_lda_igualN.csv")
    df.to_csv(ruta, index=False)
    print(f"[CSV] {ruta}")
    return df


def etapa_cnn(args):
    """CNN sobre las mejores configuraciones efectivas del LDA."""
    from entrenamiento_cv import entrenar_pliegue   # importa TensorFlow

    ruta_lda = os.path.join(args.output, "ventana_lda.csv")
    if not os.path.exists(ruta_lda):
        raise SystemExit("Falta ventana_lda.csv: corra antes --etapa lda.")
    lda = pd.read_csv(ruta_lda)
    top = (lda[~lda.duplicada].sort_values("f1_media", ascending=False)
           .head(args.top))
    print("Configuraciones seleccionadas (por F1 macro del LDA):")
    print(top[["fs_hz", "ventana_ms", "solap_efectivo", "f1_media"]]
          .to_string(index=False))

    cache = os.path.expanduser(args.cache)
    filas = []
    for _, c in top.iterrows():
        fs = float(c.fs_hz)
        sesiones, sujetos, _ = preparar_config(args.config, fs, args.data,
                                               cache_dir=cache)
        _, X, y, subj = ventanear(sesiones, sujetos, int(c.w_muestras),
                                  int(c.stride_muestras), args.variante,
                                  con_crudo=True)
        y, X, subj = submuestrear_rest(y, X, subj)
        Y = np.eye(NUM_CLASES, dtype=np.float32)[y]
        rng = np.random.RandomState(args.seed)
        for k, (tr, te) in enumerate(particiones_por_sujeto(y, subj)):
            if len(tr) > args.n_max:
                tr = rng.choice(tr, args.n_max, replace=False)
            _, _, m = entrenar_pliegue(
                X[tr], Y[tr], X[te], Y[te], k, args.epochs, 32, 1e-3,
                early_stopping_start=10, seed=args.seed)
            filas.append(dict(
                fs_hz=fs, ventana_ms=int(c.ventana_ms),
                solap_efectivo=float(c.solap_efectivo), pliegue=k + 1,
                n_train=len(tr), accuracy=m["accuracy"],
                f1_macro=m["f1_macro"], auc=m["auc"],
                epoca_restaurada=m["epoca_restaurada"]))
            pd.DataFrame(filas).to_csv(
                os.path.join(args.output, "ventana_cnn.csv"), index=False)
    print(f"[CSV] {os.path.join(args.output, 'ventana_cnn.csv')}")


def figuras(args):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    lda = pd.read_csv(os.path.join(args.output, "ventana_lda.csv"))
    fig, ejes = plt.subplots(1, 3, figsize=(18, 4.8))
    for ax, fs in zip(ejes[:2], sorted(lda.fs_hz.unique(), reverse=True)):
        t = lda[lda.fs_hz == fs].pivot_table(
            index="ventana_ms", columns="solap_nominal", values="f1_media")
        im = ax.imshow(t.values, cmap="viridis", aspect="auto", origin="lower")
        ax.set_xticks(range(len(t.columns)))
        ax.set_xticklabels([f"{int(100*s)}%" for s in t.columns])
        ax.set_yticks(range(len(t.index)))
        ax.set_yticklabels(t.index)
        for i in range(t.shape[0]):
            for j in range(t.shape[1]):
                ax.text(j, i, f"{t.values[i, j]:.3f}", ha="center",
                        va="center", fontsize=7, color="w")
        ax.set_title(f"F1 macro LDA, {fs} Hz")
        ax.set_xlabel("solapamiento nominal")
        ax.set_ylabel("ventana (ms)")
        fig.colorbar(im, ax=ax, shrink=0.8)

    ax = ejes[2]
    igual = os.path.join(args.output, "ventana_lda_igualN.csv")
    base = lda[(lda.fs_hz == lda.fs_hz.max()) & (lda.ventana_ms == 200)]
    ax.plot(base.solap_efectivo, base.f1_media, "o-",
            label="todas las ventanas")
    if os.path.exists(igual):
        ig = pd.read_csv(igual)
        ig = ig[(ig.fs_hz == ig.fs_hz.max()) & (ig.ventana_ms == 200)]
        ax.plot(ig.solap_efectivo, ig.f1_media, "s--",
                label="N de entrenamiento fijo")
    ax2 = ax.twinx()
    ax2.plot(base.solap_efectivo, base.n_ventanas, ":", color="gray")
    ax2.set_ylabel("ventanas generadas", color="gray")
    ax.set_xlabel("solapamiento efectivo")
    ax.set_ylabel("F1 macro")
    ax.set_title("200 ms: solapamiento vs numero de ventanas")
    ax.legend(loc="lower right", fontsize=8)
    plt.tight_layout()
    ruta = os.path.join(args.output, "ventana_barrido.png")
    plt.savefig(ruta, dpi=150, bbox_inches="tight")
    print(f"[FIG] {ruta}")


def main():
    p = argparse.ArgumentParser(description="1.a Barrido de ventana")
    p.add_argument("--etapa", choices=["lda", "cnn", "figuras", "todo"],
                   default="todo")
    p.add_argument("--config", default="ir",
                   help="Configuracion de luz (default ir, la mas proxima "
                        "a nuestro LED de 940 nm)")
    p.add_argument("--variante", default="dinamica_meseta")
    p.add_argument("--top", type=int, default=6)
    p.add_argument("--n_max", type=int, default=40000,
                   help="Tope de ventanas de entrenamiento por pliegue en "
                        "la CNN: acota computo y separa solapamiento de N")
    p.add_argument("--epochs", type=int, default=100)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--data", default=RUTA_DATASET_DEFECTO)
    p.add_argument("--cache", default="~/cache_lmg")
    p.add_argument("--output", default=os.path.join(AQUI, "resultados"))
    args = p.parse_args()
    os.makedirs(args.output, exist_ok=True)

    sesiones, sujetos, _ = preparar_config(args.config, FS_NATIVA, args.data,
                                           cache_dir=os.path.expanduser(args.cache))
    print(autotest_verificador(np.repeat(sujetos, 10)))

    if args.etapa in ("lda", "todo"):
        etapa_lda(args)
        etapa_lda_igual_n(args)
    if args.etapa in ("cnn", "todo"):
        etapa_cnn(args)
    if args.etapa in ("figuras", "todo", "lda"):
        figuras(args)


if __name__ == "__main__":
    main()
