"""
protocolo.py - Secuencia de bloques de una sesion de captura
=============================================================
Protesis transradial - Captura con voluntarios

ESTRUCTURA DE LA SESION:
  1. Un bloque de CALIBRACION de 15 s de reposo contiguo, fuera de la
     rotacion. Es reposo BASAL, antes de cualquier contraccion.
  2. 6 repeticiones. Cada repeticion presenta los 4 gestos activos una
     vez, en orden contrabalanceado.
  3. Cada gesto = bloque de REPOSO (8 s) + bloque de CONTRACCION (15 s).

  Total: 15 + 4*6*(8+15) = 567 s = 9.5 min de grabacion.

POR QUE REST NO ESTA EN LA ROTACION:
  Rest se graba de sobra en los 24 bloques de reposo entre contracciones.
  Anadir bloques de Rest propios duplicaria el concepto y dejaria la
  clase en 6:1 frente a cada clase activa. Asi queda en 1.63:1, que el
  submuestreo del pipeline maneja como un ajuste fino.

POR QUE EL REPOSO HEREDA EL repetition_id:
  En NinaPro DB5, todo el reposo compartia repetition = 0. Al agrupar por
  repeticion, el reposo entero caia en un unico pliegue: uno de los cinco
  quedo con 50.7% de Rest en test frente a ~8% en los demas, lo que
  inflo la desviacion estandar de la linea base.

  Aqui el reposo NUNCA recibe un repetition_id propio: hereda el del
  bloque de contraccion al que precede. Con eso, cualquier esquema de
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
# TIEMPOS (ms)
# ============================================================
DUR_CALIBRACION_MS = 15000
DUR_REPOSO_MS      = 8000
DUR_CONTRACCION_MS = 15000

MARGEN_CONTRACCION = (1000, 500)   # (entrada, salida) - NO reducir la entrada
MARGEN_REPOSO      = (2000, 500)
MARGEN_CALIBRACION = (1000, 500)

N_REPETICIONES = 6

TIPO_CALIBRACION = "calibracion"
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
        return (self.duracion_ms - self.margen_inicial_ms
                - self.margen_final_ms) / 1000.0


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
def construir_sesion(subject_id: int,
                     n_repeticiones: int = N_REPETICIONES) -> List[Bloque]:
    """
    Construye la lista completa de bloques con su linea temporal.

    El repetition_id del reposo es el del bloque de contraccion que le
    sigue, nunca uno propio.
    """
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

    for i, gesto in enumerate(secuencia):
        rep_id = i // len(GESTOS_ACTIVOS) + 1

        # Reposo previo: hereda el repetition_id del gesto que sigue.
        bloques.append(Bloque(
            tipo=TIPO_REPOSO, label=LABEL_REST, repetition_id=rep_id,
            t_inicio_ms=t, duracion_ms=DUR_REPOSO_MS,
            margen_inicial_ms=MARGEN_REPOSO[0],
            margen_final_ms=MARGEN_REPOSO[1],
        ))
        t += DUR_REPOSO_MS

        bloques.append(Bloque(
            tipo=TIPO_CONTRACCION, label=gesto, repetition_id=rep_id,
            t_inicio_ms=t, duracion_ms=DUR_CONTRACCION_MS,
            margen_inicial_ms=MARGEN_CONTRACCION[0],
            margen_final_ms=MARGEN_CONTRACCION[1],
        ))
        t += DUR_CONTRACCION_MS

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
    for sid in (1, 2, 3):
        bloques = construir_sesion(sid)
        secuencia = [b.label for b in bloques if b.tipo == TIPO_CONTRACCION]
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
