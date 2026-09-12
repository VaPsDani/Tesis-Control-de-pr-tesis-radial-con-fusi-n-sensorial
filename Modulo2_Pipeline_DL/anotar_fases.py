"""
anotar_fases.py - Columna `fase` para los CSV de captura
========================================================
Protesis transradial - Tarea 4

Anade al CSV de una sesion la columna `fase`, con el detector de
fases.py:

  bloques de gesto      reaccion, dinamica, meseta
  periodos de reposo    relajacion, reposo, recorte

El tramo de reaccion NO se borra: queda en el CSV con su fase, y es el
entrenamiento el que decide excluirlo (fases.mascara_entrenamiento). Asi
la ablacion de variantes se puede correr sin volver a grabar.

QUE SE ESCRIBE:
  - En el CSV, SOLO la columna fase, anadida al final de cada linea. Las
    demas columnas se copian byte a byte: el dato crudo no se reescribe.
    Si ya habia una columna fase (una version anterior del detector), se
    sustituye. La escritura es atomica (archivo temporal + os.replace).
  - Un JSON al lado, <csv>_fases.json, con la version del detector, sus
    parametros, el resumen de onsets y el informe por gesto (onset,
    duracion de la dinamica, sospechoso y motivo, confirmacion IMU).
    preprocesamiento.py lo usa para detectar una columna fase obsoleta.

DATOS DE LA CAPTURA QUE USA:
  - v1..v5 como senal; ax..gz como confirmacion (IMU).
  - El bloque de calibracion (es_calibracion == 1, fuera de margen) como
    base de respaldo, y como base unica con --modo_base calibracion.
  - Los huecos de timestamp (pausas) parten la sesion en tramos
    continuos: ninguna base ni onset se calcula a traves de una pausa.

Uso:
  python anotar_fases.py sesiones/s01_*.csv
  python anotar_fases.py sesiones/*.csv --comparar_bases
  python anotar_fases.py s01.csv --k 3 --t_ms 50 --recorte_ini 500 --recorte_fin 1000
"""

import argparse
import json
import os
import sys
from dataclasses import asdict
from typing import Optional

import numpy as np
import pandas as pd

AQUI = os.path.dirname(os.path.abspath(__file__))
if AQUI not in sys.path:
    sys.path.insert(0, AQUI)

from fases import (FASES_VERSION, ParametrosFases, estadisticas_base,  # noqa: E402
                   etiquetar_fases, firma)

COLUMNAS_LMG = ["v1", "v2", "v3", "v4", "v5"]
COLUMNAS_IMU = ["ax", "ay", "az", "gx", "gy", "gz"]
HUECO_PERIODOS = 3          # mismo criterio que preprocesamiento.py
MIN_MUESTRAS_CALIB = 50


def ruta_sidecar(ruta_csv: str) -> str:
    return os.path.splitext(ruta_csv)[0] + "_fases.json"


def _tramos_continuos(ts: np.ndarray, periodo_ms: float):
    cortes = np.flatnonzero(np.diff(ts) > HUECO_PERIODOS * periodo_ms) + 1
    lim = np.r_[0, cortes, len(ts)]
    return [(int(a), int(z)) for a, z in zip(lim[:-1], lim[1:])]


def _base_calibracion(df: pd.DataFrame, x: np.ndarray,
                      imu: Optional[np.ndarray]):
    if "es_calibracion" not in df.columns:
        return None, None
    m = df["es_calibracion"].to_numpy() == 1
    if "en_margen" in df.columns:
        m &= df["en_margen"].to_numpy() == 0
    if m.sum() < MIN_MUESTRAS_CALIB:
        return None, None
    return estadisticas_base(x[m]), (imu[m] if imu is not None else None)


def anotar_df(df: pd.DataFrame, p: Optional[ParametrosFases] = None,
              modo_base: str = "local"):
    """
    Fase por fila de un DataFrame de captura.

    Returns:
        fase (array de str), informes (lista de dict por gesto), fs (Hz)
    """
    p = p or ParametrosFases()
    x = df[COLUMNAS_LMG].to_numpy(np.float64)
    imu = (df[COLUMNAS_IMU].to_numpy(np.float64)
           if all(c in df.columns for c in COLUMNAS_IMU) else None)
    lab = df["label"].to_numpy(np.int64)
    ts = df["timestamp_ms"].to_numpy(np.float64)
    periodo = float(np.median(np.diff(ts))) if len(ts) > 1 else 10.0
    fs = 1000.0 / periodo
    base_cal, imu_cal = _base_calibracion(df, x, imu)
    rep = df["repetition_id"].to_numpy() if "repetition_id" in df.columns else None

    fase = np.empty(len(df), dtype=object)
    informes = []
    for s, (a, z) in enumerate(_tramos_continuos(ts, periodo)):
        f, inf = etiquetar_fases(
            x[a:z], lab[a:z], fs, p,
            imu=None if imu is None else imu[a:z],
            base_global=base_cal, imu_base_global=imu_cal,
            modo_base=modo_base)
        fase[a:z] = f
        for d in inf:
            d["tramo"] = s
            d["inicio"] += a
            d["fin"] += a
            if rep is not None:
                d["repetition_id"] = int(rep[d["inicio"]])
        informes.extend(inf)
    return fase, informes, fs


