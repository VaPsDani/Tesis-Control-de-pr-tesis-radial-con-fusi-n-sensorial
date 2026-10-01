#!/usr/bin/env python3
"""
Banco de pruebas de las variantes del modulo LMG.

Sirve para elegir entre las 6 variantes del PCB (LED pasante o SMD, a 9,
11 o 13 mm del OPT101) midiendolas sobre el mismo antebrazo, una por una,
con un solo modulo conectado al ESP32.

POR QUE UN BANCO Y NO LA APP DE CAPTURA:
  La app de captura corre el protocolo de la tesis, 8.7 min con 4 gestos
  y 6 repeticiones, y escribe el CSV que consume el pipeline. Aqui hace
  falta lo contrario: 80 s, dos gestos, un solo canal, y unas metricas de
  calidad de senal que el pipeline no calcula. Lo que si se reutiliza es
  el lector del puerto y los tonos, que ya estan probados.

PROTOCOLO POR VARIANTE (80 s):
  10 s de reposo, 3 x (5 s de puno + 5 s de reposo), 3 x (5 s de pinza +
  5 s de reposo) y 10 s moviendo el brazo sin hacer ningun gesto.

  El bloque de movimiento sin gesto es el que separa una variante que
  mide musculo de una que mide el modulo bailando sobre la piel. Sin el,
  una variante con mal acoplamiento mecanico puede dar buen SNR y aun asi
  ser la peor en uso real.

DOS RONDAS POR VARIANTE:
  La segunda ronda se hace despues de despegar y volver a colocar el
  modulo. La diferencia entre rondas mide la repetibilidad del montaje,
  que es tan decisiva como el SNR: una variante con SNR alto pero que
  cambia mucho entre colocaciones no sirve para 10 participantes.

USO:
  python banco.py capturar --variante SMD_11mm --ronda 1 --puerto COM3
  python banco.py analizar

  Ver el README de esta carpeta para el modo del firmware.
"""

import argparse
import csv
import json
import os
import queue
import sys
import time
from datetime import datetime

AQUI = os.path.dirname(os.path.abspath(__file__))
_M2 = os.path.dirname(AQUI)
for _d in (_M2, os.path.join(_M2, "captura")):
    if _d not in sys.path:
        sys.path.insert(0, _d)

# Margenes de entrada y salida de cada fase. Son los mismos que usa el
# protocolo de la tesis para la contraccion, y por el mismo motivo: el
# primer segundo se va en la reaccion y en la subida de fuerza, y el
# ultimo medio segundo en soltar. Medir ahi mezcla transicion con meseta.
from config_captura import (                       # noqa: E402
    MARGEN_CONTRACCION, COLOR_CONTRACCION, COLOR_REPOSO, COLOR_PREPARACION,
    COLOR_FIN, COLOR_TEXTO, FUENTE_FASE, FUENTE_INSTRUCCION, FUENTE_CUENTA,
    FUENTE_PIE, DIR_IMAGENES)

DIR_SALIDA = os.path.join(AQUI, "pruebas")

FASE_REPOSO = "reposo"
FASE_PUNO = "puno"
FASE_PINZA = "pinza"
FASE_MOVIMIENTO = "movimiento"

# (fase, duracion en segundos), en orden.
PROTOCOLO = (
    [(FASE_REPOSO, 10)]
    + [(FASE_PUNO, 5), (FASE_REPOSO, 5)] * 3
    + [(FASE_PINZA, 5), (FASE_REPOSO, 5)] * 3
    + [(FASE_MOVIMIENTO, 10)]
)

# Tono de cada fase, con las claves que ya define config_captura.
TONO = {
    FASE_REPOSO: "reposo",
    FASE_PUNO: "contraccion",
    FASE_PINZA: "contraccion",
    FASE_MOVIMIENTO: "posicion",
}

INSTRUCCION = {
    FASE_REPOSO: "REPOSO. Mano relajada, brazo quieto.",
    FASE_PUNO: "PUNO. Cierre la mano con fuerza media y mantenga.",
    FASE_PINZA: "PINZA. Indice contra pulgar, fuerza media, mantenga.",
    FASE_MOVIMIENTO: "MUEVA EL BRAZO. SIN hacer ningun gesto, mano relajada.",
}

