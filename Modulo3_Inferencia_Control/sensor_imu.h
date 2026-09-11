/*
 * sensor_imu.h - Driver MPU6050 para contexto espacial
 *
 * Proporciona los 3 canales de acelerometro que consume el modelo.
 * Ver sensor_imu.cpp del Modulo 1 para documentacion detallada.
 */

#ifndef SENSOR_IMU_H
#define SENSOR_IMU_H

#include <Arduino.h>
#include <Wire.h>
#include "config.h"

class SensorIMU {
public:
    SensorIMU();
    bool begin();
    bool leerAcelerometro(float &ax, float &ay, float &az);

private:
    bool _inicializado;
    void _escribirRegistro(uint8_t reg, uint8_t valor);
    uint8_t _leerRegistro(uint8_t reg);
    void _leerBloque(uint8_t reg, uint8_t *buf, uint8_t len);
};

#endif