def resumen(informes, fs: float, p: Optional[ParametrosFases] = None) -> dict:
    """
    Resumen de onsets. pct_borde_busqueda es el diagnostico de una base
    obsoleta: el onset sale pegado al inicio de la ventana de busqueda
    porque la deriva ya supera el umbral antes de que empiece el gesto.
    """
    p = p or ParametrosFases()
    n = len(informes)
    on = np.array([d["onset_ms"] for d in informes
                   if d["onset_ms"] is not None], float)
    din = np.array([d["dinamica_ms"] for d in informes
                    if d["dinamica_ms"] is not None], float)
    conf = [d["confirmado_imu"] for d in informes
            if d["confirmado_imu"] is not None]
    borde = -p.busqueda_previa_ms + 2 * 1000.0 / fs
    pct = lambda v: round(100.0 * v, 1)                  # noqa: E731
    q = lambda a, k: round(float(np.percentile(a, k)), 1) if len(a) else None  # noqa: E731
    return dict(
        n_gestos=n,
        sin_onset=int(n - len(on)),
        onset_mediana_ms=q(on, 50), onset_p10_ms=q(on, 10), onset_p90_ms=q(on, 90),
        dinamica_mediana_ms=q(din, 50),
        pct_sospechosos=pct(np.mean([d["sospechoso"] for d in informes])) if n else None,
        pct_anticipados=pct(np.mean([d["anticipado"] for d in informes])) if n else None,
        pct_borde_busqueda=pct(np.mean(on <= borde)) if len(on) else None,
        pct_confirmado_imu=pct(np.mean(conf)) if conf else None,
    )


def _escribir_columna(ruta: str, fase: np.ndarray) -> None:
    """Anade (o sustituye) la ultima columna `fase` sin tocar las demas."""
    with open(ruta, "r", encoding="utf-8", newline="") as f:
        contenido = f.read()
    fin_linea = "\r\n" if "\r\n" in contenido else "\n"
    lineas = contenido.splitlines()
    cabecera, datos = lineas[0], [l for l in lineas[1:] if l.strip()]
    if len(datos) != len(fase):
        raise ValueError(f"{ruta}: {len(datos)} filas en el archivo y "
                         f"{len(fase)} fases calculadas")
    sustituir = cabecera.split(",")[-1] == "fase"
    quitar = (lambda l: l.rsplit(",", 1)[0]) if sustituir else (lambda l: l)
    salida = [quitar(cabecera) + ",fase"]
    salida += [f"{quitar(l)},{f}" for l, f in zip(datos, fase)]
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(fin_linea.join(salida) + fin_linea)
    os.replace(tmp, ruta)


def _a_json(o):
    if hasattr(o, "item"):
        return o.item()
    return str(o)


def anotar_csv(ruta: str, p: Optional[ParametrosFases] = None,
               modo_base: str = "local", comparar_bases: bool = False) -> dict:
    p = p or ParametrosFases()
    df = pd.read_csv(ruta)
    if "fase" in df.columns:
        df = df.drop(columns="fase")
    fase, informes, fs = anotar_df(df, p, modo_base)
    _escribir_columna(ruta, fase)

    info = dict(
        csv=os.path.basename(ruta),
        fases_version=FASES_VERSION, firma=firma(p), parametros=asdict(p),
        modo_base=modo_base, fs_hz=round(fs, 2),
        filas_por_fase={str(k): int(v) for k, v in
                        zip(*np.unique(fase.astype(str), return_counts=True))},
        resumen=resumen(informes, fs, p),
        gestos=informes,
    )
    if comparar_bases:
        otro = "calibracion" if modo_base == "local" else "local"
        _, inf2, _ = anotar_df(df, p, otro)
        info["comparacion_base"] = {otro: resumen(inf2, fs, p)}

    with open(ruta_sidecar(ruta), "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2, ensure_ascii=False, default=_a_json)
    return info


def main():
    ap = argparse.ArgumentParser(description="Anade la columna fase a CSV de captura")
    ap.add_argument("csv", nargs="+")
    ap.add_argument("--modo_base", choices=["local", "calibracion"], default="local")
    ap.add_argument("--comparar_bases", action="store_true",
                    help="Resume tambien los onsets con la otra base.")
    ap.add_argument("--k", type=float, default=ParametrosFases.k)
    ap.add_argument("--t_ms", type=float, default=ParametrosFases.t_sostenido_ms)
    ap.add_argument("--recorte_ini", type=float,
                    default=ParametrosFases.recorte_reposo_ini_ms)
    ap.add_argument("--recorte_fin", type=float,
                    default=ParametrosFases.recorte_reposo_fin_ms)
    args = ap.parse_args()

    p = ParametrosFases(k=args.k, t_sostenido_ms=args.t_ms,
                        recorte_reposo_ini_ms=args.recorte_ini,
                        recorte_reposo_fin_ms=args.recorte_fin)
    for ruta in args.csv:
        info = anotar_csv(ruta, p, args.modo_base, args.comparar_bases)
        r = info["resumen"]
        print(f"{info['csv']}: {r['n_gestos']} gestos, onset mediano "
              f"{r['onset_mediana_ms']} ms (p10 {r['onset_p10_ms']}, p90 "
              f"{r['onset_p90_ms']}), dinamica {r['dinamica_mediana_ms']} ms, "
              f"{r['pct_sospechosos']}% sospechosos, {r['pct_borde_busqueda']}% "
              f"en el borde de busqueda, IMU confirma {r['pct_confirmado_imu']}%")
        print(f"    filas por fase: {info['filas_por_fase']}")
        for modo, rr in info.get("comparacion_base", {}).items():
            print(f"    con base {modo}: onset mediano {rr['onset_mediana_ms']} "
                  f"ms, {rr['pct_sospechosos']}% sospechosos, "
                  f"{rr['pct_borde_busqueda']}% en el borde")


if __name__ == "__main__":
    main()
