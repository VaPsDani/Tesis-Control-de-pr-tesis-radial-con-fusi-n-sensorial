"""
Calibracion de los FSR en newtons (A27).

Los datos se fabrican con una curva conocida, asi que se sabe que curva
tiene que ganar y que error tiene que salir.
"""
import numpy as np
import pandas as pd
import pytest

import calibrar_fsr as C


def pares_potenciales(c=0.002, d=1.5, ruido=0.0, semilla=0):
    rng = np.random.RandomState(semilla)
    masas = np.array([0, 20, 50, 100, 200, 350, 500])
    f = masas / 1000.0 * C.G
    v = np.where(f > 0, (np.maximum(f, 1e-12) / c) ** (1 / d), 5.0)
    v = v * (1 + ruido * rng.randn(len(v)))
    return pd.DataFrame({"sensor": "P", "masa_g": masas, "lectura_mv": v})


def test_una_curva_potencial_gana_y_se_recupera():
    res = C.ajustar(pares_potenciales())["P"]
    assert res["elegida"] == "potencial"
    assert res["curva"]["c"] == pytest.approx(0.002, rel=1e-6)
    assert res["curva"]["d"] == pytest.approx(1.5, rel=1e-6)
    assert res["candidatas"]["potencial"]["rmse_n"] < 1e-9
    # La masa cero no entra al ajuste: la potencial no existe en cero.
    assert res["n_puntos"] == 6


def test_una_curva_lineal_gana_cuando_los_datos_son_lineales():
    masas = np.array([10, 50, 100, 200, 400])
    f = masas / 1000.0 * C.G
    pares = pd.DataFrame({"sensor": "I", "masa_g": masas,
                          "lectura_mv": (f - 0.05) / 0.004})
    assert C.ajustar(pares)["I"]["elegida"] == "lineal"


def test_con_pocos_puntos_no_se_ajusta():
    pares = pd.DataFrame({"sensor": "M", "masa_g": [0, 50, 100],
                          "lectura_mv": [3.0, 100.0, 180.0]})
    with pytest.raises(ValueError):
        C.ajustar(pares)


def test_el_mae_compara_la_parada_con_la_consigna_en_newtons():
    curvas = {"P": {"curva": {"tipo": "lineal", "a": 0.01, "b": 0.0}}}
    log = ["[FSR_STOP] dedo=0 lectura_mv=420.0 umbral_mv=410.0 angulo=120",
           "[FSR_STOP] dedo=0 lectura_mv=400.0 umbral_mv=410.0 angulo=118",
           "[SERVO] otra linea que no cuenta",
           "[FSR_STOP] dedo=3 lectura_mv=380.0 umbral_mv=372.0 angulo=90"]
    res = C.mae(curvas, log)
    # 0.1 N por encima y 0.1 N por debajo; el anular no esta calibrado.
    assert res["mae_n"] == pytest.approx(0.1)
    assert res["sesgo_n"] == pytest.approx(0.0)
    assert res["n_paradas"] == 2
