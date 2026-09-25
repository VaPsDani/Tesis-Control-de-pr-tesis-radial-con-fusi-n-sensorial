/*
 * reverse_v2_lmg.cpp - Implementacion de REVERSE_V2 (ver reverse_v2_lmg.h)
 */

#include "reverse_v2_lmg.h"

#include <string.h>

#include "tensorflow/lite/c/common.h"
#include "tensorflow/lite/kernels/kernel_util.h"
#include "tensorflow/lite/micro/kernels/kernel_util.h"
#include "tensorflow/lite/micro/micro_log.h"

namespace lmg {
namespace {

constexpr int kEntrada = 0;
constexpr int kEjes = 1;
constexpr int kSalida = 0;

int bytesPorElemento(TfLiteType tipo) {
    switch (tipo) {
        case kTfLiteInt8:    return 1;
        case kTfLiteInt16:   return 2;
        case kTfLiteInt32:   return 4;
        case kTfLiteFloat32: return 4;
        default:             return 0;
    }
}

TfLiteStatus Prepare(TfLiteContext *context, TfLiteNode *node) {
    tflite::MicroContext *mc = tflite::GetMicroContext(context);
    TF_LITE_ENSURE_EQ(context, tflite::NumInputs(node), 2);
    TF_LITE_ENSURE_EQ(context, tflite::NumOutputs(node), 1);

    TfLiteTensor *entrada = mc->AllocateTempInputTensor(node, kEntrada);
    TfLiteTensor *ejes = mc->AllocateTempInputTensor(node, kEjes);
    TfLiteTensor *salida = mc->AllocateTempOutputTensor(node, kSalida);
    TF_LITE_ENSURE(context, entrada != nullptr && ejes != nullptr && salida != nullptr);

    TF_LITE_ENSURE_TYPES_EQ(context, entrada->type, salida->type);
    TF_LITE_ENSURE(context, bytesPorElemento(entrada->type) > 0);
    TF_LITE_ENSURE_TYPES_EQ(context, ejes->type, kTfLiteInt32);
    // Solo un eje: es lo que genera el conversor para la BiLSTM
    TF_LITE_ENSURE_EQ(context, tflite::NumElements(ejes), 1);
    TF_LITE_ENSURE_EQ(context, tflite::NumDimensions(entrada), tflite::NumDimensions(salida));
    if (entrada->type == kTfLiteInt8 || entrada->type == kTfLiteInt16) {
        // Se copia sin recuantizar: exige el mismo punto cero y casi la misma
        // escala. El conversor no garantiza escalas identicas: en este modelo,
        // tras la LSTM hacia atras difieren un 0.07 % (error < 0.1 paso).
        // Por encima del 1 % copiar seria incorrecto y se rechaza.
        TF_LITE_ENSURE_EQ(context, entrada->params.zero_point, salida->params.zero_point);
        const float si = entrada->params.scale, so = salida->params.scale;
        const float dif = (si > so ? si - so : so - si) / (so > 0.0f ? so : 1.0f);
        if (dif > 0.01f) {
            MicroPrintf("REVERSE_V2: escalas distintas (%f vs %f), no soportado", si, so);
            return kTfLiteError;
        }
    }

    mc->DeallocateTempTfLiteTensor(entrada);
    mc->DeallocateTempTfLiteTensor(ejes);
    mc->DeallocateTempTfLiteTensor(salida);
    return kTfLiteOk;
}

TfLiteStatus Eval(TfLiteContext *context, TfLiteNode *node) {
    const TfLiteEvalTensor *entrada = tflite::micro::GetEvalInput(context, node, kEntrada);
    const TfLiteEvalTensor *ejes = tflite::micro::GetEvalInput(context, node, kEjes);
    TfLiteEvalTensor *salida = tflite::micro::GetEvalOutput(context, node, kSalida);

    const int rango = entrada->dims->size;
    int eje = tflite::micro::GetTensorData<int32_t>(ejes)[0];
    if (eje < 0) eje += rango;
    if (eje < 0 || eje >= rango) {
        MicroPrintf("REVERSE_V2: eje %d fuera de rango (rango %d)", eje, rango);
        return kTfLiteError;
    }

    // Vista del tensor como [externo][n][interno], invirtiendo el indice n
    int externo = 1, interno = 1;
    for (int i = 0; i < eje; i++) externo *= entrada->dims->data[i];
    for (int i = eje + 1; i < rango; i++) interno *= entrada->dims->data[i];
    const int n = entrada->dims->data[eje];
    const size_t bloque = static_cast<size_t>(interno) * bytesPorElemento(entrada->type);

    const uint8_t *src = static_cast<const uint8_t *>(entrada->data.data);
    uint8_t *dst = static_cast<uint8_t *>(salida->data.data);
    for (int o = 0; o < externo; o++) {
        const uint8_t *s = src + static_cast<size_t>(o) * n * bloque;
        uint8_t *d = dst + static_cast<size_t>(o) * n * bloque;
        for (int i = 0; i < n; i++) {
            memcpy(d + static_cast<size_t>(n - 1 - i) * bloque, s + static_cast<size_t>(i) * bloque, bloque);
        }
    }
    return kTfLiteOk;
}

}  // namespace

TfLiteRegistration Register_REVERSE_V2() {
    return tflite::micro::RegisterOp(nullptr, Prepare, Eval);
}

TfLiteStatus ParseReverseV2(const tflite::Operator *, tflite::ErrorReporter *,
                            tflite::BuiltinDataAllocator *, void **builtin_data) {
    *builtin_data = nullptr;
    return kTfLiteOk;
}

}  // namespace lmg
