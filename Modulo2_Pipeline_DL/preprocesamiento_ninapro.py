"""
preprocesamiento_ninapro.py - Carga, remuestreo y ventaneo del dataset NinaPro DB5
==================================================================================
Protesis transradial - Validacion con dataset publico multimodal

ALCANCE DE ESTE ARCHIVO:
  Este modulo es la ruta de VALIDACION del pipeline, sobre el dataset
  publico NinaPro DB5 (senales sEMG). Es independiente de
  'preprocesamiento.py', que es la ruta de PRODUCCION sobre el CSV del
  hardware fisico (senales LMG opticas + acelerometro, ventana (20, 8)).

  Ambas rutas comparten la MISMA arquitectura de 'modelo.py'; solo
  cambian la forma de entrada y el origen de los datos:
    - Ruta LMG (produccion):  (20, 8)  a 100 Hz  <- preprocesamiento.py
    - Ruta EMG (validacion):  (40, 8)  a 200 Hz  <- este archivo

FLUJO COMPLETO:
  1. Carga archivos .mat de NinaPro DB5 (10 sujetos, ejercicios E1/E2/E3)
  2. Extrae EMG (16 canales, 200 Hz), ACC (6 canales, 200 Hz), restimulus,
     repetition y SUBJECT_ID (derivado del nombre del archivo)
  3. Selecciona solo los primeros 5 canales EMG y 3 canales ACC
     (simula el vector x(t) de 8 variables de la protesis fisica)
  4. Downsampling de ACC: 200 Hz -> 50 Hz (simula IMU MPU6050 real)
  5. Upsampling de ACC: 50 Hz -> 200 Hz (interpolacion lineal)
  6. Mapeo de etiquetas: de clases NinaPro a 5 gestos objetivo
  7. Ventana deslizante con early fusion (EMG + ACC concatenados)

TRAZABILIDAD DEL SUJETO:
  Cada ventana arrastra dos identificadores independientes:
    - grupos:  numero de repeticion (1..6), voto mayoritario en la ventana
    - sujetos: id del sujeto (1..10), constante dentro de cada archivo .mat

  Ambos se propagan por EXACTAMENTE la misma ruta y con las mismas
  operaciones de indexado, de modo que cualquier reordenamiento,
  filtrado o submuestreo los arrastra en conjunto con X e y. El punto
  critico es 'submuestrear_clase_0', que baraja indices: alli los cuatro
  arrays se indexan con el mismo vector 'idx_final'.

FUNDAMENTO MATEMATICO DE LA INTERPOLACION:
  El acelerometro en el hardware real muestrea a 50 Hz
  (T = 20 ms entre muestras). Para fusionarlo con EMG
  a 200 Hz (T = 5 ms), debemos reconstruir 3 muestras
  intermedias por cada muestra real.

  Interpolacion lineal entre (t0, a0) y (t1, a1):
    a(t*) = a0 + (a1 - a0) * (t* - t0) / (t1 - t0)

  Teorema de Nyquist-Shannon: la frecuencia de Nyquist del
  acelerometro es f_sample/2 = 25 Hz. Los gestos humanos
  tienen componentes frecuenciales <= 5 Hz, muy por debajo
  de 25 Hz, por lo que la senal se reconstruye sin aliasing.

CALCULO DE LA VENTANA DESLIZANTE:
  - Ventana: 200 ms a 200 Hz = 200 * 200 / 1000 = 40 muestras
  - Stride:  20 ms a 200 Hz =  20 * 200 / 1000 = 4 muestras
  - Solapamiento: (40 - 4) / 40 = 90%
"""

import re
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Tuple

# ============================================================
# CONSTANTES DEL SISTEMA
# ============================================================
# Simulacion del hardware fisico:
#   - 5 sensores LMG (opticos)  -> primeros 5 canales EMG
#   - 1 IMU (3 ejes)            -> primeros 3 canales ACC
CANALES_EMG = 5
CANALES_ACC = 3
CANALES_TOTAL = CANALES_EMG + CANALES_ACC  # 8 (early fusion)
TASA_ORIGINAL = 200       # Hz (frecuencia nativa de DB5)
TASA_ACC_BAJA = 50        # Hz (simula IMU MPU6050 real)
TASA_FINAL = 200          # Hz (despues de upsampling)

VENTANA_MS = 200
STRIDE_MS = 20
VENTANA_SAMPLES = int(VENTANA_MS * TASA_FINAL / 1000)   # 40
STRIDE_SAMPLES = int(STRIDE_MS * TASA_FINAL / 1000)      # 4