# Lo que se ve en pantalla en cada fase: titulo, color de fondo e imagen.
# Los colores y las fotos son los de la app de captura, para que el
# banco se lea igual que una sesion.
ASPECTO = {
    FASE_REPOSO: ("REPOSO", COLOR_REPOSO, "Rest"),
    FASE_PUNO: ("PUNO", COLOR_CONTRACCION, "Power"),
    FASE_PINZA: ("PINZA", COLOR_CONTRACCION, "Pinch"),
    FASE_MOVIMIENTO: ("MUEVA EL BRAZO", COLOR_PREPARACION, "Rest"),
}

# Umbral de saturacion. El fondo de escala util son 2000 mV y la
# autocalibracion del firmware ya no deja pasar del 95%, o sea 1900 mV
# (AUTOCAL_LIMITE_FRAC y FONDO_ESCALA_UTIL_MV en Modulo1/config.h). Una
# variante que aun asi recorta esta demasiado cerca del sensor.
UMBRAL_SATURACION_MV = 1900.0
# Una muestra suelta en 1900 mV puede ser un pico de red. Se considera
# que la variante satura a partir de 0.1 s de recorte acumulado.
MIN_MUESTRAS_SATURADAS = 10

# Regla de decision, fijada antes de medir nada.
TOLERANCIA_EMPATE = 0.10        # 10% de diferencia de SNR se considera empate

CAMPOS_CSV = (["variante", "ronda", "canal", "t_esp32_ms", "ts_pc_ms", "fase"]
              + [f"v{i}" for i in range(1, 6)] + ["ax", "ay", "az"])


# ============================================================
# CAPTURA
# ============================================================
class Pantalla:
    """
    Ventana a pantalla completa que guia la prueba.

    Hace falta porque la prueba se hace sobre el propio antebrazo, con
    una mano ocupada en el gesto y la vista a un metro de la laptop: una
    linea de consola no se lee desde ahi. Escape sale de pantalla
    completa.

    Si no hay entorno grafico, abrir() devuelve None y el banco sigue
    por consola, que es como corre en una terminal sin ventanas.
    """

    @staticmethod
    def abrir(titulo):
        try:
            return Pantalla(titulo)
        except Exception as e:
            print(f"(sin ventana: {e}. Sigo por consola.)")
            return None

    def __init__(self, titulo):
        import tkinter as tk
        self.tk = tk
        self.root = tk.Tk()
        self.root.title(titulo)
        self.root.attributes("-fullscreen", True)
        self.root.bind("<Escape>",
                       lambda e: self.root.attributes("-fullscreen", False))
        self.cerrada = False
        self.root.protocol("WM_DELETE_WINDOW", self._al_cerrar)

        def etiqueta(fuente):
            l = tk.Label(self.root, fg=COLOR_TEXTO, font=fuente,
                         wraplength=1400, justify="center")
            l.pack(pady=10)
            return l

        self._pie = etiqueta(FUENTE_PIE)
        self._fase = etiqueta(FUENTE_FASE)
        self._img = tk.Label(self.root)
        self._img.pack(pady=10)
        self._instruccion = etiqueta(FUENTE_INSTRUCCION)
        self._cuenta = etiqueta(FUENTE_CUENTA)
        self._partes = [self.root, self._pie, self._fase, self._img,
                        self._instruccion, self._cuenta]

        self._imagenes = {}
        for nombre in {a[2] for a in ASPECTO.values()}:
            ruta = os.path.join(DIR_IMAGENES, f"{nombre}.png")
            if os.path.exists(ruta):
                try:
                    self._imagenes[nombre] = tk.PhotoImage(file=ruta)
                except Exception:
                    pass
        self._fase_actual = None

    def _al_cerrar(self):
        self.cerrada = True

    def mostrar(self, fase, idx, total, restante_s):
        if fase != self._fase_actual:
            titulo, color, imagen = ASPECTO[fase]
            for p in self._partes:
                p.configure(bg=color)
            self._fase.config(text=titulo)
            self._instruccion.config(text=INSTRUCCION[fase])
            self._pie.config(text=f"Bloque {idx + 1} de {total}")
            img = self._imagenes.get(imagen)
            self._img.config(image=img if img is not None else "")
            self._fase_actual = fase
        self._cuenta.config(text=f"{max(0, int(restante_s + 0.999))}")
        self.root.update()

    def fin(self, texto):
        for p in self._partes:
            p.configure(bg=COLOR_FIN)
        self._fase.config(text=texto)
        self._instruccion.config(text="")
        self._cuenta.config(text="")
        self._img.config(image="")
        self._pie.config(text="")
        self.root.attributes("-fullscreen", False)
        self.root.update()

    def cerrar(self):
        try:
            self.root.destroy()
        except Exception:
            pass


