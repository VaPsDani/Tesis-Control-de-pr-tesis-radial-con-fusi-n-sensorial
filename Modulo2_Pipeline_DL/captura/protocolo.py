"""
protocolo.py - Secuencia de bloques de una sesion de captura
=============================================================
Protesis transradial - Captura con voluntarios

ESTRUCTURA DE LA SESION:
  1. Un bloque de CALIBRACION de 15 s de reposo contiguo, fuera de la
     rotacion. Es reposo BASAL, antes de cualquier contraccion, y es la
     referencia con la que se normaliza a ese sujeto.
  2. 6 repeticiones. Cada repeticion presenta los 4 gestos activos una
     vez, en orden contrabalanceado.
  3. Cada gesto = PREPARACION (3 s) + CONTRACCION (10 s) + REPOSO (8 s).
  4. Ademas, 3 REPOSOS EN MOVIMIENTO, con la misma temporizacion: el
     participante recorre las tres posiciones con la mano relajada. Van
     etiquetados como Rest, con bloque_tipo "reposo_dinamico", y caen en
     3 de las 6 repeticiones, en una posicion sorteada dentro de ella.

  Total: 15 + (4*6 + 3)*(3+10+8) = 582 s = 9.7 min de grabacion.

CONDICION POSTURAL, POR REPETICION Y NO POR SESION:
  De las 6 repeticiones de cada gesto, 3 son ESTATICAS, con el brazo
  quieto, y 3 DINAMICAS, recorriendo tres posiciones del brazo durante la
  contraccion sin soltar el gesto.

  Las dos condiciones conviven en la misma sesion a proposito: comparten
  sujeto, colocacion del brazalete y bloque de calibracion, asi que la
  comparacion entre ellas es pareada y no arrastra las diferencias de
  montaje que tendrian dos sesiones distintas. Es el factor B del
  experimento experimentos/ablacion_imu.

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
  inflo la desviacion estandar de la referencia SI2.

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
from config_captura import (CONDICION_DINAMICA, CONDICION_ESTATICA,  # noqa: E402
                            CONDICION_NINGUNA, CONDICIONES,
                            DUR_CALIBRACION_MS, DUR_CONTRACCION_MS,
                            DUR_PREPARACION_MS, DUR_REPOSO_MS,
                            MARGEN_CALIBRACION, MARGEN_CONTRACCION,
                            MARGEN_PREPARACION, MARGEN_REPOSO, N_REPETICIONES,
                            N_REPOSO_DINAMICO,
                            POSICION_NINGUNA, POSICIONES_BRAZO,
                            RAMPA_CONTRACCION_MS, REPETICIONES_POR_CONDICION,
                            TRAMO_POSICION_MINIMO_MS)

TIPO_CALIBRACION = "calibracion"
TIPO_PREPARACION = "preparacion"
TIPO_REPOSO      = "reposo"
TIPO_CONTRACCION = "contraccion"
# Bloque de 10 s del reposo en movimiento. Lleva label Rest. Se distingue
# por bloque_tipo y no por una clase nueva: para el modelo es Rest, y lo
# unico que cambia es que el brazo se mueve.
TIPO_REPOSO_DINAMICO = "reposo_dinamico"
# Bloques en los que se recorren las posiciones del brazo.
TIPOS_CON_RECORRIDO = (TIPO_CONTRACCION, TIPO_REPOSO_DINAMICO)


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
    # Condicion postural de la repeticion: estatica o dinamica. Vacia en
    # el bloque de calibracion, que no pertenece a ninguna.
    condicion_postural: str = CONDICION_NINGUNA
    # Orden en que se recorren las tres posiciones del brazo, solo en las
    # repeticiones dinamicas. Vacio en las estaticas. Lo llevan la
    # contraccion, que es donde se recorre, y su preparacion, que lo usa
    # solo para pedir en pantalla la posicion de partida.
    orden_posiciones: tuple = ()

    def posicion_en(self, t_ms: int) -> str:
        """
        Posicion del brazo pedida en el instante absoluto t_ms.

        En una repeticion dinamica la contraccion se reparte en tres
        tramos iguales, uno por posicion, y el participante pasa de una a
        otra sin soltar el gesto. Devolver la posicion instante a instante
        es lo que permite escribirla en el CSV y estudiar despues si el
        error de clasificacion se concentra en los cambios de posicion.
        """
        if not self.orden_posiciones or self.tipo not in TIPOS_CON_RECORRIDO:
            return POSICION_NINGUNA
        # Se recorta a los limites del bloque en vez de devolver vacio:
        # una muestra puede caer unos milisegundos despues del final
        # nominal y seguir perteneciendo a este bloque, porque la etiqueta
        # se asigna por el reloj del ESP32 relativo al marcador. Dejarla
        # sin posicion crearia huecos en la columna sin significado.
        rel = min(max(t_ms - self.t_inicio_ms, 0), self.duracion_ms - 1)
        tramo = self.duracion_ms / len(self.orden_posiciones)
        return self.orden_posiciones[min(int(rel / tramo),
                                         len(self.orden_posiciones) - 1)]

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

    # Las tres posiciones de una repeticion dinamica se reparten la
    # contraccion. Con tramos muy cortos el participante no llega a
    # colocarse y lo que se graba es transicion pura.
    tramo = DUR_CONTRACCION_MS / len(POSICIONES_BRAZO)
    if tramo < TRAMO_POSICION_MINIMO_MS:
        raise ValueError(
            f"Con una contraccion de {DUR_CONTRACCION_MS} ms, cada una de las "
            f"{len(POSICIONES_BRAZO)} posiciones dura {tramo:.0f} ms, por "
            f"debajo del minimo de {TRAMO_POSICION_MINIMO_MS} ms. Alargue la "
            f"contraccion o reduzca el numero de posiciones.")


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
def asignar_condiciones(subject_id: int, secuencia: List[int]) -> List[str]:
    """
    Reparte las repeticiones de cada gesto entre estatica y dinamica.

    POR QUE POR GESTO Y NO A LO LARGO DE LA SESION:
      Cada gesto tiene que recibir el mismo numero de repeticiones de
      cada condicion, 3 y 3. Repartiendo solo por el orden global, un
      gesto podria acabar con 5 estaticas y 1 dinamica, y la condicion
      quedaria confundida con el gesto, que es justo el efecto que el
      experimento de ablacion quiere medir.

      Dentro de cada gesto el orden se sortea con semilla derivada del
      subject_id: la sesion es reproducible, cada sujeto recibe un orden
      distinto y la condicion no cae siempre en el mismo tramo de la
      sesion, donde la fatiga es distinta.
    """
    rng = np.random.RandomState(subject_id + 7919)
    pendientes = {}
    for gesto in sorted(set(secuencia)):
        bolsa = ([CONDICION_ESTATICA] * REPETICIONES_POR_CONDICION
                 + [CONDICION_DINAMICA] * REPETICIONES_POR_CONDICION)
        rng.shuffle(bolsa)
        pendientes[gesto] = list(bolsa)

    salida = []
    for gesto in secuencia:
        if pendientes[gesto]:
            salida.append(pendientes[gesto].pop())
        else:
            # Mas repeticiones que condiciones preparadas: se alterna en
            # vez de fallar. Solo ocurre si se sube N_REPETICIONES sin
            # tocar REPETICIONES_POR_CONDICION.
            salida.append(CONDICIONES[len(salida) % len(CONDICIONES)])
    return salida


def orden_posiciones_de(ocurrencia_dinamica: int) -> tuple:
    """
    Orden en que se recorren las tres posiciones dentro de una
    contraccion dinamica.

    Rota con cada repeticion dinamica del gesto, de modo que ninguna
    posicion cae siempre en el primer tramo, que es el que pierde su
    primer segundo por el margen de entrada.
    """
    k = ocurrencia_dinamica % len(POSICIONES_BRAZO)
    return tuple(POSICIONES_BRAZO[k:] + POSICIONES_BRAZO[:k])


def ubicar_reposos_dinamicos(subject_id: int,
                             n_repeticiones: int = N_REPETICIONES,
                             n_reposos: int = N_REPOSO_DINAMICO) -> List[tuple]:
    """
    En que repeticion y en que lugar de ella cae cada reposo en
    movimiento. Devuelve pares (repetition_id, hueco), donde hueco va de
    0 (antes del primer gesto) a 4 (despues del ultimo).

    Las repeticiones se parten en n_reposos tramos seguidos y se sortea
    UNA de cada tramo. Con 6 y 3, una entre la 1 y la 2, otra entre la 3
    y la 4 y otra entre la 5 y la 6. Asi los tres quedan repartidos a lo
    largo de la sesion y ninguno carga siempre con el principio o con el
    final, donde la fatiga es distinta.

    El orden de los gestos NO se toca: el reposo se inserta entre ellos.
    El contrabalanceo de los pares de gestos consecutivos sigue siendo el
    de generar_secuencia_gestos, salvo los pares que el reposo separa.
    """
    rng = np.random.RandomState(subject_id + 104729)
    tramos = np.array_split(np.arange(1, n_repeticiones + 1), n_reposos)
    return [(int(rng.choice(t)), int(rng.randint(0, len(GESTOS_ACTIVOS) + 1)))
            for t in tramos if len(t)]


def construir_sesion(subject_id: int,
                     n_repeticiones: int = N_REPETICIONES) -> List[Bloque]:
    """
    Construye la lista completa de bloques con su linea temporal.

    Cada gesto son tres bloques seguidos: PREPARACION, CONTRACCION y
    REPOSO. El repetition_id de la preparacion y del reposo es el del
    bloque de contraccion al que acompanan, nunca uno propio: asi
    cualquier esquema de agrupamiento reparte el reposo de forma
    proporcional en vez de dejarlo entero en un pliegue.

    Las dos condiciones posturales conviven en la MISMA sesion, con 3
    repeticiones de cada una por gesto. Comparten sujeto, colocacion del
    brazalete y calibracion, que es lo que hace pareada la comparacion.
    """
    validar_tiempos()

    secuencia = generar_secuencia_gestos(subject_id, n_repeticiones)
    condiciones = asignar_condiciones(subject_id, secuencia)
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

    # Cada item es (label, condicion, repetition_id, orden de posiciones,
    # tipo del bloque principal). Primero los gestos, en su orden
    # contrabalanceado, y despues se intercalan los reposos en movimiento.
    dinamicas_vistas = {g: 0 for g in set(secuencia)}
    por_repeticion = {}
    for i, (gesto, condicion) in enumerate(zip(secuencia, condiciones)):
        rep_id = i // len(GESTOS_ACTIVOS) + 1
        if condicion == CONDICION_DINAMICA:
            orden = orden_posiciones_de(dinamicas_vistas[gesto])
            dinamicas_vistas[gesto] += 1
        else:
            orden = ()
        por_repeticion.setdefault(rep_id, []).append(
            (gesto, condicion, rep_id, orden, TIPO_CONTRACCION))

    # El punto de partida del recorrido rota entre los reposos en
    # movimiento, igual que entre las repeticiones dinamicas de un gesto.
    # Se insertan de atras hacia delante dentro de cada repeticion para
    # que un hueco no desplace al siguiente.
    huecos = ubicar_reposos_dinamicos(subject_id, n_repeticiones)
    for j, (rep_id, hueco) in sorted(enumerate(huecos),
                                     key=lambda x: (x[1][0], -x[1][1])):
        por_repeticion[rep_id].insert(hueco, (
            LABEL_REST, CONDICION_DINAMICA, rep_id, orden_posiciones_de(j),
            TIPO_REPOSO_DINAMICO))

    items = [it for rep_id in sorted(por_repeticion)
             for it in por_repeticion[rep_id]]

    for gesto, condicion, rep_id, orden, tipo_principal in items:

        # Preparacion: se anuncia el gesto que viene y, si toca, que la
        # repeticion es con el brazo en movimiento. Entera en margen, asi
        # que no entra al entrenamiento por descuido. Lleva el label del
        # gesto anunciado para poder estudiar la anticipacion.
        #
        # LLEVA TAMBIEN EL ORDEN DE POSICIONES, y es solo para la
        # pantalla: en la preparacion se ilumina la PRIMERA posicion del
        # recorrido para que el participante coloque ahi el brazo, con la
        # mano relajada, antes de que empiece la contraccion. Sin esto el
        # primer tramo de cada repeticion dinamica se gastaba llevando el
        # brazo a su sitio con el gesto ya hecho.
        #
        # No toca el CSV: posicion_en() sigue devolviendo vacio en
        # cualquier bloque que no sea la contraccion.
        bloques.append(Bloque(
            tipo=TIPO_PREPARACION, label=gesto, repetition_id=rep_id,
            t_inicio_ms=t, duracion_ms=DUR_PREPARACION_MS,
            margen_inicial_ms=MARGEN_PREPARACION[0],
            margen_final_ms=MARGEN_PREPARACION[1],
            condicion_postural=condicion, orden_posiciones=orden,
        ))
        t += DUR_PREPARACION_MS

        # El bloque principal es una contraccion o un reposo en
        # movimiento. Los dos duran lo mismo y llevan los mismos margenes,
        # asi que la unica diferencia es la etiqueta y lo que se pide.
        bloques.append(Bloque(
            tipo=tipo_principal, label=gesto, repetition_id=rep_id,
            t_inicio_ms=t, duracion_ms=DUR_CONTRACCION_MS,
            margen_inicial_ms=MARGEN_CONTRACCION[0],
            margen_final_ms=MARGEN_CONTRACCION[1],
            condicion_postural=condicion, orden_posiciones=orden,
        ))
        t += DUR_CONTRACCION_MS

        # Reposo posterior: hereda el repetition_id de la contraccion que
        # acaba de terminar. El brazo vuelve a quedarse quieto, asi que
        # conserva la condicion de la repeticion solo como etiqueta.
        bloques.append(Bloque(
            tipo=TIPO_REPOSO, label=LABEL_REST, repetition_id=rep_id,
            t_inicio_ms=t, duracion_ms=DUR_REPOSO_MS,
            margen_inicial_ms=MARGEN_REPOSO[0],
            margen_final_ms=MARGEN_REPOSO[1],
            condicion_postural=condicion,
        ))
        t += DUR_REPOSO_MS

    return bloques


def orden_completo(bloques: List[Bloque]) -> List[str]:
    """
    Lo que se pide en la sesion, un elemento por bloque principal: el
    gesto, o Rest_mov para el reposo en movimiento, con su repeticion y
    su condicion. Es lo que va al JSON para reconstruir la sesion.
    """
    return [f"r{b.repetition_id} "
            f"{'Rest_mov' if b.tipo == TIPO_REPOSO_DINAMICO else b.nombre_gesto} "
            f"{b.condicion_postural}"
            for b in bloques if b.tipo in TIPOS_CON_RECORRIDO]


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

    # Reparto por condicion postural: las dos celdas del factor B tienen
    # que quedar con el mismo n, o el contraste no seria pareado.
    por_condicion = {c: 0.0 for c in CONDICIONES}
    contracciones = {c: 0 for c in CONDICIONES}
    for b in bloques:
        if b.condicion_postural in por_condicion:
            por_condicion[b.condicion_postural] += b.segundos_utiles
            if b.tipo == TIPO_CONTRACCION:
                contracciones[b.condicion_postural] += 1
    reposos_dinamicos = sum(1 for b in bloques
                            if b.tipo == TIPO_REPOSO_DINAMICO)

    return {
        "segundos_utiles": {k: round(v, 1) for k, v in utiles.items()},
        "porcentaje": {k: round(100 * v / total, 1) if total else 0.0
                       for k, v in utiles.items()},
        "ratio_rest_vs_activa": round(ratio, 2),
        "duracion_total_s": round(dur_total, 1),
        "n_bloques": len(bloques),
        "ventanas_estimadas": int(total * 50),   # stride 20 ms
        "segundos_utiles_por_condicion": {k: round(v, 1)
                                          for k, v in por_condicion.items()},
        "contracciones_por_condicion": contracciones,
        "reposos_en_movimiento": reposos_dinamicos,
    }


if __name__ == "__main__":
    import collections
    for sid in (1, 2, 3):
        bloques = construir_sesion(sid)
        contracciones = [b for b in bloques if b.tipo == TIPO_CONTRACCION]
        secuencia = [b.label for b in contracciones]
        r = resumen_sesion(bloques)
        print(f"\n=== Sujeto {sid} ===")
        print(f"  Orden: {secuencia}")
        print(f"  Desbalance de transiciones: "
              f"{_desbalance(secuencia, GESTOS_ACTIVOS)}")
        print(f"  Duracion: {r['duracion_total_s']} s "
              f"({r['duracion_total_s']/60:.1f} min), {r['n_bloques']} bloques")
        print(f"  Segundos utiles: {r['segundos_utiles']}")
        print(f"  Ratio Rest:activa = {r['ratio_rest_vs_activa']}:1")
        print(f"  Ventanas estimadas: {r['ventanas_estimadas']}")
        print(f"  Contracciones por condicion: "
              f"{r['contracciones_por_condicion']}, reposos en movimiento: "
              f"{r['reposos_en_movimiento']}")
        print("  Orden completo:")
        for k, item in enumerate(orden_completo(bloques), 1):
            print(f"    {k:2d}. {item}")
        tabla = collections.Counter((NOMBRES_GESTOS[b.label],
                                     b.condicion_postural)
                                    for b in contracciones)
        for g in GESTOS_ACTIVOS:
            n = NOMBRES_GESTOS[g]
            print(f"    {n:<12}"
                  + "  ".join(f"{c} {tabla[(n, c)]}" for c in CONDICIONES))
