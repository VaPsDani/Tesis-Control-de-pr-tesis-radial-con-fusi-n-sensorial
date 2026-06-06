"""
entrenamiento.py - Ciclo completo de entrenamiento con validacion cruzada
==========================================================================
Protesis transradial - Validacion con dataset NinaPro DB5

FLUJO:
  1. Cargar y preprocesar dataset NinaPro DB5 (10 sujetos)
  2. Aplicar remuestreo de ACC (200 -> 50 -> 200 Hz)
  3. Ventana deslizante con early fusion (EMG + ACC)
  4. K-Fold estratificado (k=5) sobre la totalidad de ventanas
  5. Entrenar modelo CNN-BiLSTM-Attention en cada fold
  6. Exportar a 'resultados_preliminares/':
     - historial_entrenamiento.png (curvas promedio + por fold)
     - matriz_confusion.png (matriz 5x5 normalizada y promediada)
     - metricas.txt (reporte completo por clase y global)

USO:
  python entrenamiento.py --mat ./NinaPro_DB5/ --epochs 100
"""

import argparse
import os
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import tensorflow as tf
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    precision_recall_fscore_support,
)

from modelo import construir_modelo, compilar_modelo
from preprocesamiento import (
    cargar_procesar_dataset,
    NOMBRES_GESTOS,
    NUM_CLASES,
    VENTANA_SAMPLES,
    CANALES_TOTAL,
)

warnings.filterwarnings("ignore")

RESULTADOS_DIR = "resultados_preliminares"


# ============================================================
# GRAFICAS DE ENTRENAMIENTO
# ============================================================
def graficar_historial_kfold(
    historiales: list,
    output_dir: str = RESULTADOS_DIR,
):
    """
    Grafica las curvas de Loss y Accuracy de los k folds.

    Cada fold puede tener distinta longitud (EarlyStopping).
    Se truncan al minimo comun y se grafica:
      - Lineas semi-transparentes por fold
      - Linea gruesa del promedio
      - Banda de desviacion estandar

    Args:
        historiales: Lista de History objects de Keras
        output_dir: Directorio de salida
    """
    os.makedirs(output_dir, exist_ok=True)

    # Extraer historias
    train_losses = []
    val_losses = []
    train_accs = []
    val_accs = []

    for h in historiales:
        train_losses.append(h.history["loss"])
        val_losses.append(h.history["val_loss"])
        train_accs.append(h.history["accuracy"])
        val_accs.append(h.history["val_accuracy"])

    # Truncar al minimo comun de epochs entre folds
    min_epochs = min(len(l) for l in train_losses)
    train_losses = [l[:min_epochs] for l in train_losses]
    val_losses = [l[:min_epochs] for l in val_losses]
    train_accs = [l[:min_epochs] for l in train_accs]
    val_accs = [l[:min_epochs] for l in val_accs]

    epochs = np.arange(1, min_epochs + 1)
    k = len(historiales)
    colores = plt.cm.tab10(np.linspace(0, 1, k))

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    # --- Grafico de Loss ---
    for i in range(k):
        ax1.plot(epochs, train_losses[i], color=colores[i], alpha=0.3, linewidth=1)
        ax1.plot(epochs, val_losses[i], color=colores[i], alpha=0.3, linewidth=1,
                 linestyle="--")

    train_mean = np.mean(train_losses, axis=0)
    train_std = np.std(train_losses, axis=0)
    val_mean = np.mean(val_losses, axis=0)
    val_std = np.std(val_losses, axis=0)

    ax1.plot(epochs, train_mean, color="blue", linewidth=2, label="Train (prom)")
    ax1.fill_between(epochs, train_mean - train_std, train_mean + train_std,
                     color="blue", alpha=0.1)
    ax1.plot(epochs, val_mean, color="red", linewidth=2, label="Val (prom)", linestyle="--")
    ax1.fill_between(epochs, val_mean - val_std, val_mean + val_std,
                     color="red", alpha=0.1)

    ax1.set_title(f"Perdida (Categorical Crossentropy) - {k}-Fold CV")
    ax1.set_xlabel("Epoca")
    ax1.set_ylabel("Loss")
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    # --- Grafico de Accuracy ---
    for i in range(k):
        ax2.plot(epochs, train_accs[i], color=colores[i], alpha=0.3, linewidth=1)
        ax2.plot(epochs, val_accs[i], color=colores[i], alpha=0.3, linewidth=1,
                 linestyle="--")

    train_mean = np.mean(train_accs, axis=0)
    train_std = np.std(train_accs, axis=0)
    val_mean = np.mean(val_accs, axis=0)
    val_std = np.std(val_accs, axis=0)

    ax2.plot(epochs, train_mean, color="blue", linewidth=2, label="Train (prom)")
    ax2.fill_between(epochs, train_mean - train_std, train_mean + train_std,
                     color="blue", alpha=0.1)
    ax2.plot(epochs, val_mean, color="red", linewidth=2, label="Val (prom)", linestyle="--")
    ax2.fill_between(epochs, val_mean - val_std, val_mean + val_std,
                     color="red", alpha=0.1)

    ax2.set_title(f"Exactitud (Accuracy) - {k}-Fold CV")
    ax2.set_xlabel("Epoca")
    ax2.set_ylabel("Accuracy")
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    ruta = os.path.join(output_dir, "historial_entrenamiento.png")
    plt.savefig(ruta, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"[GRAFICA] {ruta}")


