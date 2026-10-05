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

#define MPU_RA_CONFIG       0x1A   // DLPF_CFG en los bits 2:0
#define MPU_RA_GYRO_CONFIG  0x1B   // FS_SEL en los bits 4:3
#define MPU_RA_ACCEL_CONFIG 0x1C   // AFS_SEL en los bits 4:3

// Valores que se escriben, a partir de config.h.
#define MPU_VALOR_CONFIG        (MPU_DLPF_CFG & 0x07)
#define MPU_VALOR_GYRO_CONFIG   ((MPU_GYRO_FS_SEL & 0x03) << 3)
#define MPU_VALOR_ACCEL_CONFIG  ((MPU_ACCEL_FS_SEL & 0x03) << 3)
static_assert(MPU_ACCEL_FS_SEL == 0, "sensor_imu.cpp divide entre 16384, que supone +/-2 g");

class SensorIMU {
public:
    SensorIMU();
    bool begin();
    bool leerAcelerometro(float &ax, float &ay, float &az);
    bool configuracionCorrecta() const;
    void imprimirConfig() const;

private:
    bool _inicializado;
    uint8_t _cfg[3];        // CONFIG, GYRO_CONFIG, ACCEL_CONFIG releidos
    void _escribirRegistro(uint8_t reg, uint8_t valor);
    uint8_t _leerRegistro(uint8_t reg);
    void _leerBloque(uint8_t reg, uint8_t *buf, uint8_t len);
};

#endif
