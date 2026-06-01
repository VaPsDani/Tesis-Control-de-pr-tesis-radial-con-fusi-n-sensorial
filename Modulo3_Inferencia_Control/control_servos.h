/*
 * control_servos.h - Driver PCA9685 para control de servos MG90S
 *
 * Los 5 servos corresponden a los 5 dedos de la protesis:
 *   0: Pulgar, 1: Indice, 2: Medio, 3: Anular, 4: Menique
 *
 * MAPEO GESTO → POSICIONES:
 *   Cada gesto tiene un angulo predefinido para cada servo.
 *   0°  = dedo extendido (abierto)
 *   180° = dedo flexionado (cerrado)
 *
 *   Los angulos se convierten a pulsos PWM (500-2500 us) usando
 *   la formula: pulso = map(angulo, 0, 180, SERVO_PULSE_MIN, SERVO_PULSE_MAX)
 *
 * LAZO CERRADO CON FSR:
 *   Cuando un servo se esta cerrando y su FSR supera el umbral,
 *   se frena ese servo especifico estableciendo su angulo actual
 *   como limite, evitando que continue apretando.
 */

#ifndef CONTROL_SERVOS_H
#define CONTROL_SERVOS_H

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>
#include "config.h"

// Angulos predefinidos para cada gesto [servo][angulo]
// Los valores se calibran experimentalmente
// 0 = abierto (extendido), 180 = cerrado (flexionado)
struct ConfigGesto {
    uint8_t angulos[NUM_SERVOS];   // grados para cada servo
    const char *nombre;
};

class ControlServos {
public:
    ControlServos();
    bool begin();

    // Ejecuta un gesto: mueve todos los servos a las posiciones del gesto
    void ejecutarGesto(uint8_t gesto_id);

    // Frena un servo especifico (lo deja en su posicion actual)
    void frenarServo(uint8_t servo_id);

    // Retorna el angulo actual de un servo
    uint8_t getAnguloActual(uint8_t servo_id) const;

    // Establece manualmente el angulo de un servo (usado por feedback FSR)
    void setAnguloServo(uint8_t servo_id, uint8_t angulo);

    // Configuracion de gestos predefinidos
    static const ConfigGesto gestos[NUM_CLASES];

private:
    Adafruit_PWMServoDriver _pca;
    uint8_t _angulos_actuales[NUM_SERVOS];
    bool _inicializado;

    // Convierte angulo (0-180) a pulso PWM para PCA9685
    // PCA9685 usa cuentas de 0-4096 para el ciclo completo de 20 ms
    // 500 us → 102 cuentas, 2500 us → 512 cuentas
    uint16_t _anguloAPulso(uint8_t angulo);

    // Envia el pulso a un canal especifico del PCA9685
    void _escribirPulso(uint8_t servo_id, uint16_t pulso);
};

#endif
