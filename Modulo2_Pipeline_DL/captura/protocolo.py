"""
protocolo.py - Secuencia de bloques de una sesion de captura
=============================================================
Protesis transradial - Captura con voluntarios

ESTRUCTURA DE LA SESION:
  1. Un bloque de CALIBRACION de 15 s de reposo contiguo, fuera de la
     rotacion. Es reposo BASAL, antes de cualquier contraccion.
  2. 6 repeticiones. Cada repeticion presenta los 4 gestos activos una
     vez, en orden contrabalanceado.
  3. Cada gesto = PREPARACION (3 s) + CONTRACCION (10 s) + REPOSO (8 s).

  Total: 15 + 4*6*(3+10+8) = 519 s = 8.7 min de grabacion.

  RATIO DE CLASES CON ESTOS TIEMPOS:
    Con contraccion de 10 s quedan 8.5 s utiles por repeticion, o sea
    51 s por clase activa, frente a 132 s de Rest: un ratio de 2.6:1. Con
    los 15 s anteriores el ratio era 1.63:1. El submuestreo de Rest del
    pipeline lo absorbe, pero conviene saber que al acortar la
    contraccion el desbalance sube. Si molesta, la perilla es acortar el
    bloque de REPOSO, no alargar la contraccion, porque el reposo entre
    agarres es lo que sobra.

POR QUE REST NO ESTA EN LA ROTACION:
  Rest se graba de sobra en los 24 bloques de reposo entre contracciones.
  Anadir bloques de Rest propios duplicaria el concepto y dejaria la
  clase en 6:1 frente a cada clase activa. Asi queda en 2.6:1, que el
  submuestreo del pipeline maneja como un ajuste fino.

POR QUE EL REPOSO HEREDA EL repetition_id:
  En NinaPro DB5, todo el reposo compartia repetition = 0. Al agrupar por
  repeticion, el reposo entero caia en un unico pliegue: uno de los cinco
  quedo con 50.7% de Rest en test frente a ~8% en los demas, lo que
  inflo la desviacion estandar de la linea base.

  Aqui el reposo NUNCA recibe un repetition_id propio: hereda el de la
  contraccion que acaba de terminar, igual que la preparacion hereda el
  de la contraccion que anuncia. Con eso, cualquier esquema de
  agrupamiento lo reparte proporcionalmente.

MARGENES POR TIPO DE BLOQUE:
  Se MARCAN, no se borran (columna en_margen), para poder barrer el valor
  sobre los datos del piloto sin volver a grabar.

  Contraccion  1000 / 500 ms
    Entrada: tiempo de reaccion visual (~250 ms), que sube a 300-400 ms
    al elegir entre alternativas, mas 300-600 ms de ejecucion hasta
    postura estable.

    EL MARGEN DE ENTRADA DE 1000 ms NO DEBE REDUCIRSE, aunque el piloto
    sugiera que sobra tiempo. El orden de los gestos esta
    contrabalanceado, asi que el participante NO puede anticipar cual
    viene: por la ley de Hick, elegir entre 4 alternativas anade 150-200
    ms de tiempo de reaccion frente a una respuesta simple. Con orden
    fijo el participante aprenderia la secuencia y pre-planificaria, y
    entonces 1000 ms si serian holgura. Con orden aleatorizado son
    necesidad. El margen de reposo si es reducible; este no.

  Reposo       2000 / 500 ms
    Volver a reposo es mas lento que salir de el: extension de los dedos
    a neutro (300-500 ms), actividad post-contraccion residual y, sobre
    todo, hiperemia reactiva. El LMG es una senal optica que refleja
    deformacion muscular y volumen sanguineo, con constantes de tiempo de
    segundos, no de milisegundos.

    ADVERTENCIA: 2000 ms probablemente NO bastan. La hiperemia
    post-ejercicio puede persistir 10-30 s, mas que el bloque entero. La
    consecuencia es que esta clase Rest es "reposo post-contraccion" y no
    "reposo basal". No es un defecto: es lo que la protesis ve en uso
    real, reposo entre agarres. El reposo basal lo aporta el bloque de
    calibracion. Verificar con analizar_hiperemia.py sobre el piloto.

  Calibracion  1000 / 500 ms
    No hay contraccion previa; el margen inicial solo cubre que el
    participante se acomode tras la instruccion.
"""

from dataclasses import dataclass, field
from typing import List
import numpy as np

# ============================================================
# CLASES
# ============================================================
NOMBRES_GESTOS = ["Rest", "Pinch", "Tripod", "Power", "Finger_Ext"]
LABEL_REST = 0
GESTOS_ACTIVOS = [1, 2, 3, 4]          # Pinch, Tripod, Power, Finger_Ext

