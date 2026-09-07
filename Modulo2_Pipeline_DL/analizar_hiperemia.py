"""
analizar_hiperemia.py - Verifica el margen del bloque de reposo con datos
=========================================================================
Protesis transradial - Captura con voluntarios

LA HIPOTESIS A CONTRASTAR:
  El margen de entrada del bloque de reposo se fijo en 2000 ms razonando
  que volver a reposo es mas lento que salir de el, sobre todo con una
  senal optica: el LMG refleja deformacion muscular y volumen sanguineo,
  y la hiperemia reactiva posterior a una contraccion sostenida tiene
  constantes de tiempo de segundos.

  Ese razonamiento es teorico. Este script lo contrasta con los datos
  del piloto, y en cualquiera de los dos desenlaces se gana algo:

    Si hay una curva de decaimiento visible, hay evidencia propia para
    la metodologia en vez de una cita, y se puede justificar el margen.

    Si a los 2 s ya esta plana, el margen se puede reducir y se recuperan
    segundos utiles: cada 500 ms recuperados en los 24 bloques de reposo
    son 12 s mas de clase Rest por sujeto.

POR QUE DESAGREGADO POR GESTO PREDECESOR:
  Promediar los 24 bloques mezcla reposos que siguen a Pinch (pinza
  fina, poca masa muscular) con los que siguen a Power (agarre de
  fuerza, toda la mano). Si la hipotesis es cierta, la curva tras Power
  debe decaer mas lento y desde mas alto que la de Pinch: una relacion
  DOSIS-RESPUESTA, mucho mas dificil de explicar por un artefacto que
  una curva promedio sola.

  Si las cuatro curvas salen planas e identicas, la evidencia en contra
  tambien es mas solida.

LA REFERENCIA:
  El bloque de calibracion inicial es reposo BASAL, antes de cualquier
  contraccion de la sesion. Es la linea horizontal contra la que se mide
  si el reposo post-contraccion converge o no.

USO:
  python analizar_hiperemia.py --csv sesiones/s01_20260907_101500.csv
"""

import argparse
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from preprocesamiento import COLUMNAS_MODELO

NOMBRES = ["Rest", "Pinch", "Tripod", "Power", "Finger_Ext"]
CANALES_LMG = ["v1", "v2", "v3", "v4", "v5"]
PERIODO_MS = 10


def segmentar(df):
    """Indices de inicio y fin de cada bloque contiguo."""
    claves = ["repetition_id", "label", "bloque_tipo"]
    cambio = np.zeros(len(df), dtype=bool)
    for c in claves:
        cambio |= df[c].ne(df[c].shift()).values
    seg = np.cumsum(cambio)
    bloques = []
    for s in np.unique(seg):
        ii = np.where(seg == s)[0]
        bloques.append((ii[0], ii[-1] + 1))
    return bloques


def ajustar_tau(t_s, y):
    """
    Ajusta y = a*exp(-t/tau) + c por minimos cuadrados sobre una rejilla
    de tau. Es un barrido y no un optimizador porque con ~800 puntos y
    una sola variable no lineal resulta mas robusto y no depende de un
    valor inicial.
    """
    mejor = (None, np.inf, None, None)
    for tau in np.linspace(0.2, 30.0, 300):
        base = np.exp(-t_s / tau)
        A = np.vstack([base, np.ones_like(base)]).T
        coef, res, *_ = np.linalg.lstsq(A, y, rcond=None)
        pred = A @ coef
        sse = float(np.sum((y - pred) ** 2))
        if sse < mejor[1]:
            mejor = (tau, sse, coef[0], coef[1])
    tau, sse, a, c = mejor
    sst = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1 - sse / sst if sst > 0 else 0.0
    return tau, a, c, r2


