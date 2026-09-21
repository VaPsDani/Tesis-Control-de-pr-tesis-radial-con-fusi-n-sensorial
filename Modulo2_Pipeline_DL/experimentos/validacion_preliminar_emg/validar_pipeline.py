"""
validar_pipeline.py - Validacion algoritmica del pipeline sobre NinaPro DB5
===========================================================================
Protesis transradial - Validacion preliminar con un dataset publico

QUE ES Y QUE NO ES:
  Es una VALIDACION DEL CODIGO: comprueba que la arquitectura, la
  particion, la normalizacion y el bucle de entrenamiento hacen lo que
  dicen, usando un dataset publico con 10 sujetos, antes de tener datos
  propios con los que probarlo.

  NO es una comparacion entre LMG y sEMG. Esa comparacion tendria
  confusores irresolubles (otros sujetos, otra instrumentacion, otro
  protocolo, otra frecuencia) y ademas ya esta hecha correctamente por
  Shahmohammadi et al., con grabacion simultanea de ambas modalidades
  sobre los mismos participantes. La comparacion central de este trabajo
  es la ablacion de la IMU sobre datos propios
  (experimentos/ablacion_imu).

  Que las senales sean sEMG es circunstancial: la entrada es (40, 8), la
  misma forma que los 8 canales del brazalete propio, y por eso el mismo
  pipeline sirve para las dos. La ruta de produccion sobre el hardware
  fisico (entrada (20, 8)) vive en produccion/entrenar_modelo.py y no se
  ve afectada por este archivo.

FLUJO:
  1. Cargar y preprocesar NinaPro DB5 (cargar_ninapro.py)
  2. Autotest del verificador de fuga entre sujetos
  3. Particion por grupos: repeticion o sujeto (common/validacion.py)
  4. Entrenar CNN-BiLSTM-Attention en cada pliegue
  5. Exportar metricas por pliegue, agregadas y comparadas con la
     referencia transcrita del informe SI2

ESQUEMAS DE AGRUPAMIENTO:
  --agrupamiento repeticion : referencia SI2 (intra-sujeto), 82.98% +/- 2.85%
  --agrupamiento sujeto     : inter-sujeto, 2 sujetos completos por pliegue

  Todo lo demas (arquitectura, hiperparametros, preprocesamiento, ventana,
  stride, submuestreo de Rest, k=5) es identico entre ambos esquemas: el
  criterio de agrupamiento es el unico grado de libertad.

USO:
  python validar_pipeline.py --mat ~/data/NinaPro_DB5 --agrupamiento sujeto
  python validar_pipeline.py --mat ~/data/NinaPro_DB5 --agrupamiento repeticion
"""

# Rutas del Modulo 2 tras la reorganizacion: common/ tiene el codigo
# compartido por todos los experimentos y produccion/ el pipeline del
# modelo que se despliega.
import os as _os
import sys as _sys
_M2 = _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                     "..", ".."))
for _d in (_M2, _os.path.join(_M2, "common"), _os.path.join(_M2, "produccion"),
           _os.path.join(_M2, "experimentos", "validacion_preliminar_emg")):
    if _d not in _sys.path:
        _sys.path.insert(0, _d)


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
from cargar_ninapro import (
    cargar_procesar_dataset,
    NOMBRES_GESTOS,
    NUM_CLASES,
    VENTANA_SAMPLES,
    CANALES_TOTAL,
)
from validacion import (
    autotest_verificador,
    describir_pliegue,
    formatear_pliegue,
    generar_particiones,
)
from normalizacion import MODOS as MODOS_NORM, normalizar, verificar_normalizacion
from entrenamiento import (LABEL_SMOOTHING, augmentar_muestra, fijar_semilla,
                           entrenar_con_validacion_interna, entrenar_pliegue)
from metricas import (graficar_historial_kfold, graficar_matriz_confusion,
                      ruta_sin_sobrescribir)

warnings.filterwarnings("ignore")

RESULTADOS_DIR = "resultados_cv"

# LABEL_SMOOTHING vive ahora en common/entrenamiento.py, que es el unico
# sitio donde se entrena. Cambiarlo rompe la comparabilidad con la cifra
# de referencia de 82.98%.

