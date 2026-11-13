"""
prueba_en_linea.py - Prueba en linea con la protesis (A28)
==========================================================
Protesis transradial - Etapa 4

QUE HACE:
  Muestra 20 indicaciones en orden aleatorio, con semilla: 5 de cada
  gesto activo, 10 con el antebrazo apoyado y 10 con el brazo al frente.
  Mientras tanto lee del ESP32 (Modulo 3) cada cambio de clase predicha,
  con la hora de la PC, y al final evalua cada intento.

  Cada intento: 3 s de preparacion con el gesto y la postura, la
  indicacion de AHORA, 5 s de ventana, y 5 s de descanso.

CRITERIO (A28):
  Exito si la clase pedida se mantiene al menos 1 s seguido dentro de los
  5 s siguientes a la indicacion. Tiempo hasta completar: desde la
  indicacion hasta que se cumple ese segundo, o sea el inicio del tramo
  correcto mas 1 s. Se reporta tambien el tiempo hasta la primera
  prediccion correcta.

ANTES DE EMPEZAR:
  El modelo INT8 cargado en el Modulo 3 tiene que ser el entrenado SIN
  este participante (entrenar_modelo.py --modo final --excluir <id>), y el
  participante tiene que estar calibrado ('C' en el firmware).

  Reposo mantiene la posicion de la mano (A25): entre intentos la mano no
  se abre sola. Si hace falta empezar cada intento con la mano abierta,
  el participante hace una extension en el descanso.

USO:
  python prueba_en_linea.py --puerto COM4 --participante 3 --salida prueba_s03
  python prueba_en_linea.py --simulado --salida prueba_simulada --escala 0.2

AGARRES:
  La segunda parte, 3 objetos por 5 intentos con la mano en un soporte
  fijo, se anota a mano en planilla_agarres.csv, que esta junto a este
  script. Exito si el objeto queda sostenido 3 s.
"""

import argparse
import csv
import json
import os
import queue
import re
import sys
import threading
import time

import numpy as np

NOMBRES = ["Rest", "Pinch", "Tripod", "Power", "Finger_Ext"]
TEXTO_GESTO = {1: "PINZA", 2: "TRIPODE", 3: "PUNO", 4: "EXTENSION"}
POSTURAS = {"apoyado": "ANTEBRAZO APOYADO", "frente": "BRAZO AL FRENTE"}
GESTOS_ACTIVOS = [1, 2, 3, 4]
REPETICIONES_POR_GESTO = 5
PREPARACION_S, VENTANA_S, DESCANSO_S, SOSTENER_S = 3.0, 5.0, 5.0, 1.0
LINEA_GESTO = re.compile(r"\[INFERENCIA\] Gesto: \S+ \(clase (\d)\)")


# ============================================================
# PLAN Y EVALUACION, SIN HARDWARE
# ============================================================
def plan(semilla: int) -> list:
    """
    20 intentos: 5 por gesto, 10 apoyado y 10 al frente, en orden
    aleatorio. Como 5 es impar, dos gestos van 3 apoyados y 2 al frente y
    los otros dos al reves, y cuales son tambien se sortea.
    """
    rng = np.random.RandomState(semilla)
    tres_apoyados = set(rng.choice(GESTOS_ACTIVOS, 2, replace=False).tolist())
    intentos = []
    for g in GESTOS_ACTIVOS:
        n_ap = 3 if g in tres_apoyados else 2
        intentos += [(g, "apoyado")] * n_ap + [(g, "frente")] * (REPETICIONES_POR_GESTO - n_ap)
    orden = rng.permutation(len(intentos))
    return [intentos[i] for i in orden]


