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

PROTOCOLO POR VARIANTE (160 s, A30):
  10 s de reposo, 7 x (5 s de puno + 5 s de reposo), 7 x (5 s de pinza +
  5 s de reposo) y 10 s moviendo el brazo con la mano relajada.

CORRIENTE FIJA (A30):
  Las seis variantes se miden con la misma corriente media del LED,
  13 mA, por PWM. Sin autocalibrar: el banco compara cuanta senal saca
  cada variante de la MISMA luz. El duty sale de medir la corriente al
  100% con el multimetro (subcomando duty) y queda en
  parametros_banco.json.

INDICE (A30):
  I = |dS| / (Phi_e * Rp). dS en mV es la media de contraccion menos la
  del reposo que la precede, promediada sobre las 7 repeticiones.
  Phi_e es el flujo radiante del LED en mW a la corriente media de la
  prueba y Rp la responsividad del fotodiodo en A/W a 940 nm. Los dos
  salen de las hojas de datos. Phi_e * Rp queda en mA, asi que I queda
  en mV/mA.

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
  python banco.py duty --corriente_100_ma 18.2
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
    FUENTE_PIE, FUENTE_POSICION, COLOR_RAMPA, DIR_IMAGENES,
    POSICIONES_BRAZO, TEXTO_POSICION)

DIR_SALIDA = os.path.join(AQUI, "pruebas")
RUTA_PARAMETROS = os.path.join(AQUI, "parametros_banco.json")

# Igual que LED_DUTY_MAX en Modulo1_Adquisicion_Datos/config.h (9 bits).
LED_DUTY_MAX = 511
N_REPETICIONES = 7

FASE_REPOSO = "reposo"
FASE_PUNO = "puno"
FASE_PINZA = "pinza"
FASE_MOVIMIENTO = "movimiento"

# (fase, duracion en segundos), en orden.
PROTOCOLO = (
    [(FASE_REPOSO, 10)]
    + [(FASE_PUNO, 5), (FASE_REPOSO, 5)] * N_REPETICIONES
    + [(FASE_PINZA, 5), (FASE_REPOSO, 5)] * N_REPETICIONES
    + [(FASE_MOVIMIENTO, 10)]
)

# Tono de cada fase, con las claves que ya define config_captura.
TONO = {
    FASE_REPOSO: "reposo",
    FASE_PUNO: "contraccion",
    FASE_PINZA: "contraccion",
    FASE_MOVIMIENTO: "preparacion",
}

INSTRUCCION = {
    FASE_REPOSO: "REPOSO. Mano relajada, brazo quieto.",
    FASE_PUNO: "PUNO. Cierre la mano con fuerza media y mantenga.",
    FASE_PINZA: "PINZA. Indice contra pulgar, fuerza media, mantenga.",
    FASE_MOVIMIENTO: "Lleve el brazo a la posicion marcada. Mano relajada, "
                     "sin gesto y sin girar la muneca.",
}


def posicion_en(frac):
    """
    Posicion del brazo pedida en el bloque de movimiento, segun la
    fraccion transcurrida del bloque, de 0 a 1.

    Son las tres posiciones de la condicion dinamica de la tesis, en su
    orden y a su ritmo, 3.3 s cada una. Dos motivos. El artefacto que
    interesa es el del movimiento que haran los participantes, no el de
    uno cualquiera. Y un recorrido fijo hace comparable la metrica entre
    las 12 corridas: si el movimiento quedara a criterio de quien mide,
    una variante saldria peor solo por haber movido el brazo con mas
    ganas.
    """
    n = len(POSICIONES_BRAZO)
    return POSICIONES_BRAZO[min(int(max(frac, 0.0) * n), n - 1)]

# Lo que se ve en pantalla en cada fase: titulo, color de fondo e imagen.
# Los colores y las fotos son los de la app de captura, para que el
# banco se lea igual que una sesion.
ASPECTO = {
    FASE_REPOSO: ("REPOSO", COLOR_REPOSO, "Rest"),
    FASE_PUNO: ("PUNO", COLOR_CONTRACCION, "Power"),
    FASE_PINZA: ("PINZA", COLOR_CONTRACCION, "Pinch"),
    FASE_MOVIMIENTO: ("MUEVA EL BRAZO", COLOR_PREPARACION, "Rest"),
}

