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

    Con reposo=700, sd=10 y delta_pinza=100, el dS de pinza esperado es
    100 mV y el SNR 100/10 = 10, salvo el error de muestreo del ruido.
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


PARAMETROS = {"corriente_media_ma": 13.0, "duty": 369, "rp_a_por_w": 0.5,
              "phi_e_mw": {"PASANTE": 4.0, "SMD": 2.0}}


# ---------- metricas ----------
def test_el_protocolo_tiene_7_punos_7_pinzas_y_movimiento():
    fases = [f for f, _ in b.PROTOCOLO]
    assert fases.count(b.FASE_PUNO) == 7 and fases.count(b.FASE_PINZA) == 7
    assert fases[-1] == b.FASE_MOVIMIENTO
    # Cada contraccion va precedida de reposo.
    assert all(fases[i - 1] == b.FASE_REPOSO for i, f in enumerate(fases)
               if f in (b.FASE_PUNO, b.FASE_PINZA))
    assert sum(d for _, d in b.PROTOCOLO) == 160


def test_ds_snr_y_cv_salen_como_la_definicion(tmp_path):
    ruta = escribir_prueba(str(tmp_path), "A", 1, sd=10.0,
                           delta_puno=200.0, delta_pinza=100.0)
    m = b.metricas(ruta)
    assert m["n_rep_pinza"] == 7 and m["n_rep_puno"] == 7
    assert m["ds_pinza_mv"] == pytest.approx(100.0, abs=2.0)
    assert m["snr_pinza"] == pytest.approx(10.0, abs=1.0)
    assert m["snr_puno"] == pytest.approx(20.0, abs=1.0)
    assert m["reposo_mv"] == pytest.approx(700.0, abs=1.0)
    # Sin variacion entre repeticiones, solo el ruido: CV pequeno.
    assert m["cv_pinza"] < 0.05


def test_una_bajada_cuenta_igual_que_una_subida(tmp_path):
    m = b.metricas(escribir_prueba(str(tmp_path), "A", 1, delta_pinza=-100.0))
    assert m["ds_pinza_mv"] < 0 and m["snr_pinza"] == pytest.approx(10.0, abs=1.0)


def test_el_indice_divide_por_phi_e_y_rp():
    import pandas as pd
    det = pd.DataFrame({"variante": ["SMD_11mm", "PASANTE_9mm"],
                        "ds_puno_mv": [200.0, 200.0],
                        "ds_pinza_mv": [-100.0, 100.0]})
    det = b.anadir_indice(det, PARAMETROS)
    # 100 mV / (2 mW * 0.5 A/W) = 100 mV/mA. El pasante emite el doble.
    assert det["i_pinza"].tolist() == pytest.approx([100.0, 50.0])


def test_sin_parametros_se_dice_que_falta():
    falta = b.faltan_parametros({"rp_a_por_w": None, "phi_e_mw": {"SMD": 2.0}},
                                ["SMD_9mm", "PASANTE_9mm"])
    assert falta == ["rp_a_por_w", "phi_e_mw.PASANTE"]
    assert b.faltan_parametros(PARAMETROS, ["SMD_9mm", "PASANTE_9mm"]) == []


def test_el_duty_da_la_corriente_media():
    # 18 mA al 100% -> 13/18 de 511 = 369.
    assert b.duty_para(18.0, 13.0) == 369
    with pytest.raises(ValueError):
        b.duty_para(12.0, 13.0)


def test_el_artefacto_es_la_razon_de_desviaciones(tmp_path):
    ruta = escribir_prueba(str(tmp_path), "A", 1, sd=10.0, sd_mov=30.0)
    assert b.metricas(ruta)["artefacto_mov"] == pytest.approx(3.0, abs=0.5)


def test_los_margenes_se_recortan_de_cada_tramo(tmp_path):
    import pandas as pd
    ruta = escribir_prueba(str(tmp_path), "A", 1)
    df = pd.read_csv(ruta)
    util = b.recortar_margenes(df)
    # 30 tramos, y de cada uno se van 1000 ms de entrada y 500 de salida.
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
        {"variante": "A", "i_pinza": 10.0, "artefacto_mov": 5.0, "satura": False},
        {"variante": "B", "i_pinza": 5.0, "artefacto_mov": 1.0, "satura": False},
    ])
    ganadora, motivo = b.elegir(r)
    assert ganadora == "A" and "ventaja" in motivo


