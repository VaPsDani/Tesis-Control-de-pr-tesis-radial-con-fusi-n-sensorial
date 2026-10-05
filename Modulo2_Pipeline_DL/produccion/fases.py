"""
fases.py - Deteccion de fases del gesto a partir de la senal
=============================================================
Protesis transradial - compartido por la captura propia y los datasets
publicos de LMG.

POR QUE NO BASTA UN MARGEN FIJO:
  La etiqueta de un bloque sigue a la SENAL VISUAL, no al movimiento.
  Entre la instruccion y el primer cambio en la senal hay un tiempo de
  reaccion variable entre personas y entre repeticiones, y con orden
  aleatorizado sube 150-200 ms por la ley de Hick. Un margen fijo o
  recorta movimiento real o deja reaccion etiquetada como gesto.

  Aqui el inicio del movimiento se detecta en la propia senal.

FASES:
  Preparacion (solo con bloque_tipo, desde la version 3):
    preparacion  los 3 s en que se anuncia el gesto. No entra nunca.
  Bloques de gesto:
    reaccion   desde la senal visual hasta el onset detectado. La mano
               sigue en reposo aunque la etiqueta ya diga "gesto".
    dinamica   desde el onset hasta que la senal alcanza su meseta. Es la
               fase que gobierna el control real de la protesis.
    meseta     el gesto sostenido.
  Periodos de reposo:
    relajacion desde el fin del gesto hasta que la senal se asienta.
    reposo     reposo estable.
    recorte    bordes del reposo estable que se descartan.

LINEA BASE LOCAL — la decision de diseno central:
  La version 1 comparaba cada gesto con la base del reposo anterior
  ENCADENADA desde bloques previos, y exigia que tras un gesto la senal
  volviera a ese nivel viejo. Sobre lmg_wavelength_dataset fallo: la
  relajacion ocupaba el 25-34% de todas las filas, porque tras un gesto
  la senal tarda ~5 s en asentarse (compatible con hiperemia reactiva)
  y a menudo NO vuelve al nivel previo dentro de los 10 s del reposo,
  sino a uno nuevo por deriva. La base quedaba obsoleta, la deriva
  bastaba para superar el umbral y el onset salia en el borde de la
  ventana de busqueda (-998 ms) en buena parte de los bloques.

  Ahora cada periodo de reposo define SU PROPIA linea base con su tramo
  final, justo antes de la zona de anticipacion. Esa base sirve para dos
  cosas: la relajacion termina cuando la senal entra en su banda, y el
  onset del gesto siguiente se mide contra ella. Lo que importa para el
  onset es el nivel inmediatamente previo al movimiento, no el nivel de
  hace dos gestos.

CRITERIO DE ONSET:
  Con la base (media mu_c y desviacion sigma_c por canal, el S-barra-r
  de la calibracion) se define la desviacion multicanal

      D(t) = sqrt( mean_c ((x_c(t) - mu_c) / sigma_c)^2 )

  La media cuadratica de los z por canal es mas robusta que el maximo:
  con muchos canales, tomar el maximo multiplica los falsos positivos
  (comparaciones multiples), y el promedio simple diluye un gesto que
  solo mueve unos pocos canales.

  El onset es la primera muestra en que D(t) supera mu_D + k*sigma_D de
  forma sostenida durante al menos T ms, donde mu_D y sigma_D son la
  media y la desviacion de D sobre la propia base. Por defecto k = 3 y
  T = 50 ms, configurables. La busqueda empieza busqueda_previa_ms antes
  de la etiqueta, porque el movimiento puede adelantarse: el onset puede
  salir negativo, y eso se reporta como anticipacion.

  Cuando hay IMU se usa como confirmacion, con su propia base tomada de
  la MISMA ventana de reposo que la optica. Sin IMU (los datasets
  publicos de LMG no la tienen) solo cuenta la senal optica.

LAS DOS LINEAS BASE DE LA CAPTURA PROPIA (version 4):
  Inicio del gesto
    estatica   los base_ms finales del reposo previo, sin su ultimo
               recorte_reposo_fin_ms (2 s sin el ultimo segundo).
    dinamica   el ultimo base_preparacion_ms de la PREPARACION (1 s), con
               el brazo ya en la primera posicion y la mano relajada. La
               busqueda empieza en la indicacion, sin anticipacion. Con la
               base del reposo sobre la mesa, el cambio de postura movia
               la senal antes de la indicacion: en datos sinteticos el
               57% de las dinamicas daba un inicio negativo falso.
  Fin de la relajacion, en las dos condiciones
    la cola del PROPIO reposo en que ocurre (2 s sin el ultimo segundo),
    ya con el antebrazo sobre la mesa. Comparada en 10 sujetos
    sinteticos con deriva entre gestos, frente a la cola del reposo
    previo al gesto y frente al final de la preparacion, es la unica que
    no se resiente: 0 relajaciones sin detectar y p90 de 570 ms en las
    dinamicas, frente a 1 y 855 ms con el reposo previo y 8 y 891 ms con
    la preparacion.

BASE LOCAL O DE CALIBRACION (modo_base):
  "local"        (defecto) la base del reposo inmediatamente previo.
  "calibracion"  la del bloque de calibracion de la sesion (base_global),
                 que es el S-barra-r que calcula la calibracion.
  La especificacion original pedia la segunda. Se deja como opcion y no
  como defecto por la evidencia de arriba: una base de hace minutos es
  exactamente la base obsoleta con que fallo la version 1. La
  relajacion se mide SIEMPRE contra la base local; contra la de
  calibracion, con deriva, la senal podria no volver nunca a la banda y
  el reposo entero quedaria como relajacion. anotar_fases.py
  --comparar_bases cuantifica ambas sobre el piloto.

COTAS DE SANIDAD (se MARCAN, no se descartan):
  onset < 0         anticipacion: el movimiento empezo antes de la senal
  0 <= onset < 150  mas rapido que cualquier reaccion visual humana
  onset > 1000      participante distraido o gesto de baja amplitud
  base inestable    la senal aun derivaba en la ventana de base
"""