# Mapeos condicionales por ejercicio (archivo .mat):
#   E1 (Exercise A): solo Rest
#   E2 (Exercise B): Rest, Power, Finger_Ext
#   E3 (Exercise C): Rest, Pinch, Tripod
# Cada dict: {clase_tesis: [lista_de_IDs_originales_en_restimulus]}
MAPEO_E1 = {
    0: [0],    # Rest
}
MAPEO_E2 = {
    0: [0],    # Rest
    3: [6],    # Power   (6 en DB5 = fingers flexed in fist)
    4: [5],    # Finger_Ext (5 en DB5 = abduction of all fingers)
}
MAPEO_E3 = {
    0: [0],    # Rest
    1: [15],   # Pinch   (15 en DB5 = tip pinch)
    2: [13],   # Tripod  (13 en DB5 = tripod grasp)
}

NOMBRES_GESTOS = ["Rest", "Pinch", "Tripod", "Power", "Finger_Ext"]
NUM_CLASES = len(NOMBRES_GESTOS)  # 5

# Nombres de archivo de DB5: S<sujeto>_E<ejercicio>_A<adquisicion>.mat
PATRON_ARCHIVO = re.compile(r"^S(\d+)_E(\d+)_A(\d+)$", re.IGNORECASE)
# Nombre de carpeta por sujeto: s1, s2, ... s10
PATRON_CARPETA = re.compile(r"^s(\d+)$", re.IGNORECASE)


# ============================================================
# IDENTIFICACION DEL SUJETO A PARTIR DEL ARCHIVO DE ORIGEN
# ============================================================
def extraer_subject_id(ruta: Path) -> Tuple[int, int]:
    """
    Deriva (subject_id, exercise_id) del archivo .mat de origen.

    NinaPro DB5 nombra sus archivos como 'S<sujeto>_E<ejercicio>_A1.mat'
    (p.ej. S7_E3_A1.mat -> sujeto 7, ejercicio 3) y los agrupa en
    carpetas 's<sujeto>/'. Se prioriza el nombre del archivo y se usa la
    carpeta contenedora solo como respaldo.

    Esta funcion FALLA de forma ruidosa si no puede determinar el sujeto.
    Asignar un id incorrecto (o un placeholder) invalidaria por completo
    la particion por sujeto, que es justamente lo que este pipeline
    pretende medir.

    Args:
        ruta: Path al archivo .mat

    Returns:
        (subject_id, exercise_id)  ambos enteros; exercise_id = -1 si solo
        se pudo recuperar el sujeto desde la carpeta.

    Raises:
        ValueError: si el sujeto no se puede derivar del archivo.
    """
    m = PATRON_ARCHIVO.match(ruta.stem)
    if m is not None:
        return int(m.group(1)), int(m.group(2))

    # Respaldo: carpeta ancestro 's<n>' (DB5 anida como sN/sN/archivo.mat)
    for padre in ruta.parents:
        mp = PATRON_CARPETA.match(padre.name)
        if mp is not None:
            return int(mp.group(1)), -1

    raise ValueError(
        f"No se pudo derivar subject_id de '{ruta}'. Se esperaba un nombre "
        f"'S<n>_E<n>_A<n>.mat' o una carpeta ancestro 's<n>'. Continuar "
        f"seria invalidar la particion por sujeto."
    )


