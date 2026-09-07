"""
captura_sesion.py - Punto de entrada de la app de captura
==========================================================
Protesis transradial - Captura con voluntarios

USO:
  python captura_sesion.py --puerto COM3
  python captura_sesion.py --simulado          (sin hardware)

REQUISITOS:
  pyserial. Tkinter viene con la biblioteca estandar de Python.

PROTOCOLO DE LA SESION (ver captura/protocolo.py):
  15 s de calibracion en reposo + 6 repeticiones x 4 gestos, cada uno
  con 8 s de reposo y 15 s de contraccion. 9.4 min de grabacion.

  El orden de los gestos esta CONTRABALANCEADO con semilla derivada del
  subject_id, para que el arrastre fisiologico entre gestos consecutivos
  no quede asociado siempre al mismo par.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "captura"))

from sesion import Sesion


def main():
    p = argparse.ArgumentParser(description="Captura de sesiones LMG")
    p.add_argument("--puerto", type=str, default="COM3")
    p.add_argument("--simulado", action="store_true",
                   help="Genera muestras sinteticas, sin hardware")
    p.add_argument("--salida", type=str, default="sesiones",
                   help="Directorio de sesiones (default: sesiones/)")
    args = p.parse_args()

    app = Sesion(dir_salida=args.salida)
    app.op.var_puerto.set(args.puerto)
    app.op.var_simulado.set(args.simulado)
    app.run()


if __name__ == "__main__":
    main()
