"""
normalizacion.py - Estandarizacion z-score por canal para la ruta EMG
=====================================================================
Protesis transradial - Validacion con dataset NinaPro DB5

MOTIVACION:
  La amplitud del sEMG varia mucho de una persona a otra: colocacion del
  brazalete, impedancia de la piel, masa muscular. Medido sobre NinaPro
  DB5, la desviacion estandar de un mismo canal cambia hasta 4.9x entre
  sujetos (EMG2: 5.27 a 21.58; ACC6: 0.018 a 0.091), mientras que las
  medias son practicamente iguales. Es decir: el problema entre sujetos
  es de ESCALA, no de offset.

  Sin normalizar, una red entrenada con 8 sujetos ve al noveno como una
  senal de otra magnitud y no transfiere.

MODOS:

  'ninguna'
      Sin transformacion. Reproduce el comportamiento previo.

  'global'
      z-score por canal con media y desviacion calculadas UNICAMENTE
      sobre las ventanas de entrenamiento del pliegue, aplicadas despues
      a train y a test. Es la opcion conservadora: no toca ningun dato
      de test para estimar los parametros.

  'sujeto'
      z-score por canal calculado de forma independiente para cada
      sujeto, con las estadisticas de ese mismo sujeto, incluidos los
      sujetos de test.

      POR QUE ESTO NO ES FUGA DE DATOS:
        1. No usa las etiquetas. Las estadisticas son medias y
           desviaciones de la senal cruda; no interviene y en ningun
           momento, ni directa ni indirectamente.
        2. No cruza informacion entre sujetos. Cada sujeto se normaliza
           en su propio marco de referencia, sin ver a los demas, asi
           que el conjunto de entrenamiento no aporta nada al de prueba.
        3. Reproduce el procedimiento real de despliegue. Al ponerse la
           protesis, el usuario graba unos segundos de calibracion antes
           de usarla; esas muestras son exactamente las que darian estas
           estadisticas. Un modelo que exigiera conocer de antemano la
           escala del usuario no seria desplegable, y uno evaluado sin
           calibracion estaria midiendo un escenario que en la practica
           nunca ocurre.
        Lo que si seria fuga es estimar la escala de un sujeto de test
        usando datos de los sujetos de entrenamiento, o usar sus
        etiquetas para elegir que muestras entran en el calculo.

  'sujeto_rest'
      Igual que 'sujeto' pero calculando las estadisticas SOLO con las
      ventanas de clase Rest del sujeto, que es lo mas parecido a una
      calibracion real de unos segundos en reposo.

      ADVERTENCIA, y es una diferencia importante frente a 'sujeto':
      este modo SI mira las etiquetas del sujeto de test, porque hay que
      saber que ventanas son Rest para seleccionarlas. La justificacion
      seria operativa, no estadistica: en despliegue se conoce la
      etiqueta POR PROTOCOLO, porque se le pide al usuario que
      descanse, no porque se infiera del modelo. Es un argumento mas
      debil que el del punto 1 de 'sujeto' y conviene reportarlo como
      tal.

      Segunda advertencia: sobre este dataset la desviacion estandar en
      Rest es ~3-4x menor que la global (ratio medio 0.22-0.34 en los
      canales EMG), asi que normalizar por Rest amplifica los gestos
      activos por ese factor. Y la correlacion entre ambas escalas es
      irregular entre canales (EMG1 r=+0.97, pero ACC7 r=+0.42). No es
      un sustituto de 'sujeto': es una condicion distinta y mas dura.

CONVENCION:
  El z-score es POR CANAL: media y desviacion se reducen sobre los ejes
  (ventana, paso temporal), dejando un vector de longitud igual al
  numero de canales (8). No se normaliza por paso temporal ni por
  ventana individual, que destruirian la forma de onda del gesto.
"""

from typing import Tuple

import numpy as np

MODOS = ("ninguna", "global", "sujeto", "sujeto_rest")

# Piso para la desviacion estandar. Evita dividir por cero en un canal
# constante sin distorsionar los canales reales: la desviacion mas
# pequena observada en el dataset es 0.0118, siete ordenes por encima.
EPS = 1e-8

# Minimo de ventanas para considerar fiable una estadistica por sujeto.
# En este dataset el sujeto con menos ventanas Rest tiene 891.
MIN_VENTANAS_STATS = 30