# ------------------------------------------------------------
# REFERENCIA SI2 - GroupKFold agrupado por REPETICION
# Cifras del informe previo del curso SI2, que se conservan para poder
# comparar contra ellas. Es una referencia interna del propio pipeline,
# no una comparacion entre modalidades de sensor.
# Transcrita de resultados_preliminares/metricas.txt en el commit
# af6a26a, preservado bajo el tag 'si2-groupkfold-repeticion'.
# ------------------------------------------------------------
REFERENCIA_SI2 = {
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
            "normalizacion": args.normalizacion,
            "seed": args.seed,
            "validacion": args.validacion,
            "val_grupos": args.val_grupos,
            "reentrenar": bool(args.reentrenar),
            "reentreno_epocas": "las de la epoca restaurada en la seleccion, "
                                "sin escalar por el grupo anadido",
            "determinismo_gpu": bool(args.determinismo),
            "early_stopping_start": args.early_stopping_start,
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
            "epoca_restaurada_por_fold": [
                m["epoca_restaurada"] for m in metricas_por_fold
            ],
            "epoca_argmin_global_por_fold": [
                m["epoca_argmin_global"] for m in metricas_por_fold
            ],
            "pliegues_restaurados_en_el_umbral": [
                m["fold"] for m in [
                    {**metricas_por_fold[i], "fold": i + 1}
                    for i in range(len(metricas_por_fold))
                ] if m["restaurada_en_el_umbral"]
            ],
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
        "referencia_si2": REFERENCIA_SI2,
    }
    return reporte


