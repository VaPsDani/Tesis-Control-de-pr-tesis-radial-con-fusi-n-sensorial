"""Rutas para que los tests importen los modulos planos del Modulo 2."""
import os
import sys

M2 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

for d in (M2,
          os.path.join(M2, "common"),
          os.path.join(M2, "produccion"),
          os.path.join(M2, "captura")):
    if d not in sys.path:
        sys.path.insert(0, d)