# ============================================================
# MATRIZ DE CONFUSION PROMEDIADA
# ============================================================
def graficar_matriz_confusion(
    matrices_por_fold: list,
    output_dir: str = RESULTADOS_DIR,
):
    """
    Grafica la matriz de confusion promediada sobre los k folds.

    Args:
        matrices_por_fold: Lista de arrays (5,5) con matrices de cada fold
        output_dir: Directorio de salida
    """
    os.makedirs(output_dir, exist_ok=True)

    # Promediar matrices de confusion (suma de conteos)
    cm_total = sum(matrices_por_fold)
    # Normalizar por fila (porcentaje por clase real)
    cm_norm = cm_total.astype("float64") / cm_total.sum(axis=1, keepdims=True)
    cm_norm = np.nan_to_num(cm_norm, nan=0.0)

    fig, ax = plt.subplots(figsize=(7, 6))
    im = ax.imshow(cm_norm, cmap="Blues", vmin=0, vmax=1)

    # Anotaciones
    for i in range(NUM_CLASES):
        for j in range(NUM_CLASES):
            valor = cm_norm[i, j]
            # Valor absoluto promedio
            absoluto = cm_total[i, j] / len(matrices_por_fold)
            texto = f"{valor:.2f}\n({absoluto:.0f})"
            color_texto = "white" if valor > 0.5 else "black"
            ax.text(j, i, texto, ha="center", va="center", fontsize=9,
                    color=color_texto)

    ax.set_xticks(range(NUM_CLASES))
    ax.set_yticks(range(NUM_CLASES))
    ax.set_xticklabels(NOMBRES_GESTOS, rotation=45, ha="right", fontsize=10)
    ax.set_yticklabels(NOMBRES_GESTOS, fontsize=10)
    ax.set_xlabel("Predicho", fontsize=11)
    ax.set_ylabel("Real", fontsize=11)
    ax.set_title(f"Matriz de Confusion (promedio {len(matrices_por_fold)} folds)\n"
                 f"Valor: proporcion | (conteo promedio por fold)", fontsize=11)

    plt.colorbar(im, shrink=0.8)
    plt.tight_layout()
    ruta = os.path.join(output_dir, "matriz_confusion.png")
    plt.savefig(ruta, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"[GRAFICA] {ruta}")


