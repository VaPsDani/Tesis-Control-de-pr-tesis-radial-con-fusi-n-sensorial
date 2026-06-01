"""
entrenamiento.py - Ciclo de entrenamiento del modelo CNN-BiLSTM-Attention
==========================================================================
Protesis transradial - Fusion sensorial y Deep Learning

FLUJO:
  1. Cargar dataset CSV y aplicar ventana deslizante (preprocesamiento.py)
  2. Dividir en train/test respetando orden temporal (80/20)
  3. Construir y compilar el modelo (modelo.py)
  4. Entrenar con early stopping y reduccion de LR
  5. Evaluar y guardar metricas
  6. Exportar graficas de entrenamiento

USO:
  python entrenamiento.py --csv dataset_gestos.csv --epochs 100
"""

import argparse
import os

import matplotlib.pyplot as plt
import numpy as np
import tensorflow as tf
from sklearn.metrics import classification_report, confusion_matrix

from modelo import construir_modelo, compilar_modelo
from preprocesamiento import SlidingWindowPreprocessor


def graficar_historial(historial, output_dir: str = "output"):
    """Guarda las curvas de perdida y exactitud del entrenamiento."""
    os.makedirs(output_dir, exist_ok=True)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4))

    ax1.plot(historial.history["loss"], label="Train Loss")
    ax1.plot(historial.history["val_loss"], label="Val Loss")
    ax1.set_title("Perdida durante entrenamiento")
    ax1.set_xlabel("Epoca")
    ax1.set_ylabel("Categorical Crossentropy")
    ax1.legend()
    ax1.grid(True)

    ax2.plot(historial.history["accuracy"], label="Train Acc")
    ax2.plot(historial.history["val_accuracy"], label="Val Acc")
    ax2.set_title("Exactitud durante entrenamiento")
    ax2.set_xlabel("Epoca")
    ax2.set_ylabel("Accuracy")
    ax2.legend()
    ax2.grid(True)

    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "historial_entrenamiento.png"), dpi=150)
    plt.close()
    print(f"[GRAFICA] Guardada en {output_dir}/historial_entrenamiento.png")


def graficar_matriz_confusion(
    y_true: np.ndarray, y_pred: np.ndarray, output_dir: str = "output"
):
    """Guarda la matriz de confusion normalizada."""
    etiquetas = ["Rest", "Pinch", "Tripod", "Power", "Finger_Ext"]
    cm = confusion_matrix(y_true.argmax(axis=1), y_pred.argmax(axis=1))
    cm_norm = cm.astype("float32") / cm.sum(axis=1, keepdims=True)

    fig, ax = plt.subplots(figsize=(6, 5))
    im = ax.imshow(cm_norm, cmap="Blues", vmin=0, vmax=1)

    ax.set_xticks(range(5))
    ax.set_yticks(range(5))
    ax.set_xticklabels(etiquetas, rotation=45, ha="right")
    ax.set_yticklabels(etiquetas)
    ax.set_xlabel("Predicho")
    ax.set_ylabel("Real")
    ax.set_title("Matriz de Confusion (normalizada)")

    for i in range(5):
        for j in range(5):
            ax.text(j, i, f"{cm_norm[i, j]:.2f}", ha="center", va="center", fontsize=9)

    plt.colorbar(im)
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "matriz_confusion.png"), dpi=150)
    plt.close()
    print(f"[GRAFICA] Matriz guardada en {output_dir}/matriz_confusion.png")


def main():
    parser = argparse.ArgumentParser(
        description="Entrenar CNN-BiLSTM-Attention para clasificacion de gestos"
    )
    parser.add_argument("--csv", type=str, required=True, help="Ruta al dataset CSV")
    parser.add_argument(
        "--epochs", type=int, default=100, help="Maximo de epocas (default: 100)"
    )
    parser.add_argument(
        "--batch_size", type=int, default=32, help="Tamano del batch (default: 32)"
    )
    parser.add_argument(
        "--lr", type=float, default=1e-3, help="Tasa de aprendizaje inicial (default: 1e-3)"
    )
    parser.add_argument(
        "--output_dir", type=str, default="output", help="Directorio de salida"
    )
    args = parser.parse_args()

    # ========== 1. PREPROCESAMIENTO ==========
    print("=" * 60)
    print("PASO 1: Cargando y aplicando ventana deslizante")
    print("=" * 60)

    preproc = SlidingWindowPreprocessor(
        window_size_ms=200, stride_ms=20, sampling_rate_hz=100
    )
    df = preproc.cargar_csv(args.csv)
    X, y = preproc.generar_ventanas(df)
    X_train, X_test, y_train, y_test = preproc.train_test_split_secuencial(
        X, y, test_ratio=0.2
    )

    # ========== 2. CONSTRUIR MODELO ==========
    print("\n" + "=" * 60)
    print("PASO 2: Construyendo modelo CNN-BiLSTM-Attention")
    print("=" * 60)

    modelo = construir_modelo(
        window_size=X.shape[1], num_features=X.shape[2], num_clases=5
    )
    modelo = compilar_modelo(modelo, lr=args.lr)
    modelo.summary()

    # ========== 3. CALLBACKS ==========
    callbacks = [
        tf.keras.callbacks.EarlyStopping(
            monitor="val_loss",
            patience=15,
            restore_best_weights=True,
            verbose=1,
        ),
        tf.keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss",
            factor=0.5,
            patience=7,
            min_lr=1e-6,
            verbose=1,
        ),
        tf.keras.callbacks.ModelCheckpoint(
            filepath=os.path.join(args.output_dir, "mejor_modelo.keras"),
            monitor="val_accuracy",
            save_best_only=True,
            verbose=1,
        ),
    ]

    # ========== 4. ENTRENAR ==========
    print("\n" + "=" * 60)
    print("PASO 3: Entrenando modelo")
    print("=" * 60)

    historial = modelo.fit(
        X_train,
        y_train,
        validation_data=(X_test, y_test),
        epochs=args.epochs,
        batch_size=args.batch_size,
        callbacks=callbacks,
        verbose=2,
    )

    # ========== 5. EVALUAR ==========
    print("\n" + "=" * 60)
    print("PASO 4: Evaluacion en test")
    print("=" * 60)

    loss, accuracy, auc = modelo.evaluate(X_test, y_test, verbose=0)
    print(f"Loss:     {loss:.4f}")
    print(f"Accuracy: {accuracy:.4f} ({accuracy*100:.2f}%)")
    print(f"AUC:      {auc:.4f}")

    y_pred = modelo.predict(X_test)
    etiquetas = ["Rest", "Pinch", "Tripod", "Power", "Finger_Ext"]
    print("\nClassification Report:")
    print(classification_report(
        y_test.argmax(axis=1),
        y_pred.argmax(axis=1),
        target_names=etiquetas,
        digits=4,
    ))

    # ========== 6. GUARDAR MODELO FINAL ==========
    os.makedirs(args.output_dir, exist_ok=True)
    ruta_modelo = os.path.join(args.output_dir, "modelo_final.keras")
    modelo.save(ruta_modelo)
    print(f"\n[MODELO] Guardado en: {ruta_modelo}")

    # ========== 7. GRAFICAS ==========
    graficar_historial(historial, args.output_dir)
    graficar_matriz_confusion(y_test, y_pred, args.output_dir)


if __name__ == "__main__":
    main()