def test_el_empate_lo_desempata_el_artefacto_de_movimiento():
    # 9.5 esta dentro del 10% de 10.0, asi que empatan y gana la que
    # menos se ensucia al mover el brazo.
    r = _resumen([
        {"variante": "A", "i_pinza": 10.0, "artefacto_mov": 5.0, "satura": False},
        {"variante": "B", "i_pinza": 9.5, "artefacto_mov": 1.2, "satura": False},
    ])
    ganadora, motivo = b.elegir(r)
    assert ganadora == "B" and "Empate" in motivo


def test_justo_fuera_del_10_por_ciento_no_es_empate():
    r = _resumen([
        {"variante": "A", "i_pinza": 10.0, "artefacto_mov": 5.0, "satura": False},
        {"variante": "B", "i_pinza": 8.9, "artefacto_mov": 1.0, "satura": False},
    ])
    assert b.elegir(r)[0] == "A"


def test_la_que_satura_queda_fuera_aunque_tenga_el_mejor_snr():
    r = _resumen([
        {"variante": "A", "i_pinza": 99.0, "artefacto_mov": 0.1, "satura": True},
        {"variante": "B", "i_pinza": 4.0, "artefacto_mov": 3.0, "satura": False},
    ])
    ganadora, motivo = b.elegir(r)
    assert ganadora == "B" and "saturacion" in motivo


def test_si_todas_saturan_no_hay_ganadora():
    r = _resumen([
        {"variante": "A", "i_pinza": 9.0, "artefacto_mov": 1.0, "satura": True},
    ])
    assert b.elegir(r)[0] is None


def test_la_tabla_final_ordena_con_la_regla_y_las_saturadas_al_final():
    r = _resumen([
        {"variante": "A", "i_pinza": 99.0, "artefacto_mov": 0.1, "satura": True},
        {"variante": "B", "i_pinza": 10.0, "artefacto_mov": 5.0, "satura": False},
        {"variante": "C", "i_pinza": 9.5, "artefacto_mov": 1.0, "satura": False},
        {"variante": "D", "i_pinza": 4.0, "artefacto_mov": 1.0, "satura": False},
    ])
    t = b.ordenar(r)
    # B y C empatan y C se ensucia menos. A satura y va al final.
    assert t["variante"].tolist() == ["C", "B", "D", "A"]
    assert t["puesto"].tolist() == [1, 2, 3, 4]


# ---------- extremo a extremo ----------
def test_seis_variantes_dos_rondas_tabla_grafico_y_decision(tmp_path):
    import pandas as pd
    d = str(tmp_path)
    # Con Phi_e del pasante el doble que la del SMD, un pasante necesita
    # el doble de dS para el mismo I. SMD_11mm es la mejor de verdad.
    # PASANTE_9mm tendria mas I pero recorta, asi que queda fuera.
    config = {
        "PASANTE_9mm":  dict(delta_pinza=400.0, pico_saturado=60),
        "PASANTE_11mm": dict(delta_pinza=160.0),
        "PASANTE_13mm": dict(delta_pinza=100.0),
        "SMD_9mm":      dict(delta_pinza=95.0, sd_mov=60.0),
        "SMD_11mm":     dict(delta_pinza=100.0, sd_mov=20.0),
        "SMD_13mm":     dict(delta_pinza=60.0),
    }
    for k, (variante, kw) in enumerate(config.items()):
        for ronda in (1, 2):
            escribir_prueba(d, variante, ronda, semilla=10 * k + ronda, **kw)

    det = pd.DataFrame([b.metricas(os.path.join(d, f))
                        for f in sorted(os.listdir(d)) if f.endswith(".csv")])
    assert len(det) == 12
    det = b.anadir_indice(det, PARAMETROS)

    resumen = b.resumir(det)
    assert len(resumen) == 6
    assert resumen["rondas"].eq(2).all()
    assert bool(resumen.set_index("variante").loc["PASANTE_9mm", "satura"])

    # SMD_9mm y SMD_11mm empatan en I y desempata el artefacto.
    tabla = b.ordenar(resumen)
    assert tabla["variante"].iloc[0] == "SMD_11mm"
    assert tabla["variante"].iloc[-1] == "PASANTE_9mm"

    png = b.grafico(det, os.path.join(d, "i_pinza.png"))
    assert os.path.getsize(png) > 1000
