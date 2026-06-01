#include "sliding_window.h"
#include <cstring>

SlidingWindow::SlidingWindow() {
    reset();
}

void SlidingWindow::addSample(const float muestra[NUM_FEATURES]) {
    // Copiar la nueva muestra en la posicion head
    for (int i = 0; i < NUM_FEATURES; i++) {
        _buffer[_head][i] = muestra[i];
    }

    // Avanzar head circularmente
    _head = (_head + 1) % TAMANO_VENTANA;

    // Incrementar contador (nunca decrece, solo en reset)
    if (_count < TAMANO_VENTANA) {
        _count++;
    }
}

void SlidingWindow::getWindow(float destino[TAMANO_VENTANA][NUM_FEATURES]) const {
    if (_count < TAMANO_VENTANA) {
        // Aun no hay suficientes datos; llenar con ceros
        memset(destino, 0, sizeof(float) * TAMANO_VENTANA * NUM_FEATURES);
        return;
    }

    // La muestra mas antigua esta en _head (porque _head apunta al
    // siguiente slot a escribir, que contiene la muestra mas vieja)
    int idx = _head;
    for (int t = 0; t < TAMANO_VENTANA; t++) {
        for (int f = 0; f < NUM_FEATURES; f++) {
            destino[t][f] = _buffer[idx][f];
        }
        idx = (idx + 1) % TAMANO_VENTANA;
    }
}

int SlidingWindow::getCount() const {
    return _count;
}

bool SlidingWindow::isFull() const {
    return _count >= TAMANO_VENTANA;
}

void SlidingWindow::reset() {
    _head = 0;
    _count = 0;
    memset(_buffer, 0, sizeof(_buffer));
}
