/*
 * sensor_imu.h - Driver para MPU6050 (acelerometro + giroscopio)
 *
 * QUE ENTREGA Y POR QUE:
 *   El modelo consume 3 canales: el acelerometro normalizado a g.
 *   El CSV de captura guarda los 6 ejes crudos, acelerometro Y
 *   giroscopio.
 *
 *   La asimetria es deliberada. La lectura I2C de 14 bytes desde el
 *   registro 0x3B abarca acelerometro (6), temperatura (2) y giroscopio
 *   (6): los bytes del giroscopio YA cruzan el bus, se usen o no.
 *   Guardarlos cuesta cero, y recuperarlos despues significaria volver a
 *   convocar a los 10 voluntarios. El filtrado a los canales del modelo
 *   se hace en preprocesamiento.py, nunca aqui.
 *
 * POR QUE DESAPARECIO EL CUARTO CANAL:
 *   La version anterior entregaba cuatro "pseudo-cuaterniones"
 *   (qw, qx, qy, qz), donde qx, qy, qz eran el acelerometro normalizado
 *   y qw = constrain(sqrt(qx^2+qy^2+qz^2)/2, 0, 1).
 *
 *   qw era una funcion determinista de los otros tres: no aportaba
 *   informacion que la red no pudiera recomputar con una operacion, y
 *   costaba un canal de entrada. Eliminarlo deja el vector en 5 LMG + 3
 *   acelerometro = 8 canales, exactamente la misma forma que la linea
 *   base sobre NinaPro DB5 (5 sEMG + 3 ACC), lo que hace directa la
 *   comparacion entre ramas.
 */

#ifndef SENSOR_IMU_H
#define SENSOR_IMU_H

#include <Arduino.h>
#include <Wire.h>
#include "config.h"

// Registros del MPU6050
#define MPU_RA_XG_OFFS_TC  0x00
#define MPU_RA_PWR_MGMT_1  0x6B
#define MPU_RA_WHO_AM_I    0x75
#define MPU_RA_ACCEL_XOUT  0x3B   // inicio del bloque de 14 bytes

// Factores de escala del MPU6050 en su configuracion por defecto
#define MPU_LSB_POR_G      16384.0f   // rango +/-2 g
#define MPU_LSB_POR_DPS    131.0f     // rango +/-250 grados/s

class SensorIMU {
public:
    SensorIMU();
    bool begin();

    // Los 6 ejes crudos escalados a unidades fisicas (g y grados/s).
    // Es la lectura primitiva y la que alimenta el CSV de captura.
    bool leerIMUCompleta(float &ax, float &ay, float &az,
                         float &gx, float &gy, float &gz);

    // Solo el acelerometro: los 3 canales que entran al modelo.
    bool leerAcelerometro(float &ax, float &ay, float &az);

private:
    bool _inicializado;

    void _escribirRegistro(uint8_t reg, uint8_t valor);
    uint8_t _leerRegistro(uint8_t reg);
    void _leerBloque(uint8_t reg, uint8_t *buf, uint8_t len);
};

#endif