# Umbral de saturacion: el 95% del fondo de escala util de 2000 mV, el
# mismo limite que usa la autocalibracion de las sesiones
# (AUTOCAL_LIMITE_FRAC y FONDO_ESCALA_UTIL_MV en Modulo1/config.h). Con
# corriente fija, una variante con el LED muy cerca del fotodiodo puede
# llegar ahi, y esa no sirve aunque tenga el mayor indice.
UMBRAL_SATURACION_MV = 1900.0
# Una muestra suelta en 1900 mV puede ser un pico de red. Se considera
# que la variante satura a partir de 0.1 s de recorte acumulado.
MIN_MUESTRAS_SATURADAS = 10

# Regla de decision, fijada antes de medir nada.
TOLERANCIA_EMPATE = 0.10        # 10% de diferencia de I se considera empate

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
        self._marco_pos = tk.Frame(self.root)
        self._casillas = []
        for pos in POSICIONES_BRAZO:
            c = tk.Label(self._marco_pos, text=TEXTO_POSICION.get(pos, pos),
                         font=FUENTE_POSICION, padx=14, pady=8,
                         highlightbackground=COLOR_TEXTO, highlightthickness=2)
            c.pack(side="left", padx=6)
            self._casillas.append((pos, c))
        self._cuenta = etiqueta(FUENTE_CUENTA)
        self._partes = [self.root, self._pie, self._fase, self._img,
                        self._instruccion, self._cuenta, self._marco_pos]

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

    def mostrar(self, fase, idx, total, restante_s, posicion=None):
        titulo, color, imagen = ASPECTO[fase]
        if posicion:
            if not self._marco_pos.winfo_manager():
                self._marco_pos.pack(before=self._cuenta, pady=6)
            for pos, c in self._casillas:
                activa = pos == posicion
                c.configure(bg=COLOR_RAMPA if activa else color,
                            fg="#000000" if activa else COLOR_TEXTO)
        elif self._marco_pos.winfo_manager():
            self._marco_pos.pack_forget()
        if fase != self._fase_actual:
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


def cargar_parametros(ruta=RUTA_PARAMETROS):
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def duty_para(corriente_100_ma, corriente_media_ma):
    """
    Duty que da la corriente media pedida. Al 100% (LED_DUTY_MAX) el LED
    lleva la corriente medida, y la media por PWM es proporcional al duty.
    El OPT101 (14 kHz) no sigue el PWM de 100 kHz y ve esa media.
    """
    if corriente_100_ma <= 0:
        raise ValueError("La corriente al 100% tiene que ser mayor que cero.")
    if corriente_media_ma > corriente_100_ma:
        raise ValueError(f"Con {corriente_100_ma} mA al 100% no se llega a "
                         f"{corriente_media_ma} mA de media.")
    return int(round(LED_DUTY_MAX * corriente_media_ma / corriente_100_ma))


def fijar_duty(args):
    """Subcomando duty: calcula el duty y lo guarda en los parametros."""
    par = cargar_parametros(args.parametros)
    d = duty_para(args.corriente_100_ma, par["corriente_media_ma"])
    par["corriente_100_ma"] = args.corriente_100_ma
    par["duty"] = d
    with open(args.parametros, "w", encoding="utf-8") as f:
        json.dump(par, f, indent=2, ensure_ascii=False)
    print(f"{args.corriente_100_ma} mA al 100% -> duty {d} de {LED_DUTY_MAX} "
          f"({100 * d / LED_DUTY_MAX:.1f}%) para {par['corriente_media_ma']} mA "
          f"de media. Guardado en {args.parametros}")
    return 0


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

    duty = cargar_parametros(args.parametros).get("duty")
    if duty is None and not args.simulado:
        print("Falta el duty en parametros_banco.json. Mida la corriente del "
              "LED al 100% ('W1' en el firmware) y corra el subcomando duty.")
        lector.detener()
        return 1
    if duty is not None:
        # Misma corriente media en las seis variantes, sin autocalibrar.
        lector.enviar(f"D{duty}\n")
        time.sleep(0.5)

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
            ini, fin = t0 + limites[i][0], t0 + limites[i][1]
            con_pos = fase == FASE_MOVIMIENTO
            pos = posicion_en(0.0) if con_pos else None
            if pantalla:
                pantalla.mostrar(fase, i, len(PROTOCOLO),
                                 (fin - time.monotonic()) / args.escala, pos)
            sonar(TONO[fase])
            print(f"[{i + 1:2d}/{len(PROTOCOLO)}] {INSTRUCCION[fase]}")
            if con_pos:
                print(f"        > {TEXTO_POSICION[pos]}")
            while time.monotonic() < fin:
                volcar()
                restante = fin - time.monotonic()
                if con_pos:
                    nueva = posicion_en(
                        (time.monotonic() - ini) / (fin - ini))
                    if nueva != pos:
                        pos = nueva
                        sonar("posicion")
                        print(f"        > {TEXTO_POSICION[pos]}")
                if pantalla:
                    if pantalla.cerrada:
                        raise KeyboardInterrupt
                    pantalla.mostrar(fase, i, len(PROTOCOLO),
                                     restante / args.escala, pos)
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
        "duty": duty,
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