# ============================================================
# REPORTE DE METRICAS
# ============================================================
def guardar_metricas(
    metricas_por_fold: list,
    y_total: np.ndarray,
    y_pred_total: np.ndarray,
    output_dir: str = RESULTADOS_DIR,
):
    """
    Guarda un reporte detallado de metricas en TXT y lo imprime en consola.

    Args:
        metricas_por_fold: Lista de dicts con metricas por fold
        y_total: Etiquetas reales concatenadas de todos los folds
        y_pred_total: Predicciones concatenadas de todos los folds
        output_dir: Directorio de salida
    """
    os.makedirs(output_dir, exist_ok=True)

    lineas = []
    lineas.append("=" * 70)
    lineas.append("REPORTE DE METRICAS - VALIDACION CRUZADA (K-FOLD)")
    lineas.append(f"Dataset: NinaPro DB5 (10 sujetos)")
    lineas.append(f"Modelo: CNN-BiLSTM-Attention")
    lineas.append(f"Clases: {', '.join(NOMBRES_GESTOS)}")
    lineas.append(f"Numero de folds: {len(metricas_por_fold)}")
    lineas.append("=" * 70)
    lineas.append("")

    # --- Metricas por fold ---
    lineas.append("-" * 70)
    lineas.append("RESULTADOS POR FOLD")
    lineas.append("-" * 70)
    accs = []
    for i, m in enumerate(metricas_por_fold):
        accs.append(m["accuracy"])
        lineas.append(f"  Fold {i+1}:")
        lineas.append(f"    Accuracy:  {m['accuracy']:.4f} ({m['accuracy']*100:.2f}%)")
        lineas.append(f"    Loss:      {m['loss']:.4f}")
        lineas.append(f"    AUC:       {m['auc']:.4f}")
        lineas.append(f"    Epochs:    {m['epochs']}")
        lineas.append("")

    # --- Metricas globales ---
    lineas.append("-" * 70)
    lineas.append("METRICAS GLOBALES (promedio sobre folds)")
    lineas.append("-" * 70)
    acc_mean = np.mean(accs)
    acc_std = np.std(accs)
    lineas.append(f"  Accuracy promedio: {acc_mean:.4f} ({acc_mean*100:.2f}%)")
    lineas.append(f"  Accuracy std:      {acc_std:.4f} (+/- {2*acc_std:.4f})")
    lineas.append(f"  Accuracy por fold: {[f'{a:.4f}' for a in accs]}")
    lineas.append("")

    # --- Reporte por clase (sobre todas las predicciones) ---
    lineas.append("-" * 70)
    lineas.append("REPORTE POR CLASE (sobre todas las predicciones combinadas)")
    lineas.append("-" * 70)
    lineas.append("")

    # Calcular metricas por clase
    y_true_int = y_total.argmax(axis=1)
    y_pred_int = y_pred_total.argmax(axis=1)

    precision, recall, f1, support = precision_recall_fscore_support(
        y_true_int, y_pred_int, labels=range(NUM_CLASES), zero_division=0
    )

    lineas.append(f"  {'Clase':<20} {'Precision':<12} {'Recall':<12} "
                  f"{'F1-Score':<12} {'Muestras':<10}")
    lineas.append(f"  {'-'*66}")
    for i in range(NUM_CLASES):
        lineas.append(f"  {NOMBRES_GESTOS[i]:<20} {precision[i]:<12.4f} "
                      f"{recall[i]:<12.4f} {f1[i]:<12.4f} {support[i]:<10d}")

    # Promedios macro y weighted
    p_macro = np.mean(precision)
    r_macro = np.mean(recall)
    f1_macro = np.mean(f1)
    lineas.append(f"  {'-'*66}")
    lineas.append(f"  {'Macro avg':<20} {p_macro:<12.4f} {r_macro:<12.4f} "
                  f"{f1_macro:<12.4f} {support.sum():<10d}")

    # Classification report completo (sklearn)
    lineas.append("")
    lineas.append("-" * 70)
    lineas.append("CLASSIFICATION REPORT (sklearn)")
    lineas.append("-" * 70)
    lineas.append("")
    report = classification_report(
        y_true_int, y_pred_int,
        target_names=NOMBRES_GESTOS,
        digits=4,
        zero_division=0,
    )
    lineas.append(report)
    lineas.append("=" * 70)
    lineas.append("FIN DEL REPORTE")
    lineas.append("=" * 70)

    # --- Guardar TXT ---
    texto = "\n".join(lineas)
    ruta = os.path.join(output_dir, "metricas.txt")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(texto)
    print(f"[TEXTO] {ruta}")

    # --- Imprimir en consola ---
    print("\n" + texto)


# ============================================================
# ENTRENAMIENTO DE UN SOLO FOLD
# ============================================================
def entrenar_fold(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray,
    fold_idx: int,
    epochs: int,
    batch_size: int,
    lr: float,
) -> tuple:
    """
    Construye, entrena y evalua el modelo en un fold.
    Retorna (history, y_pred, metricas_dict).
    """
    print(f"\n{'='*60}")
    print(f"  FOLD {fold_idx + 1}")
    print(f"  Train: {X_train.shape[0]} | Val: {X_val.shape[0]}")
    print(f"{'='*60}")

    # Balance de clases en train
    clases, counts = np.unique(y_train.argmax(axis=1), return_counts=True)
    print(f"  Distribucion train: {dict(zip(clases, counts))}")

    modelo = construir_modelo(
        window_size=X_train.shape[1],
        num_features=X_train.shape[2],
        num_clases=NUM_CLASES,
    )
    modelo = compilar_modelo(modelo, lr=lr)
    modelo.summary()

    callbacks = [
        tf.keras.callbacks.EarlyStopping(
            monitor="val_loss",
            patience=15,
            restore_best_weights=True,
            verbose=0,
        ),
        tf.keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss",
            factor=0.5,
            patience=7,
            min_lr=1e-6,
            verbose=0,
        ),
    ]

    history = modelo.fit(
        X_train, y_train,
        validation_data=(X_val, y_val),
        epochs=epochs,
        batch_size=batch_size,
        callbacks=callbacks,
        verbose=0,
    )

    # Evaluacion
    loss, accuracy, auc = modelo.evaluate(X_val, y_val, verbose=0)
    y_pred = modelo.predict(X_val, verbose=0)

    print(f"  Resultados Fold {fold_idx + 1}:")
    print(f"    Loss:     {loss:.4f}")
    print(f"    Accuracy: {accuracy:.4f} ({accuracy*100:.2f}%)")
    print(f"    AUC:      {auc:.4f}")
    print(f"    Epochs:   {len(history.history['loss'])}")

    metricas = {
        "loss": loss,
        "accuracy": accuracy,
        "auc": auc,
        "epochs": len(history.history["loss"]),
    }

    # Liberar memoria (importante con k-fold en datasets grandes)
    del modelo
    tf.keras.backend.clear_session()

    return history, y_pred, metricas


