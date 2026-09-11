"""
analisis_longitud_onda.py - 1.b  Afecta el color del LED a la decodificacion?
=============================================================================
Replica, con nuestro pipeline, la comparacion de configuraciones de
iluminacion del dataset: solo verde (525 nm), solo IR (880 nm), y ambas
alternando cada 250 y cada 125 ms.

DISENO:
  El mismo modelo sobre cada configuracion por separado, GroupKFold por
  sujeto. Cada sujeto es test en exactamente un pliegue, asi que se
  obtiene su exactitud en cada configuracion: una medida repetida por
  sujeto y configuracion. Sobre esa tabla (10 sujetos x 4 configs):

    ANOVA de medidas repetidas, sujeto como factor (statsmodels AnovaRM)
    Friedman, su equivalente no parametrico: con 10 sujetos la
      normalidad no esta garantizada y conviene el contraste robusto.

  El orden de las 4 configuraciones esta contrabalanceado entre sujetos
  en el propio dataset, asi que la configuracion no esta confundida con
  la fatiga ni con el orden de grabacion.

LA COMPARACION LIMPIA ES VERDE CONTRA IR:
  Las configuraciones alternas no solo cambian la longitud de onda: su
  modulacion a 2-4 Hz cae en la banda del gesto y hay que filtrarla con
  una media movil de un ciclo (250 o 500 ms), que suaviza la senal. Una
  diferencia de esas configuraciones puede deberse al filtrado y no al
  color. Por eso, ademas del ANOVA sobre las cuatro, se reporta la
  comparacion pareada verde contra IR, que es la unica que aisla la
  longitud de onda.

EXTRAPOLACION A DECLARAR:
  El IR del dataset es de 880 nm y el de nuestro brazalete de 940 nm. Si
  verde e IR no difieren, que 940 nm tampoco lo haga es una
  extrapolacion razonable, no una medicion.
"""

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
from datos import (CONFIGS, FS_NATIVA, NUM_CLASES, RUTA_DATASET_DEFECTO,  # noqa
                   parametros_ventana, preparar_config, submuestrear_rest,
                   ventanear)
from evaluacion import metricas, particiones_por_sujeto, por_sujeto  # noqa

from sklearn.discriminant_analysis import LinearDiscriminantAnalysis


def evaluar_config(config, modelo, args):
    ses, suj, informes = preparar_config(config, FS_NATIVA, args.data,
                                         cache_dir=os.path.expanduser(args.cache))
    pv = parametros_ventana(200, 0.9, FS_NATIVA)
    F, X, y, subj = ventanear(ses, suj, pv["w"], pv["stride"], args.variante,
                              con_crudo=(modelo == "cnn"))
    y, F, X, subj = submuestrear_rest(y, F, X, subj)

    y_pred = np.empty_like(y)
    rng = np.random.RandomState(args.seed)
    for k, (tr, te) in enumerate(particiones_por_sujeto(y, subj)):
        if modelo == "lda":
            m = LinearDiscriminantAnalysis(solver="lsqr", shrinkage="auto")
            m.fit(F[tr], y[tr])
            y_pred[te] = m.predict(F[te])
        else:
            from entrenamiento_cv import entrenar_pliegue
            if len(tr) > args.n_max:
                tr = rng.choice(tr, args.n_max, replace=False)
            Y = np.eye(NUM_CLASES, dtype=np.float32)[y]
            _, prob, _ = entrenar_pliegue(X[tr], Y[tr], X[te], Y[te], k,
                                          args.epochs, 32, 1e-3,
                                          early_stopping_start=10,
                                          seed=args.seed)
            y_pred[te] = prob.argmax(axis=1)

    # deteccion de onset por configuracion: muestra si el filtro de un
    # ciclo resolvio la alternancia
    bloques = [b for inf in informes for b in inf["bloques"]]
    sin_onset = sum(b["onset_ms"] is None for b in bloques)
    return por_sujeto(y, y_pred, subj), metricas(y, y_pred), \
        dict(bloques=len(bloques), sin_onset=sin_onset)


