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
 * MOVIMIENTO POR RAMPA:
 *   ejecutarGesto() fija un OBJETIVO por servo; no salta a el. La rampa
 *   avanza el angulo comandado a RAMPA_GRADOS_POR_S en cada llamada a
 *   actualizarRampa(), que hay que invocar periodicamente desde el
 *   bucle principal.
 *
 *   Esto no es un adorno: sin rampa el lazo de fuerza NO PUEDE existir.
 *   La version anterior comandaba el angulo final de una sola vez, el
 *   MG90S viajaba libre a ~600 grados/s hasta el tope y frenarServo()
 *   se limitaba a imprimir un mensaje, porque ya no habia nada que
 *   frenar. El umbral FSR se detectaba y se descartaba.
 *
 * LAZO CERRADO CON FSR:
 *   Cuando un servo se esta cerrando y su FSR supera el umbral,
 *   frenarServo() congela el objetivo en el angulo comandado en ese
 *   instante. El dedo deja de apretar y mantiene la posicion.
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

    // Fija el objetivo de cada servo. NO salta: la rampa se encarga.
    void ejecutarGesto(uint8_t gesto_id);

    // Avanza la rampa hacia los objetivos. Llamar periodicamente desde
    // el bucle principal; respeta RAMPA_PERIODO_MS internamente y solo
    // escribe en el PCA9685 los servos cuyo angulo cambio, de modo que
    // mantener una postura no cuesta trafico I2C.
    void actualizarRampa(unsigned long ahora_ms);

    // Congela el objetivo en el angulo comandado ahora mismo.
    void frenarServo(uint8_t servo_id);

    // True si el servo sigue avanzando hacia su objetivo.
    bool enMovimiento(uint8_t servo_id) const;

    // Angulo comandado en este instante (no el objetivo).
    uint8_t getAnguloActual(uint8_t servo_id) const;

    // Salto inmediato, sin rampa. Solo para pruebas y posicionamiento
    // inicial: el lazo de fuerza no puede proteger un movimiento asi.
    void setAnguloServo(uint8_t servo_id, uint8_t angulo);

    // Configuracion de gestos predefinidos
    static const ConfigGesto gestos[NUM_CLASES];

private:
    Adafruit_PWMServoDriver _pca;

    // El angulo comandado se guarda en float porque el paso de rampa
    // (3.6 grados a 50 Hz) no es entero; redondear en cada paso
    // acumularia error y falsearia la velocidad efectiva.
    float   _comandado[NUM_SERVOS];
    uint8_t _objetivo[NUM_SERVOS];
    uint8_t _ultimo_escrito[NUM_SERVOS];
    unsigned long _t_ultima_rampa;
    bool _inicializado;

    // Convierte angulo (0-180) a pulso PWM para PCA9685
    // PCA9685 usa cuentas de 0-4096 para el ciclo completo de 20 ms
    // 500 us → 102 cuentas, 2500 us → 512 cuentas
    uint16_t _anguloAPulso(uint8_t angulo);

    // Envia el pulso a un canal especifico del PCA9685
    void _escribirPulso(uint8_t servo_id, uint16_t pulso);
};

#endif
