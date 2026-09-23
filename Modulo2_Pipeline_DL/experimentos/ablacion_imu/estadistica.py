"""
estadistica.py - Contrastes del 2x2 de la ablacion de la IMU
=============================================================
Protesis transradial - Ablacion de la IMU

QUE SE CONTRASTA:

  Efecto principal de A    lmg_imu frente a solo_lmg
  Efecto principal de B    dinamica frente a estatica
  Interaccion              (lmg_imu - solo_lmg) en dinamica
                           menos
                           (lmg_imu - solo_lmg) en estatica

  La interaccion, SOBRE UNA CORRIDA EN MODO MIXTO, es la prueba
  principal del aporte inercial: si la IMU sirve sobre todo cuando el
  brazo se mueve, su aporte tiene que ser MAYOR en la condicion dinamica
  que en la estatica.

  Con --entrenamiento estatica_a_dinamica la misma aritmetica significa
  otra cosa, porque el modelo nunca vio variacion postural. Ver
  analizar_caida().

POR SUJETO, NO POR PLIEGUE:
  Con 10 sujetos y k=5, contrastar por pliegue deja n = 5 y ademas los
  dos sujetos de un mismo pliegue comparten modelo. Por sujeto quedan
  n = 10 medidas y cada sujeto aporta sus cuatro celdas, que es lo que
  hace pareado el contraste.

CONTRASTES QUE SE REPORTAN:
  ANOVA de medidas repetidas 2x2 (statsmodels AnovaRM), que da los dos
  efectos principales y la interaccion, y Wilcoxon pareado para cada
  efecto, que no supone normalidad. Con 10 sujetos el p minimo de
  Wilcoxon es 2/2^10 = 0.002, y con menos de 6 sujetos ningun resultado
  puede bajar de 0.05: eso se declara en vez de disimularse.

USO:
  python estadistica.py --csv resultados/ablacion_imu_por_sujeto.csv
"""

import argparse
import json
import os

import numpy as np
import pandas as pd
from scipy.stats import ttest_rel, wilcoxon

COMPOSICIONES = ["solo_lmg", "lmg_imu"]
CONDICIONES = ["estatica", "dinamica"]


def d_de_cohen_pareado(dif: np.ndarray) -> float:
    """d_z: media de las diferencias entre su desviacion."""
    sd = dif.std(ddof=1)
    return float(dif.mean() / sd) if sd > 0 else float("nan")


def contraste(dif: np.ndarray, etiqueta: str) -> dict:
    """Wilcoxon y t pareada sobre un vector de diferencias por sujeto."""
    n = len(dif)
    p_min = 2 / (2 ** n) if n else float("nan")
    if np.allclose(dif, 0):
        p_w = float("nan")
    else:
        p_w = float(wilcoxon(dif).pvalue)
    t = ttest_rel(dif, np.zeros_like(dif))
    return {
        "etiqueta": etiqueta,
        "n": int(n),
        "media": float(dif.mean()),
        "sd": float(dif.std(ddof=1)) if n > 1 else float("nan"),
        "wilcoxon_p": p_w,
        "wilcoxon_p_minimo_alcanzable": float(p_min),
        "t": float(t.statistic),
        "t_p": float(t.pvalue),
        "d_z": d_de_cohen_pareado(dif),
    }


def tabla_ancha(df: pd.DataFrame, metrica: str) -> pd.DataFrame:
    """Una fila por sujeto y una columna por celda."""
    ancha = df.pivot_table(index="sujeto", columns=["composicion", "condicion"],
                           values=metrica)
    faltan = [c for c in [(a, b) for a in COMPOSICIONES for b in CONDICIONES]
              if c not in ancha.columns]
    if faltan:
        raise ValueError(f"Faltan celdas en el CSV: {faltan}")
    return ancha.dropna()


