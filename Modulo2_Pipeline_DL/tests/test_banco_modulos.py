"""
Tests del banco de variantes del modulo LMG.

Los CSV se fabrican con estadisticas conocidas, asi que cada metrica
tiene un valor esperado que se puede comprobar a mano.
"""
import csv
import os
import sys

import numpy as np
import pytest

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(AQUI), "banco_modulos"))

import banco as b                                        # noqa: E402


def escribir_prueba(dirpath, variante, ronda, *, reposo=700.0, sd=10.0,
                    delta_puno=200.0, delta_pinza=100.0, sd_mov=30.0,
                    pico_saturado=0, semilla=0):
    """
    Fabrica un CSV con el protocolo real y ruido gaussiano conocido.

    Con reposo=700, sd=10 y delta_pinza=100, el SNR de pinza esperado es
    100/10 = 10, salvo el error de muestreo del ruido.
    """
    rng = np.random.RandomState(semilla)
    ruta = os.path.join(dirpath, f"{variante}_r{ronda}.csv")
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(b.CAMPOS_CSV)
        t = 0
        for fase, dur in b.PROTOCOLO:
            media = reposo
            desv = sd
            if fase == b.FASE_PUNO:
                media += delta_puno
            elif fase == b.FASE_PINZA:
                media += delta_pinza
            elif fase == b.FASE_MOVIMIENTO:
                desv = sd_mov
            for _ in range(int(dur * 100)):          # 100 Hz
                v = rng.randn() * desv + media
                w.writerow([variante, ronda, 1, t, t, fase,
                            f"{v:.4f}", 0, 0, 0, 0, 0, 0, 1])
                t += 10
        for _ in range(pico_saturado):
            w.writerow([variante, ronda, 1, t, t, b.FASE_PINZA,
                        "1950.0", 0, 0, 0, 0, 0, 0, 1])
            t += 10
    return ruta


# ---------- metricas ----------
def test_el_snr_sale_como_la_definicion(tmp_path):
    ruta = escribir_prueba(str(tmp_path), "A", 1, sd=10.0,
                           delta_puno=200.0, delta_pinza=100.0)
    m = b.metricas(ruta)
    assert m["snr_pinza"] == pytest.approx(10.0, abs=1.0)
    assert m["snr_puno"] == pytest.approx(20.0, abs=1.0)
    assert m["reposo_mv"] == pytest.approx(700.0, abs=1.0)


def test_el_artefacto_es_la_razon_de_desviaciones(tmp_path):
    ruta = escribir_prueba(str(tmp_path), "A", 1, sd=10.0, sd_mov=30.0)
    assert b.metricas(ruta)["artefacto_mov"] == pytest.approx(3.0, abs=0.5)


def test_los_margenes_se_recortan_de_cada_tramo(tmp_path):
    import pandas as pd
    ruta = escribir_prueba(str(tmp_path), "A", 1)
    df = pd.read_csv(ruta)
    util = b.recortar_margenes(df)
    # 16 tramos, y de cada uno se van 1000 ms de entrada y 500 de salida.
    n_tramos = len(b.PROTOCOLO)
    assert len(util) == len(df) - n_tramos * 150


def test_una_variante_que_recorta_queda_marcada(tmp_path):
    limpia = b.metricas(escribir_prueba(str(tmp_path), "A", 1))
    sucia = b.metricas(escribir_prueba(str(tmp_path), "B", 1,
                                       pico_saturado=40))
    assert not limpia["satura"]
    assert sucia["satura"] and sucia["n_saturadas"] == 40


def test_una_muestra_suelta_en_1900_no_descalifica(tmp_path):
    # Un pico aislado es ruido de red, no una variante mal disenada.
    m = b.metricas(escribir_prueba(str(tmp_path), "A", 1, pico_saturado=3))
    assert m["n_saturadas"] == 3 and not m["satura"]


# ---------- bloque de movimiento ----------
def test_el_movimiento_recorre_las_tres_posiciones_de_la_tesis():
    from config_captura import POSICIONES_BRAZO
    # Un tercio del bloque por posicion, en el orden de la condicion
    # dinamica, y sin salirse de la lista en los extremos.
    assert [b.posicion_en(f) for f in (0.0, 0.2, 0.34, 0.5, 0.67, 0.99)] == [
        POSICIONES_BRAZO[0], POSICIONES_BRAZO[0], POSICIONES_BRAZO[1],
        POSICIONES_BRAZO[1], POSICIONES_BRAZO[2], POSICIONES_BRAZO[2]]
    assert b.posicion_en(1.0) == POSICIONES_BRAZO[-1]
    assert b.posicion_en(-0.1) == POSICIONES_BRAZO[0]


