/*
 * inferencia.cpp - Implementacion del motor de inferencia TFLite Micro
 *
 * DEPENDENCIAS (Arduino IDE / arduino-cli):
 *   - Chirale_TensorFLowLite 2.0.0 (gestor de librerias de Arduino). Es
 *     TensorFlow Lite Micro empaquetado para ESP32 y mbed. Sustituye a
 *     TensorFlowLite_ESP32 1.0.0, que no compila con el core esp32 3.x.
 *
 * El archivo modelo_gestos_tflite.h se genera automaticamente con
 * convertir_tflite.py y debe estar presente en esta carpeta.
 *
 * OPERACIONES:
 *   En lugar de AllOpsResolver (todas las operaciones, mucha flash) se
 *   registran solo las 13 que usa el modelo CNN-BiLSTM-Attention INT8.
 *   REVERSE_V2 no esta en la libreria y se aporta desde reverse_v2_lmg.cpp.
 *   Si el modelo cambia y aparece otra operacion, begin() falla con
 *   "Didn't find op for builtin opcode ..." en el monitor serie.
 */

#include "inferencia.h"
#include "modelo_gestos_tflite.h"

// Includes de TFLite Micro
#include <Chirale_TensorFlowLite.h>
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/schema/schema_generated.h"
#include "resolver_modelo_lmg.h"


// ============================================================
// Implementacion
// ============================================================

MotorInferencia::MotorInferencia()
    : _inicializado(false),
      _modelo_data(modelo_gestos_tflite),
      _modelo_len(modelo_gestos_tflite_len),
      _tensor_arena(nullptr),
      _interpreter(nullptr),
      _resolver(nullptr) {}

MotorInferencia::~MotorInferencia() {
    if (_tensor_arena) delete[] _tensor_arena;
    if (_resolver) delete static_cast<ResolverModeloLMG *>(_resolver);
    if (_interpreter) delete static_cast<tflite::MicroInterpreter *>(_interpreter);
}

bool MotorInferencia::begin() {
    // ========== 1. Verificar modelo ==========
    if (_modelo_data == nullptr || _modelo_len == 0) {
        Serial.println("[TFLITE] ERROR: Modelo no cargado");
        return false;
    }

    Serial.printf("[TFLITE] Tamano del modelo: %u bytes (%.2f KB)\n",
                  _modelo_len, _modelo_len / 1024.0f);

    // ========== 2. Asignar tensor arena ==========
    _tensor_arena = new (std::nothrow) uint8_t[TENSOR_ARENA_SIZE];
    if (_tensor_arena == nullptr) {
        Serial.println("[TFLITE] ERROR: No se pudo asignar tensor arena");
        return false;
    }

    // ========== 3. Crear resolver de operaciones ==========
    _resolver = new (std::nothrow) ResolverModeloLMG();
    if (_resolver == nullptr) {
        Serial.println("[TFLITE] ERROR: No se pudo crear el resolver");
        return false;
    }

    // ========== 4. Crear interprete ==========
    const tflite::Model *model = tflite::GetModel(_modelo_data);
    if (model->version() != TFLITE_SCHEMA_VERSION) {
        Serial.println("[TFLITE] ERROR: Version del esquema no coincide");
        return false;
    }

    // MicroInterpreter necesita el modelo, el resolver, el tensor arena y su tamano
    _interpreter = new tflite::MicroInterpreter(
        model,
        *static_cast<ResolverModeloLMG *>(_resolver),
        _tensor_arena,
        TENSOR_ARENA_SIZE
    );

    // ========== 5. Verificar tensores ==========
    auto *interp = static_cast<tflite::MicroInterpreter *>(_interpreter);

    TfLiteStatus status = interp->AllocateTensors();
    if (status != kTfLiteOk) {
        Serial.println("[TFLITE] ERROR: Fallo al asignar tensores");
        return false;
    }

    // Verificar dimensiones de entrada
    TfLiteTensor *input = interp->input(0);
    if (input->dims->size != 3 ||
        input->dims->data[0] != 1 ||
        input->dims->data[1] != TAMANO_VENTANA ||
        input->dims->data[2] != NUM_FEATURES) {
        Serial.println("[TFLITE] ERROR: Dimensiones de entrada inesperadas");
        Serial.printf("  Esperado: [1, %d, %d]\n", TAMANO_VENTANA, NUM_FEATURES);
        Serial.printf("  Obtenido: [%d, %d, %d]\n",
                      input->dims->data[0],
                      input->dims->data[1],
                      input->dims->data[2]);
        return false;
    }

    // Verificar dimensiones de salida
    TfLiteTensor *output = interp->output(0);
    if (output->dims->size != 2 ||
        output->dims->data[0] != 1 ||
        output->dims->data[1] != NUM_CLASES) {
        Serial.println("[TFLITE] ERROR: Dimensiones de salida inesperadas");
        return false;
    }

    // Informacion del interprete
    Serial.printf("[TFLITE] Arena usada: %d / %d bytes\n",
                  interp->arena_used_bytes(), TENSOR_ARENA_SIZE);

    _inicializado = true;
    return true;
}

