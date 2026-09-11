"""
datos.py - Carga y preparacion de lmg_wavelength_dataset
=========================================================
Experimento: validacion del pipeline sobre LMG real (Tarea 1)

DATASET:
  https://github.com/newdexterity/lmg_wavelength_dataset
  Se descarga bajo <repo>/data/, que esta en .gitignore. El dataset no
  declara licencia; no se redistribuye.

  LMGData/subj{n}_{config}{rep}_lmg.csv
    columnas 0..39  voltaje de 40 canales LMG
    columna  40     etiqueta 0..5 (rest, pinch, tripod, full, key, extension)
  10 sujetos x 4 configuraciones x 5 repeticiones = 200 archivos.

HECHOS VERIFICADOS SOBRE LOS DATOS (no tomados del paper):

  Frecuencia de muestreo: 83.2 Hz. El README del dataset no la declara.
    Se midio desde la alternancia del LED: en 125both el ciclo es de
    250 ms y en 250both de 500 ms, y el periodo dominante en muestras
    da 83.02 y 83.43 Hz respectivamente, de forma independiente. El
    control 'green', sin alternancia, no muestra ese pico.

  Estructura: cada archivo es UNA pasada por los 5 gestos,
    [rest, pinch, rest, tripod, rest, full, rest, key, rest, extension,
    rest], con bloques de 834 muestras (10.0 s) exactos. Tanta exactitud
    indica que la etiqueta sigue a la SENAL VISUAL, no al movimiento.

  ORDEN FIJO en los 200 archivos: pinch -> tripod -> full -> key ->
    extension. Es una limitacion a declarar: cada gesto hereda siempre
    el estado que deja el anterior (hiperemia, fatiga) y ocupa siempre
    la misma posicion temporal en la sesion. Con particion por sujeto
    no hay fuga, pero las clases pueden volverse separables en parte
    por deriva temporal y no solo por el gesto.

  ANTICIPACION: la senal empieza a moverse ~250 ms ANTES del cambio de
    etiqueta, y el 72% de las transiciones ya supera el 10% de su
    excursion en los 500 ms previos. Con orden fijo y bloques de 10 s el
    participante sabe que gesto viene y cuando. Nuestro protocolo lo
    evita contrabalanceando el orden y mostrando el gesto solo al
    empezar el bloque.

  El orden de las 4 configuraciones de luz SI esta contrabalanceado
    entre sujetos (SubjectInfo.xlsx), asi que la configuracion no esta
    confundida con la fatiga en el analisis de longitud de onda.

  No documenta la ubicacion anatomica de los 40 canales.

CONFIGURACIONES CON ALTERNANCIA (125both, 250both):
  El LED alterna verde e IR cada 125 o 250 ms. Esa modulacion a 2-4 Hz
  cae dentro de la banda del gesto y, sin tratar, su varianza es 5.6x y
  9.3x la excursion del propio gesto: tapa la senal. Se aplica una media
  movil CENTRADA de exactamente un ciclo de alternancia, cuyos ceros caen
  en k*fs/N, o sea sobre la fundamental y todos sus armonicos. Eso
  devuelve la relacion ruido/excursion a 0.23 y 0.18, comparable a ir
  (0.14) y green (0.09). Al ser centrada no introduce retardo.
"""

import glob
import os
import re
import sys
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from scipy.ndimage import uniform_filter1d
from scipy.signal import decimate

AQUI = os.path.dirname(os.path.abspath(__file__))
MODULO2 = os.path.abspath(os.path.join(AQUI, "..", ".."))
RAIZ_REPO = os.path.abspath(os.path.join(MODULO2, ".."))
if MODULO2 not in sys.path:
    sys.path.insert(0, MODULO2)

from fases import (ParametrosFases, etiquetar_fases, mascara_entrenamiento,  # noqa: E402
                   FASE_REPOSO, firma)

RUTA_DATASET_DEFECTO = os.path.join(RAIZ_REPO, "data", "lmg_wavelength_dataset")

FS_NATIVA = 83.2          # Hz, medida desde la alternancia (ver arriba)

CONFIGS = ["green", "ir", "250both", "125both"]
CICLO_ALTERNANCIA_S = {"125both": 0.250, "250both": 0.500}

# ============================================================
# MAPEO DE CLASES: dataset -> tesis
# ============================================================
# Etiquetas del dataset: 0 rest, 1 pinch, 2 tripod, 3 full, 4 key, 5 extension
#
# 'full' es el agarre de mano completa: es nuestro Power.
#
# 'key' (agarre de llave, pulgar contra el lateral del indice) se
# DESCARTA. No esta en nuestro repertorio y la protesis no lo ejecuta:
# conservarlo como sexta clase mediria la capacidad de separar un gesto
# que el sistema nunca va a necesitar, y fundirlo con otra clase (Pinch,
# con el que comparte el cierre del pulgar) contaminaria esa clase.
#
# Las filas de 'key' se eliminan DESPUES de detectar las fases, porque el
# reposo que sigue a key necesita su deteccion de relajacion.
MAPEO_CLASES: Dict[int, Optional[int]] = {
    0: 0,      # rest      -> Rest
    1: 1,      # pinch     -> Pinch
    2: 2,      # tripod    -> Tripod
    3: 3,      # full      -> Power
    4: None,   # key       -> DESCARTADO (no esta en el repertorio)
    5: 4,      # extension -> Extension
}
NOMBRES = ["Rest", "Pinch", "Tripod", "Power", "Extension"]
NUM_CLASES = len(NOMBRES)

