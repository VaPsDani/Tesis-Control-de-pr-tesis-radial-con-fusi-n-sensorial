"""
diagnostico_int8.py - De donde sale la perdida INT8 (sin tocar la arquitectura)
==============================================================================
Protesis transradial - Fusion sensorial y Deep Learning

1. McNemar pareado float vs INT8 sobre el mismo test. Las ventanas
   solapadas no son independientes: el p-valor es optimista.
2. Error de cuantizacion por capa (tf.lite.experimental.QuantizationDebugger).
3. Tamano de la calibracion: 1000 (produccion) frente a 2000 ventanas del
   train (las 1000 primeras mas 1000 al azar).
4. Cuantizacion selectiva: deja en coma flotante la capa con mas error y
   mide cuanto se recupera (TFLite Micro tiene kernels float para esas ops).

USO (entorno de produccion):
  python diagnostico_int8.py --pliegue 1 --resultados resultados
"""

import os as _os
import sys as _sys
_M2 = _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                     "..", ".."))
for _d in (_M2, _os.path.join(_M2, "common"), _os.path.join(_M2, "produccion"),
           _os.path.join(_M2, "experimentos", "cuantizacion_int8")):
    if _d not in _sys.path:
        _sys.path.insert(0, _d)

import keras_legado
keras_legado.activar()

import argparse                 # noqa: E402
import io                       # noqa: E402
import csv                      # noqa: E402
import json                     # noqa: E402
import os                       # noqa: E402

import numpy as np              # noqa: E402
import tensorflow as tf         # noqa: E402
from scipy.stats import binomtest  # noqa: E402

import convertir_tflite as prod          # noqa: E402
from cuantizar_evaluar import ejecutar   # noqa: E402
from modelo import MecanismoAtencion     # noqa: E402


def conversor(modelo, calib, n):
    forma = [1] + list(modelo.inputs[0].shape[1:])
    f = tf.function(lambda x: modelo(x, training=False))
    c = tf.lite.TFLiteConverter.from_concrete_functions(
        [f.get_concrete_function(tf.TensorSpec(forma, tf.float32))], modelo)
    c.optimizations = [tf.lite.Optimize.DEFAULT]
    c.representative_dataset = lambda: prod.representative_dataset_gen(calib, n)
    c.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    c.inference_input_type = tf.float32
    c.inference_output_type = tf.float32
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pliegue", type=int, default=1)
    ap.add_argument("--resultados", default="resultados")
    args = ap.parse_args()
    R = args.resultados
    d = np.load(os.path.join(R, f"datos_pliegue{args.pliegue}.npz"))
    X, y = d["X_test"], d["y_test"].astype(int)
    modelo = tf.keras.models.load_model(
        os.path.join(R, f"modelo_float_pliegue{args.pliegue}.keras"),
        custom_objects={"MecanismoAtencion": MecanismoAtencion})
    pf = modelo.predict(X, verbose=0, batch_size=256)
    pq = np.load(os.path.join(R, "int8_produccion", "p_test.npy"))
    out = {}

    # 1. McNemar exacto
    bf, bq = pf.argmax(1) == y, pq.argmax(1) == y
    b, c = int((bf & ~bq).sum()), int((~bf & bq).sum())
    out["mcnemar"] = {"float_bien_int8_mal": b, "float_mal_int8_bien": c,
                      "p_valor_exacto": float(binomtest(b, b + c, 0.5).pvalue)}
    print("[1] McNemar:", out["mcnemar"])

    # 2. Error por capa, con 1000 ventanas del test como datos de depuracion
    sel = np.linspace(0, len(X) - 1, 1000).astype(int)
    dbg = tf.lite.experimental.QuantizationDebugger(
        converter=conversor(modelo, d["calib_produccion"], 1000),
        debug_dataset=lambda: ([x[None]] for x in X[sel]))
    dbg.run()
    buf = io.StringIO(); dbg.layer_statistics_dump(buf); buf.seek(0)
    capas = []
    for r in csv.DictReader(buf):
        esc = float(r["scale"]) if r.get("scale") else 0.0
        rel = (float(r["mean_squared_error"]) ** 0.5 / esc) if esc > 0 else float("nan")
        capas.append({"op": r["op_name"], "tensor": r["tensor_name"], "rmse_en_pasos": rel})
    capas_ord = sorted([c_ for c_ in capas if c_["rmse_en_pasos"] == c_["rmse_en_pasos"]],
                       key=lambda c_: -c_["rmse_en_pasos"])
    out["capas_peor_error"] = capas_ord[:6]
    print("[2] Capas con mas error (RMSE en pasos de cuantizacion):")
    for c_ in capas_ord[:6]:
        print(f"    {c_['op']:30s} {c_['rmse_en_pasos']:.2f}  {c_['tensor'][-50:]}")

    # 3. Calibracion con 5000 ventanas al azar del train (npz guarda 1000; se
    #    recombinan las dos muestras de 1000 y se repite con 2000)
    calib2 = np.concatenate([d["calib_produccion"], d["calib_azar"]])
    p2 = ejecutar(conversor(modelo, calib2, len(calib2)).convert(), X)
    out["calibracion_2000"] = float((p2.argmax(1) == y).mean())
    print(f"[3] Calibracion 2000 ventanas: acc {out['calibracion_2000']*100:.2f} %")

    # 4. Selectiva: la op con mas error, en float
    peor = capas_ord[0]["tensor"]
    opts = tf.lite.experimental.QuantizationDebugOptions(denylisted_nodes=[peor])
    dbg2 = tf.lite.experimental.QuantizationDebugger(
        converter=conversor(modelo, d["calib_produccion"], 1000),
        debug_dataset=lambda: ([x[None]] for x in X[sel[:10]]), debug_options=opts)
    tfl_sel = dbg2.get_nondebug_quantized_model()
    ps = ejecutar(tfl_sel, X)
    ops = sorted({o["op_name"] for o in tf.lite.Interpreter(model_content=tfl_sel)._get_ops_details()})
    os.makedirs(os.path.join(R, "int8_selectivo"), exist_ok=True)
    open(os.path.join(R, "int8_selectivo", "modelo_gestos.tflite"), "wb").write(tfl_sel)
    np.save(os.path.join(R, "int8_selectivo", "p_test.npy"), ps)
    out["selectiva"] = {"nodo_en_float": peor, "accuracy": float((ps.argmax(1) == y).mean()),
                        "bytes": len(tfl_sel), "operaciones": ops}
    print(f"[4] {peor[-50:]} en float: acc {out['selectiva']['accuracy']*100:.2f} %, "
          f"{len(tfl_sel)/1024:.1f} KB, ops {ops}")

    out["float"] = float(bf.mean()); out["int8_produccion"] = float(bq.mean())
    with open(os.path.join(R, f"diagnostico_pliegue{args.pliegue}.json"), "w") as f:
        json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()
