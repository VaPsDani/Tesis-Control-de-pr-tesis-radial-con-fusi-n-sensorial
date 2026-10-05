"""
preprocesamiento.py - Construccion de ventanas deslizantes
=========================================================
Protesis transradial - Fusion sensorial y Deep Learning

LOGICA DE LA VENTANA DESLIZANTE:
  El sensor se muestrea a 100 Hz (cada 10 ms).
  Para capturar la dinamica temporal de un gesto, se agrupan
  muestras consecutivas en ventanas de 200 ms.

  Parametros:
    - window_size_ms = 200 ms  → 20 muestras por ventana (a 100 Hz)
    - stride_ms      = 20 ms   → avance de 2 muestras entre ventanas

  Ejemplo visual (cada letra = 1 muestra de 10 ms):
    Muestras:  a b c d e f g h i j k l m n o p q r s t u v w x ...
    Ventana 1: [a b c d e f g h i j k l m n o p q r s t]  → 20 muestras
    Ventana 2: [  c d e f g h i j k l m n o p q r s t u v]  → stride 2

  Esto produce solapamiento del 90% entre ventanas adyacentes,
  maximizando los datos de entrenamiento.

ETIQUETADO:
  Se asume que el dataset CSV incluye una columna 'label' con
  identificadores enteros de las 5 clases:
    0 = Rest
    1 = Pinch
    2 = Tripod
    3 = Power
    4 = Finger_Extension

ESQUEMA DEL CSV DE CAPTURA:
  subject_id, repetition_id, timestamp_ms, v1..v5,
  ax, ay, az, gx, gy, gz, label, bloque_tipo, condicion_postural,
  en_margen, es_calibracion, fase

  condicion_postural es estatica o dinamica, POR REPETICION: de las 6
  repeticiones de cada gesto, 3 se hacen con el brazo quieto y 3
  moviendolo. Es el factor B del experimento de ablacion de la IMU y
  NUNCA entra al vector del modelo, solo selecciona filas.

  La captura anade ademas id_participante, posicion_brazo, ts_pc_ms y
  descartada, que tampoco alimentan al modelo.

  fase la anade anotar_fases.py al cerrar la sesion (reaccion, dinamica,
  meseta, relajacion, reposo, recorte). Por defecto se entrena con
  dinamica + meseta como clase del gesto y el reposo estable como Rest;
  en_margen se sigue grabando, pero ya no decide que filas entran.

  De esas, SOLO 8 entran al modelo: v1..v5 + ax, ay, az.

  EL FILTRADO DE CANALES OCURRE AQUI, NO EN EL FIRMWARE.
  El giroscopio (gx, gy, gz) se graba porque sus bytes ya viajan en la
  misma lectura I2C de 14 bytes del MPU6050, asi que almacenarlo no
  cuesta tiempo de bus; recuperarlo despues obligaria a repetir la
  campana con los 10 voluntarios. Que el modelo no lo use hoy no
  significa que no vaya a usarse manana.

  El cuarto canal de IMU de la version anterior (qw, la magnitud
  saturada del acelerometro) se elimino: era una funcion determinista de
  ax, ay, az. Con 8 canales el vector tiene la misma forma con la que se
  valido el pipeline sobre NinaPro DB5 (5 sEMG + 3 ACC), asi que el mismo
  codigo sirve para las dos entradas.

ESTRUCTURA DE SALIDA:
  X: (num_ventanas, window_size, num_features)  → (N, 20, 8)
  y: (num_ventanas,)  → one-hot encoding (N, 5)
"""

import json
import os
from dataclasses import dataclass, field
from typing import List, Tuple

import numpy as np
import pandas as pd

# ============================================================
# ESQUEMA DEL CSV
# ============================================================
# Los 8 canales que consume el modelo, EN ESTE ORDEN. Debe coincidir
# exactamente con el empaquetado de muestra[] en el Modulo 3; si los dos
# se desincronizan no hay error, el modelo recibe canales permutados.
COLUMNAS_MODELO = ["v1", "v2", "v3", "v4", "v5", "ax", "ay", "az"]

