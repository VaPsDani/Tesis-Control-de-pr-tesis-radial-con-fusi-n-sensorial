"""
Formato del CSV de la captura OMG y modo de caracterizacion.
"""
import csv
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(AQUI), "caracterizacion_qre"))

import adquisicion as A                                   # noqa: E402
import capturar as C                                      # noqa: E402
from canales import CANALES_AMB, CANALES_OPT, NUM_OPT     # noqa: E402


def test_el_firmware_emite_todos_los_campos_y_el_csv_los_guarda():
    # 23 campos con 8 modulos, 15 con 4.
    assert len(A.CAMPOS_FIRMWARE) == 1 + NUM_OPT + 6 + NUM_OPT
    assert A.CAMPOS_CSV[3:3 + NUM_OPT] == CANALES_OPT
    assert A.CAMPOS_CSV[-NUM_OPT:] == CANALES_AMB


def test_el_escritor_pone_cada_valor_en_su_columna(tmp_path):
    class Bloque:
        repetition_id, label, tipo = 1, 2, "contraccion"
        es_calibracion, condicion_postural, t_inicio_ms = 0, "estatica", 0
        def en_margen(self, t): return 0
        def posicion_en(self, t): return ""

    ruta = str(tmp_path / "s.csv")
    e = A.EscritorCSV(ruta, subject_id=7)
    e.abrir()
    valores = ([float(i) for i in range(1, NUM_OPT + 1)] + [0.1] * 6
               + [3000.0 + i for i in range(NUM_OPT)])
    e.escribir(A.Muestra(123, valores, 0.0, 0), Bloque(), 0)
    e.cerrar()
    fila = list(csv.DictReader(open(ruta, encoding="utf-8")))[0]
    assert float(fila[CANALES_OPT[-1]]) == float(NUM_OPT)
    assert float(fila["amb1"]) == 3000.0
    assert float(fila[CANALES_AMB[-1]]) == 3000.0 + NUM_OPT - 1
    assert fila["label"] == "2"


def test_el_plan_de_caracterizacion_tiene_lo_pedido():
    f = C.plan()
    gestos = [x for x in f if x["fase"] == "gesto"]
    assert len(gestos) == 4 * 5 and all(x["duracion_s"] == 5.0 for x in gestos)
    assert sum(x["fase"] == "movimiento" for x in f) == 3 * 3
    assert [x["fase"] for x in f[-2:]] == ["luz_encendida", "luz_apagada"]
    assert f[0] == dict(fase="reposo", duracion_s=10.0, gesto="", repeticion="",
                        posicion="")


def test_la_etiqueta_sale_del_reloj_del_esp32_contra_los_marcadores():
    fases = [dict(fase="reposo", gesto="", repeticion="", posicion=""),
             dict(fase="gesto", gesto="Pinch", repeticion=1, posicion="")]
    m = [A.Muestra(t, [0.0] * 22, 0.0, 0) for t in (5, 10, 20, 30)]
    # La muestra de t=30 llego antes que el marcador de su fase: igual va
    # a gesto, porque se etiqueta al final.
    filas = C.etiquetar(m, [(30, 1), (10, 0)], fases)
    assert [r[0] for r in filas] == [10, 20, 30]           # t=5 antes del primero
    assert [r[1] for r in filas] == ["reposo", "reposo", "gesto"]
