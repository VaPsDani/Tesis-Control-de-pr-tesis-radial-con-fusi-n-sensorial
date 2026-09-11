"""
analisis_canales.py - 1.c  Cuantos canales hacen falta
======================================================
El dataset tiene 40 canales; nuestro brazalete tiene 5. La pregunta es
si 5 modulos son una limitacion presupuestaria o una decision respaldada.

TRES PIEZAS:
  1. Curva de desempeno contra numero de canales por ELIMINACION HACIA
     ATRAS: desde 40 se quita en cada paso el canal cuya ausencia menos
     perjudica, hasta quedar 1.
  2. Busqueda EXHAUSTIVA de los mejores subconjuntos de 3 y 4 canales
     (9 880 y 91 390 combinaciones).
  3. Para 5 y 6 canales, exhaustiva ACOTADA a los 15 canales mejor
     situados en la eliminacion hacia atras (3 003 y 5 005 combinaciones).
     La exhaustiva completa serian 658 008 y 3 838 380 por configuracion,
     de horas a dias de computo. Se documenta como busqueda acotada.

SESGO DEL GANADOR — y como se corrige:
  Elegir el mejor subconjunto con los mismos pliegues con que se reporta
  su puntuacion es OPTIMISTA: entre miles de candidatos alguno sale bien
  por azar. Por eso el mejor subconjunto de 5 canales se evalua ademas
  con VALIDACION ANIDADA: en cada pliegue externo la seleccion completa
  (eliminacion hacia atras + busqueda acotada) se hace solo con los
  sujetos de entrenamiento, y el subconjunto elegido se evalua en el
  sujeto de test, que nunca intervino en la eleccion. Ese es el numero
  honesto.

REFERENCIA: 1 000 subconjuntos de 5 canales al azar. La diferencia entre
el mejor y la mediana aleatoria mide cuanto importa ELEGIR la ubicacion,
que es el argumento de diseno.

UBICACION ANATOMICA: el dataset no la documenta. Se reportan indices de
canal.

Clasificador: LDA por estadisticos suficientes (evaluacion.LDARapido),
necesario para que la busqueda sea viable. Caracteristicas: media y
desviacion por canal en ventanas de 200 ms.
"""

import argparse
import itertools
import json
import os
import sys
import time

import numpy as np
import pandas as pd

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
from datos import (FS_NATIVA, NUM_CLASES, RUTA_DATASET_DEFECTO,  # noqa
                   parametros_ventana, preparar_config, submuestrear_rest,
                   ventanear)
from evaluacion import (LDARapido, indices_caracteristicas,  # noqa
                        particiones_por_sujeto)

from sklearn.metrics import f1_score

N_CANALES = 40
TOP_ACOTADA = 15


def f1(y, p):
    return f1_score(y, p, average="macro", labels=range(NUM_CLASES),
                    zero_division=0)


class Evaluador:
    """Cachea un LDARapido por pliegue para evaluar subconjuntos al vuelo."""

    def __init__(self, F, y, subj, k=5, idx_filas=None):
        if idx_filas is not None:
            F, y, subj = F[idx_filas], y[idx_filas], subj[idx_filas]
        self.F, self.y = F, y
        self.pliegues = []
        for tr, te in particiones_por_sujeto(y, subj, k):
            self.pliegues.append((LDARapido(F[tr], y[tr]), te))

    def puntuar(self, canales):
        idx = indices_caracteristicas(canales, N_CANALES)
        return float(np.mean([f1(self.y[te], m.predecir(self.F[te], idx))
                              for m, te in self.pliegues]))


def eliminacion_hacia_atras(ev, verbose=True):
    restantes = list(range(N_CANALES))
    curva = [dict(n_canales=N_CANALES, f1=ev.puntuar(restantes),
                  canales=json.dumps(restantes))]
    orden_eliminacion = []
    while len(restantes) > 1:
        mejor, mejor_f1 = None, -1
        for c in restantes:
            f = ev.puntuar([r for r in restantes if r != c])
            if f > mejor_f1:
                mejor, mejor_f1 = c, f
        restantes.remove(mejor)
        orden_eliminacion.append(mejor)
        curva.append(dict(n_canales=len(restantes), f1=mejor_f1,
                          canales=json.dumps(sorted(restantes))))
        if verbose and len(restantes) % 5 == 0:
            print(f"    {len(restantes):>2} canales: F1 {mejor_f1:.4f}")
    orden_eliminacion.append(restantes[0])
    # ranking: el ultimo en eliminarse es el mas valioso
    return pd.DataFrame(curva), orden_eliminacion[::-1]


