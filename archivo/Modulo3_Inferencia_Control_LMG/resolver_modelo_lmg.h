/*
 * resolver_modelo_lmg.h - Operaciones de TFLite Micro que usa el modelo
 *
 * Las 12 operaciones de Chirale_TensorFLowLite que aparecen en el modelo
 * CNN-BiLSTM-Attention INT8, mas REVERSE_V2 (reverse_v2_lmg.cpp), que la
 * libreria no trae. Lo usan Modulo3 (inferencia.cpp) y el sketch de
 * medicion Benchmark_Inferencia, que lleva una COPIA de este archivo y de
 * reverse_v2_lmg.*: si se cambia aqui, hay que copiarlo alli.
 */

#ifndef RESOLVER_MODELO_LMG_H
#define RESOLVER_MODELO_LMG_H

#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "reverse_v2_lmg.h"

// Las operaciones de la libreria mas REVERSE_V2 (propia). MicroOpResolver
// es la interfaz que usa el interprete para buscar cada operacion.
class ResolverModeloLMG : public tflite::MicroOpResolver {
public:
    ResolverModeloLMG() {
        _base.AddQuantize();
        _base.AddDequantize();
        _base.AddReshape();
        _base.AddConv2D();
        _base.AddMul();
        _base.AddAdd();
        _base.AddUnidirectionalSequenceLSTM();
        _base.AddConcatenation();
        _base.AddFullyConnected();
        _base.AddTanh();
        _base.AddSoftmax();
        _base.AddSum();
        _reverse = lmg::Register_REVERSE_V2();
        _reverse.builtin_code = tflite::BuiltinOperator_REVERSE_V2;
    }

    const TfLiteRegistration *FindOp(tflite::BuiltinOperator op) const override {
        if (op == tflite::BuiltinOperator_REVERSE_V2) return &_reverse;
        return _base.FindOp(op);
    }

    const TfLiteRegistration *FindOp(const char *op) const override {
        return _base.FindOp(op);
    }

    tflite::TfLiteBridgeBuiltinParseFunction GetOpDataParser(
        tflite::BuiltinOperator op) const override {
        if (op == tflite::BuiltinOperator_REVERSE_V2) return lmg::ParseReverseV2;
        return _base.GetOpDataParser(op);
    }

private:
    tflite::MicroMutableOpResolver<12> _base;
    TfLiteRegistration _reverse;
};

#endif