uint8_t MotorInferencia::predecir(float entrada[TAMANO_VENTANA][NUM_FEATURES]) {
    // Corre en el nucleo 1: calculo puro, sin Serial ni ningun periferico.
    // Los fallos se devuelven en ultimaOk() y los reporta el nucleo 0.
    _ultimaOk = false;
    if (!_inicializado) return GESTO_REST;

    auto *interp = static_cast<tflite::MicroInterpreter *>(_interpreter);

    // ========== Estado de la LSTM a cero ==========
    // La LSTM de TFLite guarda su estado (h y c) en tensores variables que
    // PERSISTEN entre Invoke(). Sin esto, cada ventana arrancaria con el
    // estado que dejo la anterior y el modelo no calcularia lo mismo que en
    // el entrenamiento, donde cada ventana es independiente (medido sobre
    // NinaPro: unos 2 puntos menos de exactitud). Cuesta un memset de ~200 B.
    if (interp->Reset() != kTfLiteOk) return GESTO_REST;
    TfLiteTensor *input = interp->input(0);

    // ========== Copiar datos de entrada al tensor ==========
    // El tensor de entrada espera: [1, TAMANO_VENTANA, NUM_FEATURES]
    float *input_data = input->data.f;
    for (int t = 0; t < TAMANO_VENTANA; t++) {
        for (int f = 0; f < NUM_FEATURES; f++) {
            input_data[t * NUM_FEATURES + f] = entrada[t][f];
        }
    }

    // ========== Ejecutar inferencia ==========
    if (interp->Invoke() != kTfLiteOk) return GESTO_REST;
    _ultimaOk = true;

    // ========== Leer salida ==========
    TfLiteTensor *output = interp->output(0);
    float *prediccion = output->data.f;

    // Encontrar la clase con mayor probabilidad
    uint8_t clase_max = 0;
    float prob_max = prediccion[0];
    for (uint8_t i = 1; i < NUM_CLASES; i++) {
        if (prediccion[i] > prob_max) {
            prob_max = prediccion[i];
            clase_max = i;
        }
    }

    // Umbral de confianza: si todas las probabilidades son muy bajas,
    // retornar REST como default seguro
    if (prob_max < 0.4f) {
        return GESTO_REST;
    }

    return clase_max;
}

void MotorInferencia::obtenerConfianza(float confianza[NUM_CLASES]) const {
    if (!_inicializado) return;

    auto *interp = static_cast<tflite::MicroInterpreter *>(_interpreter);
    TfLiteTensor *output = interp->output(0);
    float *data = output->data.f;

    for (uint8_t i = 0; i < NUM_CLASES; i++) {
        confianza[i] = data[i];
    }
}

void MotorInferencia::info() {
    Serial.printf("[TFLITE] Modelo: %u bytes\n", _modelo_len);
    Serial.printf("[TFLITE] Arena: %u bytes\n", TENSOR_ARENA_SIZE);

    if (_inicializado) {
        auto *interp = static_cast<tflite::MicroInterpreter *>(_interpreter);
        Serial.printf("[TFLITE] Arena usada: %d bytes\n", interp->arena_used_bytes());
        Serial.printf("[TFLITE] Input tensores: %d\n", interp->inputs_size());
        Serial.printf("[TFLITE] Output tensores: %d\n", interp->outputs_size());
    }
}
