"""
convertir_tflite.py - Conversion a TensorFlow Lite para Microcontroladores
=============================================================================
Protesis transradial - Fusion sensorial y Deep Learning

PROCESO DE CUANTIZACION:
  1. Cargar el modelo entrenado (.keras)
  2. Convertir a TFLite con cuantizacion INT8 (8-bit simetrica)
  3. El conjunto de cuantizacion (representative dataset) se toma
     de las primeras 1000 ventanas del dataset de entrenamiento
  4. Exportar un archivo .tflite y un archivo .h (C array) para
     cargar directamente en el ESP32 con TensorFlow Lite Micro

CUANTIZACION INT8:
  - Pesa los pesos de float32 → int8 (-128 a 127)
  - Reduce el tamano del modelo ~4x
  - La perdida de precision tipica es < 2% en accuracy
  - Habilita aceleracion por hardware en el ESP32 (TFLite Micro)

USO:
  python convertir_tflite.py --modelo output/mejor_modelo.keras --csv dataset_gestos.csv
"""

import argparse
import os
import struct

import numpy as np
import tensorflow as tf

from preprocesamiento import SlidingWindowPreprocessor


def representative_dataset_gen(dataset: np.ndarray, num_samples: int = 1000):
    """
    Generador de dataset representativo para calibracion de cuantizacion.

    TFLite necesita ver ejemplos reales del dominio para calcular
    los rangos optimos de activacion (min/max) para cada capa.
    Se toman las primeras `num_samples` ventanas del dataset.
    """
    n = min(num_samples, dataset.shape[0])
    for i in range(n):
        # TFLite espera un batch, por eso se anade dimension: (1, 20, 9)
        yield [dataset[i : i + 1].astype(np.float32)]


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
    print("[TFLITE] Cargando modelo Keras...")
    modelo = tf.keras.models.load_model(
        ruta_modelo,
        custom_objects={"MecanismoAtencion": None},  # se resuelve por nombre
    )

    # ========== CONVERTER ==========
    converter = tf.lite.TFLiteConverter.from_keras_model(modelo)

    # Optimizacion por defecto: reduce tamano
    converter.optimizations = [tf.lite.Optimize.DEFAULT]

    # Cuantizacion INT8 completa (pesos y activaciones)
    # El tipo de entrada/salida sigue siendo float32 para compatibilidad,
    # pero las operaciones internas se ejecutan en int8.
    converter.representative_dataset = lambda: representative_dataset_gen(
        X_calibracion, num_samples=1000
    )

    # Forzar cuantizacion INT8 para todas las operaciones
    converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]

    # Tipo de entrada y salida: float32 (el ESP32 puede manejar float32)
    converter.inference_input_type = tf.float32
    converter.inference_output_type = tf.float32

    print("[TFLITE] Convirtiendo a TFLite INT8...")
    tflite_model = converter.convert()

    # ========== GUARDAR .tflite ==========
    os.makedirs(output_dir, exist_ok=True)
    ruta_tflite = os.path.join(output_dir, "modelo_gestos.tflite")
    with open(ruta_tflite, "wb") as f:
        f.write(tflite_model)

    tamano_kb = len(tflite_model) / 1024
    print(f"[TFLITE] Modelo guardado: {ruta_tflite}")
    print(f"[TFLITE] Tamano: {tamano_kb:.2f} KB")

    return ruta_tflite


def exportar_a_c_array(ruta_tflite: str, output_dir: str = "output"):
    """
    Convierte el .tflite a un archivo .h (C array) para TFLite Micro en ESP32.

    El archivo generado se copia al Modulo 3 para su compilacion.
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

    # Copiar al Modulo 3
    destino_mod3 = os.path.join(
        os.path.dirname(output_dir),  # subir un nivel
        "..",
        "Modulo3_Inferencia_Control",
        "modelo_gestos_tflite.h",
    )
    destino_mod3 = os.path.normpath(destino_mod3)
    with open(destino_mod3, "w") as f:
        f.write("\n".join(hex_lines))
    print(f"[HEADER] Copiado a Modulo 3: {destino_mod3}")


def main():
    parser = argparse.ArgumentParser(
        description="Convertir modelo Keras a TFLite INT8 para ESP32"
    )
    parser.add_argument(
        "--modelo", type=str, required=True, help="Ruta al modelo Keras (.keras)"
    )
    parser.add_argument(
        "--csv", type=str, required=True, help="Dataset CSV para calibracion"
    )
    parser.add_argument(
        "--output_dir", type=str, default="output", help="Directorio de salida"
    )
    args = parser.parse_args()

    # ========== 1. CARGAR DATASET DE CALIBRACION ==========
    print("[CALIB] Cargando dataset para calibracion...")
    preproc = SlidingWindowPreprocessor(
        window_size_ms=200, stride_ms=20, sampling_rate_hz=100
    )
    df = preproc.cargar_csv(args.csv)
    X, _ = preproc.generar_ventanas(df)

    # ========== 2. CONVERTIR A TFLITE ==========
    ruta_tflite = convertir_a_tflite(args.modelo, X, args.output_dir)

    # ========== 3. GENERAR HEADER PARA TFLITE MICRO ==========
    exportar_a_c_array(ruta_tflite, args.output_dir)

    print("\n[DONE] Proceso completado.")
    print("  - Lleve modelo_gestos_tflite.h al Modulo 3")
    print("  - Compile con PlatformIO o Arduino IDE")


if __name__ == "__main__":
    main()
