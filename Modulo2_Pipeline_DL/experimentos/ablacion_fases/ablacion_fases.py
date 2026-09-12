"""
ablacion_fases.py - Que fases entran como la clase del gesto
============================================================
Tarea 4. Compara tres variantes de ENTRENAMIENTO (fases.VARIANTES_ABLACION):

  solo_meseta          el gesto sostenido
  dinamica_meseta      la transicion y el gesto sostenido (defecto del pipeline)
  todo_con_reaccion    ademas el tramo de reaccion, en que la mano sigue quieta

Chen et al. lo mostraron sobre sEMG; sobre LMG no existe el equivalente.

EL CONJUNTO DE TEST ES EL MISMO PARA LAS TRES - la decision central:
  Si cada variante se evaluara sobre sus propias filas, solo_meseta se
  mediria sobre ventanas de meseta, las mas faciles, y ganaria por
  construccion. Aqui las tres se evaluan sobre las MISMAS ventanas: gesto
  en dinamica o meseta, y reposo estable. Ademas se reporta la exactitud
  POR FASE, porque es donde deberia verse el efecto: la dinamica es
  apenas un 3% de un bloque de 15 s y apenas mueve la exactitud global,
  pero es lo que la protesis tiene que reconocer para responder a tiempo.

  Las ventanas de reaccion se evaluan aparte. La mano sigue en reposo,
  asi que lo deseable es que se clasifiquen como Rest: se reporta que
  fraccion lo hace. Entrenar con la reaccion como gesto deberia
  empeorarlo, y ese es el coste de la tercera variante.

VENTANAS: 200 ms con stride de 20 ms, los del pipeline de produccion,
  dentro de un bloque de etiqueta constante y de un tramo continuo (sin
  cruzar pausas). Cada ventana toma la fase de su ULTIMA muestra: es la
  decision que tomaria la protesis en ese instante con una ventana causal.

NORMALIZACION: en las capturas propias, z-score por sesion con el bloque
  de calibracion, que es lo que hace el firmware (CALIB_SOLO_REPOSO). El
  bloque de calibracion no entra ni a entrenamiento ni a test.

PARTICION: GroupKFold por sujeto, con verificacion de fuga. Con un solo
  sujeto (un piloto) solo corre con --permitir_intra_sujeto, agrupando
  por repeticion, y el resultado se etiqueta intra-sujeto en todas las
  salidas.

FUENTES:
  --csv s01.csv s02.csv ...   sesiones propias (anotadas o no con anotar_fases)
  --lmg_publico --config ir   lmg_wavelength_dataset (40 canales, sin IMU).
                              Es un SUSTITUTO hasta tener el piloto, no el
                              resultado del articulo.

Uso:
  python ablacion_fases.py --csv ../../captura/sesiones/*.csv
  python ablacion_fases.py --lmg_publico --config ir --data ~/data/lmg_wavelength_dataset
"""

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import wilcoxon
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.metrics import confusion_matrix, f1_score
from sklearn.model_selection import GroupKFold

AQUI = os.path.dirname(os.path.abspath(__file__))
MODULO2 = os.path.abspath(os.path.join(AQUI, "..", ".."))
if MODULO2 not in sys.path:
    sys.path.insert(0, MODULO2)

from fases import (FASE_DINAMICA, FASE_MESETA, FASE_REACCION,  # noqa: E402
                   FASE_REPOSO, FASES_VERSION, VARIANTES_ABLACION)

NUM_CLASES = 5
FASES_TEST = (FASE_DINAMICA, FASE_MESETA)
NOMBRES_CAPTURA = ["Rest", "Pinch", "Tripod", "Power", "Finger_Ext"]
NOMBRES_PUBLICO = ["Rest", "Pinch", "Tripod", "Power", "Extension"]


