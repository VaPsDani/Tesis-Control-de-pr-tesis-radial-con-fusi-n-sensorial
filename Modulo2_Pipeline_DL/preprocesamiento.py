"""
preprocesamiento.py - Carga, remuestreo y ventaneo del dataset NinaPro DB5
===========================================================================
Protesis transradial - Validacion con dataset publico multimodal

FLUJO COMPLETO:
  1. Carga archivos .mat de NinaPro DB5 (10 sujetos)
  2. Extrae: EMG (12 canales, 200 Hz), ACC (6 canales, 200 Hz nativo),
     y etiquetas (restimulus)
  3. Downsampling de ACC: 200 Hz -> 50 Hz (simula hardware lento)
  4. Upsampling de ACC: 50 Hz -> 200 Hz (interpolacion lineal)
  5. Mapeo de etiquetas: de 12+ clases NinaPro a solo 5 gestos objetivo
  6. Ventana deslizante con early fusion (EMG + ACC concatenados)

FUNDAMENTO MATEMATICO DE LA INTERPOLACION:
  El acelerometro en el hardware real muestrea a 50 Hz
  (T = 20 ms entre muestras). Para fusionarlo con senales
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
CANALES_EMG = 12          # 12 electrodos sEMG en DB5
CANALES_ACC = 6           # 2 acelerometros x 3 ejes
CANALES_TOTAL = CANALES_EMG + CANALES_ACC  # 18 (early fusion)
TASA_ORIGINAL = 200       # Hz (frecuencia nativa de DB5)
TASA_ACC_BAJA = 50        # Hz (simula hardware final)
TASA_FINAL = 200          # Hz (despues de upsampling)

VENTANA_MS = 200
STRIDE_MS = 20
VENTANA_SAMPLES = int(VENTANA_MS * TASA_FINAL / 1000)   # 40
STRIDE_SAMPLES = int(STRIDE_MS * TASA_FINAL / 1000)      # 4

# Mapeo: clase_tesis -> lista de IDs originales de NinaPro DB5
# Se descartan todas las etiquetas no incluidas en este mapeo.
MAPEO_GESTOS = {
    0: [0],    # Rest     (reposo)
    1: [10],   # Pinch    (pinza pulgar-indice)
    2: [11],   # Tripod   (agarre tripode)
    3: [9],    # Power    (punio de fuerza)
    4: [5],    # Finger_Ext (extension/abduccion de dedos)
}

NOMBRES_GESTOS = ["Rest", "Pinch", "Tripod", "Power", "Finger_Ext"]


# ============================================================
# CARGA DE ARCHIVOS .MAT DE NINAPRO DB5
# ============================================================
class CargadorNinaProDB5:
    """
    Busca y carga los archivos .mat del dataset NinaPro DB5.

    NinaPro DB5 contiene para cada sujeto:
      - emg:  (n_muestras, 12)  float64  -- 12 canales sEMG a 200 Hz
      - acc:  (n_muestras, 6)   float64  -- 2 acelerometros x 3 ejes
      - restimulus: (n_muestras,) int64   -- etiquetas corregidas (0..12+)
      - stimulus:   (n_muestras,) int64   -- etiqueta original (cued)
    """

    def __init__(self, ruta_dataset: str):
        self.ruta = Path(ruta_dataset)
        # Busca recursivamente todos los .mat
        self.archivos = sorted(self.ruta.glob("**/*.mat"))
        if not self.archivos:
            # Buscar tambien .MAT (mayusculas)
            self.archivos = sorted(self.ruta.glob("**/*.MAT"))
        print(f"[NINAPRO] Archivos .mat encontrados: {len(self.archivos)}")
        if self.archivos:
            print(f"[NINAPRO] Primer archivo: {self.archivos[0].name}")
            print(f"[NINAPRO] Ultimo archivo: {self.archivos[-1].name}")

    def _cargar_mat(self, ruta: Path) -> dict:
        """
        Carga un archivo .mat soportando formato v5/v7 (scipy)
        y v7.3 (h5py). Retorna un dict con las variables.
        """
        import scipy.io as sio

        try:
            datos = sio.loadmat(str(ruta))
            return datos, False
        except NotImplementedError:
            # Formato v7.3 -> usar h5py
            return self._cargar_mat_h5py(ruta)
        except Exception as e:
            raise RuntimeError(f"Error al cargar {ruta}: {e}")

    def _cargar_mat_h5py(self, ruta: Path) -> dict:
        """
        Carga archivos .mat v7.3 con h5py.
        Los arrays vienen transpuestos (column-major de MATLAB),
        se transponen de vuelta a (n_muestras, n_canales).
        """
        import h5py

        datos = {}
        with h5py.File(str(ruta), "r") as f:
            for clave in f.keys():
                arr = np.array(f[clave])
                # h5py preserva el orden column-major de MATLAB
                # Si el array tiene forma (C, N), lo transponemos a (N, C)
                # para tener (n_muestras, n_canales) como con scipy
                datos[clave] = arr.T if arr.ndim == 2 else arr.squeeze()
        return datos, True

    def extraer_sujeto(self, datos: dict):
        """
        Extrae las matrices EMG, ACC y etiquetas del dict cargado.

        Retorna:
            emg: (n, 12) float64
            acc: (n, 6)  float64
            labels: (n,)  int64
        """
        emg, acc, labels = None, None, None

        def _extraer_campo(struct, campo):
            """Extrae un campo de un struct MATLAB o dict."""
            if isinstance(struct, np.ndarray):
                if struct.dtype.names is not None and campo in struct.dtype.names:
                    return struct[campo]
                # Podria ser un struct anidado (1x1)
                if struct.size == 1 and struct.dtype == object:
                    return _extraer_campo(struct.flat[0], campo)
            elif isinstance(struct, dict):
                return struct.get(campo)
            return None

        # Caso 1: las variables estan dentro de 'data', 'Data', etc.
        for var_env in ["data", "Data", "dataset", "Dataset"]:
            if var_env in datos:
                s = datos[var_env]
                emg = _extraer_campo(s, "emg")
                acc = _extraer_campo(s, "acc")
                if emg is not None and acc is not None:
                    labels = _extraer_campo(s, "restimulus")
                    if labels is None:
                        labels = _extraer_campo(s, "stimulus")
                    break

        # Caso 2: variables directas en el nivel superior
        if emg is None:
            emg = datos.get("emg")
        if acc is None:
            acc = datos.get("acc")
        if labels is None:
            labels = datos.get("restimulus", datos.get("stimulus"))

        if emg is None or acc is None:
            raise KeyError(
                f"No se encontraron 'emg' y 'acc'. "
                f"Claves disponibles: {list(datos.keys())[:15]}"
            )

        # Asegurar tipos y formas
        emg = np.asarray(emg, dtype=np.float64)
        acc = np.asarray(acc, dtype=np.float64)
        labels = np.asarray(labels, dtype=np.int64).ravel()

        # Si los arrays son 1D, expandir dimensiones
        if emg.ndim == 1:
            emg = emg.reshape(-1, 1)
        if acc.ndim == 1:
            acc = acc.reshape(-1, 1)

        # Verificar consistencia temporal
        n_emg = emg.shape[0]
        n_acc = acc.shape[0]
        n_lab = labels.shape[0]

        # Si EMG y ACC tienen diferente longitud, truncar a la menor
        n_min = min(n_emg, n_acc, n_lab)
        if n_emg != n_acc or n_acc != n_lab:
            warnings.warn(
                f"Longitudes inconsistentes: EMG={n_emg}, ACC={n_acc}, "
                f"Labels={n_lab}. Truncando a {n_min}."
            )
            emg = emg[:n_min]
            acc = acc[:n_min]
            labels = labels[:n_min]

        return emg, acc, labels

    def cargar_sujeto(self, ruta: Path):
        """
        Carga un archivo .mat y retorna (emg, acc, labels).
        """
        datos, es_h5py = self._cargar_mat(ruta)
        emg, acc, labels = self.extraer_sujeto(datos)
        return emg, acc, labels

    def cargar_todos(self) -> list:
        """
        Carga todos los archivos .mat encontrados.

        Retorna:
            lista de tuplas (emg, acc, labels) por sujeto/archivo
        """
        sujetos = []
        for ruta in self.archivos:
            try:
                emg, acc, labels = self.cargar_sujeto(ruta)
                sujetos.append((emg, acc, labels))
                n_muestras = emg.shape[0]
                clases_unicas = sorted(np.unique(labels))
                print(f"  [{ruta.name}] {n_muestras} muestras, "
                      f"clases presentes: {clases_unicas}")
            except Exception as e:
                print(f"  [!] Error en {ruta.name}: {e}")
        return sujetos


# ============================================================
# REMUESTREO DEL ACELEROMETRO
# ============================================================
def remuestrear_acelerometro(
    acc: np.ndarray,
    tasa_origen: int = TASA_ORIGINAL,
    tasa_intermedia: int = TASA_ACC_BAJA,
    tasa_destino: int = TASA_FINAL,
) -> np.ndarray:
    """
    Simula un acelerometro lento y luego lo reinterpola a la tasa original.

    LOGICA MATEMATICA:
      Dado que el ACC nativo en DB5 esta a 200 Hz, pero nuestro hardware
      final usara un ACC a 50 Hz, primero DIEZMAMOS la senal (tomamos 1
      de cada 4 muestras) para simular el hardware limitado.

      Luego REINTERPOLAMOS: partiendo de 50 Hz, generamos 3 muestras
      intermedias entre cada par de muestras reales usando interpolacion
      lineal. Esto es posible porque los gestos humanos tienen energia
      concentrada por debajo de 5 Hz, muy por debajo de la frecuencia
      de Nyquist de 25 Hz.

    Pasos:
      1. Diezmar:  acc_200hz[::4, :]  ->  acc_50hz
      2. Reindexar a grilla fina (indices enteros: 0,1,2,3,...)
      3. Interpolar linealmente los NaN generados por el reindexado

    Args:
        acc: Array original (n, canales_acc) a 200 Hz
        tasa_origen: Frecuencia original del ACC (200 Hz en DB5)
        tasa_intermedia: Frecuencia que simulamos (50 Hz)
        tasa_destino: Frecuencia final (200 Hz)

    Returns:
        acc_reconstruido: (n, canales_acc) a 200 Hz
    """
    if tasa_origen == tasa_destino:
        # Si ya estan iguales, solo diezmamos y reinterpolamos
        pass

    factor_diezmado = tasa_origen // tasa_intermedia  # 4

    # Paso 1: Diezmar (downsampling) para simular ACC lento
    # Se toma 1 muestra cada `factor_diezmado`
    acc_lento = acc[::factor_diezmado, :].copy()
    n_lento = acc_lento.shape[0]

    # Paso 2: Crear grillas temporales con indices enteros
    # Cada unidad del indice representa 1/fase_destino segundos
    paso_fino = tasa_origen // tasa_destino  # 1 (igual tasa)

    # Indices de las muestras lentas en la grilla fina
    # Si tenemos 4x diezmado, las muestras lentas estan en
    # posiciones 0, 4, 8, 12, ...
    indices_lentos = np.arange(0, n_lento * factor_diezmado, factor_diezmado)

    # Indices de la grilla fina completa
    n_total = n_lento * factor_diezmado
    indices_finos = np.arange(n_total)

    # Paso 3: Construir DataFrame con las muestras conocidas y reindexar
    df_lento = pd.DataFrame(
        acc_lento,
        index=indices_lentos,
        columns=range(acc.shape[1]),
    )

    # Reindexar a la grilla fina (genera NaN en posiciones sin dato)
    df_fino = df_lento.reindex(indices_finos)

    # Paso 4: Interpolacion lineal para llenar NaN
    # Linear interpolation traza una recta entre dos puntos
    # conocidos y evalua en la posicion deseada.
    # Para posiciones 1,2,3: se interpola entre 0 y 4
    df_interp = df_fino.interpolate(method="linear", limit_area="inside")

    # Verificar que no queden NaN (primeras y ultimas muestras podrian
    # quedar NaN si no hay suficientes puntos para interpolar en bordes)
    if df_interp.isna().any().any():
        # Rellenar bordes con el valor conocido mas cercano
        df_interp = df_interp.bfill().ffill()

    acc_reconstruido = df_interp.values.astype(np.float64)

    # Asegurar misma longitud que el EMG original
    n_original = acc.shape[0]
    if acc_reconstruido.shape[0] != n_original:
        # Truncar o rellenar para coincidir
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
# MAPEO DE ETIQUETAS
# ============================================================
def mapear_etiquetas(
    labels: np.ndarray,
    mapeo: dict = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Mapea las etiquetas originales de NinaPro DB5 a las 5 clases objetivo.

    Las muestras con etiquetas no incluidas en el mapeo se descartan.

    Args:
        labels: Array (n,) con etiquetas originales (0..12+)
        mapeo: Dict {clase_destino: [lista_de_ids_origen]}

    Returns:
        mask: Booleano (n,) -> True para muestras a conservar
        labels_mapeadas: (n,) con etiquetas reasignadas (0-4)
                          o -1 para las descartadas
    """
    if mapeo is None:
        mapeo = MAPEO_GESTOS

    # Construir tabla inversa: id_original -> clase_destino
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

    print(f"[MAPEO] Etiquetas originales: {dict(zip(*np.unique(labels, return_counts=True)))}")
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
      Cada ventana concaten los canales de EMG (12) y ACC (6)
      en el eje de features, produciendo un vector de 18 canales.
      Esto permite que las capas Conv1D aprendan correlaciones
      espaciotemporales entre ambas modalidades desde la entrada.
    """

    def __init__(
        self,
        window_size_samples: int = VENTANA_SAMPLES,
        stride_samples: int = STRIDE_SAMPLES,
        num_emg: int = CANALES_EMG,
        num_acc: int = CANALES_ACC,
    ):
        self.window_size = window_size_samples
        self.stride = stride_samples
        self.num_emg = num_emg
        self.num_acc = num_acc
        self.num_features = num_emg + num_acc

    def generar_ventanas(
        self, emg: np.ndarray, acc: np.ndarray, labels: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Aplica ventana deslizante con early fusion.

        Args:
            emg: (n, 12) sEMG a 200 Hz
            acc: (n, 6)  ACC reconstruido a 200 Hz
            labels: (n,)  etiquetas mapeadas (0-4)

        Returns:
            X: (num_ventanas, window_size, num_features)
            y: (num_ventanas, 5)  one-hot encoding
        """
        n = emg.shape[0]

        # Early fusion: concatenar EMG y ACC en el eje de canales
        # fusion: (n, 18) = [EMG_0..EMG_11, ACC_0..ACC_5]
        fusion = np.concatenate([emg, acc], axis=1).astype(np.float32)

        ventanas_X = []
        ventanas_y = []

        for inicio in range(0, n - self.window_size + 1, self.stride):
            fin = inicio + self.window_size

            # Ventana de features fusionados
            ventanas_X.append(fusion[inicio:fin])

            # Etiqueta por voto mayoritario dentro de la ventana
            etiquetas_en_ventana = labels[inicio:fin]
            # Excluir posibles -1 (aunque no deberian existir)
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

        # One-hot encoding
        y_onehot = np.eye(5, dtype=np.float32)[y]

        print(f"[VENTANEO] Dataset generado:")
        print(f"  Ventanas totales: {X.shape[0]}")
        print(f"  Dimensiones X:    {X.shape}  (ventanas, pasos, canales)")
        print(f"  Dimensiones y:    {y_onehot.shape}  (ventanas, clases)")
        print(f"  Distribucion:     {dict(zip(*np.unique(y, return_counts=True)))}")

        return X, y_onehot


