/*
 * sliding_window.h - Buffer circular para ventana deslizante de sensores
 *
 * LOGICA:
 *   Se mantiene un buffer circular de TAMANO_VENTANA (20) muestras.
 *   Cada muestra es un vector de NUM_FEATURES (8) valores.
 *
 *   Cada 10 ms se agrega una muestra via addSample().
 *   Cada 20 ms (STRIDE samples) se ejecuta getWindow() para obtener
 *   las 20 muestras en orden cronologico y pasarlas al modelo.
 *
 *   Visualizacion (head apunta a la posicion mas reciente):
 *     Buffer: [0] [1] [2] ... [18] [19]
 *               ^head           ^head+1 (mas antigua)
 *
 *     Cuando head avanza, sobreescribe la muestra mas antigua.
 */

#ifndef SLIDING_WINDOW_H
#define SLIDING_WINDOW_H

#include <Arduino.h>
#include "config.h"

class SlidingWindow {
public:
    SlidingWindow();

    // Agrega una nueva muestra al buffer (circular)
    void addSample(const float muestra[NUM_FEATURES]);

    // Copia el buffer completo al arreglo destino en orden cronologico
    // (de mas antigua a mas reciente) para la inferencia
    void getWindow(float destino[TAMANO_VENTANA][NUM_FEATURES]) const;

    // Retorna cuantas muestras se han acumulado (para saber si el buffer
    // esta lleno antes de la primera inferencia)
    int getCount() const;

    // Retorna true si el buffer se ha llenado al menos una vez
    bool isFull() const;

    // Resetea el buffer (para cambiar de gesto o reiniciar)
    void reset();

private:
    float _buffer[TAMANO_VENTANA][NUM_FEATURES];
    int _head;      // Indice donde se escribe la siguiente muestra
    int _count;     // Total de muestras escritas desde el ultimo reset
};

#endif
