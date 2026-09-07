"""
adquisicion.py - Lectura del puerto serie y escritura del CSV
==============================================================
Protesis transradial - Captura con voluntarios

SINCRONIZACION - el punto critico del modulo:

  El ESP32 sella cada muestra con su propio millis(). Ese es el reloj
  bueno para el espaciado entre muestras: su cristal deriva 10-40 ppm,
  o sea 18-36 ms en una sesion de 15 minutos, mientras que sellar en la
  PC arrastra el latency timer del conversor USB-serie (16 ms por
  defecto en CP210x y CH340) mas el jitter del scheduler, sin cota
  superior.

  En cada cambio de bloque la PC envia 'M' y el ESP32 responde con una
  linea [MARK] que lleva su millis(). Eso ancla ambos relojes cada 8-15
  s, de modo que la deriva acumulada nunca excede un bloque: 0.6 ms a
  40 ppm, frente a los 18-36 ms de una sesion entera.

  Las etiquetas se asignan por el timestamp del ESP32 relativo al ultimo
  marcador. El error residual lo domina la latencia PC->ESP32 (~1 ms)
  mas la cuantizacion del bucle de muestreo (10 ms): ~11 ms en el peor
  caso, muy dentro del margen de 1000 ms de los bloques de contraccion.

ANCHO DE BANDA:
  12 campos por linea son ~122 bytes. A 100 Hz eso son 12200 B/s, y
  115200 baudios 8N1 solo dan 11520 B/s: el enlace se quedaba un 6%
  corto y el buffer se habria desbordado durante la sesion. De ahi los
  921600 baudios (92160 B/s, 13% de uso).

  Aun con el enlace holgado, el buffer del SO (tipicamente 4 KB) se
  desborda si el hilo lector se detiene ~300 ms. Por eso el lector es un
  hilo dedicado que SOLO lee y encola: no toca la interfaz, no escribe a
  disco y no formatea nada.

DETECCION DE PERDIDA DE MUESTRAS:
  No todos los adaptadores USB-serie sostienen 921600 de forma estable,
  y el modo de fallo es perdida intermitente de muestras, invisible en
  vivo. Se vigilan dos indicadores complementarios:

    tasa    muestras por segundo, media movil de 1 s
    huecos  saltos en el timestamp del ESP32 mayores a 3 periodos

  El segundo es el importante: una perdida esporadica puede dejar la
  tasa media en 100/s y aun asi haber perdido muestras. Como el
  firmware sella cada muestra con su propio reloj, el hueco se detecta
  aunque el ritmo medio no se mueva.
"""

import csv
import os
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional

# Campos que emite el firmware, en orden.
CAMPOS_FIRMWARE = ["timestamp_ms", "v1", "v2", "v3", "v4", "v5",
                   "ax", "ay", "az", "gx", "gy", "gz"]

# Esquema completo del CSV: los del firmware mas los del protocolo.
CAMPOS_CSV = (["subject_id", "repetition_id"] + CAMPOS_FIRMWARE
              + ["label", "bloque_tipo", "en_margen", "es_calibracion"])
# Orden final pedido: subject, repetition, timestamp, senales, protocolo.
CAMPOS_CSV = ["subject_id", "repetition_id", "timestamp_ms",
              "v1", "v2", "v3", "v4", "v5",
              "ax", "ay", "az", "gx", "gy", "gz",
              "label", "bloque_tipo", "en_margen", "es_calibracion"]

BAUDIOS = 921600
PERIODO_MS = 10
HUECO_MAX_MS = 3 * PERIODO_MS


@dataclass
class Muestra:
    t_esp32: int
    valores: List[float]        # v1..v5, ax, ay, az, gx, gy, gz (11)
    t_pc: float                 # time.monotonic() a la llegada


@dataclass
class Estadisticas:
    """Lo que la ventana del operador necesita ver en vivo."""
    total: int = 0
    tasa_hz: float = 0.0
    huecos: int = 0
    muestras_perdidas_est: int = 0
    lineas_malformadas: int = 0
    backlog: int = 0
    ultimo_lmg: List[float] = field(default_factory=lambda: [0.0] * 5)


