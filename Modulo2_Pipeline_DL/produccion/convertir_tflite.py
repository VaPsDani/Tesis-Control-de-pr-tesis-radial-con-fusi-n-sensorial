"""
convertir_tflite.py - Conversion a TensorFlow Lite para Microcontroladores
=============================================================================
Protesis transradial - Fusion sensorial y Deep Learning

PROCESO DE CUANTIZACION:
  1. Cargar el modelo entrenado (.keras)
  2. Convertir a TFLite con cuantizacion INT8 (8-bit simetrica)
  3. El conjunto de cuantizacion (representative dataset) son 1000
     ventanas al azar, con semilla fija, SOLO de los participantes con
     que se entreno el modelo (A23). Nunca de prueba. Salen de
     preparar_sesiones(), el mismo preprocesamiento del entrenamiento.
  4. Exportar un archivo .tflite y un archivo .h (C array) para
     cargar directamente en el ESP32 con TensorFlow Lite Micro

CUANTIZACION INT8:
  - Pesa los pesos de float32 → int8 (-128 a 127)
  - Reduce el tamano del modelo ~4x
  - La perdida de precision tipica es < 2% en accuracy
  - Habilita aceleracion por hardware en el ESP32 (TFLite Micro)

ENTORNO:
  Keras 2 (tf_keras), requirements.txt. El modelo tiene que
  haberse entrenado tambien con tf_keras (entrenar_modelo.py lo hace).

USO:
  python convertir_tflite.py --modelo resultados/modelo_final.keras
      --info resultados/final_lmg_imu.json --sesiones "../sesiones/*.csv"
  (todo en una linea)

  --info es el JSON que deja entrenar_modelo.py --modo final: de ahi salen
  la composicion de canales y la lista de sujetos de entrenamiento.
"""

# Rutas del Modulo 2 tras la reorganizacion: common/ tiene el codigo
# compartido por todos los experimentos y produccion/ el pipeline del
# modelo que se despliega.
import os as _os
import sys as _sys
_M2 = _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                     ".."))
for _d in (_M2, _os.path.join(_M2, "common"), _os.path.join(_M2, "produccion"),
           _os.path.join(_M2, "experimentos", "validacion_preliminar_emg")):
    if _d not in _sys.path:
        _sys.path.insert(0, _d)


import argparse
import os
import struct

import numpy as np

import keras_legado
keras_legado.activar()          # antes de importar tensorflow
import tensorflow as tf         # noqa: E402

from modelo import MecanismoAtencion                   # noqa: E402
import preprocesamiento as P                            # noqa: E402

N_CALIBRACION = 1000


def representative_dataset_gen(dataset: np.ndarray, num_samples: int = 1000):
    """
    Generador de dataset representativo para calibracion de cuantizacion.

    TFLite necesita ver ejemplos reales del dominio para calcular
    los rangos optimos de activacion (min/max) para cada capa.
    Se toman las primeras `num_samples` ventanas del dataset.
    """
    n = min(num_samples, dataset.shape[0])
    for i in range(n):
        # TFLite espera un batch, por eso se anade dimension: (1, 20, 8)
        yield [dataset[i : i + 1].astype(np.float32)]


def ventanas_de_calibracion(v, sujetos, composicion: str,
                            n: int = N_CALIBRACION, semilla: int = 42) -> np.ndarray:
    """
    El representative dataset (A23): n ventanas al azar, con semilla fija,
    de los sujetos de ENTRENAMIENTO del modelo, con sus canales. Al azar y
    no las primeras porque las primeras son casi todas del primer sujeto y
    de su primer reposo.
    """
    m = np.isin(v.sujeto, list(sujetos))
    if not m.any():
        raise ValueError(f"Ningun sujeto de {sorted(sujetos)} esta en las sesiones.")
    cols = [P.COLUMNAS_MODELO.index(c) for c in P.COMPOSICIONES[composicion]]
    idx = np.flatnonzero(m)
    rng = np.random.RandomState(semilla)
    elegidas = np.sort(rng.choice(idx, min(n, len(idx)), replace=False))
    return v.X[elegidas][:, :, cols].astype(np.float32)