from dataclasses import dataclass, asdict
from typing import Optional

import numpy as np

# Cambiar este numero cuando cambie la logica: invalida las caches que
# guardan fases calculadas con una version anterior del detector.
FASES_VERSION = 4
# Version 4: en las repeticiones dinamicas, la base del INICIO es el
# ultimo segundo de la preparacion y la busqueda empieza en la indicacion.
# Version 3: con la columna bloque_tipo, la preparacion es un bloque propio
# que no entra al entrenamiento, el gesto empieza en la indicacion de
# contraccion, el reposo en movimiento es Reposo entero, y las filas de
# las repeticiones descartadas quedan con fase "descartada".

FASE_REACCION   = "reaccion"
FASE_DINAMICA   = "dinamica"
FASE_MESETA     = "meseta"
FASE_RELAJACION = "relajacion"
FASE_REPOSO     = "reposo"
FASE_RECORTE    = "recorte"
# Preparacion de la captura: el participante ve el gesto que viene pero
# todavia no lo hace. Nunca entra al entrenamiento.
FASE_PREPARACION = "preparacion"
# Filas de una repeticion que el operador descarto. Las pone
# anotar_fases.py, no este modulo, porque es un dato del CSV.
FASE_DESCARTADA = "descartada"

FASES_GESTO = (FASE_REACCION, FASE_DINAMICA, FASE_MESETA)


@dataclass
class ParametrosFases:
    """Todos los umbrales del detector, en un solo lugar."""
    k: float = 3.0                  # umbral en desviaciones de la base
    t_sostenido_ms: float = 50.0    # duracion minima por encima del umbral
    frac_meseta: float = 0.90       # la meseta empieza al 90% de su nivel
    onset_min_ms: float = 150.0     # por debajo: sospechoso
    onset_max_ms: float = 1000.0    # por encima: sospechoso
    # Recorte de bordes del reposo estable.
    # Inicio 500 ms: la relajacion ya se detecta por senal y absorbe el
    #   transitorio post-contraccion; esto es una guarda adicional.
    # Final 1000 ms: la anticipacion del siguiente gesto empieza antes de
    #   la senal visual. En lmg_wavelength_dataset la traza mediana ya sube
    #   a -250 ms y el 72% de las transiciones supera el 10% de su
    #   excursion en los ultimos 500 ms. Es el borde que mas contamina.
    recorte_reposo_ini_ms: float = 500.0
    recorte_reposo_fin_ms: float = 1000.0
    # Busqueda del onset desde antes de la etiqueta. Coincide con el
    # recorte final: la busqueda empieza donde termina la ventana de base.
    busqueda_previa_ms: float = 1000.0
    # Ventana de linea base: los base_ms previos al recorte final.
    base_ms: float = 2000.0
    base_min_ms: float = 500.0      # menos que esto no es una base fiable
    # Base del inicio en las repeticiones DINAMICAS: el final de la
    # preparacion, con el brazo ya en la primera posicion y la mano
    # relajada. La base del reposo previo, sobre la mesa, no sirve: el
    # cambio de postura mueve la senal optica antes de la indicacion, y
    # en datos sinteticos el 57% de las dinamicas salia con un inicio
    # negativo falso.
    base_preparacion_ms: float = 1000.0