# ============================================================
# FUNCION PRINCIPAL
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="Entrenar CNN-BiLSTM-Attention con validacion cruzada "
                    "sobre NinaPro DB5"
    )
    parser.add_argument(
        "--mat", type=str, required=True,
        help="Directorio con archivos .mat de NinaPro DB5"
    )
    parser.add_argument(
        "--epochs", type=int, default=100,
        help="Maximo de epocas por fold (default: 100)"
    )
    parser.add_argument(
        "--batch_size", type=int, default=32,
        help="Tamano del batch (default: 32)"
    )
    parser.add_argument(
        "--lr", type=float, default=1e-3,
        help="Tasa de aprendizaje inicial (default: 1e-3)"
    )
    parser.add_argument(
        "--folds", type=int, default=5,
        help="Numero de folds para validacion cruzada (default: 5)"
    )
    parser.add_argument(
        "--output_dir", type=str, default=RESULTADOS_DIR,
        help="Directorio de salida para resultados (default: resultados_preliminares/)"
    )
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    # ============================================================
    # PASO 1: CARGAR Y PREPROCESAR DATASET COMPLETO
    # ============================================================
    print("\n" + "=" * 60)
    print("PASO 1: Cargando y preprocesando NinaPro DB5")
    print("=" * 60)

    X, y = cargar_procesar_dataset(args.mat)

    n_total = X.shape[0]
    print(f"\nDataset total: {n_total} ventanas de "
          f"{X.shape[1]} pasos x {X.shape[2]} canales")

    # ============================================================
    # PASO 2: VALIDACION CRUZADA ESTRATIFICADA (K-FOLD)
    # ============================================================
    print("\n" + "=" * 60)
    print(f"PASO 2: Validacion cruzada estratificada (k={args.folds})")
    print("=" * 60)

    kfold = StratifiedKFold(
        n_splits=args.folds,
        shuffle=True,
        random_state=42,
    )

    # Obtener etiquetas enteras para estratificacion
    y_int = y.argmax(axis=1)

    historiales = []
    matrices_confusion = []
    metricas_por_fold = []
    todas_y_true = []
    todas_y_pred = []

    for fold_idx, (idx_train, idx_val) in enumerate(
        kfold.split(X, y_int)
    ):
        X_train, X_val = X[idx_train], X[idx_val]
        y_train, y_val = y[idx_train], y[idx_val]

        # Entrenar fold
        history, y_pred, metricas = entrenar_fold(
            X_train, y_train,
            X_val, y_val,
            fold_idx,
            args.epochs,
            args.batch_size,
            args.lr,
        )

        # Acumular resultados
        historiales.append(history)
        metricas_por_fold.append(metricas)

        # Matriz de confusion (conteos, no normalizada aun)
        cm = confusion_matrix(
            y_val.argmax(axis=1),
            y_pred.argmax(axis=1),
            labels=range(NUM_CLASES),
        )
        matrices_confusion.append(cm)

        todas_y_true.append(y_val)
        todas_y_pred.append(y_pred)

    # Concatenar todas las predicciones
    y_total_true = np.concatenate(todas_y_true, axis=0)
    y_total_pred = np.concatenate(todas_y_pred, axis=0)

    # ============================================================
    # PASO 3: GENERAR RESULTADOS
    # ============================================================
    print("\n" + "=" * 60)
    print("PASO 3: Generando resultados en", args.output_dir)
    print("=" * 60)

    # 3a. Curvas de entrenamiento
    print("\n--- Curvas de entrenamiento ---")
    graficar_historial_kfold(historiales, args.output_dir)

    # 3b. Matriz de confusion promediada
    print("\n--- Matriz de confusion ---")
    graficar_matriz_confusion(matrices_confusion, args.output_dir)

    # 3c. Reporte de metricas
    print("\n--- Reporte de metricas ---")
    guardar_metricas(metricas_por_fold, y_total_true, y_total_pred, args.output_dir)

    # ============================================================
    # RESUMEN FINAL
    # ============================================================
    accs = [m["accuracy"] for m in metricas_por_fold]
    print("\n" + "=" * 60)
    print("RESUMEN FINAL - VALIDACION CRUZADA")
    print("=" * 60)
    print(f"  Accuracy por fold: {[f'{a*100:.2f}%' for a in accs]}")
    print(f"  Accuracy promedio: {np.mean(accs)*100:.2f}%")
    print(f"  Desviacion std:    {np.std(accs)*100:.2f}%")
    print(f"  Resultados en:     {os.path.abspath(args.output_dir)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