def texto_reporte(reporte: dict) -> str:
    """Renderiza el reporte como texto legible, incluida la comparativa."""
    L = []
    esq = reporte["esquema"]
    ag = reporte["agregado"]
    base = reporte["referencia_si2"]

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
             f"{'Loss':>10}{'Epocas':>9}{'Restaur.':>10}{'Argmin':>9}")
    L.append(f"  {'-'*77}")
    for p in reporte["pliegues"]:
        marca = "*" if p["restaurada_en_el_umbral"] else ""
        L.append(f"  {p['fold']:<9}{p['accuracy']:>11.4f}{p['f1_macro']:>11.4f}"
                 f"{p['auc']:>10.4f}{p['loss']:>10.4f}{p['epochs']:>9}"
                 f"{str(p['epoca_restaurada']) + marca:>10}"
                 f"{p['epoca_argmin_global']:>9}")
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
    L.append(f"  Normalizacion: {reporte['config']['normalizacion']}   |   "
             f"early_stopping_start: {reporte['config']['early_stopping_start']}")
    L.append("  'Restaur.' = epoca cuyos pesos devolvio restore_best_weights.")
    L.append("  'Argmin'   = minimo global de val_loss, incluidas las epocas")
    L.append("               anteriores al umbral (no es lo que se evaluo).")
    pegados = ag["pliegues_restaurados_en_el_umbral"]
    if pegados:
        L.append(f"  (*) Pliegues restaurados pegados al umbral: {pegados}.")
        L.append("      Su val_loss no mejoro despues del calentamiento: el")
        L.append("      colapso sigue ahi, solo enmascarado por el umbral.")
    else:
        L.append("  Ningun pliegue quedo pegado al umbral: todos siguieron")
        L.append("  mejorando el val_loss despues del calentamiento.")
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
    L.append("COMPARATIVA CONTRA LA REFERENCIA SI2 (agrupamiento por repeticion)")
    L.append(f"Fuente de la referencia: {base['origen']}")
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
    L.append(f"    epoca restaurada por SUJETO: "
             f"{ag['epoca_restaurada_por_fold']}")
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
    parser.add_argument("--normalizacion", type=str, default="ninguna",
                        choices=list(MODOS_NORM),
                        help="Estandarizacion z-score por canal: 'ninguna', "
                             "'global' (stats solo de train), 'sujeto' (stats "
                             "propias de cada sujeto) o 'sujeto_rest' (stats "
                             "de las ventanas Rest de cada sujeto). "
                             "Default: ninguna")
    parser.add_argument("--early_stopping_start", type=int, default=10,
                        help="Epoca minima antes de que EarlyStopping pueda "
                             "disparar o fijar 'best'. Con 0 se reproduce el "
                             "comportamiento anterior, en el que un pliegue "
                             "podia restaurar los pesos de la epoca 1. "
                             "Default: 10")
    parser.add_argument("--epochs", type=int, default=100,
                        help="Maximo de epocas por pliegue (default: 100)")
    parser.add_argument("--batch_size", type=int, default=32,
                        help="Tamano del batch (default: 32)")
    parser.add_argument("--lr", type=float, default=1e-3,
                        help="Tasa de aprendizaje inicial (default: 1e-3)")
    parser.add_argument("--folds", type=int, default=5,
                        help="Numero de pliegues (default: 5)")
    parser.add_argument("--validacion", type=str, default="interna",
                        choices=["interna", "test", "reducido_test"],
                        help="Que ven EarlyStopping y ReduceLROnPlateau. "
                             "'interna' (default): grupos enteros separados "
                             "del train, nunca del test. 'test': el pliegue "
                             "de test, comportamiento historico y optimista. "
                             "'reducido_test': control que quita del train "
                             "los mismos grupos que 'interna' pero vigila el "
                             "test, para separar el efecto de tener menos "
                             "datos del efecto de la fuga.")
    parser.add_argument("--reentrenar", action="store_true",
                        help="Con --validacion interna: tras elegir la epoca y "
                             "el calendario de lr con el grupo interno, "
                             "reentrena desde cero con TODO el train del "
                             "pliegue durante esas epocas y evalua ese modelo. "
                             "Asi la validacion no cuesta datos de "
                             "entrenamiento. Las metricas de la fase de "
                             "seleccion se guardan aparte en cada pliegue.")
    parser.add_argument("--val_grupos", type=int, default=1,
                        help="Grupos (sujetos o repeticiones, segun el "
                             "agrupamiento) que se separan del train para la "
                             "validacion interna. Default: 1")
    parser.add_argument("--seed", type=int, default=None,
                        help="Semilla para inicializacion, barajado y "
                             "augmentation. Sin ella (default) cada corrida "
                             "difiere en ~0.6 puntos de accuracy, ruido que "
                             "impide distinguir efectos pequenos. Se reancla "
                             "por pliegue como seed+fold_idx.")
    parser.add_argument("--determinismo", action="store_true",
                        help="Fuerza kernels deterministas en GPU "
                             "(enable_op_determinism). Reproducibilidad bit a "
                             "bit, pero puede rechazar el kernel cuDNN del "
                             "LSTM y ralentizar mucho. Requiere --seed.")
    parser.add_argument("--cache", type=str, default=None,
                        help="Ruta .npz para cachear el dataset preprocesado")
    parser.add_argument("--etiqueta", type=str, default=None,
                        help="Nombre con el que se guardan los resultados. Por "
                             "defecto se deriva de validador, agrupamiento y "
                             "normalizacion. Util para nombrar corridas de "
                             "control cuyo proposito no se lee del esquema.")
    parser.add_argument("--output_dir", type=str, default=RESULTADOS_DIR,
                        help=f"Directorio de salida (default: {RESULTADOS_DIR}/)")
    args = parser.parse_args()

    if args.reentrenar and args.validacion != "interna":
        parser.error("--reentrenar solo tiene sentido con --validacion interna: "
                     "con 'test' la epoca se elegiria mirando el test.")

    if args.determinismo and args.seed is None:
        parser.error("--determinismo no sirve sin --seed: forzar kernels "
                     "deterministas no elimina la varianza de inicializacion "
                     "ni de barajado, que es la que domina.")

    if args.seed is None:
        print("[SEMILLA] Sin fijar. Dos corridas identicas difieren ~0.6 "
              "puntos de accuracy; no compare efectos menores que eso.")
    else:
        print(f"[SEMILLA] {args.seed} (reanclada por pliegue como "
              f"seed+fold_idx)"
              + ("  + determinismo de kernels en GPU"
                 if args.determinismo else ""))

    os.makedirs(args.output_dir, exist_ok=True)

    validador = "stratifiedgroupkfold" if args.estratificado else "groupkfold"
    etiqueta = args.etiqueta or (
        f"{validador}_{args.agrupamiento}_norm-{args.normalizacion}"
        + ("" if args.validacion == "test" else f"_val-{args.validacion}")
        + ("_reentreno" if args.reentrenar else "")
    )
    if args.validacion == "test":
        print("[VALIDACION] AVISO: los callbacks vigilan el pliegue de TEST. "
              "La epoca restaurada se elige mirando el test y las metricas "
              "son optimistas. Solo para reproducir corridas historicas.")

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
    todos_sujetos = []
    todos_pliegues = []

    infos_normalizacion = []

    for fold_idx, (idx_train, idx_val) in enumerate(particiones):
        X_train, X_val = X[idx_train], X[idx_val]
        y_train, y_val = y[idx_train], y[idx_val]
        suj_train, suj_val = sujetos[idx_train], sujetos[idx_val]

        # La normalizacion se aplica DENTRO del pliegue para que quede a
        # la vista que el modo 'global' solo ve X_train al estimar sus
        # parametros.
        X_train, X_val, info_norm = normalizar(
            X_train, X_val, suj_train, suj_val, y_train, y_val,
            modo=args.normalizacion,
        )
        infos_normalizacion.append(info_norm)
        if args.normalizacion != "ninguna":
            print(f"  {verificar_normalizacion(X_train, suj_train, args.normalizacion)}"
                  f"  [train pliegue {fold_idx + 1}]")
            print(f"  {verificar_normalizacion(X_val, suj_val, args.normalizacion)}"
                  f"  [test pliegue {fold_idx + 1}]")

        # Validacion de los callbacks y reentreno: el mecanismo unico,
        # compartido con los scripts de experimentos/.
        g_train = (suj_train if args.agrupamiento == "sujeto"
                   else grupos_rep[idx_train])
        g_test = (suj_val if args.agrupamiento == "sujeto"
                  else grupos_rep[idx_val])
        history, y_pred, metricas = entrenar_con_validacion_interna(
            X_train, y_train, g_train, X_val, y_val, g_test, fold_idx,
            args.epochs, args.batch_size, args.lr,
            early_stopping_start=args.early_stopping_start,
            seed=args.seed, determinismo=args.determinismo,
            modo=args.validacion, val_grupos=args.val_grupos,
            reentrenar=args.reentrenar,
            num_clases=NUM_CLASES, nombres_clases=NOMBRES_GESTOS,
        )

        historiales.append(history)
        metricas_por_fold.append(metricas)

        cm_total += confusion_matrix(
            y_val.argmax(axis=1), y_pred.argmax(axis=1),
            labels=range(NUM_CLASES),
        )
        todas_y_true.append(y_val)
        todas_y_pred.append(y_pred)
        todos_sujetos.append(suj_val)
        todos_pliegues.append(np.full(len(suj_val), fold_idx))

    y_true_total = np.concatenate(todas_y_true, axis=0)
    y_pred_total = np.concatenate(todas_y_pred, axis=0)

    # ========== 5. REPORTE ==========
    print("\n" + "=" * 60)
    print("PASO 5: Generando resultados en", args.output_dir)
    print("=" * 60)

    graficar_historial_kfold(historiales, etiqueta, args.output_dir)
    graficar_matriz_confusion(cm_total, etiqueta, args.output_dir,
                              nombres_clases=NOMBRES_GESTOS)

    reporte = construir_reporte(
        args, etiqueta, descripciones, metricas_por_fold,
        y_true_total, y_pred_total, cm_total, dataset_info,
    )
    reporte["normalizacion_por_pliegue"] = infos_normalizacion

    # Predicciones por ventana con su sujeto: permiten metricas POR SUJETO
    # (10 valores pareados) en vez de por pliegue (5).
    sujetos_total = np.concatenate(todos_sujetos)
    pliegues_total = np.concatenate(todos_pliegues)
    ruta_npz = ruta_sin_sobrescribir(args.output_dir, f"predicciones_{etiqueta}", ".npz")
    yt_int = y_true_total.argmax(axis=1)
    yp_int = y_pred_total.argmax(axis=1)
    np.savez_compressed(ruta_npz, pliegue=pliegues_total.astype(np.int16),
                        sujeto=sujetos_total, y_true=yt_int.astype(np.int16),
                        prob=y_pred_total.astype(np.float32))
    reporte["archivo_predicciones"] = os.path.basename(ruta_npz)
    reporte["metricas_por_sujeto"] = {}
    for s_id in np.unique(sujetos_total):
        m_s = sujetos_total == s_id
        reporte["metricas_por_sujeto"][str(int(s_id))] = {
            "accuracy": float(np.mean(yt_int[m_s] == yp_int[m_s])),
            "f1_macro": float(f1_score(yt_int[m_s], yp_int[m_s], average="macro",
                                       labels=range(NUM_CLASES), zero_division=0)),
            "n_ventanas": int(m_s.sum()),
            "pliegues": [int(p) + 1 for p in np.unique(pliegues_total[m_s])],
        }
    print(f"[NPZ] {ruta_npz}")

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
