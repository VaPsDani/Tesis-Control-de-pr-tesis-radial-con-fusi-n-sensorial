"""
sesion.py - Orquestador de una sesion de captura
=================================================
Protesis transradial - Captura con voluntarios

Une protocolo, adquisicion e interfaz. El reloj de la sesion es el de la
PC (time.monotonic) para decidir QUE se muestra al participante, pero la
etiqueta de cada muestra se asigna por el timestamp del ESP32 relativo al
marcador del bloque, que es el reloj fiable (ver adquisicion.py).

PAUSA Y ABORTO SEGUROS:
  Ambos cierran el CSV con flush y fsync, de modo que el archivo queda
  truncado en una fila completa y nunca a medias. Al reanudar tras una
  pausa se emite un marcador nuevo, asi que el hueco temporal queda
  registrado y la segmentacion de preprocesamiento.py lo detectara como
  discontinuidad en vez de tender un puente por encima.
"""

import json
import os
import queue
import time
from datetime import datetime

from protocolo import construir_sesion, resumen_sesion, TIPO_CALIBRACION
from adquisicion import LectorSerie, EscritorCSV, Muestra
from interfaz import VentanaOperador, VentanaParticipante

REFRESCO_MS = 50          # 20 Hz de refresco de interfaz


class Sesion:
    def __init__(self, dir_salida: str = "sesiones"):
        self.dir_salida = dir_salida
        self.op = VentanaOperador()
        self.part = None

        self.bloques = []
        self.idx = 0
        self.t0 = None
        self.pausada = False
        self.corriendo = False
        self.t_pausa_acum = 0.0
        self._t_pausa_ini = None

        self.cola = queue.Queue(maxsize=20000)
        self.lector = None
        self.escritor = None
        self.subject_id = None
        self.ruta_csv = None

        self.op.btn_iniciar.config(command=self.iniciar)
        self.op.btn_pausa.config(command=self.alternar_pausa)
        self.op.btn_abortar.config(command=self.abortar)
        self.op.protocol("WM_DELETE_WINDOW", self.abortar)

    # ---------- arranque ----------
    def iniciar(self):
        try:
            self.subject_id = int(self.op.var_subject.get())
        except ValueError:
            self.op.log("ERROR: subject_id debe ser un entero.")
            return

        self.bloques = construir_sesion(self.subject_id)
        r = resumen_sesion(self.bloques)
        self.op.log(f"Sesion del sujeto {self.subject_id}: "
                    f"{r['n_bloques']} bloques, {r['duracion_total_s']:.0f} s")
        self.op.log(f"Ratio Rest:activa = {r['ratio_rest_vs_activa']}:1, "
                    f"~{r['ventanas_estimadas']} ventanas")

        marca = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = f"s{self.subject_id:02d}_{marca}"
        self.ruta_csv = os.path.join(self.dir_salida, f"{base}.csv")
        self.ruta_json = os.path.join(self.dir_salida, f"{base}.json")

        self.escritor = EscritorCSV(self.ruta_csv, self.subject_id)
        try:
            self.escritor.abrir()
        except FileExistsError as e:
            self.op.log(f"ERROR: {e}")
            return

        self.lector = LectorSerie(self.op.var_puerto.get(), self.cola,
                                  simulado=self.op.var_simulado.get())
        try:
            self.lector.abrir()
        except Exception as e:
            self.op.log(f"ERROR abriendo el puerto: {e}")
            self.escritor.cerrar()
            return

        self.lector.start()
        self.lector.enviar("L")

        self.part = VentanaParticipante(self.op)
        self.part.cargar_imagenes(
            os.path.join(os.path.dirname(__file__), "imagenes"))

        self.idx = 0
        self.t0 = time.monotonic()
        self.t_pausa_acum = 0.0
        self.corriendo = True
        self.op.btn_iniciar.config(state="disabled")
        self.op.btn_pausa.config(state="normal")
        self.op.btn_abortar.config(state="normal")

        self.lector.marcar_bloque(0)
        self.op.log(f"CSV: {self.ruta_csv}")
        self.op.after(REFRESCO_MS, self.tick)

    # ---------- bucle ----------
    def _t_sesion(self) -> float:
        if self._t_pausa_ini is not None:
            return self._t_pausa_ini - self.t0 - self.t_pausa_acum
        return time.monotonic() - self.t0 - self.t_pausa_acum

    def tick(self):
        if not self.corriendo:
            return

        self.drenar_cola()
        self.op.actualizar_stats(self.lector.stats)

        if not self.pausada:
            t_ms = self._t_sesion() * 1000.0
            bloque = self.bloques[self.idx]

            if t_ms >= bloque.t_fin_ms:
                self.idx += 1
                if self.idx >= len(self.bloques):
                    self.finalizar()
                    return
                # Marcador en cada cambio de bloque: reancla los relojes
                # y acota la deriva a un solo bloque.
                self.lector.marcar_bloque(self.idx)
                bloque = self.bloques[self.idx]
                self.op.log(f"Bloque {self.idx+1}/{len(self.bloques)}: "
                            f"{bloque.tipo} {bloque.nombre_gesto} "
                            f"rep={bloque.repetition_id}")

            restante = (bloque.t_fin_ms - t_ms) / 1000.0
            total_ms = self.bloques[-1].t_fin_ms
            self.part.actualizar(bloque, restante, t_ms / total_ms,
                                 self.idx, len(self.bloques))
            self.op.lbl_bloque.config(
                text=f"{bloque.tipo} · {bloque.nombre_gesto} · "
                     f"rep {bloque.repetition_id} · {restante:.1f} s")

        self.op.after(REFRESCO_MS, self.tick)

    def drenar_cola(self):
        """
        Vacia la cola y escribe. La etiqueta sale del timestamp del
        ESP32 comparado con los marcadores, no del reloj de la PC.
        """
        escritas = 0
        while True:
            try:
                m: Muestra = self.cola.get_nowait()
            except queue.Empty:
                break

            idx_bloque = self.lector.bloque_de(m.t_esp32)
            if idx_bloque is None:
                continue          # llego antes del primer marcador
            bloque = self.bloques[idx_bloque]

            # Instante del marcador de ESE bloque. Si por cualquier
            # motivo no esta, se descarta la muestra en vez de
            # etiquetarla con un origen temporal equivocado.
            t_marca = None
            for t, i in self.lector.marcadores:
                if i == idx_bloque:
                    t_marca = t
                    break
            if t_marca is None:
                continue

            self.escritor.escribir(m, bloque, int(m.t_esp32 - t_marca))
            escritas += 1
            if escritas > 5000:   # no monopolizar el hilo de la interfaz
                break

    # ---------- control ----------
    def alternar_pausa(self):
        self.pausada = not self.pausada
        if self.pausada:
            self._t_pausa_ini = time.monotonic()
            self.lector.enviar("S")
            self.drenar_cola()
            self.escritor.flush()
            self.op.btn_pausa.config(text="Reanudar")
            self.op.log("PAUSA. El CSV queda consistente hasta esta fila.")
        else:
            self.t_pausa_acum += time.monotonic() - self._t_pausa_ini
            self._t_pausa_ini = None
            self.lector.enviar("L")
            # Marcador nuevo: el hueco de la pausa queda registrado y
            # preprocesamiento.py lo vera como discontinuidad.
            self.lector.marcar_bloque(self.idx)
            self.op.btn_pausa.config(text="Pausar")
            self.op.log("REANUDADA. Marcador nuevo emitido.")

    def abortar(self):
        if self.corriendo:
            self.op.log("ABORTADA por el operador.")
            self._cerrar(abortada=True)
        self.op.destroy()

    def finalizar(self):
        self.op.log("Sesion COMPLETA.")
        if self.part:
            self.part.mostrar_fin("Gracias")
        self._cerrar(abortada=False)

    def _cerrar(self, abortada: bool):
        self.corriendo = False
        if self.lector:
            self.lector.enviar("S")
            self.drenar_cola()
            self.lector.detener()
        if self.escritor:
            self.escritor.cerrar()
            self.op.log(f"CSV cerrado: {self.escritor.filas_escritas} filas")
        self.guardar_metadatos(abortada)
        self.op.btn_pausa.config(state="disabled")
        self.op.btn_abortar.config(state="disabled")

    # ---------- metadatos ----------
    def guardar_metadatos(self, abortada: bool):
        """
        JSON por sesion. En la linea base EMG dos pliegues rindieron peor
        que el resto sin que pudieramos explicar por que, porque el
        dataset publico no trae estos datos. Con el nuestro si.
        """
        if not self.ruta_json:
            return
        s = self.lector.stats if self.lector else None
        secuencia = [b.label for b in self.bloques
                     if b.tipo != TIPO_CALIBRACION and b.label != 0]
        meta = {
            "subject_id": self.subject_id,
            "hora_inicio": datetime.now().isoformat(timespec="seconds"),
            "abortada": abortada,
            "csv": os.path.basename(self.ruta_csv) if self.ruta_csv else None,
            "participante": self.op.metadatos(),
            "protocolo": resumen_sesion(self.bloques),
            "orden_gestos_efectivo": secuencia,
            "semilla_contrabalanceo": self.subject_id,
            "adquisicion": {
                "baudios": 921600,
                "muestras_totales": s.total if s else 0,
                "huecos": s.huecos if s else 0,
                "muestras_perdidas_est": s.muestras_perdidas_est if s else 0,
                "lineas_malformadas": s.lineas_malformadas if s else 0,
            } if s else {},
        }
        os.makedirs(os.path.dirname(self.ruta_json) or ".", exist_ok=True)
        with open(self.ruta_json, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
        self.op.log(f"Metadatos: {self.ruta_json}")

    def run(self):
        self.op.mainloop()