# ============================================================
# CARGA
# ============================================================
def cargar_capturas(rutas):
    from anotar_fases import anotar_df, ruta_sidecar
    from preprocesamiento import COLUMNAS_MODELO

    sesiones = []
    for r in rutas:
        df = pd.read_csv(r)
        vigente = "fase" in df.columns
        if vigente and os.path.exists(ruta_sidecar(r)):
            with open(ruta_sidecar(r), encoding="utf-8") as f:
                vigente = json.load(f).get("fases_version") == FASES_VERSION
        if vigente:
            fase = df["fase"].astype(str).to_numpy()
        else:
            base = df.drop(columns="fase") if "fase" in df.columns else df
            fase = anotar_df(base)[0].astype(str)
            print(f"  {os.path.basename(r)}: fase calculada al vuelo")

        x = df[COLUMNAS_MODELO].to_numpy(np.float64)
        y = df["label"].to_numpy(np.int64).copy()
        cal = (df["es_calibracion"].to_numpy() == 1
               if "es_calibracion" in df.columns else np.zeros(len(df), bool))
        ref = cal.copy()
        if "en_margen" in df.columns:
            ref &= df["en_margen"].to_numpy() == 0
        if ref.sum() < 50:                 # sin calibracion: reposo estable
            ref = (fase == FASE_REPOSO) & (y == 0)
        mu = x[ref].mean(axis=0)
        sd = np.where(x[ref].std(axis=0) < 1e-9, 1e-9, x[ref].std(axis=0))
        y[cal] = -1

        ts = df["timestamp_ms"].to_numpy(np.float64)
        periodo = float(np.median(np.diff(ts)))
        tramo = np.r_[0, np.cumsum(np.diff(ts) > 3 * periodo)]
        sesiones.append(dict(
            x=(x - mu) / sd, y=y, fase=fase, subj=int(df["subject_id"].iloc[0]),
            rep=df["repetition_id"].to_numpy(np.int64), tramo=tramo,
            fs=1000.0 / periodo))
    return sesiones


def cargar_publico(config, data, cache):
    sys.path.insert(0, os.path.join(MODULO2, "experimentos", "lmg_wavelength"))
    from datos import FS_NATIVA, listar_archivos, preparar_config

    ses, suj, _ = preparar_config(config, FS_NATIVA, data,
                                  cache_dir=os.path.expanduser(cache))
    inv = listar_archivos(data, config)      # mismo orden que preparar_config
    out = []
    for s, sid, rep in zip(ses, suj, inv.rep):
        n = len(s["y"])
        out.append(dict(x=s["x"], y=s["y"], fase=np.asarray(s["fase"]).astype(str),
                        subj=int(sid), rep=np.full(n, int(rep)),
                        tramo=np.zeros(n, int), fs=FS_NATIVA))
    return out


# ============================================================
# VENTANAS
# ============================================================
def ventanear(sesiones, w, stride, crudo=False):
    """Ventanas dentro de un bloque y un tramo continuo; fase = ultima muestra."""
    F, X, Y, FA, S, R = [], [], [], [], [], []
    for s in sesiones:
        y, tr = s["y"], s["tramo"]
        cortes = np.flatnonzero((np.diff(y) != 0) | (np.diff(tr) != 0)) + 1
        for a, z in zip(np.r_[0, cortes], np.r_[cortes, len(y)]):
            if y[a] < 0 or z - a < w:
                continue
            v = np.lib.stride_tricks.sliding_window_view(
                s["x"][a:z], w, axis=0)[::stride]          # (n, C, w)
            ult = a + w - 1 + stride * np.arange(len(v))
            F.append(np.concatenate([v.mean(-1), v.std(-1)], 1).astype(np.float32))
            if crudo:
                X.append(np.transpose(v, (0, 2, 1)).astype(np.float32))
            Y.append(np.full(len(v), y[a]))
            FA.append(s["fase"][ult])
            S.append(np.full(len(v), s["subj"]))
            R.append(s["rep"][ult])
    cat = np.concatenate
    return (cat(F), cat(X) if crudo else None, cat(Y), cat(FA), cat(S), cat(R))


