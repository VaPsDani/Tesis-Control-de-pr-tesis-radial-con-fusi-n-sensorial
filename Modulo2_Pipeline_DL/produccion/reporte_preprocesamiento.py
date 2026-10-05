"""
reporte_preprocesamiento.py - Lo que el preprocesamiento hace con cada sesion
=============================================================================
Protesis transradial - Etapa 2

Para cada CSV de sesion, con EXACTAMENTE el preprocesamiento del modelo
(preprocesamiento.preparar_sesion):

  1. REPORTE POR REPETICION. Una fila por gesto pedido, y por cada
     reposo en movimiento: participante, gesto, condicion, repeticion,
     tiempo de reaccion detectado, ventanas que deja, y si hubo
     anticipacion o la IMU no confirmo el movimiento. Se MARCAN, no se
     descartan, las repeticiones que dejan menos del 80% de las ventanas
     esperadas o con reaccion mayor a 1.5 s.

     Ventanas esperadas: las de un bloque de 10 s entero, (1000 - 20) /
     2 + 1 = 491. Es el maximo posible, asi que el porcentaje dice que
     parte de la contraccion sobrevive al etiquetado por fases.

  2. VENTANAS POR CLASE y la proporcion Rest / gesto.

  3. RANGO DE CADA CANAL YA NORMALIZADO, en reposo y en gesto. La entrada
     del modelo INT8 usa UNA sola escala para los 8 canales, asi que
     importa cuanto mas grandes son los valores de la LMG en z que los
     del acelerometro en g.

Uso:
  python reporte_preprocesamiento.py sesiones/s01_*.csv
  python reporte_preprocesamiento.py sesiones/*.csv --salida informes/
"""

import os as _os
import sys as _sys
_M2 = _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                     ".."))
for _d in (_M2, _os.path.join(_M2, "common"), _os.path.join(_M2, "produccion")):
    if _d not in _sys.path:
        _sys.path.insert(0, _d)

import argparse
import glob
import os

import numpy as np
import pandas as pd

import preprocesamiento as P
from anotar_fases import anotar_df

NOMBRES = ["Rest", "Pinch", "Tripod", "Power", "Finger_Ext"]
VENTANAS_BLOQUE_ENTERO = (1000 - P.VENTANA_MUESTRAS) // P.PASO_MUESTRAS + 1
UMBRAL_VENTANAS = 0.80
UMBRAL_REACCION_MS = 1500.0


def reporte_por_repeticion(df: pd.DataFrame) -> pd.DataFrame:
    """Una fila por gesto pedido y por reposo en movimiento."""
    if "descartada" not in df.columns:
        df = df.assign(descartada=0)
    _, informes, _ = anotar_df(df.drop(columns="fase", errors="ignore"))
    onset = {(d["repetition_id"], d["label"]): d for d in informes}

    util = df[P.filas_de_entrenamiento(df)].reset_index(drop=True)
    v = P.ventanear(util)
    cuenta = pd.Series(1, index=pd.MultiIndex.from_arrays(
        [v.repeticion, v.y, v.bloque_tipo])).groupby(level=[0, 1, 2]).sum()

    principal = df[df.bloque_tipo.isin(["contraccion", "reposo_dinamico"])]
    claves = (principal.groupby(["repetition_id", "label", "bloque_tipo"],
                                sort=False)
              .agg(condicion=("condicion_postural", "first"),
                   descartada=("descartada", "max"))
              .reset_index())
    participante = (str(df["id_participante"].iloc[0])
                    if "id_participante" in df.columns
                    else f"S{int(df.subject_id.iloc[0]):02d}")

    filas = []
    for _, r in claves.iterrows():
        rep, lab, tipo = int(r.repetition_id), int(r.label), r.bloque_tipo
        es_rd = tipo == "reposo_dinamico"
        n = int(cuenta.get((rep, lab, tipo), 0))
        d = None if es_rd else onset.get((rep, lab))
        reaccion = None if d is None else d.get("onset_ms")
        pct = n / VENTANAS_BLOQUE_ENTERO
        desc = bool(r.descartada == 1)
        marcas = []
        if desc:
            marcas.append("descartada por el operador")
        else:
            if pct < UMBRAL_VENTANAS:
                marcas.append(f"menos del {UMBRAL_VENTANAS:.0%} de las ventanas")
            if reaccion is not None and reaccion > UMBRAL_REACCION_MS:
                marcas.append("reaccion mayor a 1.5 s")
            if not es_rd and d is None:
                marcas.append("sin inicio detectado")
        filas.append({
            "participante": participante,
            "gesto": "Rest_mov" if es_rd else NOMBRES[lab],
            "condicion": r.condicion,
            "repeticion": rep,
            "reaccion_ms": None if reaccion is None else round(reaccion),
            "ventanas": n,
            "pct_esperadas": round(100 * pct, 1),
            "anticipacion": bool(d and d.get("anticipado")),
            "imu_no_confirma": bool(d and d.get("confirmado_imu") is False),
            "marcas": "; ".join(marcas),
        })
    return pd.DataFrame(filas)


