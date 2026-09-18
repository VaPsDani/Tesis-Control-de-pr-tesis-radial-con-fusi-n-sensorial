"""
captura_sesion.py - Punto de entrada de la app de captura
==========================================================
Protesis transradial - Captura con voluntarios

USO:
  python captura_sesion.py --puerto COM3
  python captura_sesion.py --puerto COM3 --postura dinamico
  python captura_sesion.py --simulado          (sin hardware)

  Todo lo que se pasa por linea de comandos se puede cambiar tambien en
  la ventana del operador antes de iniciar.

REQUISITOS:
  pyserial. Tkinter viene con la biblioteca estandar de Python.

PROTOCOLO DE LA SESION (ver captura/protocolo.py):
  15 s de calibracion en reposo + 6 repeticiones x 4 gestos. Cada gesto
  son tres fases seguidas: preparacion de 3 s, contraccion de 10 s y
  reposo de 8 s. 8.7 min de grabacion.

  El orden de los gestos esta CONTRABALANCEADO con semilla derivada del
  subject_id, para que el arrastre fisiologico entre gestos consecutivos
  no quede asociado siempre al mismo par.

  Los tiempos y los colores estan en captura/config_captura.py, que es
  el unico archivo que hay que editar para cambiar el protocolo.

MANUAL DEL OPERADOR:
  Modulo1_Adquisicion_Datos/gui_captura/README.md
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "captura"))

from config_captura import (BAUDIOS_DEFECTO, BLOQUE_ESTATICO, BLOQUES_POSTURA,
                            DIR_SALIDA_DEFECTO, PUERTO_DEFECTO)
from sesion import Sesion


def main():
    p = argparse.ArgumentParser(description="Captura de sesiones LMG")
    p.add_argument("--puerto", type=str, default=PUERTO_DEFECTO)
    p.add_argument("--baudios", type=int, default=BAUDIOS_DEFECTO,
                   help="Por defecto el del firmware")
    p.add_argument("--simulado", action="store_true",
                   help="Genera muestras sinteticas, sin hardware")
    p.add_argument("--salida", type=str, default=DIR_SALIDA_DEFECTO,
                   help="Directorio de sesiones")
    p.add_argument("--participante", type=str, default="S01",
                   help="Id anonimo del participante")
    p.add_argument("--postura", choices=BLOQUES_POSTURA,
                   default=BLOQUE_ESTATICO, help="Bloque de postura")
    args = p.parse_args()

    app = Sesion(dir_salida=args.salida)
    app.op.var_puerto.set(args.puerto)
    app.op.var_baudios.set(str(args.baudios))
    app.op.var_simulado.set(args.simulado)
    app.op.var_id_participante.set(args.participante)
    app.op.var_postura.set(args.postura)
    app.run()


if __name__ == "__main__":
    main()