@dataclass
class ResultadoOnset:
    idx_onset: Optional[int]        # indice relativo al inicio de la busqueda
    idx_meseta: Optional[int]
    onset_ms: Optional[float]       # relativo a la ETIQUETA; negativo = antes
    sospechoso: bool
    motivo: str = ""
    confirmado_imu: Optional[bool] = None
    anticipado: bool = False


def firma(p: "ParametrosFases") -> str:
    """Identificador de version + parametros, para claves de cache."""
    import hashlib
    txt = f"v{FASES_VERSION}:" + repr(sorted(asdict(p).items()))
    return f"v{FASES_VERSION}_" + hashlib.md5(txt.encode()).hexdigest()[:8]


def estadisticas_base(x_base: np.ndarray):
    """(mu_c, sigma_c, mu_D, sigma_D) sobre un tramo de reposo (N, C)."""
    mu = x_base.mean(axis=0)
    sd = x_base.std(axis=0)
    sd = np.where(sd < 1e-9, 1e-9, sd)
    D = desviacion(x_base, mu, sd)
    return mu, sd, float(D.mean()), float(max(D.std(), 1e-9))


def desviacion(x: np.ndarray, mu: np.ndarray, sd: np.ndarray) -> np.ndarray:
    """D(t) = media cuadratica de los z por canal. x: (N, C)."""
    z = (x - mu) / sd
    return np.sqrt(np.mean(z * z, axis=1))