# ============================================================
# TIEMPOS Y POSTURA
# ============================================================
# Los numeros viven en config_captura.py, que es el unico archivo que se
# edita para cambiar el protocolo. Aqui solo se reexportan para no
# romper a quien ya importaba de protocolo.
from config_captura import (BLOQUE_DINAMICO, BLOQUE_ESTATICO,  # noqa: E402
                            RAMPA_CONTRACCION_MS,
                            BLOQUES_POSTURA, DUR_CALIBRACION_MS,
                            DUR_CONTRACCION_MS, DUR_PREPARACION_MS,
                            DUR_REPOSO_MS, MARGEN_CALIBRACION,
                            MARGEN_CONTRACCION, MARGEN_PREPARACION,
                            MARGEN_REPOSO, N_REPETICIONES, POSICION_NINGUNA,
                            POSICIONES_BRAZO)

TIPO_CALIBRACION = "calibracion"
TIPO_PREPARACION = "preparacion"
TIPO_REPOSO      = "reposo"
TIPO_CONTRACCION = "contraccion"


@dataclass
class Bloque:
    """Un bloque del protocolo, con su ventana temporal absoluta."""
    tipo: str
    label: int
    repetition_id: int
    t_inicio_ms: int
    duracion_ms: int
    margen_inicial_ms: int
    margen_final_ms: int
    es_calibracion: int = 0
    # Posicion del brazo pedida en ese bloque. Vacia en el bloque
    # estatico, donde el brazo no cambia de sitio.
    posicion_brazo: str = POSICION_NINGUNA

    @property
    def t_fin_ms(self) -> int:
        return self.t_inicio_ms + self.duracion_ms

    @property
    def nombre_gesto(self) -> str:
        return NOMBRES_GESTOS[self.label]

    def en_margen(self, t_ms: int) -> int:
        """1 si t_ms cae en el margen de entrada o de salida del bloque."""
        rel = t_ms - self.t_inicio_ms
        if rel < self.margen_inicial_ms:
            return 1
        if rel >= self.duracion_ms - self.margen_final_ms:
            return 1
        return 0

    @property
    def segundos_utiles(self) -> float:
        # Nunca negativo: si alguien deja margenes mas largos que el
        # bloque, el resumen debe decir cero, no una cifra imposible.
        return max(0.0, (self.duracion_ms - self.margen_inicial_ms
                         - self.margen_final_ms) / 1000.0)


def validar_tiempos():
    """
    Comprueba que los margenes caben en su bloque.

    Se llama al construir la sesion. Es barato y evita que un cambio en
    config_captura.py se descubra a mitad de una sesion con voluntario,
    que es el peor momento posible.
    """
    combinaciones = [
        ("calibracion", DUR_CALIBRACION_MS, MARGEN_CALIBRACION),
        ("preparacion", DUR_PREPARACION_MS, MARGEN_PREPARACION),
        ("contraccion", DUR_CONTRACCION_MS, MARGEN_CONTRACCION),
        ("reposo", DUR_REPOSO_MS, MARGEN_REPOSO),
    ]
    for nombre, duracion, (entrada, salida) in combinaciones:
        if duracion <= 0:
            raise ValueError(f"La duracion del bloque {nombre} debe ser "
                             f"positiva (config_captura.py).")
        if entrada + salida > duracion:
            raise ValueError(
                f"Los margenes del bloque {nombre} suman {entrada + salida} ms "
                f"y el bloque dura {duracion} ms: no quedarian datos utiles. "
                f"Revise config_captura.py.")
    if RAMPA_CONTRACCION_MS > MARGEN_CONTRACCION[0]:
        raise ValueError(
            f"La rampa de {RAMPA_CONTRACCION_MS} ms excede el margen de "
            f"entrada de la contraccion ({MARGEN_CONTRACCION[0]} ms), asi que "
            f"la subida de fuerza entraria como dato util.")


# ============================================================
# CONTRABALANCEO DEL ORDEN DE GESTOS
# ============================================================
def _contar_transiciones(secuencia: List[int]) -> dict:
    """Cuenta cada par ordenado (predecesor -> sucesor) de la secuencia."""
    conteo = {}
    for a, b in zip(secuencia[:-1], secuencia[1:]):
        conteo[(a, b)] = conteo.get((a, b), 0) + 1
    return conteo


