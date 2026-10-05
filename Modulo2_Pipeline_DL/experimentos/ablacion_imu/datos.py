"""
datos.py - Datos del experimento de ablacion de la IMU
=======================================================
Protesis transradial - Ablacion de la IMU

LA CARGA, LAS FASES, EL VENTANEO Y LA NORMALIZACION NO VIVEN AQUI.
Vienen de produccion/preprocesamiento.py (preparar_sesiones), que es la
misma funcion que usan el entrenamiento de produccion y la conversion
INT8 (A18 del articulo). Antes este modulo tenia su propio ventaneo, sin
detector de fases: la preparacion, con la mano relajada, entraba como
gesto en entrenamiento y en test. Ahora es imposible que la ablacion y
produccion preprocesen distinto, porque no hay dos codigos.

LO QUE SI ES DE AQUI:
  - Los niveles del factor A (que canales entran al modelo).
  - seleccionar_canales(), que es lo UNICO que cambia entre solo_lmg y
    lmg_imu: las cuatro celdas del 2x2 parten de las mismas ventanas.
  - El generador de sesiones sinteticas, para probar sin piloto.
"""

# Rutas del Modulo 2 tras la reorganizacion: common/ tiene el codigo
# compartido por todos los experimentos y produccion/ el pipeline del
# modelo que se despliega.
import os as _os
import sys as _sys
_M2 = _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                     "..", ".."))
for _d in (_M2, _os.path.join(_M2, "common"), _os.path.join(_M2, "produccion"),
           _os.path.join(_M2, "captura")):
    if _d not in _sys.path:
        _sys.path.insert(0, _d)

import os
from typing import List

import numpy as np
import pandas as pd

from preprocesamiento import (CANALES_ACC, CANALES_LMG,  # noqa: F401
                              COLUMNAS_MODELO, COMPOSICIONES,
                              CONDICIONES_POSTURALES, NOMBRES_CLASES,
                              Ventanas, preparar_sesiones)

# Niveles del factor B, tal como se escriben en el CSV.
CONDICION_ESTATICA, CONDICION_DINAMICA = CONDICIONES_POSTURALES

CANALES_IMU = CANALES_ACC

# Niveles del factor A (COMPOSICIONES) y nombres de las clases vienen del
# nucleo compartido, igual que para produccion.
NOMBRES_GESTOS = NOMBRES_CLASES
NUM_CLASES = len(NOMBRES_GESTOS)
LABEL_REST = 0

PERIODO_MS = 10


def cargar(patron, variante_fases: str = "dinamica_meseta",
           ventana: int = 20, paso: int = 2) -> Ventanas:
    """Las sesiones del patron, ya en ventanas y normalizadas."""
    return preparar_sesiones(patron, variante_fases, ventana, paso)


def seleccionar_canales(v: Ventanas, composicion: str) -> np.ndarray:
    """
    Devuelve X con los canales del nivel pedido del factor A.

    Es lo UNICO que cambia entre solo_lmg y lmg_imu: las mismas ventanas,
    las mismas filas, el mismo orden.
    """
    if composicion not in COMPOSICIONES:
        raise ValueError(f"Composicion desconocida: {composicion}. "
                         f"Use una de {list(COMPOSICIONES)}")
    cols = [v.canales.index(c) for c in COMPOSICIONES[composicion]]
    return v.X[:, :, cols]


def indices_de_canales(composicion: str) -> List[int]:
    return [COLUMNAS_MODELO.index(c) for c in COMPOSICIONES[composicion]]


# ============================================================
# SESIONES SINTETICAS, PARA PROBAR SIN PILOTO
# ============================================================
# Vector de gravedad, en g, que lee el acelerometro en cada postura del
# antebrazo. Son SUPUESTOS DEL SIMULADOR, elegidos para que la fisica
# sea plausible, no medidas: antebrazo horizontal en pronacion sobre la
# mesa, colgando al costado, al frente sin apoyo (casi como en la mesa) y
# con la mano por encima del hombro.
GRAVEDAD = {
    "mesa": np.array([0.0, 0.0, 1.0]),
    "abajo_al_costado": np.array([1.0, 0.0, 0.0]),
    "al_frente_codo_90": np.array([0.15, 0.0, 0.99]),
    "arriba_sobre_el_hombro": np.array([-0.9, 0.0, 0.4]),
}


