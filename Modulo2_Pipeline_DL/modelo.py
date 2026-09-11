"""
modelo.py - Arquitectura CNN-BiLSTM-Attention para clasificacion de gestos
==========================================================================
Protesis transradial - Fusion sensorial y Deep Learning

ARQUITECTURA:
  Entrada: (window_size=20, num_features=8) → 20 pasos temporales × 8 canales
           - 5 canales LMG (fotodiodos OPT101) + 3 del acelerometro
           - Misma forma que la rama EMG (5 sEMG + 3 ACC), lo que hace
             directa la comparacion entre ambas

  Capa 1 (Conv1D):  Filtros=64, kernel=3, activacion=ReLU
    → Extrae patrones espaciales entre canales de sensores LMG+ACC
    → Ej: correlacion entre el fotodiodo 1 y la componente az del
      acelerometro durante un gesto

  Capa 2 (Conv1D):  Filtros=128, kernel=3, activacion=ReLU
    → Jerarquia de caracteristicas mas abstractas

  Capa 3 (BiLSTM):  64 unidades (32 forward + 32 backward)
    → Captura dependencias temporales bidireccionales
    → El contexto pasado y futuro mejora la precision del gesto

  Capa 4 (Attention):  Mecanismo personalizado
    → Ponderacion temporal: asigna pesos a cada paso temporal
    → El gesto "Power" puede depender mas de los ultimos 5 pasos
    → El gesto "Rest" se distribuye uniformemente en el tiempo

  Capa 5 (Dense):  64 unidades, ReLU, Dropout 0.5
    → Clasificador con regularizacion para evitar overfitting

  Capa 6 (Salida):  5 unidades, Softmax
    → Distribucion de probabilidad sobre: Rest, Pinch, Tripod, Power, Ext.

ARQUITECTURA (resumen):
  Input(20,8) → Conv1D(64) → Conv1D(128) → BiLSTM(64) → Attention → Dense(64) → Softmax(5)
"""

import tensorflow as tf
from tensorflow.keras import layers, Model, Input
from tensorflow.keras.regularizers import l2


# ============================================================
# CAPA DE ATENCION PERSONALIZADA (Luong-style / Bahdanau)
# ============================================================
class MecanismoAtencion(layers.Layer):
    """
    Capa de atencion temporal basada en Bahdanau Attention.

    Funcionamiento:
      1. Recibe la secuencia completa de la BiLSTM: (batch, timesteps, units)
      2. Calcula un score de relevancia para cada timestep
      3. Normaliza con Softmax → pesos de atencion alpha_t
      4. Multiplica cada timestep por su peso y suma (contexto global)

    Esto permite que el modelo "preste atencion" a los momentos
    criticos del gesto (ej: el pico de contraccion muscular).
    """

    def __init__(self, units: int = 64, **kwargs):
        super().__init__(**kwargs)
        self.units = units

    def build(self, input_shape):
        # W1: peso para transformar la salida de la BiLSTM
        self.W1 = self.add_weight(
            shape=(input_shape[-1], self.units),
            initializer="glorot_uniform",
            trainable=True,
            name="atencion_W1",
        )
        # W2: peso para el vector de contexto
        self.W2 = self.add_weight(
            shape=(self.units, 1),
            initializer="glorot_uniform",
            trainable=True,
            name="atencion_W2",
        )
        super().build(input_shape)

    def call(self, inputs):
        # inputs shape: (batch, timesteps, features)
        # score = tanh(x · W1) · W2  → (batch, timesteps, 1)
        score = tf.tanh(tf.tensordot(inputs, self.W1, axes=[[2], [0]]))
        attention_weights = tf.nn.softmax(
            tf.tensordot(score, self.W2, axes=[[2], [0]]), axis=1
        )
        # context = suma(attention_weights * inputs, axis=1)
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
    window_size: int = 20,
    num_features: int = 8,
    num_clases: int = 5,
    l2_reg: float = 1e-4,
    dropout_rate: float = 0.5,
) -> Model:
    """
    Construye el grafo de computacion CNN-BiLSTM-Attention.

    Args:
        window_size: Pasos temporales de la ventana deslizante (20)
        num_features: Canales de sensores (8: 5 LMG + 3 acelerometro)
        num_clases: Gestos a clasificar (5: Rest, Pinch, Tripod, Power, Ext.)
        l2_reg: Factor de regularizacion L2
        dropout_rate: Tasa de dropout en la capa densa

    Returns:
        modelo: Modelo de Keras compilado
    """
    entrada = Input(shape=(window_size, num_features), name="sensor_input")

    # --- Bloque Conv1D: Extraccion espacial ---
    # Cada filtro Conv1D aprende a detectar patrones entre sensores
    # en una vecindad de 3 pasos temporales.
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

    # --- Bloque BiLSTM: Dependencias temporales ---
    # BiLSTM procesa la secuencia en ambas direcciones.
    # return_sequences=True para que Attention reciba la secuencia completa.
    x = layers.Bidirectional(
        layers.LSTM(units=32, return_sequences=True, kernel_regularizer=l2(l2_reg)),
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


def compilar_modelo(
    modelo: Model, lr: float = 1e-3, label_smoothing: float = 0.0
) -> Model:
    """
    Compila el modelo con optimizador Adam y categorical crossentropy.

    Args:
        modelo: Modelo de Keras sin compilar
        lr: Tasa de aprendizaje inicial de Adam
        label_smoothing: Suavizado de etiquetas de la crossentropy.
            0.0 (default) reproduce exactamente la ruta LMG del hardware
            fisico. La ruta de validacion sobre NinaPro DB5
            (entrenamiento_cv.py) pasa 0.1, que es el valor con el que se
            obtuvo la linea base de 82.98%; cambiarlo romperia la
            comparabilidad entre esquemas de particion.
    """
    modelo.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=lr),
        loss=tf.keras.losses.CategoricalCrossentropy(
            label_smoothing=label_smoothing
        ),
        metrics=["accuracy", tf.keras.metrics.AUC(name="auc")],
    )
    return modelo


def resumen_modelo(modelo: Model):
    """Imprime la arquitectura y el conteo de parametros."""
    modelo.summary()
    total_params = modelo.count_params()
    print(f"[MODELO] Parametros totales: {total_params:,}")
    print(f"[MODELO] Parametros entrenables: {sum(
        tf.size(w).numpy() for w in modelo.trainable_weights
    ):,}")

    # Verificar que quepa en ESP32 (< 512 KB)
    if total_params < 100_000:
        print("[OK] Modelo ligero, apto para TFLite Micro")
    else:
        print("[WARN] Modelo pesado > 100k params, considere reducirlo")


if __name__ == "__main__":
    modelo = construir_modelo()
    modelo = compilar_modelo(modelo)
    resumen_modelo(modelo)
