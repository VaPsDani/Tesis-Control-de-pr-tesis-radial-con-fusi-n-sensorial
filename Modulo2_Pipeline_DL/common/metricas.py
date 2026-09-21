"""
metricas.py - Metricas y figuras comunes a todos los experimentos
==================================================================
Protesis transradial - Codigo compartido

Reune lo que antes estaba duplicado entre la ruta de NinaPro y los
experimentos sobre el dataset publico de LMG: el calculo de metricas de
un vector de predicciones, el desglose por sujeto y las dos figuras que
acompanan a toda validacion cruzada.

AGNOSTICO DEL DATASET: los nombres de las clases entran por parametro.
"""

import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from sklearn.metrics import (accuracy_score, confusion_matrix, f1_score,
                             precision_recall_fscore_support)

RESULTADOS_DIR = "resultados_cv"


def nombres_por_defecto(num_clases: int):
    return [f"clase_{i}" for i in range(num_clases)]


def metricas(y_true, y_pred, nombres_clases=None) -> dict:
    """
    Exactitud, F1 macro y F1 por clase de un vector de predicciones.

    Es la funcion que usaban los experimentos del dataset publico de LMG,
    traida aqui para que todos midan igual.
    """
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)
    n_clases = int(max(y_true.max(), y_pred.max())) + 1
    nombres = nombres_clases or nombres_por_defecto(n_clases)
    f1_clases = f1_score(y_true, y_pred, average=None,
                         labels=list(range(n_clases)), zero_division=0)
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "f1_macro": float(f1_score(y_true, y_pred, average="macro",
                                   zero_division=0)),
        "f1_por_clase": {nombres[i]: float(f1_clases[i])
                         for i in range(min(len(nombres), n_clases))},
        "n": int(len(y_true)),
    }


def por_sujeto(y_true, y_pred, sujetos, nombres_clases=None) -> dict:
    """
    Metricas de cada sujeto por separado.

    Hace falta para los contrastes pareados: con 5 pliegues y 10 sujetos,
    comparar por pliegue deja n = 5, y por sujeto deja n = 10.
    """
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)
    sujetos = np.asarray(sujetos)
    salida = {}
    for s in np.unique(sujetos):
        m = sujetos == s
        salida[int(s)] = metricas(y_true[m], y_pred[m], nombres_clases)
    return salida


def graficar_historial_kfold(historiales: list, etiqueta: str,
                             output_dir: str = RESULTADOS_DIR):
    """
    Grafica las curvas de Loss y Accuracy de los k pliegues.

    Cada pliegue puede tener distinta longitud (EarlyStopping). Se truncan
    al minimo comun y se grafica: lineas por pliegue, promedio y banda de
    desviacion estandar.
    """
    os.makedirs(output_dir, exist_ok=True)

    train_losses = [h.history["loss"] for h in historiales]
    val_losses = [h.history["val_loss"] for h in historiales]
    train_accs = [h.history["accuracy"] for h in historiales]
    val_accs = [h.history["val_accuracy"] for h in historiales]

    min_epochs = min(len(l) for l in train_losses)
    train_losses = [l[:min_epochs] for l in train_losses]
    val_losses = [l[:min_epochs] for l in val_losses]
    train_accs = [l[:min_epochs] for l in train_accs]
    val_accs = [l[:min_epochs] for l in val_accs]

    epochs = np.arange(1, min_epochs + 1)
    k = len(historiales)
    colores = plt.cm.tab10(np.linspace(0, 1, k))

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    for i in range(k):
        ax1.plot(epochs, train_losses[i], color=colores[i], alpha=0.3, linewidth=1)
        ax1.plot(epochs, val_losses[i], color=colores[i], alpha=0.3, linewidth=1,
                 linestyle="--")

    train_mean, train_std = np.mean(train_losses, axis=0), np.std(train_losses, axis=0)
    val_mean, val_std = np.mean(val_losses, axis=0), np.std(val_losses, axis=0)

    ax1.plot(epochs, train_mean, color="blue", linewidth=2, label="Train (prom)")
    ax1.fill_between(epochs, train_mean - train_std, train_mean + train_std,
                     color="blue", alpha=0.1)
    ax1.plot(epochs, val_mean, color="red", linewidth=2, label="Val (prom)",
             linestyle="--")
    ax1.fill_between(epochs, val_mean - val_std, val_mean + val_std,
                     color="red", alpha=0.1)
    ax1.set_title(f"Perdida - {k}-Fold CV ({etiqueta})")
    ax1.set_xlabel("Epoca")
    ax1.set_ylabel("Loss")
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    for i in range(k):
        ax2.plot(epochs, train_accs[i], color=colores[i], alpha=0.3, linewidth=1)
        ax2.plot(epochs, val_accs[i], color=colores[i], alpha=0.3, linewidth=1,
                 linestyle="--")

    train_mean, train_std = np.mean(train_accs, axis=0), np.std(train_accs, axis=0)
    val_mean, val_std = np.mean(val_accs, axis=0), np.std(val_accs, axis=0)

    ax2.plot(epochs, train_mean, color="blue", linewidth=2, label="Train (prom)")
    ax2.fill_between(epochs, train_mean - train_std, train_mean + train_std,
                     color="blue", alpha=0.1)
    ax2.plot(epochs, val_mean, color="red", linewidth=2, label="Val (prom)",
             linestyle="--")
    ax2.fill_between(epochs, val_mean - val_std, val_mean + val_std,
                     color="red", alpha=0.1)
    ax2.set_title(f"Exactitud - {k}-Fold CV ({etiqueta})")
    ax2.set_xlabel("Epoca")
    ax2.set_ylabel("Accuracy")
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    ruta = os.path.join(output_dir, f"historial_entrenamiento_{etiqueta}.png")
    plt.savefig(ruta, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"[GRAFICA] {ruta}")
    return ruta


