"""
comparativa_fuga_cnn.py - CNN antes y despues de quitar la fuga del test
=========================================================================
Las corridas historicas de CNN pasaban el pliegue de test como
validation_data: EarlyStopping y ReduceLROnPlateau elegian la epoca mirando
el test. Las corregidas usan validacion interna (un sujeto separado del
train) y reentreno con todo el train.

LDA, SVM y RF no tienen parada temprana: sus cifras no cambian y se toman de
las corridas historicas.

Genera resultados/fuga_cnn_antes_despues.txt.
"""

import glob
import os

import numpy as np
import pandas as pd
from scipy.stats import wilcoxon

AQUI = os.path.dirname(os.path.abspath(__file__))
R = os.path.join(AQUI, "resultados")
ABL = os.path.join(AQUI, "..", "ablacion_fases", "resultados")
L = []
w = L.append


def existe(*rutas):
    return all(os.path.exists(os.path.join(R, r)) for r in rutas)


def celda(df):
    # Clave de texto: con tuplas como indice, .loc[tupla, col] se lee como
    # indexacion multinivel y falla.
    return [f"({a:.1f}, {b:d}, {c:.3f})" for a, b, c in
            zip(df.fs_hz, df.ventana_ms.astype(int), df.solap_efectivo)]


def veredicto(dif_media, p, contexto):
    if dif_media > 0 and p < 0.05:
        return f"   -> {contexto}: la CNN SI le gana al LDA (+{dif_media:.3f}, p = {p:.4f})"
    return (f"   -> {contexto}: la CNN NO le gana al LDA (CNN - LDA = {dif_media:+.3f}"
            + (f", p = {p:.4f}" if np.isfinite(p) else "") + ")")


w("CNN ANTES Y DESPUES DE QUITAR LA FUGA DEL TEST")
w("=" * 78)

# ---------------------------------------------------------------- 1.a
w("")
w("1.a BARRIDO DE VENTANAS: CNN en las 6 mejores celdas del LDA (F1 macro medio)")
nuevos = sorted(glob.glob(os.path.join(R, "ventana_cnn_corregido*.csv")))
if existe("ventana_cnn.csv", "ventana_lda.csv") and nuevos:
    viejo = pd.read_csv(os.path.join(R, "ventana_cnn.csv"))
    nuevo = pd.concat([pd.read_csv(f) for f in nuevos])
    lda = pd.read_csv(os.path.join(R, "ventana_lda.csv"))
    lda = lda[~lda.duplicada]
    lda_f1 = dict(zip(celda(lda), lda.f1_media))
    agg = lambda d: d.assign(c=celda(d)).groupby("c").agg(f1=("f1_macro", "mean"), acc=("accuracy", "mean"))  # noqa: E731
    gv, gn = agg(viejo), agg(nuevo)
    w(f"   {'celda (fs, ms, solap)':<26}{'LDA':>8}{'CNN antes':>11}{'CNN despues':>13}{'cambio':>8}{'despues-LDA':>13}")
    filas = []
    for c in gv.index:
        if c not in gn.index:
            continue
        fv, fn, fl = gv.loc[c, "f1"], gn.loc[c, "f1"], lda_f1.get(c, np.nan)
        filas.append((fl, fv, fn))
        w(f"   {str(c):<26}{fl:8.4f}{fv:11.4f}{fn:13.4f}{fn - fv:+8.4f}{fn - fl:+13.4f}")
    if filas:
        fl, fv, fn = map(np.array, zip(*filas))
        w(f"   {'media':<26}{fl.mean():8.4f}{fv.mean():11.4f}{fn.mean():13.4f}"
          f"{(fn - fv).mean():+8.4f}{(fn - fl).mean():+13.4f}")
        w(f"   celdas donde la CNN supera al LDA: antes {int(np.sum(fv > fl))}/{len(fl)}, "
          f"despues {int(np.sum(fn > fl))}/{len(fl)}")
        w(veredicto((fn - fl).mean(), np.nan, "1.a (6 celdas, sin contraste: n = 6 celdas no independientes)"))
else:
    w("   pendiente: faltan ventana_cnn_corregido*.csv")

# ---------------------------------------------------------------- 1.b
w("")
w("1.b LONGITUD DE ONDA: exactitud media por sujeto")
if existe("longitud_onda_cnn_por_sujeto.csv", "longitud_onda_cnn_corregido_por_sujeto.csv",
          "longitud_onda_lda_por_sujeto.csv"):
    from statsmodels.stats.anova import AnovaRM
    from scipy.stats import friedmanchisquare
    v = pd.read_csv(os.path.join(R, "longitud_onda_cnn_por_sujeto.csv"))
    n = pd.read_csv(os.path.join(R, "longitud_onda_cnn_corregido_por_sujeto.csv"))
    l = pd.read_csv(os.path.join(R, "longitud_onda_lda_por_sujeto.csv"))
    configs = ["green", "ir", "250both", "125both"]
    w(f"   {'config':<10}{'LDA':>8}{'CNN antes':>11}{'CNN despues':>13}{'cambio':>8}")
    for c in configs:
        a_l = l[l.config == c].accuracy.mean()
        a_v = v[v.config == c].accuracy.mean()
        a_n = n[n.config == c].accuracy.mean()
        w(f"   {c:<10}{a_l:8.4f}{a_v:11.4f}{a_n:13.4f}{a_n - a_v:+8.4f}")
    for nombre, t in (("CNN antes", v), ("CNN despues", n)):
        aov = AnovaRM(t, depvar="accuracy", subject="subj", within=["config"]).fit().anova_table.iloc[0]
        ancho = t.pivot(index="subj", columns="config", values="accuracy")
        fr = friedmanchisquare(*[ancho[c] for c in configs])
        w(f"   {nombre:<12} ANOVA medidas repetidas F({int(aov['Num DF'])},{int(aov['Den DF'])}) = "
          f"{aov['F Value']:.3f}, p = {aov['Pr > F']:.4f}; Friedman p = {fr.pvalue:.4f}")
    m = n.merge(l, on=["subj", "config"], suffixes=("_cnn", "_lda"))
    d = m.accuracy_cnn - m.accuracy_lda
    p = wilcoxon(m.accuracy_cnn, m.accuracy_lda).pvalue
    w(veredicto(d.mean(), p, "1.b (40 pares sujeto x configuracion, no independientes entre configuraciones)"))