def deltas(util, canal, fase):
    """
    dS de cada repeticion, en mV: media de la contraccion menos la del
    reposo que la precede. Restar el reposo vecino y no uno global quita
    la deriva lenta de la piel y del LED a lo largo de los 160 s.
    """
    import numpy as np
    medias = util.groupby("seg", sort=True).agg(fase=("fase", "first"),
                                                m=(canal, "mean"))
    salida, previa = [], None
    for f, m in zip(medias["fase"], medias["m"]):
        if f == fase and previa is not None and previa[0] == FASE_REPOSO:
            salida.append(m - previa[1])
        previa = (f, m)
    return np.array(salida)


def metricas(ruta):
    """Metricas de una prueba. Devuelve un dict por archivo."""
    import pandas as pd
    df = pd.read_csv(ruta)
    df["seg"] = _segmentos(df)
    canal = f"v{int(df['canal'].iloc[0])}"
    v = df[canal]

    # La saturacion se mira sobre el archivo COMPLETO, sin recortar
    # margenes: un recorte en la transicion sigue siendo un recorte.
    n_sat = int((v >= UMBRAL_SATURACION_MV).sum())

    util = recortar_margenes(df)
    s = util[canal]
    reposo = s[util["fase"] == FASE_REPOSO]
    mov = s[util["fase"] == FASE_MOVIMIENTO]
    sd_reposo = float(reposo.std())

    # El duty con que se midio, del JSON que deja capturar.
    duty = None
    meta = os.path.splitext(ruta)[0] + ".json"
    if os.path.exists(meta):
        with open(meta, encoding="utf-8") as f:
            duty = json.load(f).get("duty")

    fila = {
        "archivo": os.path.basename(ruta),
        "variante": str(df["variante"].iloc[0]),
        "ronda": int(df["ronda"].iloc[0]),
        "canal": canal,
        "duty": duty,
        "n": len(df),
        "reposo_mv": float(reposo.mean()) if len(reposo) else float("nan"),
        "sd_reposo_mv": sd_reposo,
    }
    for nombre, fase in (("puno", FASE_PUNO), ("pinza", FASE_PINZA)):
        d = deltas(util, canal, fase)
        media = float(d.mean()) if len(d) else float("nan")
        fila[f"n_rep_{nombre}"] = len(d)
        fila[f"ds_{nombre}_mv"] = media
        # SNR: cuanto sobresale el gesto sobre el ruido del reposo.
        fila[f"snr_{nombre}"] = (abs(media) / sd_reposo if sd_reposo > 0
                                 else float("nan"))
        # Repetibilidad dentro de la prueba: coeficiente de variacion de
        # dS entre las 7 repeticiones.
        fila[f"cv_{nombre}"] = (float(d.std(ddof=1) / abs(media))
                                if len(d) > 1 and media else float("nan"))
    fila.update({
        # Artefacto de movimiento: cuanto se mueve la senal al mover el
        # brazo SIN gesto, en unidades de la desviacion del reposo. Un 1
        # significa que moverse ensucia tanto como el ruido de fondo.
        "artefacto_mov": (float(mov.std() / sd_reposo)
                          if len(mov) and sd_reposo > 0 else float("nan")),
        "n_saturadas": n_sat,
        "frac_saturada": n_sat / max(len(v), 1),
        "satura": n_sat >= MIN_MUESTRAS_SATURADAS,
    })
    return fila


def tipo_led(variante):
    """PASANTE_9mm -> PASANTE. Es la clave de phi_e_mw en los parametros."""
    return str(variante).split("_")[0].upper()


def faltan_parametros(par, variantes):
    """Lista de lo que falta en parametros_banco.json para calcular I."""
    faltan = [] if par.get("rp_a_por_w") else ["rp_a_por_w"]
    phis = par.get("phi_e_mw") or {}
    faltan += sorted({f"phi_e_mw.{tipo_led(v)}" for v in variantes
                      if not phis.get(tipo_led(v))})
    return faltan


def anadir_indice(det, par):
    """I = |dS| / (Phi_e * Rp), en mV/mA, por prueba."""
    rp, phis = par["rp_a_por_w"], par["phi_e_mw"]
    for nombre in ("puno", "pinza"):
        det[f"i_{nombre}"] = [abs(ds) / (phis[tipo_led(v)] * rp)
                              for v, ds in zip(det["variante"],
                                               det[f"ds_{nombre}_mv"])]
    return det