def rangos_normalizados(v: P.Ventanas) -> pd.DataFrame:
    """Percentiles 1 y 99 de cada canal normalizado, en reposo y en gesto."""
    filas = []
    for nombre, m in (("reposo", v.y == 0), ("gesto", v.y > 0)):
        for j, c in enumerate(P.COLUMNAS_MODELO):
            x = v.X[m][:, :, j].ravel()
            if not len(x):
                continue
            p1, p50, p99 = np.percentile(x, [1, 50, 99])
            filas.append({"clase": nombre, "canal": c,
                          "unidad": "z" if c in P.CANALES_LMG else "g",
                          "p1": round(float(p1), 3),
                          "mediana": round(float(p50), 3),
                          "p99": round(float(p99), 3),
                          "max_abs": round(float(np.abs(x).max()), 3)})
    return pd.DataFrame(filas)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", nargs="+")
    ap.add_argument("--salida", default=None,
                    help="carpeta de los informes (por defecto, junto a cada CSV)")
    args = ap.parse_args()
    rutas = sorted({r for patron in args.csv for r in glob.glob(patron)})
    pd.set_option("display.width", 200)
    pd.set_option("display.max_rows", 500)

    reportes, ventanas = [], []
    for ruta in rutas:
        df = P.cargar_sesion(ruta)
        rep = reporte_por_repeticion(df)
        v = P.preparar_sesion(ruta)
        reportes.append(rep)
        ventanas.append(v)
        destino = args.salida or os.path.dirname(os.path.abspath(ruta))
        os.makedirs(destino, exist_ok=True)
        base = os.path.splitext(os.path.basename(ruta))[0]
        rep.to_csv(os.path.join(destino, base + "_repeticiones.csv"), index=False)
        marcadas = rep[rep.marcas != ""]
        print(f"\n=== {os.path.basename(ruta)}: {len(rep)} repeticiones, "
              f"{len(marcadas)} marcadas ===")
        print(rep.to_string(index=False))

    v = P.Ventanas.concatenar(ventanas)
    print("\n=== VENTANAS POR CLASE ===")
    por_clase = {NOMBRES[k]: int((v.y == k).sum()) for k in range(5)}
    gesto = sum(n for k, n in por_clase.items() if k != "Rest")
    print(f"  {por_clase}")
    print(f"  Rest / gesto = {por_clase['Rest'] / max(gesto, 1):.2f}   "
          f"Rest / media de una clase activa = "
          f"{por_clase['Rest'] / max(gesto / 4, 1):.2f}")

    rangos = rangos_normalizados(v)
    print("\n=== RANGO DE CADA CANAL NORMALIZADO (entrada del modelo) ===")
    print(rangos.to_string(index=False))
    lmg = rangos[rangos.unidad == "z"].max_abs.max()
    acc = rangos[rangos.unidad == "g"].max_abs.max()
    print(f"\n  Mayor valor absoluto: LMG {lmg:.2f} z, acelerometro {acc:.2f} g, "
          f"razon {lmg / max(acc, 1e-9):.1f}")


if __name__ == "__main__":
    main()
