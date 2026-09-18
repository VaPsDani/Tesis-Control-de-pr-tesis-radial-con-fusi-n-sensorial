"""
interfaz.py - Ventanas de participante y operador
==================================================
Protesis transradial - Captura con voluntarios

DOS VENTANAS CON PUBLICOS DISTINTOS:

  Participante  Pantalla completa, pensada para verse a distancia. Solo
                lo que la persona necesita: que gesto hacer, cuanto
                falta y en que estado esta. Sin numeros de diagnostico,
                que solo distraen.

  Operador      Controles, metadatos y monitor en vivo de los 5 canales
                LMG. Sirve para detectar un sensor despegado ANTES de
                perder la sesion entera, y para vigilar la tasa de
                muestreo.

  Tkinter es de la biblioteca estandar, asi que la app no anade ninguna
  dependencia mas alla de pyserial. El grafico va en un Canvas nativo y
  no en matplotlib: a 100 Hz, redibujar un Figure cada 50 ms consume mas
  CPU de la que conviene gastar mientras el hilo lector tiene que
  vaciar el buffer del puerto.

COLORES DE ESTADO:
  Reposo y contraccion tienen que distinguirse de un vistazo y sin leer.
  Se usa color de fondo completo, no un detalle pequeno.
"""

import os
import tkinter as tk
from tkinter import filedialog, ttk

from config_captura import (BAUDIOS_DEFECTO, BLOQUE_DINAMICO, BLOQUE_ESTATICO,
                            BLOQUES_POSTURA, COLOR_CALIBRACION, COLOR_CONTRACCION,
                            COLOR_FIN, COLOR_PAUSA, COLOR_PREPARACION,
                            COLOR_RAMPA, COLOR_REPOSO, COLOR_TEXTO, COLORES_LMG,
                            DIR_IMAGENES, DIR_IMAGENES_ALT, DIR_SALIDA_DEFECTO,
                            FUENTE_CUENTA, FUENTE_FASE, FUENTE_GESTO,
                            FUENTE_INSTRUCCION, FUENTE_PIE, FUENTE_POSICION,
                            LADO_IMAGEN, PUERTO_DEFECTO, RAMPA_CONTRACCION_MS,
                            SONIDO_HABILITADO, SONIDO_HZ, SONIDO_MS,
                            TEXTO_MOVIMIENTO_LENTO, TEXTO_POSICION)
from protocolo import (TIPO_CALIBRACION, TIPO_CONTRACCION, TIPO_PREPARACION,
                       TIPO_REPOSO, NOMBRES_GESTOS)


def color_de(tipo: str) -> str:
    return {
        TIPO_CONTRACCION: COLOR_CONTRACCION,
        TIPO_CALIBRACION: COLOR_CALIBRACION,
        TIPO_PREPARACION: COLOR_PREPARACION,
    }.get(tipo, COLOR_REPOSO)


# Nombre de la fase en texto, porque el color NO puede ser la unica
# senal: un participante con daltonismo tiene que distinguir las fases
# igual de rapido que los demas.
TEXTO_FASE = {
    TIPO_CALIBRACION: "FASE 0 de 3  ·  CALIBRACION",
    TIPO_PREPARACION: "FASE 1 de 3  ·  PREPARESE",
    TIPO_CONTRACCION: "FASE 2 de 3  ·  CONTRAIGA",
    TIPO_REPOSO:      "FASE 3 de 3  ·  DESCANSE",
}


def sonar(clave: str = "aviso"):
    """
    Aviso breve en cada cambio de fase. Nunca interrumpe la sesion: si el
    sistema no puede emitir sonido, se sigue sin el.
    """
    if not SONIDO_HABILITADO:
        return
    try:
        import winsound
        winsound.Beep(SONIDO_HZ.get(clave, SONIDO_HZ["aviso"]), SONIDO_MS)
        return
    except Exception:
        pass
    try:
        # La campana de Tk existe en cualquier plataforma con display.
        tk._default_root.bell()
    except Exception:
        pass


