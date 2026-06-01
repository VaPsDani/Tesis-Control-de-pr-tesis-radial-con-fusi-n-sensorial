/*
 * inferencia.h - Motor de inferencia TFLite Micro para ESP32
 *
 * PROCESO:
 *   1. Carga el modelo .tflite desde un array en memoria (generado por
 *      convertir_tflite.py del Modulo 2).
 *   2. Asigna un tensor arena de 40 KB para las operaciones intermedias.
 *   3. Cada 20 ms recibe una ventana de 20x9, ejecuta la inferencia y
 *      retorna la clase predicha (0-4).
 *
 * TENSOR ARENA:
 *   Memoria reservada para TFLite Micro. Debe ser suficiente para todas
 *   las operaciones del grafo. Para una CNN-BiLSTM-Attention de ~50k params,
 *   se requieren aproximadamente 30-40 KB. Ajustar segun el modelo final.
 */

#ifndef INFERENCIA_H
#define INFERENCIA_H

#include <Arduino.h>
#include "config.h"

// Tamano del tensor arena para TFLite Micro (40 KB)
#define TENSOR_ARENA_SIZE  (40 * 1024)

class MotorInferencia {
public:
    MotorInferencia();
    ~MotorInferencia();

    // Inicializa el interprete TFLite Micro
    bool begin();

    // Ejecuta la inferencia sobre la ventana de entrada
    // entrada: (TAMANO_VENTANA, NUM_FEATURES) en orden cronologico
    // Retorna: indice de la clase predicha (0-4)
    uint8_t predecir(float entrada[TAMANO_VENTANA][NUM_FEATURES]);

    // Obtener puntajes de confianza de la ultima prediccion
    void obtenerConfianza(float confianza[NUM_CLASES]) const;

    // Debug: imprime el tamano del modelo y estado
    void info();

private:
    bool _inicializado;

    // Puntero al modelo cargado (definido en modelo_gestos_tflite.h)
    const unsigned char *_modelo_data;
    unsigned int _modelo_len;

    // Tensor arena (memoria para operaciones intermedias)
    uint8_t *_tensor_arena;

    // Punteros TFLite (no se pueden declarar directamente sin includes)
    // Se manejan en el .cpp con forward declarations
    void *_interpreter;
    void *_resolver;
};

#endif
