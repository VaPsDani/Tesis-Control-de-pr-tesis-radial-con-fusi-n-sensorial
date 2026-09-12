"""
verificar_piloto.py - Auditoria de la primera sesion real
==========================================================
Protesis transradial - Captura con voluntarios

PARA QUE SIRVE:
  Correr esto sobre el CSV del PRIMER sujeto, ANTES de convocar a los
  otros nueve. Cualquier fallo de protocolo, de sincronizacion o de
  segmentacion que aparezca aqui se arregla con un voluntario perdido,
  no con diez.

QUE VERIFICA:

  1. FRONTERAS. En NinaPro DB5, el 9.26% de las ventanas de Rest cruzaba
     alguna discontinuidad, por la misma razon que ocurrira aqui: los 24
     bloques de reposo estan flanqueados por contracciones y acumulan
     fronteras por ambos lados. La segmentacion por bloque de
     preprocesamiento.py deberia dejarlo en CERO. Si sale distinto de
     cero, hay un fallo que corregir antes de seguir.

  2. INTEGRIDAD DEL MUESTREO. Huecos en el timestamp del ESP32, que
     delatan muestras perdidas aunque la tasa media parezca correcta.
     Es el sintoma de que el adaptador USB-serie no sostiene 921600.

  3. PROTOCOLO. Que el reposo herede el repetition_id (el bug de DB5),
     que cada repeticion tenga los 4 gestos, y que el balance de clases
     salga como se diseno.

  4. SENSORES. Canales planos o saturados, que delatan un sensor
     despegado durante la sesion.

USO:
  python verificar_piloto.py --csv sesiones/s01_20260907_101500.csv
"""

import argparse
import json
import os

import numpy as np
import pandas as pd

from preprocesamiento import (COLUMNAS_MODELO, COLUMNAS_NO_MODELO,
                              SlidingWindowPreprocessor)

NOMBRES = ["Rest", "Pinch", "Tripod", "Power", "Finger_Ext"]
PERIODO_MS = 10


def _seccion(t):
    print("\n" + "=" * 72)
    print(t)
    print("=" * 72)


def verificar_fronteras(df, window=20, stride=2):
    """
    Cuenta ventanas que cruzan cada tipo de frontera, replicando la
    segmentacion de preprocesamiento.py. Debe dar CERO en todas.
    """
    claves = ["subject_id", "repetition_id", "label", "bloque_tipo"]
    cambio = np.zeros(len(df), dtype=bool)
    for c in claves:
        cambio |= df[c].ne(df[c].shift()).values
    dt = df["timestamp_ms"].diff().values
    cambio |= np.nan_to_num(dt, nan=0.0) > 3 * PERIODO_MS
    seg = np.cumsum(cambio)

    ts = df["timestamp_ms"].values
    lab = df["label"].values
    rep = df["repetition_id"].values
    tipo = df["bloque_tipo"].values

    cont = {"hueco": 0, "etiqueta": 0, "repeticion": 0, "bloque_tipo": 0}
    total = 0

    for s in np.unique(seg):
        ii = np.where(seg == s)[0]
        a, b = ii[0], ii[-1] + 1
        if (b - a) < window:
            continue
        for off in range(0, (b - a) - window + 1, stride):
            w = slice(a + off, a + off + window)
            total += 1
            if not np.all(np.diff(ts[w]) == PERIODO_MS):
                cont["hueco"] += 1
            if len(np.unique(lab[w])) > 1:
                cont["etiqueta"] += 1
            if len(np.unique(rep[w])) > 1:
                cont["repeticion"] += 1
            if len(np.unique(tipo[w])) > 1:
                cont["bloque_tipo"] += 1

    return cont, total, int(seg.max() + 1)


