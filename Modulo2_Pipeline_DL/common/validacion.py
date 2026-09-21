"""
particion.py - Esquemas de validacion cruzada por grupos y verificacion de fuga
===============================================================================
Protesis transradial - Validacion con dataset NinaPro DB5

Este modulo aisla TODA la logica de particion para que el criterio de
agrupamiento sea el unico grado de libertad entre corridas comparables.

ESQUEMAS DISPONIBLES:

  'repeticion'  (linea base, tag si2-groupkfold-repeticion)
      Agrupa por el campo 'repetition' del .mat (1..6), COLAPSADO entre
      sujetos y ejercicios: la repeticion 3 del sujeto 1 y la del sujeto 7
      caen en el mismo grupo. Ningun sujeto queda fuera del entrenamiento,
      de modo que la metrica resultante es INTRA-SUJETO.

  'sujeto'
      Agrupa por subject_id (1..10). Cada pliegue reserva sujetos
      completos para prueba, sin que ninguna de sus ventanas aparezca en
      entrenamiento. La metrica resultante es INTER-SUJETO y mide
      generalizacion a un usuario no visto.

VERIFICACION DE FUGA:
  'verificar_sujetos_disjuntos' es una comprobacion dura (RuntimeError,
  no assert) que no depende de -O ni de flags del interprete. Con
  GroupKFold sobre subject_id nunca puede dispararse por construccion;
  por eso 'autotest_verificador' la ejerce contra una particion
  deliberadamente incorrecta en cada corrida, para demostrar que el
  detector realmente detecta.
"""

from typing import Iterable, List, Tuple

import numpy as np
from sklearn.model_selection import GroupKFold, KFold, StratifiedGroupKFold


ESQUEMAS = ("repeticion", "sujeto")


class FugaEntreParticiones(RuntimeError):
    """Se levanta cuando un mismo sujeto aparece en train y en test."""


# ============================================================
# SELECCION DEL VECTOR DE GRUPOS
# ============================================================
def obtener_vector_grupos(
    agrupamiento: str,
    grupos_repeticion: np.ndarray,
    sujetos: np.ndarray,
) -> np.ndarray:
    """
    Devuelve el vector de grupos que alimenta al validador cruzado.

    Args:
        agrupamiento: 'repeticion' o 'sujeto'
        grupos_repeticion: (N,) id de repeticion por ventana
        sujetos: (N,) id de sujeto por ventana

    Returns:
        (N,) vector de grupos
    """
    if agrupamiento == "repeticion":
        return grupos_repeticion
    if agrupamiento == "sujeto":
        return sujetos
    raise ValueError(
        f"Agrupamiento desconocido: '{agrupamiento}'. Use uno de {ESQUEMAS}."
    )


def construir_validador(n_splits: int, estratificado: bool, seed: int = 42):
    """
    Construye el objeto de validacion cruzada por grupos.

    GroupKFold reparte los grupos buscando equilibrar el NUMERO DE
    MUESTRAS por pliegue; no equilibra la distribucion de clases ni
    garantiza el mismo numero de grupos en cada pliegue.

    StratifiedGroupKFold ademas intenta preservar la proporcion de clases
    de cada pliegue, a costa de un reparto de grupos menos uniforme en
    tamano. Es estocastico, por lo que se fija shuffle+random_state.
    """
    if estratificado:
        return StratifiedGroupKFold(
            n_splits=n_splits, shuffle=True, random_state=seed
        )
    return GroupKFold(n_splits=n_splits)


# ============================================================
# VERIFICACION DE FUGA ENTRE TRAIN Y TEST
# ============================================================
def verificar_sujetos_disjuntos(
    sujetos: np.ndarray,
    idx_train: np.ndarray,
    idx_test: np.ndarray,
    fold_idx: int,
) -> None:
    """
    Falla ruidosamente si algun subject_id aparece a la vez en train y test.

    Esta verificacion NO es opcional y NO usa 'assert': un assert se
    desactiva con 'python -O' y esta comprobacion es justamente la que
    distingue una metrica inter-sujeto de una intra-sujeto disfrazada.

    Raises:
        FugaEntreParticiones: con la lista de sujetos infractores y cuantas
        ventanas aporta cada uno a cada lado.
    """
    sujetos_train = set(np.unique(sujetos[idx_train]).tolist())
    sujetos_test = set(np.unique(sujetos[idx_test]).tolist())
    interseccion = sorted(sujetos_train & sujetos_test)

    if interseccion:
        detalle = []
        for s in interseccion:
            n_tr = int((sujetos[idx_train] == s).sum())
            n_te = int((sujetos[idx_test] == s).sum())
            detalle.append(f"    sujeto {s}: {n_tr} ventanas en train, "
                           f"{n_te} en test")
        raise FugaEntreParticiones(
            f"FUGA ENTRE SUJETOS en el pliegue {fold_idx + 1}: "
            f"{len(interseccion)} sujeto(s) aparecen en train Y en test "
            f"{interseccion}.\n" + "\n".join(detalle) + "\n"
            "  La metrica de este pliegue seria intra-sujeto, no "
            "inter-sujeto. Corrida abortada."
        )