def resumir(det):
    """Una fila por variante, promediando rondas."""
    import pandas as pd
    filas = []
    for variante, g in det.groupby("variante"):
        ds = g["ds_pinza_mv"].abs()
        filas.append({
            "variante": variante,
            "rondas": len(g),
            "i_puno": g["i_puno"].mean(),
            "i_pinza": g["i_pinza"].mean(),
            "snr_puno": g["snr_puno"].mean(),
            "snr_pinza": g["snr_pinza"].mean(),
            "cv_pinza": g["cv_pinza"].mean(),
            # Repetibilidad del montaje: cuanto cambia dS de pinza al
            # despegar y volver a colocar el modulo. Es el mismo % que el
            # de I, porque Phi_e y Rp no cambian entre rondas.
            "dif_rondas_pct": (float(100 * (ds.max() - ds.min()) / ds.mean())
                               if len(g) > 1 and ds.mean() else float("nan")),
            "artefacto_mov": g["artefacto_mov"].mean(),
            "n_saturadas": int(g["n_saturadas"].sum()),
            "satura": bool(g["satura"].any()),
        })
    return pd.DataFrame(filas).sort_values("i_pinza", ascending=False)


def elegir(resumen):
    """
    Aplica la regla fijada de antemano.

      1. Se descartan las variantes que saturan.
      2. Gana la de mayor I de pinza.
      3. Si otra queda a menos del 10% de esa, empatan, y desempata la
         de menor artefacto de movimiento.

    Devuelve (variante, texto del motivo).
    """
    vivas = resumen[~resumen["satura"] & resumen["i_pinza"].notna()]
    if vivas.empty:
        return None, ("Ninguna variante es elegible: todas saturan o no "
                      "tienen repeticiones de pinza validas.")

    mejor = vivas.loc[vivas["i_pinza"].idxmax()]
    tope = mejor["i_pinza"]
    if tope <= 0:
        return None, ("Ninguna variante tiene I de pinza mayor que cero. La "
                      "medicion no distingue el gesto del reposo.")

    empatadas = vivas[vivas["i_pinza"] >= tope * (1 - TOLERANCIA_EMPATE)]
    descartadas = int(resumen["satura"].sum())
    nota = (f" Descartadas por saturacion: {descartadas}."
            if descartadas else "")

    if len(empatadas) == 1:
        return mejor["variante"], (
            f"{mejor['variante']} gana por I de pinza "
            f"({tope:.3g} mV/mA), con mas del {TOLERANCIA_EMPATE:.0%} de "
            f"ventaja sobre la siguiente.{nota}")

    ganadora = empatadas.loc[empatadas["artefacto_mov"].idxmin()]
    nombres = ", ".join(empatadas["variante"])
    return ganadora["variante"], (
        f"Empate dentro del {TOLERANCIA_EMPATE:.0%} de I de pinza entre: "
        f"{nombres}. Desempata el artefacto de movimiento y gana "
        f"{ganadora['variante']} ({ganadora['artefacto_mov']:.2f} frente a "
        f"{empatadas['artefacto_mov'].max():.2f} de la peor).{nota}")


def ordenar(resumen):
    """
    Tabla final ordenada con la misma regla: se aplica elegir() a las que
    quedan, una y otra vez. Las que saturan van al final, por I.
    """
    quedan, orden = resumen, []
    while True:
        ganadora, _ = elegir(quedan)
        if ganadora is None:
            break
        orden.append(ganadora)
        quedan = quedan[quedan["variante"] != ganadora]
    orden += quedan.sort_values("i_pinza", ascending=False)["variante"].tolist()
    tabla = resumen.set_index("variante").loc[orden].reset_index()
    tabla.insert(0, "puesto", range(1, len(tabla) + 1))
    return tabla


