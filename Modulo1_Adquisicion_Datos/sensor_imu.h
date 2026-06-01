/*
 * sensor_imu.h - Driver para MPU6050 con lectura de cuaterniones via DMP
 *
 * El MPU6050 incorpora un DMP (Digital Motion Processor) que
 * fusiona acelerometro + giroscopio para generar cuaterniones
 * directamente, reduciendo la carga de calculo en el ESP32.
 *
 * Cuaternion q = (w, x, y, z) representa la orientacion espacial
 * del antebrazo, util como contexto para el clasificador de gestos.
 */

#ifndef SENSOR_IMU_H
#define SENSOR_IMU_H

#include <Arduino.h>
#include <Wire.h>
#include "config.h"

// Registrar MPU6050 (modo DMP)
#define MPU_RA_XG_OFFS_TC  0x00
#define MPU_RA_PWR_MGMT_1  0x6B
#define MPU_RA_WHO_AM_I    0x75

class SensorIMU {
public:
    SensorIMU();
    bool begin();
    bool leerCuaterniones(float &qw, float &qx, float &qy, float &qz);
    
private:
    bool _dmpInicializado;
    
    // Lectura raw de registros I2C
    void _escribirRegistro(uint8_t reg, uint8_t valor);
    uint8_t _leerRegistro(uint8_t reg);
    void _leerBloque(uint8_t reg, uint8_t *buf, uint8_t len);
    
    // Inicializacion basica (sin DMP) - modo passthrough
    bool _initBasic();
};

#endif