def deriva_base(x_base: np.ndarray, base: tuple) -> float:
    """
    Cuanto se mueve D entre el primer y el ultimo cuarto de la ventana de
    base, en desviaciones de D. Una base todavia en relajacion deriva.
    """
    mu, sd, mu_D, sd_D = base
    D = desviacion(x_base, mu, sd)
    q = max(1, len(D) // 4)
    return float(abs(D[-q:].mean() - D[:q].mean()) / sd_D)


def _primer_sostenido(mascara: np.ndarray, n_min: int) -> Optional[int]:
    """Primer indice donde mascara es True durante n_min muestras seguidas."""
    if n_min <= 1:
        idx = np.flatnonzero(mascara)
        return int(idx[0]) if len(idx) else None
    corrida = 0
    for i, v in enumerate(mascara):
        corrida = corrida + 1 if v else 0
        if corrida >= n_min:
            return i - n_min + 1
    return None


def detectar_onset(x_busqueda: np.ndarray, base: tuple, fs: float,
                   p: ParametrosFases,
                   imu_busqueda: Optional[np.ndarray] = None,
                   imu_base: Optional[np.ndarray] = None,
                   offset_muestras: int = 0) -> ResultadoOnset:
    """
    Onset y comienzo de meseta de un gesto.

    x_busqueda empieza offset_muestras antes de la etiqueta; onset_ms se
    reporta relativo a la etiqueta, asi que un movimiento anticipado sale
    negativo.
    """
    mu, sd, mu_D, sd_D = base
    D = desviacion(x_busqueda, mu, sd)
    umbral = mu_D + p.k * sd_D
    n_min = max(1, int(round(p.t_sostenido_ms * fs / 1000.0)))

    i0 = _primer_sostenido(D > umbral, n_min)
    if i0 is None:
        return ResultadoOnset(None, None, None, True,
                              "sin onset: la senal no supera el umbral")
    onset_ms = 1000.0 * (i0 - offset_muestras) / fs

    # Meseta: primera muestra que alcanza frac_meseta del nivel sostenido,
    # estimado como la mediana de D en la segunda mitad de la busqueda.
    nivel = float(np.median(D[len(D) // 2:]))
    objetivo = mu_D + p.frac_meseta * (nivel - mu_D)
    rel = np.flatnonzero(D[i0:] >= objetivo)
    i_meseta = int(i0 + rel[0]) if len(rel) else i0

    motivos = []
    anticipado = onset_ms < 0
    if anticipado:
        motivos.append(f"onset a {onset_ms:.0f} ms: movimiento ANTES de la "
                       f"senal visual (anticipacion)")
    elif onset_ms < p.onset_min_ms:
        motivos.append(f"onset a {onset_ms:.0f} ms, antes de "
                       f"{p.onset_min_ms:.0f}: mas rapido que una reaccion "
                       f"visual humana")
    if onset_ms > p.onset_max_ms:
        motivos.append(f"onset a {onset_ms:.0f} ms, despues de "
                       f"{p.onset_max_ms:.0f}: posible distraccion")

    confirmado = None
    if imu_busqueda is not None and imu_base is not None:
        mu_i = imu_base.mean(axis=0)
        sd_i = np.where(imu_base.std(axis=0) < 1e-9, 1e-9,
                        imu_base.std(axis=0))
        Di = desviacion(imu_busqueda, mu_i, sd_i)
        Dbi = desviacion(imu_base, mu_i, sd_i)
        umb_i = Dbi.mean() + p.k * Dbi.std()
        ventana = slice(i0, min(len(Di), i0 + int(0.5 * fs)))
        confirmado = bool(np.any(Di[ventana] > umb_i))
        if not confirmado:
            motivos.append("la IMU no confirma movimiento en los 500 ms "
                           "posteriores al onset")

    return ResultadoOnset(i0, i_meseta, onset_ms, bool(motivos),
                          "; ".join(motivos), confirmado, anticipado)


def detectar_fin_relajacion(x_reposo: np.ndarray, base: tuple, fs: float,
                            p: ParametrosFases) -> int:
    """
    Indice relativo en que la senal entra de forma sostenida en la banda
    de la base. Si nunca entra, todo el periodo es relajacion.
    """
    mu, sd, mu_D, sd_D = base
    D = desviacion(x_reposo, mu, sd)
    n_min = max(1, int(round(p.t_sostenido_ms * fs / 1000.0)))
    i = _primer_sostenido(D <= mu_D + p.k * sd_D, n_min)
    return len(D) if i is None else int(i)


def _clase_de_bloque(tipo) -> str:
    """
    Agrupa el bloque_tipo de la captura en las cuatro clases de bloque que
    distingue el detector. La calibracion se trata como un periodo de
    reposo mas, que es lo que es.
    """
    return {"calibracion": "reposo", "reposo": "reposo",
            "preparacion": "preparacion", "contraccion": "gesto",
            "reposo_dinamico": "reposo_dinamico"}.get(str(tipo), "")


def etiquetar_fases(x: np.ndarray, etiquetas: np.ndarray, fs: float,
                    p: ParametrosFases = None,
                    etiqueta_reposo: int = 0,
                    imu: Optional[np.ndarray] = None,
                    base_global: Optional[tuple] = None,
                    imu_base_global: Optional[np.ndarray] = None,
                    modo_base: str = "local",
                    tipo: Optional[np.ndarray] = None,
                    dinamica: Optional[np.ndarray] = None):
    """
    Asigna una fase a cada muestra de una grabacion continua.

    base_global / imu_base_global: base de respaldo (y la unica en
    modo_base="calibracion"), p. ej. el bloque de calibracion.

    tipo: el bloque_tipo de cada muestra, si la grabacion es de la app de
    captura. Con el, los bloques se cortan tambien donde cambia el tipo,
    y eso permite tres cosas que la etiqueta sola no permite:

      - La PREPARACION es un bloque propio, con fase "preparacion", que
        nunca entra al entrenamiento. Lleva la etiqueta del gesto que
        anuncia, asi que sin el tipo quedaba unida a la contraccion en un
        solo bloque de 13 s: el inicio se buscaba desde el comienzo de la
        preparacion y, si el brazo se movia para colocarse, esas muestras
        con la mano relajada salian etiquetadas como gesto.
      - El gesto empieza en la indicacion de CONTRACCION, que es la
        referencia del tiempo de reaccion. La busqueda del inicio sigue
        empezando busqueda_previa_ms antes, dentro de la preparacion, para
        detectar la anticipacion.
      - El REPOSO EN MOVIMIENTO no pasa por el detector de inicio: sus
        10 s son Reposo completos. Lleva label Rest, asi que sin el tipo
        se fundia con los reposos de alrededor.

    Sin tipo, que es el caso de los datasets publicos, los bloques se
    cortan solo por la etiqueta, como en la version 2.

    dinamica: booleano por muestra, True en las repeticiones de la
    condicion dinamica. Con el, el INICIO de esos gestos se mide contra
    el ultimo segundo de su preparacion y se busca solo desde la
    indicacion, sin anticipacion. La RELAJACION no cambia en ninguna
    condicion: se mide siempre contra la cola de su propio reposo, que
    ya ocurre con el antebrazo sobre la mesa.

    Returns:
        fase: array de str, una por muestra
        informe: lista de dict, uno por bloque de gesto
    """
    if modo_base not in ("local", "calibracion"):
        raise ValueError(f"modo_base debe ser 'local' o 'calibracion', no {modo_base!r}")
    p = p or ParametrosFases()
    n = len(etiquetas)
    fase = np.empty(n, dtype=object)
    informe = []

    if tipo is not None:
        clase_muestra = np.array([_clase_de_bloque(t) for t in tipo], dtype=object)
        cambio = (np.diff(etiquetas) != 0) | (clase_muestra[1:] != clase_muestra[:-1])
        cambios = np.flatnonzero(cambio) + 1
    else:
        cambios = np.flatnonzero(np.diff(etiquetas) != 0) + 1
    limites = np.concatenate([[0], cambios, [n]])
    bloques = [(int(limites[i]), int(limites[i + 1]))
               for i in range(len(limites) - 1)]

    def clase(b):
        a = bloques[b][0]
        if tipo is not None and clase_muestra[a]:
            return clase_muestra[a]
        return "reposo" if etiquetas[a] == etiqueta_reposo else "gesto"

    clases = [clase(b) for b in range(len(bloques))]
    es_reposo = [c == "reposo" for c in clases]
    ms = lambda v: int(round(v * fs / 1000.0))          # noqa: E731
    rec_ini, rec_fin = ms(p.recorte_reposo_ini_ms), ms(p.recorte_reposo_fin_ms)
    n_base, n_base_min = ms(p.base_ms), ms(p.base_min_ms)

    # ---- 1. Base local de cada periodo de reposo: su tramo final ----
    bases, derivas, rangos = {}, {}, {}
    for b, (a, z) in enumerate(bloques):
        if not es_reposo[b]:
            continue
        fin_b = z - rec_fin
        ini_b = max(a, fin_b - n_base)
        if fin_b - ini_b >= n_base_min:
            bases[b] = estadisticas_base(x[ini_b:fin_b])
            derivas[b] = deriva_base(x[ini_b:fin_b], bases[b])
            rangos[b] = (ini_b, fin_b)

    # ---- 2. Preparacion y reposo en movimiento: sin deteccion ----
    for b, (a, z) in enumerate(bloques):
        if clases[b] == "preparacion":
            fase[a:z] = FASE_PREPARACION
        elif clases[b] == "reposo_dinamico":
            fase[a:z] = FASE_REPOSO

    # ---- 3. Periodos de reposo ----
    for b, (a, z) in enumerate(bloques):
        if not es_reposo[b]:
            continue
        # Hay relajacion si antes hubo un gesto o un reposo en movimiento:
        # en los dos casos la senal vuelve de un estado distinto.
        viene_de_gesto = b > 0 and clases[b - 1] in ("gesto", "reposo_dinamico")
        if not viene_de_gesto:
            i_rel = 0
        elif b in bases:
            i_rel = detectar_fin_relajacion(x[a:z], bases[b], fs, p)
        else:
            i_rel = z - a            # demasiado corto para asentarse
        fase[a:a + i_rel] = FASE_RELAJACION
        fase[a + i_rel:z] = FASE_REPOSO
        ini = a + i_rel
        if ini < z:
            fase[ini:min(z, ini + rec_ini)] = FASE_RECORTE
            fase[max(ini, z - rec_fin):z] = FASE_RECORTE

    # ---- 4. Bloques de gesto: inicio contra la base del reposo previo ----
    for b, (a, z) in enumerate(bloques):
        if clases[b] != "gesto":
            continue
        lab = int(etiquetas[a])
        # El reposo previo es el ultimo periodo de reposo antes del gesto,
        # saltando su preparacion.
        previo = b - 1
        while previo >= 0 and clases[previo] == "preparacion":
            previo -= 1
        previo = previo if previo >= 0 and es_reposo[previo] else None
        n_prep = ms(p.base_preparacion_ms)
        en_preparacion = (dinamica is not None and bool(dinamica[a])
                          and b > 0 and clases[b - 1] == "preparacion"
                          and a - bloques[b - 1][0] >= n_prep)
        if modo_base == "calibracion" and base_global is not None:
            base, deriva, imu_base = base_global, None, imu_base_global
            origen = "calibracion"
        elif en_preparacion:
            tramo = x[a - n_prep:a]
            base = estadisticas_base(tramo)
            deriva = deriva_base(tramo, base)
            imu_base = imu[a - n_prep:a] if imu is not None else None
            origen = "preparacion"
        else:
            base = bases.get(previo)
            deriva = derivas.get(previo)
            # La IMU se compara contra la MISMA ventana de reposo que la
            # optica.
            imu_base = (imu[slice(*rangos[previo])]
                        if imu is not None and previo in rangos else None)
            origen = "local"
            if base is None:
                base, imu_base = base_global, imu_base_global
                origen = "respaldo_global"
        if base is None:
            fase[a:z] = FASE_MESETA
            informe.append(dict(bloque=b, label=lab, inicio=a, fin=z,
                                onset_ms=None, anticipado=False,
                                dinamica_ms=None, sospechoso=True,
                                motivo="sin linea base previa",
                                confirmado_imu=None, deriva_base=None,
                                base=None))
            continue
        # Con la base en la preparacion no se busca antes de la
        # indicacion: esas muestras SON la base.
        pre = 0 if origen == "preparacion" else min(ms(p.busqueda_previa_ms), a)
        imu_b = imu[a - pre:z] if imu is not None else None
        r = detectar_onset(x[a - pre:z], base, fs, p, imu_b, imu_base,
                           offset_muestras=pre)
        if r.idx_onset is None:
            fase[a:z] = FASE_REACCION
        else:
            on, me = r.idx_onset - pre, r.idx_meseta - pre
            # Las muestras PREVIAS a la indicacion no se reetiquetan:
            # conservan su fase (preparacion o reposo). Darles la clase del
            # gesto seria fabricar etiquetas. Con inicio anticipado, el
            # bloque no tiene reaccion y la dinamica arranca en la propia
            # indicacion.
            on_c, me_c = max(on, 0), max(me, 0)
            fase[a:a + on_c] = FASE_REACCION
            fase[a + on_c:a + me_c] = FASE_DINAMICA
            fase[a + me_c:z] = FASE_MESETA
        motivo, sosp = r.motivo, r.sospechoso
        if deriva is not None and deriva > p.k:
            sosp = True
            motivo = "; ".join(filter(None, [
                motivo, f"base inestable (deriva {deriva:.1f} sigma_D)"]))
        informe.append(dict(
            bloque=b, label=lab, inicio=a, fin=z,
            onset_ms=r.onset_ms, anticipado=r.anticipado,
            dinamica_ms=(None if r.idx_onset is None else
                         1000.0 * (r.idx_meseta - r.idx_onset) / fs),
            sospechoso=sosp, motivo=motivo,
            confirmado_imu=r.confirmado_imu, deriva_base=deriva,
            base=origen,
        ))
    return fase, informe


# Variantes de la ablacion: que fases entran como la clase del gesto.
VARIANTES_ABLACION = {
    "solo_meseta":        (FASE_MESETA,),
    "dinamica_meseta":    (FASE_DINAMICA, FASE_MESETA),      # por defecto
    "todo_con_reaccion":  (FASE_REACCION, FASE_DINAMICA, FASE_MESETA),
}


def mascara_entrenamiento(fase: np.ndarray, etiquetas: np.ndarray,
                          variante: str = "dinamica_meseta",
                          etiqueta_reposo: int = 0) -> np.ndarray:
    """
    Filas que entran al entrenamiento segun la variante de la ablacion.
    El reposo entra solo con su fase estable; relajacion y recorte nunca
    se etiquetan como Rest.
    """
    fases_gesto = VARIANTES_ABLACION[variante]
    es_reposo = etiquetas == etiqueta_reposo
    return np.where(es_reposo, fase == FASE_REPOSO, np.isin(fase, fases_gesto))