def convertir_modelo(modelo, X_calibracion: np.ndarray) -> bytes:
    """Modelo en memoria a TFLite INT8. Devuelve los bytes del .tflite."""
    # Lote fijo de 1: el ESP32 infiere una ventana cada vez, y con lote
    # variable el conversor no puede fusionar la LSTM en su operacion
    # nativa (error "TensorListReserve ... element_shape to be static").
    forma = [1] + list(modelo.inputs[0].shape[1:])
    funcion = tf.function(lambda x: modelo(x, training=False))
    concreta = funcion.get_concrete_function(tf.TensorSpec(forma, tf.float32))
    converter = tf.lite.TFLiteConverter.from_concrete_functions([concreta], modelo)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    converter.representative_dataset = lambda: representative_dataset_gen(
        X_calibracion, num_samples=len(X_calibracion))
    converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    # Entrada y salida en float32: las operaciones internas son int8.
    converter.inference_input_type = tf.float32
    converter.inference_output_type = tf.float32
    tflite_model = converter.convert()
    verificar_operaciones(tflite_model)
    return tflite_model


def ejecutar_tflite(tflite_model: bytes, X: np.ndarray) -> np.ndarray:
    """
    Probabilidades del modelo TFLite, ventana a ventana.

    La LSTM de TFLite guarda su estado en tensores variables que persisten
    entre invoke(): se reinician antes de cada ventana, igual que hace el
    firmware con Reset() (experimentos/cuantizacion_int8/README.md). Sin
    eso, cada ventana hereda el estado de la anterior.
    """
    it = tf.lite.Interpreter(
        model_content=tflite_model,
        experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES)
    it.allocate_tensors()
    i = it.get_input_details()[0]["index"]
    o = it.get_output_details()[0]["index"]
    salida = np.empty((len(X), it.get_output_details()[0]["shape"][-1]), np.float32)
    for k, x in enumerate(X):
        it.reset_all_variables()
        it.set_tensor(i, x[None].astype(np.float32))
        it.invoke()
        salida[k] = it.get_tensor(o)[0]
    return salida


def escala_entrada(tflite_model: bytes):
    """
    Paso y cero de la cuantizacion de la ENTRADA, que es uno solo para los
    8 canales (cuantizacion por tensor). Con la LMG en z y el acelerometro
    en g, el paso lo fija el canal de mayor rango: si es grande, al
    acelerometro le quedan pocos niveles.
    """
    it = tf.lite.Interpreter(model_content=tflite_model)
    ops = it._get_ops_details()
    q = next(o for o in ops if o["op_name"] == "QUANTIZE")
    det = {t["index"]: t for t in it.get_tensor_details()}[q["outputs"][0]]
    escala, cero = det["quantization"]
    return float(escala), int(cero)


def convertir_a_tflite(
    ruta_modelo: str, X_calibracion: np.ndarray, output_dir: str = "output"
) -> str:
    """
    Convierte modelo Keras a TFLite INT8 cuantizado.

    Pasos:
      1. Cargar modelo GuardadoModel
      2. Crear TFLiteConverter
      3. Configurar optimizacion por defecto (optimize for size)
      4. Especificar tipo de cuantizacion objetivo: int8
      5. Proveer dataset representativo
      6. Convertir y guardar

    Returns:
        ruta_tflite: Ruta al archivo .tflite generado
    """
    print(f"[TFLITE] Keras 2 (tf_keras {keras_legado.verificar()})")
    print("[TFLITE] Cargando modelo Keras...")
    # La capa de atencion es propia: hay que pasar la clase, no None
    modelo = tf.keras.models.load_model(
        ruta_modelo,
        custom_objects={"MecanismoAtencion": MecanismoAtencion},
    )

    print("[TFLITE] Convirtiendo a TFLite INT8...")
    tflite_model = convertir_modelo(modelo, X_calibracion)

    # ========== GUARDAR .tflite ==========
    os.makedirs(output_dir, exist_ok=True)
    ruta_tflite = os.path.join(output_dir, "modelo_gestos.tflite")
    with open(ruta_tflite, "wb") as f:
        f.write(tflite_model)

    tamano_kb = len(tflite_model) / 1024
    print(f"[TFLITE] Modelo guardado: {ruta_tflite}")
    print(f"[TFLITE] Tamano: {tamano_kb:.2f} KB")

    return ruta_tflite


def verificar_operaciones(tflite_model: bytes):
    """
    Falla si la LSTM no quedo como operacion nativa.

    Un bucle WHILE en el grafo significa que el modelo se entreno o se
    convirtio con Keras 3: TFLite Micro no lo ejecutaria como la BiLSTM
    validada.
    """
    interp = tf.lite.Interpreter(model_content=tflite_model)
    ops = sorted({d["op_name"] for d in interp._get_ops_details()})
    print(f"[TFLITE] Operaciones: {', '.join(ops)}")
    if "WHILE" in ops or "UNIDIRECTIONAL_SEQUENCE_LSTM" not in ops:
        raise RuntimeError(
            "La LSTM no se fusiono en UNIDIRECTIONAL_SEQUENCE_LSTM. "
            "Entrene y convierta con tf_keras (requirements.txt).")