def analizar(df: pd.DataFrame, metrica: str) -> dict:
    ancha = tabla_ancha(df, metrica)
    sujetos = ancha.index.tolist()
    v = {(a, b): ancha[(a, b)].values for a in COMPOSICIONES
         for b in CONDICIONES}

    # Efectos principales: se promedia el otro factor dentro de cada
    # sujeto, que es lo que hace el ANOVA de medidas repetidas.
    efecto_a = ((v[("lmg_imu", "estatica")] + v[("lmg_imu", "dinamica")]) / 2
                - (v[("solo_lmg", "estatica")] + v[("solo_lmg", "dinamica")]) / 2)
    efecto_b = ((v[("solo_lmg", "dinamica")] + v[("lmg_imu", "dinamica")]) / 2
                - (v[("solo_lmg", "estatica")] + v[("lmg_imu", "estatica")]) / 2)
    aporte_estatica = v[("lmg_imu", "estatica")] - v[("solo_lmg", "estatica")]
    aporte_dinamica = v[("lmg_imu", "dinamica")] - v[("solo_lmg", "dinamica")]
    interaccion = aporte_dinamica - aporte_estatica

    salida = {
        "metrica": metrica,
        "n_sujetos": len(sujetos),
        "medias_por_celda": {f"{a}|{b}": float(v[(a, b)].mean())
                             for a in COMPOSICIONES for b in CONDICIONES},
        "sd_por_celda": {f"{a}|{b}": float(v[(a, b)].std(ddof=1))
                         for a in COMPOSICIONES for b in CONDICIONES},
        "efecto_A_imu": contraste(efecto_a, "lmg_imu - solo_lmg"),
        "efecto_B_postura": contraste(efecto_b, "dinamica - estatica"),
        "aporte_imu_en_estatica": contraste(aporte_estatica,
                                            "IMU con el brazo quieto"),
        "aporte_imu_en_dinamica": contraste(aporte_dinamica,
                                            "IMU con el brazo en movimiento"),
        "interaccion": contraste(interaccion,
                                 "aporte en dinamica - aporte en estatica"),
    }

    # ANOVA de medidas repetidas, si statsmodels esta disponible.
    try:
        from statsmodels.stats.anova import AnovaRM
        largo = df[df.sujeto.isin(sujetos)]
        aov = AnovaRM(largo, depvar=metrica, subject="sujeto",
                      within=["composicion", "condicion"]).fit()
        tabla = aov.anova_table
        salida["anova_medidas_repetidas"] = {
            str(i): {"F": float(r["F Value"]), "p": float(r["Pr > F"]),
                     "df1": float(r["Num DF"]), "df2": float(r["Den DF"])}
            for i, r in tabla.iterrows()}
    except Exception as e:
        salida["anova_medidas_repetidas"] = {"error": str(e)}

    return salida