def autocalibrar(lector, limite_s=90.0, silencio_s=6.0):
    """
    Manda 'A' y muestra la respuesta del firmware hasta que se calle.

    HAY QUE AUTOCALIBRAR EN CADA VARIANTE. La autocalibracion ajusta la
    corriente del LED hasta que el reposo queda en 700 mV. Sin ella, una
    variante con el LED a 9 mm entrega mas luz al fotodiodo que una a
    13 mm y saldria mejor en el SNR por la distancia, no por la calidad
    del acoplamiento. Con ella, las 6 se comparan en el mismo punto de
    operacion.

    Con un solo modulo conectado el firmware marcara DEBIL los otros
    cuatro canales y devolvera fallo. Es lo esperado: lo que importa es
    que el canal conectado quede cerca de 700 mV.
    """
    print("\n--- Autocalibracion del LED (comando A). No mueva la mano.")
    lector.enviar("A")
    vistas = 0
    t0 = time.monotonic()
    t_ultima = t0
    while True:
        ahora = time.monotonic()
        while vistas < len(lector.info):
            print("    " + lector.info[vistas])
            vistas += 1
            t_ultima = ahora
        if vistas and ahora - t_ultima > silencio_s:
            print("--- Autocalibracion terminada.\n")
            return True
        if ahora - t0 > limite_s:
            print("--- AVISO: el firmware no respondio a 'A'.\n")
            return False
        time.sleep(0.1)