# ============================================================
# CARGA DE ARCHIVOS .MAT DE NINAPRO DB5
# ============================================================
class CargadorNinaProDB5:
    """
    Busca y carga los archivos .mat del dataset NinaPro DB5.

    Estructura real de cada archivo:
      - emg:         (N, 16)  float32  -- 16 canales sEMG a 200 Hz
      - acc:         (N, 6)   float32  -- 6 canales ACC (2 Myo x 3 ejes)
                                           ya alineados a 200 Hz
      - restimulus:  (N, 1)   int8     -- etiquetas corregidas (0..41)
      - repetition:  (N, 1)   int8     -- numero de repeticion (1..6)

    El subject_id NO vive dentro del .mat: se deriva del nombre del
    archivo (ver 'extraer_subject_id') y se adjunta a cada muestra.

    Se procesan todos los archivos .mat del dataset; el filtro por
    etiquetas ocurre a nivel de filas via RESTIMULUS, usando el
    diccionario de mapeo del ejercicio para conservar solo las 5 clases
    objetivo y descartar automaticamente el resto.
    """

    def __init__(self, ruta_dataset: str):
        self.ruta = Path(ruta_dataset)
        # Busca todos los archivos .mat recursivamente
        self.archivos = sorted(self.ruta.glob("**/*.mat"))
        if not self.archivos:
            self.archivos = sorted(self.ruta.glob("**/*.MAT"))
        print(f"[NINAPRO] Archivos .mat encontrados: {len(self.archivos)}")
        if self.archivos:
            print(f"[NINAPRO] Primer archivo: {self.archivos[0].name}")
            print(f"[NINAPRO] Ultimo archivo: {self.archivos[-1].name}")

    def _cargar_mat(self, ruta: Path) -> dict:
        """Carga .mat (v5/v7 con scipy, v7.3 con h5py)."""
        import scipy.io as sio
        try:
            return sio.loadmat(str(ruta))
        except NotImplementedError:
            return self._cargar_mat_h5py(ruta)
        except Exception as e:
            raise RuntimeError(f"Error al cargar {ruta}: {e}")

    def _cargar_mat_h5py(self, ruta: Path) -> dict:
        """Carga .mat v7.3 con h5py y transpone arrays 2D."""
        import h5py
        datos = {}
        with h5py.File(str(ruta), "r") as f:
            for clave in f.keys():
                arr = np.array(f[clave])
                datos[clave] = arr.T if arr.ndim == 2 else arr.squeeze()
        return datos

    def extraer_sujeto(self, datos: dict):
        """
        Extrae EMG, ACC, restimulus y repetition del dict toplevel.

        Las variables en NinaPro DB5 estan en el nivel superior del .mat
        (no anidadas en structs).

        Retorna:
            emg: (N, 16)  float64  -- todos los canales
            acc: (N, 6)   float64  -- todos los canales
            labels: (N,)  int64    -- etiquetas restimulus
            repetition: (N,) int64 -- numero de repeticion (1..6)
        """
        if "emg" not in datos or "acc" not in datos:
            claves = [k for k in datos.keys() if not k.startswith("__")]
            raise KeyError(
                "No se encontraron 'emg' y 'acc' en el .mat. "
                f"Claves disponibles: {claves[:15]}"
            )

        emg = np.asarray(datos["emg"], dtype=np.float64)
        acc = np.asarray(datos["acc"], dtype=np.float64)

        # Labels: restimulus (corregido) con fallback a stimulus
        labels = datos.get("restimulus", datos.get("stimulus"))
        if labels is None:
            raise KeyError("No se encontro 'restimulus' ni 'stimulus'.")
        labels = np.asarray(labels, dtype=np.int64).ravel()

        # Repeticion: grupo del esquema de validacion original
        repetition = datos.get("repetition")
        if repetition is None:
            raise KeyError("No se encontro 'repetition' en el .mat.")
        repetition = np.asarray(repetition, dtype=np.int64).ravel()

        # Expandir 1D a 2D si es necesario
        if emg.ndim == 1:
            emg = emg.reshape(-1, 1)
        if acc.ndim == 1:
            acc = acc.reshape(-1, 1)

        return emg, acc, labels, repetition

    def cargar_todos(self) -> list:
        """
        Carga todos los archivos .mat encontrados.

        Retorna lista de tuplas
        (emg_raw, acc_raw, labels, repetition, subject_id, exercise_id).
        emg_raw tiene 16 canales, acc_raw tiene 6 canales.

        El subject_id se deriva del archivo ANTES de cargarlo, de modo que
        un archivo con nombre no reconocible aborta la corrida en vez de
        entrar al dataset sin identificar.
        """
        sujetos = []
        for ruta in self.archivos:
            # Derivar identidad ANTES de leer: si falla, es un error duro
            subject_id, exercise_id = extraer_subject_id(ruta)
            try:
                datos = self._cargar_mat(ruta)
                emg, acc, labels, repetition = self.extraer_sujeto(datos)
                sujetos.append(
                    (emg, acc, labels, repetition, subject_id, exercise_id)
                )
                clases_unicas = sorted(np.unique(labels))
                reps_unicas = sorted(np.unique(repetition))
                print(f"  [{ruta.name}] sujeto={subject_id} "
                      f"ejercicio=E{exercise_id} "
                      f"{emg.shape[0]} muestras, "
                      f"EMG={emg.shape[1]}ch, ACC={acc.shape[1]}ch, "
                      f"clases={clases_unicas}, reps={reps_unicas}")
            except Exception as e:
                print(f"  [!] Error en {ruta.name}: {e}")
        return sujetos