def main():
    p = argparse.ArgumentParser(description="Curva de hiperemia post-contraccion")
    p.add_argument("--csv", type=str, required=True)
    p.add_argument("--output_dir", type=str, default=None)
    args = p.parse_args()

    df = pd.read_csv(args.csv)
    out = args.output_dir or os.path.dirname(args.csv) or "."
    os.makedirs(out, exist_ok=True)
    base = os.path.splitext(os.path.basename(args.csv))[0]

    bloques = segmentar(df)
    tipo = df["bloque_tipo"].values
    lab = df["label"].values

    # Referencia basal: el bloque de calibracion, excluyendo sus margenes.
    cal = df[(df["es_calibracion"] == 1) & (df["en_margen"] == 0)]
    if len(cal) == 0:
        raise SystemExit("El CSV no tiene bloque de calibracion utilizable.")
    basal = {c: float(cal[c].mean()) for c in CANALES_LMG}
    print(f"Referencia basal (calibracion, {len(cal)} muestras):")
    for c in CANALES_LMG:
        print(f"  {c}: {basal[c]:.4f}")

    # Agrupar cada bloque de reposo por el gesto que lo precede.
    por_predecesor = {}
    for k, (a, b) in enumerate(bloques):
        if tipo[a] != "reposo" or k == 0:
            continue
        a_prev, b_prev = bloques[k - 1]
        if tipo[a_prev] != "contraccion":
            continue
        pred = int(lab[a_prev])
        por_predecesor.setdefault(pred, []).append((a, b))

    if not por_predecesor:
        raise SystemExit("No hay bloques de reposo precedidos por contraccion.")

    n_min = min(b - a for lst in por_predecesor.values() for a, b in lst)
    t_s = np.arange(n_min) * PERIODO_MS / 1000.0

    fig, axes = plt.subplots(1, len(CANALES_LMG), figsize=(22, 4.2),
                             sharex=True)
    informe = {"basal": basal, "por_predecesor": {}}

    for j, canal in enumerate(CANALES_LMG):
        ax = axes[j]
        ax.axhline(basal[canal], color="k", ls=":", lw=1.5,
                   label="basal (calibracion)")

        for pred in sorted(por_predecesor):
            trazas = np.stack([df[canal].values[a:a + n_min]
                               for a, b in por_predecesor[pred]])
            media = trazas.mean(axis=0)
            sd = trazas.std(axis=0)

            linea, = ax.plot(t_s, media, lw=1.6, label=NOMBRES[pred])
            ax.fill_between(t_s, media - sd, media + sd, alpha=0.12,
                            color=linea.get_color())

            tau, amp, c0, r2 = ajustar_tau(t_s, media)
            informe["por_predecesor"].setdefault(NOMBRES[pred], {})[canal] = {
                "n_bloques": len(por_predecesor[pred]),
                "tau_s": round(float(tau), 3),
                "amplitud": round(float(amp), 4),
                "asintota": round(float(c0), 4),
                "r2": round(float(r2), 4),
                "delta_vs_basal_en_2s": round(
                    float(media[min(200, n_min - 1)] - basal[canal]), 4),
            }

        ax.axvline(2.0, color="r", ls="--", lw=1,
                   label="margen actual (2 s)")
        ax.set_title(canal)
        ax.set_xlabel("s desde el inicio del reposo")
        if j == 0:
            ax.set_ylabel("LMG (mV)")
            ax.legend(fontsize=7)
        ax.grid(alpha=0.3)

    fig.suptitle("Reposo post-contraccion por gesto predecesor. Si la "
                 "hipotesis de hiperemia es cierta, Power decae mas lento "
                 "y desde mas alto que Pinch.", fontsize=11)
    plt.tight_layout()
    ruta_png = os.path.join(out, f"{base}_hiperemia.png")
    plt.savefig(ruta_png, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\n[GRAFICA] {ruta_png}")

    # --- Veredicto cuantitativo ---
    print("\n" + "=" * 72)
    print("CONSTANTE DE TIEMPO POR GESTO PREDECESOR (mediana de canales)")
    print("=" * 72)
    print(f"  {'Predecesor':<14}{'tau (s)':>10}{'r2':>8}"
          f"{'delta a 2 s':>14}")
    print(f"  {'-'*46}")
    taus = {}
    for nombre, canales in informe["por_predecesor"].items():
        tau_med = float(np.median([v["tau_s"] for v in canales.values()]))
        r2_med = float(np.median([v["r2"] for v in canales.values()]))
        d2 = float(np.median([abs(v["delta_vs_basal_en_2s"])
                              for v in canales.values()]))
        taus[nombre] = tau_med
        print(f"  {nombre:<14}{tau_med:>10.2f}{r2_med:>8.3f}{d2:>14.4f}")

    print()
    if taus and max(taus.values()) < 1.0:
        print("  Las constantes de tiempo son inferiores a 1 s: a los 2 s la")
        print("  senal ya esta plana. EL MARGEN DE REPOSO SE PUEDE REDUCIR,")
        print("  lo que recupera segundos utiles de la clase Rest.")
        informe["veredicto"] = "margen_reducible"
    elif taus and max(taus.values()) > 3.0:
        print("  Hay constantes de tiempo superiores a 3 s: la hiperemia es")
        print("  real y medible. El margen de 2 s se queda CORTO; esta clase")
        print("  Rest es reposo post-contraccion, no basal. Declararlo en la")
        print("  discusion y comparar contra el bloque de calibracion.")
        informe["veredicto"] = "hiperemia_confirmada"
    else:
        print("  Constantes de tiempo intermedias. El margen de 2 s es")
        print("  razonable; revisar la grafica antes de tocarlo.")
        informe["veredicto"] = "margen_razonable"

    if len(taus) >= 2:
        peor, mejor = max(taus, key=taus.get), min(taus, key=taus.get)
        print(f"\n  Relacion dosis-respuesta: tau mayor tras {peor} "
              f"({taus[peor]:.2f} s) que tras {mejor} ({taus[mejor]:.2f} s).")
        print(f"  Si {peor} es el gesto de mas masa muscular, apoya la")
        print(f"  explicacion por hiperemia y no por artefacto.")

    ruta_json = os.path.join(out, f"{base}_hiperemia.json")
    with open(ruta_json, "w", encoding="utf-8") as f:
        json.dump(informe, f, indent=2, ensure_ascii=False)
    print(f"\n[JSON] {ruta_json}")


if __name__ == "__main__":
    main()