def _desbalance(secuencia: List[int], gestos: List[int]) -> int:
    """
    Penalizacion de una secuencia: rango entre el par ordenado mas y
    menos frecuente. Cuanto menor, mas uniforme es el arrastre entre
    gestos consecutivos.
    """
    conteo = _contar_transiciones(secuencia)
    pares = [(a, b) for a in gestos for b in gestos if a != b]
    valores = [conteo.get(p, 0) for p in pares]
    return max(valores) - min(valores)


def generar_secuencia_gestos(subject_id: int,
                             n_repeticiones: int = N_REPETICIONES,
                             gestos: List[int] = None,
                             n_candidatos: int = 4000) -> List[int]:
    """
    Genera el orden de presentacion de los gestos, contrabalanceado.

    POR QUE NO AZAR PURO:
      Con orden fijo, el arrastre fisiologico queda asociado siempre al
      mismo par: el gesto que sigue a Power hereda siempre la hiperemia
      de Power, y se convierte en un confusor estructural. Aleatorizar lo
      convierte en ruido, pero con 4 gestos hay 12 pares ordenados y
      n_repeticiones*4 - 1 = 23 transiciones, o sea ~1.9 por par: un
      sorteo concreto deja algunos pares a 0 y otros a 4.

      Aqui se sortean candidatos y se elige el de menor desbalance, con
      lo que el equilibrio queda GARANTIZADO y no solo esperado. La
      semilla se deriva del subject_id, asi que la sesion es reproducible
      y cada sujeto recibe un orden distinto.

      Aleatorizar corrige ademas un segundo confusor: con orden fijo, el
      ultimo gesto de cada repeticion carga siempre con la mayor fatiga
      acumulada.

    Returns:
        Lista de n_repeticiones * len(gestos) etiquetas de gesto. Cada
        bloque consecutivo de len(gestos) contiene los 4 gestos una vez.
    """
    if gestos is None:
        gestos = list(GESTOS_ACTIVOS)

    rng = np.random.RandomState(subject_id)

    mejor, mejor_score = None, None
    for _ in range(n_candidatos):
        secuencia = []
        for _ in range(n_repeticiones):
            perm = list(gestos)
            rng.shuffle(perm)
            secuencia.extend(perm)
        score = _desbalance(secuencia, gestos)
        if mejor_score is None or score < mejor_score:
            mejor, mejor_score = list(secuencia), score
            if score <= 1:      # optimo alcanzable con 23 transiciones
                break

    return mejor


# ============================================================
# CONSTRUCCION DE LA SESION
# ============================================================
def posicion_de(ocurrencia_del_gesto: int, bloque_postura: str) -> str:
    """
    Posicion del brazo de una contraccion del bloque dinamico.

    En el bloque estatico no hay posicion.

    POR QUE SE ROTA POR GESTO Y NO POR ORDEN DE SESION:
      Rotando por el orden de la sesion, las posiciones quedan
      equilibradas EN TOTAL pero no por gesto: con la secuencia del
      sujeto 1, Pinch no caia nunca en "abajo al costado" y Finger_Ext
      nunca al frente. La posicion quedaria confundida con el gesto, que
      es justo lo que el bloque dinamico quiere separar.

      Contando las apariciones de CADA gesto, las 6 repeticiones de cada
      uno se reparten 2, 2 y 2 entre las tres posiciones, y cada celda
      de la tabla gesto por posicion queda con el mismo n.

    Args:
        ocurrencia_del_gesto: cuantas veces ha aparecido ya ese gesto,
            empezando en 0.
    """
    if bloque_postura != BLOQUE_DINAMICO:
        return POSICION_NINGUNA
    return POSICIONES_BRAZO[ocurrencia_del_gesto % len(POSICIONES_BRAZO)]