def analizar_caida(df: pd.DataFrame, metrica: str) -> dict:
    """
    Caida al pasar de evaluar en estatica a evaluar en dinamica.

    Con --entrenamiento estatica_a_dinamica el modelo solo vio el brazo
    quieto, asi que esta caida mide que ocurre cuando el entrenamiento NO
    incluye variacion postural.

    OJO CON LA LECTURA: ese modo esta sesgado contra la IMU. Con el brazo
    fijo el acelerometro lee casi siempre el mismo vector de gravedad, y
    el modelo nunca ve la relacion entre postura y senal optica, que es
    lo que tendria que aprender para compensarla. Si lmg_imu cae mas, lo
    que se concluye es que la fusion inercial necesita variacion postural
    en los datos de entrenamiento, NO que la IMU no compense la postura.
    Esa pregunta la responde la interaccion del modo mixto.

    La diferencia de caidas coincide numericamente con la interaccion del
    2x2, con el signo cambiado. Se reporta aparte porque con este
    entrenamiento significa otra cosa: alli es cuanto aporta la IMU en
    cada condicion, y aqui cuanto aguanta cada composicion una postura
    que no estuvo en su entrenamiento.
    """
    ancha = tabla_ancha(df, metrica)
    caidas, resumen = {}, {}
    for a in COMPOSICIONES:
        est = ancha[(a, "estatica")].values
        din = ancha[(a, "dinamica")].values
        caidas[a] = est - din
        with np.errstate(divide="ignore", invalid="ignore"):
            rel = np.where(est > 0, (est - din) / est, np.nan)
        resumen[a] = {
            "media_estatica": float(est.mean()),
            "media_dinamica": float(din.mean()),
            "caida_absoluta": float((est - din).mean()),
            "caida_relativa": float(np.nanmean(rel)),
            "contraste_contra_cero": contraste(
                est - din, f"caida de {a}"),
        }

    salida = {"metrica": metrica, "n_sujetos": len(ancha), "por_composicion": resumen}
    if len(COMPOSICIONES) == 2:
        a, b = COMPOSICIONES            # solo_lmg, lmg_imu
        salida["diferencia_de_caidas"] = contraste(
            caidas[a] - caidas[b], f"caida({a}) - caida({b})")
        salida["lectura"] = (
            f"positivo: {b} aguanta mejor el cambio de postura. negativo con "
            f"entrenamiento solo estatico: la fusion inercial necesita "
            f"variacion postural en el entrenamiento")
    return salida


def texto_caida(res: dict) -> str:
    L = []
    w = L.append
    w(f"CAIDA ENTRE POSTURAS - {res['metrica'].upper()} "
      f"(n = {res['n_sujetos']} sujetos)")
    w("=" * 74)
    w(f"   {'':<10}{'estatica':>11}{'dinamica':>11}{'caida':>10}{'relativa':>11}"
      f"{'Wilcoxon p':>13}")
    for a in COMPOSICIONES:
        r = res["por_composicion"][a]
        w(f"   {a:<10}{r['media_estatica']:11.4f}{r['media_dinamica']:11.4f}"
          f"{r['caida_absoluta']:+10.4f}{100 * r['caida_relativa']:10.1f}%"
          f"{r['contraste_contra_cero']['wilcoxon_p']:13.4f}")
    if "diferencia_de_caidas" in res:
        d = res["diferencia_de_caidas"]
        w("")
        w(f"   {d['etiqueta']}: {d['media']:+.4f}  "
          f"Wilcoxon p = {d['wilcoxon_p']:.4f}  "
          f"t({d['n']-1}) = {d['t']:+.2f}, p = {d['t_p']:.4f}  "
          f"d_z = {d['d_z']:+.2f}")
        w(f"   {res['lectura']}")
    return "\n".join(L)


def texto(res: dict) -> str:
    L = []
    w = L.append
    m = res["metrica"]
    w(f"ABLACION DE LA IMU - {m.upper()} (n = {res['n_sujetos']} sujetos)")
    w("=" * 74)
    w("")
    w("1. MEDIAS POR CELDA")
    w(f"   {'':<12}{'estatica':>14}{'dinamica':>14}")
    for a in COMPOSICIONES:
        w(f"   {a:<12}" + "".join(
            f"{res['medias_por_celda'][f'{a}|{b}']:14.4f}" for b in CONDICIONES))
    w("")
    w("2. EFECTOS, CONTRASTES PAREADOS POR SUJETO")
    for clave in ("efecto_A_imu", "efecto_B_postura", "aporte_imu_en_estatica",
                  "aporte_imu_en_dinamica", "interaccion"):
        c = res[clave]
        w(f"   {clave:<24} {c['media']:+.4f}  Wilcoxon p = {c['wilcoxon_p']:.4f}"
          f"  t({c['n']-1}) = {c['t']:+.2f}, p = {c['t_p']:.4f}"
          f"  d_z = {c['d_z']:+.2f}")
    w(f"   p minimo alcanzable por Wilcoxon con n = {res['n_sujetos']}: "
      f"{res['efecto_A_imu']['wilcoxon_p_minimo_alcanzable']:.4f}")
    w("")
    w("3. ANOVA DE MEDIDAS REPETIDAS 2x2")
    aov = res.get("anova_medidas_repetidas", {})
    if "error" in aov:
        w(f"   no disponible: {aov['error']}")
    else:
        for efecto, r in aov.items():
            w(f"   {efecto:<26} F({r['df1']:.0f},{r['df2']:.0f}) = {r['F']:.3f}"
              f", p = {r['p']:.4f}")
    w("")
    w("LECTURA: en una corrida en modo MIXTO, la interaccion es la cifra que")
    w("responde a la pregunta del experimento. Un aporte de la IMU mayor en")
    w("dinamica que en estatica indica que la IMU compensa el movimiento del")
    w("brazo, que es lo que ningun trabajo de lightmiografia ha medido. Con")
    w("entrenamiento solo estatico la misma aritmetica NO dice eso: ver la")
    w("seccion de caida entre posturas.")
    return "\n".join(L)


