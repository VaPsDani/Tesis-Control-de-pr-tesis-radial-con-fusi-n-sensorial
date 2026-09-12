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

ESQUEMA DEL CSV DE CAPTURA (18 columnas):
  subject_id, repetition_id, timestamp_ms, v1..v5,
  ax, ay, az, gx, gy, gz, label, bloque_tipo, en_margen, es_calibracion,
  fase

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
  ax, ay, az. Con 8 canales el vector tiene la misma forma que la rama
  EMG sobre NinaPro DB5 (5 sEMG + 3 ACC), lo que hace directa la
  comparacion entre ramas.

ESTRUCTURA DE SALIDA:
  X: (num_ventanas, window_size, num_features)  → (N, 20, 8)
  y: (num_ventanas,)  → one-hot encoding (N, 5)
"""

import json
import os

import numpy as np
import pandas as pd
from typing import Tuple

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
    "label", "bloque_tipo", "en_margen", "es_calibracion",
]

NUM_CANALES_MODELO = len(COLUMNAS_MODELO)   # 8


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
        df = pd.read_csv(ruta)

        # Las fases se calculan sobre la sesion ENTERA, antes de filtrar:
        # necesitan el bloque de calibracion como base de respaldo y la
        # continuidad temporal de los reposos.
        mascara_fases = None
        if variante_fases is not None and "label" in df.columns:
            from fases import FASES_VERSION, mascara_entrenamiento
            vigente = "fase" in df.columns
            ruta_json = os.path.splitext(ruta)[0] + "_fases.json"
            if vigente and os.path.exists(ruta_json):
                with open(ruta_json, encoding="utf-8") as f:
                    vigente = json.load(f).get("fases_version") == FASES_VERSION
            if not vigente:
                from anotar_fases import anotar_df
                base = df.drop(columns="fase") if "fase" in df.columns else df
                fase, _, _ = anotar_df(base)
                df = base.assign(fase=fase)
                print("[PREPROC] Columna fase ausente u obsoleta: calculada "
                      "al vuelo (anotar_fases.py la deja en el CSV).")
            mascara_fases = mascara_entrenamiento(
                df["fase"].astype(str).values, df["label"].values,
                variante_fases)
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
        claves = [c for c in ("subject_id", "repetition_id", "label",
                              "bloque_tipo")
                  if c in df.columns]
        if claves:
            cambio = np.zeros(len(df), dtype=bool)
            for c in claves:
                cambio |= df[c].ne(df[c].shift()).values
            if "timestamp_ms" in df.columns:
                dt = df["timestamp_ms"].diff().values
                periodo = 1000.0 / self.sampling_rate_hz
                cambio |= np.nan_to_num(dt, nan=0.0) > 3 * periodo
            segmento_id = np.cumsum(cambio)
        else:
            # CSV sin metadatos de bloque: un unico segmento, que es el
            # comportamiento historico.
            segmento_id = np.zeros(len(df), dtype=np.int64)

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

    def train_test_split_secuencial(
        self, X: np.ndarray, y: np.ndarray, test_ratio: float = 0.2
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Division entrenamiento/prueba RESPETANDO el orden temporal.
        NO se usa shuffle aleatorio porque los datos son temporales.
        """
        n = X.shape[0]
        split_idx = int(n * (1 - test_ratio))

        X_train = X[:split_idx]
        y_train = y[:split_idx]
        X_test = X[split_idx:]
        y_test = y[split_idx:]

        print(f"[SPLIT] Train: {X_train.shape[0]} | Test: {X_test.shape[0]}")
        return X_train, X_test, y_train, y_test


if __name__ == "__main__":
    # Ejemplo de uso
    preproc = SlidingWindowPreprocessor(
        window_size_ms=200, stride_ms=20, sampling_rate_hz=100
    )

    df = preproc.cargar_csv("dataset_gestos.csv")
    X, y = preproc.generar_ventanas(df)

    X_train, X_test, y_train, y_test = preproc.train_test_split_secuencial(
        X, y, test_ratio=0.2
    )
