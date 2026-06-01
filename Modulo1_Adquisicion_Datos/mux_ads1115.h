/*
 * mux_ads1115.h - Driver combinado MUX CD74HC4067 + ADC ADS1115
 *
 * Logica:
 *   El MUX expande 1 canal del ADS1115 a 16 canales analogicos.
 *   Para leer el canal N: (1) setear S0..S3 con la direccion binaria de N,
 *   (2) esperar t_setup ~5 us, (3) leer el ADS1115.
 *
 *   Los 5 LMG estan conectados a los canales 0..4 del MUX.
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
    
    // Lee el valor de un canal especifico del MUX (0-15)
    // Retorna el voltaje en milivoltios
    float leerCanal(uint8_t canal);

private:
    Adafruit_ADS1115 _ads;
    
    // Pone la direccion del canal en los pines S0..S3
    void _seleccionarCanal(uint8_t canal);
};

#endif