# ---------- regla de decision ----------
def _resumen(filas):
    import pandas as pd
    return pd.DataFrame(filas)


def test_gana_el_mayor_snr_de_pinza_cuando_no_hay_empate():
    r = _resumen([
        {"variante": "A", "snr_pinza": 10.0, "artefacto_mov": 5.0, "satura": False},
        {"variante": "B", "snr_pinza": 5.0, "artefacto_mov": 1.0, "satura": False},
    ])
    ganadora, motivo = b.elegir(r)
    assert ganadora == "A" and "ventaja" in motivo


def test_el_empate_lo_desempata_el_artefacto_de_movimiento():
    # 9.5 esta dentro del 10% de 10.0, asi que empatan y gana la que
    # menos se ensucia al mover el brazo.
    r = _resumen([
        {"variante": "A", "snr_pinza": 10.0, "artefacto_mov": 5.0, "satura": False},
        {"variante": "B", "snr_pinza": 9.5, "artefacto_mov": 1.2, "satura": False},
    ])
    ganadora, motivo = b.elegir(r)
    assert ganadora == "B" and "Empate" in motivo


def test_justo_fuera_del_10_por_ciento_no_es_empate():
    r = _resumen([
        {"variante": "A", "snr_pinza": 10.0, "artefacto_mov": 5.0, "satura": False},
        {"variante": "B", "snr_pinza": 8.9, "artefacto_mov": 1.0, "satura": False},
    ])
    assert b.elegir(r)[0] == "A"


def test_la_que_satura_queda_fuera_aunque_tenga_el_mejor_snr():
    r = _resumen([
        {"variante": "A", "snr_pinza": 99.0, "artefacto_mov": 0.1, "satura": True},
        {"variante": "B", "snr_pinza": 4.0, "artefacto_mov": 3.0, "satura": False},
    ])
    ganadora, motivo = b.elegir(r)
    assert ganadora == "B" and "saturacion" in motivo


def test_si_todas_saturan_no_hay_ganadora():
    r = _resumen([
        {"variante": "A", "snr_pinza": 9.0, "artefacto_mov": 1.0, "satura": True},
    ])
    assert b.elegir(r)[0] is None


# ---------- extremo a extremo ----------
def test_seis_variantes_dos_rondas_tabla_grafico_y_decision(tmp_path):
    d = str(tmp_path)
    # SMD_11mm es la mejor de verdad. PASANTE_9mm tendria mas SNR pero
    # recorta, asi que la regla tiene que dejarla fuera.
    config = {
        "PASANTE_9mm":  dict(delta_pinza=200.0, pico_saturado=60),
        "PASANTE_11mm": dict(delta_pinza=80.0),
        "PASANTE_13mm": dict(delta_pinza=50.0),
        "SMD_9mm":      dict(delta_pinza=95.0, sd_mov=60.0),
        "SMD_11mm":     dict(delta_pinza=100.0, sd_mov=20.0),
        "SMD_13mm":     dict(delta_pinza=60.0),
    }
    for k, (variante, kw) in enumerate(config.items()):
        for ronda in (1, 2):
            escribir_prueba(d, variante, ronda, semilla=10 * k + ronda, **kw)

    pruebas = [b.metricas(os.path.join(d, f))
               for f in sorted(os.listdir(d)) if f.endswith(".csv")]
    assert len(pruebas) == 12

    resumen = b.resumir(pruebas)
    assert len(resumen) == 6
    assert resumen["rondas"].eq(2).all()
    assert bool(resumen.set_index("variante").loc["PASANTE_9mm", "satura"])

    # SMD_9mm y SMD_11mm empatan en SNR y desempata el artefacto.
    ganadora, motivo = b.elegir(resumen)
    assert ganadora == "SMD_11mm", motivo

    png = b.grafico(pruebas, os.path.join(d, "snr_pinza.png"))
    assert os.path.getsize(png) > 1000