def graficar_matriz_confusion(cm_total: np.ndarray, etiqueta: str,
                              output_dir: str = RESULTADOS_DIR,
                              nombres_clases=None):
    """
    Grafica la matriz de confusion agregada sobre los k pliegues,
    normalizada por fila (recall por clase real).
    """
    os.makedirs(output_dir, exist_ok=True)

    n_clases = cm_total.shape[0]
    nombres = nombres_clases or nombres_por_defecto(n_clases)
    cm_norm = cm_total.astype("float64") / cm_total.sum(axis=1, keepdims=True)
    cm_norm = np.nan_to_num(cm_norm, nan=0.0)

    fig, ax = plt.subplots(figsize=(7, 6))
    im = ax.imshow(cm_norm, cmap="Blues", vmin=0, vmax=1)

    for i in range(n_clases):
        for j in range(n_clases):
            valor = cm_norm[i, j]
            texto = f"{valor:.2f}\n({int(cm_total[i, j])})"
            color_texto = "white" if valor > 0.5 else "black"
            ax.text(j, i, texto, ha="center", va="center", fontsize=9,
                    color=color_texto)

    ax.set_xticks(range(n_clases))
    ax.set_yticks(range(n_clases))
    ax.set_xticklabels(nombres, rotation=45, ha="right", fontsize=10)
    ax.set_yticklabels(nombres, fontsize=10)
    ax.set_xlabel("Predicho", fontsize=11)
    ax.set_ylabel("Real", fontsize=11)
    ax.set_title(f"Matriz de Confusion normalizada - agregada 5 pliegues\n"
                 f"({etiqueta})  Valor: proporcion | (conteo total)",
                 fontsize=11)

    plt.colorbar(im, shrink=0.8)
    plt.tight_layout()
    ruta = os.path.join(output_dir, f"matriz_confusion_{etiqueta}.png")
    plt.savefig(ruta, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"[GRAFICA] {ruta}")
    return ruta



def ruta_sin_sobrescribir(directorio: str, base: str, ext: str) -> str:
    """
    Devuelve una ruta libre: si '<base><ext>' existe, prueba '<base>_2',
    '<base>_3', etc. Nunca sobrescribe resultados anteriores.
    """
    ruta = os.path.join(directorio, f"{base}{ext}")
    if not os.path.exists(ruta):
        return ruta
    i = 2
    while True:
        ruta = os.path.join(directorio, f"{base}_{i}{ext}")
        if not os.path.exists(ruta):
            return ruta
        i += 1


