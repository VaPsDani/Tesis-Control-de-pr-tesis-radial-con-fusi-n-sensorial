"""
entrenamiento_cv.py - Validacion cruzada por grupos sobre NinaPro DB5
======================================================================
Protesis transradial - Validacion con dataset publico multimodal

ALCANCE:
  Ruta de VALIDACION del pipeline (senales sEMG de NinaPro DB5, entrada
  (40, 8)). La ruta de PRODUCCION sobre el hardware fisico (senales LMG,
  entrada (20, 9)) vive en 'entrenamiento.py' y no se ve afectada por
  este archivo. Ambas comparten la arquitectura de 'modelo.py'.

FLUJO:
  1. Cargar y preprocesar NinaPro DB5 (preprocesamiento_ninapro.py)
  2. Autotest del verificador de fuga entre sujetos
  3. Particion por grupos: repeticion (linea base) o sujeto (particion.py)
  4. Entrenar CNN-BiLSTM-Attention en cada pliegue
  5. Exportar metricas por pliegue, agregadas y comparadas con la linea base

ESQUEMAS DE AGRUPAMIENTO:
  --agrupamiento repeticion : linea base SI2 (intra-sujeto), 82.98% +/- 2.85%
  --agrupamiento sujeto     : inter-sujeto, 2 sujetos completos por pliegue

  Todo lo demas (arquitectura, hiperparametros, preprocesamiento, ventana,
  stride, submuestreo de Rest, k=5) es identico entre ambos esquemas: el
  criterio de agrupamiento es el unico grado de libertad.

USO:
  python entrenamiento_cv.py --mat ./NinaPro_DB5/ --agrupamiento sujeto
  python entrenamiento_cv.py --mat ./NinaPro_DB5/ --agrupamiento repeticion
"""

import argparse
import json
import os
import time
import warnings
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import tensorflow as tf
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    f1_score,
    precision_recall_fscore_support,
)

from modelo import construir_modelo, compilar_modelo
from preprocesamiento_ninapro import (
    cargar_procesar_dataset,
    NOMBRES_GESTOS,
    NUM_CLASES,
    VENTANA_SAMPLES,
    CANALES_TOTAL,
)
from particion import (
    autotest_verificador,
    describir_pliegue,
    formatear_pliegue,
    generar_particiones,
)

warnings.filterwarnings("ignore")

RESULTADOS_DIR = "resultados_cv"

# Suavizado de etiquetas con el que se obtuvo la linea base de 82.98%.
# Cambiarlo rompe la comparabilidad entre esquemas de particion.
LABEL_SMOOTHING = 0.1

# ------------------------------------------------------------
# LINEA BASE SI2 - GroupKFold agrupado por REPETICION
# Transcrita de resultados_preliminares/metricas.txt en el commit
# af6a26a, preservado bajo el tag 'si2-groupkfold-repeticion'.
# ------------------------------------------------------------
LINEA_BASE_SI2 = {
    "esquema": "GroupKFold k=5 agrupado por repeticion",
    "origen": "tag si2-groupkfold-repeticion (commit af6a26a), "
              "resultados_preliminares/metricas.txt",
    "accuracy_por_fold": [0.7936, 0.8275, 0.8438, 0.8756, 0.8087],
    "loss_por_fold": [0.9132, 0.7995, 0.7884, 0.7062, 0.8575],
    "auc_por_fold": [0.9457, 0.9660, 0.9703, 0.9774, 0.9595],
    "epochs_por_fold": [30, 41, 25, 71, 23],
    "accuracy_media": 0.8298,
    "accuracy_std": 0.0285,
    "auc_media": 0.9638,
    "f1_por_clase": {
        "Rest": 0.8875,
        "Pinch": 0.8352,
        "Tripod": 0.8554,
        "Power": 0.7943,
        "Finger_Ext": 0.7775,
    },
    "f1_macro": 0.8300,
    "n_ventanas_evaluadas": 54346,
}