# ============================================================
# SELECCION DE CANALES (simula hardware fisico)
# ============================================================
def seleccionar_canales(
    emg: np.ndarray,
    acc: np.ndarray,
    n_emg: int = CANALES_EMG,
    n_acc: int = CANALES_ACC,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Selecciona los primeros canales para simular el hardware real.

    La protesis fisica tiene:
      - 5 sensores LMG (opticos)  -> primeros 5 de 16 canales EMG
      - 1 IMU (3 ejes)            -> primeros 3 de 6 canales ACC

    Esto reduce la dimensionalidad de (16+6=22) a (5+3=8), alineado con
    el vector x(t) del sistema real.
    """
    emg_sel = emg[:, :n_emg].copy()
    acc_sel = acc[:, :n_acc].copy()
    print(f"[CANALES] EMG: {emg.shape[1]} -> {emg_sel.shape[1]} | "
          f"ACC: {acc.shape[1]} -> {acc_sel.shape[1]}")
    return emg_sel, acc_sel


# ============================================================
# REMUESTREO DEL ACELEROMETRO (200 -> 50 -> 200 Hz)
# ============================================================
def remuestrear_acelerometro(
    acc: np.ndarray,
    tasa_origen: int = TASA_ORIGINAL,
    tasa_intermedia: int = TASA_ACC_BAJA,
    tasa_destino: int = TASA_FINAL,
) -> np.ndarray:
    """
    Simula un acelerometro lento (50 Hz) y lo reinterpola a 200 Hz.

    LOGICA MATEMATICA:
      El ACC en DB5 viene a 200 Hz, pero nuestro hardware final (MPU6050)
      entrega datos a 50 Hz. Para validar el pipeline de fusion, primero
      DIEZMAMOS la senal (tomamos 1 de cada 4 muestras, simulando el IMU
      real) y luego la REINTERPOLAMOS a 200 Hz mediante interpolacion
      lineal.

      La interpolacion lineal entre dos puntos conocidos (t0, a0) y
      (t1, a1) para encontrar a(t*) en t* = t0 + k*Delta_t es:

        a(t*) = a0 + (a1 - a0) * (t* - t0) / (t1 - t0)

      donde Delta_t = 5 ms (200 Hz) y k = 1, 2, 3.

      El Teorema de Nyquist garantiza que frecuencias <= 25 Hz se
      reconstruyen sin aliasing. Los gestos humanos tienen energia
      concentrada por debajo de 5 Hz, muy por debajo del limite de
      Nyquist, por lo que la reconstruccion lineal es matematicamente
      valida.

    Pasos:
      1. Diezmar: acc_200hz[::4, :] -> acc_50hz
      2. Reindexar a grilla fina 200 Hz (indices 0,1,2,3,...)
      3. Interpolar linealmente los NaN generados
      4. Asegurar longitud final igual a la original

    Args:
        acc: Array original (N, canales) a 200 Hz
        tasa_origen: Frecuencia original (200 Hz)
        tasa_intermedia: Frecuencia intermedia (50 Hz)
        tasa_destino: Frecuencia final (200 Hz)

    Returns:
        acc_reconstruido: (N, canales) a 200 Hz
    """
    factor_diezmado = tasa_origen // tasa_intermedia  # 4

    # Paso 1: Diezmar (downsampling) para simular ACC lento
    acc_lento = acc[::factor_diezmado, :].copy()
    n_lento = acc_lento.shape[0]
    n_canales = acc.shape[1]
    n_original = acc.shape[0]

    # Paso 2: Crear grillas con indices enteros
    # Cada unidad del indice = 1/200 s = 5 ms
    indices_lentos = np.arange(0, n_lento * factor_diezmado, factor_diezmado)
    n_total = n_lento * factor_diezmado
    indices_finos = np.arange(n_total)

    # Paso 3: DataFrame con muestras conocidas y reindexar
    df_lento = pd.DataFrame(
        acc_lento,
        index=indices_lentos,
        columns=range(n_canales),
    )
    df_fino = df_lento.reindex(indices_finos)

    # Paso 4: Interpolacion lineal para llenar NaN
    df_interp = df_fino.interpolate(method="linear", limit_area="inside")

    # Rellenar bordes si quedaron NaN
    if df_interp.isna().any().any():
        df_interp = df_interp.bfill().ffill()

    acc_reconstruido = df_interp.values.astype(np.float64)

    # Asegurar misma longitud que el original
    if acc_reconstruido.shape[0] != n_original:
        if acc_reconstruido.shape[0] > n_original:
            acc_reconstruido = acc_reconstruido[:n_original]
        else:
            acc_reconstruido = np.pad(
                acc_reconstruido,
                ((0, n_original - acc_reconstruido.shape[0]), (0, 0)),
                mode="edge",
            )

    return acc_reconstruido


# ============================================================
# MAPEO DE ETIQUETAS (12+ clases -> 5 clases objetivo)
# ============================================================
def mapear_etiquetas(
    labels: np.ndarray,
    mapeo: dict = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Mapea las etiquetas originales de NinaPro DB5 a las 5 clases objetivo.
    Descarta las muestras con etiquetas no incluidas en el mapeo.

    Args:
        labels: Array (N,) con etiquetas originales (0..41)
        mapeo: Dict {clase_destino: [lista_de_ids_origen]}

    Returns:
        mask: Booleano (N,) -> True para muestras a conservar
        labels_mapeadas: (N,) con etiquetas reasignadas {0..4}
                          o -1 para las descartadas
    """
    if mapeo is None:
        mapeo = MAPEO_E1

    # Tabla inversa: id_original -> clase_destino
    tabla = {}
    for clase_dest, ids_origen in mapeo.items():
        for id_orig in ids_origen:
            tabla[id_orig] = clase_dest

    labels_out = np.full(labels.shape, -1, dtype=np.int64)
    mask = np.zeros(labels.shape, dtype=bool)

    for id_orig, clase_dest in tabla.items():
        idx = labels == id_orig
        mask[idx] = True
        labels_out[idx] = clase_dest

    print(f"[MAPEO] Muestras conservadas: {mask.sum()} / {len(labels)} "
          f"({100 * mask.sum() / len(labels):.1f}%)")

    return mask, labels_out


# ============================================================
# VENTANA DESLIZANTE CON EARLY FUSION
# ============================================================
class SlidingWindowNinaPro:
    """
    Construye ventanas deslizantes fusionando EMG + ACC.

    CALCULO DE MUESTRAS POR VENTANA:
      window_size = window_size_ms * sampling_rate_hz / 1000
                  = 200 * 200 / 1000 = 40 muestras

      stride = stride_ms * sampling_rate_hz / 1000
             = 20 * 200 / 1000 = 4 muestras

    EARLY FUSION:
      Cada ventana concatena los canales de EMG (5) y ACC (3) en el eje
      de features, produciendo un vector de 8 canales. Esto permite que
      las capas Conv1D aprendan correlaciones espaciotemporales entre
      ambas modalidades desde la entrada.
    """

    def __init__(
        self,
        window_size_samples: int = VENTANA_SAMPLES,
        stride_samples: int = STRIDE_SAMPLES,
    ):
        self.window_size = window_size_samples
        self.stride = stride_samples

    def generar_ventanas(
        self, emg: np.ndarray, acc: np.ndarray, labels: np.ndarray,
        repetition: np.ndarray, subject_id: int,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Aplica ventana deslizante con early fusion.

        Args:
            emg: (N, 5)  sEMG (5 canales LMG simulados) a 200 Hz
            acc: (N, 3)  ACC reconstruido (3 ejes IMU) a 200 Hz
            labels: (N,) etiquetas mapeadas (0-4)
            repetition: (N,) numero de repeticion (1..6)
            subject_id: id del sujeto del archivo .mat de origen

        Returns:
            X: (ventanas, 40, 8)  early fusion EMG+ACC
            y: (ventanas, 5)      one-hot encoding
            grupos: (ventanas,)   id de repeticion
            sujetos: (ventanas,)  id de sujeto

        'sujetos' se rellena DENTRO del mismo bucle que 'grupos' (y no con
        un np.full a posteriori) para que comparta exactamente el mismo
        camino de aceptacion/descarte de ventanas: si el bucle salta una
        ventana, los cuatro arrays la saltan juntos.
        """
        n = emg.shape[0]

        # Early fusion: concatenar EMG y ACC en el eje de canales
        # fusion: (N, 8) = [EMG_0..EMG_4, ACC_0..ACC_2]
        fusion = np.concatenate([emg, acc], axis=1).astype(np.float32)

        ventanas_X = []
        ventanas_y = []
        ventanas_grupos = []
        ventanas_sujetos = []

        for inicio in range(0, n - self.window_size + 1, self.stride):
            fin = inicio + self.window_size

            # Etiqueta por voto mayoritario dentro de la ventana
            etiquetas_en_ventana = labels[inicio:fin]
            etiquetas_validas = etiquetas_en_ventana[etiquetas_en_ventana >= 0]
            if len(etiquetas_validas) == 0:
                continue
            etiqueta = np.bincount(etiquetas_validas).argmax()

            ventanas_X.append(fusion[inicio:fin])
            ventanas_y.append(etiqueta)

            # Grupo (repetition) por voto mayoritario dentro de la ventana
            rep_en_ventana = repetition[inicio:fin]
            rep_validas = rep_en_ventana[etiquetas_en_ventana >= 0]
            if len(rep_validas) == 0:
                rep_validas = rep_en_ventana
            grupo = int(np.bincount(rep_validas).argmax())
            ventanas_grupos.append(grupo)

            # Sujeto: constante dentro del archivo, pero se anexa aqui para
            # quedar indexado 1:1 con la ventana efectivamente aceptada.
            ventanas_sujetos.append(int(subject_id))

        if len(ventanas_X) == 0:
            raise ValueError(
                "No se generaron ventanas. Verifique la longitud de los datos "
                f"(n={n}, window_size={self.window_size})."
            )

        X = np.array(ventanas_X, dtype=np.float32)
        y = np.array(ventanas_y, dtype=np.int32)
        y_onehot = np.eye(NUM_CLASES, dtype=np.float32)[y]
        grupos = np.array(ventanas_grupos, dtype=np.int32)
        sujetos = np.array(ventanas_sujetos, dtype=np.int32)

        assert X.shape[0] == y_onehot.shape[0] == grupos.shape[0] == sujetos.shape[0], (
            f"Desalineacion tras ventaneo: X={X.shape[0]} y={y_onehot.shape[0]} "
            f"grupos={grupos.shape[0]} sujetos={sujetos.shape[0]}"
        )

        print(f"[VENTANEO] Dataset generado:")
        print(f"  Ventanas totales: {X.shape[0]}")
        print(f"  X: {X.shape}  (ventanas, pasos, canales)")
        print(f"  y: {y_onehot.shape}  (ventanas, clases)")
        clases, counts = np.unique(y, return_counts=True)
        dist = {NOMBRES_GESTOS[c]: int(counts[i])
                for i, c in enumerate(clases)}
        print(f"  Distribucion: {dist}")
        print(f"  Grupos (repeticiones): {sorted(np.unique(grupos).tolist())}")
        print(f"  Sujeto: {sorted(np.unique(sujetos).tolist())}")

        return X, y_onehot, grupos, sujetos


# Alias de compatibilidad con el nombre historico del preprocesador.
SlidingWindowPreprocessor = SlidingWindowNinaPro


# ============================================================
# SUB-MUESTREO (Random Undersampling) PARA BALANCEAR CLASES
# ============================================================
def submuestrear_clase_0(
    X: np.ndarray,
    y: np.ndarray,
    grupos: np.ndarray = None,
    sujetos: np.ndarray = None,
    random_state: int = 42,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Reduce aleatoriamente la clase 0 (Rest) para balancear el dataset.

    El desbalance es critico: clase 0 (reposo) suele tener ~40x mas
    muestras que las clases activas. Si no se corrige, el modelo aprende
    a predecir siempre 'Rest' y obtiene ~95% de accuracy sin aprender
    ningun gesto.

    Estrategia:
      1. Cuenta las muestras de las 4 clases activas (1..4)
      2. Calcula el promedio: target = (count_1+count_2+count_3+count_4)/4
      3. Selecciona aleatoriamente 'target' muestras de la clase 0
      4. Combina con todas las muestras de las clases 1..4

    PUNTO CRITICO DE TRAZABILIDAD:
      Esta es la unica operacion del pipeline que BARAJA el dataset.
      X, y, grupos y sujetos se indexan los cuatro con el MISMO vector
      'idx_final', de modo que la correspondencia ventana <-> sujeto
      sobrevive intacta. La secuencia de llamadas al RNG es identica a la
      version original (choice + shuffle, semilla 42), por lo que el
      subconjunto de Rest seleccionado es exactamente el mismo y los
      resultados siguen siendo comparables.

    Args:
        X: (N, 40, 8)  ventanas de features
        y: (N, 5)      one-hot encoding
        grupos: (N,)    grupos de repeticion (opcional)
        sujetos: (N,)   ids de sujeto (opcional)
        random_state: Semilla para reproducibilidad

    Returns:
        X_bal, y_bal, grupos_bal, sujetos_bal
    """
    rng = np.random.RandomState(random_state)
    y_int = y.argmax(axis=1)

    if grupos is not None:
        assert len(grupos) == len(y), (
            f"grupos ({len(grupos)}) no alinea con y ({len(y)}) "
            f"antes del submuestreo"
        )
    if sujetos is not None:
        assert len(sujetos) == len(y), (
            f"sujetos ({len(sujetos)}) no alinea con y ({len(y)}) "
            f"antes del submuestreo"
        )

    idx_clase_0 = np.where(y_int == 0)[0]
    n_0_original = len(idx_clase_0)

    # Contar clases activas
    counts = {}
    for c in range(1, NUM_CLASES):
        counts[c] = int((y_int == c).sum())
        print(f"  Count clase {c} ({NOMBRES_GESTOS[c]}): {counts[c]}")

    # Promedio de las clases activas
    target = int(np.mean(list(counts.values())))
    print(f"  Promedio clases 1-4: {target}")

    vacio = np.array([], dtype=np.int32)

    # Si clase 0 ya es menor o igual al target, no submuestrear
    if n_0_original <= target:
        print(f"  [SUB-MUESTREO] Clase 0 ({n_0_original}) <= target ({target}), "
              f"no se aplica sub-muestreo.")
        return (
            X,
            y,
            grupos if grupos is not None else vacio,
            sujetos if sujetos is not None else vacio,
        )

    # Submuestrear clase 0
    idx_0_sel = rng.choice(idx_clase_0, size=target, replace=False)
    idx_otras = np.where(y_int >= 1)[0]
    idx_final = np.concatenate([idx_0_sel, idx_otras])
    rng.shuffle(idx_final)

    X_bal = X[idx_final]
    y_bal = y[idx_final]
    grupos_bal = grupos[idx_final] if grupos is not None else vacio
    sujetos_bal = sujetos[idx_final] if sujetos is not None else vacio

    print(f"  [SUB-MUESTREO] Clase 0: {n_0_original} -> {target} "
          f"(reducidas en {n_0_original - target})")
    print(f"  [SUB-MUESTREO] Dataset balanceado: {len(idx_final)} ventanas")

    return X_bal, y_bal, grupos_bal, sujetos_bal


# ============================================================
# ORQUESTADOR PRINCIPAL
# ============================================================
def cargar_procesar_dataset(
    ruta_dataset: str,
    ventana_ms: int = VENTANA_MS,
    stride_ms: int = STRIDE_MS,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Orquesta la carga y preprocesamiento de todo NinaPro DB5.

    El mapeo de etiquetas es CONDICIONAL segun el archivo:
      - E1 (Exercise A): solo Rest (0)
      - E2 (Exercise B): Rest(0), Power(6->3), Finger_Ext(5->4)
      - E3 (Exercise C): Rest(0), Pinch(15->1), Tripod(13->2)
    Cualquier fila con restimulus fuera de estos rangos se descarta.

    Flujo por cada archivo .mat:
      1. Derivar subject_id / exercise_id del nombre del archivo
      2. Cargar EMG (16ch), ACC (6ch), restimulus, repetition
      3. Seleccionar canales: EMG[:5], ACC[:3]
      4. Seleccionar mapeo segun el ejercicio (E1/E2/E3)
      5. Mapear y filtrar filas (descarta las no mapeadas)
      6. Remuestrear ACC (200 -> 50 -> 200 Hz)
      7. Ventana deslizante con early fusion (8 canales)
      8. Asignar a cada ventana su repeticion y su sujeto
      9. Acumular ventanas de todos los archivos
     10. Sub-muestreo aleatorio de clase 0 (Rest) para balancear

    Args:
        ruta_dataset: Directorio con los archivos .mat
        ventana_ms: Tamano de ventana en ms
        stride_ms: Stride en ms

    Returns:
        X: (total_ventanas, 40, 8)
        y: (total_ventanas, 5)  one-hot
        grupos: (total_ventanas,)  id de repeticion
        sujetos: (total_ventanas,) id de sujeto
    """
    cargador = CargadorNinaProDB5(ruta_dataset)
    archivos_cargados = cargador.cargar_todos()

    if not archivos_cargados:
        raise FileNotFoundError(
            f"No se encontraron archivos .mat validos en {ruta_dataset}"
        )

    todas_X = []
    todas_y = []
    todas_grupos = []
    todos_sujetos = []

    for idx, (emg_raw, acc_raw, labels, repetition, subject_id, exercise_id) \
            in enumerate(archivos_cargados):
        nombre_archivo = cargador.archivos[idx].name
        print(f"\n{'='*50}")
        print(f"PROCESANDO {nombre_archivo} "
              f"({idx + 1}/{len(archivos_cargados)}) "
              f"[sujeto {subject_id}]")

        # Seleccionar mapeo segun el ejercicio (E1, E2, E3)
        if "E2" in nombre_archivo:
            mapeo_actual = MAPEO_E2
            print(f"  [MAPEO] Exercise B: Rest(0), Power(6->3), Finger_Ext(5->4)")
        elif "E3" in nombre_archivo:
            mapeo_actual = MAPEO_E3
            print(f"  [MAPEO] Exercise C: Rest(0), Pinch(15->1), Tripod(13->2)")
        else:  # E1 u otros
            mapeo_actual = MAPEO_E1
            print(f"  [MAPEO] Exercise A: solo Rest(0)")

        # Paso 1: Seleccionar canales (simular hardware fisico)
        emg, acc = seleccionar_canales(emg_raw, acc_raw)

        # Paso 2: Mapear etiquetas segun el ejercicio y filtrar
        mask, labels_mapeadas = mapear_etiquetas(labels, mapeo_actual)

        if mask.sum() == 0:
            print("  [!] Sin muestras de las clases objetivo, saltando.")
            continue

        emg = emg[mask]
        acc = acc[mask]
        labels_filtradas = labels_mapeadas[mask]
        rep_filtrada = repetition[mask]
        print(f"  Muestras utiles: {len(labels_filtradas)}")

        # Paso 3: Remuestrear acelerometro (200 -> 50 -> 200 Hz)
        print(f"  Remuestreo ACC: 200 -> 50 -> 200 Hz...")
        acc_reconstruido = remuestrear_acelerometro(
            acc,
            tasa_origen=TASA_ORIGINAL,
            tasa_intermedia=TASA_ACC_BAJA,
            tasa_destino=TASA_FINAL,
        )

        assert emg.shape[0] == acc_reconstruido.shape[0] == labels_filtradas.shape[0] == rep_filtrada.shape[0], \
            f"Desalineacion: EMG {emg.shape}, ACC {acc_reconstruido.shape}, Labels {labels_filtradas.shape}, Rep {rep_filtrada.shape}"

        # Paso 4: Ventana deslizante con early fusion
        preproc = SlidingWindowNinaPro(
            window_size_samples=int(ventana_ms * TASA_FINAL / 1000),
            stride_samples=int(stride_ms * TASA_FINAL / 1000),
        )

        X_sujeto, y_sujeto, grupos_sujeto, ids_sujeto = preproc.generar_ventanas(
            emg, acc_reconstruido, labels_filtradas, rep_filtrada, subject_id
        )

        # El sujeto es constante dentro del archivo: si aqui aparece mas de
        # un valor, la propagacion se rompio.
        assert set(np.unique(ids_sujeto).tolist()) == {subject_id}, (
            f"El archivo {nombre_archivo} produjo sujetos "
            f"{np.unique(ids_sujeto).tolist()}, se esperaba solo {subject_id}"
        )

        todas_X.append(X_sujeto)
        todas_y.append(y_sujeto)
        todas_grupos.append(grupos_sujeto)
        todos_sujetos.append(ids_sujeto)

    if not todas_X:
        raise RuntimeError(
            "No se generaron ventanas. Verifique que los archivos .mat "
            "contengan las clases requeridas (E1={0}, E2={0,5,6}, E3={0,13,15})."
        )

    X_total = np.concatenate(todas_X, axis=0)
    y_total = np.concatenate(todas_y, axis=0)
    grupos_total = np.concatenate(todas_grupos, axis=0)
    sujetos_total = np.concatenate(todos_sujetos, axis=0)

    assert X_total.shape[0] == y_total.shape[0] == grupos_total.shape[0] == sujetos_total.shape[0], \
        "Desalineacion al concatenar los archivos"

    # Aplicar sub-muestreo para balancear la clase 0 (Rest)
    print(f"\n{'='*50}")
    print("SUB-MUESTREO: Balanceando clase 0 (Rest)")
    print("=" * 50)
    X_total, y_total, grupos_total, sujetos_total = submuestrear_clase_0(
        X_total, y_total, grupos_total, sujetos_total
    )

    assert X_total.shape[0] == y_total.shape[0] == grupos_total.shape[0] == sujetos_total.shape[0], \
        "Desalineacion tras el submuestreo de Rest"

    print(f"\n{'='*50}")
    print("DATASET FINAL")
    print(f"  X: {X_total.shape}")
    print(f"  y: {y_total.shape}")
    for i, nombre in enumerate(NOMBRES_GESTOS):
        count = (y_total[:, i] == 1).sum()
        print(f"    {nombre}: {count} ({100*count/y_total.shape[0]:.1f}%)")
    print(f"  Grupos de repeticion: {sorted(np.unique(grupos_total).tolist())}")
    print(f"  Sujetos: {sorted(np.unique(sujetos_total).tolist())}")
    print(f"  Ventanas por sujeto:")
    for s in sorted(np.unique(sujetos_total).tolist()):
        n_s = int((sujetos_total == s).sum())
        print(f"    Sujeto {s:>2}: {n_s:>6} ventanas "
              f"({100*n_s/len(sujetos_total):.1f}%)")

    return X_total, y_total, grupos_total, sujetos_total


if __name__ == "__main__":
    import sys
    ruta = sys.argv[1] if len(sys.argv) > 1 else "./NinaPro_DB5"
    print("=" * 60)
    print("PREPROCESAMIENTO NINAPRO DB5")
    print("=" * 60)
    X, y, grupos, sujetos = cargar_procesar_dataset(ruta)
    print(f"\n[OK] Dataset listo: {X.shape[0]} ventanas, "
          f"{X.shape[1]} pasos, {X.shape[2]} canales, "
          f"{len(np.unique(grupos))} grupos de repeticion, "
          f"{len(np.unique(sujetos))} sujetos.")
