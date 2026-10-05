"""
perdida_cuantizacion.py - Perdida por cuantizacion INT8 (A21), pliegue a pliegue
=================================================================================
Protesis transradial - Etapa 4

PARA CADA PLIEGUE de la ablacion (corrida con --guardar_modelos):
  1. Carga el modelo reentrenado del pliegue.
  2. Lo cuantiza a INT8 con un representative dataset de 1000 ventanas de
     SUS sujetos de entrenamiento, los 7 que ajustaron y el de validacion
     (A23). Ninguna ventana de prueba.
  3. Predice con el modelo flotante y con el INT8 sobre SUS sujetos de
     prueba, los mismos datos para los dos. El INT8 se ejecuta ventana a
     ventana reiniciando el estado de la LSTM, como el firmware.

PERDIDA (A21): F1 macro de 5 clases del flotante menos el del INT8, en
puntos porcentuales, sobre todas las ventanas de prueba de todos los
pliegues. Se informa tambien por pliegue y como media por participante.

Control: el modelo recargado tiene que reproducir las predicciones que la
ablacion guardo durante el entrenamiento (predicciones.npz). Si no, los
datos o el modelo no son los mismos y la comparacion no vale.

Regla acordada para la Etapa 4: si la perdida supera 1 punto porcentual,
se aplica una ganancia fija al acelerometro en Python y en el firmware.

Uso:
  python perdida_cuantizacion.py --ablacion resultados_ablacion --sesiones "../sesiones/*.csv"
"""

import os as _os
import sys as _sys
_M2 = _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                     ".."))
for _d in (_M2, _os.path.join(_M2, "common"), _os.path.join(_M2, "produccion")):
    if _d not in _sys.path:
        _sys.path.insert(0, _d)

import keras_legado                              # noqa: E402
keras_legado.activar()

import argparse                                  # noqa: E402
import json                                      # noqa: E402
import os                                        # noqa: E402

import numpy as np                               # noqa: E402
import tensorflow as tf                          # noqa: E402

import preprocesamiento as P                     # noqa: E402
from convertir_tflite import (convertir_modelo, ejecutar_tflite,  # noqa: E402
                              escala_entrada, ventanas_de_calibracion)
from metricas import metricas, por_sujeto        # noqa: E402
from modelo import MecanismoAtencion             # noqa: E402