def augmentar_muestra(X, y):
    """
    Data augmentation ligero sobre cada ventana de entrenamiento.

    Identico a la linea base: ruido gaussiano, escalado global y
    desplazamiento temporal de +/- 1 muestra. Se aplica solo al conjunto
    de entrenamiento, nunca al de validacion.
    """
    noise = tf.random.normal(tf.shape(X), mean=0.0, stddev=0.02)
    X = X + noise
    factor = tf.random.uniform([], minval=0.95, maxval=1.05)
    X = X * factor
    shift = tf.random.uniform([], minval=-1, maxval=2, dtype=tf.int32)
    X = tf.roll(X, shift=shift, axis=0)
    return X, y


# ============================================================
# CARGA CON CACHE OPCIONAL
# ============================================================
def cargar_dataset(ruta_mat: str, cache: str = None):
    """Carga el dataset, con cache opcional en .npz para iterar rapido."""
    if cache and os.path.exists(cache):
        print(f"[CACHE] Leyendo dataset preprocesado de {cache}")
        d = np.load(cache)
        return d["X"], d["y"], d["grupos"], d["sujetos"]

    X, y, grupos, sujetos = cargar_procesar_dataset(ruta_mat)

    if cache:
        print(f"[CACHE] Guardando dataset preprocesado en {cache}")
        np.savez_compressed(cache, X=X, y=y, grupos=grupos, sujetos=sujetos)
    return X, y, grupos, sujetos


# ============================================================
# GRAFICAS DE ENTRENAMIENTO
# ============================================================
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
                              output_dir: str = RESULTADOS_DIR):
    """
    Grafica la matriz de confusion agregada sobre los k pliegues,
    normalizada por fila (recall por clase real).
    """
    os.makedirs(output_dir, exist_ok=True)

    cm_norm = cm_total.astype("float64") / cm_total.sum(axis=1, keepdims=True)
    cm_norm = np.nan_to_num(cm_norm, nan=0.0)

    fig, ax = plt.subplots(figsize=(7, 6))
    im = ax.imshow(cm_norm, cmap="Blues", vmin=0, vmax=1)

    for i in range(NUM_CLASES):
        for j in range(NUM_CLASES):
            valor = cm_norm[i, j]
            texto = f"{valor:.2f}\n({int(cm_total[i, j])})"
            color_texto = "white" if valor > 0.5 else "black"
            ax.text(j, i, texto, ha="center", va="center", fontsize=9,
                    color=color_texto)

    ax.set_xticks(range(NUM_CLASES))
    ax.set_yticks(range(NUM_CLASES))
    ax.set_xticklabels(NOMBRES_GESTOS, rotation=45, ha="right", fontsize=10)
    ax.set_yticklabels(NOMBRES_GESTOS, fontsize=10)
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


