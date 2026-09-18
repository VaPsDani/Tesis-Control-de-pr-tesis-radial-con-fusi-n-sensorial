"""
config_captura.py - Constantes de la sesion de captura, en un solo sitio
========================================================================
Protesis transradial - Captura con voluntarios

TODO lo que un operador o un tesista podria querer cambiar entre
campanas vive aqui: duraciones, margenes, numero de repeticiones,
colores, tamanos de letra, puerto por defecto y rutas. Los demas modulos
importan de aqui y no definen numeros propios.

QUE NO SE TOCA DESDE AQUI:
  El esquema de columnas del CSV, que lo lee el pipeline del Modulo 2, y
  la forma del vector del modelo, que son 8 canales. Ver adquisicion.py.
"""

import os

AQUI = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# ENLACE SERIAL
# ============================================================
# 921600 y no 115200: 12 campos por linea son ~122 bytes, que a 100 Hz
# son 12200 B/s, y 115200 8N1 solo da 11520 B/s. Es el valor del
# firmware (BAUDIOS en Modulo1_Adquisicion_Datos/config.h).
BAUDIOS_DEFECTO = 921600
PUERTO_DEFECTO = "COM3"
PERIODO_MS = 10                  # 100 Hz, INTERVALO_MS del firmware
HUECO_MAX_MS = 3 * PERIODO_MS    # salto que se cuenta como hueco

# Si no llega ninguna muestra en este tiempo con la sesion corriendo, se
# considera que el puerto se cayo y la sesion se pausa sola.
TIMEOUT_SIN_DATOS_S = 2.0

# Plazo mas largo mientras no llegue la primera muestra: al abrirse el
# puerto el ESP32 se reinicia y tarda en arrancar.
GRACIA_ARRANQUE_S = 8.0

# ============================================================
# TIEMPOS DE LOS BLOQUES (ms)
# ============================================================
# Una repeticion son tres fases seguidas: PREPARACION, CONTRACCION y
# REPOSO. La calibracion va una sola vez, al principio.
DUR_CALIBRACION_MS = 15000
DUR_PREPARACION_MS = 3000
DUR_CONTRACCION_MS = 10000
DUR_REPOSO_MS      = 8000

# Margenes (entrada, salida) en ms. Se MARCAN en la columna en_margen,
# no se borran, para poder barrer el valor sobre el piloto sin volver a
# grabar.
#
# EL MARGEN DE ENTRADA DE LA CONTRACCION NO DEBE REDUCIRSE. El orden de
# los gestos esta contrabalanceado, asi que el participante no puede
# anticipar cual viene: por la ley de Hick, elegir entre 4 alternativas
# anade 150-200 ms al tiempo de reaccion. Con 10 s de contraccion y este
# margen quedan 8.5 s utiles por repeticion.
MARGEN_CONTRACCION = (1000, 500)
MARGEN_REPOSO      = (2000, 500)
MARGEN_CALIBRACION = (1000, 500)

# La preparacion entera es margen. Es una fase de lectura de la pantalla,
# no una clase: la mano esta quieta pero el participante ya esta
# preparando el gesto, asi que no es reposo limpio ni contraccion.
# Marcandola completa nunca entra al entrenamiento por descuido, y sigue
# quedando en el CSV por si luego interesa estudiar la anticipacion.
MARGEN_PREPARACION = (DUR_PREPARACION_MS, 0)

# Rampa de fuerza al inicio de la contraccion. La guia visual pide subir
# la fuerza de forma gradual durante este tiempo, que cae entero dentro
# del margen de entrada, asi que la rampa no contamina el dato util.
RAMPA_CONTRACCION_MS = 1000

N_REPETICIONES = 6

# ============================================================
# BLOQUE DE POSTURA
# ============================================================
BLOQUE_ESTATICO = "estatico"
BLOQUE_DINAMICO = "dinamico"
BLOQUES_POSTURA = [BLOQUE_ESTATICO, BLOQUE_DINAMICO]

# Posiciones del brazo del bloque dinamico. Rotan entre repeticiones, de
# modo que cada posicion recibe el mismo numero de contracciones y de
# gestos, y la posicion no queda confundida con la fatiga.
POSICION_NINGUNA = ""
POSICIONES_BRAZO = [
    "abajo_al_costado",
    "al_frente_codo_90",
    "arriba_sobre_el_hombro",
]
TEXTO_POSICION = {
    "abajo_al_costado": "BRAZO ABAJO, AL COSTADO",
    "al_frente_codo_90": "BRAZO AL FRENTE, CODO A 90 GRADOS",
    "arriba_sobre_el_hombro": "BRAZO ARRIBA, SOBRE EL HOMBRO",
}
TEXTO_MOVIMIENTO_LENTO = "Mueva el brazo lento y continuo"

# ============================================================
# SALIDA
# ============================================================
DIR_SALIDA_DEFECTO = os.path.join(AQUI, "..", "sesiones")
DIR_IMAGENES = os.path.join(AQUI, "..", "..",
                            "Modulo1_Adquisicion_Datos", "gui_captura",
                            "assets")
# Carpeta de imagenes anterior, que se sigue aceptando.
DIR_IMAGENES_ALT = os.path.join(AQUI, "imagenes")

FLUSH_CADA_N = 100               # filas entre flush del CSV

# ============================================================
# INTERFAZ
# ============================================================
REFRESCO_MS = 50                 # 20 Hz de refresco

# Colores por fase. NUNCA son la unica senal: cada fase muestra ademas
# su nombre en texto, porque un participante puede tener daltonismo.
COLOR_CALIBRACION = "#4a4a4a"    # gris neutro
COLOR_PREPARACION = "#7a4f00"    # ambar oscuro, atencion
COLOR_CONTRACCION = "#1f6f3a"    # verde, accion
COLOR_REPOSO      = "#1f3a5f"    # azul oscuro, calma
COLOR_PAUSA       = "#6b0f0f"    # rojo oscuro, sesion detenida
COLOR_FIN         = "#000000"
COLOR_TEXTO       = "#ffffff"
COLOR_RAMPA       = "#ffd24a"

COLORES_LMG = ["#e6194b", "#3cb44b", "#ffe119", "#4363d8", "#f58231"]

# Tamanos pensados para leerse a un metro de la pantalla.
FUENTE_FASE        = ("Helvetica", 44, "bold")
FUENTE_INSTRUCCION = ("Helvetica", 40)
FUENTE_GESTO       = ("Helvetica", 130, "bold")
FUENTE_CUENTA      = ("Helvetica", 96, "bold")
FUENTE_POSICION    = ("Helvetica", 34, "bold")
FUENTE_PIE         = ("Helvetica", 18)

LADO_IMAGEN = 320                # lado del marco del pictograma

# ============================================================
# SONIDO
# ============================================================
# Aviso breve en cada cambio de fase. En Windows se usa winsound, que es
# de la biblioteca estandar. En el resto, la campana de Tk. Si nada de
# eso existe, la sesion sigue sin sonido y solo se anota en el log.
SONIDO_HABILITADO = True
SONIDO_MS = 120
SONIDO_HZ = {
    "calibracion": 440,
    "preparacion": 660,
    "contraccion": 880,
    "reposo": 330,
    "aviso": 220,
}
