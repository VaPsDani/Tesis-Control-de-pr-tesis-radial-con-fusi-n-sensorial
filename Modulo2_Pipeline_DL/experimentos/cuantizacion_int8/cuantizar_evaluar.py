"""
cuantizar_evaluar.py - Etapa 2: coma flotante frente a INT8 sobre el mismo test
==============================================================================
Protesis transradial - Fusion sensorial y Deep Learning

Toma el modelo de entrenar_ninapro_100hz.py, lo convierte con
produccion/convertir_tflite.py (el mismo codigo que genera el modelo del
ESP32) y compara la exactitud sobre el MISMO test del pliegue.

Variantes:
  float32           control: convertido a TFLite SIN cuantizar. Tiene que dar
                    lo mismo que Keras; si no, el fallo es de conversion
  int8_produccion   calibracion con las 1000 primeras ventanas del train,
                    exactamente lo que hace convertir_tflite.py
  int8_azar         calibracion con 1000 ventanas al azar del train
  16x8_produccion   activaciones de 16 bits y pesos de 8 (solo con --16x8)
  16x8_azar

El .tflite se ejecuta con el interprete de TFLite sin delegados (sin
XNNPACK). tflm_evaluar.py repite la evaluacion con TFLite Micro.

USO (entorno de produccion):
  python cuantizar_evaluar.py --pliegue 1 --resultados resultados [--16x8]
"""

import os as _os
import sys as _sys
_M2 = _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                     "..", ".."))
for _d in (_M2, _os.path.join(_M2, "common"), _os.path.join(_M2, "produccion")):
    if _d not in _sys.path:
        _sys.path.insert(0, _d)

import keras_legado
keras_legado.activar()

import argparse                 # noqa: E402
import json                     # noqa: E402
import os                       # noqa: E402

import numpy as np              # noqa: E402
import tensorflow as tf         # noqa: E402
from sklearn.metrics import f1_score  # noqa: E402

import convertir_tflite as prod          # noqa: E402
from modelo import MecanismoAtencion     # noqa: E402

NOMBRES = ["Rest", "Pinch", "Tripod", "Power", "Finger_Ext"]


def convertir_16x8(modelo, X_calib):
    """Mismos ajustes que produccion salvo el esquema: activaciones int16."""
    forma = [1] + list(modelo.inputs[0].shape[1:])
    f = tf.function(lambda x: modelo(x, training=False))
    c = tf.lite.TFLiteConverter.from_concrete_functions(
        [f.get_concrete_function(tf.TensorSpec(forma, tf.float32))], modelo)
    c.optimizations = [tf.lite.Optimize.DEFAULT]
    c.representative_dataset = lambda: prod.representative_dataset_gen(X_calib, 1000)
    c.target_spec.supported_ops = [
        tf.lite.OpsSet.EXPERIMENTAL_TFLITE_BUILTINS_ACTIVATIONS_INT16_WEIGHTS_INT8]
    c.inference_input_type = tf.float32
    c.inference_output_type = tf.float32
    t = c.convert()
    prod.verificar_operaciones(t)
    return t


def ejecutar(tfl: bytes, X: np.ndarray) -> np.ndarray:
    it = tf.lite.Interpreter(
        model_content=tfl,
        experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES)
    it.allocate_tensors()
    i, o = it.get_input_details()[0]["index"], it.get_output_details()[0]["index"]
    p = np.empty((len(X), 5), np.float32)
    for k, x in enumerate(X):
        # La LSTM de TFLite guarda su estado en tensores variables que
        # persisten entre invoke(): sin reiniciarlos, cada ventana hereda el
        # estado de la anterior. Cada ventana es independiente.
        it.reset_all_variables()
        it.set_tensor(i, x[None]); it.invoke(); p[k] = it.get_tensor(o)[0]
    return p


