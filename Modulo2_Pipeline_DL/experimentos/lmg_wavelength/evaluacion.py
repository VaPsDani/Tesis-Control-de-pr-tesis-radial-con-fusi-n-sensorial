"""
evaluacion.py - Utilidades compartidas por los analisis 1.a-1.d
================================================================
Todas las validaciones cruzadas agrupan por SUJETO (GroupKFold k=5), con
la verificacion dura de no fuga de particion.py.
"""

import os
import sys

import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
from datos import NUM_CLASES  # noqa: E402
from particion import generar_particiones  # noqa: E402

from sklearn.metrics import accuracy_score, f1_score  # noqa: E402


def particiones_por_sujeto(y, subj, k=5):
    """GroupKFold por sujeto con verificacion de sujetos disjuntos."""
    return generar_particiones(np.zeros(len(y)), y, subj, subj,
                               agrupamiento="sujeto", n_splits=k)


def metricas(y_true, y_pred):
    return dict(
        accuracy=float(accuracy_score(y_true, y_pred)),
        f1_macro=float(f1_score(y_true, y_pred, average="macro",
                                labels=range(NUM_CLASES), zero_division=0)),
        f1_por_clase=[float(v) for v in f1_score(
            y_true, y_pred, average=None, labels=range(NUM_CLASES),
            zero_division=0)],
    )


def por_sujeto(y_true, y_pred, subj):
    """Accuracy y F1 macro de cada sujeto sobre sus ventanas de test."""
    fuera = {}
    for s in np.unique(subj):
        m = subj == s
        fuera[int(s)] = metricas(y_true[m], y_pred[m])
    return fuera


# ============================================================
# LDA RAPIDO POR ESTADISTICOS SUFICIENTES (para 1.c)
# ============================================================
# La busqueda de canales evalua cientos de miles de subconjuntos. Ajustar
# un LDA de sklearn en cada uno recorre los datos de entrenamiento cada
# vez. Pero el LDA solo necesita, por clase, el numero de muestras, la
# suma y la matriz de productos cruzados. Se calculan UNA vez por pliegue
# sobre las 80 caracteristicas, y cualquier subconjunto se entrena
# extrayendo submatrices: O(k^3) sin tocar los datos. Solo la prediccion
# recorre el conjunto de test.
#
# Regularizacion: contraccion fija hacia la diagonal, alfa = 0.1, igual
# para todos los subconjuntos para que sus puntuaciones sean comparables.
# (El shrinkage 'auto' de Ledoit-Wolf varia con cada subconjunto.)
ALFA_CONTRACCION = 0.1


class LDARapido:
    def __init__(self, F_tr, y_tr, n_clases=NUM_CLASES):
        self.C = n_clases
        n = len(y_tr)
        P = F_tr.shape[1]
        self.mu = np.zeros((n_clases, P))
        Sw = np.zeros((P, P))
        self.logpi = np.zeros(n_clases)
        for c in range(n_clases):
            Xc = F_tr[y_tr == c].astype(np.float64)
            nc = len(Xc)
            self.logpi[c] = np.log(max(nc, 1) / n)
            if nc == 0:
                continue
            self.mu[c] = Xc.mean(axis=0)
            D = Xc - self.mu[c]
            Sw += D.T @ D
        self.Sigma = Sw / max(n - n_clases, 1)

    def predecir(self, F_te, idx):
        S = self.Sigma[np.ix_(idx, idx)]
        S = (1 - ALFA_CONTRACCION) * S + ALFA_CONTRACCION * np.diag(np.diag(S))
        M = self.mu[:, idx]                        # (C, k)
        W = np.linalg.solve(S, M.T)                # (k, C)
        b = -0.5 * np.sum(M.T * W, axis=0) + self.logpi
        return np.argmax(F_te[:, idx] @ W + b, axis=1)


def indices_caracteristicas(canales, n_canales=40):
    """Canal j -> columnas [j] (media) y [n_canales + j] (desviacion)."""
    canales = np.asarray(canales)
    return np.concatenate([canales, canales + n_canales])
