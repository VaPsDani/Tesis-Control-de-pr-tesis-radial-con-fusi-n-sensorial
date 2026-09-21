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
import sys
import time
from datetime import datetime

# anotar_fases.py vive en Modulo2_Pipeline_DL, un nivel arriba.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config_captura import (DIR_IMAGENES, DIR_IMAGENES_ALT,
                            DIR_SALIDA_DEFECTO, DUR_CALIBRACION_MS,
                            DUR_CONTRACCION_MS, DUR_PREPARACION_MS,
                            DUR_REPOSO_MS, RAMPA_CONTRACCION_MS, REFRESCO_MS)
from protocolo import (construir_sesion, resumen_sesion, NOMBRES_GESTOS,
                       TIPO_CALIBRACION, TIPO_CONTRACCION, TIPO_PREPARACION)
from adquisicion import (LectorSerie, EscritorCSV, Muestra,
                         marcar_descartadas)
from interfaz import (VentanaOperador, VentanaParticipante, VentanaPrueba,
                      sonar)


class Sesion:
    def __init__(self, dir_salida: str = None):
        self.op = VentanaOperador()
        if dir_salida:
            self.op.var_salida.set(os.path.abspath(dir_salida))
        self.dir_salida = self.op.var_salida.get()
        self.part = None

        self.bloques = []
        self.idx = 0
        self.t0 = None
        self.pausada = False
        self.corriendo = False
        self.t_pausa_acum = 0.0
        self._t_pausa_ini = None
        self._pausa_por_fallo = False
        self._after_id = None

        self.cola = queue.Queue(maxsize=20000)
        self.lector = None
        self.escritor = None
        self.subject_id = None
        self.id_participante = ""
        self.ruta_csv = None
        self.ruta_json = None

        # Repeticiones anuladas por el operador: pares (repeticion, gesto).
        # Se marcan en el CSV al cerrar y quedan siempre en el JSON.
        self.descartadas = []

        # Prueba de conexion previa a la sesion.
        self.prueba = None
        self.lector_prueba = None
        self.cola_prueba = queue.Queue(maxsize=20000)

        self.op.btn_probar.config(command=self.probar_conexion)
        self.op.btn_iniciar.config(command=self.iniciar)
        self.op.btn_pausa.config(command=self.alternar_pausa)
        self.op.btn_descartar.config(command=self.descartar_repeticion)
        self.op.btn_abortar.config(command=self.abortar)
        self.op.protocol("WM_DELETE_WINDOW", self.abortar)

    # ---------- prueba de conexion ----------
    def probar_conexion(self):
        """
        Abre el puerto, muestra los 5 canales en crudo y no graba nada.

        Sirve para verificar la colocacion del brazalete con tres
        contracciones fuertes antes de gastar los 9 minutos de la sesion.
        """
        if self.corriendo or self.prueba is not None:
            return
        self.lector_prueba = LectorSerie(
            self.op.var_puerto.get(), self.cola_prueba,
            baudios=self.op.baudios(), simulado=self.op.var_simulado.get())
        try:
            self.lector_prueba.abrir()
        except Exception as e:
            self.op.log(f"ERROR abriendo el puerto: {e}")
            self.lector_prueba = None
            return
        self.lector_prueba.start()
        self.lector_prueba.enviar("L")
        self.prueba = VentanaPrueba(self.op, al_cerrar=self._cerrar_prueba)
        self.op.log("Prueba de conexion abierta. Pida 3 contracciones fuertes.")
        self._tick_prueba()

    def _tick_prueba(self):
        if self.prueba is None or self.lector_prueba is None:
            return
        # La cola se vacia y se tira: la prueba no graba.
        while True:
            try:
                self.cola_prueba.get_nowait()
            except queue.Empty:
                break
        self.prueba.actualizar(self.lector_prueba.stats)
        motivo = self.lector_prueba.caido()
        if motivo:
            self.op.log(f"AVISO en la prueba: {motivo}")
        self.op.after(REFRESCO_MS, self._tick_prueba)

    def _cerrar_prueba(self):
        if self.lector_prueba:
            self.lector_prueba.enviar("S")
            self.lector_prueba.detener()
            self.lector_prueba = None
        self.prueba = None
        self.op.log("Prueba de conexion cerrada.")

    # ---------- arranque ----------
    def iniciar(self):
        if self.prueba is not None:
            self.op.log("Cierre la prueba de conexion antes de iniciar.")
            return
        try:
            self.subject_id = int(self.op.var_subject.get())
        except ValueError:
            self.op.log("ERROR: subject_id debe ser un entero.")
            return

        self.id_participante = self.op.var_id_participante.get().strip()
        if not self.id_participante:
            self.op.log("ERROR: falta el id anonimo del participante (S01).")
            return
        self.dir_salida = self.op.var_salida.get() or DIR_SALIDA_DEFECTO

        self.bloques = construir_sesion(self.subject_id)
        r = resumen_sesion(self.bloques)
        self.op.log(f"Sesion del sujeto {self.subject_id} "
                    f"({self.id_participante}): "
                    f"{r['n_bloques']} bloques, {r['duracion_total_s']:.0f} s")
        self.op.log(f"Ratio Rest:activa = {r['ratio_rest_vs_activa']}:1, "
                    f"~{r['ventanas_estimadas']} ventanas")

        marca = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = f"s{self.subject_id:02d}_{marca}"
        self.ruta_csv = os.path.join(self.dir_salida, f"{base}.csv")
        self.ruta_json = os.path.join(self.dir_salida, f"{base}.json")

        self.escritor = EscritorCSV(self.ruta_csv, self.subject_id,
                                    id_participante=self.id_participante)
        try:
            self.escritor.abrir()
        except FileExistsError as e:
            self.op.log(f"ERROR: {e}")
            return

        self.lector = LectorSerie(self.op.var_puerto.get(), self.cola,
                                  baudios=self.op.baudios(),
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
        n_img = self.part.cargar_imagenes(DIR_IMAGENES, DIR_IMAGENES_ALT)
        if n_img < len(NOMBRES_GESTOS):
            self.op.log(f"AVISO: solo {n_img} de {len(NOMBRES_GESTOS)} "
                        f"imagenes de gesto. Faltan PNG en "
                        f"{os.path.abspath(DIR_IMAGENES)}")

        self.idx = 0
        self.t0 = time.monotonic()
        self.t_pausa_acum = 0.0
        self.corriendo = True
        self.op.btn_probar.config(state="disabled")
        self.op.btn_iniciar.config(state="disabled")
        self.op.btn_pausa.config(state="normal")
        self.op.btn_descartar.config(state="normal")
        self.op.btn_abortar.config(state="normal")
        sonar("calibracion")

        self.lector.marcar_bloque(0)
        self.op.log(f"CSV: {self.ruta_csv}")
        self._after_id = self.op.after(REFRESCO_MS, self.tick)

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
        self._vigilar_enlace()

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
                sonar(bloque.tipo)
                self.op.log(f"Bloque {self.idx+1}/{len(self.bloques)}: "
                            f"{bloque.tipo} {bloque.nombre_gesto} "
                            f"rep={bloque.repetition_id}")

            restante = (bloque.t_fin_ms - t_ms) / 1000.0
            total_ms = self.bloques[-1].t_fin_ms
            self.part.actualizar(bloque, restante, t_ms / total_ms,
                                 self.idx, len(self.bloques),
                                 transcurrido_ms=t_ms - bloque.t_inicio_ms)
            self.op.lbl_bloque.config(
                text=f"{bloque.tipo} · {bloque.nombre_gesto} · "
                     f"rep {bloque.repetition_id} · {restante:.1f} s")

        self._after_id = self.op.after(REFRESCO_MS, self.tick)

    def _vigilar_enlace(self):
        """
        Si el puerto se cae, pausa sola y avisa en las dos pantallas.

        Lo ya escrito no se pierde: la pausa hace flush y fsync, asi que
        el CSV queda completo hasta la ultima fila. Al reanudar se emite
        un marcador nuevo y el hueco queda registrado como discontinuidad
        en vez de tenderse un puente por encima.
        """
        motivo = self.lector.caido() if self.lector else "sin lector"
        if motivo and not self.pausada:
            self._pausa_por_fallo = True
            self.alternar_pausa()
            self.op.log(f"ENLACE CAIDO: {motivo}. Sesion pausada, "
                        f"CSV a salvo. Revise el cable y reanude.")
            if self.part:
                self.part.mostrar_pausa("Problema tecnico. Espere al operador.")
            sonar("aviso")
        elif not motivo and self.pausada and self._pausa_por_fallo:
            self.op.log("El enlace volvio. Pulse Reanudar cuando el "
                        "participante este listo.")
            self._pausa_por_fallo = False

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
            if self.part:
                self.part.mostrar_pausa("Pausa. Relaje el brazo y espere.")
        else:
            self.t_pausa_acum += time.monotonic() - self._t_pausa_ini
            self._t_pausa_ini = None
            self._pausa_por_fallo = False
            self.lector.enviar("L")
            # Durante la pausa el firmware no emite, asi que el reloj de
            # silencio viene con toda la pausa encima y dispararia un
            # falso aviso de enlace caido en el primer tick.
            self.lector.reanudado()
            # Marcador nuevo: el hueco de la pausa queda registrado y
            # preprocesamiento.py lo vera como discontinuidad.
            self.lector.marcar_bloque(self.idx)
            self.op.btn_pausa.config(text="Pausar")
            self.op.log("REANUDADA. Marcador nuevo emitido.")

    def descartar_repeticion(self):
        """
        Anula la repeticion en curso, o la ultima contraccion hecha.

        Se usa cuando el participante ejecuta un gesto distinto al que
        pedia la pantalla. No borra nada: marca la columna descartada al
        cerrar el CSV y deja constancia en el JSON. Borrar filas dejaria
        un hueco temporal sin explicacion en el archivo.
        """
        if not self.corriendo:
            return
        bloque = None
        for b in reversed(self.bloques[:self.idx + 1]):
            if b.tipo in (TIPO_CONTRACCION, TIPO_PREPARACION):
                bloque = b
                break
        if bloque is None:
            self.op.log("Todavia no hay ninguna repeticion que descartar.")
            return
        clave = (bloque.repetition_id, bloque.label)
        if clave in self.descartadas:
            self.op.log(f"La repeticion {clave[0]} de "
                        f"{NOMBRES_GESTOS[clave[1]]} ya estaba descartada.")
            return
        self.descartadas.append(clave)
        self.op.log(f"DESCARTADA la repeticion {clave[0]} de "
                    f"{NOMBRES_GESTOS[clave[1]]}. Se marca al cerrar el CSV.")
        sonar("aviso")

    def abortar(self):
        if self.corriendo:
            self.op.log("ABORTADA por el operador.")
            self._cerrar(abortada=True)
        if self.lector_prueba:
            self._cerrar_prueba()
        self.op.destroy()

    def finalizar(self):
        self.op.log("Sesion COMPLETA.")
        if self.part:
            self.part.mostrar_fin("Gracias")
        self._cerrar(abortada=False)

    def _cerrar(self, abortada: bool):
        self.corriendo = False
        # Cancela el tick pendiente: si no, Tk intenta ejecutarlo despues
        # de destruir la ventana y escupe un error que no significa nada
        # pero asusta al operador.
        if self._after_id is not None:
            try:
                self.op.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        if self.lector:
            self.lector.enviar("S")
            self.drenar_cola()
            self.lector.detener()
        if self.escritor:
            self.escritor.cerrar()
            self.op.log(f"CSV cerrado: {self.escritor.filas_escritas} filas")
            self.marcar_descartes()
            self.anotar_fases()
        self.guardar_metadatos(abortada)
        self.op.btn_pausa.config(state="disabled")
        self.op.btn_descartar.config(state="disabled")
        self.op.btn_abortar.config(state="disabled")

    def marcar_descartes(self):
        """
        Pasa la columna descartada a 1 en las repeticiones anuladas.

        Un fallo aqui no compromete nada: el dato crudo ya esta en disco
        y la lista tambien queda en el JSON de la sesion.
        """
        if not self.descartadas or not self.ruta_csv:
            return
        try:
            n = marcar_descartadas(self.ruta_csv, self.descartadas)
            self.op.log(f"Descartes marcados en {n} filas.")
        except Exception as e:
            self.op.log(f"AVISO: no se pudo marcar los descartes ({e}). "
                        f"La lista esta en el JSON de la sesion.")

    def anotar_fases(self):
        """
        Columna fase sobre el CSV ya cerrado. Un fallo aqui NO compromete
        la sesion: el dato crudo ya esta en disco y la columna se puede
        calcular despues con anotar_fases.py.
        """
        if not self.ruta_csv or not self.escritor.filas_escritas:
            return
        try:
            from anotar_fases import anotar_csv
            r = anotar_csv(self.ruta_csv, comparar_bases=True)["resumen"]
            self.op.log(f"Fases: {r['n_gestos']} gestos, onset mediano "
                        f"{r['onset_mediana_ms']} ms, "
                        f"{r['pct_sospechosos']}% sospechosos")
        except Exception as e:
            self.op.log(f"AVISO: no se pudo anotar la columna fase ({e}). "
                        f"Ejecute anotar_fases.py sobre el CSV.")

    # ---------- metadatos ----------
    def guardar_metadatos(self, abortada: bool):
        """
        JSON por sesion. En la validacion sobre NinaPro DB5 dos pliegues
        rindieron peor que el resto sin que pudieramos explicar por que,
        porque el dataset publico no trae estos datos. Con el nuestro si.
        """
        if not self.ruta_json:
            return
        s = self.lector.stats if self.lector else None
        # La secuencia se toma de los bloques de contraccion, que son los
        # que definen el orden presentado. Guardarla es lo que hace la
        # sesion reproducible sin volver a ejecutar el contrabalanceo.
        contracciones = [b for b in self.bloques if b.tipo == TIPO_CONTRACCION]
        secuencia = [b.label for b in contracciones]
        duracion_s = (time.monotonic() - self.t0 - self.t_pausa_acum
                      if self.t0 else 0.0)
        meta = {
            "subject_id": self.subject_id,
            "id_participante": self.id_participante,
            "fecha": datetime.now().isoformat(timespec="seconds"),
            "hora_inicio": datetime.now().isoformat(timespec="seconds"),
            "duracion_s": round(duracion_s, 1),
            "abortada": abortada,
            "csv": os.path.basename(self.ruta_csv) if self.ruta_csv else None,
            "participante": self.op.metadatos(),
            "protocolo": resumen_sesion(self.bloques),
            "tiempos_ms": {
                "calibracion": DUR_CALIBRACION_MS,
                "preparacion": DUR_PREPARACION_MS,
                "contraccion": DUR_CONTRACCION_MS,
                "reposo": DUR_REPOSO_MS,
                "rampa_contraccion": RAMPA_CONTRACCION_MS,
            },
            "orden_gestos_efectivo": secuencia,
            "orden_gestos_nombres": [NOMBRES_GESTOS[g] for g in secuencia],
            "condiciones_posturales": [b.condicion_postural for b in contracciones],
            "orden_posiciones": ["|".join(b.orden_posiciones)
                                 for b in contracciones],
            "semilla_contrabalanceo": self.subject_id,
            "repeticiones_descartadas": [
                {"repeticion": r, "label": l, "gesto": NOMBRES_GESTOS[l]}
                for r, l in self.descartadas],
            "adquisicion": {
                "puerto": self.op.var_puerto.get(),
                "simulado": bool(self.op.var_simulado.get()),
                "baudios": self.op.baudios(),
                "version_firmware": (self.lector.version_firmware
                                     if self.lector else None),
                "banner_firmware": self.lector.banner if self.lector else [],
                "muestras_totales": s.total if s else 0,
                "huecos": s.huecos if s else 0,
                "muestras_perdidas_est": s.muestras_perdidas_est if s else 0,
                "lineas_malformadas": s.lineas_malformadas if s else 0,
            } if s else {},
            # Ganancia de los LED y reposo por canal al iniciar la sesion.
            # Vacio si el firmware es anterior a la Tarea 3; reposo en 0
            # si nunca se autocalibro.
            "optica": self.lector.optica if self.lector else {},
        }
        os.makedirs(os.path.dirname(self.ruta_json) or ".", exist_ok=True)
        with open(self.ruta_json, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
        self.op.log(f"Metadatos: {self.ruta_json}")

    def run(self):
        self.op.mainloop()
