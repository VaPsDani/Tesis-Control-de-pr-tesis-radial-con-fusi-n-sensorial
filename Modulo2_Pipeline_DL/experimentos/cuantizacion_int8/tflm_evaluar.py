"""
tflm_evaluar.py - Etapa 3: las variantes cuantizadas en TensorFlow Lite Micro
===========================================================================
Protesis transradial - Fusion sensorial y Deep Learning

Ejecuta cada .tflite de cuantizar_evaluar.py con el interprete OFICIAL de
TFLite Micro (kernels de microcontrolador) sobre el mismo test:
  - si una operacion o su variante de tipos no esta soportada, falla aqui;
  - arena usada (la imprime TFLite Micro: 'Arena allocation total');
  - exactitud y acuerdo con el TFLite de PC.

Entorno aparte (Python 3.13), requirements-tflm.txt:
  ~/venv-tflm313/bin/python tflm_evaluar.py --pliegue 1 --resultados resultados
"""

import argparse
import json
import os

import numpy as np
from tflite_micro.python.tflite_micro import runtime


def cargar(ruta, x):
    """Interprete con arena holgada (64 KB). Reintentar con arenas pequenas
    tras un fallo de asignacion revienta el envoltorio de Python, asi que no
    se busca el minimo aqui: la arena real la imprime el propio TFLite Micro
    al crear el interprete ('Arena allocation total')."""
    it = runtime.Interpreter.from_file(ruta, arena_size=64 * 1024)
    it.set_input(x, 0); it.invoke()
    return it


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pliegue", type=int, default=1)
    ap.add_argument("--resultados", default="resultados")
    args = ap.parse_args()
    R = args.resultados
    d = np.load(os.path.join(R, f"datos_pliegue{args.pliegue}.npz"))
    X, y = d["X_test"], d["y_test"].astype(int)
    salida = {}
    for var in sorted(os.listdir(R)):
        ruta = os.path.join(R, var, "modelo_gestos.tflite")
        if not os.path.isfile(ruta):
            continue
        try:
            it = cargar(ruta, X[:1])
        except Exception as e:           # noqa: BLE001
            salida[var] = {"soportado_tflm": False, "error": str(e)}
            print(f"{var:16s} NO SOPORTADO en TFLite Micro: {e}")
            continue
        p = np.empty((len(X), 5), np.float32)
        for k, x in enumerate(X):
            it.reset()   # estado de la LSTM a cero: cada ventana es independiente
            it.set_input(x[None], 0); it.invoke(); p[k] = np.array(it.get_output(0))[0]
        p_pc = np.load(os.path.join(R, var, "p_test.npy"))
        r = {"soportado_tflm": True,
             "accuracy": float((p.argmax(1) == y).mean()),
             "acuerdo_con_tflite_pc": float((p.argmax(1) == p_pc.argmax(1)).mean()),
             "max_dif_con_tflite_pc": float(np.abs(p - p_pc).max())}
        salida[var] = r
        print(f"{var:16s} TFLM acc {r['accuracy']*100:6.2f} %  "
              f"igual que TFLite PC en {r['acuerdo_con_tflite_pc']*100:.2f} %")
    with open(os.path.join(R, f"tflm_pliegue{args.pliegue}.json"), "w") as f:
        json.dump(salida, f, indent=2)


if __name__ == "__main__":
    main()