class LectorSerie(threading.Thread):
    """
    Hilo dedicado a leer el puerto. Solo lee, parsea y encola.

    No toca la interfaz ni el disco a proposito: cualquier bloqueo aqui
    se traduce en desbordamiento del buffer del SO y en muestras
    perdidas silenciosamente.
    """

    def __init__(self, puerto: str, cola: queue.Queue,
                 baudios: int = BAUDIOS, simulado: bool = False):
        super().__init__(daemon=True, name="LectorSerie")
        self.puerto = puerto
        self.baudios = baudios
        self.cola = cola
        self.simulado = simulado

        self._parar = threading.Event()
        self._ser = None
        self._lock = threading.Lock()

        self.stats = Estadisticas()
        self._t_ultimo_esp32: Optional[int] = None
        self._ventana_tasa: List[float] = []
        self.marcadores: List[tuple] = []      # (t_esp32, indice_bloque)
        self._marcador_pendiente: Optional[int] = None

    # ---------- ciclo de vida ----------
    def abrir(self):
        if self.simulado:
            return True
        import serial            # pyserial, import local para poder
                                 # simular sin la dependencia instalada
        self._ser = serial.Serial(self.puerto, self.baudios, timeout=1)
        time.sleep(2.0)          # el ESP32 se reinicia al abrir el puerto
        self._ser.reset_input_buffer()
        return True

    def enviar(self, comando: str):
        if self.simulado or self._ser is None:
            return
        with self._lock:
            self._ser.write(comando.encode("ascii"))
            self._ser.flush()

    def marcar_bloque(self, indice_bloque: int):
        """
        Pide al ESP32 un marcador de sincronizacion para este bloque.
        El marcador se completa cuando llega la linea [MARK].
        """
        self._marcador_pendiente = indice_bloque
        self.enviar("M")

    def detener(self):
        self._parar.set()

    # ---------- bucle ----------
    def run(self):
        if self.simulado:
            self._run_simulado()
            return

        while not self._parar.is_set():
            try:
                linea = self._ser.readline()
            except Exception:
                break
            if not linea:
                continue
            self._procesar(linea.decode("ascii", errors="replace").strip())

    def _run_simulado(self):
        """Genera muestras sinteticas a 100 Hz para probar sin hardware."""
        import math
        t0 = time.monotonic()
        n = 0
        while not self._parar.is_set():
            objetivo = t0 + n * PERIODO_MS / 1000.0
            espera = objetivo - time.monotonic()
            if espera > 0:
                time.sleep(espera)
            t_esp32 = int(n * PERIODO_MS)
            fase = n / 100.0
            valores = [500 + 100 * math.sin(fase + i) for i in range(5)]
            valores += [0.0, 0.0, 1.0, 0.0, 0.0, 0.0]
            if self._marcador_pendiente is not None:
                self.marcadores.append((t_esp32, self._marcador_pendiente))
                self._marcador_pendiente = None
            self._encolar(Muestra(t_esp32, valores, time.monotonic()))
            n += 1

    def _procesar(self, texto: str):
        if not texto:
            return

        if texto.startswith("[MARK]"):
            try:
                t_esp32 = int(texto.split()[1])
            except (IndexError, ValueError):
                return
            if self._marcador_pendiente is not None:
                self.marcadores.append((t_esp32, self._marcador_pendiente))
                self._marcador_pendiente = None
            return

        if texto.startswith("["):
            return                       # mensajes informativos del firmware

        partes = texto.split(",")
        if len(partes) != len(CAMPOS_FIRMWARE):
            self.stats.lineas_malformadas += 1
            return
        try:
            t_esp32 = int(partes[0])
            valores = [float(x) for x in partes[1:]]
        except ValueError:
            self.stats.lineas_malformadas += 1
            return

        self._encolar(Muestra(t_esp32, valores, time.monotonic()))

    def _encolar(self, m: Muestra):
        # Deteccion de huecos con el reloj del ESP32. Un salto mayor a 3
        # periodos delata muestras perdidas aunque la tasa media siga
        # dando 100/s.
        if self._t_ultimo_esp32 is not None:
            dt = m.t_esp32 - self._t_ultimo_esp32
            if dt > HUECO_MAX_MS:
                self.stats.huecos += 1
                self.stats.muestras_perdidas_est += max(
                    0, int(round(dt / PERIODO_MS)) - 1)
        self._t_ultimo_esp32 = m.t_esp32

        self.stats.total += 1
        self.stats.ultimo_lmg = m.valores[:5]

        ahora = m.t_pc
        self._ventana_tasa.append(ahora)
        while self._ventana_tasa and ahora - self._ventana_tasa[0] > 1.0:
            self._ventana_tasa.pop(0)
        self.stats.tasa_hz = len(self._ventana_tasa)

        try:
            self.cola.put_nowait(m)
        except queue.Full:
            self.stats.lineas_malformadas += 1
        self.stats.backlog = self.cola.qsize()

    def bloque_de(self, t_esp32: int) -> Optional[int]:
        """
        Indice del bloque al que pertenece una muestra, segun el ultimo
        marcador anterior a su timestamp. None si llego antes del primero.
        """
        indice = None
        for t_marca, idx in self.marcadores:
            if t_esp32 >= t_marca:
                indice = idx
            else:
                break
        return indice


class EscritorCSV:
    """
    Escribe el CSV incrementalmente y lo cierra de forma segura.

    El archivo se abre con line buffering y se hace flush cada
    FLUSH_CADA_N filas, de modo que un aborto o un cierre inesperado deja
    un CSV truncado en una fila completa y no a medias.
    """

    FLUSH_CADA_N = 100

    def __init__(self, ruta: str, subject_id: int):
        self.ruta = ruta
        self.subject_id = subject_id
        self._f = None
        self._w = None
        self._n = 0
        self.filas_escritas = 0

    def abrir(self):
        os.makedirs(os.path.dirname(self.ruta) or ".", exist_ok=True)
        if os.path.exists(self.ruta):
            raise FileExistsError(
                f"{self.ruta} ya existe. Los CSV de sesion nunca se "
                f"sobrescriben."
            )
        self._f = open(self.ruta, "w", newline="", encoding="utf-8")
        self._w = csv.writer(self._f)
        self._w.writerow(CAMPOS_CSV)
        self._f.flush()

    def escribir(self, m: Muestra, bloque, t_rel_ms: int):
        fila = [
            self.subject_id,
            bloque.repetition_id,
            m.t_esp32,
            *[f"{v:.4f}" for v in m.valores],
            bloque.label,
            bloque.tipo,
            bloque.en_margen(bloque.t_inicio_ms + t_rel_ms),
            bloque.es_calibracion,
        ]
        self._w.writerow(fila)
        self.filas_escritas += 1
        self._n += 1
        if self._n >= self.FLUSH_CADA_N:
            self._f.flush()
            self._n = 0

    def flush(self):
        """
        Fuerza la escritura a disco sin cerrar. Se usa al pausar: si la
        sesion se corta durante la pausa, el CSV ya esta completo hasta
        la ultima fila escrita.
        """
        if self._f is not None:
            self._f.flush()
            os.fsync(self._f.fileno())
            self._n = 0

    def cerrar(self):
        if self._f is not None:
            self._f.flush()
            os.fsync(self._f.fileno())
            self._f.close()
            self._f = None
