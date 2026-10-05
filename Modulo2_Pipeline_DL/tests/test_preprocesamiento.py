"""
Preprocesamiento compartido por la ablacion, produccion y la conversion.

Lo que se protege aqui es lo que el articulo dice del preprocesamiento:
la normalizacion (A8, A9, A10), el etiquetado por fases (A12), que la
preparacion y las repeticiones descartadas nunca entren, y los pesos por
clase (A13).
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

import preprocesamiento as P

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(AQUI), "experimentos",
                                "ablacion_imu"))


# ---------- normalizacion ----------
def test_la_lmg_va_en_z_y_el_acelerometro_solo_resta_la_media():
    mu = np.array([1, 2, 3, 4, 5, 0.1, 0.2, 0.9], dtype=np.float32)
    sd = np.array([2, 2, 2, 2, 2, 0.01, 0.01, 0.01], dtype=np.float32)
    x = np.array([[[3, 4, 5, 6, 7, 0.6, 0.2, 1.4]]], dtype=np.float32)
    z = P.normalizar(x, mu, sd)[0, 0]
    assert np.allclose(z[:5], 1.0, atol=1e-6)            # (x - mu) / sd
    # El acelerometro NO se divide: con sd = 0.01 dividir daria 50.
    assert np.allclose(z[5:], [0.5, 0.0, 0.5], atol=1e-6)


def _calibracion(n_filas, margen_ini=100, margen_fin=50, semilla=0):
    rng = np.random.RandomState(semilla)
    df = pd.DataFrame(rng.randn(n_filas, 8) * 3 + 10, columns=P.COLUMNAS_MODELO)
    df["es_calibracion"] = 1
    m = np.zeros(n_filas, dtype=int)
    m[:margen_ini] = 1
    m[n_filas - margen_fin:] = 1
    df["en_margen"] = m
    return df


def test_las_estadisticas_replican_al_firmware():
    df = _calibracion(1500)
    mu, sd = P.estadisticas_calibracion(df)
    # Sin margenes quedan 1350 filas, y solo 67 ventanas completas de 20.
    util = df[df.en_margen == 0][P.COLUMNAS_MODELO].to_numpy(np.float64)[:1340]
    assert np.allclose(mu, util.mean(axis=0), atol=1e-4)
    # Desviacion poblacional, como var = E[x^2] - E[x]^2 en el firmware.
    assert np.allclose(sd, util.std(axis=0, ddof=0), atol=1e-4)


def test_una_calibracion_corta_no_se_acepta():
    with pytest.raises(ValueError):
        P.estadisticas_calibracion(_calibracion(700))     # 550 utiles < 600


# ---------- sesion sintetica completa ----------
@pytest.fixture(scope="module")
def sesion(tmp_path_factory):
    import datos as D
    d = str(tmp_path_factory.mktemp("sesion"))
    D.generar_sesiones_sinteticas(d, n_sujetos=1, semilla=5)
    ruta = os.path.join(d, "s01_sintetica.csv")
    return ruta, P.cargar_sesion(ruta)


def test_la_preparacion_nunca_queda_como_gesto(sesion):
    _, df = sesion
    prep = df[df.bloque_tipo == "preparacion"]
    assert set(prep.fase) == {"preparacion"}


def test_el_reposo_en_movimiento_es_reposo_entero(sesion):
    _, df = sesion
    rd = df[df.bloque_tipo == "reposo_dinamico"]
    assert len(rd) and set(rd.fase) == {"reposo"}


def test_el_tiempo_de_reaccion_se_mide_desde_la_contraccion(sesion):
    from anotar_fases import anotar_df
    _, df = sesion
    _, informes, _ = anotar_df(df.drop(columns="fase"))
    onsets = np.array([d["onset_ms"] for d in informes
                       if d["onset_ms"] is not None])
    assert len(informes) == 24
    # El simulador reacciona entre 250 y 550 ms. Con la preparacion unida
    # al gesto, como en la version 2, saldrian mas de 3000.
    assert 200 < np.median(onsets) < 800


def test_en_las_dinamicas_el_inicio_se_mide_contra_la_preparacion(sesion):
    # Con la base del reposo previo, sobre la mesa, el cambio de postura de
    # la preparacion disparaba el detector antes de la indicacion: inicios
    # negativos falsos en la mitad de las dinamicas. Con la base en el
    # ultimo segundo de la preparacion, las dinamicas se parecen a las
    # estaticas y nunca salen negativas.
    from anotar_fases import anotar_df
    _, df = sesion
    _, informes, _ = anotar_df(df.drop(columns="fase"))
    cond = df["condicion_postural"].fillna("").to_numpy()
    din = [d for d in informes if cond[d["inicio"]] == "dinamica"]
    est = [d for d in informes if cond[d["inicio"]] == "estatica"]
    assert {d["base"] for d in din} == {"preparacion"}
    assert {d["base"] for d in est} == {"local"}
    on_din = np.array([d["onset_ms"] for d in din if d["onset_ms"] is not None])
    on_est = np.array([d["onset_ms"] for d in est if d["onset_ms"] is not None])
    assert (on_din >= 0).all()
    assert abs(np.median(on_din) - np.median(on_est)) < 300


def test_no_hay_ventanas_de_calibracion_preparacion_ni_cruzadas(sesion):
    ruta, _ = sesion
    v = P.preparar_sesion(ruta)
    assert set(v.bloque_tipo) <= {"contraccion", "reposo", "reposo_dinamico"}
    for k in range(5):
        assert (v.y == k).sum() > 0
    # Rest solo sale de bloques de reposo, y los gestos de contracciones.
    assert set(v.bloque_tipo[v.y > 0]) == {"contraccion"}
    assert set(v.bloque_tipo[v.y == 0]) <= {"reposo", "reposo_dinamico"}


def test_las_repeticiones_descartadas_no_entran(sesion, tmp_path):
    ruta, df = sesion
    df = df.drop(columns="fase")
    # El operador descarta la pinza de la repeticion 2.
    m = ((df.repetition_id == 2) & (df.label == 1)
         & df.bloque_tipo.isin(["preparacion", "contraccion"]))
    df.loc[m, "descartada"] = 1
    otra = str(tmp_path / "s01_descartes.csv")
    df.to_csv(otra, index=False)

    from anotar_fases import anotar_df
    fase, informes, _ = anotar_df(df)
    assert set(fase[m.to_numpy()]) == {"descartada"}
    assert len(informes) == 23

    v = P.preparar_sesion(otra)
    assert not np.any((v.repeticion == 2) & (v.y == 1))


# ---------- pesos por clase ----------
def test_los_pesos_siguen_la_formula_del_articulo():
    from entrenamiento import pesos_de_clase
    y = np.eye(5)[[0] * 60 + [1] * 10 + [2] * 10 + [3] * 10 + [4] * 10]
    w = pesos_de_clase(y, 5)
    total = 100
    esperado = [total / (5 * n) for n in (60, 10, 10, 10, 10)]
    assert np.allclose(w, esperado)
    # Con los pesos, cada clase suma lo mismo en la perdida.
    assert np.allclose(w * y.sum(axis=0), total / 5)


def test_una_clase_ausente_pesa_cero():
    from entrenamiento import pesos_de_clase
    y = np.eye(5)[[0, 0, 1, 2, 3]]
    assert pesos_de_clase(y, 5)[4] == 0.0