def main():
    p = argparse.ArgumentParser(description="Contrastes del 2x2")
    p.add_argument("--csv", type=str, required=True)
    p.add_argument("--metricas", nargs="+",
                   default=["accuracy", "f1_macro", "auc"])
    p.add_argument("--salida", type=str, default=None)
    args = p.parse_args()

    df = pd.read_csv(args.csv)
    salida = args.salida or os.path.dirname(os.path.abspath(args.csv))
    os.makedirs(salida, exist_ok=True)

    todo, bloques = {}, []
    for metrica in args.metricas:
        if metrica not in df.columns:
            print(f"[AVISO] El CSV no tiene la columna {metrica}, se omite.")
            continue
        res = analizar(df, metrica)
        caida = analizar_caida(df, metrica)
        res["caida_entre_posturas"] = caida
        todo[metrica] = res
        bloques.append(texto(res))
        bloques.append(texto_caida(caida))

    modos = sorted(df["entrenamiento"].unique()) if "entrenamiento" in df else []
    if modos:
        if "estatica_a_dinamica" in modos:
            nota = (
                "\n   El modelo solo vio repeticiones ESTATICAS, asi que esta"
                "\n   corrida mide que ocurre cuando el entrenamiento no"
                "\n   incluye variacion postural."
                "\n"
                "\n   ESTE MODO ESTA SESGADO CONTRA LA IMU: con el brazo fijo"
                "\n   el acelerometro lee casi siempre el mismo vector de"
                "\n   gravedad, y el modelo nunca ve la relacion entre postura"
                "\n   y senal optica. Si lmg_imu cae mas, la conclusion es que"
                "\n   la fusion inercial NECESITA variacion postural en el"
                "\n   entrenamiento, no que la IMU no compense la postura."
                "\n"
                "\n   La prueba principal del aporte inercial es el modo"
                "\n   mixto, y en el la cifra que responde es la interaccion."
                "\n   Ver el rango del acelerometro en ablacion_imu.json"
                "\n   (rango_acelerometro_train_vs_test) para comprobar si"
                "\n   hubo desplazamiento de distribucion.")
        else:
            nota = ("\n   El modelo vio las dos condiciones en el"
                    "\n   entrenamiento, asi que la caida entre posturas es lo"
                    "\n   que cuesta la postura a un modelo que la conoce.")
        bloques.append("MODO DE ENTRENAMIENTO DE ESTA CORRIDA: "
                       + ", ".join(modos) + nota)

    informe = "\n\n".join(bloques)
    print("\n" + informe)
    with open(os.path.join(salida, "estadistica.txt"), "w",
              encoding="utf-8") as f:
        f.write(informe + "\n")
    with open(os.path.join(salida, "estadistica.json"), "w",
              encoding="utf-8") as f:
        json.dump(todo, f, indent=2, ensure_ascii=False)
    print(f"\n[SALIDA] {os.path.join(salida, 'estadistica.txt')}")


if __name__ == "__main__":
    main()
