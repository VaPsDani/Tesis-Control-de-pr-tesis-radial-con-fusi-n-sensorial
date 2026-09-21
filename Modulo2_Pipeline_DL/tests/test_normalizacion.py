"""
Modos de normalizacion.

Lo que se protege aqui: que las estadisticas NUNCA salgan del pliegue de
test, y que cada modo transforme lo que dice transformar. Un error aqui
no da excepcion, solo cifras infladas.
"""
import numpy as np
import pytest

from normalizacion import MODOS, normalizar, verificar_normalizacion

CLASES = 5


def datos(n_sujetos=6, por_sujeto=120, canales=8, pasos=20, seed=0):
    rng = np.random.RandomState(seed)
    sujetos = np.repeat(np.arange(1, n_sujetos + 1), por_sujeto)
    n = len(sujetos)
    # Cada sujeto con su propia escala y su propio offset, que es el
    # problema que la normalizacion por sujeto viene a resolver.
    X = np.empty((n, pasos, canales), dtype=np.float32)
    for s in np.unique(sujetos):
        m = sujetos == s
        X[m] = (rng.randn(m.sum(), pasos, canales) * (s * 2.0) + s * 10.0)
    # Rest es la clase mayoritaria, como en una sesion real: la
    # normalizacion por reposo exige un minimo de ventanas de Rest.
    y_int = np.where(rng.rand(n) < 0.45, 0, rng.randint(1, CLASES, size=n))
    y = np.eye(CLASES, dtype=np.float32)[y_int]
    return X, y, sujetos


def partir(X, y, sujetos, sujetos_test=(5, 6)):
    te = np.isin(sujetos, sujetos_test)
    tr = ~te
    return (X[tr], X[te], sujetos[tr], sujetos[te], y[tr], y[te])


def test_todos_los_modos_conservan_la_forma():
    X, y, suj = datos()
    for modo in MODOS:
        Xtr, Xte, str_, ste, ytr, yte = partir(X, y, suj)
        a, b, info = normalizar(Xtr, Xte, str_, ste, ytr, yte, modo)
        assert a.shape == Xtr.shape and b.shape == Xte.shape
        assert info["modo"] == modo


def test_modo_ninguna_no_toca_los_datos():
    X, y, suj = datos()
    Xtr, Xte, str_, ste, ytr, yte = partir(X, y, suj)
    a, b, _ = normalizar(Xtr, Xte, str_, ste, ytr, yte, "ninguna")
    assert np.array_equal(a, Xtr) and np.array_equal(b, Xte)


def test_modo_sujeto_estandariza_a_cada_sujeto():
    X, y, suj = datos()
    Xtr, Xte, str_, ste, ytr, yte = partir(X, y, suj)
    a, b, _ = normalizar(Xtr, Xte, str_, ste, ytr, yte, "sujeto")
    for Xn, sn in ((a, str_), (b, ste)):
        for s in np.unique(sn):
            m = sn == s
            assert np.allclose(Xn[m].mean(axis=(0, 1)), 0, atol=1e-3)
            assert np.allclose(Xn[m].std(axis=(0, 1)), 1, atol=1e-2)


def test_modo_global_usa_solo_estadisticas_del_train():
    """
    Si las estadisticas se calcularan con el test incluido, cambiar el
    test cambiaria la transformacion del train. No debe pasar.
    """
    X, y, suj = datos()
    Xtr, Xte, str_, ste, ytr, yte = partir(X, y, suj)
    a1, _, info1 = normalizar(Xtr, Xte, str_, ste, ytr, yte, "global")

    Xte2 = Xte * 100.0 + 5.0           # un test completamente distinto
    a2, _, info2 = normalizar(Xtr, Xte2, str_, ste, ytr, yte, "global")

    assert np.allclose(a1, a2)
    assert info1["mu"] == info2["mu"] and info1["sd"] == info2["sd"]


def test_sujeto_rest_centra_el_reposo_de_cada_sujeto():
    X, y, suj = datos()
    Xtr, Xte, str_, ste, ytr, yte = partir(X, y, suj)
    a, b, _ = normalizar(Xtr, Xte, str_, ste, ytr, yte, "sujeto_rest",
                         clase_rest=0)
    for Xn, sn, yn in ((a, str_, ytr), (b, ste, yte)):
        for s in np.unique(sn):
            m = (sn == s) & (yn.argmax(axis=1) == 0)
            if m.sum() < 2:
                continue
            assert np.allclose(Xn[m].mean(axis=(0, 1)), 0, atol=1e-2)


def test_modo_desconocido_falla():
    X, y, suj = datos()
    Xtr, Xte, str_, ste, ytr, yte = partir(X, y, suj)
    with pytest.raises(ValueError):
        normalizar(Xtr, Xte, str_, ste, ytr, yte, "por_la_cara")


def test_el_verificador_describe_cada_modo():
    X, y, suj = datos()
    Xtr, Xte, str_, ste, ytr, yte = partir(X, y, suj)
    for modo in MODOS:
        a, _, _ = normalizar(Xtr, Xte, str_, ste, ytr, yte, modo)
        assert verificar_normalizacion(a, str_, modo).startswith("[NORM]")