# ============================================================
# ENTRENAMIENTO DE UN SOLO PLIEGUE
# ============================================================
def entrenar_pliegue(X_train, y_train, X_val, y_val, fold_idx,
                     epochs, batch_size, lr):
    """
    Construye, entrena y evalua el modelo en un pliegue.
    Retorna (history, y_pred, metricas_dict).
    """
    print(f"\n{'='*60}")
    print(f"  PLIEGUE {fold_idx + 1}")
    print(f"  Train: {X_train.shape[0]} | Val: {X_val.shape[0]}")
    print(f"{'='*60}")

    clases, counts = np.unique(y_train.argmax(axis=1), return_counts=True)
    print(f"  Distribucion train: {dict(zip(clases.tolist(), counts.tolist()))}")

    modelo = construir_modelo(
        window_size=X_train.shape[1],
        num_features=X_train.shape[2],
        num_clases=NUM_CLASES,
    )
    modelo = compilar_modelo(modelo, lr=lr, label_smoothing=LABEL_SMOOTHING)

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

    train_ds = tf.data.Dataset.from_tensor_slices((X_train, y_train))
    train_ds = train_ds.map(augmentar_muestra, num_parallel_calls=tf.data.AUTOTUNE)
    train_ds = train_ds.shuffle(1024).batch(batch_size).prefetch(tf.data.AUTOTUNE)
    val_ds = tf.data.Dataset.from_tensor_slices((X_val, y_val))
    val_ds = val_ds.batch(batch_size).prefetch(tf.data.AUTOTUNE)

    t0 = time.time()
    history = modelo.fit(
        train_ds,
        validation_data=val_ds,
        epochs=epochs,
        callbacks=callbacks,
        verbose=0,
    )
    duracion = time.time() - t0

    loss, accuracy, auc = modelo.evaluate(X_val, y_val, verbose=0)
    y_pred = modelo.predict(X_val, verbose=0)

    y_true_int = y_val.argmax(axis=1)
    y_pred_int = y_pred.argmax(axis=1)
    f1_macro = f1_score(y_true_int, y_pred_int, average="macro", zero_division=0)
    f1_clases = f1_score(
        y_true_int, y_pred_int, average=None,
        labels=range(NUM_CLASES), zero_division=0,
    )

    n_epocas = len(history.history["loss"])
    # EarlyStopping con restore_best_weights: la mejor epoca es la que
    # quedo en los pesos; se recupera del minimo de val_loss.
    mejor_epoca = int(np.argmin(history.history["val_loss"])) + 1
    paro_temprano = n_epocas < epochs

    print(f"  Resultados Pliegue {fold_idx + 1}:")
    print(f"    Loss:       {loss:.4f}")
    print(f"    Accuracy:   {accuracy:.4f} ({accuracy*100:.2f}%)")
    print(f"    AUC:        {auc:.4f}")
    print(f"    F1 macro:   {f1_macro:.4f}")
    print(f"    Epocas:     {n_epocas} (mejor: {mejor_epoca}, "
          f"early stopping: {'si' if paro_temprano else 'no, tope de epocas'})")
    print(f"    Duracion:   {duracion/60:.1f} min")

    metricas = {
        "loss": float(loss),
        "accuracy": float(accuracy),
        "auc": float(auc),
        "f1_macro": float(f1_macro),
        "f1_por_clase": {
            NOMBRES_GESTOS[i]: float(f1_clases[i]) for i in range(NUM_CLASES)
        },
        "epochs": int(n_epocas),
        "mejor_epoca": mejor_epoca,
        "detuvo_por_early_stopping": bool(paro_temprano),
        "duracion_seg": round(duracion, 1),
    }

    del modelo
    tf.keras.backend.clear_session()

    return history, y_pred, metricas


# ============================================================
# REPORTE
# ============================================================
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