def submuestrear_rest(idx, y, rng):
    """Rest a la media de las clases activas, la misma regla del pipeline."""
    i0 = idx[y[idx] == 0]
    activas = [int(np.sum(y[idx] == c)) for c in range(1, NUM_CLASES)]
    objetivo = int(np.mean(activas)) if activas else len(i0)
    if len(i0) > objetivo:
        i0 = rng.choice(i0, objetivo, replace=False)
    return np.sort(np.r_[i0, idx[y[idx] != 0]])


# ============================================================
# MODELO
# ============================================================
def ajustar_predecir(args, F, X, y, tr, te, pliegue, rng):
    if args.modelo == "lda":
        m = LinearDiscriminantAnalysis(solver="lsqr", shrinkage="auto")
        return m.fit(F[tr], y[tr]).predict(F[te])
    from entrenamiento_cv import entrenar_pliegue   # importa TensorFlow
    if len(tr) > args.n_max:
        tr = np.sort(rng.choice(tr, args.n_max, replace=False))
    Y = np.eye(NUM_CLASES, dtype=np.float32)[y]
    # entrenar_pliegue usa el pliegue de test para la parada temprana,
    # igual que el resto del pipeline: optimista en absoluto, pero igual
    # para las tres variantes, que es lo que se compara.
    _, prob, _ = entrenar_pliegue(X[tr], Y[tr], X[te], Y[te], pliegue,
                                  args.epochs, 32, 1e-3,
                                  early_stopping_start=10, seed=args.seed)
    return prob.argmax(axis=1)


def _acc(yt, yp):
    return float(np.mean(yt == yp)) if len(yt) else np.nan


