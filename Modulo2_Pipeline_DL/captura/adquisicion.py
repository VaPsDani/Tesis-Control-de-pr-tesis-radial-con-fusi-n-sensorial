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

# Esquema del CSV. Los nombres de las primeras 18 columnas NO se cambian:
# los leen preprocesamiento.py, anotar_fases.py y verificar_piloto.py.
# Las columnas nuevas se ANADEN al final, que es donde no rompen nada.
#
# OJO CON LA PALABRA FASE: aqui bloque_tipo es calibracion, preparacion,
# contraccion o reposo. La columna fase de fases.py es otra cosa, reposo,
# dinamica, meseta o reaccion, y se calcula despues sobre el CSV cerrado.
CAMPOS_CSV = ["subject_id", "repetition_id", "timestamp_ms",
              "v1", "v2", "v3", "v4", "v5",
              "ax", "ay", "az", "gx", "gy", "gz",
              "label", "bloque_tipo", "en_margen", "es_calibracion",
              # Anadidas para la sesion guiada:
              "condicion_postural", # estatica o dinamica, POR REPETICION
              "id_participante",    # anonimo, S01, S02, ...
              "posicion_brazo",     # posicion pedida en ese instante,
                                    # vacia salvo en contracciones dinamicas
              "ts_pc_ms",           # reloj de la PC, epoch en ms
              "descartada"]         # 1 si el operador anulo la repeticion

from config_captura import (BAUDIOS_DEFECTO, FLUSH_CADA_N,  # noqa: E402
                            GRACIA_ARRANQUE_S, HUECO_MAX_MS, PERIODO_MS,
                            TIMEOUT_SIN_DATOS_S)

BAUDIOS = BAUDIOS_DEFECTO      # se conserva el nombre anterior


@dataclass
class Muestra:
    t_esp32: int
    valores: List[float]        # v1..v5, ax, ay, az, gx, gy, gz (11)
    t_pc: float                 # time.monotonic() a la llegada
    # Reloj de pared de la PC, en ms desde epoch. El espaciado entre
    # muestras se toma SIEMPRE del reloj del ESP32, que es el bueno. Este
    # solo sirve para cruzar la sesion con hechos externos, como una nota
    # del operador o la hora de una incidencia.
    ts_pc_ms: int = 0


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

        # Caida del puerto. El hilo no decide nada: deja constancia y la
        # sesion, que es quien sabe lo que hay en pantalla, pausa y avisa.
        self.fallo: Optional[str] = None
        self.t_ultimo_dato: float = time.monotonic()
        # Lineas de arranque del firmware, para el JSON de la sesion.
        self.banner: List[str] = []
        self.version_firmware: Optional[str] = None
        # Lineas [OPTICA_*] del firmware: config del ADC, duty de cada LED
        # y reposo por canal en mV (S-barra-r del indice de rendimiento).
        self.optica: dict = {}

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
            except Exception as e:
                # Cable desconectado, adaptador retirado o puerto tomado
                # por otro programa. Se registra y se sale del bucle: la
                # sesion lo detecta en su siguiente tick.
                self.fallo = f"{type(e).__name__}: {e}"
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
            self._encolar(Muestra(t_esp32, valores, time.monotonic(),
                                  int(time.time() * 1000)))
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

        if texto.startswith("[OPTICA_"):
            # Ganancia de los LED y reposo por canal (S-barra-r). Llegan
            # al enviar 'L', antes de la primera muestra, y van al JSON.
            etiqueta, _, resto = texto.partition(" ")
            clave = etiqueta.strip("[]").lower()      # optica_duty, ...
            if clave == "optica_config":
                self.optica[clave] = dict(
                    par.split("=", 1) for par in resto.split() if "=" in par)
            else:
                try:
                    self.optica[clave] = [float(x) for x in resto.split(",")]
                except ValueError:
                    pass
            return

        if texto.startswith("[FW]"):
            # Version del firmware, si la emite. Formato: [FW] version=...
            for par in texto[4:].split():
                if par.startswith("version="):
                    self.version_firmware = par.split("=", 1)[1]
            self.banner.append(texto)
            return

        if texto.startswith("["):
            # Mensajes informativos del firmware: [INIT], [OK], [READY],
            # [AUTOTEST]. Se guardan para el JSON, acotados, porque el
            # autotest del ciclo es parte del estado del equipo ese dia.
            if len(self.banner) < 40:
                self.banner.append(texto)
            return

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

        self._encolar(Muestra(t_esp32, valores, time.monotonic(),
                              int(time.time() * 1000)))

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
        self.t_ultimo_dato = m.t_pc

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

    def caido(self) -> Optional[str]:
        """
        Motivo por el que el enlace se considera caido, o None.

        Dos sintomas: una excepcion al leer, que es el caso del cable
        desconectado, y el silencio prolongado, que es el del ESP32
        reiniciado o el adaptador colgado. El segundo hace falta porque
        readline() con timeout devuelve vacio sin lanzar nada.

        GRACIA DE ARRANQUE: el ESP32 se reinicia al abrirse el puerto y
        tarda en responder, asi que mientras no haya llegado la primera
        muestra se concede un plazo mas largo. Sin esto, cada sesion
        empezaria con un falso aviso de enlace caido.
        """
        if self.fallo:
            return self.fallo
        if not self.simulado and not self.is_alive():
            return "el hilo lector termino"
        callado = time.monotonic() - self.t_ultimo_dato
        limite = (TIMEOUT_SIN_DATOS_S if self.stats.total
                  else GRACIA_ARRANQUE_S)
        if callado > limite:
            return f"sin muestras desde hace {callado:.1f} s"
        return None

    def reanudado(self):
        """
        Reinicia el reloj de silencio al reanudar una pausa.

        Durante la pausa se envia 'S' y el firmware deja de emitir, asi
        que al volver el contador viene con toda la pausa acumulada y
        dispararia un falso aviso.
        """
        self.t_ultimo_dato = time.monotonic()

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

    FLUSH_CADA_N = FLUSH_CADA_N

    def __init__(self, ruta: str, subject_id: int,
                 id_participante: str = ""):
        self.ruta = ruta
        self.subject_id = subject_id
        self.id_participante = id_participante
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
            bloque.condicion_postural,
            self.id_participante,
            bloque.posicion_en(bloque.t_inicio_ms + t_rel_ms),
            m.ts_pc_ms,
            0,          # descartada: se marca al cerrar, si hubo descartes
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