def construir_sesion(subject_id: int,
                     n_repeticiones: int = N_REPETICIONES,
                     bloque_postura: str = BLOQUE_ESTATICO) -> List[Bloque]:
    """
    Construye la lista completa de bloques con su linea temporal.

    Cada gesto son tres bloques seguidos: PREPARACION, CONTRACCION y
    REPOSO. El repetition_id de la preparacion y del reposo es el del
    bloque de contraccion al que acompanan, nunca uno propio: asi
    cualquier esquema de agrupamiento reparte el reposo de forma
    proporcional en vez de dejarlo entero en un pliegue.
    """
    validar_tiempos()
    if bloque_postura not in BLOQUES_POSTURA:
        raise ValueError(f"bloque_postura debe ser uno de {BLOQUES_POSTURA}")

    secuencia = generar_secuencia_gestos(subject_id, n_repeticiones)
    bloques: List[Bloque] = []
    t = 0

    # Bloque de calibracion: reposo basal contiguo, fuera de la rotacion.
    bloques.append(Bloque(
        tipo=TIPO_CALIBRACION, label=LABEL_REST, repetition_id=0,
        t_inicio_ms=t, duracion_ms=DUR_CALIBRACION_MS,
        margen_inicial_ms=MARGEN_CALIBRACION[0],
        margen_final_ms=MARGEN_CALIBRACION[1],
        es_calibracion=1,
    ))
    t += DUR_CALIBRACION_MS

    vistas = {g: 0 for g in set(secuencia)}
    for i, gesto in enumerate(secuencia):
        rep_id = i // len(GESTOS_ACTIVOS) + 1
        posicion = posicion_de(vistas[gesto], bloque_postura)
        vistas[gesto] += 1

        # Preparacion: se anuncia el gesto que viene. Entera en margen,
        # asi que no entra al entrenamiento por descuido. Lleva el label
        # del gesto anunciado para poder estudiar la anticipacion.
        bloques.append(Bloque(
            tipo=TIPO_PREPARACION, label=gesto, repetition_id=rep_id,
            t_inicio_ms=t, duracion_ms=DUR_PREPARACION_MS,
            margen_inicial_ms=MARGEN_PREPARACION[0],
            margen_final_ms=MARGEN_PREPARACION[1],
            posicion_brazo=posicion,
        ))
        t += DUR_PREPARACION_MS

        bloques.append(Bloque(
            tipo=TIPO_CONTRACCION, label=gesto, repetition_id=rep_id,
            t_inicio_ms=t, duracion_ms=DUR_CONTRACCION_MS,
            margen_inicial_ms=MARGEN_CONTRACCION[0],
            margen_final_ms=MARGEN_CONTRACCION[1],
            posicion_brazo=posicion,
        ))
        t += DUR_CONTRACCION_MS

        # Reposo posterior: hereda el repetition_id de la contraccion que
        # acaba de terminar.
        bloques.append(Bloque(
            tipo=TIPO_REPOSO, label=LABEL_REST, repetition_id=rep_id,
            t_inicio_ms=t, duracion_ms=DUR_REPOSO_MS,
            margen_inicial_ms=MARGEN_REPOSO[0],
            margen_final_ms=MARGEN_REPOSO[1],
            posicion_brazo=posicion,
        ))
        t += DUR_REPOSO_MS

    return bloques


def resumen_sesion(bloques: List[Bloque]) -> dict:
    """Segundos utiles por clase y ratio de balance."""
    utiles = {n: 0.0 for n in NOMBRES_GESTOS}
    for b in bloques:
        if b.es_calibracion:
            continue          # se excluye del entrenamiento por defecto
        utiles[b.nombre_gesto] += b.segundos_utiles

    activos = [utiles[NOMBRES_GESTOS[g]] for g in GESTOS_ACTIVOS]
    media_activas = float(np.mean(activos)) if activos else 0.0
    ratio = utiles["Rest"] / media_activas if media_activas else 0.0

    total = sum(utiles.values())
    dur_total = max(b.t_fin_ms for b in bloques) / 1000.0

    return {
        "segundos_utiles": {k: round(v, 1) for k, v in utiles.items()},
        "porcentaje": {k: round(100 * v / total, 1) if total else 0.0
                       for k, v in utiles.items()},
        "ratio_rest_vs_activa": round(ratio, 2),
        "duracion_total_s": round(dur_total, 1),
        "n_bloques": len(bloques),
        "ventanas_estimadas": int(total * 50),   # stride 20 ms
    }


if __name__ == "__main__":
    import sys
    postura = sys.argv[1] if len(sys.argv) > 1 else BLOQUE_ESTATICO
    for sid in (1, 2, 3):
        bloques = construir_sesion(sid, bloque_postura=postura)
        secuencia = [b.label for b in bloques if b.tipo == TIPO_CONTRACCION]
        r = resumen_sesion(bloques)
        print(f"\n=== Sujeto {sid} ({postura}) ===")
        print(f"  Orden: {secuencia}")
        print(f"  Desbalance de transiciones: "
              f"{_desbalance(secuencia, GESTOS_ACTIVOS)}")
        print(f"  Duracion: {r['duracion_total_s']} s "
              f"({r['duracion_total_s']/60:.1f} min), {r['n_bloques']} bloques")
        print(f"  Segundos utiles: {r['segundos_utiles']}")
        print(f"  Ratio Rest:activa = {r['ratio_rest_vs_activa']}:1")
        print(f"  Ventanas estimadas: {r['ventanas_estimadas']}")