def _estadisticas(X: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """
    Media y desviacion estandar por canal.

    Se reduce sobre (ventanas, pasos) y se calcula en float64 para que la
    suma de decenas de miles de ventanas no pierda precision, devolviendo
    float32 para no cambiar el dtype del dataset.
    """
    mu = X.mean(axis=(0, 1), dtype=np.float64)
    sd = X.std(axis=(0, 1), dtype=np.float64)
    return mu.astype(np.float32), np.maximum(sd, EPS).astype(np.float32)


def _aplicar(X: np.ndarray, mu: np.ndarray, sd: np.ndarray) -> np.ndarray:
    """Aplica (X - mu) / sd difundiendo sobre el eje de canales."""
    return ((X - mu) / sd).astype(np.float32)


def _normalizar_por_sujeto(
    X: np.ndarray,
    sujetos: np.ndarray,
    y_int: np.ndarray,
    solo_rest: bool,
    clase_rest: int,
    etiqueta_lado: str,
) -> Tuple[np.ndarray, dict]:
    """
    Normaliza cada sujeto con sus propias estadisticas, in-place sobre una
    copia. Devuelve el array normalizado y las estadisticas por sujeto.
    """
    X_out = np.empty_like(X)
    stats = {}

    for s in np.unique(sujetos):
        mask_sujeto = sujetos == s

        if solo_rest:
            mask_stats = mask_sujeto & (y_int == clase_rest)
            fuente = f"clase {clase_rest} (Rest)"
        else:
            mask_stats = mask_sujeto
            fuente = "todas sus ventanas"

        n_stats = int(mask_stats.sum())
        if n_stats < MIN_VENTANAS_STATS:
            raise ValueError(
                f"El sujeto {s} solo aporta {n_stats} ventanas de {fuente} "
                f"en {etiqueta_lado}, por debajo del minimo de "
                f"{MIN_VENTANAS_STATS}. Las estadisticas de calibracion "
                f"serian ruido; abortando en vez de normalizar mal."
            )

        mu, sd = _estadisticas(X[mask_stats])
        X_out[mask_sujeto] = _aplicar(X[mask_sujeto], mu, sd)

        stats[int(s)] = {
            "n_ventanas_stats": n_stats,
            "n_ventanas_normalizadas": int(mask_sujeto.sum()),
            "fuente": fuente,
            "mu": [round(float(v), 6) for v in mu],
            "sd": [round(float(v), 6) for v in sd],
        }

    return X_out, stats


def normalizar(
    X_train: np.ndarray,
    X_test: np.ndarray,
    sujetos_train: np.ndarray,
    sujetos_test: np.ndarray,
    y_train: np.ndarray,
    y_test: np.ndarray,
    modo: str,
    clase_rest: int = 0,
) -> Tuple[np.ndarray, np.ndarray, dict]:
    """
    Aplica el modo de normalizacion pedido a un pliegue.

    Args:
        X_train, X_test: (N, pasos, canales)
        sujetos_train, sujetos_test: (N,) id de sujeto por ventana
        y_train, y_test: (N, clases) one-hot
        modo: uno de MODOS
        clase_rest: indice de la clase Rest (para 'sujeto_rest')

    Returns:
        (X_train_norm, X_test_norm, info)  info es serializable a JSON.
    """
    if modo not in MODOS:
        raise ValueError(f"Modo de normalizacion desconocido: '{modo}'. "
                         f"Use uno de {MODOS}.")

    if modo == "ninguna":
        return X_train, X_test, {"modo": "ninguna"}

    if modo == "global":
        # Estadisticas SOLO del pliegue de entrenamiento. X_test no
        # participa en el calculo, solo recibe la transformacion.
        mu, sd = _estadisticas(X_train)
        info = {
            "modo": "global",
            "origen_estadisticas": "solo ventanas de train del pliegue",
            "n_ventanas_stats": int(X_train.shape[0]),
            "mu": [round(float(v), 6) for v in mu],
            "sd": [round(float(v), 6) for v in sd],
        }
        return _aplicar(X_train, mu, sd), _aplicar(X_test, mu, sd), info

    # --- Modos por sujeto ---
    # Solo estan bien definidos si cada sujeto vive entero en un lado del
    # pliegue. Con agrupamiento por repeticion un sujeto aparece a ambos
    # lados y "sus propias estadisticas" seria ambiguo (calcularlas por
    # separado en cada lado daria dos escalas distintas al mismo sujeto).
    solapan = sorted(set(np.unique(sujetos_train).tolist())
                     & set(np.unique(sujetos_test).tolist()))
    if solapan:
        raise ValueError(
            f"La normalizacion '{modo}' requiere que cada sujeto quede "
            f"entero en un solo lado del pliegue, pero los sujetos "
            f"{solapan} aparecen en train y en test. Use "
            f"--agrupamiento sujeto, o --normalizacion global."
        )

    solo_rest = (modo == "sujeto_rest")
    y_train_int = y_train.argmax(axis=1)
    y_test_int = y_test.argmax(axis=1)

    X_tr_n, stats_tr = _normalizar_por_sujeto(
        X_train, sujetos_train, y_train_int, solo_rest, clase_rest, "train"
    )
    X_te_n, stats_te = _normalizar_por_sujeto(
        X_test, sujetos_test, y_test_int, solo_rest, clase_rest, "test"
    )

    info = {
        "modo": modo,
        "origen_estadisticas": (
            "ventanas de clase Rest de cada sujeto"
            if solo_rest else "todas las ventanas de cada sujeto"
        ),
        "usa_etiquetas_de_test": bool(solo_rest),
        "estadisticas_por_sujeto": {**stats_tr, **stats_te},
    }
    return X_tr_n, X_te_n, info


def verificar_normalizacion(X: np.ndarray, sujetos: np.ndarray,
                            modo: str) -> str:
    """
    Comprueba que la transformacion hizo lo que dice y devuelve una linea
    de log. Para los modos por sujeto, cada sujeto debe quedar con media
    ~0 y desviacion ~1 en cada canal (salvo 'sujeto_rest', donde eso solo
    vale para sus ventanas de Rest).
    """
    if modo in ("ninguna",):
        return "[NORM] modo 'ninguna': datos sin transformar"

    if modo in ("global", "sujeto_rest"):
        mu = X.mean(axis=(0, 1))
        sd = X.std(axis=(0, 1))
        return (f"[NORM] modo '{modo}': media global por canal en "
                f"[{mu.min():+.3f}, {mu.max():+.3f}], "
                f"sd en [{sd.min():.3f}, {sd.max():.3f}]")

    # modo 'sujeto': cada sujeto debe quedar estandarizado
    peor_mu, peor_sd = 0.0, 0.0
    for s in np.unique(sujetos):
        Xs = X[sujetos == s]
        peor_mu = max(peor_mu, float(np.abs(Xs.mean(axis=(0, 1))).max()))
        peor_sd = max(peor_sd, float(np.abs(Xs.std(axis=(0, 1)) - 1.0).max()))
    return (f"[NORM] modo 'sujeto': peor |media| por sujeto/canal "
            f"{peor_mu:.2e}, peor |sd-1| {peor_sd:.2e}")