# ============================================================
# PRINCIPAL
# ============================================================
def main():
    ap = argparse.ArgumentParser(description="Ablacion de fases (Tarea 4)")
    fuente = ap.add_mutually_exclusive_group(required=True)
    fuente.add_argument("--csv", nargs="+", help="CSV de sesiones propias")
    fuente.add_argument("--lmg_publico", action="store_true")
    ap.add_argument("--config", default="ir")
    ap.add_argument("--data", default=os.path.join(
        MODULO2, "..", "data", "lmg_wavelength_dataset"))
    ap.add_argument("--cache", default="~/cache_lmg")
    ap.add_argument("--modelo", choices=["lda", "cnn"], default="lda")
    ap.add_argument("--variantes", nargs="+", default=list(VARIANTES_ABLACION))
    ap.add_argument("--ventana_ms", type=float, default=200.0)
    ap.add_argument("--stride_ms", type=float, default=20.0)
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--permitir_intra_sujeto", action="store_true")
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--n_max", type=int, default=40000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--output", default=None)
    args = ap.parse_args()

    if args.lmg_publico:
        nombre_fuente = f"lmg_publico_{args.config}"
        sesiones = cargar_publico(args.config, args.data, args.cache)
        nombres = NOMBRES_PUBLICO
    else:
        nombre_fuente = "captura"
        sesiones = cargar_capturas(args.csv)
        nombres = NOMBRES_CAPTURA
    out = args.output or os.path.join(AQUI, "resultados",
                                      f"{nombre_fuente}_{args.modelo}")
    os.makedirs(out, exist_ok=True)

    fs = sesiones[0]["fs"]
    w = max(2, int(round(args.ventana_ms * fs / 1000.0)))
    stride = max(1, int(round(args.stride_ms * fs / 1000.0)))
    F, X, y, fase, subj, rep = ventanear(sesiones, w, stride,
                                         crudo=args.modelo == "cnn")

    # ---------- particion ----------
    n_suj = len(np.unique(subj))
    if n_suj >= 2:
        grupos, particion = subj, "GroupKFold por sujeto"
    elif args.permitir_intra_sujeto:
        grupos, particion = rep, "INTRA-SUJETO, GroupKFold por repeticion"
    else:
        sys.exit("Un solo sujeto: la particion por sujeto es imposible. "
                 "Use --permitir_intra_sujeto (el resultado se etiquetara "
                 "intra-sujeto).")
    k = min(args.k, len(np.unique(grupos)))

    es_rest_estable = (y == 0) & (fase == FASE_REPOSO)
    test_comun = es_rest_estable | ((y > 0) & np.isin(fase, FASES_TEST))
    reaccion = (y > 0) & (fase == FASE_REACCION)
    evaluables = test_comun | reaccion

    print(f"Fuente: {nombre_fuente}  modelo: {args.modelo}  particion: "
          f"{particion} (k={k})")
    print(f"Ventanas: {len(y)} ({w} muestras, stride {stride}) - test comun "
          f"{test_comun.sum()}, reaccion {reaccion.sum()}")
    print("Ventanas por fase: " + ", ".join(
        f"{f} {n}" for f, n in zip(*np.unique(fase, return_counts=True))))

    rng = np.random.RandomState(args.seed)
    pred = {v: np.full(len(y), -1) for v in args.variantes}
    pliegue = np.full(len(y), -1)
    n_train = {v: [] for v in args.variantes}
    for kf, (tr, te) in enumerate(GroupKFold(k).split(F, y, grupos)):
        fuga = set(np.unique(grupos[tr])) & set(np.unique(grupos[te]))
        assert not fuga, f"fuga de grupos entre train y test: {fuga}"
        te = te[evaluables[te]]
        pliegue[te] = kf
        for v in args.variantes:
            m_v = es_rest_estable | ((y > 0) & np.isin(fase, VARIANTES_ABLACION[v]))
            tr_v = submuestrear_rest(tr[m_v[tr]], y, rng)
            n_train[v].append(len(tr_v))
            pred[v][te] = ajustar_predecir(args, F, X, y, tr_v, te, kf, rng)
        print(f"  pliegue {kf+1}/{k}: grupos test "
              f"{sorted(np.unique(grupos[te]).tolist())}")

    # ---------- metricas ----------
    ev = test_comun & (pliegue >= 0)
    rc = reaccion & (pliegue >= 0)
    filas_g, filas_c, filas_s = [], [], []
    cms = {}
    for v in args.variantes:
        p = pred[v]
        por_pliegue = [_acc(y[ev & (pliegue == f)], p[ev & (pliegue == f)])
                       for f in range(k)]
        sel_d = ev & (fase == FASE_DINAMICA) & (y > 0)
        sel_m = ev & (fase == FASE_MESETA) & (y > 0)
        filas_g.append(dict(
            variante=v, particion=particion, modelo=args.modelo,
            n_train_medio=int(np.mean(n_train[v])),
            accuracy=_acc(y[ev], p[ev]),
            accuracy_std_pliegues=float(np.nanstd(por_pliegue)),
            f1_macro=float(f1_score(y[ev], p[ev], average="macro",
                                    labels=range(NUM_CLASES), zero_division=0)),
            acc_dinamica=_acc(y[sel_d], p[sel_d]), n_dinamica=int(sel_d.sum()),
            acc_meseta=_acc(y[sel_m], p[sel_m]), n_meseta=int(sel_m.sum()),
            acc_rest=_acc(y[ev & (y == 0)], p[ev & (y == 0)]),
            reaccion_como_rest=float(np.mean(p[rc] == 0)) if rc.any() else np.nan,
            n_reaccion=int(rc.sum()),
        ))
        for c in range(NUM_CLASES):
            s = ev & (y == c)
            filas_c.append(dict(variante=v, clase=nombres[c],
                                exactitud=_acc(y[s], p[s]), n=int(s.sum())))
        for g in np.unique(grupos[pliegue >= 0]):
            sg = grupos == g
            sd_ = sg & ev & (fase == FASE_DINAMICA) & (y > 0)
            filas_s.append(dict(variante=v, grupo=int(g),
                                accuracy=_acc(y[sg & ev], p[sg & ev]),
                                acc_dinamica=_acc(y[sd_], p[sd_])))
        cms[v] = confusion_matrix(y[ev], p[ev], labels=range(NUM_CLASES))
        pd.DataFrame(cms[v], index=nombres, columns=nombres).to_csv(
            os.path.join(out, f"confusion_{v}.csv"))

    g = pd.DataFrame(filas_g)
    c = pd.DataFrame(filas_c)
    s = pd.DataFrame(filas_s)
    g.to_csv(os.path.join(out, "ablacion_global.csv"), index=False)
    c.to_csv(os.path.join(out, "ablacion_por_clase.csv"), index=False)
    s.to_csv(os.path.join(out, "ablacion_por_grupo.csv"), index=False)

    # ---------- contraste pareado por grupo ----------
    lineas = [f"Ablacion de fases - {nombre_fuente}, {args.modelo}, {particion}",
              f"Ventana {args.ventana_ms:.0f} ms, stride {args.stride_ms:.0f} ms, "
              f"fs {fs:.1f} Hz", ""]
    lineas.append(g[["variante", "accuracy", "f1_macro", "acc_dinamica",
                     "acc_meseta", "acc_rest", "reaccion_como_rest"]]
                  .round(4).to_string(index=False))
    lineas.append("")
    lineas.append(c.pivot(index="clase", columns="variante", values="exactitud")
                  .loc[nombres].round(4).to_string())
    ref = "dinamica_meseta"
    n_g = s.grupo.nunique()
    if ref in args.variantes and n_g >= 2:
        lineas += ["", f"Wilcoxon pareado por grupo contra {ref} (n = {n_g}; "
                       f"p minimo alcanzable = {2 / 2 ** n_g:.4f}):"]
        a = s[s.variante == ref].set_index("grupo")
        for v in args.variantes:
            if v == ref:
                continue
            b = s[s.variante == v].set_index("grupo")
            for met in ("accuracy", "acc_dinamica"):
                d = (a[met] - b.loc[a.index, met]).dropna()
                if len(d) >= 2 and np.any(d != 0):
                    pv = wilcoxon(d).pvalue
                    lineas.append(f"  {met:<13} {ref} - {v}: media {d.mean():+.4f}"
                                  f"  p = {pv:.4f}")
    texto = "\n".join(lineas)
    print("\n" + texto)
    with open(os.path.join(out, "ablacion_estadistica.txt"), "w",
              encoding="utf-8") as f:
        f.write(texto + "\n")

    # ---------- figura ----------
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axs = plt.subplots(1, len(args.variantes),
                            figsize=(4.2 * len(args.variantes), 4))
    for ax, v in zip(np.atleast_1d(axs), args.variantes):
        m = cms[v] / np.maximum(cms[v].sum(axis=1, keepdims=True), 1)
        ax.imshow(m, vmin=0, vmax=1, cmap="Blues")
        for i in range(NUM_CLASES):
            for j in range(NUM_CLASES):
                ax.text(j, i, f"{m[i, j]:.2f}", ha="center", va="center",
                        fontsize=7, color="white" if m[i, j] > 0.5 else "black")
        ax.set_xticks(range(NUM_CLASES), nombres, rotation=45, fontsize=7)
        ax.set_yticks(range(NUM_CLASES), nombres, fontsize=7)
        fila = g[g.variante == v].iloc[0]
        ax.set_title(f"{v}\nacc {fila.accuracy:.3f}  dinamica "
                     f"{fila.acc_dinamica:.3f}", fontsize=8)
    fig.suptitle(f"Ablacion de fases - {nombre_fuente} ({particion})", fontsize=9)
    plt.tight_layout()
    plt.savefig(os.path.join(out, "ablacion_confusion.png"), dpi=150)
    print(f"[OUT] {out}")


if __name__ == "__main__":
    main()