else:
    w("   pendiente: falta longitud_onda_cnn_corregido_por_sujeto.csv")

# ---------------------------------------------------------------- 1.d
w("")
w("1.d CLASICOS FRENTE A CNN (exactitud y F1 macro medios por pliegue)")
if existe("clasicos_por_pliegue.csv", "clasicos_cnn_corregido_por_pliegue.csv",
          "clasicos_por_sujeto.csv", "clasicos_cnn_corregido_por_sujeto.csv"):
    pv = pd.read_csv(os.path.join(R, "clasicos_por_pliegue.csv"))
    pn = pd.read_csv(os.path.join(R, "clasicos_cnn_corregido_por_pliegue.csv"))
    sv = pd.read_csv(os.path.join(R, "clasicos_por_sujeto.csv"))
    sn = pd.read_csv(os.path.join(R, "clasicos_cnn_corregido_por_sujeto.csv"))
    for conj in pv.conjunto.unique():
        w(f"   [{conj}]")
        for mod in ("LDA", "SVM", "RF", "CNN"):
            d = pv[(pv.conjunto == conj) & (pv.modelo == mod)]
            etiqueta = mod + (" antes" if mod == "CNN" else "")
            w(f"     {etiqueta:<12} acc {d.accuracy.mean():.4f} +/- {d.accuracy.std():.4f}   F1 {d.f1_macro.mean():.4f}")
        d = pn[pn.conjunto == conj]
        w(f"     {'CNN despues':<12} acc {d.accuracy.mean():.4f} +/- {d.accuracy.std():.4f}   F1 {d.f1_macro.mean():.4f}")
        lda = sv[(sv.conjunto == conj) & (sv.modelo == "LDA")].set_index("subj")
        cnn_v = sv[(sv.conjunto == conj) & (sv.modelo == "CNN")].set_index("subj")
        cnn_n = sn[sn.conjunto == conj].set_index("subj")
        for metrica in ("accuracy", "f1_macro"):
            dn = (cnn_n[metrica] - lda[metrica]).dropna()
            dv = (cnn_v[metrica] - lda[metrica]).dropna()
            p_n = wilcoxon(dn).pvalue if (dn != 0).any() else np.nan
            p_v = wilcoxon(dv).pvalue if (dv != 0).any() else np.nan
            w(f"     por sujeto (n = {len(dn)}), {metrica}: CNN - LDA antes {dv.mean():+.4f} (p = {p_v:.4f}), "
              f"despues {dn.mean():+.4f} (p = {p_n:.4f})")
        dn = (cnn_n.accuracy - lda.accuracy).dropna()
        w(veredicto(dn.mean(), wilcoxon(dn).pvalue if (dn != 0).any() else np.nan, f"1.d [{conj}]"))
else:
    w("   pendiente: falta clasicos_cnn_corregido_por_pliegue.csv")

# ---------------------------------------------------------------- ablacion
w("")
w("ABLACION DE FASES (dataset publico, ir): CNN sin fuga frente a LDA")
w("   La CNN no se habia corrido antes: no hay cifra 'antes'.")
g_cnn = os.path.join(ABL, "lmg_publico_ir_cnn", "ablacion_global.csv")
g_lda = os.path.join(ABL, "lmg_publico_ir_lda", "ablacion_global.csv")
if os.path.exists(g_cnn) and os.path.exists(g_lda):
    c, l_ = pd.read_csv(g_cnn), pd.read_csv(g_lda)
    cols = ["accuracy", "f1_macro", "acc_dinamica", "acc_meseta", "acc_rest", "reaccion_como_rest"]
    w(f"   {'variante':<20}{'modelo':>7}" + "".join(f"{k:>19}" for k in cols))
    for var in c.variante:
        for nombre, t in (("LDA", l_), ("CNN", c)):
            fila = t[t.variante == var].iloc[0]
            w(f"   {var:<20}{nombre:>7}" + "".join(f"{fila[k]:19.4f}" for k in cols))
else:
    w("   pendiente: falta resultados/lmg_publico_ir_cnn/ablacion_global.csv")

texto = "\n".join(L)
print(texto)
with open(os.path.join(R, "fuga_cnn_antes_despues.txt"), "w", encoding="utf-8") as f:
    f.write(texto + "\n")