def capturar(args):
    from adquisicion import LectorSerie                  # import tardio:
    from interfaz import sonar                           # arrastran tkinter

    os.makedirs(args.dir, exist_ok=True)
    sello = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = f"{args.variante}_r{args.ronda}_{sello}"
    ruta_csv = os.path.join(args.dir, base + ".csv")

    cola = queue.Queue(maxsize=20000)
    lector = LectorSerie(args.puerto, cola, baudios=args.baudios,
                         simulado=args.simulado)
    lector.abrir()
    lector.start()

    if not args.simulado and not args.sin_autocal:
        autocalibrar(lector)

    lector.enviar("L")
    time.sleep(0.5)

    print(f"Variante {args.variante}, ronda {args.ronda}, canal "
          f"v{args.canal}. Archivo: {os.path.basename(ruta_csv)}")
    print(f"Duracion: {sum(d for _, d in PROTOCOLO) * args.escala:.0f} s. "
          f"Ctrl+C para abortar.\n")

    f = open(ruta_csv, "w", newline="", encoding="utf-8")
    w = csv.writer(f)
    w.writerow(CAMPOS_CSV)
    filas = 0
    limites = []            # (t_inicio, t_fin, fase) en segundos desde t0
    t = 0.0
    for fase, dur in PROTOCOLO:
        limites.append((t, t + dur * args.escala, fase))
        t += dur * args.escala

    pantalla = None if args.sin_ventana else Pantalla.abrir(
        f"Banco LMG - {args.variante} ronda {args.ronda}")
    # El reloj arranca DESPUES de abrir la ventana, que tarda lo suyo.
    t0 = time.monotonic()

    def volcar():
        """
        Saca de la cola lo que haya y lo escribe con su fase.

        Lo que cae FUERA del horario se tira: son las muestras que
        llegaron mientras se abria la ventana, antes de empezar, y las
        que siguen llegando despues del ultimo bloque. Etiquetarlas con
        la fase vecina seria inventarles una condicion que nadie pidio.
        """
        nonlocal filas
        while True:
            try:
                m = cola.get_nowait()
            except queue.Empty:
                return
            rel = m.t_pc - t0
            fase = next((nombre for ini, fin, nombre in limites
                         if ini <= rel < fin), None)
            if fase is None:
                continue
            w.writerow([args.variante, args.ronda, args.canal, m.t_esp32,
                        m.ts_pc_ms, fase]
                       + [f"{v:.4f}" for v in m.valores[:8]])
            filas += 1

    abortada = False
    try:
        for i, (fase, _) in enumerate(PROTOCOLO):
            # El fin de cada fase sale del HORARIO ABSOLUTO, el mismo con
            # el que se etiquetan las muestras, y no de sumar duraciones.
            # El tono bloquea unos 120 ms: sumando, la pantalla acababa
            # 1.7 s por detras de las etiquetas al final de las 14 fases,
            # un tercio de un bloque de 5 s.
            fin = t0 + limites[i][1]
            if pantalla:
                pantalla.mostrar(fase, i, len(PROTOCOLO),
                                 (fin - time.monotonic()) / args.escala)
            sonar(TONO[fase])
            print(f"[{i + 1:2d}/{len(PROTOCOLO)}] {INSTRUCCION[fase]}")
            while time.monotonic() < fin:
                volcar()
                restante = fin - time.monotonic()
                if pantalla:
                    if pantalla.cerrada:
                        raise KeyboardInterrupt
                    pantalla.mostrar(fase, i, len(PROTOCOLO),
                                     restante / args.escala)
                else:
                    print(f"\r     {restante:5.1f} s   ", end="", flush=True)
                time.sleep(min(0.05, max(0.0, restante)))
            if not pantalla:
                print("\r" + " " * 20)
    except KeyboardInterrupt:
        abortada = True
        print("\nABORTADA por el operador.")
    finally:
        volcar()
        lector.enviar("S")
        time.sleep(0.2)
        volcar()
        lector.detener()
        f.close()

    sonar("aviso")
    if pantalla:
        pantalla.fin("ABORTADA" if abortada else "LISTO")
    meta = {
        "variante": args.variante,
        "ronda": args.ronda,
        "canal": args.canal,
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "filas": filas,
        "abortada": abortada,
        "simulado": bool(args.simulado),
        "escala_tiempo": args.escala,
        "protocolo_s": [[fa, d] for fa, d in PROTOCOLO],
        "puerto": args.puerto,
        "version_firmware": lector.version_firmware,
        # Corriente de los LED y reposo por canal tras la autocalibracion.
        # Es el punto de operacion con el que se midio esta variante.
        "optica": lector.optica,
        "huecos": lector.stats.huecos,
        "muestras_perdidas_est": lector.stats.muestras_perdidas_est,
        "tasa_hz_final": round(lector.stats.tasa_hz, 1),
    }
    with open(os.path.join(args.dir, base + ".json"), "w",
              encoding="utf-8") as fj:
        json.dump(meta, fj, indent=2, ensure_ascii=False)

    print(f"\nCSV cerrado: {filas} filas. Huecos: {lector.stats.huecos}.")
    print(f"  {ruta_csv}")
    if filas < 0.8 * 100 * sum(d for _, d in PROTOCOLO) * args.escala:
        print("  AVISO: llegaron muchas menos muestras de las esperadas. "
              "Revise el enlace antes de dar la prueba por buena.")
    if abortada:
        print("  PRUEBA ABORTADA: el CSV esta incompleto. Borrelo o repita "
              "la prueba, porque 'analizar' lo va a leer igual.")
    if pantalla:
        time.sleep(2.0)             # que se alcance a leer el final
        pantalla.cerrar()


# ============================================================
# METRICAS
# ============================================================
def _segmentos(df):
    """Indice de segmento: cada tramo contiguo de la misma fase."""
    return (df["fase"] != df["fase"].shift()).cumsum()


def recortar_margenes(df, periodo_ms=10.0):
    """
    Quita el margen de entrada y de salida de cada tramo.

    Sin esto, la media de la contraccion incluye el segundo que el
    participante tarda en llegar a la fuerza pedida, y la desviacion del
    reposo incluye la relajacion, que no es reposo.
    """
    n_ini = int(MARGEN_CONTRACCION[0] / periodo_ms)
    n_fin = int(MARGEN_CONTRACCION[1] / periodo_ms)
    trozos = []
    for _, g in df.groupby(_segmentos(df), sort=False):
        if len(g) > n_ini + n_fin:
            trozos.append(g.iloc[n_ini: len(g) - n_fin])
    if not trozos:
        return df.iloc[0:0]
    import pandas as pd
    return pd.concat(trozos)