def marcar_descartadas(ruta: str, descartadas) -> int:
    """
    Pone descartada = 1 en las filas de las repeticiones anuladas.

    POR QUE AL CERRAR Y NO EN CALIENTE:
      Cuando el operador descarta una repeticion, sus filas ya estan en
      disco. Reescribir el CSV mientras se captura seria arriesgar la
      sesion entera por una anotacion. Aqui se hace una sola pasada sobre
      el archivo ya cerrado, a un temporal, y se reemplaza al final. Si
      algo falla, el CSV original queda intacto y la lista de descartes
      sigue estando en el JSON de la sesion, que es la fuente de verdad.

    Args:
        descartadas: iterable de pares (repetition_id, label).

    Returns:
        Numero de filas marcadas.
    """
    objetivo = {(int(r), int(l)) for r, l in descartadas}
    if not objetivo or not os.path.exists(ruta):
        return 0

    tmp = ruta + ".tmp"
    marcadas = 0
    with open(ruta, "r", newline="", encoding="utf-8") as fin, \
            open(tmp, "w", newline="", encoding="utf-8") as fout:
        lector = csv.reader(fin)
        escritor = csv.writer(fout)
        cabecera = next(lector)
        escritor.writerow(cabecera)
        i_rep = cabecera.index("repetition_id")
        i_lab = cabecera.index("label")
        i_des = cabecera.index("descartada")
        i_tipo = cabecera.index("bloque_tipo")
        for fila in lector:
            try:
                clave = (int(fila[i_rep]), int(fila[i_lab]))
            except (ValueError, IndexError):
                escritor.writerow(fila)
                continue
            # Solo la preparacion y la contraccion de ese gesto. El
            # reposo que sigue lleva label 0 y comparte repetition_id con
            # los otros tres gestos de la repeticion, asi que no se puede
            # identificar por clave, y ademas sigue siendo reposo valido:
            # que el participante se equivocara de gesto no invalida el
            # reposo posterior.
            if clave in objetivo and fila[i_tipo] in ("preparacion",
                                                      "contraccion"):
                fila[i_des] = "1"
                marcadas += 1
            escritor.writerow(fila)

    os.replace(tmp, ruta)
    return marcadas