# Se graban pero NO entran al modelo.
COLUMNAS_NO_MODELO = ["gx", "gy", "gz"]

# Columnas de protocolo que anade el script de captura.
COLUMNAS_METADATOS = [
    "subject_id", "repetition_id", "timestamp_ms",
    "label", "bloque_tipo", "condicion_postural", "en_margen",
    "es_calibracion",
]

# Valores validos de condicion_postural. Vacio en la calibracion, que no
# pertenece a ninguna de las dos condiciones.
CONDICIONES_POSTURALES = ("estatica", "dinamica")

NUM_CANALES_MODELO = len(COLUMNAS_MODELO)   # 8


# ============================================================
# NUCLEO COMPARTIDO: CARGA, NORMALIZACION Y VENTANEO
# ============================================================
# La ablacion de la IMU, el entrenamiento de produccion y la conversion
# INT8 pasan por estas funciones y por ninguna otra. Si dos caminos
# preprocesaran distinto, el modelo que se evalua en el articulo no seria
# el que se despliega en el ESP32.

CANALES_LMG = COLUMNAS_MODELO[:5]       # v1..v5
CANALES_ACC = COLUMNAS_MODELO[5:]       # ax, ay, az
# Configuraciones del articulo (A16): A con los 5 canales LMG, B con los
# 5 LMG y los 3 del acelerometro. Mismas ventanas, mismas etiquetas.
COMPOSICIONES = {
    "solo_lmg": CANALES_LMG,
    "lmg_imu": CANALES_LMG + CANALES_ACC,
}
NOMBRES_CLASES = ["Rest", "Pinch", "Tripod", "Power", "Finger_Ext"]
PERIODO_MS = 10
VENTANA_MUESTRAS = 20                   # 200 ms a 100 Hz
PASO_MUESTRAS = 2                       # 20 ms
# El mismo epsilon que CALIB_EPSILON en el firmware del Modulo 3.
EPS_CALIBRACION = 1e-8
# El firmware rechaza una calibracion con menos de 30 ventanas de 20.
MIN_MUESTRAS_CALIBRACION = 30 * VENTANA_MUESTRAS
# Un segmento cambia cuando cambia cualquiera de estas columnas.
CLAVES_SEGMENTO = ("subject_id", "repetition_id", "label", "bloque_tipo",
                   "condicion_postural")


def cargar_sesion(ruta: str) -> pd.DataFrame:
    """
    Lee el CSV de una sesion con la columna fase VIGENTE.

    La fase se recalcula si falta, si no hay JSON lateral que diga con
    que version del detector se calculo, o si la version es otra. Se
    calcula sobre la sesion ENTERA, antes de filtrar nada, porque la base
    de cada gesto y la relajacion necesitan la senal continua.
    """
    from fases import FASES_VERSION
    df = pd.read_csv(ruta)
    vigente = False
    ruta_json = os.path.splitext(ruta)[0] + "_fases.json"
    if "fase" in df.columns and os.path.exists(ruta_json):
        with open(ruta_json, encoding="utf-8") as f:
            vigente = json.load(f).get("fases_version") == FASES_VERSION
    if not vigente:
        from anotar_fases import anotar_df
        base = df.drop(columns="fase") if "fase" in df.columns else df
        fase, _, _ = anotar_df(base)
        df = base.assign(fase=fase)
        print(f"[PREPROC] {os.path.basename(ruta)}: columna fase ausente u "
              f"obsoleta, calculada al vuelo (version {FASES_VERSION}).")
    return df