def main():
    p = argparse.ArgumentParser(description="1.b Longitud de onda")
    p.add_argument("--modelo", choices=["lda", "cnn"], default="lda")
    p.add_argument("--variante", default="dinamica_meseta")
    p.add_argument("--n_max", type=int, default=40000)
    p.add_argument("--epochs", type=int, default=100)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--data", default=RUTA_DATASET_DEFECTO)
    p.add_argument("--cache", default="~/cache_lmg")
    p.add_argument("--output", default=os.path.join(AQUI, "resultados"))
    args = p.parse_args()
    os.makedirs(args.output, exist_ok=True)

    filas, globales = [], []
    for cfg in CONFIGS:
        print(f"\n=== {cfg} ({args.modelo}) ===")
        ps, g, det = evaluar_config(cfg, args.modelo, args)
        for s, m in ps.items():
            filas.append(dict(subj=s, config=cfg, accuracy=m["accuracy"],
                              f1_macro=m["f1_macro"]))
        globales.append(dict(config=cfg, **{k: v for k, v in g.items()
                                            if k != "f1_por_clase"},
                             f1_por_clase=json.dumps(g["f1_por_clase"]),
                             bloques_sin_onset=det["sin_onset"],
                             bloques=det["bloques"]))
        print(f"  acc {g['accuracy']:.4f}  F1 {g['f1_macro']:.4f}  "
              f"(bloques sin onset: {det['sin_onset']}/{det['bloques']})")

    tabla = pd.DataFrame(filas)
    tabla.to_csv(os.path.join(args.output,
                              f"longitud_onda_{args.modelo}_por_sujeto.csv"),
                 index=False)
    pd.DataFrame(globales).to_csv(
        os.path.join(args.output, f"longitud_onda_{args.modelo}_global.csv"),
        index=False)

    # ---------- Estadistica ----------
    from statsmodels.stats.anova import AnovaRM
    from scipy.stats import friedmanchisquare, ttest_rel, wilcoxon

    lineas = [f"ANALISIS 1.b - longitud de onda ({args.modelo})", ""]
    for metrica in ("accuracy", "f1_macro"):
        aov = AnovaRM(tabla, depvar=metrica, subject="subj",
                      within=["config"]).fit()
        r = aov.anova_table.iloc[0]
        ancho = tabla.pivot(index="subj", columns="config", values=metrica)
        fr = friedmanchisquare(*[ancho[c] for c in CONFIGS])
        t = ttest_rel(ancho["green"], ancho["ir"])
        w = wilcoxon(ancho["green"], ancho["ir"])
        lineas += [
            f"--- {metrica} ---",
            "  media por configuracion: " + "  ".join(
                f"{c} {ancho[c].mean():.4f}" for c in CONFIGS),
            f"  ANOVA medidas repetidas: F({int(r['Num DF'])},"
            f"{int(r['Den DF'])}) = {r['F Value']:.3f}, p = {r['Pr > F']:.4f}",
            f"  Friedman: chi2 = {fr.statistic:.3f}, p = {fr.pvalue:.4f}",
            f"  verde vs IR (la comparacion limpia): t pareada p = "
            f"{t.pvalue:.4f}, Wilcoxon p = {w.pvalue:.4f}, "
            f"diferencia media {(ancho['green']-ancho['ir']).mean():+.4f}",
            "",
        ]
    lineas += [
        "Nota: AnovaRM no aplica correccion de esfericidad "
        "(Greenhouse-Geisser); con 4 niveles conviene contrastar con "
        "Friedman, que no la requiere.",
        "Extrapolacion: el IR del dataset es 880 nm; nuestro LED es 940 nm.",
    ]
    texto = "\n".join(lineas)
    print("\n" + texto)
    with open(os.path.join(args.output,
                           f"longitud_onda_{args.modelo}_estadistica.txt"),
              "w", encoding="utf-8") as f:
        f.write(texto)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ancho = tabla.pivot(index="subj", columns="config", values="accuracy")
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for s in ancho.index:
        ax.plot(CONFIGS, ancho.loc[s, CONFIGS], "-", color="gray", alpha=0.4)
    # tick_labels: matplotlib >= 3.9 retiro el argumento labels.
    ax.boxplot([ancho[c] for c in CONFIGS], tick_labels=CONFIGS, widths=0.4)
    ax.set_ylabel("accuracy por sujeto")
    ax.set_title(f"Configuracion de iluminacion ({args.modelo}); "
                 f"lineas = mismo sujeto")
    ax.grid(alpha=0.3)
    plt.savefig(os.path.join(args.output,
                             f"longitud_onda_{args.modelo}.png"),
                dpi=150, bbox_inches="tight")


if __name__ == "__main__":
    main()
