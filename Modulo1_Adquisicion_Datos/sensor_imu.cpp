/*
 * sensor_imu.cpp - Implementacion MPU6050
 *
 * Estrategia de lectura:
 *   El MPU6050 se configura en modo passthrough (sin DMP). Se leen
 *   directamente acelerometro y giroscopio en crudo y se escalan a
 *   unidades fisicas. No se calculan cuaterniones: el pipeline de deep
 *   learning aprende las relaciones temporales a partir de los ejes
 *   crudos, y una fusion de actitud en el ESP32 solo anadiria latencia
 *   y una fuente de error propia.
 *
 *   Una sola transaccion I2C de 14 bytes desde 0x3B cubre los 6 ejes,
 *   asi que leerIMUCompleta y leerAcelerometro cuestan lo mismo en el
 *   bus (~0.4 ms a 400 kHz).
 */

#include "sensor_imu.h"

SensorIMU::SensorIMU() : _inicializado(false) {}

bool SensorIMU::begin() {
    Wire.beginTransmission(MPU_ADDR);
    if (Wire.endTransmission() != 0) {
        return false;   // MPU6050 no detectado
    }

    // Salir del modo sleep
    _escribirRegistro(MPU_RA_PWR_MGMT_1, 0x00);
    delay(100);

    _inicializado = true;
    return true;
}

bool SensorIMU::leerIMUCompleta(float &ax, float &ay, float &az,
                                float &gx, float &gy, float &gz) {
    if (!_inicializado) return false;

    // Un unico bloque de 14 bytes: accel (6) + temp (2) + gyro (6).
    // Los bytes 6 y 7 son la temperatura y se ignoran.
    uint8_t buf[14];
    _leerBloque(MPU_RA_ACCEL_XOUT, buf, 14);

    // Big-endian a int16 con signo
    int16_t rax = (int16_t)((buf[0]  << 8) | buf[1]);
    int16_t ray = (int16_t)((buf[2]  << 8) | buf[3]);
    int16_t raz = (int16_t)((buf[4]  << 8) | buf[5]);
    int16_t rgx = (int16_t)((buf[8]  << 8) | buf[9]);
    int16_t rgy = (int16_t)((buf[10] << 8) | buf[11]);
    int16_t rgz = (int16_t)((buf[12] << 8) | buf[13]);

    // Escalar a unidades fisicas
    ax = (float)rax / MPU_LSB_POR_G;
    ay = (float)ray / MPU_LSB_POR_G;
    az = (float)raz / MPU_LSB_POR_G;
    gx = (float)rgx / MPU_LSB_POR_DPS;
    gy = (float)rgy / MPU_LSB_POR_DPS;
    gz = (float)rgz / MPU_LSB_POR_DPS;

    return true;
}

bool SensorIMU::leerAcelerometro(float &ax, float &ay, float &az) {
    float gx, gy, gz;
    return leerIMUCompleta(ax, ay, az, gx, gy, gz);
}

// ========== PRIVADAS: Comunicacion I2C directa ==========

void SensorIMU::_escribirRegistro(uint8_t reg, uint8_t valor) {
    Wire.beginTransmission(MPU_ADDR);
    Wire.write(reg);
    Wire.write(valor);
    Wire.endTransmission();
}

uint8_t SensorIMU::_leerRegistro(uint8_t reg) {
    Wire.beginTransmission(MPU_ADDR);
    Wire.write(reg);
    Wire.endTransmission(false);
    Wire.requestFrom(MPU_ADDR, (uint8_t)1);
    return Wire.read();
}

void SensorIMU::_leerBloque(uint8_t reg, uint8_t *buf, uint8_t len) {
    Wire.beginTransmission(MPU_ADDR);
    Wire.write(reg);
    Wire.endTransmission(false);
    Wire.requestFrom(MPU_ADDR, len);
    for (uint8_t i = 0; i < len; i++) {
        buf[i] = Wire.read();
    }
}