def construir_reporte(args, etiqueta, descripciones, metricas_por_fold,
                      y_true_total, y_pred_total, cm_total, dataset_info):
    """Arma el diccionario completo de resultados que se serializa a JSON."""
    accs = [m["accuracy"] for m in metricas_por_fold]
    f1s = [m["f1_macro"] for m in metricas_por_fold]
    aucs = [m["auc"] for m in metricas_por_fold]
    losses = [m["loss"] for m in metricas_por_fold]

    y_true_int = y_true_total.argmax(axis=1)
    y_pred_int = y_pred_total.argmax(axis=1)
    precision, recall, f1, support = precision_recall_fscore_support(
        y_true_int, y_pred_int, labels=range(NUM_CLASES), zero_division=0
    )

    cm_norm = cm_total.astype("float64") / cm_total.sum(axis=1, keepdims=True)
    cm_norm = np.nan_to_num(cm_norm, nan=0.0)

    reporte = {
        "esquema": {
            "etiqueta": etiqueta,
            "agrupamiento": args.agrupamiento,
            "validador": ("StratifiedGroupKFold" if args.estratificado
                          else "GroupKFold"),
            "k": args.folds,
        },
        "generado": datetime.now().isoformat(timespec="seconds"),
        "config": {
            "optimizador": "Adam",
            "learning_rate": args.lr,
            "batch_size": args.batch_size,
            "epochs_max": args.epochs,
            "early_stopping_patience": 15,
            "reduce_lr_factor": 0.5,
            "reduce_lr_patience": 7,
            "dropout": 0.5,
            "l2": 1e-4,
            "label_smoothing": LABEL_SMOOTHING,
            "forma_entrada": [int(VENTANA_SAMPLES), int(CANALES_TOTAL)],
            "ventana_ms": 200,
            "stride_ms": 20,
            "tasa_hz": 200,
            "data_augmentation": "ruido N(0,0.02) + escala U(0.95,1.05) "
                                 "+ roll temporal +/-1",
        },
        "dataset": dataset_info,
        "pliegues": [
            {**descripciones[i], **metricas_por_fold[i]}
            for i in range(len(metricas_por_fold))
        ],
        "agregado": {
            "accuracy_media": float(np.mean(accs)),
            "accuracy_std": float(np.std(accs)),
            "accuracy_por_fold": [float(a) for a in accs],
            "f1_macro_media": float(np.mean(f1s)),
            "f1_macro_std": float(np.std(f1s)),
            "f1_macro_por_fold": [float(v) for v in f1s],
            "auc_media": float(np.mean(aucs)),
            "auc_std": float(np.std(aucs)),
            "auc_por_fold": [float(v) for v in aucs],
            "loss_media": float(np.mean(losses)),
            "loss_std": float(np.std(losses)),
            "loss_por_fold": [float(v) for v in losses],
            "epochs_por_fold": [m["epochs"] for m in metricas_por_fold],
            "mejor_epoca_por_fold": [m["mejor_epoca"] for m in metricas_por_fold],
        },
        "por_clase_global": {
            NOMBRES_GESTOS[i]: {
                "precision": float(precision[i]),
                "recall": float(recall[i]),
                "f1": float(f1[i]),
                "support": int(support[i]),
            }
            for i in range(NUM_CLASES)
        },
        "matriz_confusion_conteos": cm_total.astype(int).tolist(),
        "matriz_confusion_normalizada": np.round(cm_norm, 4).tolist(),
        "clases": NOMBRES_GESTOS,
        "linea_base_si2": LINEA_BASE_SI2,
    }
    return reporte


