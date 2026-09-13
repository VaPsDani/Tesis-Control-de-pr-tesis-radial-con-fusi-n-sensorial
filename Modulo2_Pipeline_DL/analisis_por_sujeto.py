"""
analisis_por_sujeto.py - sujeto frente a sujeto_rest con 10 sujetos pareados
=============================================================================
Pregunta: ¿hay diferencia demostrable entre normalizar con TODOS los datos
del sujeto y hacerlo solo con su REPOSO (CALIB_SOLO_REPOSO del firmware)?

Con 5 pliegues el Wilcoxon no puede bajar de p = 0.062. Cada sujeto aparece
en exactamente un conjunto de test, asi que las predicciones por ventana
dan 10 valores pareados, con p minimo de 0.002.

QUE SE REPORTA
  - Exactitud y F1 macro por sujeto en ambas configuraciones.
  - Wilcoxon y t pareadas sobre los 10 sujetos, y d de Cohen pareada
    (d_z = media de las diferencias / desviacion de las diferencias).
  - Desviacion ENTRE SUJETOS de cada configuracion (ddof = 1) y su cociente
    rest/sujeto. Es el argumento real de CALIB_SOLO_REPOSO.
  - Test de Pitman-Morgan: igualdad de varianzas en muestras PAREADAS
    (correlacion entre suma y diferencia).
  - Intervalo bootstrap al 95% del cociente de desviaciones, remuestreando
    sujetos pareados.

DECISIONES FIJADAS ANTES DE VER LOS DATOS
  - El intervalo que decide es el BCa (corrige sesgo y asimetria, adecuado
    con n = 10). El percentil se reporta como referencia. Si BCa no puede
    calcularse, decide el percentil y se dice.
  - Regla acordada para el deja-un-sujeto-fuera, sobre la exactitud:
      el intervalo incluye 1.0 y su extremo superior es < 1.15  -> lanzarlo
      en cualquier otro caso (excluye 1, o lo incluye con holgura) -> no

ADVERTENCIA DE DEPENDENCIA
  Con 5 pliegues, los dos sujetos de un mismo pliegue comparten modelo. Los
  10 pares no son independientes: la n efectiva esta entre 5 y 10 y los p
  nominales son algo optimistas. Por la misma razon, la desviacion entre
  sujetos mezcla la dificultad propia de cada sujeto con el modelo que le
  toco. Mezcla menos que la desviacion entre pliegues, pero no es cero. El
  deja-un-sujeto-fuera (un modelo por sujeto) elimina el primer problema.
"""

import argparse
import json
import os

import numpy as np
from scipy import stats
from sklearn.metrics import f1_score

NUM_CLASES = 5
UMBRAL_LOSO = 1.15


def por_sujeto(ruta_npz):
    d = np.load(ruta_npz)
    suj, yt, pl = d["sujeto"], d["y_true"], d["pliegue"]
    yp = d["prob"].argmax(axis=1)
    out = {}
    for s in np.unique(suj):
        m = suj == s
        pls = np.unique(pl[m])
        out[int(s)] = dict(
            acc=100 * float(np.mean(yt[m] == yp[m])),
            f1=100 * float(f1_score(yt[m], yp[m], average="macro",
                                    labels=range(NUM_CLASES), zero_division=0)),
            pliegues=[int(p) + 1 for p in pls], n=int(m.sum()))
    por_pliegue = {int(p) + 1: 100 * float(np.mean(yt[pl == p] == yp[pl == p]))
                   for p in np.unique(pl)}
    return out, por_pliegue


def pitman_morgan(x, y):
    """Igualdad de varianzas de dos muestras pareadas."""
    r = float(np.corrcoef(x + y, x - y)[0, 1])
    n = len(x)
    t = r * np.sqrt((n - 2) / (1 - r ** 2))
    return r, float(t), float(2 * stats.t.sf(abs(t), n - 2))


def cociente_sd(rest, sujeto):
    return np.std(rest, ddof=1) / np.std(sujeto, ddof=1)