def exportar_a_c_array(ruta_tflite: str, output_dir: str = "output",
                       copiar_al_modulo3: bool = False):
    """
    Convierte el .tflite a un archivo .h (C array) para TFLite Micro en ESP32.

    Con copiar_al_modulo3, el archivo se copia ademas al Modulo 3 para su
    compilacion.
    """
    with open(ruta_tflite, "rb") as f:
        tflite_data = f.read()

    # Generar el contenido del header
    hex_lines = []
    hex_lines.append("#ifndef MODELO_GESTOS_TFLITE_H")
    hex_lines.append("#define MODELO_GESTOS_TFLITE_H")
    hex_lines.append("")
    hex_lines.append("#include <cstdint>")
    hex_lines.append("")
    hex_lines.append("// Modelo TFLite cuantizado INT8 para clasificacion de gestos")
    hex_lines.append(f"// Tamano: {len(tflite_data)} bytes ({len(tflite_data)/1024:.2f} KB)")
    hex_lines.append("// Generado por: convertir_tflite.py")
    hex_lines.append("// La LSTM guarda su estado entre Invoke(): reiniciar con")
    hex_lines.append("// interpreter->Reset() antes de cada ventana (inferencia.cpp lo hace).")
    hex_lines.append("")
    hex_lines.append(
        "alignas(16) const unsigned char modelo_gestos_tflite[] = {"
    )

    # Formatear como bytes hex (16 por linea)
    for i in range(0, len(tflite_data), 16):
        chunk = tflite_data[i : i + 16]
        hex_str = ", ".join(f"0x{b:02x}" for b in chunk)
        hex_lines.append(f"  {hex_str},")

    hex_lines.append("};")
    hex_lines.append("")
    hex_lines.append(
        f"const unsigned int modelo_gestos_tflite_len = {len(tflite_data)};"
    )
    hex_lines.append("")
    hex_lines.append("#endif  // MODELO_GESTOS_TFLITE_H")

    # Guardar en output_dir
    os.makedirs(output_dir, exist_ok=True)
    ruta_h = os.path.join(output_dir, "modelo_gestos_tflite.h")
    with open(ruta_h, "w") as f:
        f.write("\n".join(hex_lines))

    print(f"[HEADER] Archivo .h generado: {ruta_h}")

    # Copiar al Modulo 3, SOLO si se pide. Antes se copiaba siempre, a una
    # ruta calculada desde output_dir que solo existia si la salida estaba
    # dentro del repositorio, y una conversion de prueba pisaba el modelo
    # del firmware.
    if copiar_al_modulo3:
        destino_mod3 = os.path.normpath(os.path.join(
            _M2, "..", "Modulo3_Inferencia_Control", "modelo_gestos_tflite.h"))
        with open(destino_mod3, "w") as f:
            f.write("\n".join(hex_lines))
        print(f"[HEADER] Copiado a Modulo 3: {destino_mod3}")


def main():
    import json
    parser = argparse.ArgumentParser(
        description="Convertir modelo Keras a TFLite INT8 para ESP32")
    parser.add_argument("--modelo", required=True, help="modelo .keras")
    parser.add_argument("--info", required=True,
                        help="JSON de entrenar_modelo.py --modo final")
    parser.add_argument("--sesiones", required=True, help="patron de los CSV")
    parser.add_argument("--output_dir", default="output")
    parser.add_argument("--copiar_al_modulo3", action="store_true",
                        help="copia el .h a Modulo3_Inferencia_Control")
    args = parser.parse_args()

    with open(args.info, encoding="utf-8") as f:
        info = json.load(f)
    entrenamiento = info["sujetos_entrenamiento"]
    composicion = info["composicion"]
    print(f"[CALIB] {composicion}, representative dataset de los sujetos de "
          f"entrenamiento {entrenamiento} (nunca de prueba)")

    v = P.preparar_sesiones(args.sesiones)
    X = ventanas_de_calibracion(v, entrenamiento, composicion)
    ruta_tflite = convertir_a_tflite(args.modelo, X, args.output_dir)
    exportar_a_c_array(ruta_tflite, args.output_dir, args.copiar_al_modulo3)

    print("\n[DONE] Proceso completado.")
    if not args.copiar_al_modulo3:
        print("  - Revise el modelo y copie modelo_gestos_tflite.h al Modulo 3,")
        print("    o repita con --copiar_al_modulo3")
    print("  - Compile con el IDE de Arduino")


if __name__ == "__main__":
    main()
