"""
preprocesamiento.py - Carga, remuestreo y ventaneo del dataset NinaPro DB5
===========================================================================
Protesis transradial - Validacion con dataset publico multimodal

FLUJO COMPLETO:
  1. Carga archivos .mat de NinaPro DB5 (solo ejercicio E1, 10 sujetos)
  2. Extrae EMG (16 canales, 200 Hz), ACC (6 canales, 200 Hz) y restimulus
  3. Selecciona solo los primeros 5 canales EMG y 3 canales ACC
     (simula el vector x(t) de 8 variables de la protesis fisica)
  4. Downsampling de ACC: 200 Hz -> 50 Hz (simula IMU MPU6050 real)
  5. Upsampling de ACC: 50 Hz -> 200 Hz (interpolacion lineal)
  6. Mapeo de etiquetas: de clases NinaPro a 5 gestos objetivo
  7. Ventana deslizante con early fusion (EMG + ACC concatenados)

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

import numpy as np
import pandas as pd
from pathlib import Path
from typing import Tuple, Optional, List
import warnings

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

# Mapeo: clase_tesis -> lista de IDs originales de NinaPro DB5
# Solo se conservan las muestras con estas etiquetas.
MAPEO_GESTOS = {
    0: [0],    # Rest           (reposo)
    1: [10],   # Pinch          (pinza pulgar-indice)
    2: [11],   # Tripod         (agarre tripode)
    3: [9],    # Power          (punio de fuerza)
    4: [5],    # Finger_Ext     (extension/abduccion de dedos)
}

NOMBRES_GESTOS = ["Rest", "Pinch", "Tripod", "Power", "Finger_Ext"]
NUM_CLASES = len(NOMBRES_GESTOS)  # 5


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

    Solamente se procesan archivos del Ejercicio 1 (E1),
    que contiene los gestos de mano individuales.
    """

    def __init__(self, ruta_dataset: str):
        self.ruta = Path(ruta_dataset)
        # Busca solo archivos de E1 (gestos de mano)
        self.archivos = sorted(self.ruta.glob("**/*E1*.mat"))
        if not self.archivos:
            self.archivos = sorted(self.ruta.glob("**/*E1*.MAT"))
        print(f"[NINAPRO] Archivos E1 encontrados: {len(self.archivos)}")
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
        Extrae EMG, ACC y restimulus directamente del dict toplevel.

        Las variables en NinaPro DB5 estan en el nivel superior
        del .mat (no anidadas en structs).

        Retorna:
            emg: (N, 16)  float64  -- todos los canales
            acc: (N, 6)   float64  -- todos los canales
            labels: (N,)  int64    -- etiquetas restimulus
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

        # Expandir 1D a 2D si es necesario
        if emg.ndim == 1:
            emg = emg.reshape(-1, 1)
        if acc.ndim == 1:
            acc = acc.reshape(-1, 1)

        return emg, acc, labels

    def cargar_todos(self) -> list:
        """
        Carga todos los archivos .mat E1 encontrados.

        Retorna lista de tuplas (emg_raw, acc_raw, labels).
        emg_raw tiene 16 canales, acc_raw tiene 6 canales.
        """
        sujetos = []
        for ruta in self.archivos:
            try:
                datos = self._cargar_mat(ruta)
                emg, acc, labels = self.extraer_sujeto(datos)
                sujetos.append((emg, acc, labels))
                clases_unicas = sorted(np.unique(labels))
                print(f"  [{ruta.name}] {emg.shape[0]} muestras, "
                      f"EMG={emg.shape[1]}ch, ACC={acc.shape[1]}ch, "
                      f"clases={clases_unicas}")
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

    Esto reduce la dimensionalidad de (16+6=22) a (5+3=8),
    alineado con el vector x(t) del sistema real.
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
      El ACC en DB5 viene a 200 Hz, pero nuestro hardware final
      (MPU6050) entrega datos a 50 Hz. Para validar el pipeline
      de fusion, primero DIEZMAMOS la senal (tomamos 1 de cada 4
      muestras, simulando el IMU real) y luego la REINTERPOLAMOS
      a 200 Hz mediante interpolacion lineal.

      La interpolacion lineal entre dos puntos conocidos (t0, a0)
      y (t1, a1) para encontrar a(t*) en t* = t0 + k*Delta_t es:

        a(t*) = a0 + (a1 - a0) * (t* - t0) / (t1 - t0)

      donde Delta_t = 5 ms (200 Hz) y k = 1, 2, 3.

      El Teorema de Nyquist garantiza que frecuencias <= 25 Hz
      se reconstruyen sin aliasing. Los gestos humanos tienen
      energia concentrada por debajo de 5 Hz, muy por debajo
      del limite de Nyquist, por lo que la reconstruccion lineal
      es matematicamente valida.

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
        mapeo = MAPEO_GESTOS

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
class SlidingWindowPreprocessor:
    """
    Construye ventanas deslizantes fusionando EMG + ACC.

    CALCULO DE MUESTRAS POR VENTANA:
      window_size = window_size_ms * sampling_rate_hz / 1000
                  = 200 * 200 / 1000 = 40 muestras

      stride = stride_ms * sampling_rate_hz / 1000
             = 20 * 200 / 1000 = 4 muestras

    EARLY FUSION:
      Cada ventana concaten los canales de EMG (5) y ACC (3)
      en el eje de features, produciendo un vector de 8 canales.
      Esto permite que las capas Conv1D aprendan correlaciones
      espaciotemporales entre ambas modalidades desde la entrada.
    """

    def __init__(
        self,
        window_size_samples: int = VENTANA_SAMPLES,
        stride_samples: int = STRIDE_SAMPLES,
    ):
        self.window_size = window_size_samples
        self.stride = stride_samples

    def generar_ventanas(
        self, emg: np.ndarray, acc: np.ndarray, labels: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Aplica ventana deslizante con early fusion.

        Args:
            emg: (N, 5)  sEMG (5 canales LMG simulados) a 200 Hz
            acc: (N, 3)  ACC reconstruido (3 ejes IMU) a 200 Hz
            labels: (N,) etiquetas mapeadas (0-4)

        Returns:
            X: (ventanas, 40, 8)  early fusion EMG+ACC
            y: (ventanas, 5)      one-hot encoding
        """
        n = emg.shape[0]

        # Early fusion: concatenar EMG y ACC en el eje de canales
        # fusion: (N, 8) = [EMG_0..EMG_4, ACC_0..ACC_2]
        fusion = np.concatenate([emg, acc], axis=1).astype(np.float32)

        ventanas_X = []
        ventanas_y = []

        for inicio in range(0, n - self.window_size + 1, self.stride):
            fin = inicio + self.window_size

            ventanas_X.append(fusion[inicio:fin])

            # Etiqueta por voto mayoritario dentro de la ventana
            etiquetas_en_ventana = labels[inicio:fin]
            etiquetas_validas = etiquetas_en_ventana[etiquetas_en_ventana >= 0]
            if len(etiquetas_validas) == 0:
                continue
            etiqueta = np.bincount(etiquetas_validas).argmax()
            ventanas_y.append(etiqueta)

        if len(ventanas_X) == 0:
            raise ValueError(
                "No se generaron ventanas. Verifique la longitud de los datos "
                f"(n={n}, window_size={self.window_size})."
            )

        X = np.array(ventanas_X, dtype=np.float32)
        y = np.array(ventanas_y, dtype=np.int32)
        y_onehot = np.eye(5, dtype=np.float32)[y]

        print(f"[VENTANEO] Dataset generado:")
        print(f"  Ventanas totales: {X.shape[0]}")
        print(f"  X: {X.shape}  (ventanas, pasos, canales)")
        print(f"  y: {y_onehot.shape}  (ventanas, clases)")
        clases, counts = np.unique(y, return_counts=True)
        dist = {NOMBRES_GESTOS[c]: int(counts[i])
                for i, c in enumerate(clases)}
        print(f"  Distribucion: {dist}")

        return X, y_onehot


# ============================================================
# ORQUESTADOR PRINCIPAL
# ============================================================
def cargar_procesar_dataset(
    ruta_dataset: str,
    mapeo: dict = None,
    ventana_ms: int = VENTANA_MS,
    stride_ms: int = STRIDE_MS,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Orquesta la carga y preprocesamiento de todo NinaPro DB5 E1.

    Flujo por cada archivo:
      1. Cargar EMG (16ch), ACC (6ch), restimulus
      2. Seleccionar canales: EMG[:5], ACC[:3]
      3. Mapear etiquetas a 5 clases (descartar el resto)
      4. Remuestrear ACC (200 -> 50 -> 200 Hz)
      5. Ventana deslizante con early fusion (8 canales)
      6. Acumular ventanas de todos los sujetos

    Args:
        ruta_dataset: Directorio con los archivos .mat
        mapeo: Diccionario de mapeo de gestos
        ventana_ms: Tamano de ventana en ms
        stride_ms: Stride en ms

    Returns:
        X: (total_ventanas, 40, 8)
        y: (total_ventanas, 5)  one-hot
    """
    cargador = CargadorNinaProDB5(ruta_dataset)
    sujetos = cargador.cargar_todos()

    if not sujetos:
        raise FileNotFoundError(
            f"No se encontraron archivos E1 validos en {ruta_dataset}"
        )

    todas_X = []
    todas_y = []

    for idx, (emg_raw, acc_raw, labels) in enumerate(sujetos):
        print(f"\n{'='*50}")
        print(f"PROCESANDO {cargador.archivos[idx].name} "
              f"({idx + 1}/{len(sujetos)})")

        # Paso 1: Seleccionar canales (simular hardware fisico)
        emg, acc = seleccionar_canales(emg_raw, acc_raw)

        # Paso 2: Mapear etiquetas y filtrar
        mask, labels_mapeadas = mapear_etiquetas(labels, mapeo)

        if mask.sum() == 0:
            print("  [!] Sin muestras de las clases objetivo, saltando.")
            continue

        emg = emg[mask]
        acc = acc[mask]
        labels_filtradas = labels_mapeadas[mask]
        print(f"  Muestras utiles: {len(labels_filtradas)}")

        # Paso 3: Remuestrear acelerometro (200 -> 50 -> 200 Hz)
        print(f"  Remuestreo ACC: 200 -> 50 -> 200 Hz...")
        acc_reconstruido = remuestrear_acelerometro(
            acc,
            tasa_origen=TASA_ORIGINAL,
            tasa_intermedia=TASA_ACC_BAJA,
            tasa_destino=TASA_FINAL,
        )

        assert emg.shape[0] == acc_reconstruido.shape[0] == labels_filtradas.shape[0], \
            f"Desalineacion: EMG {emg.shape}, ACC {acc_reconstruido.shape}, Labels {labels_filtradas.shape}"

        # Paso 4: Ventana deslizante con early fusion
        preproc = SlidingWindowPreprocessor(
            window_size_samples=int(ventana_ms * TASA_FINAL / 1000),
            stride_samples=int(stride_ms * TASA_FINAL / 1000),
        )

        X_sujeto, y_sujeto = preproc.generar_ventanas(
            emg, acc_reconstruido, labels_filtradas
        )

        todas_X.append(X_sujeto)
        todas_y.append(y_sujeto)

    if not todas_X:
        raise RuntimeError(
            "No se generaron ventanas. Verifique que los archivos E1 "
            "contengan las clases del mapeo {0,5,9,10,11}."
        )

    X_total = np.concatenate(todas_X, axis=0)
    y_total = np.concatenate(todas_y, axis=0)

    print(f"\n{'='*50}")
    print("DATASET FINAL")
    print(f"  X: {X_total.shape}")
    print(f"  y: {y_total.shape}")
    for i, nombre in enumerate(NOMBRES_GESTOS):
        count = (y_total[:, i] == 1).sum()
        print(f"    {nombre}: {count} ({100*count/y_total.shape[0]:.1f}%)")

    return X_total, y_total


if __name__ == "__main__":
    import sys
    ruta = sys.argv[1] if len(sys.argv) > 1 else "./NinaPro_DB5"
    print("=" * 60)
    print("PREPROCESAMIENTO NINAPRO DB5")
    print("=" * 60)
    X, y = cargar_procesar_dataset(ruta)
    print(f"\n[OK] Dataset listo: {X.shape[0]} ventanas, "
          f"{X.shape[1]} pasos, {X.shape[2]} canales.")