def evaluar_intento(cambios, t0: float, clase: int,
                    ventana_s: float = VENTANA_S, sostener_s: float = SOSTENER_S) -> dict:
    """
    cambios: lista ordenada de (t, clase predicha), con la clase vigente
    desde ese instante. Evalua la ventana [t0, t0 + ventana_s].
    """
    fin = t0 + ventana_s
    # Clase vigente en cada tramo de la ventana.
    vigente = None
    for t, c in cambios:
        if t <= t0:
            vigente = c
    tramos = []
    inicio = t0
    for t, c in cambios:
        if t0 < t < fin:
            tramos.append((inicio, t, vigente))
            inicio, vigente = t, c
    tramos.append((inicio, fin, vigente))

    primer_acierto = next((round(a - t0, 3) for a, z, c in tramos if c == clase), None)
    for a, z, c in tramos:
        if c == clase and z - a >= sostener_s:
            return {"exito": True,
                    "tiempo_hasta_completar_s": round(a - t0 + sostener_s, 3),
                    "primer_acierto_s": primer_acierto}
    return {"exito": False, "tiempo_hasta_completar_s": None,
            "primer_acierto_s": primer_acierto}


def resumir(resultados: list) -> dict:
    def tasa(filas):
        return float(np.mean([r["exito"] for r in filas])) if filas else None
    tiempos = [r["tiempo_hasta_completar_s"] for r in resultados if r["exito"]]
    return {
        "tasa_exito": tasa(resultados),
        "exitos": int(sum(r["exito"] for r in resultados)),
        "intentos": len(resultados),
        "por_gesto": {TEXTO_GESTO[g]: tasa([r for r in resultados if r["clase"] == g])
                      for g in GESTOS_ACTIVOS},
        "por_postura": {p: tasa([r for r in resultados if r["postura"] == p])
                        for p in POSTURAS},
        "tiempo_hasta_completar_mediana_s": float(np.median(tiempos)) if tiempos else None,
        "tiempo_hasta_completar_iqr_s": ([float(np.percentile(tiempos, 25)),
                                          float(np.percentile(tiempos, 75))]
                                         if tiempos else None),
    }


# ============================================================
# LECTURA DEL ESP32
# ============================================================
class Lector(threading.Thread):
    """Lee el puerto y deja (hora de la PC, clase) en una cola."""

    def __init__(self, puerto, baudios, cola, simulado=False):
        super().__init__(daemon=True)
        self.cola, self.simulado = cola, simulado
        self.parar = threading.Event()
        self.pedida = None                      # solo para el simulador
        if not simulado:
            import serial
            self.ser = serial.Serial(puerto, baudios, timeout=0.2)
            time.sleep(2.0)                     # el ESP32 se reinicia al abrir
            self.ser.write(b"G")                # activar el control por gestos

    def run(self):
        if self.simulado:
            return self._simular()
        while not self.parar.is_set():
            linea = self.ser.readline().decode("utf-8", errors="ignore")
            m = LINEA_GESTO.search(linea)
            if m:
                self.cola.put((time.monotonic(), int(m.group(1))))

    def _simular(self):
        """Responde a la clase pedida con una demora y algun error."""
        rng = np.random.RandomState(0)
        actual = 0
        while not self.parar.is_set():
            objetivo = self.pedida if self.pedida is not None else 0
            if objetivo != actual:
                time.sleep(rng.uniform(0.3, 0.9))
                actual = objetivo if rng.rand() > 0.15 else int(rng.choice([1, 2, 3, 4]))
                self.cola.put((time.monotonic(), actual))
            time.sleep(0.02)


# ============================================================
# PANTALLA
# ============================================================
def pantalla():
    """Ventana grande o, sin entorno grafico, None y consola."""
    try:
        import tkinter as tk
        r = tk.Tk()
        r.title("Prueba en linea")
        r.attributes("-fullscreen", True)
        r.bind("<Escape>", lambda e: r.attributes("-fullscreen", False))
        r.configure(bg="#1f3a5f")
        labels = [tk.Label(r, fg="white", bg="#1f3a5f", font=("Helvetica", s, "bold"))
                  for s in (40, 120, 50, 90)]
        for l in labels:
            l.pack(pady=20)
        return r, labels
    except Exception as e:
        print(f"(sin ventana: {e}. Sigo por consola.)")
        return None, None