def generar_sesiones_sinteticas(directorio: str, n_sujetos: int = 10,
                                semilla: int = 42) -> str:
    """
    Escribe CSV con la estructura exacta del protocolo, sin hardware.

    NO sustituyen al piloto ni producen resultados publicables: sirven
    para comprobar que el experimento corre de principio a fin, que las
    cuatro celdas quedan equilibradas y que la estadistica no se rompe.

    Lo que imitan, todo con supuestos del simulador:
      - REACCION: el gesto empieza entre 250 y 550 ms despues de la
        indicacion, y la fuerza sube en 1 s, como pide la barra.
      - SUELTA: al empezar el reposo la senal vuelve en 400 ms.
      - POSTURA: el acelerometro sigue el vector de gravedad de la postura
        con una constante de tiempo de 0.3 s, y la senal optica cambia
        con la postura. Esto ultimo es la premisa del trabajo: la LMG se
        mueve con el brazo aunque la mano no haga nada.
      - En las DINAMICAS el brazo va a la primera posicion durante la
        preparacion, con la mano relajada, y vuelve a la mesa despues de
        soltar el gesto. En el REPOSO EN MOVIMIENTO recorre las tres
        posiciones sin gesto.
    Asi la celda lmg_imu tiene, por construccion, informacion que
    solo_lmg no tiene en la condicion dinamica: el acelerometro dice en
    que postura esta el brazo.
    """
    from protocolo import (TIPO_CONTRACCION, TIPO_PREPARACION,
                           TIPO_REPOSO, TIPO_REPOSO_DINAMICO,
                           construir_sesion)

    os.makedirs(directorio, exist_ok=True)
    rng = np.random.RandomState(semilla)
    rutas = []
    dt = PERIODO_MS / 1000.0
    tau = 0.3

    for sujeto in range(1, n_sujetos + 1):
        bloques = construir_sesion(sujeto)
        filas = []
        t = 0
        escala = 1.0 + 0.3 * rng.rand()          # cada sujeto, su ganancia
        offset = 10.0 * rng.rand()
        acc = GRAVEDAD["mesa"].copy()
        nivel_previo = 0.0                        # fuerza al acabar el bloque
        ultima_postura = "mesa"
        for b in bloques:
            n = int(b.duracion_ms / PERIODO_MS)
            reaccion_ms = rng.uniform(250, 550)
            amplitud = escala * (1.0 + b.label) * 0.8
            dinamica = b.condicion_postural == CONDICION_DINAMICA
            for i in range(n):
                t_rel = i * PERIODO_MS
                # --- fuerza del gesto
                if b.tipo == TIPO_CONTRACCION:
                    sube = (t_rel - reaccion_ms) / 1000.0
                    nivel = amplitud * float(np.clip(sube, 0.0, 1.0))
                elif b.tipo == TIPO_REPOSO:
                    nivel = nivel_previo * max(0.0, 1.0 - t_rel / 400.0)
                else:
                    nivel = 0.0
                # --- postura que se esta pidiendo
                pos = b.posicion_en(b.t_inicio_ms + t_rel)
                if b.tipo in (TIPO_CONTRACCION, TIPO_REPOSO_DINAMICO) and pos:
                    postura = pos
                elif b.tipo == TIPO_PREPARACION and dinamica and t_rel >= 500:
                    postura = b.orden_posiciones[0]
                elif b.tipo == TIPO_REPOSO and dinamica and t_rel < 400:
                    postura = ultima_postura      # primero suelta, despues baja
                else:
                    postura = "mesa"
                acc += (GRAVEDAD[postura] - acc) * (dt / tau)
                desvio_postura = float(np.linalg.norm(acc - GRAVEDAD["mesa"]))

                lmg = (rng.randn(5) * 0.4 + offset + nivel
                       + 0.8 * desvio_postura * np.array([1.0, 0.7, 0.5, 0.8, 0.6]))
                filas.append([
                    sujeto, b.repetition_id, t,
                    *np.round(lmg, 4),
                    *np.round(acc + rng.randn(3) * 0.02, 4),
                    *np.round(rng.randn(3) * 0.5, 4),
                    b.label, b.tipo, b.condicion_postural,
                    b.en_margen(b.t_inicio_ms + t_rel), b.es_calibracion,
                    f"S{sujeto:02d}", pos, 0, 0,
                ])
                t += PERIODO_MS
            if b.tipo in (TIPO_CONTRACCION, TIPO_REPOSO_DINAMICO):
                ultima_postura = postura
            if b.tipo == TIPO_CONTRACCION:
                nivel_previo = amplitud
            elif b.tipo != TIPO_REPOSO:
                nivel_previo = 0.0

        columnas = ["subject_id", "repetition_id", "timestamp_ms",
                    "v1", "v2", "v3", "v4", "v5", "ax", "ay", "az",
                    "gx", "gy", "gz", "label", "bloque_tipo",
                    "condicion_postural", "en_margen", "es_calibracion",
                    "id_participante", "posicion_brazo", "ts_pc_ms",
                    "descartada"]
        ruta = os.path.join(directorio, f"s{sujeto:02d}_sintetica.csv")
        pd.DataFrame(filas, columns=columnas).to_csv(ruta, index=False)
        rutas.append(ruta)

    print(f"[DATOS] {len(rutas)} sesiones sinteticas en {directorio}")
    return os.path.join(directorio, "*.csv")
