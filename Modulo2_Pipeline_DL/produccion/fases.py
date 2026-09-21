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
FASES_VERSION = 2

FASE_REACCION   = "reaccion"
FASE_DINAMICA   = "dinamica"
FASE_MESETA     = "meseta"
FASE_RELAJACION = "relajacion"
FASE_REPOSO     = "reposo"
FASE_RECORTE    = "recorte"

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


def etiquetar_fases(x: np.ndarray, etiquetas: np.ndarray, fs: float,
                    p: ParametrosFases = None,
                    etiqueta_reposo: int = 0,
                    imu: Optional[np.ndarray] = None,
                    base_global: Optional[tuple] = None,
                    imu_base_global: Optional[np.ndarray] = None,
                    modo_base: str = "local"):
    """
    Asigna una fase a cada muestra de una grabacion continua.

    base_global / imu_base_global: base de respaldo (y la unica en
    modo_base="calibracion"), p. ej. el bloque de calibracion.

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

    cambios = np.flatnonzero(np.diff(etiquetas) != 0) + 1
    limites = np.concatenate([[0], cambios, [n]])
    bloques = [(int(limites[i]), int(limites[i + 1]))
               for i in range(len(limites) - 1)]
    es_reposo = [etiquetas[a] == etiqueta_reposo for a, _ in bloques]

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

    # ---- 2. Periodos de reposo ----
    for b, (a, z) in enumerate(bloques):
        if not es_reposo[b]:
            continue
        viene_de_gesto = b > 0 and not es_reposo[b - 1]
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

    # ---- 3. Bloques de gesto: onset contra la base del reposo previo ----
    for b, (a, z) in enumerate(bloques):
        if es_reposo[b]:
            continue
        lab = int(etiquetas[a])
        previo = b - 1 if b > 0 and es_reposo[b - 1] else None
        if modo_base == "calibracion" and base_global is not None:
            base, deriva, imu_base = base_global, None, imu_base_global
            origen = "calibracion"
        else:
            base = bases.get(previo)
            deriva = derivas.get(previo)
            # La IMU se compara contra la MISMA ventana de reposo que la
            # optica. Antes se pasaba None y la confirmacion no se
            # calculaba nunca.
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

        pre = min(ms(p.busqueda_previa_ms), a)
        imu_b = imu[a - pre:z] if imu is not None else None
        r = detectar_onset(x[a - pre:z], base, fs, p, imu_b, imu_base,
                           offset_muestras=pre)

        if r.idx_onset is None:
            fase[a:z] = FASE_REACCION
        else:
            on, me = r.idx_onset - pre, r.idx_meseta - pre
            # Las muestras PREVIAS a la etiqueta no se reetiquetan: el
            # dataset las marco como reposo y el recorte final del reposo
            # ya las excluye de Rest. Darles la clase del gesto seria
            # fabricar etiquetas. Con onset anticipado, el bloque no
            # tiene reaccion y la dinamica arranca en la propia etiqueta.
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
