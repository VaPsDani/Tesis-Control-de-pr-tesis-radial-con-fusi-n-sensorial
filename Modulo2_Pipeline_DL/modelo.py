"""
modelo.py - Arquitectura CNN-BiLSTM-Attention para clasificacion de gestos
==========================================================================
Protesis transradial - Fusion sensorial y Deep Learning

ARQUITECTURA:
  Entrada: (window_size=40, num_features=8)
           - 5 canales EMG (simula LMG) + 3 canales ACC (simula IMU)
           - 40 pasos temporales = 200 ms a 200 Hz

  Capa 1 (Conv1D):  Filtros=64, kernel=3, ReLU, BatchNorm
    -> Extrae patrones locales entre canales vecinos
    -> Ventana de 3 pasos (~15 ms) captura activaciones musculares
       y variaciones de aceleracion simultaneamente

  Capa 2 (Conv1D):  Filtros=128, kernel=3, ReLU, BatchNorm
    -> Jerarquia de caracteristicas mas abstractas
    -> Combina patrones de bajo nivel en descriptores de mas alto nivel

  Capa 3 (BiLSTM):  64 unidades (32 forward + 32 backward)
    -> Procesa la secuencia temporal en ambas direcciones
    -> El contexto futuro (BiLSTM) permite distinguir gestos que
       comparten inicio pero divergen al final

  Capa 4 (Attention): Mecanismo Bahdanau personalizado
    -> Ponderacion temporal adaptativa
    -> Un gesto "Power" depende mas de los picos de activacion,
       mientras que "Rest" se distribuye uniformemente

  Capa 5 (Dense):  64 unidades, ReLU, Dropout 0.5
    -> Clasificador con regularizacion

  Capa 6 (Salida):  5 unidades, Softmax
    -> Distribucion sobre: Rest, Pinch, Tripod, Power, Finger_Ext

ARQUITECTURA (resumen):
  Input(40,8) -> Conv1D(64) -> Conv1D(128) -> BiLSTM(64) ->
  Attention -> Dense(64) -> Softmax(5)
"""

import tensorflow as tf
from tensorflow.keras import layers, Model, Input
from tensorflow.keras.regularizers import l2


# ============================================================
# CAPA DE ATENCION PERSONALIZADA (Bahdanau-style)
# ============================================================
class MecanismoAtencion(layers.Layer):
    """
    Capa de atencion temporal basada en Bahdanau Attention.

    Funcionamiento:
      1. Recibe la secuencia de la BiLSTM: (batch, timesteps, units)
      2. Calcula un score de relevancia para cada timestep
         score(t) = tanh(h_t * W1) * W2
      3. Normaliza con Softmax: alpha_t = softmax(score(t))
      4. Contexto = suma(alpha_t * h_t) -> vector global ponderado

    Esto permite que el modelo preste atencion a los momentos
    criticos del gesto (ej: el pico de contraccion muscular).
    """

    def __init__(self, units: int = 64, **kwargs):
        super().__init__(**kwargs)
        self.units = units

    def build(self, input_shape):
        self.W1 = self.add_weight(
            shape=(input_shape[-1], self.units),
            initializer="glorot_uniform",
            trainable=True,
            name="atencion_W1",
        )
        self.W2 = self.add_weight(
            shape=(self.units, 1),
            initializer="glorot_uniform",
            trainable=True,
            name="atencion_W2",
        )
        super().build(input_shape)

    def call(self, inputs):
        score = tf.tanh(tf.tensordot(inputs, self.W1, axes=[[2], [0]]))
        attention_weights = tf.nn.softmax(
            tf.tensordot(score, self.W2, axes=[[2], [0]]), axis=1
        )
        context = tf.reduce_sum(attention_weights * inputs, axis=1)
        return context

    def get_config(self):
        config = super().get_config()
        config.update({"units": self.units})
        return config


# ============================================================
# CONSTRUCTOR DEL MODELO HIBRIDO
# ============================================================
def construir_modelo(
    window_size: int = 40,
    num_features: int = 8,
    num_clases: int = 5,
    l2_reg: float = 1e-4,
    dropout_rate: float = 0.5,
) -> Model:
    """
    Construye el grafo de computacion CNN-BiLSTM-Attention.

    Args:
        window_size: Pasos temporales (40 = 200 ms a 200 Hz)
        num_features: Canales totales (8 = 5 EMG + 3 ACC)
        num_clases: Gestos a clasificar (5)
        l2_reg: Factor de regularizacion L2
        dropout_rate: Tasa de dropout en la capa densa

    Returns:
        modelo: Modelo de Keras (sin compilar)
    """
    entrada = Input(shape=(window_size, num_features), name="sensor_input")

    # --- Bloque Conv1D: Extraccion espaciotemporal ---
    # Cada filtro Conv1D aprende a detectar correlaciones entre
    # canales EMG+ACC en una vecindad de 3 pasos temporales (~15 ms)
    x = layers.Conv1D(
        filters=64,
        kernel_size=3,
        padding="same",
        activation="relu",
        kernel_regularizer=l2(l2_reg),
        name="conv1d_1",
    )(entrada)
    x = layers.BatchNormalization(name="bn_1")(x)

    x = layers.Conv1D(
        filters=128,
        kernel_size=3,
        padding="same",
        activation="relu",
        kernel_regularizer=l2(l2_reg),
        name="conv1d_2",
    )(x)
    x = layers.BatchNormalization(name="bn_2")(x)

    # --- Bloque BiLSTM: Dependencias temporales bidireccionales ---
    # BiLSTM procesa la secuencia completa en ambos sentidos.
    # return_sequences=True para que Attention reciba toda la secuencia.
    # BiLSTM con cuDNN activado (por defecto en TF 2.10).
    # En NVIDIA RTX, cuDNN acelera ~3-5x la operacion LSTM.
    x = layers.Bidirectional(
        layers.LSTM(units=32, return_sequences=True,
                    kernel_regularizer=l2(l2_reg)),
        name="bilstm_1",
    )(x)

    # --- Mecanismo de Atencion ---
    # Pondera cada paso temporal segun su relevancia para la clasificacion.
    x = MecanismoAtencion(units=64, name="atencion")(x)

    # --- Clasificador ---
    x = layers.Dense(64, activation="relu", kernel_regularizer=l2(l2_reg), name="dense_1")(x)
    x = layers.Dropout(dropout_rate, name="dropout")(x)

    salida = layers.Dense(num_clases, activation="softmax", name="salida_gesto")(x)

    modelo = Model(inputs=entrada, outputs=salida, name="CNN_BiLSTM_Attention")

    return modelo


def compilar_modelo(modelo: Model, lr: float = 1e-3) -> Model:
    """
    Compila el modelo con optimizador Adam y categorical crossentropy.
    """
    modelo.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=lr),
        loss="categorical_crossentropy",
        metrics=["accuracy", tf.keras.metrics.AUC(name="auc")],
    )
    return modelo


def resumen_modelo(modelo: Model):
    """Imprime la arquitectura y el conteo de parametros."""
    modelo.summary()
    total_params = modelo.count_params()
    print(f"[MODELO] Parametros totales: {total_params:,}")
    params_entrenables = sum(tf.size(w).numpy() for w in modelo.trainable_weights)
    print(f"[MODELO] Parametros entrenables: {params_entrenables:,}")

    if total_params < 100_000:
        print("[OK] Modelo ligero, apto para TFLite Micro")
    else:
        print("[WARN] Modelo pesado > 100k params, considere reducirlo")


if __name__ == "__main__":
    modelo = construir_modelo()
    modelo = compilar_modelo(modelo)
    resumen_modelo(modelo)