def ranking_desde_curva(curva):
    """Reconstruye el ranking de la eliminacion hacia atras desde su CSV:
    el canal quitado en cada paso es la diferencia entre conjuntos
    consecutivos, y el ultimo que queda es el mas valioso."""
    conjuntos = [set(json.loads(c)) for c in curva.canales]
    orden = [(a - b).pop() for a, b in zip(conjuntos, conjuntos[1:])]
    orden.append(conjuntos[-1].pop())
    return orden[::-1]


def exhaustiva(ev, candidatos, k, top=10):
    res = []
    for comb in itertools.combinations(candidatos, k):
        res.append((ev.puntuar(list(comb)), comb))
    res.sort(key=lambda t: -t[0])
    return res[:top], len(res)


def main():
    p = argparse.ArgumentParser(description="1.c Seleccion de canales")
    p.add_argument("--config", default="ir")
    p.add_argument("--variante", default="dinamica_meseta")
    p.add_argument("--solap", type=float, default=0.5,
                   help="Solapamiento para la busqueda. 50%% reduce las "
                        "ventanas 4x frente al 88%% de produccion sin "
                        "cambiar el ranking de canales, y hace viable la "
                        "exhaustiva.")
    p.add_argument("--n_aleatorios", type=int, default=1000)
    p.add_argument("--sin_anidada", action="store_true")
    p.add_argument("--reusar", action="store_true",
                   help="Si ya existen canales_{curva,exhaustiva,aleatorio5}"
                        ".csv, los carga en vez de recalcularlos.")
    p.add_argument("--data", default=RUTA_DATASET_DEFECTO)
    p.add_argument("--cache", default="~/cache_lmg")
    p.add_argument("--output", default=os.path.join(AQUI, "resultados"))
    args = p.parse_args()
    os.makedirs(args.output, exist_ok=True)

    ses, suj, _ = preparar_config(args.config, FS_NATIVA, args.data,
                                  cache_dir=os.path.expanduser(args.cache))
    pv = parametros_ventana(200, args.solap, FS_NATIVA)
    F, _, y, subj = ventanear(ses, suj, pv["w"], pv["stride"], args.variante)
    y, F, subj = submuestrear_rest(y, F, subj)
    print(f"Ventanas: {len(y)}  caracteristicas: {F.shape[1]}")

    ev = Evaluador(F, y, subj)
    rutas = {n: os.path.join(args.output, f"canales_{n}.csv")
             for n in ("curva", "exhaustiva", "aleatorio5")}

    if args.reusar and all(os.path.exists(r) for r in rutas.values()):
        # Las piezas 1-3 son deterministas; recalcularlas repite ~25 min.
        print("\n[1-3] Reutilizando curva, exhaustiva y aleatorios ya calculados")
        curva = pd.read_csv(rutas["curva"])
        ranking = ranking_desde_curva(curva)
        filas = pd.read_csv(rutas["exhaustiva"]).to_dict("records")
        aleat = pd.read_csv(rutas["aleatorio5"]).f1.tolist()
        print(f"    Ranking (mas valioso primero): {ranking[:10]}")
    else:
        # ---------- 1. Eliminacion hacia atras ----------
        print("\n[1] Eliminacion hacia atras 40 -> 1")
        t0 = time.time()
        curva, ranking = eliminacion_hacia_atras(ev)
        curva.to_csv(rutas["curva"], index=False)
        print(f"    {time.time()-t0:.0f} s.  Ranking (mas valioso primero): "
              f"{ranking[:10]}")

        # ---------- 2 y 3. Exhaustiva completa y acotada ----------
        filas = []
        top15 = ranking[:TOP_ACOTADA]
        for k in (3, 4, 5, 6):
            candidatos = list(range(N_CANALES)) if k <= 4 else top15
            modo = "completa" if k <= 4 else f"acotada top-{TOP_ACOTADA}"
            t0 = time.time()
            mejores, n = exhaustiva(ev, candidatos, k)
            print(f"\n[{'2' if k <= 4 else '3'}] Exhaustiva {modo}, k={k}: "
                  f"{n} subconjuntos, {time.time()-t0:.0f} s")
            for rango, (f, comb) in enumerate(mejores, 1):
                filas.append(dict(k=k, modo=modo, rango=rango, f1=f,
                                  canales=json.dumps(list(comb)),
                                  n_evaluados=n))
            print(f"    mejor: {list(mejores[0][1])}  F1 {mejores[0][0]:.4f}")
        pd.DataFrame(filas).to_csv(rutas["exhaustiva"], index=False)

        # ---------- Referencia aleatoria de 5 canales ----------
        rng = np.random.RandomState(42)
        aleat = [ev.puntuar(sorted(rng.choice(N_CANALES, 5, replace=False)))
                 for _ in range(args.n_aleatorios)]
        pd.DataFrame(dict(f1=aleat)).to_csv(rutas["aleatorio5"], index=False)

    mejor5 = max(f for f in (r["f1"] for r in filas if r["k"] == 5))
    print(f"\n[ref] 5 canales al azar ({len(aleat)}): mediana "
          f"{np.median(aleat):.4f}  p95 {np.percentile(aleat, 95):.4f}  "
          f"-> mejor seleccionado {mejor5:.4f} (percentil "
          f"{100*np.mean(np.array(aleat) < mejor5):.1f})")

    # ---------- Validacion anidada del mejor subconjunto de 5 ----------
    anidada = []
    if not args.sin_anidada:
        print("\n[anidada] Seleccion de 5 canales dentro de cada pliegue externo")
        for k_ext, (tr, te) in enumerate(particiones_por_sujeto(y, subj)):
            t0 = time.time()
            ev_int = Evaluador(F, y, subj, k=4, idx_filas=tr)
            _, rank_int = eliminacion_hacia_atras(ev_int, verbose=False)
            mejores_int, _ = exhaustiva(ev_int, rank_int[:TOP_ACOTADA], 5, 1)
            f_int, comb = mejores_int[0]
            # evaluar en el sujeto de test externo, que no intervino
            m = LDARapido(F[tr], y[tr])
            idx = indices_caracteristicas(list(comb), N_CANALES)
            f_ext = f1(y[te], m.predecir(F[te], idx))
            anidada.append(dict(pliegue=k_ext + 1, canales=json.dumps(list(comb)),
                                f1_interno=f_int, f1_externo=f_ext,
                                sujetos_test=json.dumps(
                                    sorted(np.unique(subj[te]).tolist()))))
            print(f"    pliegue {k_ext+1}: {list(comb)}  F1 interno "
                  f"{f_int:.4f} -> externo {f_ext:.4f}  ({time.time()-t0:.0f} s)")
        an = pd.DataFrame(anidada)
        an.to_csv(os.path.join(args.output, "canales_anidada.csv"), index=False)
        print(f"    F1 honesto (anidado): {an.f1_externo.mean():.4f} "
              f"+/- {an.f1_externo.std():.4f}   vs optimista {mejor5:.4f}")

    # ---------- Figura ----------
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(curva.n_canales, curva.f1, "o-", ms=3,
            label="eliminacion hacia atras")
    for k in (3, 4, 5, 6):
        fk = max(r["f1"] for r in filas if r["k"] == k)
        ax.plot(k, fk, "r*", ms=12)
    ax.plot([], [], "r*", ms=12, label="mejor subconjunto (exhaustiva)")
    ax.axhline(np.median(aleat), color="gray", ls=":",
               label="mediana de 5 canales al azar")
    if anidada:
        ax.errorbar(5, an.f1_externo.mean(), yerr=an.f1_externo.std(),
                    fmt="gs", capsize=4, label="5 canales, anidado (honesto)")
    ax.axvline(5, color="k", lw=0.5)
    ax.set_xlabel("numero de canales")
    ax.set_ylabel("F1 macro (LDA, GroupKFold por sujeto)")
    ax.set_title(f"Desempeno contra numero de canales ({args.config})")
    ax.invert_xaxis()
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    ruta = os.path.join(args.output, "canales_curva.png")
    plt.savefig(ruta, dpi=150, bbox_inches="tight")
    print(f"[FIG] {ruta}")

    with open(os.path.join(args.output, "canales_ranking.json"), "w") as f:
        json.dump(dict(ranking=[int(c) for c in ranking],
                       ubicacion_anatomica="no documentada en el dataset"),
                  f, indent=2)


if __name__ == "__main__":
    main()
