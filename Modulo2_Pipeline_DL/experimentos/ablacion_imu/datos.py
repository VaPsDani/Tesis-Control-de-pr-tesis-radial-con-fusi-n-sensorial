"""
datos.py - Carga, ventaneo y normalizacion del experimento de ablacion
=======================================================================
Protesis transradial - Ablacion de la IMU

Lee los CSV de sesion que escribe la app de captura y los convierte en
ventanas con TODOS sus metadatos, que es lo que distingue a este modulo
del preprocesador de produccion: alli basta con X e y, aqui hace falta
saber de que sujeto, de que repeticion y de que condicion postural viene
cada ventana, porque son los ejes del diseno factorial.

LO QUE NO SE HACE AQUI:
  Elegir canales. Eso ocurre despues, con seleccionar_canales(), para
  que las cuatro celdas del 2x2 partan EXACTAMENTE de las mismas
  ventanas y solo se diferencien en las columnas y en las repeticiones
  que se evaluan.
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

import glob
import os
from dataclasses import dataclass, field
from typing import List

import numpy as np
import pandas as pd

from preprocesamiento import COLUMNAS_MODELO, CONDICIONES_POSTURALES

# Niveles del factor B, tal como se escriben en el CSV.
CONDICION_ESTATICA, CONDICION_DINAMICA = CONDICIONES_POSTURALES

# Columnas opticas y de acelerometro dentro de COLUMNAS_MODELO.
CANALES_LMG = ["v1", "v2", "v3", "v4", "v5"]
CANALES_IMU = ["ax", "ay", "az"]

# Niveles del factor A: que alimenta al modelo.
COMPOSICIONES = {
    "solo_lmg": CANALES_LMG,
    "lmg_imu": CANALES_LMG + CANALES_IMU,
}

NOMBRES_GESTOS = ["Rest", "Pinch", "Tripod", "Power", "Finger_Ext"]
NUM_CLASES = len(NOMBRES_GESTOS)
LABEL_REST = 0

PERIODO_MS = 10
# Ventanas de calibracion minimas por sujeto para fiarse de su media y
# su desviacion. Con 15 s de calibracion y stride de 20 ms salen ~700.
MIN_VENTANAS_CALIBRACION = 30


@dataclass
class Ventanas:
    """Ventanas con todo lo que el diseno factorial necesita saber."""
    X: np.ndarray                  # (N, pasos, 8) con los 8 canales
    y: np.ndarray                  # (N,) entero
    sujeto: np.ndarray             # (N,)
    repeticion: np.ndarray         # (N,)
    condicion: np.ndarray          # (N,) estatica, dinamica o vacia
    es_calibracion: np.ndarray     # (N,) 0 o 1
    canales: List[str] = field(default_factory=lambda: list(COLUMNAS_MODELO))

    def __len__(self):
        return len(self.y)

    def subconjunto(self, mascara):
        return Ventanas(self.X[mascara], self.y[mascara],
                        self.sujeto[mascara], self.repeticion[mascara],
                        self.condicion[mascara], self.es_calibracion[mascara],
                        list(self.canales))


def cargar_sesiones(patron: str) -> pd.DataFrame:
    """
    Concatena los CSV de sesion que casen con el patron.

    Comprueba que traigan la columna condicion_postural: un CSV anterior
    al cambio de protocolo no sirve para este experimento y es mejor
    decirlo aqui que dejar que el 2x2 salga con una celda vacia.
    """
    rutas = sorted(glob.glob(patron))
    if not rutas:
        raise FileNotFoundError(f"Ningun CSV casa con {patron}")

    marcos = []
    for ruta in rutas:
        df = pd.read_csv(ruta)
        faltan = [c for c in ("subject_id", "repetition_id", "label",
                              "bloque_tipo", "condicion_postural",
                              "es_calibracion", "timestamp_ms")
                  if c not in df.columns]
        if faltan:
            raise ValueError(f"{os.path.basename(ruta)} no tiene {faltan}. "
                             f"Es de una version anterior del protocolo.")
        if "descartada" in df.columns:
            n = int((df["descartada"] == 1).sum())
            if n:
                print(f"[DATOS] {os.path.basename(ruta)}: {n} filas "
                      f"descartadas por el operador, fuera.")
            df = df[df["descartada"] != 1]
        marcos.append(df)
        print(f"[DATOS] {os.path.basename(ruta)}: {len(df)} filas, "
              f"sujeto {sorted(df['subject_id'].unique().tolist())}")

    return pd.concat(marcos, ignore_index=True)


def ventanear(df: pd.DataFrame, ventana_ms: int = 200,
              stride_ms: int = 20) -> Ventanas:
    """
    Ventana deslizante que NUNCA cruza de un bloque a otro.

    Un segmento cambia cuando cambia cualquiera de las claves de bloque o
    cuando el timestamp da un salto mayor a tres periodos. Sin esto
    apareceria la mezcla de final de contraccion con principio de reposo
    que en NinaPro DB5 afectaba al 9.26% de las ventanas de Rest.
    """
    w = int(ventana_ms / PERIODO_MS)
    s = max(1, int(stride_ms / PERIODO_MS))

    claves = ["subject_id", "repetition_id", "label", "bloque_tipo",
              "condicion_postural"]
    cambio = np.zeros(len(df), dtype=bool)
    for c in claves:
        # fillna ANTES de comparar: la condicion postural viene vacia en
        # la calibracion y pandas la lee como NaN, que nunca es igual a
        # si mismo. Sin esto cada fila de calibracion seria su propio
        # segmento, ninguna llegaria a los 20 pasos de la ventana y el
        # bloque entero desapareceria en silencio.
        col = df[c].fillna("")
        cambio |= col.ne(col.shift()).values
    dt = df["timestamp_ms"].diff().values
    cambio |= np.nan_to_num(dt, nan=0.0) > 3 * PERIODO_MS
    segmento = np.cumsum(cambio)

    datos = df[COLUMNAS_MODELO].values.astype(np.float32)
    etiquetas = df["label"].values.astype(np.int64)
    sujetos = df["subject_id"].values
    repeticiones = df["repetition_id"].values
    condiciones = df["condicion_postural"].fillna("").values
    calibracion = df["es_calibracion"].values

    X, y, suj, rep, cond, cal = [], [], [], [], [], []
    for seg in np.unique(segmento):
        idx = np.where(segmento == seg)[0]
        if len(idx) < w:
            continue
        a = idx[0]
        for off in range(0, len(idx) - w + 1, s):
            i0, i1 = a + off, a + off + w
            X.append(datos[i0:i1])
            # La etiqueta es constante dentro del segmento por
            # construccion; el voto mayoritario es una salvaguarda.
            y.append(np.bincount(etiquetas[i0:i1]).argmax())
            suj.append(sujetos[i1 - 1])
            rep.append(repeticiones[i1 - 1])
            cond.append(condiciones[i1 - 1])
            cal.append(calibracion[i1 - 1])

    if not X:
        raise ValueError(f"Ningun bloque contiguo llega a {w} muestras.")

    v = Ventanas(np.asarray(X, dtype=np.float32), np.asarray(y),
                 np.asarray(suj), np.asarray(rep),
                 np.asarray(cond, dtype=object), np.asarray(cal))
    print(f"[DATOS] {len(v)} ventanas de {w} pasos, {len(np.unique(v.sujeto))} "
          f"sujetos, {int(v.es_calibracion.sum())} de calibracion")
    return v


def submuestrear_rest(v: Ventanas, semilla: int = 42,
                      ratio: float = 1.0) -> Ventanas:
    """
    Recorta Rest hasta 'ratio' veces la media de las clases activas.

    SE HACE UNA SOLA VEZ, antes de repartir las celdas: las cuatro tienen
    que partir de las mismas ventanas o la comparacion dejaria de ser
    limpia. La calibracion se conserva entera, porque no entra al
    entrenamiento y hace falta completa para normalizar.
    """
    rng = np.random.RandomState(semilla)
    activo = (v.y != LABEL_REST) & (v.es_calibracion == 0)
    rest = (v.y == LABEL_REST) & (v.es_calibracion == 0)
    por_clase = [int((v.y == c).sum()) for c in range(1, NUM_CLASES)]
    objetivo = int(ratio * np.mean(por_clase)) if por_clase else int(rest.sum())

    idx_rest = np.where(rest)[0]
    if len(idx_rest) > objetivo:
        elegidos = rng.choice(idx_rest, size=objetivo, replace=False)
    else:
        elegidos = idx_rest

    mascara = np.zeros(len(v), dtype=bool)
    mascara[np.where(activo)[0]] = True
    mascara[np.where(v.es_calibracion == 1)[0]] = True
    mascara[elegidos] = True
    print(f"[DATOS] Submuestreo de Rest: {int(rest.sum())} -> "
          f"{len(elegidos)} ventanas (objetivo {objetivo})")
    return v.subconjunto(mascara)


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


def estadisticas_de_calibracion(v: Ventanas) -> dict:
    """
    Media y desviacion por canal de CADA sujeto, tomadas de su bloque de
    calibracion.

    POR QUE LA CALIBRACION Y NO TODO EL TRAIN:
      Es lo que el firmware puede hacer en el brazo de una persona: pedir
      15 s de reposo antes de empezar. Normalizar con todo el train
      supondria conocer de antemano los gestos del sujeto, que en uso
      real no se tienen.

      Ademas, el bloque de calibracion no entra al entrenamiento ni a la
      evaluacion, asi que usarlo para normalizar no filtra nada del test.
    """
    stats = {}
    for s in np.unique(v.sujeto):
        m = (v.sujeto == s) & (v.es_calibracion == 1)
        if int(m.sum()) < MIN_VENTANAS_CALIBRACION:
            raise ValueError(
                f"El sujeto {s} solo aporta {int(m.sum())} ventanas de "
                f"calibracion, por debajo del minimo de "
                f"{MIN_VENTANAS_CALIBRACION}. Sus estadisticas serian ruido.")
        datos = v.X[m]
        mu = datos.mean(axis=(0, 1))
        sd = datos.std(axis=(0, 1))
        stats[int(s)] = (mu, np.where(sd < 1e-6, 1.0, sd))
    return stats


def normalizar_por_calibracion(X: np.ndarray, sujetos: np.ndarray,
                               stats: dict, canales: List[int]) -> np.ndarray:
    """Aplica a cada ventana la media y la desviacion de SU sujeto."""
    Xn = np.empty_like(X)
    for s in np.unique(sujetos):
        m = sujetos == s
        mu, sd = stats[int(s)]
        Xn[m] = (X[m] - mu[canales]) / sd[canales]
    return Xn


def indices_de_canales(composicion: str) -> List[int]:
    return [COLUMNAS_MODELO.index(c) for c in COMPOSICIONES[composicion]]


# ============================================================
# SESIONES SINTETICAS, PARA PROBAR SIN PILOTO
# ============================================================
def generar_sesiones_sinteticas(directorio: str, n_sujetos: int = 10,
                                semilla: int = 42) -> str:
    """
    Escribe CSV con la estructura exacta del protocolo, sin hardware.

    NO sustituyen al piloto ni producen resultados publicables: sirven
    para comprobar que el experimento corre de principio a fin, que las
    cuatro celdas quedan equilibradas y que la estadistica no se rompe.

    La senal es deliberadamente sencilla: cada gesto desplaza la media de
    los canales opticos, y la condicion dinamica anade al acelerometro
    una rampa por posicion. Asi la celda lmg_imu tiene, por construccion,
    informacion que solo_lmg no tiene en la condicion dinamica.
    """
    from protocolo import (TIPO_CALIBRACION, TIPO_CONTRACCION,
                           construir_sesion)

    os.makedirs(directorio, exist_ok=True)
    rng = np.random.RandomState(semilla)
    rutas = []

    for sujeto in range(1, n_sujetos + 1):
        bloques = construir_sesion(sujeto)
        filas = []
        t = 0
        escala = 1.0 + 0.3 * rng.rand()          # cada sujeto, su ganancia
        offset = 10.0 * rng.rand()
        for b in bloques:
            n = int(b.duracion_ms / PERIODO_MS)
            for i in range(n):
                t_rel = i * PERIODO_MS
                base = rng.randn(5) * 0.4 + offset
                if b.tipo == TIPO_CONTRACCION:
                    base += escala * (1.0 + b.label) * 0.8
                acc = rng.randn(3) * 0.05
                pos = b.posicion_en(b.t_inicio_ms + t_rel)
                if pos:
                    k = list(b.orden_posiciones).index(pos)
                    acc += np.array([0.9 * k, -0.4 * k, 0.5 * k])
                filas.append([
                    sujeto, b.repetition_id, t,
                    *np.round(base, 4), *np.round(acc, 4),
                    *np.round(rng.randn(3) * 0.02, 4),
                    b.label, b.tipo, b.condicion_postural,
                    b.en_margen(b.t_inicio_ms + t_rel), b.es_calibracion,
                    f"S{sujeto:02d}", pos, 0, 0,
                ])
                t += PERIODO_MS

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