def grafico(det, ruta_png):
    """Barras de I de pinza por variante, una barra por ronda."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    tabla = det.pivot_table(index="variante", columns="ronda",
                            values="i_pinza", aggfunc="mean")
    tabla = tabla.loc[tabla.mean(axis=1).sort_values(ascending=False).index]

    ancho = 0.8 / max(len(tabla.columns), 1)
    fig, ax = plt.subplots(figsize=(9, 5))
    for k, ronda in enumerate(tabla.columns):
        x = [i + k * ancho for i in range(len(tabla))]
        ax.bar(x, tabla[ronda].values, width=ancho, label=f"ronda {ronda}")
    ax.set_xticks([i + ancho * (len(tabla.columns) - 1) / 2
                   for i in range(len(tabla))])
    ax.set_xticklabels(tabla.index, rotation=20, ha="right")
    ax.set_ylabel("I de pinza (mV/mA)\n|dS| / (Phi_e * Rp)")
    ax.set_title("Variantes del modulo LMG, I de pinza por ronda")
    ax.legend()
    fig.tight_layout()
    fig.savefig(ruta_png, dpi=150)
    plt.close(fig)
    return ruta_png


def analizar(args):
    import glob
    import pandas as pd

    rutas = sorted(glob.glob(os.path.join(args.dir, "*.csv")))
    rutas = [r for r in rutas if os.path.basename(r) not in
             ("metricas_pruebas.csv", "tabla_variantes.csv")]
    if not rutas:
        print(f"No hay CSV en {args.dir}. Corra primero 'capturar'.")
        return 1

    det = pd.DataFrame([metricas(r) for r in rutas])
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 50)
    fmt = lambda x: f"{x:8.3g}"                      # noqa: E731

    par = cargar_parametros(args.parametros)
    duties = set(det["duty"].dropna())
    if len(duties) > 1:
        print(f"AVISO: las pruebas no se midieron todas con el mismo duty: "
              f"{sorted(duties)}. No son comparables entre si.")

    faltan = faltan_parametros(par, det["variante"])
    if faltan:
        print("\n=== PRUEBAS INDIVIDUALES (sin I) ===")
        print(det[["variante", "ronda", "duty", "ds_pinza_mv", "snr_pinza",
                   "cv_pinza", "artefacto_mov", "n_saturadas"]]
              .to_string(index=False, float_format=fmt))
        print(f"\nFaltan en {args.parametros}: {', '.join(faltan)}. Sin "
              f"ellos no se calcula I ni se ordena la tabla.")
        det.to_csv(os.path.join(args.dir, "metricas_pruebas.csv"), index=False)
        return 1

    det = anadir_indice(det, par)
    print("\n=== PRUEBAS INDIVIDUALES ===")
    print(det[["variante", "ronda", "duty", "ds_pinza_mv", "i_pinza",
               "snr_pinza", "cv_pinza", "artefacto_mov", "n_saturadas"]]
          .to_string(index=False, float_format=fmt))

    tabla = ordenar(resumir(det))
    print("\n=== TABLA FINAL, ORDENADA POR LA REGLA ===")
    print(tabla.to_string(index=False, float_format=fmt))

    ganadora, motivo = elegir(tabla)
    print("\n=== DECISION ===")
    print(motivo)
    if ganadora:
        print(f"\nVARIANTE ELEGIDA: {ganadora}")

    det.to_csv(os.path.join(args.dir, "metricas_pruebas.csv"), index=False)
    tabla.to_csv(os.path.join(args.dir, "tabla_variantes.csv"), index=False)
    png = grafico(det, os.path.join(args.dir, "i_pinza.png"))
    print(f"\nTablas en {args.dir} y grafico en {png}")
    return 0


# ============================================================
def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("duty", help="duty para la corriente media, desde la "
                                    "corriente medida al 100%%")
    d.add_argument("--corriente_100_ma", type=float, required=True,
                   help="lo que marca el multimetro con 'W1' en el firmware")
    d.add_argument("--parametros", default=RUTA_PARAMETROS)
    d.set_defaults(func=fijar_duty)

    c = sub.add_parser("capturar", help="correr el protocolo de una variante")
    c.add_argument("--variante", required=True,
                   help="TIPO_distancia, por ejemplo SMD_11mm o PASANTE_9mm")
    c.add_argument("--ronda", type=int, required=True, help="1 o 2")
    c.add_argument("--puerto", default="COM3")
    c.add_argument("--baudios", type=int, default=921600)
    c.add_argument("--canal", type=int, default=1,
                   help="canal LMG donde esta conectado el modulo (1 a 5)")
    c.add_argument("--dir", default=DIR_SALIDA)
    c.add_argument("--parametros", default=RUTA_PARAMETROS)
    c.add_argument("--simulado", action="store_true",
                   help="sin hardware, para probar el flujo")
    c.add_argument("--sin-ventana", action="store_true",
                   help="guiar solo por consola, sin la pantalla completa")
    c.add_argument("--escala", type=float, default=1.0,
                   help="factor de tiempo. Solo para probar, 1.0 en las "
                        "mediciones de verdad")
    c.set_defaults(func=capturar)

    a = sub.add_parser("analizar", help="tabla, grafico y decision")
    a.add_argument("--dir", default=DIR_SALIDA)
    a.add_argument("--parametros", default=RUTA_PARAMETROS)
    a.set_defaults(func=analizar)

    args = p.parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