_PATRON = re.compile(r"subj(\d+)_(green|ir|250both|125both)(\d+)_lmg\.csv$")


def listar_archivos(raiz: str = RUTA_DATASET_DEFECTO,
                    config: Optional[str] = None) -> pd.DataFrame:
    """Inventario de LMGData: una fila por archivo."""
    filas = []
    for ruta in sorted(glob.glob(os.path.join(raiz, "LMGData", "**", "*.csv"),
                                 recursive=True)):
        m = _PATRON.search(os.path.basename(ruta))
        if m and (config is None or m.group(2) == config):
            filas.append((int(m.group(1)), m.group(2), int(m.group(3)), ruta))
    if not filas:
        raise FileNotFoundError(
            f"No hay CSV de LMGData en {raiz}. Descargue el dataset con:\n"
            f"  git clone --depth 1 https://github.com/newdexterity/"
            f"lmg_wavelength_dataset.git data/lmg_wavelength_dataset")
    return pd.DataFrame(filas, columns=["subj", "config", "rep", "ruta"])


def mapear(y_orig: np.ndarray) -> np.ndarray:
    """Etiqueta del dataset -> clase de la tesis. -1 para las descartadas."""
    lut = np.full(max(MAPEO_CLASES) + 1, -1, dtype=np.int64)
    for k, v in MAPEO_CLASES.items():
        if v is not None:
            lut[k] = v
    return lut[y_orig]


def cargar_sesion(ruta: str, config: str, fs: float = FS_NATIVA,
                  p: Optional[ParametrosFases] = None) -> dict:
    """
    Carga un archivo, filtra la alternancia si la hay y etiqueta fases.

    Las fases se detectan sobre las etiquetas ORIGINALES (con key), para
    que el reposo posterior a key tenga su deteccion de relajacion; el
    mapeo a las clases de la tesis se aplica despues.
    """
    d = pd.read_csv(ruta).values
    x = d[:, :40].astype(np.float64)
    y_orig = d[:, 40].astype(np.int64)

    if config in CICLO_ALTERNANCIA_S:
        n = int(round(CICLO_ALTERNANCIA_S[config] * fs))
        x = uniform_filter1d(x, size=n, axis=0, mode="nearest")

    fase, informe = etiquetar_fases(x, y_orig, fs, p or ParametrosFases())
    return dict(x=x, y_orig=y_orig, y=mapear(y_orig), fase=fase,
                informe=informe)


def decimar_sesion(s: dict, factor: int = 2) -> dict:
    """
    Submuestreo con filtro anti-alias (decimate, fase cero), NO [::2].

    Tomar una de cada dos muestras sin filtrar pliega el contenido entre
    fs/4 y fs/2 sobre la banda baja. Etiquetas y fases, que son
    constantes a tramos de cientos de muestras, si se toman cada 2.
    """
    return dict(
        x=decimate(s["x"], factor, axis=0, zero_phase=True),
        y_orig=s["y_orig"][::factor], y=s["y"][::factor],
        fase=s["fase"][::factor], informe=s["informe"],
    )


def normalizar_por_sujeto(sesiones: List[dict], sujetos: List[int]) -> None:
    """
    z-score por canal con la media y desviacion del REPOSO ESTABLE de
    cada sujeto, sobre todas sus sesiones. In situ.

    Es la misma normalizacion que usa el firmware (calibracion en reposo,
    CALIB_SOLO_REPOSO), elegida porque sobre NinaPro DB5 dio la media
    equivalente a la normalizacion completa con la mitad de desviacion
    entre sujetos (69.11% +/- 3.92% frente a 70.00% +/- 7.86%).
    """
    for s_id in sorted(set(sujetos)):
        idx = [i for i, s in enumerate(sujetos) if s == s_id]
        reposo = np.concatenate([
            sesiones[i]["x"][sesiones[i]["fase"] == FASE_REPOSO] for i in idx])
        mu = reposo.mean(axis=0)
        sd = np.where(reposo.std(axis=0) < 1e-9, 1e-9, reposo.std(axis=0))
        for i in idx:
            sesiones[i]["x"] = (sesiones[i]["x"] - mu) / sd


def parametros_ventana(ventana_ms: float, solapamiento: float, fs: float):
    """
    Traduce (ventana en ms, solapamiento) a muestras y devuelve los valores
    EFECTIVOS tras redondear, que es lo que realmente se evalua.

    A 41.6 Hz, 100 ms son 4 muestras: pedir 90% de solapamiento da un
    stride de 0.4 muestras, que redondea a 1, o sea 75% efectivo. Varias
    celdas de la rejilla colapsan en la misma configuracion real, y hay
    que reportarlo en vez de fingir que se evaluo el valor nominal.
    """
    w = max(2, int(round(ventana_ms * fs / 1000.0)))
    stride = max(1, int(round(w * (1.0 - solapamiento))))
    return dict(
        w=w, stride=stride,
        ventana_ms_efectiva=1000.0 * w / fs,
        stride_ms_efectivo=1000.0 * stride / fs,
        solapamiento_efectivo=1.0 - stride / w,
    )


