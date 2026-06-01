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

ESTRUCTURA DE SALIDA:
  X: (num_ventanas, window_size, num_features)  → (N, 20, 9)
  y: (num_ventanas,)  → one-hot encoding (N, 5)
"""

import numpy as np
import pandas as pd
from typing import Tuple


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

    def cargar_csv(self, ruta: str) -> pd.DataFrame:
        """
        Carga el CSV generado por el ESP32 (Modulo 1).
        El CSV debe tener 9 columnas de features + 1 columna 'label'.
        """
        df = pd.read_csv(ruta)
        if self.feature_cols is None:
            # Detectar automaticamente (todas excepto 'label')
            self.feature_cols = [c for c in df.columns if c != "label"]
        return df

    def generar_ventanas(
        self, df: pd.DataFrame
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Aplica la ventana deslizante sobre el DataFrame.

        Returns:
            X: (num_ventanas, window_size, num_features)
            y: (num_ventanas, 5)  ← one-hot encoding de las 5 clases
        """
        data = df[self.feature_cols].values.astype(np.float32)
        labels = df["label"].values.astype(np.int32)

        ventanas_X = []
        ventanas_y = []

        n = len(data)
        for inicio in range(0, n - self.window_size + 1, self.stride):
            fin = inicio + self.window_size
            ventana = data[inicio:fin]

            # Etiqueta = valor mas frecuente en la ventana (voto mayoritario)
            etiquetas_en_ventana = labels[inicio:fin]
            etiqueta = np.bincount(etiquetas_en_ventana).argmax()

            ventanas_X.append(ventana)
            ventanas_y.append(etiqueta)

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
