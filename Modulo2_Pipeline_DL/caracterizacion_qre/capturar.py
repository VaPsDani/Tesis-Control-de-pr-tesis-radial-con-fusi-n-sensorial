"""
capturar.py - Captura de caracterizacion de los modulos QRE1113
================================================================
Protesis transradial - OMG (QRE1113) + IMU

PRUEBAS PRELIMINARES, NO ES PARTE DEL CONJUNTO DE DATOS.

Secuencia guiada por consola, con un tono en cada cambio y un marcador
de sincronizacion ('M') al inicio de cada fase:

  1. 10 s de reposo
  2. 5 repeticiones de cada gesto (pinza, tripode, puno, extension):
     5 s de gesto y 5 s de reposo
  3. 3 recorridos por las 3 posiciones dinamicas con la mano relajada,
     3,3 s por posicion
  4. 10 s con la luz de la sala encendida y 10 s apagada, mano en reposo

Unos 4 min 20 s. Las muestras se etiquetan AL FINAL por el reloj del
ESP32 contra los marcadores, igual que la app de captura, asi que una
muestra que llega antes que su [MARK] no queda con la fase anterior.

Salidas, en --salida:
  <id>_<carcasa>_<fecha>.csv   timestamp_ms, fase, gesto, repeticion,
                               posicion, v1..v8, ax..gz, amb1..amb8, ts_pc_ms
  <id>_<carcasa>_<fecha>.json  configuracion del firmware y del ensayo

USO:
  python capturar.py --puerto COM5 --carcasa sin_carcasa --participante P01
  python capturar.py --simulado --carcasa sin_carcasa --escala 0.05
"""

import argparse
import csv
import json
import os
import queue
import sys
import time
from datetime import datetime

_M2 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in (os.path.join(_M2, "common"), os.path.join(_M2, "captura")):
    if _d not in sys.path:
        sys.path.insert(0, _d)

from canales import CAMPOS_FIRMWARE                      # noqa: E402
from adquisicion import LectorSerie                     # noqa: E402
from config_captura import (BAUDIOS_DEFECTO, POSICIONES_BRAZO,  # noqa: E402
                            TEXTO_POSICION)
from protocolo import GESTOS_ACTIVOS, NOMBRES_GESTOS     # noqa: E402

CARCASAS = ("sin_carcasa", "con_carcasa")
REPETICIONES_GESTO = 5
RECORRIDOS = 3
CAMPOS_CSV = (["timestamp_ms", "fase", "gesto", "repeticion", "posicion"]
              + CAMPOS_FIRMWARE[1:] + ["ts_pc_ms"])

TEXTO = {
    "reposo": "REPOSO. Mano relajada, brazo quieto.",
    "gesto": "GESTO {gesto}. Fuerza moderada y mantenga.",
    "movimiento": "MANO RELAJADA. Lleve el brazo a: {posicion}",
    "luz_encendida": "LUZ DE LA SALA ENCENDIDA. Mano en reposo.",
    "luz_apagada": "LUZ DE LA SALA APAGADA. Mano en reposo.",
}


def plan():
    """Lista de fases: dict con fase, duracion_s, gesto, repeticion, posicion."""
    fases = [dict(fase="reposo", duracion_s=10.0)]
    for g in GESTOS_ACTIVOS:
        for r in range(1, REPETICIONES_GESTO + 1):
            fases.append(dict(fase="gesto", duracion_s=5.0,
                              gesto=NOMBRES_GESTOS[g], repeticion=r))
            fases.append(dict(fase="reposo", duracion_s=5.0))
    for r in range(1, RECORRIDOS + 1):
        for pos in POSICIONES_BRAZO:
            fases.append(dict(fase="movimiento", duracion_s=3.3,
                              posicion=pos, repeticion=r))
    fases.append(dict(fase="luz_encendida", duracion_s=10.0))
    fases.append(dict(fase="luz_apagada", duracion_s=10.0))
    for f in fases:
        f.setdefault("gesto", "")
        f.setdefault("repeticion", "")
        f.setdefault("posicion", "")
    return fases