def autotest_verificador(sujetos: np.ndarray, seed: int = 0) -> str:
    """
    Prueba negativa del verificador de fuga.

    Con GroupKFold agrupado por sujeto, 'verificar_sujetos_disjuntos' no
    puede dispararse: es cierta por construccion. Un detector que nunca
    se ejerce es indistinguible de un detector roto, asi que aqui se le
    presenta a proposito una particion INCORRECTA (KFold barajado, que
    parte las ventanas sin respetar al sujeto) y se exige que la detecte.

    Returns:
        Mensaje descriptivo del resultado, para el log.

    Raises:
        RuntimeError: si el verificador NO detecta la fuga inyectada.
    """
    kf = KFold(n_splits=5, shuffle=True, random_state=seed)
    idx_train, idx_test = next(iter(kf.split(np.arange(len(sujetos)))))

    try:
        verificar_sujetos_disjuntos(sujetos, idx_train, idx_test, fold_idx=-1)
    except FugaEntreParticiones as e:
        primera_linea = str(e).splitlines()[0]
        return ("[AUTOTEST] OK - el verificador detecto la fuga inyectada "
                f"con KFold barajado: {primera_linea}")

    raise RuntimeError(
        "[AUTOTEST] FALLO - se inyecto una particion con fuga evidente "
        "(KFold barajado sobre ventanas de 10 sujetos) y "
        "'verificar_sujetos_disjuntos' NO la detecto. El verificador de la "
        "TAREA 3 no es confiable; no tiene sentido continuar."
    )


# ============================================================
# COMPOSICION DE UN PLIEGUE (para logging y reporte)
# ============================================================
def describir_pliegue(
    fold_idx: int,
    idx_train: np.ndarray,
    idx_test: np.ndarray,
    y_int: np.ndarray,
    sujetos: np.ndarray,
    grupos_repeticion: np.ndarray,
    nombres_clases: Iterable[str],
) -> dict:
    """
    Resume la composicion de un pliegue: que sujetos y cuantas ventanas de
    cada clase quedan a cada lado.
    """
    nombres_clases = list(nombres_clases)
    n_clases = len(nombres_clases)

    def conteo_clases(idx):
        cuenta = np.bincount(y_int[idx], minlength=n_clases)
        return {nombres_clases[c]: int(cuenta[c]) for c in range(n_clases)}

    return {
        "fold": fold_idx + 1,
        "sujetos_train": sorted(np.unique(sujetos[idx_train]).tolist()),
        "sujetos_test": sorted(np.unique(sujetos[idx_test]).tolist()),
        "repeticiones_train": sorted(
            np.unique(grupos_repeticion[idx_train]).tolist()
        ),
        "repeticiones_test": sorted(
            np.unique(grupos_repeticion[idx_test]).tolist()
        ),
        "n_train": int(len(idx_train)),
        "n_test": int(len(idx_test)),
        "clases_train": conteo_clases(idx_train),
        "clases_test": conteo_clases(idx_test),
        "proporciones_test": {
            k: round(v / max(len(idx_test), 1), 4)
            for k, v in conteo_clases(idx_test).items()
        },
    }


def formatear_pliegue(desc: dict, agrupamiento: str) -> str:
    """Formatea 'describir_pliegue' como texto legible para el log."""
    lineas = []
    lineas.append(f"  --- Pliegue {desc['fold']} "
                  f"(agrupamiento: {agrupamiento}) ---")
    lineas.append(f"    Sujetos TRAIN ({len(desc['sujetos_train'])}): "
                  f"{desc['sujetos_train']}")
    lineas.append(f"    Sujetos TEST  ({len(desc['sujetos_test'])}): "
                  f"{desc['sujetos_test']}")
    solapan = sorted(set(desc["sujetos_train"]) & set(desc["sujetos_test"]))
    lineas.append(f"    Sujetos en AMBOS lados: {solapan if solapan else 'ninguno'}")
    lineas.append(f"    Ventanas: train={desc['n_train']} test={desc['n_test']}")
    lineas.append(f"    {'Clase':<14}{'train':>10}{'test':>10}{'% test':>10}")
    for clase in desc["clases_train"]:
        n_tr = desc["clases_train"][clase]
        n_te = desc["clases_test"][clase]
        pct = 100 * desc["proporciones_test"][clase]
        lineas.append(f"    {clase:<14}{n_tr:>10}{n_te:>10}{pct:>9.1f}%")
    return "\n".join(lineas)


# ============================================================
# GENERACION DE PARTICIONES
# ============================================================
def generar_particiones(
    X: np.ndarray,
    y_int: np.ndarray,
    grupos_repeticion: np.ndarray,
    sujetos: np.ndarray,
    agrupamiento: str,
    n_splits: int = 5,
    estratificado: bool = False,
    seed: int = 42,
) -> List[Tuple[np.ndarray, np.ndarray]]:
    """
    Genera la lista de pares (idx_train, idx_test) del esquema pedido.

    La verificacion de sujetos disjuntos se aplica SOLO cuando el
    agrupamiento es por sujeto. Con agrupamiento por repeticion los
    sujetos se solapan por construccion (ese es, precisamente, el motivo
    por el que aquella metrica es intra-sujeto); alli el solapamiento se
    reporta como estadistica, no como error.
    """
    grupos = obtener_vector_grupos(agrupamiento, grupos_repeticion, sujetos)
    validador = construir_validador(n_splits, estratificado, seed)

    particiones = []
    for fold_idx, (idx_train, idx_test) in enumerate(
        validador.split(X, y_int, groups=grupos)
    ):
        if agrupamiento == "sujeto":
            verificar_sujetos_disjuntos(sujetos, idx_train, idx_test, fold_idx)
        particiones.append((idx_train, idx_test))

    return particiones