def texto_reporte(reporte: dict) -> str:
    """Renderiza el reporte como texto legible, incluida la comparativa."""
    L = []
    esq = reporte["esquema"]
    ag = reporte["agregado"]
    base = reporte["linea_base_si2"]

    L.append("=" * 78)
    L.append("REPORTE DE METRICAS - VALIDACION CRUZADA")
    L.append(f"Dataset: NinaPro DB5 ({reporte['dataset']['n_sujetos']} sujetos, "
             f"{reporte['dataset']['n_archivos_mat']} archivos .mat)")
    L.append(f"Modelo:  CNN-BiLSTM-Attention, entrada "
             f"{tuple(reporte['config']['forma_entrada'])}")
    L.append(f"Esquema: {esq['validador']} k={esq['k']} agrupado por "
             f"{esq['agrupamiento'].upper()}")
    L.append(f"Clases:  {', '.join(reporte['clases'])}")
    L.append(f"Generado: {reporte['generado']}")
    L.append("=" * 78)
    L.append("")

    # --- Composicion de pliegues ---
    L.append("-" * 78)
    L.append("COMPOSICION DE LOS PLIEGUES")
    L.append("-" * 78)
    for p in reporte["pliegues"]:
        L.append(formatear_pliegue(p, esq["agrupamiento"]))
        L.append("")

    # --- Metricas por pliegue ---
    L.append("-" * 78)
    L.append("RESULTADOS POR PLIEGUE")
    L.append("-" * 78)
    L.append(f"  {'Pliegue':<9}{'Accuracy':>11}{'F1 macro':>11}{'AUC':>10}"
             f"{'Loss':>10}{'Epocas':>9}{'Mejor':>8}")
    L.append(f"  {'-'*66}")
    for p in reporte["pliegues"]:
        L.append(f"  {p['fold']:<9}{p['accuracy']:>11.4f}{p['f1_macro']:>11.4f}"
                 f"{p['auc']:>10.4f}{p['loss']:>10.4f}{p['epochs']:>9}"
                 f"{p['mejor_epoca']:>8}")
    L.append(f"  {'-'*66}")
    L.append(f"  {'Media':<9}{ag['accuracy_media']:>11.4f}"
             f"{ag['f1_macro_media']:>11.4f}{ag['auc_media']:>10.4f}"
             f"{ag['loss_media']:>10.4f}")
    L.append(f"  {'Std':<9}{ag['accuracy_std']:>11.4f}"
             f"{ag['f1_macro_std']:>11.4f}{ag['auc_std']:>10.4f}"
             f"{ag['loss_std']:>10.4f}")
    L.append("")
    L.append(f"  Accuracy: {ag['accuracy_media']*100:.2f}% +/- "
             f"{ag['accuracy_std']*100:.2f}%")
    L.append("")

    # --- Por clase ---
    L.append("-" * 78)
    L.append("METRICAS POR CLASE (predicciones combinadas de los 5 pliegues)")
    L.append("-" * 78)
    L.append(f"  {'Clase':<14}{'Precision':>12}{'Recall':>12}{'F1':>12}"
             f"{'Muestras':>12}")
    L.append(f"  {'-'*62}")
    for clase, m in reporte["por_clase_global"].items():
        L.append(f"  {clase:<14}{m['precision']:>12.4f}{m['recall']:>12.4f}"
                 f"{m['f1']:>12.4f}{m['support']:>12}")
    L.append("")

    # --- Matriz de confusion ---
    L.append("-" * 78)
    L.append("MATRIZ DE CONFUSION NORMALIZADA (agregada, filas = clase real)")
    L.append("-" * 78)
    cabecera = "  " + " " * 14 + "".join(f"{c[:10]:>11}" for c in reporte["clases"])
    L.append(cabecera)
    for i, clase in enumerate(reporte["clases"]):
        fila = reporte["matriz_confusion_normalizada"][i]
        L.append(f"  {clase:<14}" + "".join(f"{v:>11.4f}" for v in fila))
    L.append("")

    # --- Comparativa ---
    L.append("=" * 78)
    L.append("COMPARATIVA CONTRA LA LINEA BASE (agrupamiento por repeticion)")
    L.append(f"Fuente linea base: {base['origen']}")
    L.append("=" * 78)
    L.append("")
    L.append(f"  {'Metrica':<22}{'por REPETICION':>18}{'por SUJETO':>18}"
             f"{'Delta':>14}")
    L.append(f"  {'-'*72}")

    filas = [
        ("Accuracy media", base["accuracy_media"], ag["accuracy_media"], "{:.4f}"),
        ("Accuracy std", base["accuracy_std"], ag["accuracy_std"], "{:.4f}"),
        ("AUC media", base["auc_media"], ag["auc_media"], "{:.4f}"),
        ("F1 macro", base["f1_macro"], ag["f1_macro_media"], "{:.4f}"),
    ]
    for nombre, v_base, v_nuevo, fmt in filas:
        delta = v_nuevo - v_base
        L.append(f"  {nombre:<22}{fmt.format(v_base):>18}"
                 f"{fmt.format(v_nuevo):>18}{delta:>+14.4f}")

    L.append("")
    L.append(f"  {'F1 por clase':<22}{'por REPETICION':>18}{'por SUJETO':>18}"
             f"{'Delta':>14}")
    L.append(f"  {'-'*72}")
    for clase in reporte["clases"]:
        v_base = base["f1_por_clase"][clase]
        v_nuevo = reporte["por_clase_global"][clase]["f1"]
        L.append(f"  {clase:<22}{v_base:>18.4f}{v_nuevo:>18.4f}"
                 f"{v_nuevo - v_base:>+14.4f}")

    L.append("")
    L.append(f"  {'Accuracy por pliegue':<22}")
    L.append(f"    por REPETICION: "
             f"{[f'{a*100:.2f}%' for a in base['accuracy_por_fold']]}")
    L.append(f"    por SUJETO:     "
             f"{[f'{a*100:.2f}%' for a in ag['accuracy_por_fold']]}")
    L.append("")
    L.append(f"  {'Epocas hasta early stopping':<30}")
    L.append(f"    por REPETICION: {base['epochs_por_fold']}")
    L.append(f"    por SUJETO:     {ag['epochs_por_fold']}")
    L.append("")
    L.append("  NOTA: los dos esquemas comparten arquitectura, hiperparametros,")
    L.append("  preprocesamiento, ventana, stride, submuestreo de Rest y k=5.")
    L.append("  El unico grado de libertad es el criterio de agrupamiento.")
    L.append("  La particion por repeticion deja los 10 sujetos en train Y en")
    L.append("  test de cada pliegue (metrica intra-sujeto); la particion por")
    L.append("  sujeto reserva 2 sujetos completos por pliegue (inter-sujeto).")
    L.append("=" * 78)

    return "\n".join(L)