def metricas(ruta):
    """Metricas de una prueba. Devuelve un dict por archivo."""
    import pandas as pd
    df = pd.read_csv(ruta)
    canal = f"v{int(df['canal'].iloc[0])}"
    v = df[canal]

    # La saturacion se mira sobre el archivo COMPLETO, sin recortar
    # margenes: un recorte en la transicion sigue siendo un recorte.
    n_sat = int((v >= UMBRAL_SATURACION_MV).sum())

    util = recortar_margenes(df)
    s = util[canal]
    reposo = s[util["fase"] == FASE_REPOSO]
    puno = s[util["fase"] == FASE_PUNO]
    pinza = s[util["fase"] == FASE_PINZA]
    mov = s[util["fase"] == FASE_MOVIMIENTO]

    sd_reposo = float(reposo.std())
    def snr(x):
        if len(x) == 0 or len(reposo) == 0 or sd_reposo <= 0:
            return float("nan")
        return float((x.mean() - reposo.mean()) / sd_reposo)

    return {
        "archivo": os.path.basename(ruta),
        "variante": str(df["variante"].iloc[0]),
        "ronda": int(df["ronda"].iloc[0]),
        "canal": canal,
        "n": len(df),
        "reposo_mv": float(reposo.mean()) if len(reposo) else float("nan"),
        "sd_reposo_mv": sd_reposo,
        "snr_puno": snr(puno),
        "snr_pinza": snr(pinza),
        # Artefacto de movimiento: cuanto se mueve la senal al mover el
        # brazo SIN gesto, en unidades de la desviacion del reposo. Un 1
        # significa que moverse ensucia tanto como el ruido de fondo.
        "artefacto_mov": (float(mov.std() / sd_reposo)
                          if len(mov) and sd_reposo > 0 else float("nan")),
        "n_saturadas": n_sat,
        "frac_saturada": n_sat / max(len(v), 1),
        "satura": n_sat >= MIN_MUESTRAS_SATURADAS,
    }


def resumir(pruebas):
    """Una fila por variante, promediando rondas."""
    import pandas as pd
    df = pd.DataFrame(pruebas)
    filas = []
    for variante, g in df.groupby("variante"):
        g = g.sort_values("ronda")
        snr_p = g["snr_pinza"]
        filas.append({
            "variante": variante,
            "rondas": len(g),
            "snr_puno": g["snr_puno"].mean(),
            "snr_pinza": snr_p.mean(),
            # Repetibilidad del montaje: cuanto cambia el SNR de pinza al
            # despegar y volver a colocar el modulo.
            "dif_rondas": (float(snr_p.max() - snr_p.min())
                           if len(g) > 1 else float("nan")),
            "dif_rondas_pct": (float(100 * (snr_p.max() - snr_p.min())
                                     / abs(snr_p.mean()))
                               if len(g) > 1 and snr_p.mean() else float("nan")),
            "artefacto_mov": g["artefacto_mov"].mean(),
            "n_saturadas": int(g["n_saturadas"].sum()),
            "satura": bool(g["satura"].any()),
        })
    return pd.DataFrame(filas).sort_values("snr_pinza", ascending=False)


def elegir(resumen):
    """
    Aplica la regla fijada de antemano.

      1. Se descartan las variantes que saturan.
      2. Gana la de mayor SNR de pinza.
      3. Si otra queda a menos del 10% de esa, empatan, y desempata la
         de menor artefacto de movimiento.

    Devuelve (variante, texto del motivo).
    """
    vivas = resumen[~resumen["satura"]]
    if vivas.empty:
        return None, ("Todas las variantes saturan. Ninguna es elegible: "
                      "revise la distancia del LED o baje la corriente.")

    mejor = vivas.loc[vivas["snr_pinza"].idxmax()]
    tope = mejor["snr_pinza"]
    if tope <= 0:
        return None, ("Ninguna variante tiene SNR de pinza positivo. La "
                      "medicion no distingue el gesto del reposo.")

    empatadas = vivas[vivas["snr_pinza"] >= tope * (1 - TOLERANCIA_EMPATE)]
    descartadas = int(resumen["satura"].sum())
    nota = (f" Descartadas por saturacion: {descartadas}."
            if descartadas else "")

    if len(empatadas) == 1:
        return mejor["variante"], (
            f"{mejor['variante']} gana por SNR de pinza "
            f"({tope:.2f}), con mas del {TOLERANCIA_EMPATE:.0%} de ventaja "
            f"sobre la siguiente.{nota}")

    ganadora = empatadas.loc[empatadas["artefacto_mov"].idxmin()]
    nombres = ", ".join(empatadas["variante"])
    return ganadora["variante"], (
        f"Empate dentro del {TOLERANCIA_EMPATE:.0%} de SNR de pinza entre: "
        f"{nombres}. Desempata el artefacto de movimiento y gana "
        f"{ganadora['variante']} ({ganadora['artefacto_mov']:.2f} frente a "
        f"{empatadas['artefacto_mov'].max():.2f} de la peor).{nota}")