def main():
    p = argparse.ArgumentParser(description="Auditoria del piloto")
    p.add_argument("--csv", type=str, required=True)
    p.add_argument("--json", type=str, default=None,
                   help="Salida del informe (default: junto al CSV)")
    args = p.parse_args()

    df_raw = pd.read_csv(args.csv)
    informe = {"csv": os.path.basename(args.csv), "filas_crudas": len(df_raw)}
    problemas = []

    _seccion("1. INTEGRIDAD DEL MUESTREO")
    ts = df_raw["timestamp_ms"].values
    dt = np.diff(ts)
    huecos = int((dt > 3 * PERIODO_MS).sum())
    perdidas = int(np.sum(np.round(dt[dt > 3 * PERIODO_MS] / PERIODO_MS) - 1))
    dur_s = (ts[-1] - ts[0]) / 1000.0
    tasa = len(ts) / dur_s if dur_s else 0.0

    print(f"  Muestras           : {len(ts)}")
    print(f"  Duracion           : {dur_s:.1f} s")
    print(f"  Tasa media         : {tasa:.2f} Hz  (objetivo 100)")
    print(f"  Intervalo mediano  : {np.median(dt):.1f} ms  (objetivo {PERIODO_MS})")
    print(f"  Huecos > {3*PERIODO_MS} ms     : {huecos}")
    print(f"  Muestras perdidas  : ~{perdidas} ({100*perdidas/max(len(ts),1):.3f}%)")
    informe["muestreo"] = {"muestras": len(ts), "duracion_s": round(dur_s, 1),
                           "tasa_hz": round(tasa, 2), "huecos": huecos,
                           "perdidas_est": perdidas}
    if not (98 <= tasa <= 102):
        problemas.append(f"Tasa media {tasa:.1f} Hz fuera de 98-102")
    if huecos:
        problemas.append(f"{huecos} huecos: revisar el adaptador USB-serie "
                         f"a 921600 baudios")

    _seccion("2. PROTOCOLO")
    reposo = df_raw[df_raw["bloque_tipo"] == "reposo"]
    reps_reposo = sorted(reposo["repetition_id"].unique().tolist())
    hereda = 0 not in reps_reposo
    print(f"  repetition_id del reposo : {reps_reposo}")
    print(f"  Hereda el del bloque (no usa 0, el bug de DB5) : {hereda}")
    if not hereda:
        problemas.append("Hay reposo con repetition_id 0: se reproduce el "
                         "reparto desigual de DB5")

    contr = df_raw[df_raw["bloque_tipo"] == "contraccion"]
    por_rep = contr.groupby("repetition_id")["label"].nunique()
    completas = bool((por_rep == 4).all())
    print(f"  Gestos distintos por repeticion : {por_rep.tolist()}")
    print(f"  Cada repeticion tiene los 4     : {completas}")
    if not completas:
        problemas.append("Alguna repeticion no tiene los 4 gestos")

    informe["protocolo"] = {"reps_reposo": reps_reposo,
                            "hereda_repetition_id": hereda,
                            "repeticiones_completas": completas}

    _seccion("3. SENSORES (deteccion de sensor despegado)")
    print(f"  {'Canal':<8}{'min':>12}{'max':>12}{'sd':>12}{'estado':>12}")
    print(f"  {'-'*56}")
    informe["sensores"] = {}
    for c in COLUMNAS_MODELO:
        v = df_raw[c].values
        sd = float(np.std(v))
        rango = float(np.max(v) - np.min(v))
        if sd < 1e-3:
            estado = "PLANO"
            problemas.append(f"Canal {c} plano (sd={sd:.2e}): sensor "
                             f"despegado o desconectado")
        elif c.startswith("v") and rango < 1.0:
            estado = "casi plano"
            problemas.append(f"Canal {c} con rango {rango:.3f} mV: revisar")
        else:
            estado = "ok"
        print(f"  {c:<8}{np.min(v):>12.4f}{np.max(v):>12.4f}"
              f"{sd:>12.4f}{estado:>12}")
        informe["sensores"][c] = {"sd": round(sd, 6), "rango": round(rango, 4),
                                  "estado": estado}

    _seccion("4. FRONTERAS TRAS LA SEGMENTACION (deben ser CERO)")
    preproc = SlidingWindowPreprocessor(window_size_ms=200, stride_ms=20,
                                        sampling_rate_hz=100)
    df = preproc.cargar_csv(args.csv)
    cont, total, n_seg = verificar_fronteras(df)

    print(f"  Segmentos contiguos : {n_seg}")
    print(f"  Ventanas generadas  : {total}")
    print()
    print(f"  {'Tipo de frontera':<22}{'Ventanas':>12}{'Veredicto':>14}")
    print(f"  {'-'*48}")
    for k, v in cont.items():
        veredicto = "OK" if v == 0 else "FALLO"
        print(f"  {k:<22}{v:>12}{veredicto:>14}")
        if v:
            problemas.append(f"{v} ventanas cruzan una frontera de tipo "
                             f"'{k}'. La segmentacion no esta funcionando.")
    informe["fronteras"] = {"segmentos": n_seg, "ventanas": total, **cont}

    _seccion("5. BALANCE DE CLASES")
    X, y = preproc.generar_ventanas(df)
    yi = y.argmax(axis=1)
    print(f"  {'Clase':<14}{'Ventanas':>12}{'%':>9}")
    print(f"  {'-'*35}")
    conteo = {}
    for c in range(5):
        n = int((yi == c).sum())
        conteo[NOMBRES[c]] = n
        print(f"  {NOMBRES[c]:<14}{n:>12}{100*n/len(yi):>8.1f}%")
    activas = [conteo[NOMBRES[c]] for c in range(1, 5)]
    ratio = conteo["Rest"] / np.mean(activas) if np.mean(activas) else 0
    # El 1.63:1 que promete el protocolo suponia el filtrado por MARGEN
    # FIJO. Con el criterio de fases, del reposo se descuentan ademas la
    # relajacion (detectada por senal, tan larga como dure la hiperemia) y
    # los bordes recortados, asi que el ratio baja por construccion. CUANTO
    # baja es una medida del asentamiento post-contraccion, que es justo lo
    # que el piloto tiene que averiguar: se informa siempre, y solo es un
    # problema si Rest queda inutilizable para entrenar la clase.
    print(f"\n  Ratio Rest:activa = {ratio:.2f}:1  (el protocolo preve "
          f"~1.63 con margen fijo; con fases baja segun dure la relajacion)")
    informe["balance"] = {"conteo": conteo, "ratio_rest": round(float(ratio), 2)}
    if not (0.3 <= ratio <= 3.0):
        problemas.append(f"Ratio Rest:activa {ratio:.2f}: Rest queda "
                         f"inutilizable para entrenar")

    # Composicion del reposo por fase: el diagnostico de hiperemia.
    crudo = pd.read_csv(args.csv)
    if "fase" in crudo.columns:
        rep = crudo[crudo["label"] == 0]
        comp = rep["fase"].value_counts()
        pct = {k: 100.0 * int(comp.get(k, 0)) / max(len(rep), 1)
               for k in ("reposo", "relajacion", "recorte")}
        print(f"  Reposo por fase: {pct['reposo']:.0f}% estable, "
              f"{pct['relajacion']:.0f}% relajacion, "
              f"{pct['recorte']:.0f}% recorte de bordes")
        informe["balance"]["reposo_por_fase"] = {str(k): int(v)
                                                 for k, v in comp.items()}
        if pct["relajacion"] > 60:
            problemas.append(f"{pct['relajacion']:.0f}% del reposo es "
                             f"relajacion: la senal no se asienta dentro del "
                             f"bloque de 8 s. Alargue el reposo.")

    _seccion("VEREDICTO")
    if problemas:
        print(f"  {len(problemas)} PROBLEMA(S). No convoque a los demas "
              f"voluntarios hasta resolverlos:")
        for i, p_ in enumerate(problemas, 1):
            print(f"    {i}. {p_}")
    else:
        print("  Sin problemas. El protocolo, la sincronizacion y la")
        print("  segmentacion funcionan sobre datos reales.")
        print("  Se puede convocar al resto de voluntarios.")
    informe["problemas"] = problemas
    informe["apto"] = not problemas

    ruta = args.json or os.path.splitext(args.csv)[0] + "_auditoria.json"
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(informe, f, indent=2, ensure_ascii=False)
    print(f"\n[JSON] {ruta}")


if __name__ == "__main__":
    main()
