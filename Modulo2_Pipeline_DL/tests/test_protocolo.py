"""
Protocolo de la sesion de captura.

Lo que se protege aqui: el contrabalanceo, el reparto de posiciones del
brazo y la validacion de los tiempos. Un protocolo mal armado no se nota
hasta que hay un voluntario delante.
"""
import collections

import pytest

import protocolo as p


def test_la_sesion_tiene_calibracion_y_tres_fases_por_gesto():
    bloques = p.construir_sesion(1)
    tipos = collections.Counter(b.tipo for b in bloques)
    n_gestos = p.N_REPETICIONES * len(p.GESTOS_ACTIVOS)
    assert tipos[p.TIPO_CALIBRACION] == 1
    assert tipos[p.TIPO_PREPARACION] == n_gestos
    assert tipos[p.TIPO_CONTRACCION] == n_gestos
    assert tipos[p.TIPO_REPOSO] == n_gestos


def test_los_bloques_no_se_solapan_ni_dejan_huecos():
    bloques = p.construir_sesion(1)
    for a, b in zip(bloques, bloques[1:]):
        assert a.t_fin_ms == b.t_inicio_ms


def test_cada_repeticion_presenta_los_cuatro_gestos_una_vez():
    bloques = p.construir_sesion(3)
    contracciones = [b for b in bloques if b.tipo == p.TIPO_CONTRACCION]
    for rep in range(1, p.N_REPETICIONES + 1):
        gestos = [b.label for b in contracciones if b.repetition_id == rep]
        assert sorted(gestos) == sorted(p.GESTOS_ACTIVOS)


def test_el_orden_es_reproducible_y_distinto_entre_sujetos():
    a1 = p.generar_secuencia_gestos(1)
    a2 = p.generar_secuencia_gestos(1)
    b = p.generar_secuencia_gestos(2)
    assert a1 == a2
    assert a1 != b


def test_el_contrabalanceo_deja_las_transiciones_equilibradas():
    for sid in (1, 2, 3, 7):
        sec = p.generar_secuencia_gestos(sid)
        assert p._desbalance(sec, p.GESTOS_ACTIVOS) <= 1


def test_el_reposo_hereda_el_id_de_repeticion_y_nunca_es_cero():
    bloques = p.construir_sesion(1)
    for b in bloques:
        if b.tipo == p.TIPO_REPOSO:
            assert b.repetition_id >= 1


def test_la_preparacion_queda_entera_en_margen():
    bloques = p.construir_sesion(1)
    prep = next(b for b in bloques if b.tipo == p.TIPO_PREPARACION)
    for t in (0, prep.duracion_ms // 2, prep.duracion_ms - 1):
        assert prep.en_margen(prep.t_inicio_ms + t) == 1
    assert prep.segundos_utiles == 0


def test_en_el_bloque_estatico_no_hay_posicion_de_brazo():
    bloques = p.construir_sesion(1, bloque_postura=p.BLOQUE_ESTATICO)
    assert all(b.posicion_brazo == p.POSICION_NINGUNA for b in bloques)


def test_en_el_dinamico_cada_gesto_pasa_por_las_tres_posiciones():
    bloques = p.construir_sesion(1, bloque_postura=p.BLOQUE_DINAMICO)
    contracciones = [b for b in bloques if b.tipo == p.TIPO_CONTRACCION]
    tabla = collections.Counter((b.label, b.posicion_brazo)
                                for b in contracciones)
    for gesto in p.GESTOS_ACTIVOS:
        cuentas = [tabla[(gesto, pos)] for pos in p.POSICIONES_BRAZO]
        assert len(set(cuentas)) == 1, "las posiciones deben repartirse igual"


def test_postura_desconocida_falla():
    with pytest.raises(ValueError):
        p.construir_sesion(1, bloque_postura="de_lado")


def test_los_margenes_tienen_que_caber_en_su_bloque(monkeypatch):
    monkeypatch.setattr(p, "MARGEN_CONTRACCION", (9000, 9000))
    with pytest.raises(ValueError):
        p.validar_tiempos()


def test_la_rampa_no_puede_salirse_del_margen_de_entrada(monkeypatch):
    monkeypatch.setattr(p, "RAMPA_CONTRACCION_MS", 5000)
    with pytest.raises(ValueError):
        p.validar_tiempos()


def test_el_resumen_cuadra_con_los_tiempos():
    bloques = p.construir_sesion(1)
    r = p.resumen_sesion(bloques)
    esperado = (p.DUR_CALIBRACION_MS + p.N_REPETICIONES * len(p.GESTOS_ACTIVOS)
                * (p.DUR_PREPARACION_MS + p.DUR_CONTRACCION_MS
                   + p.DUR_REPOSO_MS)) / 1000.0
    assert r["duracion_total_s"] == pytest.approx(esperado)
    assert r["ratio_rest_vs_activa"] > 0