def grafico(pruebas, ruta_png):
    """Barras del SNR de pinza por variante, una barra por ronda."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd

    df = pd.DataFrame(pruebas)
    tabla = df.pivot_table(index="variante", columns="ronda",
                           values="snr_pinza", aggfunc="mean")
    orden = tabla.mean(axis=1).sort_values(ascending=False).index
    tabla = tabla.loc[orden]

    ancho = 0.8 / max(len(tabla.columns), 1)
    fig, ax = plt.subplots(figsize=(9, 5))
    for k, ronda in enumerate(tabla.columns):
        x = [i + k * ancho for i in range(len(tabla))]
        ax.bar(x, tabla[ronda].values, width=ancho, label=f"ronda {ronda}")
    ax.set_xticks([i + ancho * (len(tabla.columns) - 1) / 2
                   for i in range(len(tabla))])
    ax.set_xticklabels(tabla.index, rotation=20, ha="right")
    ax.set_ylabel("SNR de pinza\n(media contraccion - media reposo) / sd reposo")
    ax.set_title("Variantes del modulo LMG, SNR de pinza por ronda")
    ax.axhline(0, color="#666666", linewidth=0.8)
    ax.legend()
    fig.tight_layout()
    fig.savefig(ruta_png, dpi=150)
    plt.close(fig)
    return ruta_png


def analizar(args):
    import glob
    import pandas as pd

    rutas = sorted(glob.glob(os.path.join(args.dir, "*.csv")))
    if not rutas:
        print(f"No hay CSV en {args.dir}. Corra primero 'capturar'.")
        return 1

    pruebas = [metricas(r) for r in rutas]
    det = pd.DataFrame(pruebas)
    resumen = resumir(pruebas)

    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 50)
    print("\n=== PRUEBAS INDIVIDUALES ===")
    print(det[["variante", "ronda", "reposo_mv", "sd_reposo_mv", "snr_puno",
               "snr_pinza", "artefacto_mov", "n_saturadas"]]
          .to_string(index=False, float_format=lambda x: f"{x:8.2f}"))

    print("\n=== RESUMEN POR VARIANTE ===")
    print(resumen.to_string(index=False,
                            float_format=lambda x: f"{x:8.2f}"))

    ganadora, motivo = elegir(resumen)
    print("\n=== DECISION ===")
    print(motivo)
    if ganadora:
        print(f"\nVARIANTE ELEGIDA: {ganadora}")

    det.to_csv(os.path.join(args.dir, "metricas_pruebas.csv"), index=False)
    resumen.to_csv(os.path.join(args.dir, "metricas_variantes.csv"),
                   index=False)
    png = grafico(pruebas, os.path.join(args.dir, "snr_pinza.png"))
    print(f"\nTablas en {args.dir} y grafico en {png}")
    return 0


# ============================================================
def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("capturar", help="correr el protocolo de una variante")
    c.add_argument("--variante", required=True,
                   help="nombre, por ejemplo SMD_11mm o PASANTE_9mm")
    c.add_argument("--ronda", type=int, required=True, help="1 o 2")
    c.add_argument("--puerto", default="COM3")
    c.add_argument("--baudios", type=int, default=921600)
    c.add_argument("--canal", type=int, default=1,
                   help="canal LMG donde esta conectado el modulo (1 a 5)")
    c.add_argument("--dir", default=DIR_SALIDA)
    c.add_argument("--simulado", action="store_true",
                   help="sin hardware, para probar el flujo")
    c.add_argument("--sin-autocal", action="store_true",
                   help="no mandar 'A' antes de medir. Solo si ya calibro")
    c.add_argument("--sin-ventana", action="store_true",
                   help="guiar solo por consola, sin la pantalla completa")
    c.add_argument("--escala", type=float, default=1.0,
                   help="factor de tiempo. Solo para probar, 1.0 en las "
                        "mediciones de verdad")
    c.set_defaults(func=capturar)

    a = sub.add_parser("analizar", help="tabla, grafico y decision")
    a.add_argument("--dir", default=DIR_SALIDA)
    a.set_defaults(func=analizar)

    args = p.parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
