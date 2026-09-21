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


def test_cada_gesto_tiene_tres_estaticas_y_tres_dinamicas():
    bloques = p.construir_sesion(1)
    contracciones = [b for b in bloques if b.tipo == p.TIPO_CONTRACCION]
    tabla = collections.Counter((b.label, b.condicion_postural)
                                for b in contracciones)
    for gesto in p.GESTOS_ACTIVOS:
        for cond in p.CONDICIONES:
            assert tabla[(gesto, cond)] == p.REPETICIONES_POR_CONDICION


def test_la_calibracion_no_pertenece_a_ninguna_condicion():
    calib = next(b for b in p.construir_sesion(1)
                 if b.tipo == p.TIPO_CALIBRACION)
    assert calib.condicion_postural == p.CONDICION_NINGUNA


def test_las_tres_fases_de_una_repeticion_comparten_condicion():
    bloques = [b for b in p.construir_sesion(2)
               if b.tipo != p.TIPO_CALIBRACION]
    for i in range(0, len(bloques), 3):
        prep, contr, reposo = bloques[i:i + 3]
        assert prep.condicion_postural == contr.condicion_postural
        assert reposo.condicion_postural == contr.condicion_postural


def test_solo_las_dinamicas_recorren_posiciones():
    for b in p.construir_sesion(1):
        if b.tipo == p.TIPO_CONTRACCION and b.condicion_postural == p.CONDICION_DINAMICA:
            assert len(b.orden_posiciones) == len(p.POSICIONES_BRAZO)
            assert set(b.orden_posiciones) == set(p.POSICIONES_BRAZO)
        else:
            assert b.orden_posiciones == ()


def test_la_posicion_avanza_en_tres_tramos_iguales():
    contr = next(b for b in p.construir_sesion(1)
                 if b.tipo == p.TIPO_CONTRACCION
                 and b.condicion_postural == p.CONDICION_DINAMICA)
    tramo = contr.duracion_ms / 3
    for i, pos in enumerate(contr.orden_posiciones):
        medio = contr.t_inicio_ms + int(tramo * i + tramo / 2)
        assert contr.posicion_en(medio) == pos
    # Una muestra que cae justo despues del final nominal conserva la
    # ultima posicion, en vez de dejar un hueco sin significado.
    assert contr.posicion_en(contr.t_fin_ms) == contr.orden_posiciones[-1]


def test_una_contraccion_estatica_no_pide_posiciones():
    contr = next(b for b in p.construir_sesion(1)
                 if b.tipo == p.TIPO_CONTRACCION
                 and b.condicion_postural == p.CONDICION_ESTATICA)
    assert contr.posicion_en(contr.t_inicio_ms + 100) == p.POSICION_NINGUNA


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
