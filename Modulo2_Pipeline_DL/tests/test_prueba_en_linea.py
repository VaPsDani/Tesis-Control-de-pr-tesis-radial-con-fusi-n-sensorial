"""
Prueba en linea (A28): el plan de intentos y el criterio de exito.
"""
import collections

import pytest

import prueba_en_linea as L


def test_el_plan_tiene_cinco_por_gesto_y_diez_por_postura():
    p = L.plan(3)
    assert len(p) == 20
    assert collections.Counter(g for g, _ in p) == {1: 5, 2: 5, 3: 5, 4: 5}
    assert collections.Counter(q for _, q in p) == {"apoyado": 10, "frente": 10}
    assert p == L.plan(3) and p != L.plan(4)


def test_exito_si_la_clase_se_sostiene_un_segundo():
    # Pinza desde 0.6 s hasta el final de la ventana.
    r = L.evaluar_intento([(10.0, 0), (100.6, 1)], 100.0, 1)
    assert r["exito"]
    assert r["tiempo_hasta_completar_s"] == pytest.approx(1.6)
    assert r["primer_acierto_s"] == pytest.approx(0.6)


def test_un_acierto_de_menos_de_un_segundo_no_cuenta():
    cambios = [(100.5, 1), (101.2, 3), (102.0, 1), (102.8, 0)]
    r = L.evaluar_intento(cambios, 100.0, 1)
    assert not r["exito"]
    assert r["primer_acierto_s"] == pytest.approx(0.5)


def test_la_clase_vigente_antes_de_la_indicacion_cuenta_desde_la_indicacion():
    # Ya estaba en puno antes de la indicacion: cuenta desde t0.
    r = L.evaluar_intento([(90.0, 3)], 100.0, 3)
    assert r["exito"] and r["tiempo_hasta_completar_s"] == pytest.approx(1.0)


def test_lo_que_pasa_despues_de_la_ventana_no_cuenta():
    r = L.evaluar_intento([(104.5, 2)], 100.0, 2)
    assert not r["exito"]