def ventanear(sesiones: List[dict], sujetos: List[int], w: int, stride: int,
              variante: str = "dinamica_meseta", con_crudo: bool = False):
    """
    Ventanas que NUNCA cruzan un limite de segmento.

    Un segmento es un tramo contiguo de filas incluidas con la misma
    clase. Tras filtrar fases las filas dejan de ser contiguas, y deslizar
    la ventana a traves del hueco mezclaria dos regimenes: es el mismo
    defecto que se cuantifico en la linea base EMG (6.27% de ventanas).

    Returns:
        F: (N, 2C) media y desviacion por canal (modelos clasicos)
        X: (N, w, C) ventana cruda (CNN), solo si con_crudo
        y: (N,) clase, subj: (N,) sujeto
    """
    Fs, Xs, ys, ss = [], [], [], []
    for s, sid in zip(sesiones, sujetos):
        valido = (s["y"] >= 0) & mascara_entrenamiento(s["fase"], s["y"],
                                                       variante)
        # limites de segmento: cambia la validez o la clase
        clave = np.where(valido, s["y"], -1)
        cortes = np.flatnonzero(np.diff(clave) != 0) + 1
        for a, z in zip(np.r_[0, cortes], np.r_[cortes, len(clave)]):
            if clave[a] < 0 or z - a < w:
                continue
            seg = s["x"][a:z]
            vista = np.lib.stride_tricks.sliding_window_view(
                seg, w, axis=0)[::stride]          # (n, C, w)
            Fs.append(np.concatenate([vista.mean(-1), vista.std(-1)], axis=1))
            if con_crudo:
                Xs.append(np.transpose(vista, (0, 2, 1)).astype(np.float32))
            ys.append(np.full(len(vista), clave[a], dtype=np.int64))
            ss.append(np.full(len(vista), sid, dtype=np.int64))

    F = np.concatenate(Fs).astype(np.float32)
    y = np.concatenate(ys)
    subj = np.concatenate(ss)
    X = np.concatenate(Xs) if con_crudo else None
    return F, X, y, subj


def submuestrear_rest(y: np.ndarray, *arrays, random_state: int = 42):
    """
    Reduce Rest a la media de las clases activas, igual que el pipeline
    EMG, para que las dos ramas se traten con la misma regla. Todos los
    arrays se indexan con el mismo vector, que es lo que preserva la
    correspondencia ventana <-> sujeto.
    """
    rng = np.random.RandomState(random_state)
    idx0 = np.flatnonzero(y == 0)
    activas = [int((y == c).sum()) for c in range(1, NUM_CLASES)]
    objetivo = int(np.mean(activas))
    if len(idx0) <= objetivo:
        return (y,) + arrays
    sel = np.concatenate([rng.choice(idx0, objetivo, replace=False),
                          np.flatnonzero(y != 0)])
    rng.shuffle(sel)
    return (y[sel],) + tuple(None if a is None else a[sel] for a in arrays)


def preparar_config(config: str, fs_objetivo: float = FS_NATIVA,
                    raiz: str = RUTA_DATASET_DEFECTO,
                    p: Optional[ParametrosFases] = None,
                    cache_dir: Optional[str] = None):
    """
    Carga, etiqueta fases, (decima) y normaliza todas las sesiones de una
    configuracion. Es lo caro y no depende de ventana ni solapamiento,
    asi que se hace una vez por (config, fs) y se cachea.
    """
    factor = int(round(FS_NATIVA / fs_objetivo))
    p = p or ParametrosFases()
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
        # La clave incluye la version del detector y sus parametros: una
        # cache calculada con otra version de fases.py devolveria fases
        # equivocadas en silencio, que es justo lo que ocurrio al
        # corregir la linea base local.
        ruta_cache = os.path.join(cache_dir,
                                  f"{config}_fs{factor}_{firma(p)}.npz")
        if os.path.exists(ruta_cache):
            d = np.load(ruta_cache, allow_pickle=True)
            return list(d["sesiones"]), list(d["sujetos"]), list(d["informes"])

    inv = listar_archivos(raiz, config)
    sesiones, sujetos, informes = [], [], []
    for _, r in inv.iterrows():
        s = cargar_sesion(r.ruta, config, FS_NATIVA, p)
        informes.append(dict(subj=int(r.subj), rep=int(r.rep),
                             bloques=s["informe"]))
        if factor > 1:
            s = decimar_sesion(s, factor)
        sesiones.append(s)
        sujetos.append(int(r.subj))

    normalizar_por_sujeto(sesiones, sujetos)

    if cache_dir:
        np.savez(ruta_cache, sesiones=np.array(sesiones, dtype=object),
                 sujetos=np.array(sujetos), informes=np.array(informes,
                                                             dtype=object))
    return sesiones, sujetos, informes
