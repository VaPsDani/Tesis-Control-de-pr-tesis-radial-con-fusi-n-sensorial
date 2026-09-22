"""
Piezas del experimento de ablacion que no necesitan entrenar.

Lo que se protege aqui: que las cuatro celdas no puedan divergir en
silencio, que la seleccion de canales sea lo unico que cambia entre
composiciones, y que la caida entre posturas se calcule en el sentido
correcto. Un signo invertido en esa resta daria la conclusion contraria
sin que nada fallara.
"""
import os
import sys
import types

import numpy as np
import pytest

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(AQUI), "experimentos",
                                "ablacion_imu"))

import ablacion_imu as A          # noqa: E402  no importa TensorFlow
import datos as D                 # noqa: E402


def args_falsos(**cambios):
    base = dict(ventana_ms=200, stride_ms=20, folds=5, epochs=100,
                batch_size=32, lr=1e-3, early_stopping_start=10, seed=42,
                ratio_rest=1.0, entrenamiento="mixto")
    base.update(cambios)
    return types.SimpleNamespace(**base)


def configs_de(args_por_celda=None):
    args = args_falsos()
    configs = {}
    for c in A.COMPOSICIONES:
        for k in A.CONDICIONES:
            a = args if args_por_celda is None else args_por_celda(c, k, args)
            configs[f"{c}|{k}"] = A.configuracion_de_celda(a, c, k)
    return configs


def test_las_cuatro_celdas_identicas_pasan_la_verificacion():
    assert "VERIFICACION" in A.verificar_identidad_de_configuracion(configs_de())


def test_una_semilla_distinta_en_una_celda_falla():
    def con_semilla_rara(c, k, args):
        return args_falsos(seed=7) if (c, k) == ("lmg_imu", "dinamica") else args
    with pytest.raises(AssertionError):
        A.verificar_identidad_de_configuracion(configs_de(con_semilla_rara))


def test_un_numero_de_epocas_distinto_falla():
    def con_epocas_raras(c, k, args):
        return args_falsos(epochs=5) if c == "solo_lmg" else args
    with pytest.raises(AssertionError):
        A.verificar_identidad_de_configuracion(configs_de(con_epocas_raras))


def test_la_composicion_solo_cambia_los_canales():
    n = 40
    v = D.Ventanas(
        X=np.random.RandomState(0).randn(n, 20, 8).astype(np.float32),
        y=np.zeros(n, dtype=int), sujeto=np.ones(n, dtype=int),
        repeticion=np.ones(n, dtype=int),
        condicion=np.array(["estatica"] * n, dtype=object),
        es_calibracion=np.zeros(n, dtype=int))
    solo = D.seleccionar_canales(v, "solo_lmg")
    con = D.seleccionar_canales(v, "lmg_imu")
    assert solo.shape == (n, 20, 5)
    assert con.shape == (n, 20, 8)
    # Los cinco opticos son exactamente los mismos numeros en las dos.
    assert np.array_equal(solo, con[:, :, :5])


def test_composicion_desconocida_falla():
    v = D.Ventanas(np.zeros((2, 20, 8), dtype=np.float32), np.zeros(2, dtype=int),
                   np.ones(2, dtype=int), np.ones(2, dtype=int),
                   np.array(["estatica"] * 2, dtype=object),
                   np.zeros(2, dtype=int))
    with pytest.raises(ValueError):
        D.seleccionar_canales(v, "solo_imu")


def celda(acc_por_sujeto):
    """Celda minima con la forma que produce medir_celda()."""
    media = float(np.mean(list(acc_por_sujeto.values())))
    return {
        "global": {"accuracy": media},
        "por_sujeto": {s: {"accuracy": a} for s, a in acc_por_sujeto.items()},
    }


def test_la_caida_se_mide_de_estatica_a_dinamica():
    celdas = {
        "solo_lmg|estatica": celda({1: 0.80, 2: 0.70}),
        "solo_lmg|dinamica": celda({1: 0.60, 2: 0.50}),   # cae 0.20
        "lmg_imu|estatica": celda({1: 0.82, 2: 0.72}),
        "lmg_imu|dinamica": celda({1: 0.77, 2: 0.67}),    # cae 0.05
    }
    r = A.caida_entre_posturas(celdas)
    assert r["solo_lmg"]["caida_absoluta"] == pytest.approx(0.20)
    assert r["lmg_imu"]["caida_absoluta"] == pytest.approx(0.05)
    # La IMU aguanta mejor: la diferencia de caidas es positiva.
    assert r["diferencia_de_caidas"]["absoluta"] == pytest.approx(0.15)


def test_la_caida_relativa_usa_el_valor_estatico():
    celdas = {
        "solo_lmg|estatica": celda({1: 0.50}),
        "solo_lmg|dinamica": celda({1: 0.25}),
        "lmg_imu|estatica": celda({1: 0.80}),
        "lmg_imu|dinamica": celda({1: 0.40}),
    }
    r = A.caida_entre_posturas(celdas)
    # Las dos pierden la mitad, aunque en puntos absolutos una pierda el
    # doble que la otra.
    assert r["solo_lmg"]["caida_relativa"] == pytest.approx(0.5)
    assert r["lmg_imu"]["caida_relativa"] == pytest.approx(0.5)


def test_sin_caida_la_diferencia_es_cero():
    celdas = {f"{c}|{k}": celda({1: 0.7, 2: 0.6})
              for c in A.COMPOSICIONES for k in A.CONDICIONES}
    r = A.caida_entre_posturas(celdas)
    assert r["diferencia_de_caidas"]["absoluta"] == pytest.approx(0.0)