def estadisticas_calibracion(df: pd.DataFrame):
    """
    Media y desviacion por canal del bloque de calibracion de 15 s.

    REPLICA EXACTAMENTE AL FIRMWARE (Modulo3, calibracion.cpp):
      - las muestras fuera de los margenes del bloque, 1000 ms al entrar y
        500 ms al salir, que es lo que marca en_margen,
      - solo bloques completos de 20 muestras, porque el firmware pliega
        las muestras a los acumuladores ventana a ventana y descarta la
        incompleta del final,
      - desviacion poblacional, var = E[x^2] - E[x]^2.

    El bloque de calibracion solo aporta estas estadisticas: nunca entra
    al entrenamiento ni a la evaluacion (A10).
    """
    m = df["es_calibracion"].to_numpy() == 1
    if "en_margen" in df.columns:
        m &= df["en_margen"].to_numpy() == 0
    x = df.loc[m, COLUMNAS_MODELO].to_numpy(np.float64)
    n = (len(x) // VENTANA_MUESTRAS) * VENTANA_MUESTRAS
    if n < MIN_MUESTRAS_CALIBRACION:
        raise ValueError(
            f"Solo hay {n} muestras utiles de calibracion, por debajo de las "
            f"{MIN_MUESTRAS_CALIBRACION} que exige el firmware. La sesion no "
            f"se puede normalizar.")
    x = x[:n]
    return x.mean(axis=0).astype(np.float32), x.std(axis=0).astype(np.float32)


def normalizar(X: np.ndarray, mu: np.ndarray, sd: np.ndarray) -> np.ndarray:
    """
    La normalizacion del articulo, igual que en el firmware.

      LMG (A8)            z por canal: (x - media) / desviacion, ambas de
                          la calibracion.
      Acelerometro (A9)   (x - media de la calibracion), en g. NO se
                          divide: el firmware ya entrega el acelerometro en
                          g (16384 LSB/g en +/-2 g), y dividir entre la
                          desviacion de un brazo quieto, que es casi solo
                          ruido, inflaria la escala sin sentido fisico.

    X: (..., 8) en el orden de COLUMNAS_MODELO.
    """
    Xn = np.asarray(X, dtype=np.float32) - mu
    k = len(CANALES_LMG)
    Xn[..., :k] = Xn[..., :k] / (sd[:k] + EPS_CALIBRACION)
    return Xn.astype(np.float32)


def filas_de_entrenamiento(df: pd.DataFrame,
                           variante_fases: str = "dinamica_meseta") -> np.ndarray:
    """
    Filas que pueden dar ventanas: las de la variante de fases (por
    defecto dinamica y meseta como gesto, y el reposo estable como Rest),
    fuera de la calibracion y fuera de las repeticiones descartadas. La
    preparacion queda fuera por su propia fase.
    """
    from fases import mascara_entrenamiento
    m = mascara_entrenamiento(df["fase"].astype(str).to_numpy(),
                              df["label"].to_numpy(), variante_fases)
    m &= df["es_calibracion"].to_numpy() == 0
    if "descartada" in df.columns:
        m &= df["descartada"].fillna(0).to_numpy() != 1
    return m


def segmentos(df: pd.DataFrame, periodo_ms: float = PERIODO_MS) -> np.ndarray:
    """
    Identificador de tramo contiguo por fila. Ninguna ventana cruza de un
    tramo a otro: un tramo cambia cuando cambia la repeticion, la clase,
    el tipo de bloque o la condicion, o cuando el timestamp salta mas de
    3 periodos, que es una pausa o una fila filtrada.
    """
    cambio = np.zeros(len(df), dtype=bool)
    if len(df):
        cambio[0] = True
    for c in CLAVES_SEGMENTO:
        if c in df.columns:
            # fillna antes de comparar: la condicion viene vacia en la
            # calibracion y NaN nunca es igual a si mismo.
            col = df[c].fillna("")
            cambio |= col.ne(col.shift()).to_numpy()
    if "timestamp_ms" in df.columns:
        dt = df["timestamp_ms"].diff().to_numpy()
        cambio |= np.nan_to_num(dt, nan=0.0) > 3 * periodo_ms
    return np.cumsum(cambio)


@dataclass
class Ventanas:
    """Ventanas con lo que hace falta saber de cada una."""
    X: np.ndarray                  # (N, pasos, 8)
    y: np.ndarray                  # (N,) entero
    sujeto: np.ndarray             # (N,)
    repeticion: np.ndarray         # (N,)
    condicion: np.ndarray          # (N,) estatica o dinamica
    bloque_tipo: np.ndarray        # (N,) contraccion, reposo o reposo_dinamico
    canales: List[str] = field(default_factory=lambda: list(COLUMNAS_MODELO))

    def __len__(self):
        return len(self.y)

    def subconjunto(self, mascara):
        return Ventanas(self.X[mascara], self.y[mascara],
                        self.sujeto[mascara], self.repeticion[mascara],
                        self.condicion[mascara], self.bloque_tipo[mascara],
                        list(self.canales))

    @staticmethod
    def concatenar(lista):
        return Ventanas(
            np.concatenate([v.X for v in lista]),
            np.concatenate([v.y for v in lista]),
            np.concatenate([v.sujeto for v in lista]),
            np.concatenate([v.repeticion for v in lista]),
            np.concatenate([v.condicion for v in lista]),
            np.concatenate([v.bloque_tipo for v in lista]),
            list(lista[0].canales))


def ventanear(df: pd.DataFrame, ventana: int = VENTANA_MUESTRAS,
              paso: int = PASO_MUESTRAS) -> Ventanas:
    """
    Ventana deslizante sobre las filas que se le pasan, sin cruzar nunca
    de un tramo contiguo a otro. No normaliza: devuelve la senal tal cual.
    """
    seg = segmentos(df)
    datos = df[COLUMNAS_MODELO].to_numpy(np.float32)
    etiquetas = df["label"].to_numpy(np.int64)
    sujetos = df["subject_id"].to_numpy()
    reps = df["repetition_id"].to_numpy()
    cond = df["condicion_postural"].fillna("").astype(str).to_numpy()
    tipos = df["bloque_tipo"].astype(str).to_numpy()

    idx = []
    if len(seg):
        cortes = np.flatnonzero(np.diff(seg)) + 1
        for a, z in zip(np.r_[0, cortes], np.r_[cortes, len(seg)]):
            idx.extend(range(a, z - ventana + 1, paso))
    idx = np.asarray(idx, dtype=np.int64)
    if not len(idx):
        vacio = np.zeros(0)
        return Ventanas(np.zeros((0, ventana, len(COLUMNAS_MODELO)), np.float32),
                        vacio.astype(np.int64), vacio, vacio,
                        vacio.astype(object), vacio.astype(object))
    fin = idx + ventana - 1
    X = np.stack([datos[i:i + ventana] for i in idx])
    # La etiqueta es constante dentro del tramo por construccion.
    return Ventanas(X, etiquetas[idx], sujetos[fin], reps[fin],
                    cond[fin].astype(object), tipos[fin].astype(object))


def preparar_sesion(ruta: str, variante_fases: str = "dinamica_meseta",
                    ventana: int = VENTANA_MUESTRAS,
                    paso: int = PASO_MUESTRAS) -> Ventanas:
    """
    Una sesion de principio a fin: fases, filas de entrenamiento,
    ventanas y normalizacion con SU calibracion. Es la unica puerta de
    entrada de los datos propios al modelo.
    """
    df = cargar_sesion(ruta)
    mu, sd = estadisticas_calibracion(df)
    util = df[filas_de_entrenamiento(df, variante_fases)].reset_index(drop=True)
    v = ventanear(util, ventana, paso)
    v.X = normalizar(v.X, mu, sd)
    return v


def preparar_sesiones(rutas, variante_fases: str = "dinamica_meseta",
                      ventana: int = VENTANA_MUESTRAS,
                      paso: int = PASO_MUESTRAS) -> Ventanas:
    """Varias sesiones, cada una normalizada con su propia calibracion."""
    import glob
    if isinstance(rutas, str):
        rutas = sorted(glob.glob(rutas))
    if not rutas:
        raise FileNotFoundError("No hay ningun CSV de sesion que cargar.")
    lista = [preparar_sesion(r, variante_fases, ventana, paso) for r in rutas]
    v = Ventanas.concatenar(lista)
    print(f"[PREPROC] {len(rutas)} sesiones, {len(v)} ventanas, "
          f"{len(np.unique(v.sujeto))} sujetos")
    return v


class SlidingWindowPreprocessor:
    """
    Construye ventanas deslizantes a partir de un CSV de series temporales.

    Args:
        window_size_ms: Tamano de la ventana en milisegundos (default: 200)
        stride_ms: Salto entre ventanas en milisegundos (default: 20)
        sampling_rate_hz: Frecuencia de muestreo del sensor (default: 100)
        feature_cols: Columnas que son features (sin incluir 'label')
    """

    def __init__(
        self,
        window_size_ms: int = 200,
        stride_ms: int = 20,
        sampling_rate_hz: int = 100,
        feature_cols: list = None,
    ):
        self.window_size_ms = window_size_ms
        self.stride_ms = stride_ms
        self.sampling_rate_hz = sampling_rate_hz

        # Convertir tiempo a numero de muestras
        # 200 ms * 100 Hz / 1000 = 20 samples
        self.window_size = int(window_size_ms * sampling_rate_hz / 1000)
        self.stride = int(stride_ms * sampling_rate_hz / 1000)

        self.feature_cols = feature_cols

    def cargar_csv(
        self,
        ruta: str,
        excluir_margenes: bool = None,
        excluir_calibracion: bool = True,
        variante_fases: str = "dinamica_meseta",
    ) -> pd.DataFrame:
        """
        Carga el CSV de captura y selecciona los canales del modelo.

        Args:
            ruta: Ruta al CSV de la sesion
            variante_fases: que filas entran, segun la columna fase
                (ver fases.VARIANTES_ABLACION). Por defecto la dinamica
                y la meseta como clase del gesto, y solo el reposo
                estable como Rest; la reaccion, la relajacion y los
                bordes del reposo quedan fuera. Si el CSV no trae la
                columna fase, o la trae de una version anterior del
                detector, se calcula al vuelo. None desactiva el
                criterio de fases y vuelve al de margen fijo.
            excluir_margenes: criterio ANTERIOR, por margen fijo
                (en_margen == 1). Por defecto solo se aplica si
                variante_fases es None: el margen fijo corta a ciegas,
                y las fases lo sustituyen.
            excluir_calibracion: descarta el bloque de calibracion
                inicial (es_calibracion == 1). Ese bloque es reposo basal
                contiguo, grabado para validar la calibracion del
                firmware, y su distribucion no es la del reposo
                post-contraccion que vera el clasificador en uso.

        Returns:
            DataFrame filtrado. self.feature_cols queda fijado a las 8
            columnas del modelo.
        """
        # Las fases se calculan sobre la sesion ENTERA, antes de filtrar,
        # con la misma funcion que usa todo lo demas (cargar_sesion).
        mascara_fases = None
        if variante_fases is not None:
            df = cargar_sesion(ruta)
            from fases import mascara_entrenamiento
            mascara_fases = mascara_entrenamiento(
                df["fase"].astype(str).values, df["label"].values,
                variante_fases)
        else:
            df = pd.read_csv(ruta)
        if excluir_margenes is None:
            excluir_margenes = mascara_fases is None

        if self.feature_cols is None:
            faltan = [c for c in COLUMNAS_MODELO if c not in df.columns]
            if not faltan:
                # Esquema nuevo: seleccion explicita. Detectar "todas
                # menos label" seria un error aqui, porque arrastraria
                # subject_id, timestamps y el giroscopio al vector de
                # entrada.
                self.feature_cols = list(COLUMNAS_MODELO)
            else:
                # CSV antiguo o de otra procedencia: se avisa y se cae al
                # comportamiento previo, en vez de fallar en silencio.
                candidatas = [c for c in df.columns
                              if c not in COLUMNAS_METADATOS]
                print(f"[PREPROC] AVISO: faltan las columnas {faltan} del "
                      f"esquema estandar. Usando como features: {candidatas}")
                self.feature_cols = candidatas

        n_inicial = len(df)
        conservar = np.ones(len(df), dtype=bool)
        if mascara_fases is not None:
            conservar &= mascara_fases
        if excluir_calibracion and "es_calibracion" in df.columns:
            conservar &= df["es_calibracion"].values == 0
        if excluir_margenes and "en_margen" in df.columns:
            conservar &= df["en_margen"].values == 0
        # Repeticiones que el operador descarto: no entran nunca.
        if "descartada" in df.columns:
            conservar &= df["descartada"].fillna(0).values != 1
        df = df[conservar]

        if len(df) != n_inicial:
            criterio = (f"fases, variante {variante_fases}"
                        if mascara_fases is not None else "margen fijo")
            print(f"[PREPROC] Filas: {n_inicial} → {len(df)} "
                  f"(descartadas {n_inicial - len(df)}: calibracion y "
                  f"{criterio})")

        descartados = [c for c in COLUMNAS_NO_MODELO if c in df.columns]
        if descartados:
            print(f"[PREPROC] Canales grabados pero fuera del modelo: "
                  f"{descartados}")
        print(f"[PREPROC] Canales del modelo ({len(self.feature_cols)}): "
              f"{self.feature_cols}")

        return df.reset_index(drop=True)

    def generar_ventanas(
        self, df: pd.DataFrame
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Aplica la ventana deslizante sobre el DataFrame.

        Returns:
            X: (num_ventanas, window_size, num_features) → (N, 20, 8)
            y: (num_ventanas, 5)  ← one-hot encoding de las 5 clases
        """
        data = df[self.feature_cols].values.astype(np.float32)
        labels = df["label"].values.astype(np.int32)

        # SEGMENTACION POR BLOQUE.
        #
        # Tras descartar los margenes y la calibracion, las filas que
        # quedan ya NO son contiguas en el tiempo: entre el final de un
        # bloque y el principio del siguiente hay un hueco. Deslizar la
        # ventana sobre el DataFrame entero produciria ventanas que
        # cruzan ese hueco y mezclan el final de una contraccion con el
        # principio del reposo siguiente, etiquetadas por voto
        # mayoritario con lo que toque. Serian ventanas que no
        # corresponden a ninguna senal real.
        #
        # Por eso se identifican segmentos contiguos y la ventana nunca
        # cruza de uno a otro. Un segmento cambia cuando cambia
        # cualquiera de las claves de bloque, o cuando el timestamp da un
        # salto mayor a 3 periodos de muestreo.
        segmento_id = segmentos(df, 1000.0 / self.sampling_rate_hz)

        ventanas_X = []
        ventanas_y = []
        descartadas = 0

        for seg in np.unique(segmento_id):
            idx = np.where(segmento_id == seg)[0]
            inicio_seg, fin_seg = idx[0], idx[-1] + 1
            n_seg = fin_seg - inicio_seg

            if n_seg < self.window_size:
                # Segmento mas corto que una ventana: no da ni una.
                descartadas += n_seg
                continue

            for off in range(0, n_seg - self.window_size + 1, self.stride):
                inicio = inicio_seg + off
                fin = inicio + self.window_size

                ventanas_X.append(data[inicio:fin])

                # Etiqueta por voto mayoritario. Dentro de un segmento la
                # etiqueta es constante por construccion, asi que el voto
                # es una salvaguarda, no una necesidad.
                etiquetas_en_ventana = labels[inicio:fin]
                ventanas_y.append(np.bincount(etiquetas_en_ventana).argmax())

        if not ventanas_X:
            raise ValueError(
                f"No se genero ninguna ventana. Con window_size="
                f"{self.window_size} muestras, ningun bloque contiguo del "
                f"CSV alcanza esa longitud."
            )

        if descartadas:
            print(f"[PREPROC] {descartadas} muestras en bloques mas cortos "
                  f"que la ventana ({self.window_size}); sin ventanas.")
        print(f"[PREPROC] Segmentos contiguos: {len(np.unique(segmento_id))}")

        X = np.array(ventanas_X)
        y = np.array(ventanas_y)

        # One-hot encoding: 5 clases
        y_onehot = np.eye(5, dtype=np.float32)[y]

        print(f"[PREPROC] Dataset generado:")
        print(f"  Ventanas totales: {X.shape[0]}")
        print(f"  Dimensiones X:    {X.shape}  (ventanas, pasos, features)")
        print(f"  Dimensiones y:    {y_onehot.shape}  (ventanas, clases)")

        return X, y_onehot


if __name__ == "__main__":
    # Una sesion de principio a fin, por el mismo camino que el modelo.
    import sys
    v = preparar_sesion(sys.argv[1])
    print(f"{len(v)} ventanas, forma {v.X.shape}")
