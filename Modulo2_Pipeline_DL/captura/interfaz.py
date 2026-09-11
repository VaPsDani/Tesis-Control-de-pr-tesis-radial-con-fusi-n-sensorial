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

import tkinter as tk
from tkinter import ttk

from protocolo import (TIPO_CALIBRACION, TIPO_CONTRACCION, TIPO_REPOSO,
                       NOMBRES_GESTOS)

COLOR_REPOSO      = "#1f3a5f"   # azul oscuro, calmado
COLOR_CONTRACCION = "#1f6f3a"   # verde, accion
COLOR_CALIBRACION = "#4a4a4a"   # gris neutro
COLOR_TEXTO       = "#ffffff"
COLOR_FIN         = "#000000"

COLORES_LMG = ["#e6194b", "#3cb44b", "#ffe119", "#4363d8", "#f58231"]


def color_de(tipo: str) -> str:
    if tipo == TIPO_CONTRACCION:
        return COLOR_CONTRACCION
    if tipo == TIPO_CALIBRACION:
        return COLOR_CALIBRACION
    return COLOR_REPOSO


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

        self._instruccion = tk.Label(
            self, text="Preparado", font=("Helvetica", 40),
            bg=COLOR_REPOSO, fg=COLOR_TEXTO)
        self._instruccion.pack(pady=(60, 10))

        self._gesto = tk.Label(
            self, text="", font=("Helvetica", 130, "bold"),
            bg=COLOR_REPOSO, fg=COLOR_TEXTO)
        self._gesto.pack(pady=10)

        # Hueco para el pictograma del gesto. Las imagenes las pone el
        # operador en captura/imagenes/<Gesto>.png; si no existen, se
        # muestra el marco vacio y la sesion funciona igual.
        self._marco_img = tk.Frame(self, width=320, height=320,
                                   bg=COLOR_REPOSO,
                                   highlightbackground=COLOR_TEXTO,
                                   highlightthickness=2)
        self._marco_img.pack(pady=20)
        self._marco_img.pack_propagate(False)
        self._img = tk.Label(self._marco_img, text="[ imagen del gesto ]",
                             bg=COLOR_REPOSO, fg=COLOR_TEXTO,
                             font=("Helvetica", 14))
        self._img.pack(expand=True)
        self._imagenes = {}

        self._cuenta = tk.Label(
            self, text="", font=("Helvetica", 96, "bold"),
            bg=COLOR_REPOSO, fg=COLOR_TEXTO)
        self._cuenta.pack(pady=10)

        self._barra = ttk.Progressbar(self, length=900, maximum=1000)
        self._barra.pack(pady=30)

        self._progreso_txt = tk.Label(
            self, text="", font=("Helvetica", 18),
            bg=COLOR_REPOSO, fg=COLOR_TEXTO)
        self._progreso_txt.pack()

    def cargar_imagenes(self, carpeta: str):
        """Carga <carpeta>/<Gesto>.png si existen. Opcional."""
        import os
        for nombre in NOMBRES_GESTOS:
            ruta = os.path.join(carpeta, f"{nombre}.png")
            if os.path.exists(ruta):
                try:
                    self._imagenes[nombre] = tk.PhotoImage(file=ruta)
                except tk.TclError:
                    pass

    def _pintar(self, color: str):
        self.configure(bg=color)
        for w in (self._instruccion, self._gesto, self._cuenta,
                  self._progreso_txt, self._marco_img, self._img):
            w.configure(bg=color)

    def actualizar(self, bloque, restante_s: float, frac: float,
                   idx: int, total: int):
        self._pintar(color_de(bloque.tipo))

        if bloque.tipo == TIPO_CALIBRACION:
            self._instruccion.config(text="CALIBRACION")
            self._gesto.config(text="Quieto")
        elif bloque.tipo == TIPO_REPOSO:
            self._instruccion.config(text="Relaje la mano")
            self._gesto.config(text="REPOSO")
        else:
            self._instruccion.config(text="Ejecute y mantenga")
            self._gesto.config(text=bloque.nombre_gesto.upper())

        img = self._imagenes.get(bloque.nombre_gesto)
        if img is not None and bloque.tipo == TIPO_CONTRACCION:
            self._img.config(image=img, text="")
        else:
            self._img.config(image="", text="[ imagen del gesto ]")

        self._cuenta.config(text=f"{max(0, int(restante_s + 0.999))}")
        self._barra["value"] = frac * 1000
        self._progreso_txt.config(
            text=f"Bloque {idx + 1} de {total}   ·   {frac * 100:.0f}%")

    def mostrar_fin(self, texto: str):
        self._pintar(COLOR_FIN)
        self._instruccion.config(text="")
        self._gesto.config(text=texto)
        self._cuenta.config(text="")
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
        self.var_puerto = tk.StringVar(value="COM3")
        ttk.Label(f, text="subject_id").grid(row=0, column=0, sticky="w", padx=4)
        ttk.Entry(f, textvariable=self.var_subject, width=8).grid(row=0, column=1)
        ttk.Label(f, text="puerto").grid(row=0, column=2, sticky="w", padx=4)
        ttk.Entry(f, textvariable=self.var_puerto, width=10).grid(row=0, column=3)
        self.var_simulado = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text="simulado (sin hardware)",
                        variable=self.var_simulado).grid(row=0, column=4, padx=6)

        g = ttk.LabelFrame(self, text="Participante")
        g.pack(fill="x", padx=8, pady=6)
        self.vars_meta = {}
        campos = [("edad", 6), ("sexo", 6), ("brazo_dominante", 10),
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

    def _construir_controles(self):
        f = ttk.Frame(self)
        f.pack(fill="x", padx=8, pady=4)
        self.btn_iniciar = ttk.Button(f, text="Iniciar")
        self.btn_pausa   = ttk.Button(f, text="Pausar", state="disabled")
        self.btn_abortar = ttk.Button(f, text="Abortar", state="disabled")
        for b in (self.btn_iniciar, self.btn_pausa, self.btn_abortar):
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
        d["observaciones"] = self.txt_obs.get("1.0", "end").strip()
        return d