def intervalos(rest, sujeto, n_boot, semilla):
    res = {}
    for metodo in ("BCa", "percentile"):
        try:
            b = stats.bootstrap((rest, sujeto), cociente_sd, paired=True,
                                vectorized=False, n_resamples=n_boot,
                                confidence_level=0.95, method=metodo,
                                random_state=semilla)
            lo, hi = float(b.confidence_interval.low), float(b.confidence_interval.high)
            res[metodo] = (lo, hi) if np.isfinite(lo) and np.isfinite(hi) else None
        except Exception as e:          # BCa puede degenerar con n pequeno
            res[metodo] = None
            res[metodo + "_error"] = str(e)[:200]
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--sujeto", required=True, help="predicciones_*.npz de 'sujeto'")
    ap.add_argument("--rest", required=True, help="predicciones_*.npz de 'sujeto_rest'")
    ap.add_argument("--salida", required=True)
    ap.add_argument("--etiqueta", default="5 pliegues")
    ap.add_argument("--ref_sujeto", default=None, help="JSON de cc872da para comprobar consistencia")
    ap.add_argument("--ref_rest", default=None)
    ap.add_argument("--n_boot", type=int, default=10000)
    ap.add_argument("--semilla", type=int, default=42)
    args = ap.parse_args()
    os.makedirs(args.salida, exist_ok=True)

    a, a_pl = por_sujeto(args.sujeto)
    b, b_pl = por_sujeto(args.rest)
    subs = sorted(set(a) & set(b))
    assert len(subs) == len(a) == len(b), "los dos archivos no tienen los mismos sujetos"
    n = len(subs)

    L = []
    w = L.append
    w(f"SUJETO FRENTE A SUJETO_REST, POR SUJETO ({args.etiqueta}, n = {n})")
    w("=" * 78)
    w("")
    w("1. TABLA POR SUJETO (%)")
    w(f"   {'sujeto':>6}{'pliegue':>9}{'acc sujeto':>12}{'acc rest':>10}{'dif':>8}"
      f"{'F1 sujeto':>11}{'F1 rest':>9}{'dif':>8}")
    for s in subs:
        w(f"   {s:>6}{str(a[s]['pliegues']):>9}{a[s]['acc']:12.2f}{b[s]['acc']:10.2f}"
          f"{a[s]['acc'] - b[s]['acc']:+8.2f}{a[s]['f1']:11.2f}{b[s]['f1']:9.2f}"
          f"{a[s]['f1'] - b[s]['f1']:+8.2f}")

    resultado = {"etiqueta": args.etiqueta, "n_sujetos": n, "metricas": {}}
    w("")
    w("2. DIFERENCIA DE MEDIAS (sujeto - sujeto_rest)")
    for clave, nombre in (("acc", "exactitud"), ("f1", "F1 macro")):
        x = np.array([a[s][clave] for s in subs])
        y = np.array([b[s][clave] for s in subs])
        d = x - y
        wil = stats.wilcoxon(x, y)
        tt = stats.ttest_rel(x, y)
        dz = float(d.mean() / d.std(ddof=1))
        sd_x, sd_y = float(np.std(x, ddof=1)), float(np.std(y, ddof=1))
        pm = pitman_morgan(x, y)
        ic = intervalos(y, x, args.n_boot, args.semilla)
        resultado["metricas"][clave] = dict(
            media_sujeto=float(x.mean()), media_rest=float(y.mean()),
            diferencia_media=float(d.mean()), wilcoxon_p=float(wil.pvalue),
            t=float(tt.statistic), t_p=float(tt.pvalue), d_z=dz,
            sd_entre_sujetos_sujeto=sd_x, sd_entre_sujetos_rest=sd_y,
            cociente_sd_rest_sobre_sujeto=sd_y / sd_x,
            pitman_morgan_r=pm[0], pitman_morgan_t=pm[1], pitman_morgan_p=pm[2],
            ic95_bca=ic.get("BCa"), ic95_percentil=ic.get("percentile"),
            ic95_bca_error=ic.get("BCa_error"))
        w(f"   {nombre}: sujeto {x.mean():.2f}, rest {y.mean():.2f}, diferencia "
          f"{d.mean():+.2f}  |  Wilcoxon p = {wil.pvalue:.4f} (minimo {2 / 2 ** n:.4f}), "
          f"t({n - 1}) = {tt.statistic:.2f}, p = {tt.pvalue:.4f}, d_z = {dz:+.2f}")

    w("")
    w("3. DESVIACION ENTRE SUJETOS (ddof = 1) - la cifra que decide")
    for clave, nombre in (("acc", "exactitud"), ("f1", "F1 macro")):
        r = resultado["metricas"][clave]
        bca = r["ic95_bca"]
        per = r["ic95_percentil"]
        w(f"   {nombre}: sujeto {r['sd_entre_sujetos_sujeto']:.2f}, rest "
          f"{r['sd_entre_sujetos_rest']:.2f}, cociente rest/sujeto "
          f"{r['cociente_sd_rest_sobre_sujeto']:.3f}")
        w(f"      IC 95% BCa: " + (f"[{bca[0]:.3f}, {bca[1]:.3f}]" if bca else
                                   f"no calculable ({r['ic95_bca_error']})")
          + "   percentil: " + (f"[{per[0]:.3f}, {per[1]:.3f}]" if per else "no calculable"))
        w(f"      Pitman-Morgan: r = {r['pitman_morgan_r']:+.3f}, t({n - 2}) = "
          f"{r['pitman_morgan_t']:+.2f}, p = {r['pitman_morgan_p']:.4f}")

    # ---- decision pre-registrada ----
    r = resultado["metricas"]["acc"]
    ic_dec, metodo = (r["ic95_bca"], "BCa") if r["ic95_bca"] else (r["ic95_percentil"], "percentil")
    lo, hi = ic_dec
    incluye = lo <= 1.0 <= hi
    lanzar = bool(incluye and hi < UMBRAL_LOSO)
    if not incluye:
        lectura = ("el intervalo EXCLUYE 1: la dispersion entre sujetos de sujeto_rest es "
                   + ("menor" if hi < 1.0 else "mayor") + " que la de sujeto")
    elif lanzar:
        lectura = (f"el intervalo incluye 1 POR POCO (extremo superior {hi:.3f} < {UMBRAL_LOSO}): "
                   f"ambiguo, se lanza el deja-un-sujeto-fuera")
    else:
        lectura = (f"el intervalo incluye 1 CON HOLGURA (extremo superior {hi:.3f} >= {UMBRAL_LOSO}): "
                   f"no hay evidencia de diferencia de dispersion")
    resultado["decision"] = dict(metodo_intervalo=metodo, ic95=[lo, hi], incluye_1=incluye,
                                 umbral=UMBRAL_LOSO, lanzar_loso=lanzar, lectura=lectura)
    w("")
    w(f"4. DECISION (regla acordada, intervalo {metodo} del cociente de exactitud)")
    w(f"   IC 95% [{lo:.3f}, {hi:.3f}] -> {lectura}")
    w(f"   lanzar_loso = {lanzar}")

    # ---- consistencia con cc872da ----
    if args.ref_sujeto and args.ref_rest:
        w("")
        w("5. CONSISTENCIA CON LA CORRIDA cc872da (exactitud por pliegue)")
        for nombre, pl_nuevo, ruta in (("sujeto", a_pl, args.ref_sujeto),
                                       ("sujeto_rest", b_pl, args.ref_rest)):
            ref = json.load(open(ruta, encoding="utf-8"))
            pls = next(v for v in ref.values() if isinstance(v, list) and v
                       and isinstance(v[0], dict) and "accuracy" in v[0])
            viejo = [100 * p["accuracy"] for p in pls]
            nuevo = [pl_nuevo[i + 1] for i in range(len(viejo))]
            w(f"   {nombre:<12} cc872da [{', '.join(f'{v:.2f}' for v in viejo)}] media "
              f"{np.mean(viejo):.2f}")
            w(f"   {'':<12} ahora   [{', '.join(f'{v:.2f}' for v in nuevo)}] media "
              f"{np.mean(nuevo):.2f}  (diferencia {np.mean(nuevo) - np.mean(viejo):+.2f}; "
              f"ruido esperado entre corridas ~0.6)")

    w("")
    w("ADVERTENCIA: " + ("con 5 pliegues, los dos sujetos de cada pliegue comparten modelo; "
                         "los 10 pares no son independientes y los p nominales son algo "
                         "optimistas. La desviacion entre sujetos tambien incluye la "
                         "variacion entre los modelos de cada pliegue."
                         if "5" in args.etiqueta else
                         "deja-un-sujeto-fuera: cada sujeto tiene su propio modelo, los 10 "
                         "pares son independientes entre si."))

    texto = "\n".join(L)
    print(texto)
    base = "analisis_por_sujeto"
    with open(os.path.join(args.salida, base + ".txt"), "w", encoding="utf-8") as f:
        f.write(texto + "\n")
    with open(os.path.join(args.salida, base + ".json"), "w", encoding="utf-8") as f:
        json.dump(resultado, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
