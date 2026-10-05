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
    n_rd = p.N_REPOSO_DINAMICO
    assert tipos[p.TIPO_CALIBRACION] == 1
    # Cada reposo en movimiento trae su preparacion y su reposo, como
    # un gesto mas.
    assert tipos[p.TIPO_PREPARACION] == n_gestos + n_rd
    assert tipos[p.TIPO_CONTRACCION] == n_gestos
    assert tipos[p.TIPO_REPOSO_DINAMICO] == n_rd
    assert tipos[p.TIPO_REPOSO] == n_gestos + n_rd


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
    # La preparacion de una repeticion dinamica tambien lleva el orden,
    # porque la pantalla ilumina en ella la posicion de partida, y tiene
    # que ser LA MISMA que la del primer tramo de su contraccion.
    for b in p.construir_sesion(1):
        dinamica = (b.condicion_postural == p.CONDICION_DINAMICA
                    and b.tipo in (p.TIPO_PREPARACION,) + p.TIPOS_CON_RECORRIDO)
        if dinamica:
            assert len(b.orden_posiciones) == len(p.POSICIONES_BRAZO)
            assert set(b.orden_posiciones) == set(p.POSICIONES_BRAZO)
        else:
            assert b.orden_posiciones == ()


def test_la_preparacion_dinamica_anuncia_la_posicion_de_partida():
    bloques = [b for b in p.construir_sesion(3)
               if b.tipo != p.TIPO_CALIBRACION]
    vistas = 0
    for i in range(0, len(bloques), 3):
        prep, contr, _ = bloques[i:i + 3]
        if contr.condicion_postural != p.CONDICION_DINAMICA:
            continue
        vistas += 1
        assert prep.orden_posiciones == contr.orden_posiciones
        # Lo que se ilumina en la preparacion es donde empieza el
        # recorrido de la contraccion que viene.
        assert prep.orden_posiciones[0] == contr.posicion_en(
            contr.t_inicio_ms + 1)
    # 4 gestos por 3 repeticiones dinamicas, mas los reposos en
    # movimiento, que tambien anuncian su posicion de partida.
    assert vistas == 12 + p.N_REPOSO_DINAMICO


def test_la_preparacion_no_escribe_posicion_en_el_csv():
    # Llevar el orden en la preparacion es solo para la pantalla. Si
    # posicion_en() empezara a devolver algo aqui, la columna
    # posicion_brazo diria que el brazo ya estaba colocado durante los
    # 3 s en los que todavia lo esta llevando.
    prep = next(b for b in p.construir_sesion(3)
                if b.tipo == p.TIPO_PREPARACION and b.orden_posiciones)
    for t in (0, prep.duracion_ms // 2, prep.duracion_ms - 1):
        assert prep.posicion_en(prep.t_inicio_ms + t) == p.POSICION_NINGUNA


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
    n_items = p.N_REPETICIONES * len(p.GESTOS_ACTIVOS) + p.N_REPOSO_DINAMICO
    esperado = (p.DUR_CALIBRACION_MS + n_items
                * (p.DUR_PREPARACION_MS + p.DUR_CONTRACCION_MS
                   + p.DUR_REPOSO_MS)) / 1000.0
    assert esperado == 582.0
    assert r["reposos_en_movimiento"] == p.N_REPOSO_DINAMICO
    assert r["duracion_total_s"] == pytest.approx(esperado)
    assert r["ratio_rest_vs_activa"] > 0


# ---------- reposo en movimiento ----------
def _reposos_dinamicos(sid):
    bloques = p.construir_sesion(sid)
    return bloques, [i for i, b in enumerate(bloques)
                     if b.tipo == p.TIPO_REPOSO_DINAMICO]


def test_el_reposo_en_movimiento_es_rest_dinamico_y_con_su_preparacion():
    for sid in (1, 2, 5):
        bloques, idx = _reposos_dinamicos(sid)
        assert len(idx) == p.N_REPOSO_DINAMICO
        for i in idx:
            prep, rd, reposo = bloques[i - 1], bloques[i], bloques[i + 1]
            assert rd.label == p.LABEL_REST
            assert rd.condicion_postural == p.CONDICION_DINAMICA
            assert rd.duracion_ms == p.DUR_CONTRACCION_MS
            # La preparacion tambien es Rest: no anuncia ningun gesto.
            assert prep.tipo == p.TIPO_PREPARACION and prep.label == p.LABEL_REST
            assert reposo.tipo == p.TIPO_REPOSO
            assert prep.repetition_id == rd.repetition_id == reposo.repetition_id


def test_el_reposo_en_movimiento_recorre_las_tres_posiciones():
    bloques, idx = _reposos_dinamicos(1)
    partidas = []
    for i in idx:
        rd = bloques[i]
        tramo = rd.duracion_ms / 3
        vistas = [rd.posicion_en(rd.t_inicio_ms + int(tramo * k + tramo / 2))
                  for k in range(3)]
        assert sorted(vistas) == sorted(p.POSICIONES_BRAZO)
        partidas.append(vistas[0])
    # El punto de partida rota entre los tres, igual que en los gestos.
    assert sorted(partidas) == sorted(p.POSICIONES_BRAZO)


def test_hay_un_reposo_en_movimiento_por_tercio_de_la_sesion():
    for sid in (1, 2, 3, 9):
        bloques, idx = _reposos_dinamicos(sid)
        reps = sorted(bloques[i].repetition_id for i in idx)
        assert reps[0] in (1, 2) and reps[1] in (3, 4) and reps[2] in (5, 6)


def test_los_reposos_en_movimiento_no_alteran_el_orden_de_los_gestos():
    # Se intercalan, no se mezclan con el contrabalanceo de los gestos.
    for sid in (1, 4):
        contracciones = [b.label for b in p.construir_sesion(sid)
                         if b.tipo == p.TIPO_CONTRACCION]
        assert contracciones == p.generar_secuencia_gestos(sid)


def test_la_ubicacion_es_reproducible_y_depende_del_sujeto():
    assert p.ubicar_reposos_dinamicos(1) == p.ubicar_reposos_dinamicos(1)
    distintas = {tuple(p.ubicar_reposos_dinamicos(s)) for s in range(1, 11)}
    assert len(distintas) > 1