# ============================================================
# ORQUESTADOR: CARGA TODO EL DATASET
# ============================================================
def cargar_procesar_dataset(
    ruta_dataset: str,
    mapeo: dict = None,
    ventana_ms: int = VENTANA_MS,
    stride_ms: int = STRIDE_MS,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Orquesta la carga de todos los sujetos de NinaPro DB5.

    Flujo por cada archivo .mat:
      1. Cargar EMG, ACC, etiquetas
      2. Mapear etiquetas a 5 clases (descartar el resto)
      3. Remuestrear ACC (200 -> 50 -> 200 Hz)
      4. Aplicar ventana deslizante con early fusion
      5. Acumular ventanas de todos los sujetos

    Args:
        ruta_dataset: Directorio con los archivos .mat
        mapeo: Diccionario de mapeo de gestos
        ventana_ms: Tamano de ventana en ms
        stride_ms: Stride en ms

    Returns:
        X: (total_ventanas, window_size, num_features)
        y: (total_ventanas, 5)  one-hot
    """
    cargador = CargadorNinaProDB5(ruta_dataset)
    sujetos = cargador.cargar_todos()

    if not sujetos:
        raise FileNotFoundError(
            f"No se encontraron archivos .mat validos en {ruta_dataset}"
        )

    # Procesar cada sujeto y acumular ventanas
    todas_X = []
    todas_y = []

    for idx, (emg, acc, labels) in enumerate(sujetos):
        print(f"\n{'='*50}")
        print(f"PROCESANDO SUJETO {idx + 1}/{len(sujetos)}")

        # Paso 1: Mapear etiquetas y filtrar
        mask, labels_mapeadas = mapear_etiquetas(labels, mapeo)

        if mask.sum() == 0:
            print(f"  [!] Sin muestras de las clases objetivo, saltando.")
            continue

        emg_filtrado = emg[mask]
        acc_filtrado = acc[mask]
        labels_filtradas = labels_mapeadas[mask]

        print(f"  Muestras despues de filtrado: {len(labels_filtradas)}")

        # Paso 2: Remuestrear acelerometro
        print(f"  Remuestreando ACC: {TASA_ORIGINAL} -> {TASA_ACC_BAJA} -> {TASA_FINAL} Hz...")
        acc_reconstruido = remuestrear_acelerometro(
            acc_filtrado,
            tasa_origen=TASA_ORIGINAL,
            tasa_intermedia=TASA_ACC_BAJA,
            tasa_destino=TASA_FINAL,
        )

        # Verificar alineacion temporal
        assert emg_filtrado.shape[0] == acc_reconstruido.shape[0] == labels_filtradas.shape[0], \
            f"Desalineacion: EMG {emg_filtrado.shape}, ACC {acc_reconstruido.shape}, Labels {labels_filtradas.shape}"

        # Paso 3: Ventana deslizante con early fusion
        preproc = SlidingWindowPreprocessor(
            window_size_samples=int(ventana_ms * TASA_FINAL / 1000),
            stride_samples=int(stride_ms * TASA_FINAL / 1000),
        )

        X_sujeto, y_sujeto = preproc.generar_ventanas(
            emg_filtrado, acc_reconstruido, labels_filtradas
        )

        todas_X.append(X_sujeto)
        todas_y.append(y_sujeto)

    if not todas_X:
        raise RuntimeError(
            "No se generaron datos. Verifique que los archivos .mat "
            "contengan las clases del mapeo."
        )

    X_total = np.concatenate(todas_X, axis=0)
    y_total = np.concatenate(todas_y, axis=0)

    print(f"\n{'='*50}")
    print(f"DATASET FINAL")
    print(f"  X: {X_total.shape}  ({X_total.shape[0]} ventanas, "
          f"{X_total.shape[1]} pasos, {X_total.shape[2]} canales)")
    print(f"  y: {y_total.shape}")
    print(f"  Distribucion de clases:")
    for i, nombre in enumerate(NOMBRES_GESTOS):
        count = (y_total[:, i] == 1).sum()
        print(f"    {nombre}: {count} ({100*count/y_total.shape[0]:.1f}%)")

    return X_total, y_total


# ============================================================
# EJEMPLO DE USO STANDALONE
# ============================================================
if __name__ == "__main__":
    import sys

    ruta = sys.argv[1] if len(sys.argv) > 1 else "./NinaPro_DB5"

    print("=" * 60)
    print("PREPROCESAMIENTO NINAPRO DB5")
    print("=" * 60)

    X, y = cargar_procesar_dataset(ruta)
    print(f"\n[OK] Dataset listo: {X.shape[0]} ventanas para entrenamiento.")
