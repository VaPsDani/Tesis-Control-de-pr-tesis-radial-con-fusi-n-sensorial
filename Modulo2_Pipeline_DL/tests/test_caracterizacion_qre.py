"""
Analisis de la caracterizacion QRE con datos fabricados de valores
conocidos, y lectura de los registros con el formato exacto del firmware.
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(AQUI), "caracterizacion_qre"))

import analizar as A                                      # noqa: E402
import capturar as C                                      # noqa: E402
from canales import NUM_OPT                               # noqa: E402

N = NUM_OPT
MEDIO = N // 2          # modulo con peso 0.5 en los datos fabricados

DELTA = {"Pinch": 20.0, "Tripod": 40.0, "Power": 80.0, "Finger_Ext": 60.0}
SIGMA = 2.0


def sintetico(semilla=0):
    """
    Reposo: v = 100 + ruido de sd 2 en los N modulos. Gesto: + DELTA por
    el modulo k / N. Movimiento: sd 10. Luz encendida: V_apag baja 100 mV
    respecto de apagada. V_enc = amb - v.
    """
    rng = np.random.RandomState(semilla)
    filas, t = [], 0
    peso = (np.arange(N) + 1) / float(N)
    for f in C.plan():
        for _ in range(int(f["duracion_s"] * 100)):
            v = 100 + rng.randn(N) * SIGMA
            if f["fase"] == "gesto":
                v = v + DELTA[f["gesto"]] * peso
            if f["fase"] == "movimiento":
                v = 100 + rng.randn(N) * 10
            amb = np.full(N, 3000.0 if f["fase"] != "luz_encendida" else 2900.0)
            filas.append([t, f["fase"], f["gesto"], f["repeticion"], f["posicion"],
                          *v, 0, 0, 1, 0, 0, 0, *amb, 0])
            t += 10
    return pd.DataFrame(filas, columns=C.CAMPOS_CSV)


def test_deltas_sigma_luz_y_movimiento_salen_como_se_fabricaron():
    m = A.metricas_archivo(sintetico()).set_index("modulo")
    assert m["sigma_mV"].to_numpy() == pytest.approx(SIGMA, rel=0.1)
    for g, d in DELTA.items():
        col = f"DeltaS_{A.NOMBRE_GESTO[g]}_mV"
        assert m.loc[N, col] == pytest.approx(d, abs=1.0)          # peso 1
        assert m.loc[MEDIO, col] == pytest.approx(d / 2, abs=1.0)  # peso 0.5
    # El minimo es la pinza: 20 / 2 = 10 en el modulo N.
    assert m.loc[N, "DeltaS_sigma_min"] == pytest.approx(10, rel=0.15)
    assert m["luz_sobre_V_apag_mV"].to_numpy() == pytest.approx(-100.0)
    assert m.loc[N, "sd_movimiento_mV"] == pytest.approx(10, rel=0.15)
    assert m.loc[N, "movimiento_sobre_DeltaS_min"] == pytest.approx(0.5, rel=0.2)
    # V_enc = amb - v.
    assert m.loc[1, "V_enc_reposo_mV"] == pytest.approx(2900.0, abs=1.0)


def test_los_registros_del_firmware_se_leen():
    c = ["[ASENTAMIENTO] modulo 3 encender: delta=812 cuentas t90=120 us "
         "t95=180 us t99=400 us paso=22.5 us",
         "[ASENTAMIENTO] modulo 3 apagar: delta=-805 cuentas t90=200 us "
         "t95=260 us t99=350 us paso=22.1 us  AVISO: no asentado en 3 ms"]
    x = ["[DIAFONIA] modulo 2: base=3050.0 otros=3040.0 propio=2800.0 mV "
         "diafonia=10.0 mV (4.0% de su senal de 250.0 mV)"]
    t = ["[AUTOTEST] ciclo: medio 5400.0 us, p95 5500 us, maximo 5600 us, de 10000 us disponibles",
         "[AUTOTEST] modulo 5: V_enc=200.0 V_apag=3080.0 v=2880.0 sd_v=1.20 mV "
         "SATURADO TOPE_ADC(informativo)",
         "[AUTOTEST] modulo 6: V_enc=900.0 V_apag=3080.0 v=2180.0 sd_v=1.10 mV OK"]
    assert A.asentamiento(c) == {3: (260.0, 400.0)}      # el peor de los dos
    assert A.diafonia(x) == {2: 4.0}
    b = A.banderas(t)
    assert b[5].startswith("SATURADO") and b[6] == "OK" and len(b) == 2


def test_salidas_completas(tmp_path):
    ruta = tmp_path / "P01_sin_carcasa.csv"
    sintetico().to_csv(ruta, index=False)
    log_t = tmp_path / "t.txt"
    log_t.write_text("[AUTOTEST] modulo 2: V_enc=200.0 V_apag=3080.0 v=2880.0 "
                     "sd_v=1.20 mV SATURADO\n", encoding="utf-8")
    sal = tmp_path / "res"
    assert A.main(["--csv", str(ruta), "--log_t", str(log_t), "--salida", str(sal)]) == 0
    for f in ("tabla_6_1.csv", "tabla_6_1.md", "figura_6_1.png", "figura_6_2.png",
              "figura_6_3.png", "resumen.md", "metricas_modulos.csv"):
        assert (sal / f).exists(), f
    t = pd.read_csv(sal / "tabla_6_1.csv")
    assert t["satura"].tolist() == [False, True] + [False] * (N - 2)
    assert "no forma parte del conjunto de datos" in (sal / "resumen.md").read_text(encoding="utf-8")
