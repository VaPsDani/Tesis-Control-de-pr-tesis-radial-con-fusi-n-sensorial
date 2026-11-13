"""
calibrar_fsr.py - Curva lectura -> newtons de cada FSR y error de fuerza (A27)
==============================================================================
Protesis transradial - Etapa 4

PASO 1, MEDIR (firmware del Modulo 3, comando 'F'):
  Con una masa conocida apoyada sobre UN sensor (agua medida por volumen
  o pesada en una balanza de cocina), enviar 'F'. El firmware promedia
  100 lecturas en 1 s e imprime una linea [FSR_CAL] con los cinco. Se
  anota en un CSV la masa y la lectura de ESE sensor:

      sensor,masa_g,lectura_mv
      P,0,12.0
      P,50,240.5
      ...

  sensor es P, I, M, A o Mn (pulgar, indice, medio, anular, menique).
  Conviene 5 o mas masas por sensor, de cero hasta mas alla del umbral.

PASO 2, AJUSTAR:
      python calibrar_fsr.py ajustar --pares pares.csv
  F = m * g con g = 9.80665 m/s^2. Por sensor se prueban dos curvas de
  lectura (mV) a fuerza (N), y gana la de menor RMSE en newtons:
      lineal      F = a * V + b
      potencial   F = c * V ^ d       (ajuste lineal en escala log-log)
  Las dos se evaluan sobre los mismos puntos, los de masa y lectura
  mayores que cero, porque la potencial no esta definida en cero.

PASO 3, ERROR DE FUERZA:
      python calibrar_fsr.py mae --curvas curvas_fsr.json --log monitor.txt
  monitor.txt es lo que imprimio el firmware al usar la mano. Cada vez
  que un dedo se detiene por su FSR sale una linea [FSR_STOP] con la
  lectura de parada y el umbral. La consigna es el umbral pasado a
  newtons con la curva del sensor, y el error es la fuerza de parada
  menos la consigna. Se reporta el MAE en newtons, por dedo y global.
"""

import argparse
import json
import re
import sys

import numpy as np
import pandas as pd

G = 9.80665
SENSORES = ["P", "I", "M", "A", "Mn"]
MIN_PUNTOS = 3


def curva(params: dict, v):
    v = np.asarray(v, dtype=float)
    if params["tipo"] == "lineal":
        return params["a"] * v + params["b"]
    return params["c"] * np.power(np.clip(v, 1e-9, None), params["d"])


def ajustar_sensor(v: np.ndarray, f: np.ndarray) -> dict:
    """Ajusta las dos curvas a un sensor y elige la de menor RMSE."""
    m = (v > 0) & (f > 0)
    if m.sum() < MIN_PUNTOS:
        raise ValueError(f"hacen falta al menos {MIN_PUNTOS} puntos con masa y "
                         f"lectura mayores que cero, hay {int(m.sum())}")
    vv, ff = v[m], f[m]
    a, b = np.polyfit(vv, ff, 1)
    d, log_c = np.polyfit(np.log(vv), np.log(ff), 1)
    candidatas = {"lineal": {"tipo": "lineal", "a": float(a), "b": float(b)},
                  "potencial": {"tipo": "potencial", "c": float(np.exp(log_c)),
                                "d": float(d)}}
    for p in candidatas.values():
        pred = curva(p, vv)
        p["rmse_n"] = float(np.sqrt(np.mean((pred - ff) ** 2)))
        p["r2"] = float(1 - np.sum((ff - pred) ** 2) / np.sum((ff - ff.mean()) ** 2))
    elegida = min(candidatas, key=lambda k: candidatas[k]["rmse_n"])
    return {"elegida": elegida, "curva": candidatas[elegida],
            "candidatas": candidatas, "n_puntos": int(m.sum()),
            "rango_mv": [float(vv.min()), float(vv.max())]}


def ajustar(pares: pd.DataFrame) -> dict:
    salida = {}
    for s in SENSORES:
        d = pares[pares.sensor.astype(str) == s]
        if not len(d):
            continue
        f = d.masa_g.to_numpy(float) / 1000.0 * G
        salida[s] = ajustar_sensor(d.lectura_mv.to_numpy(float), f)
    return salida


PARADA = re.compile(r"\[FSR_STOP\] dedo=(\d+) lectura_mv=([\d.]+) umbral_mv=([\d.]+)")


def mae(curvas: dict, lineas) -> dict:
    """MAE en newtons entre la fuerza de parada y la consigna, por dedo."""
    errores = {s: [] for s in SENSORES}
    for linea in lineas:
        m = PARADA.search(linea)
        if not m:
            continue
        s = SENSORES[int(m.group(1))]
        if s not in curvas:
            continue
        c = curvas[s]["curva"]
        parada = float(curva(c, float(m.group(2))))
        consigna = float(curva(c, float(m.group(3))))
        errores[s].append(parada - consigna)
    todos = [e for v in errores.values() for e in v]
    if not todos:
        raise ValueError("No hay lineas [FSR_STOP] de sensores calibrados en el log.")
    return {
        "mae_n": float(np.mean(np.abs(todos))),
        "sesgo_n": float(np.mean(todos)),
        "n_paradas": len(todos),
        "por_dedo": {s: {"mae_n": float(np.mean(np.abs(v))), "n": len(v)}
                     for s, v in errores.items() if v},
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("ajustar")
    a.add_argument("--pares", required=True)
    a.add_argument("--salida", default="curvas_fsr.json")
    e = sub.add_parser("mae")
    e.add_argument("--curvas", required=True)
    e.add_argument("--log", required=True)
    args = ap.parse_args(argv)

    if args.cmd == "ajustar":
        res = ajustar(pd.read_csv(args.pares))
        for s, r in res.items():
            cand = r["candidatas"]
            print(f"{s:3s} n={r['n_puntos']:2d}  lineal RMSE {cand['lineal']['rmse_n']:.3f} N "
                  f"R2 {cand['lineal']['r2']:.4f}  |  potencial RMSE "
                  f"{cand['potencial']['rmse_n']:.3f} N R2 {cand['potencial']['r2']:.4f}"
                  f"  ->  {r['elegida']}")
        with open(args.salida, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2)
        print(f"[SALIDA] {args.salida}")
    else:
        with open(args.curvas, encoding="utf-8") as f:
            curvas = json.load(f)
        with open(args.log, encoding="utf-8", errors="ignore") as f:
            res = mae(curvas, f)
        print(f"MAE {res['mae_n']:.3f} N, sesgo {res['sesgo_n']:+.3f} N, "
              f"{res['n_paradas']} paradas")
        for s, r in res["por_dedo"].items():
            print(f"  {s:3s} MAE {r['mae_n']:.3f} N  (n = {r['n']})")


if __name__ == "__main__":
    sys.exit(main())
