/*
 * reverse_v2_lmg.h - Operacion REVERSE_V2 para TFLite Micro
 *
 * POR QUE EXISTE:
 *   La BiLSTM del modelo se convierte en dos UNIDIRECTIONAL_SEQUENCE_LSTM.
 *   La rama hacia atras invierte el eje temporal antes y despues de su LSTM
 *   con REVERSE_V2. TFLite Micro la trae, pero la libreria de Arduino
 *   Chirale_TensorFlowLite 2.0.0 no la incluye. Esta es una implementacion
 *   propia, registrada desde el sketch (no se modifica la libreria ni el
 *   modelo).
 *
 * ALCANCE:
 *   Invierte UN eje (el que diga el tensor constante de ejes), para int8,
 *   int16, int32 y float32. Es solo una copia de datos en otro orden: la
 *   entrada y la salida comparten escala y punto cero.
 */

#ifndef REVERSE_V2_LMG_H
#define REVERSE_V2_LMG_H

#include "tensorflow/lite/micro/micro_op_resolver.h"

namespace lmg {

// Registro del kernel (Prepare + Eval)
TfLiteRegistration Register_REVERSE_V2();

// REVERSE_V2 no tiene opciones en el modelo: el analizador no reserva nada
TfLiteStatus ParseReverseV2(const tflite::Operator *op,
                            tflite::ErrorReporter *error_reporter,
                            tflite::BuiltinDataAllocator *allocator,
                            void **builtin_data);

}  // namespace lmg

#endif
