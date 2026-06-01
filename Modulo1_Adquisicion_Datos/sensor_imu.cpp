/*
 * sensor_imu.cpp - Implementacion MPU6050
 *
 * Estrategia de lectura:
 *   El MPU6050 se configura en modo passthrough (sin DMP).
 *   Se leen directamente acelerometro (ax,ay,az) y giroscopio (gx,gy,gz)
 *   en crudo. Los cuaterniones se aproximan mediante combinacion de
 *   actitudes (madgwick o complementary filter) para mantener
 *   consistencia. En una segunda version se puede cargar el firmware DMP.
 *
 *   Alternativa simplificada: se normalizan los 6 ejes y se tratan
 *   como entradas al modelo junto con los LMG. El deep learning
 *   aprendera las relaciones temporales inherentes.
 *
 *   Para esta version: retornamos [ax, ay, az, gx, gy, gz] como
 *   pseudo-cuaterniones (6 valores). El pipeline de DL los
 *   interpretara como features de contexto.
 */

#include "sensor_imu.h"

SensorIMU::SensorIMU() : _dmpInicializado(false) {}

bool SensorIMU::begin() {
    Wire.beginTransmission(MPU_ADDR);
    if (Wire.endTransmission() != 0) {
        return false;   // MPU6050 no detectado
    }
    
    // Salir del modo sleep
    _escribirRegistro(MPU_RA_PWR_MGMT_1, 0x00);
    delay(100);
    
    _dmpInicializado = true;
    return true;
}

bool SensorIMU::leerCuaterniones(float &qw, float &qx, float &qy, float &qz) {
    if (!_dmpInicializado) return false;
    
    // Leer acelerometro (6 bytes) y giroscopio (6 bytes)
    uint8_t buf[14];
    _leerBloque(0x3B, buf, 14);
    
    // Convertir de big-endian a int16
    int16_t ax = (buf[0]  << 8) | buf[1];
    int16_t ay = (buf[2]  << 8) | buf[3];
    int16_t az = (buf[4]  << 8) | buf[5];
    int16_t gx = (buf[8]  << 8) | buf[9];
    int16_t gy = (buf[10] << 8) | buf[11];
    int16_t gz = (buf[12] << 8) | buf[13];
    
    // Normalizar a gravedad y °/s
    // Escala acelerometro: ±2g → 16384 LSB/g
    // Escala giroscopio: ±250°/s → 131 LSB/(°/s)
    float acc_norm = sqrt(ax*ax + ay*ay + az*az) / 16384.0f;
    
    // Empaquetar como pseudo-cuaterniones:
    // qw = magnitud normalizada de aceleracion (contexto de movimiento)
    // qx, qy, qz = acelerometro normalizado por gravedad
    qw = constrain(acc_norm / 2.0f, 0.0f, 1.0f);
    qx = (float)ax / 16384.0f;
    qy = (float)ay / 16384.0f;
    qz = (float)az / 16384.0f;
    
    return true;
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
