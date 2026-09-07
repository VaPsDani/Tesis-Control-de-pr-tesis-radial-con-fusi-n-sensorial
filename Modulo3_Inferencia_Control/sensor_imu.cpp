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

// Devuelve los 3 canales de acelerometro que consume el modelo,
// normalizados a g. La inferencia no necesita el giroscopio: el vector
// de entrada es 5 LMG + 3 ACC = 8 canales, la misma forma con la que se
// valido la arquitectura sobre NinaPro DB5.
//
// El cuarto canal de la version anterior (qw = |a|/2 saturado) era una
// funcion determinista de ax, ay, az. No aportaba informacion que la
// red no pudiera recomputar, y ocupaba un canal de entrada.
bool SensorIMU::leerAcelerometro(float &ax, float &ay, float &az) {
    if (!_inicializado) return false;

    uint8_t buf[14];
    _leerBloque(0x3B, buf, 14);

    int16_t rax = (int16_t)((buf[0] << 8) | buf[1]);
    int16_t ray = (int16_t)((buf[2] << 8) | buf[3]);
    int16_t raz = (int16_t)((buf[4] << 8) | buf[5]);

    // +/-2 g -> 16384 LSB/g
    ax = (float)rax / 16384.0f;
    ay = (float)ray / 16384.0f;
    az = (float)raz / 16384.0f;

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