# ============================================================
# VENTANA DEL PARTICIPANTE
# ============================================================
class VentanaParticipante(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Sesion de captura")
        self.configure(bg=COLOR_REPOSO)
        self.attributes("-fullscreen", True)
        self.bind("<Escape>", lambda e: self.attributes("-fullscreen", False))

        # Nombre de la fase, arriba del todo y siempre visible. Es la
        # senal redundante del color.
        self._fase = tk.Label(
            self, text="", font=FUENTE_FASE,
            bg=COLOR_REPOSO, fg=COLOR_TEXTO)
        self._fase.pack(pady=(30, 0))

        self._instruccion = tk.Label(
            self, text="Preparado", font=FUENTE_INSTRUCCION,
            bg=COLOR_REPOSO, fg=COLOR_TEXTO)
        self._instruccion.pack(pady=(10, 4))

        # Elemento dominante de la pantalla.
        self._gesto = tk.Label(
            self, text="", font=FUENTE_GESTO,
            bg=COLOR_REPOSO, fg=COLOR_TEXTO)
        self._gesto.pack(pady=4)

        # Posicion del brazo. Solo aparece en el bloque dinamico.
        self._posicion = tk.Label(
            self, text="", font=FUENTE_POSICION,
            bg=COLOR_REPOSO, fg=COLOR_TEXTO)
        self._posicion.pack(pady=2)

        # Hueco para el pictograma del gesto. Las imagenes van en
        # gui_captura/assets/<Gesto>.png; si no existen, se muestra el
        # marco vacio y la sesion funciona igual.
        self._marco_img = tk.Frame(self, width=LADO_IMAGEN, height=LADO_IMAGEN,
                                   bg=COLOR_REPOSO,
                                   highlightbackground=COLOR_TEXTO,
                                   highlightthickness=2)
        self._marco_img.pack(pady=10)
        self._marco_img.pack_propagate(False)
        self._img = tk.Label(self._marco_img, text="[ imagen del gesto ]",
                             bg=COLOR_REPOSO, fg=COLOR_TEXTO,
                             font=("Helvetica", 14))
        self._img.pack(expand=True)
        self._imagenes = {}

        self._cuenta = tk.Label(
            self, text="", font=FUENTE_CUENTA,
            bg=COLOR_REPOSO, fg=COLOR_TEXTO)
        self._cuenta.pack(pady=4)

        # Guia de rampa: durante el primer segundo de la contraccion, una
        # barra que se llena sola marca el ritmo al que subir la fuerza.
        # Sin ella el participante contrae de golpe, y el escalon no se
        # parece a como se usa una protesis.
        self._rampa = tk.Canvas(self, width=900, height=26,
                                bg=COLOR_REPOSO, highlightthickness=0)
        self._rampa.pack(pady=(6, 0))
        self._rampa_marco = self._rampa.create_rectangle(
            0, 0, 900, 26, outline=COLOR_TEXTO, width=2)
        self._rampa_relleno = self._rampa.create_rectangle(
            2, 2, 2, 24, outline="", fill=COLOR_RAMPA)
        self._rampa_txt = tk.Label(
            self, text="", font=FUENTE_PIE,
            bg=COLOR_REPOSO, fg=COLOR_TEXTO)
        self._rampa_txt.pack()

        self._barra = ttk.Progressbar(self, length=900, maximum=1000)
        self._barra.pack(pady=16)

        self._progreso_txt = tk.Label(
            self, text="", font=FUENTE_PIE,
            bg=COLOR_REPOSO, fg=COLOR_TEXTO)
        self._progreso_txt.pack()

    def cargar_imagenes(self, *carpetas):
        """
        Carga <carpeta>/<Gesto>.png de la primera carpeta donde existan.
        Es opcional: sin imagenes, la sesion corre con el marco vacio.
        """
        for carpeta in carpetas:
            if not carpeta or not os.path.isdir(carpeta):
                continue
            for nombre in NOMBRES_GESTOS:
                ruta = os.path.join(carpeta, f"{nombre}.png")
                if nombre not in self._imagenes and os.path.exists(ruta):
                    try:
                        self._imagenes[nombre] = tk.PhotoImage(file=ruta)
                    except tk.TclError:
                        pass
        return len(self._imagenes)

    def _pintar(self, color: str):
        self.configure(bg=color)
        for w in (self._fase, self._instruccion, self._gesto, self._posicion,
                  self._cuenta, self._rampa, self._rampa_txt,
                  self._progreso_txt, self._marco_img, self._img):
            w.configure(bg=color)

    def _dibujar_rampa(self, bloque, transcurrido_ms: float):
        """Barra que se llena durante el primer segundo de la contraccion."""
        if bloque.tipo != TIPO_CONTRACCION or transcurrido_ms > RAMPA_CONTRACCION_MS:
            self._rampa.coords(self._rampa_relleno, 2, 2, 2, 24)
            self._rampa.itemconfigure(self._rampa_marco, state="hidden")
            self._rampa_txt.config(text="")
            return
        self._rampa.itemconfigure(self._rampa_marco, state="normal")
        frac = max(0.0, min(1.0, transcurrido_ms / RAMPA_CONTRACCION_MS))
        self._rampa.coords(self._rampa_relleno, 2, 2, 2 + frac * 896, 24)
        self._rampa_txt.config(text="Suba la fuerza poco a poco, sin golpe")

    def actualizar(self, bloque, restante_s: float, frac: float,
                   idx: int, total: int, transcurrido_ms: float = 0.0,
                   bloque_postura: str = ""):
        self._pintar(color_de(bloque.tipo))
        self._fase.config(text=TEXTO_FASE.get(bloque.tipo, bloque.tipo.upper()))

        if bloque.tipo == TIPO_CALIBRACION:
            self._instruccion.config(
                text="Calibracion. Brazo relajado y quieto. No mueva la mano.")
            self._gesto.config(text="QUIETO")
        elif bloque.tipo == TIPO_PREPARACION:
            self._instruccion.config(text="Ahora viene este gesto")
            self._gesto.config(text=bloque.nombre_gesto.upper())
        elif bloque.tipo == TIPO_REPOSO:
            self._instruccion.config(text="Relaje la mano")
            self._gesto.config(text="REPOSO")
        else:
            self._instruccion.config(text="Ejecute y mantenga")
            self._gesto.config(text=bloque.nombre_gesto.upper())

        # Posicion del brazo, solo en el bloque dinamico.
        if bloque_postura == BLOQUE_DINAMICO and bloque.posicion_brazo:
            self._posicion.config(
                text=f"{TEXTO_POSICION.get(bloque.posicion_brazo, bloque.posicion_brazo)}"
                     f"\n{TEXTO_MOVIMIENTO_LENTO}")
        else:
            self._posicion.config(text="")

        # La imagen acompana desde la preparacion, que es cuando sirve
        # para reconocer el gesto que viene.
        img = self._imagenes.get(bloque.nombre_gesto)
        if img is not None and bloque.tipo in (TIPO_CONTRACCION,
                                               TIPO_PREPARACION):
            self._img.config(image=img, text="")
        else:
            self._img.config(image="", text="[ imagen del gesto ]")

        self._cuenta.config(text=f"{max(0, int(restante_s + 0.999))}")
        self._dibujar_rampa(bloque, transcurrido_ms)
        self._barra["value"] = frac * 1000
        self._progreso_txt.config(
            text=f"Bloque {idx + 1} de {total}   ·   {frac * 100:.0f}%")

    def mostrar_pausa(self, motivo: str):
        """Pantalla de pausa. El participante tiene que saber que parar."""
        self._pintar(COLOR_PAUSA)
        self._fase.config(text="SESION EN PAUSA")
        self._instruccion.config(text=motivo)
        self._gesto.config(text="ESPERE")
        self._posicion.config(text="")
        self._cuenta.config(text="")
        self._rampa_txt.config(text="")
        self._img.config(image="", text="")

    def mostrar_fin(self, texto: str):
        self._pintar(COLOR_FIN)
        self._fase.config(text="")
        self._instruccion.config(text="")
        self._gesto.config(text=texto)
        self._posicion.config(text="")
        self._cuenta.config(text="")
        self._rampa_txt.config(text="")
        self._img.config(image="", text="")


# ============================================================
# MONITOR DE SENALES (Canvas nativo)
# ============================================================
class MonitorLMG(tk.Canvas):
    """
    Traza los 5 canales LMG en tiempo real.

    Sirve para lo unico que importa durante la sesion: ver si un sensor
    se despego. Una linea plana o saturada canta a la vista mucho antes
    de que el CSV lo revele.
    """

    N_PUNTOS = 300      # 6 s a 50 Hz de refresco

    def __init__(self, master, ancho=560, alto=260, **kw):
        super().__init__(master, width=ancho, height=alto, bg="#101010",
                         highlightthickness=0, **kw)
        self.ancho, self.alto = ancho, alto
        self._series = [[] for _ in range(5)]
        self._lineas = [self.create_line(0, 0, 0, 0, fill=c, width=1)
                        for c in COLORES_LMG]
        for i, c in enumerate(COLORES_LMG):
            self.create_text(10 + i * 60, 12, text=f"v{i+1}", fill=c,
                             anchor="w", font=("Consolas", 10))

    def anadir(self, valores):
        for i in range(5):
            s = self._series[i]
            s.append(valores[i])
            if len(s) > self.N_PUNTOS:
                del s[0]
        self._redibujar()

    def _redibujar(self):
        planos = [v for s in self._series for v in s]
        if not planos:
            return
        lo, hi = min(planos), max(planos)
        if hi - lo < 1e-6:
            hi = lo + 1.0
        margen = 24
        util = self.alto - 2 * margen

        for i, s in enumerate(self._series):
            if len(s) < 2:
                continue
            pts = []
            for j, v in enumerate(s):
                x = j * self.ancho / max(1, self.N_PUNTOS - 1)
                y = margen + util * (1 - (v - lo) / (hi - lo))
                pts.extend((x, y))
            self.coords(self._lineas[i], *pts)


# ============================================================
# VENTANA DE PRUEBA DE CONEXION
# ============================================================
class VentanaPrueba(tk.Toplevel):
    """
    Verificacion de la colocacion del brazalete ANTES de empezar.

    Muestra los 5 canales en crudo, en mV, y el recorrido de cada uno
    desde que se abrio la ventana. Se pide al participante que haga tres
    contracciones fuertes: un canal que no se mueva delata un modulo
    despegado o un LED muerto, y eso se arregla en un minuto ahora o
    cuesta la sesion entera despues.

    NO graba nada. Es solo una comprobacion.
    """

    UMBRAL_RECORRIDO_MV = 20.0     # recorrido minimo para dar por buen canal

    def __init__(self, master, al_cerrar=None):
        super().__init__(master)
        self.title("Prueba de conexion")
        self.geometry("720x560")
        self._al_cerrar = al_cerrar
        self._min = [None] * 5
        self._max = [None] * 5

        tk.Label(self, text="Pida TRES contracciones fuertes",
                 font=("Helvetica", 20, "bold")).pack(pady=(12, 2))
        tk.Label(self, font=("Helvetica", 11), justify="left",
                 text="Los cinco canales deben moverse. Un canal plano "
                      "significa modulo despegado, LED apagado o cable "
                      "suelto.").pack(pady=(0, 8))

        f = ttk.Frame(self)
        f.pack(pady=4)
        self._val, self._rec, self._ok = [], [], []
        for i in range(5):
            tk.Label(f, text=f"v{i+1}", font=("Consolas", 16, "bold"),
                     fg=COLORES_LMG[i]).grid(row=i, column=0, padx=6, pady=3)
            lv = tk.Label(f, text="-", font=("Consolas", 16), width=12,
                          anchor="e")
            lv.grid(row=i, column=1, padx=4)
            lr = tk.Label(f, text="-", font=("Consolas", 14), width=16,
                          anchor="e")
            lr.grid(row=i, column=2, padx=4)
            lo = tk.Label(f, text="sin datos", font=("Consolas", 13), width=12)
            lo.grid(row=i, column=3, padx=6)
            self._val.append(lv)
            self._rec.append(lr)
            self._ok.append(lo)
        tk.Label(f, text="mV", font=("Consolas", 10)).grid(row=5, column=1)
        tk.Label(f, text="recorrido", font=("Consolas", 10)).grid(row=5, column=2)

        self.monitor = MonitorLMG(self, ancho=660, alto=240)
        self.monitor.pack(pady=8)

        self.lbl_tasa = tk.Label(self, text="tasa: -", font=("Consolas", 12))
        self.lbl_tasa.pack()
        ttk.Button(self, text="Cerrar y volver",
                   command=self.cerrar).pack(pady=8)
        self.protocol("WM_DELETE_WINDOW", self.cerrar)

    def actualizar(self, stats):
        for i, v in enumerate(stats.ultimo_lmg[:5]):
            self._min[i] = v if self._min[i] is None else min(self._min[i], v)
            self._max[i] = v if self._max[i] is None else max(self._max[i], v)
            recorrido = self._max[i] - self._min[i]
            self._val[i].config(text=f"{v:9.2f}")
            self._rec[i].config(text=f"{recorrido:9.2f}")
            bueno = recorrido >= self.UMBRAL_RECORRIDO_MV
            self._ok[i].config(text="responde" if bueno else "plano",
                               fg="#1f6f3a" if bueno else "#a00000")
        self.lbl_tasa.config(
            text=f"tasa: {stats.tasa_hz:.0f} muestras/s   "
                 f"huecos: {stats.huecos}   total: {stats.total}")
        self.monitor.anadir(stats.ultimo_lmg)

    def reiniciar_recorrido(self):
        self._min = [None] * 5
        self._max = [None] * 5

    def cerrar(self):
        if self._al_cerrar:
            self._al_cerrar()
        self.destroy()


# ============================================================
# VENTANA DEL OPERADOR
# ============================================================
class VentanaOperador(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Captura - Operador")
        self.geometry("620x760")

        self._construir_datos()
        self._construir_controles()
        self._construir_estado()

        self.monitor = MonitorLMG(self)
        self.monitor.pack(pady=8)

        self._log = tk.Text(self, height=8, width=72, bg="#f4f4f4",
                            font=("Consolas", 9))
        self._log.pack(pady=6)

    # ---------- construccion ----------
    def _construir_datos(self):
        f = ttk.LabelFrame(self, text="Sesion")
        f.pack(fill="x", padx=8, pady=6)
        self.var_subject = tk.StringVar()
        self.var_id_participante = tk.StringVar(value="S01")
        self.var_puerto = tk.StringVar(value=PUERTO_DEFECTO)
        self.var_baudios = tk.StringVar(value=str(BAUDIOS_DEFECTO))
        self.var_postura = tk.StringVar(value=BLOQUE_ESTATICO)
        self.var_salida = tk.StringVar(value=os.path.abspath(DIR_SALIDA_DEFECTO))

        ttk.Label(f, text="subject_id").grid(row=0, column=0, sticky="w", padx=4)
        ttk.Entry(f, textvariable=self.var_subject, width=8).grid(row=0, column=1)
        ttk.Label(f, text="id anonimo").grid(row=0, column=2, sticky="w", padx=4)
        ttk.Entry(f, textvariable=self.var_id_participante,
                  width=8).grid(row=0, column=3)
        self.var_simulado = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text="simulado (sin hardware)",
                        variable=self.var_simulado).grid(row=0, column=4, padx=6)

        ttk.Label(f, text="puerto").grid(row=1, column=0, sticky="w", padx=4)
        ttk.Entry(f, textvariable=self.var_puerto, width=8).grid(row=1, column=1)
        ttk.Label(f, text="baudios").grid(row=1, column=2, sticky="w", padx=4)
        ttk.Entry(f, textvariable=self.var_baudios, width=8).grid(row=1, column=3)
        ttk.Label(f, text="bloque").grid(row=1, column=4, sticky="w", padx=4)
        ttk.Combobox(f, textvariable=self.var_postura, values=BLOQUES_POSTURA,
                     width=10, state="readonly").grid(row=1, column=5, padx=4)

        ttk.Label(f, text="carpeta").grid(row=2, column=0, sticky="w", padx=4)
        ttk.Entry(f, textvariable=self.var_salida,
                  width=46).grid(row=2, column=1, columnspan=4, sticky="w")
        ttk.Button(f, text="Elegir...", width=9,
                   command=self._elegir_carpeta).grid(row=2, column=5, padx=4)

        g = ttk.LabelFrame(self, text="Participante")
        g.pack(fill="x", padx=8, pady=6)
        self.vars_meta = {}
        campos = [("edad", 6), ("sexo", 6), ("mano_dominante", 10),
                  ("circunferencia_antebrazo_cm", 8),
                  ("posicion_brazalete_cm", 8)]
        for i, (nombre, ancho) in enumerate(campos):
            ttk.Label(g, text=nombre).grid(row=i // 2, column=(i % 2) * 2,
                                           sticky="w", padx=4, pady=2)
            v = tk.StringVar()
            self.vars_meta[nombre] = v
            ttk.Entry(g, textvariable=v, width=ancho).grid(
                row=i // 2, column=(i % 2) * 2 + 1, sticky="w")
        ttk.Label(g, text="observaciones").grid(row=3, column=0, sticky="nw",
                                                padx=4)
        self.txt_obs = tk.Text(g, height=3, width=52, font=("Consolas", 9))
        self.txt_obs.grid(row=3, column=1, columnspan=3, pady=4)

    def _elegir_carpeta(self):
        ruta = filedialog.askdirectory(
            title="Carpeta de salida de la sesion",
            initialdir=self.var_salida.get() or ".")
        if ruta:
            self.var_salida.set(ruta)

    def _construir_controles(self):
        f = ttk.Frame(self)
        f.pack(fill="x", padx=8, pady=4)
        self.btn_probar   = ttk.Button(f, text="Probar conexion")
        self.btn_iniciar  = ttk.Button(f, text="Iniciar")
        self.btn_pausa    = ttk.Button(f, text="Pausar", state="disabled")
        self.btn_descartar = ttk.Button(f, text="Descartar repeticion",
                                        state="disabled")
        self.btn_abortar  = ttk.Button(f, text="Abortar", state="disabled")
        for b in (self.btn_probar, self.btn_iniciar, self.btn_pausa,
                  self.btn_descartar, self.btn_abortar):
            b.pack(side="left", padx=4)

    def _construir_estado(self):
        f = ttk.LabelFrame(self, text="Adquisicion")
        f.pack(fill="x", padx=8, pady=6)
        self.lbl = {}
        etiquetas = [("tasa", "muestras/s"), ("total", "total"),
                     ("huecos", "huecos"), ("perdidas", "perdidas est."),
                     ("backlog", "cola"), ("malformadas", "malformadas")]
        for i, (clave, texto) in enumerate(etiquetas):
            ttk.Label(f, text=texto).grid(row=i // 3, column=(i % 3) * 2,
                                          sticky="w", padx=4)
            l = tk.Label(f, text="-", font=("Consolas", 11, "bold"))
            l.grid(row=i // 3, column=(i % 3) * 2 + 1, sticky="w", padx=4)
            self.lbl[clave] = l

        self.lbl_bloque = tk.Label(self, text="-", font=("Helvetica", 11))
        self.lbl_bloque.pack()

    # ---------- actualizacion ----------
    def actualizar_stats(self, s):
        self.lbl["total"].config(text=str(s.total))
        self.lbl["backlog"].config(text=str(s.backlog))
        self.lbl["malformadas"].config(text=str(s.lineas_malformadas))
        self.lbl["perdidas"].config(text=str(s.muestras_perdidas_est))

        # La tasa se colorea porque es el sintoma de que el adaptador
        # USB-serie no sostiene 921600. Verde 95-105, ambar fuera de ahi.
        self.lbl["tasa"].config(
            text=f"{s.tasa_hz:.0f}",
            fg="#1f6f3a" if 95 <= s.tasa_hz <= 105 else "#b35c00")

        # Cualquier hueco es una muestra perdida: en rojo desde el primero.
        self.lbl["huecos"].config(
            text=str(s.huecos), fg="#a00000" if s.huecos else "#1f6f3a")

        self.monitor.anadir(s.ultimo_lmg)

    def log(self, texto: str):
        self._log.insert("end", texto + "\n")
        self._log.see("end")

    def metadatos(self) -> dict:
        d = {k: v.get() for k, v in self.vars_meta.items()}
        d["id_participante"] = self.var_id_participante.get().strip()
        d["bloque_postura"] = self.var_postura.get()
        d["observaciones"] = self.txt_obs.get("1.0", "end").strip()
        return d

    def baudios(self) -> int:
        try:
            return int(self.var_baudios.get())
        except ValueError:
            return BAUDIOS_DEFECTO