def etiquetar(muestras, marcadores, fases):
    """
    Filas del CSV. Cada muestra toma la fase del ultimo marcador anterior
    a su timestamp del ESP32. Las de antes del primer marcador se tiran.

    muestras: Muestra de adquisicion.py. marcadores: (t_esp32, indice).
    """
    marcas = sorted(marcadores)
    filas, j = [], -1
    for m in sorted(muestras, key=lambda x: x.t_esp32):
        while j + 1 < len(marcas) and m.t_esp32 >= marcas[j + 1][0]:
            j += 1
        if j < 0:
            continue
        f = fases[marcas[j][1]]
        filas.append([m.t_esp32, f["fase"], f["gesto"], f["repeticion"],
                      f["posicion"], *m.valores, m.ts_pc_ms])
    return filas


def tono():
    try:
        import winsound
        winsound.Beep(880, 120)
    except Exception:
        print("\a", end="", flush=True)


def capturar(args):
    fases = plan()
    total_s = sum(f["duracion_s"] for f in fases) * args.escala
    cola = queue.Queue(maxsize=100000)
    lector = LectorSerie(args.puerto, cola, baudios=args.baudios,
                         simulado=args.simulado)
    lector.abrir()
    lector.start()
    lector.enviar("L")
    time.sleep(1.0)

    print(f"\nCaracterizacion {args.carcasa}, {len(fases)} fases, "
          f"{total_s:.0f} s. Ctrl+C aborta.\n")
    muestras, abortada = [], False

    def vaciar(hasta):
        while time.monotonic() < hasta:
            try:
                muestras.append(cola.get(timeout=0.05))
            except queue.Empty:
                pass

    try:
        for i, f in enumerate(fases):
            lector.marcar_bloque(i)
            tono()
            texto = TEXTO[f["fase"]].format(
                gesto=f["gesto"].upper(),
                posicion=TEXTO_POSICION.get(f["posicion"], f["posicion"]))
            print(f"[{i + 1:3d}/{len(fases)}] {texto}  ({f['duracion_s']:.1f} s)")
            vaciar(time.monotonic() + f["duracion_s"] * args.escala)
    except KeyboardInterrupt:
        abortada = True
        print("\nABORTADA por el operador.")
    finally:
        lector.enviar("S")
        vaciar(time.monotonic() + 0.5)
        lector.detener()

    filas = etiquetar(muestras, lector.marcadores, fases)
    os.makedirs(args.salida, exist_ok=True)
    base = os.path.join(args.salida, f"{args.participante}_{args.carcasa}_"
                        f"{datetime.now():%Y%m%d_%H%M%S}")
    with open(base + ".csv", "w", newline="", encoding="utf-8") as fcsv:
        w = csv.writer(fcsv)
        w.writerow(CAMPOS_CSV)
        w.writerows(filas)
    meta = {
        "aviso": "Prueba preliminar de caracterizacion. No forma parte del "
                 "conjunto de datos.",
        "participante": args.participante,
        "carcasa": args.carcasa,
        "placas_por_posicion": args.placas,
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "abortada": abortada,
        "simulado": bool(args.simulado),
        "escala_tiempo": args.escala,
        "fases": fases,
        "filas": len(filas),
        "version_firmware": lector.version_firmware,
        "optica": lector.optica,
        "banner_firmware": lector.banner,
        "huecos": lector.stats.huecos,
        "muestras_perdidas_est": lector.stats.muestras_perdidas_est,
    }
    with open(base + ".json", "w", encoding="utf-8") as fj:
        json.dump(meta, fj, indent=2, ensure_ascii=False)
    print(f"\n{len(filas)} filas, {lector.stats.huecos} huecos.")
    print(f"[SALIDA] {base}.csv")
    return 1 if abortada else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--carcasa", required=True, choices=CARCASAS)
    ap.add_argument("--participante", default="P01")
    ap.add_argument("--placas", default="1,2,3,4,5,6,7,8",
                    help="placa fisica en cada posicion 1 a 8")
    ap.add_argument("--puerto", default="COM5")
    ap.add_argument("--baudios", type=int, default=BAUDIOS_DEFECTO)
    ap.add_argument("--salida", default=os.path.join(os.path.dirname(
        os.path.abspath(__file__)), "capturas"))
    ap.add_argument("--simulado", action="store_true")
    ap.add_argument("--escala", type=float, default=1.0,
                    help="factor de tiempo, solo para probar el flujo")
    return capturar(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
