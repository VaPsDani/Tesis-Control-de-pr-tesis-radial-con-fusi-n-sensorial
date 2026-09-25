"""
keras_legado.py - Keras 2 (tf_keras) para todo modelo que se despliega
======================================================================
Protesis transradial - Fusion sensorial y Deep Learning

POR QUE:
  Con Keras 3, la LSTM se exporta a TFLite como un bucle WHILE que el
  conversor no fusiona en su operacion nativa UNIDIRECTIONAL_SEQUENCE_LSTM,
  y la cuantizacion INT8 de ese bucle revienta el proceso (TF 2.16 y 2.21).
  Con Keras 2 (tf_keras) la BiLSTM sale como dos LSTM nativas, todo INT8,
  y TFLite Micro la ejecuta. Ver claude/viabilidad-tflite-micro.md.

DESDE 2026-09-25:
  Todo entrenamiento nuevo de produccion y de ablacion con datos propios
  usa tf_keras, para que el modelo evaluado sea el mismo que se despliega.
  Entorno: requirements-produccion.txt (WSL, TF 2.21 + tf_keras 2.21).

  NO lo usan la validacion preliminar sobre NinaPro
  (experimentos/validacion_preliminar_emg) ni los analisis del dataset
  publico de LMG: quedan reproducibles en su entorno original
  (venv-tesis, requirements.txt, Keras 3).

USO (antes de importar tensorflow en el proceso):
  import keras_legado
  keras_legado.activar()
  import tensorflow as tf
  keras_legado.verificar()
"""

import os
import sys


def activar() -> None:
    """Fija TF_USE_LEGACY_KERAS=1. Debe llamarse antes de importar tensorflow."""
    if "tensorflow" in sys.modules and os.environ.get("TF_USE_LEGACY_KERAS") != "1":
        raise RuntimeError(
            "TensorFlow ya se importo con Keras 3 en este proceso. Llame a "
            "keras_legado.activar() antes del primer 'import tensorflow'.")
    os.environ["TF_USE_LEGACY_KERAS"] = "1"


def verificar() -> str:
    """Comprueba que tf.keras es tf_keras (Keras 2). Devuelve su version."""
    import tensorflow as tf
    try:
        modulo = tf.keras.layers.LSTM.__module__
    except ImportError as e:
        raise RuntimeError(
            "Falta el paquete tf_keras. Use el entorno de "
            "requirements-produccion.txt.") from e
    if not modulo.startswith("tf_keras"):
        raise RuntimeError(
            f"tf.keras no es Keras 2 (LSTM viene de {modulo}). Llame a "
            "keras_legado.activar() antes de importar tensorflow.")
    import tf_keras
    return tf_keras.__version__
