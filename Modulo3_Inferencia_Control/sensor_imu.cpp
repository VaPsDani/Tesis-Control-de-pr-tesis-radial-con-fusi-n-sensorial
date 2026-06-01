#include "sensor_imu.h"

SensorIMU::SensorIMU() : _inicializado(false) {}

bool SensorIMU::begin() {
    Wire.beginTransmission(MPU_ADDR);
    if (Wire.endTransmission() != 0) return false;

    // Despertar MPU6050 (PWR_MGMT_1 = 0)
    _escribirRegistro(0x6B, 0x00);
    delay(100);
    _inicializado = true;
    return true;
}

bool SensorIMU::leerCuaterniones(float &qw, float &qx, float &qy, float &qz) {
    if (!_inicializado) return false;

    uint8_t buf[14];
    _leerBloque(0x3B, buf, 14);

    int16_t ax = (buf[0]  << 8) | buf[1];
    int16_t ay = (buf[2]  << 8) | buf[3];
    int16_t az = (buf[4]  << 8) | buf[5];
    // int16_t gx = (buf[8]  << 8) | buf[9];
    // int16_t gy = (buf[10] << 8) | buf[11];
    // int16_t gz = (buf[12] << 8) | buf[13];

    float acc_norm = sqrt(ax*ax + ay*ay + az*az) / 16384.0f;

    qw = constrain(acc_norm / 2.0f, 0.0f, 1.0f);
    qx = (float)ax / 16384.0f;
    qy = (float)ay / 16384.0f;
    qz = (float)az / 16384.0f;

    return true;
}

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