# ============================================================
# FUNCION PRINCIPAL
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="Validacion cruzada por grupos de CNN-BiLSTM-Attention "
                    "sobre NinaPro DB5"
    )
    parser.add_argument("--mat", type=str, required=True,
                        help="Directorio con archivos .mat de NinaPro DB5")
    parser.add_argument("--agrupamiento", type=str, default="sujeto",
                        choices=["sujeto", "repeticion"],
                        help="Criterio de agrupamiento del GroupKFold "
                             "(default: sujeto)")
    parser.add_argument("--estratificado", action="store_true",
                        help="Usar StratifiedGroupKFold en lugar de GroupKFold")
    parser.add_argument("--epochs", type=int, default=100,
                        help="Maximo de epocas por pliegue (default: 100)")
    parser.add_argument("--batch_size", type=int, default=32,
                        help="Tamano del batch (default: 32)")
    parser.add_argument("--lr", type=float, default=1e-3,
                        help="Tasa de aprendizaje inicial (default: 1e-3)")
    parser.add_argument("--folds", type=int, default=5,
                        help="Numero de pliegues (default: 5)")
    parser.add_argument("--cache", type=str, default=None,
                        help="Ruta .npz para cachear el dataset preprocesado")
    parser.add_argument("--output_dir", type=str, default=RESULTADOS_DIR,
                        help=f"Directorio de salida (default: {RESULTADOS_DIR}/)")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    validador = "stratifiedgroupkfold" if args.estratificado else "groupkfold"
    etiqueta = f"{validador}_{args.agrupamiento}"

    # ========== 1. DATASET ==========
    print("\n" + "=" * 60)
    print("PASO 1: Cargando y preprocesando NinaPro DB5")
    print("=" * 60)

    X, y, grupos_rep, sujetos = cargar_dataset(args.mat, args.cache)
    y_int = y.argmax(axis=1)

    dataset_info = {
        "n_ventanas": int(X.shape[0]),
        "forma_ventana": [int(X.shape[1]), int(X.shape[2])],
        "n_sujetos": int(len(np.unique(sujetos))),
        "sujetos": sorted(np.unique(sujetos).tolist()),
        "n_archivos_mat": 30,
        "repeticiones": sorted(np.unique(grupos_rep).tolist()),
        "ventanas_por_sujeto": {
            str(s): int((sujetos == s).sum())
            for s in sorted(np.unique(sujetos).tolist())
        },
        "distribucion_clases": {
            NOMBRES_GESTOS[c]: int((y_int == c).sum())
            for c in range(NUM_CLASES)
        },
    }

    print(f"\nDataset total: {X.shape[0]} ventanas de "
          f"{X.shape[1]} pasos x {X.shape[2]} canales")
    print(f"Sujetos: {dataset_info['sujetos']}")
    print(f"Repeticiones: {dataset_info['repeticiones']}")

    # ========== 2. AUTOTEST DEL VERIFICADOR ==========
    print("\n" + "=" * 60)
    print("PASO 2: Autotest del verificador de fuga entre sujetos")
    print("=" * 60)
    print(autotest_verificador(sujetos))

    # ========== 3. PARTICION ==========
    print("\n" + "=" * 60)
    print(f"PASO 3: {'StratifiedGroupKFold' if args.estratificado else 'GroupKFold'}"
          f" (k={args.folds}) agrupado por {args.agrupamiento.upper()}")
    print("=" * 60)

    particiones = generar_particiones(
        X, y_int, grupos_rep, sujetos,
        agrupamiento=args.agrupamiento,
        n_splits=args.folds,
        estratificado=args.estratificado,
    )

    descripciones = []
    for i, (idx_tr, idx_te) in enumerate(particiones):
        d = describir_pliegue(i, idx_tr, idx_te, y_int, sujetos,
                              grupos_rep, NOMBRES_GESTOS)
        descripciones.append(d)
        print(formatear_pliegue(d, args.agrupamiento))

    # ========== 4. ENTRENAMIENTO ==========
    print("\n" + "=" * 60)
    print("PASO 4: Entrenando")
    print("=" * 60)

    historiales = []
    metricas_por_fold = []
    cm_total = np.zeros((NUM_CLASES, NUM_CLASES), dtype=np.int64)
    todas_y_true = []
    todas_y_pred = []

    for fold_idx, (idx_train, idx_val) in enumerate(particiones):
        X_train, X_val = X[idx_train], X[idx_val]
        y_train, y_val = y[idx_train], y[idx_val]

        history, y_pred, metricas = entrenar_pliegue(
            X_train, y_train, X_val, y_val, fold_idx,
            args.epochs, args.batch_size, args.lr,
        )

        historiales.append(history)
        metricas_por_fold.append(metricas)

        cm_total += confusion_matrix(
            y_val.argmax(axis=1), y_pred.argmax(axis=1),
            labels=range(NUM_CLASES),
        )
        todas_y_true.append(y_val)
        todas_y_pred.append(y_pred)

    y_true_total = np.concatenate(todas_y_true, axis=0)
    y_pred_total = np.concatenate(todas_y_pred, axis=0)

    # ========== 5. REPORTE ==========
    print("\n" + "=" * 60)
    print("PASO 5: Generando resultados en", args.output_dir)
    print("=" * 60)

    graficar_historial_kfold(historiales, etiqueta, args.output_dir)
    graficar_matriz_confusion(cm_total, etiqueta, args.output_dir)

    reporte = construir_reporte(
        args, etiqueta, descripciones, metricas_por_fold,
        y_true_total, y_pred_total, cm_total, dataset_info,
    )

    ruta_json = ruta_sin_sobrescribir(args.output_dir, f"metricas_{etiqueta}", ".json")
    with open(ruta_json, "w", encoding="utf-8") as f:
        json.dump(reporte, f, indent=2, ensure_ascii=False)
    print(f"[JSON] {ruta_json}")

    texto = texto_reporte(reporte)
    ruta_txt = ruta_sin_sobrescribir(args.output_dir, f"metricas_{etiqueta}", ".txt")
    with open(ruta_txt, "w", encoding="utf-8") as f:
        f.write(texto)
    print(f"[TEXTO] {ruta_txt}")

    print("\n" + texto)

    print("\nClassification report (sklearn):")
    print(classification_report(
        y_true_total.argmax(axis=1), y_pred_total.argmax(axis=1),
        target_names=NOMBRES_GESTOS, digits=4, zero_division=0,
    ))


if __name__ == "__main__":
    main()