def mostrar(ventana, labels, fondo, textos):
    if ventana is None:
        print("  " + "  |  ".join(t for t in textos if t))
        return
    ventana.configure(bg=fondo)
    for l, t in zip(labels, textos):
        l.configure(text=t, bg=fondo)
    ventana.update()


def correr(args):
    cola = queue.Queue()
    lector = Lector(args.puerto, args.baudios, cola, args.simulado)
    lector.start()
    ventana, labels = pantalla()
    cambios = []

    def drenar(hasta):
        while time.monotonic() < hasta:
            try:
                cambios.append(cola.get(timeout=0.02))
            except queue.Empty:
                pass
            if ventana is not None:
                ventana.update()

    resultados = []
    intentos = plan(args.semilla)
    e = args.escala
    for n, (clase, postura) in enumerate(intentos, 1):
        lector.pedida = None
        mostrar(ventana, labels, "#7a4f00",
                [f"Intento {n} de {len(intentos)}  ·  PREPARESE",
                 TEXTO_GESTO[clase], POSTURAS[postura], ""])
        drenar(time.monotonic() + PREPARACION_S * e)
        t0 = time.monotonic()
        lector.pedida = clase
        mostrar(ventana, labels, "#1f6f3a", ["AHORA", TEXTO_GESTO[clase],
                                             POSTURAS[postura], ""])
        drenar(t0 + VENTANA_S * e)
        lector.pedida = None
        r = evaluar_intento(cambios, t0, clase, VENTANA_S * e, SOSTENER_S * e)
        r.update({"intento": n, "clase": clase, "gesto": TEXTO_GESTO[clase],
                  "postura": postura})
        resultados.append(r)
        print(f"[{n:2d}] {TEXTO_GESTO[clase]:9s} {postura:7s} "
              f"{'EXITO' if r['exito'] else 'fallo'}  "
              f"completo en {r['tiempo_hasta_completar_s']}")
        mostrar(ventana, labels, "#1f3a5f", ["DESCANSE", "", "", ""])
        drenar(time.monotonic() + DESCANSO_S * e)

    lector.parar.set()
    if ventana is not None:
        ventana.destroy()
    return resultados, cambios


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--puerto", default="COM4")
    ap.add_argument("--baudios", type=int, default=115200)
    ap.add_argument("--participante", type=int, default=0,
                    help="subject_id, tambien semilla del orden")
    ap.add_argument("--semilla", type=int, default=None)
    ap.add_argument("--salida", default="prueba_en_linea")
    ap.add_argument("--simulado", action="store_true")
    ap.add_argument("--escala", type=float, default=1.0,
                    help="factor de tiempo, solo para probar el flujo")
    args = ap.parse_args(argv)
    if args.semilla is None:
        args.semilla = args.participante

    resultados, cambios = correr(args)
    os.makedirs(args.salida, exist_ok=True)
    with open(os.path.join(args.salida, "intentos.csv"), "w", newline="",
              encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(resultados[0]))
        w.writeheader()
        w.writerows(resultados)
    t_ini = cambios[0][0] if cambios else 0.0
    with open(os.path.join(args.salida, "predicciones.csv"), "w", newline="",
              encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["t_s", "clase", "gesto"])
        w.writerows([(round(t - t_ini, 3), c, NOMBRES[c]) for t, c in cambios])
    resumen = resumir(resultados)
    resumen.update({"participante": args.participante, "semilla": args.semilla,
                    "simulado": bool(args.simulado), "escala_tiempo": args.escala})
    with open(os.path.join(args.salida, "resumen.json"), "w", encoding="utf-8") as f:
        json.dump(resumen, f, indent=2, ensure_ascii=False)
    print(f"\nTasa de exito {resumen['exitos']}/{resumen['intentos']} = "
          f"{100 * resumen['tasa_exito']:.0f}%, tiempo hasta completar (mediana) "
          f"{resumen['tiempo_hasta_completar_mediana_s']} s")
    print(f"[SALIDA] {args.salida}")


if __name__ == "__main__":
    sys.exit(main())