UMBRAL_PP = 1.0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ablacion", required=True,
                    help="carpeta de salida de ablacion_imu.py --guardar_modelos")
    ap.add_argument("--sesiones", required=True)
    ap.add_argument("--composicion", default="lmg_imu", choices=list(P.COMPOSICIONES))
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    with open(os.path.join(args.ablacion, "ablacion_imu.json"), encoding="utf-8") as f:
        info = json.load(f)
    roles = info["roles_por_pliegue"][args.composicion]
    guardadas = np.load(os.path.join(args.ablacion, "predicciones.npz"), allow_pickle=True)
    prob_ablacion = guardadas[f"prob_{args.composicion}"]

    v = P.preparar_sesiones(args.sesiones)
    if len(v) != len(prob_ablacion):
        raise ValueError("Las sesiones no dan las mismas ventanas que en la ablacion.")
    cols = [P.COLUMNAS_MODELO.index(c) for c in P.COMPOSICIONES[args.composicion]]

    p_float = np.zeros_like(prob_ablacion)
    p_int8 = np.zeros_like(prob_ablacion)
    evaluada = np.zeros(len(v), dtype=bool)
    pliegues = []
    for r in roles:
        k = r["pliegue"]
        ruta = os.path.join(args.ablacion, "modelos", f"{args.composicion}_pliegue{k}.keras")
        modelo = tf.keras.models.load_model(
            ruta, custom_objects={"MecanismoAtencion": MecanismoAtencion})
        entrenamiento = sorted(r["entrenamiento"] + r["validacion"])
        X_cal = ventanas_de_calibracion(v, entrenamiento, args.composicion,
                                        semilla=args.seed + k)
        m = np.isin(v.sujeto, r["prueba"])
        X_te = v.X[m][:, :, cols]

        pf = modelo.predict(X_te, batch_size=256, verbose=0)
        control = float(np.abs(pf - prob_ablacion[m]).max())
        tfl = convertir_modelo(modelo, X_cal)
        pi = ejecutar_tflite(tfl, X_te)
        escala, cero = escala_entrada(tfl)
        p_float[m], p_int8[m], evaluada[m] = pf, pi, True

        mf = metricas(v.y[m], pf.argmax(1), P.NOMBRES_CLASES, todas_las_clases=True)
        mi = metricas(v.y[m], pi.argmax(1), P.NOMBRES_CLASES, todas_las_clases=True)
        pliegues.append({
            "pliegue": k, "entrenamiento_y_calibracion": entrenamiento,
            "prueba": r["prueba"], "n_prueba": int(m.sum()),
            "f1_float": mf["f1_macro"], "f1_int8": mi["f1_macro"],
            "perdida_pp": 100 * (mf["f1_macro"] - mi["f1_macro"]),
            "acuerdo_float_int8": float((pf.argmax(1) == pi.argmax(1)).mean()),
            "bytes_tflite": len(tfl),
            # Paso de la entrada, unico para todos los canales, y cuantos
            # niveles le quedan a 1 g de acelerometro con ese paso.
            "paso_entrada": escala, "cero_entrada": cero,
            "niveles_por_g": 1.0 / escala,
            "control_dif_max_con_la_ablacion": control,
        })
        print(f"[PLIEGUE {k + 1}] prueba {r['prueba']}  F1 float {mf['f1_macro']:.4f}  "
              f"INT8 {mi['f1_macro']:.4f}  perdida {pliegues[-1]['perdida_pp']:+.2f} pp  "
              f"acuerdo {100 * pliegues[-1]['acuerdo_float_int8']:.1f}%  "
              f"control {control:.1e}  {len(tfl) / 1024:.1f} KB  "
              f"paso de la entrada {escala:.4f} ({1 / escala:.0f} niveles por g)")
        tf.keras.backend.clear_session()

    y = v.y[evaluada]
    gf = metricas(y, p_float[evaluada].argmax(1), P.NOMBRES_CLASES, todas_las_clases=True)
    gi = metricas(y, p_int8[evaluada].argmax(1), P.NOMBRES_CLASES, todas_las_clases=True)
    sf = por_sujeto(y, p_float[evaluada].argmax(1), v.sujeto[evaluada],
                    P.NOMBRES_CLASES, todas_las_clases=True)
    si = por_sujeto(y, p_int8[evaluada].argmax(1), v.sujeto[evaluada],
                    P.NOMBRES_CLASES, todas_las_clases=True)
    por_suj = {s: 100 * (sf[s]["f1_macro"] - si[s]["f1_macro"]) for s in sf}
    perdida = 100 * (gf["f1_macro"] - gi["f1_macro"])
    aplicar = perdida > UMBRAL_PP
    res = {
        "composicion": args.composicion,
        "f1_macro_float": gf["f1_macro"], "f1_macro_int8": gi["f1_macro"],
        "perdida_pp": perdida,
        "perdida_media_por_participante_pp": float(np.mean(list(por_suj.values()))),
        "perdida_por_participante_pp": por_suj,
        "umbral_pp": UMBRAL_PP,
        "aplicar_ganancia_acelerometro": bool(aplicar),
        "pliegues": pliegues,
    }
    print(f"\n[A21] {args.composicion}: F1 macro float {gf['f1_macro']:.4f}, INT8 "
          f"{gi['f1_macro']:.4f}, perdida {perdida:+.2f} pp (media por participante "
          f"{res['perdida_media_por_participante_pp']:+.2f} pp)")
    print(f"[A21] Umbral {UMBRAL_PP} pp: "
          + ("SE SUPERA, aplicar la ganancia fija del acelerometro."
             if aplicar else "no se supera, no hace falta tocar la escala."))
    ruta = os.path.join(args.ablacion, f"perdida_cuantizacion_{args.composicion}.json")
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2, ensure_ascii=False)
    print(f"[SALIDA] {ruta}")


if __name__ == "__main__":
    main()
