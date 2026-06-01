/*
 * mux_ads1115.h - Driver MUX CD74HC4067 + ADC ADS1115 (reutilizado del Modulo 1)
 *
 * Funcionalidad identica al Modulo 1, pero con soporte para leer
 * tanto canales LMG (0-4) como canales FSR (5-10).
 *
 * El ADS1115 esta configurado en modo single-shot con ganancia ±4.096V,
 * resolucion efectiva de 0.125 mV por LSB.
 */

#ifndef MUX_ADS1115_H
#define MUX_ADS1115_H

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_ADS1115.h>
#include "config.h"

class MUX_ADS1115 {
public:
    MUX_ADS1115();
    bool begin();
    float leerCanal(uint8_t canal);

private:
    Adafruit_ADS1115 _ads;
    void _seleccionarCanal(uint8_t canal);
};

#endif