def metricas(p, y, p_ref=None):
    yp = p.argmax(1)
    r = {"accuracy": float((yp == y).mean()),
         "f1_macro": float(f1_score(y, yp, average="macro", labels=range(5), zero_division=0)),
         "f1_por_clase": dict(zip(NOMBRES, map(float, f1_score(y, yp, average=None, labels=range(5), zero_division=0))))}
    if p_ref is not None:
        r["acuerdo_con_float"] = float((yp == p_ref.argmax(1)).mean())
        r["max_dif_prob"] = float(np.abs(p - p_ref).max())
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pliegue", type=int, default=1)
    ap.add_argument("--resultados", default="resultados")
    ap.add_argument("--16x8", dest="x16", action="store_true")
    args = ap.parse_args()
    R = args.resultados
    d = np.load(os.path.join(R, f"datos_pliegue{args.pliegue}.npz"))
    X, y = d["X_test"], d["y_test"].astype(int)
    ruta = os.path.join(R, f"modelo_float_pliegue{args.pliegue}.keras")
    modelo = tf.keras.models.load_model(ruta, custom_objects={"MecanismoAtencion": MecanismoAtencion})

    p_float = modelo.predict(X, verbose=0, batch_size=256)
    dif_guardado = float(np.abs(p_float - d["p_float"]).max())
    res = {"pliegue": args.pliegue, "n_test": int(len(X)),
           "sujetos_test": sorted(set(d["sujetos_test"].tolist())),
           "float": metricas(p_float, y), "control_float_recargado_vs_entrenamiento": dif_guardado,
           "variantes": {}}

    # Control: TFLite float32, sin cuantizar
    forma = [1] + list(modelo.inputs[0].shape[1:])
    fn = tf.function(lambda x: modelo(x, training=False))
    tfl32 = tf.lite.TFLiteConverter.from_concrete_functions(
        [fn.get_concrete_function(tf.TensorSpec(forma, tf.float32))], modelo).convert()
    prod.verificar_operaciones(tfl32)
    sal = os.path.join(R, "float32"); os.makedirs(sal, exist_ok=True)
    open(os.path.join(sal, "modelo_gestos.tflite"), "wb").write(tfl32)
    p = ejecutar(tfl32, X); np.save(os.path.join(sal, "p_test.npy"), p)
    res["variantes"]["float32"] = {"bytes": len(tfl32), **metricas(p, y, p_float)}

    for nombre, calib in (("int8_produccion", d["calib_produccion"]), ("int8_azar", d["calib_azar"])):
        sal = os.path.join(R, nombre)
        ruta_tfl = prod.convertir_a_tflite(ruta, calib, output_dir=sal)
        tfl = open(ruta_tfl, "rb").read()
        p = ejecutar(tfl, X)
        np.save(os.path.join(sal, "p_test.npy"), p)
        res["variantes"][nombre] = {"bytes": len(tfl), **metricas(p, y, p_float)}

    peor = max(res["float"]["accuracy"] - v["accuracy"] for n, v in res["variantes"].items() if n != "float32")
    if args.x16 or peor > 0.02:
        for nombre, calib in (("16x8_produccion", d["calib_produccion"]), ("16x8_azar", d["calib_azar"])):
            sal = os.path.join(R, nombre); os.makedirs(sal, exist_ok=True)
            try:
                tfl = convertir_16x8(modelo, calib)
            except Exception as e:
                res["variantes"][nombre] = {"error_conversion": str(e).splitlines()[0][:300]}
                continue
            open(os.path.join(sal, "modelo_gestos.tflite"), "wb").write(tfl)
            p = ejecutar(tfl, X)
            np.save(os.path.join(sal, "p_test.npy"), p)
            ops = sorted({o["op_name"] for o in tf.lite.Interpreter(model_content=tfl)._get_ops_details()})
            res["variantes"][nombre] = {"bytes": len(tfl), "operaciones": ops, **metricas(p, y, p_float)}

    with open(os.path.join(R, f"cuantizacion_pliegue{args.pliegue}.json"), "w") as f:
        json.dump(res, f, indent=2)
    print(f"\nFLOAT            acc {res['float']['accuracy']*100:6.2f} %  F1 {res['float']['f1_macro']:.4f}")
    for n, v in res["variantes"].items():
        if "error_conversion" in v:
            print(f"{n:16s} ERROR: {v['error_conversion']}"); continue
        print(f"{n:16s} acc {v['accuracy']*100:6.2f} %  F1 {v['f1_macro']:.4f}  "
              f"perdida {100*(res['float']['accuracy']-v['accuracy']):+.2f} pt  "
              f"acuerdo {v['acuerdo_con_float']*100:.1f} %  {v['bytes']/1024:.1f} KB")


if __name__ == "__main__":
    main()
