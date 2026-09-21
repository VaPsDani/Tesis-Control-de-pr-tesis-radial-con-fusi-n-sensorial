"""
Particion por grupos y deteccion de fuga.

Lo que se protege aqui: que ningun sujeto aparezca a la vez en train y en
test cuando el agrupamiento es por sujeto. Una fuga asi no rompe nada de
forma visible, solo infla la exactitud, y por eso hace falta una prueba.
"""
import numpy as np
import pytest

from validacion import (FugaEntreParticiones, autotest_verificador,
                        generar_particiones, obtener_vector_grupos,
                        verificar_sujetos_disjuntos)


def datos(n_sujetos=10, por_sujeto=40, n_repeticiones=6):
    sujetos = np.repeat(np.arange(1, n_sujetos + 1), por_sujeto)
    n = len(sujetos)
    # Repeticiones dentro de cada sujeto, como en una sesion real.
    repeticiones = np.tile(
        np.repeat(np.arange(1, n_repeticiones + 1),
                  int(np.ceil(por_sujeto / n_repeticiones)))[:por_sujeto],
        n_sujetos)
    X = np.random.RandomState(0).randn(n, 20, 8).astype(np.float32)
    y = np.random.RandomState(1).randint(0, 5, size=n)
    return X, y, repeticiones[:n], sujetos


def test_autotest_del_verificador_pasa():
    sujetos = np.repeat(np.arange(10), 20)
    assert "OK" in autotest_verificador(sujetos, seed=0)


def test_agrupar_por_sujeto_deja_los_sujetos_disjuntos():
    X, y, rep, suj = datos()
    pliegues = generar_particiones(X, y, rep, suj, "sujeto", n_splits=5)
    assert len(pliegues) == 5
    for tr, te in pliegues:
        assert not (set(suj[tr]) & set(suj[te]))


def test_cada_sujeto_es_test_exactamente_una_vez():
    X, y, rep, suj = datos()
    pliegues = generar_particiones(X, y, rep, suj, "sujeto", n_splits=5)
    veces = {s: 0 for s in np.unique(suj)}
    for _, te in pliegues:
        for s in np.unique(suj[te]):
            veces[s] += 1
    assert set(veces.values()) == {1}


def test_el_verificador_detecta_una_fuga_inyectada():
    _, _, _, suj = datos()
    idx = np.arange(len(suj))
    tr = idx[suj <= 8]
    te = idx[suj >= 8]           # el sujeto 8 cae en los dos lados
    with pytest.raises(FugaEntreParticiones):
        verificar_sujetos_disjuntos(suj, tr, te, fold_idx=0)


def test_agrupar_por_repeticion_es_intra_sujeto():
    """
    Con agrupamiento por repeticion los sujetos SI se solapan. No es un
    error, es la definicion del esquema, y el codigo no debe tratarlo
    como fuga.
    """
    X, y, rep, suj = datos()
    pliegues = generar_particiones(X, y, rep, suj, "repeticion", n_splits=5)
    solapan = any(set(suj[tr]) & set(suj[te]) for tr, te in pliegues)
    assert solapan


def test_vector_de_grupos_segun_el_esquema():
    _, _, rep, suj = datos()
    assert np.array_equal(obtener_vector_grupos("sujeto", rep, suj), suj)
    assert np.array_equal(obtener_vector_grupos("repeticion", rep, suj), rep)
