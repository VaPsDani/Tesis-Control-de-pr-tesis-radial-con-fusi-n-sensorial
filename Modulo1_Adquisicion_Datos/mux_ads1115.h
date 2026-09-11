/*
 * mux_ads1115.h - Driver combinado MUX CD74HC4067 + ADC ADS1115/ADS1015
 *
 * Logica:
 *   El MUX expande 1 canal del ADC a 16 canales analogicos.
 *   Para leer el canal N: (1) setear S0..S3 con la direccion binaria de N,
 *   (2) esperar el asentamiento del MUX, (3) convertir.
 *
 *   La seleccion y la conversion estan separadas (seleccionar /
 *   leerActual) porque la trama oscura necesita DOS conversiones sobre el
 *   mismo canal, una con el LED apagado y otra encendido, sin volver a
 *   conmutar el MUX entre ambas.
 *
 * MODELO DE ADC (config.h, ADC_MODELO):
 *   El nombre de la clase se conserva por compatibilidad aunque el chip
 *   sea un ADS1015. Ambos son pin compatibles y usan la misma libreria.
 *   La conversion a mV usa computeVolts(), que conoce la ganancia y la
 *   resolucion del modelo, de modo que el resto del firmware no cambia.
 */

#ifndef MUX_ADS1115_H
#define MUX_ADS1115_H

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_ADS1X15.h>
#include "config.h"

class MUX_ADS1115 {
public:
    MUX_ADS1115();
    bool begin();

    // Conmuta el MUX y espera su asentamiento.
    void seleccionar(uint8_t canal);

    // Convierte el canal YA seleccionado. En mV.
    float leerActual();

    // seleccionar + leerActual. En mV.
    float leerCanal(uint8_t canal);

private:
#if ADC_MODELO == ADC_ADS1015
    Adafruit_ADS1015 _ads;
#else
    Adafruit_ADS1115 _ads;
#endif

    void _seleccionarCanal(uint8_t canal);
};

#endif
