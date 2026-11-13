/*
 * intercambio_nucleos.h - Paso de datos entre el nucleo 0 y el nucleo 1
 *
 * REPARTO:
 *   Nucleo 0 (tarea de tiempo real, cada 10 ms): todo lo que tiene plazo y
 *     TODO el bus I2C: LMG e IMU, FSR, frenado, rampa y PCA9685. Cada STRIDE
 *     muestras publica aqui una copia de la ventana, ya normalizada.
 *   Nucleo 1 (loop de Arduino): solo la inferencia, calculo puro. Copia la
 *     ultima ventana, clasifica y deja aqui el gesto.
 *   El nucleo 0 lee el resultado en su ciclo y es el unico que mueve los
 *     servos.
 *
 * COPIA ATOMICA:
 *   Un cerrojo de giro (portMUX) protege las dos copias. La seccion critica
 *   es un memcpy de 640 bytes (20 x 8 float), del orden de 2 us: el nucleo 0
 *   nunca escribe una ventana a medias mientras el nucleo 1 la lee, y
 *   ninguno espera de forma apreciable al otro.
 *
 * SI LA INFERENCIA ES MAS LENTA QUE EL STRIDE:
 *   Gana la ventana mas reciente. El nucleo 1 toma la ultima publicada
 *   cuando termina la anterior; las intermedias se cuentan como descartadas.
 *   El muestreo del nucleo 0 no espera nunca a la inferencia.
 */

#ifndef INTERCAMBIO_NUCLEOS_H
#define INTERCAMBIO_NUCLEOS_H

#include <Arduino.h>
#include <string.h>
#include "config.h"

struct ResultadoInferencia {
    uint8_t  gesto          = GESTO_REST;
    uint32_t n              = 0;   // resultados publicados hasta ahora
    uint32_t secVentana     = 0;   // numero de la ventana clasificada
    uint32_t tVentanaUs     = 0;   // micros() cuando el nucleo 0 la publico
    uint32_t tInferenciaUs  = 0;   // Reset + Invoke en el nucleo 1
    uint32_t errores        = 0;   // inferencias fallidas (acumulado)
    uint32_t descartadas    = 0;   // ventanas que no llegaron a clasificarse
};

class IntercambioNucleos {
public:
    // Nucleo 0: publica una ventana. Devuelve su numero de secuencia.
    uint32_t publicarVentana(const float v[TAMANO_VENTANA][NUM_FEATURES], uint32_t tUs) {
        portENTER_CRITICAL(&_mux);
        memcpy(_ventana, v, sizeof(_ventana));
        _tVentanaUs = tUs;
        const uint32_t sec = ++_secVentana;
        portEXIT_CRITICAL(&_mux);
        return sec;
    }

    // Nucleo 0: numero de la ultima ventana publicada (para descartar
    // resultados de ventanas anteriores a un 'S' o a una calibracion).
    uint32_t ultimaVentana() {
        portENTER_CRITICAL(&_mux);
        const uint32_t s = _secVentana;
        portEXIT_CRITICAL(&_mux);
        return s;
    }

    // Nucleo 1: copia la ultima ventana publicada.
    uint32_t copiarVentana(float v[TAMANO_VENTANA][NUM_FEATURES], uint32_t &tUs) {
        portENTER_CRITICAL(&_mux);
        memcpy(v, _ventana, sizeof(_ventana));
        tUs = _tVentanaUs;
        const uint32_t sec = _secVentana;
        portEXIT_CRITICAL(&_mux);
        return sec;
    }

    // Nucleo 1: deja el resultado de la ventana 'sec'.
    void publicarResultado(uint8_t gesto, uint32_t sec, uint32_t tVentanaUs,
                           uint32_t tInferenciaUs, bool ok) {
        portENTER_CRITICAL(&_mux);
        if (_res.secVentana != 0 && sec > _res.secVentana + 1)
            _res.descartadas += sec - _res.secVentana - 1;
        _res.gesto = gesto;
        _res.secVentana = sec;
        _res.tVentanaUs = tVentanaUs;
        _res.tInferenciaUs = tInferenciaUs;
        if (!ok) _res.errores++;
        _res.n++;
        portEXIT_CRITICAL(&_mux);
    }

    // Nucleo 0: copia el ultimo resultado. Devuelve true si es nuevo
    // respecto a 'nVisto', que se actualiza.
    bool leerResultado(ResultadoInferencia &r, uint32_t &nVisto) {
        portENTER_CRITICAL(&_mux);
        r = _res;
        portEXIT_CRITICAL(&_mux);
        if (r.n == nVisto) return false;
        nVisto = r.n;
        return true;
    }

private:
    portMUX_TYPE _mux = portMUX_INITIALIZER_UNLOCKED;
    float _ventana[TAMANO_VENTANA][NUM_FEATURES] = {};
    uint32_t _tVentanaUs = 0;
    uint32_t _secVentana = 0;
    ResultadoInferencia _res;
};

#endif
