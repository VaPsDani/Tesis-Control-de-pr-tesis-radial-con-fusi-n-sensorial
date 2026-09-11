#include "control_servos.h"

// ============================================================
// Configuracion de gestos predefinidos
// ============================================================
// Orden servos: [Pulgar, Indice, Medio, Anular, Menique]
// 0° = abierto, 180° = cerrado
// R = ANGULO_REST (relajado, ligera flexion pasiva)
// E = ANGULO_EXTENSION (extension completa)
//
// Rest y Extension ya NO son identicos. Antes ambos eran {0,0,0,0,0} y
// la mano hacia lo mismo en dos de las cinco clases, de modo que
// confundirlas no tenia consecuencia motora y no se podia demostrar en
// la validacion funcional que el sistema distingue las cinco.
//
// Los dedos que NO participan en un agarre tampoco se quedan en 0: van
// a la postura relajada, que es donde estarian en una mano real.
const ConfigGesto ControlServos::gestos[NUM_CLASES] = {
    // GESTO_REST: mano relajada, ligera flexion en todos los dedos
    { {ANGULO_REST, ANGULO_REST, ANGULO_REST, ANGULO_REST, ANGULO_REST},
      "Rest" },
    // GESTO_PINCH: pulgar + indice cierran, el resto relajado
    { {180, 120, ANGULO_REST, ANGULO_REST, ANGULO_REST}, "Pinch" },
    // GESTO_TRIPOD: pulgar + indice + medio
    { {180, 150, 120, ANGULO_REST, ANGULO_REST}, "Tripod" },
    // GESTO_POWER: los cinco cierran (agarre de fuerza)
    { {180, 170, 170, 150, 140}, "Power" },
    // GESTO_EXTENSION: los cinco al suelo del rango, por debajo de Rest
    { {ANGULO_EXTENSION, ANGULO_EXTENSION, ANGULO_EXTENSION,
       ANGULO_EXTENSION, ANGULO_EXTENSION}, "Extension" },
};

// ============================================================
ControlServos::ControlServos()
    : _t_ultima_rampa(0), _inicializado(false) {
    for (int i = 0; i < NUM_SERVOS; i++) {
        _comandado[i]      = (float)ANGULO_REST;
        _objetivo[i]       = ANGULO_REST;
        _ultimo_escrito[i] = 255;   // fuerza la primera escritura
    }
}

bool ControlServos::begin() {
    // Inicializar PCA9685
    _pca = Adafruit_PWMServoDriver(PCA9685_ADDR, Wire);
    _pca.begin();
    // Frecuencia de 50 Hz para servos (periodo de 20 ms)
    _pca.setPWMFreq(50);
    delay(10);

    _inicializado = true;

    // Posicion inicial SIN rampa: al arrancar no hay nada que proteger
    // y conviene que la mano adopte el reposo de inmediato.
    for (int i = 0; i < NUM_SERVOS; i++) {
        setAnguloServo(i, gestos[GESTO_REST].angulos[i]);
    }
    _t_ultima_rampa = millis();
    return true;
}

void ControlServos::ejecutarGesto(uint8_t gesto_id) {
    if (gesto_id >= NUM_CLASES) gesto_id = GESTO_REST;

    Serial.printf("[SERVO] Gesto: %s\n", gestos[gesto_id].nombre);

    // Solo se fija el OBJETIVO. El movimiento lo hace actualizarRampa();
    // saltar aqui al angulo final dejaria al lazo de fuerza sin nada que
    // frenar, que era el defecto de la version anterior.
    for (int i = 0; i < NUM_SERVOS; i++) {
        _objetivo[i] = gestos[gesto_id].angulos[i];
    }
}

void ControlServos::actualizarRampa(unsigned long ahora_ms) {
    if (!_inicializado) return;

    if (ahora_ms - _t_ultima_rampa < (unsigned long)RAMPA_PERIODO_MS) return;
    const unsigned long dt_ms = ahora_ms - _t_ultima_rampa;
    _t_ultima_rampa = ahora_ms;

    // Paso proporcional al tiempo REAL transcurrido, no al nominal: si
    // un ciclo se retrasa, la velocidad angular efectiva se mantiene.
    const float paso = RAMPA_GRADOS_POR_S * (dt_ms / 1000.0f);

    for (int i = 0; i < NUM_SERVOS; i++) {
        const float objetivo = (float)_objetivo[i];
        const float delta = objetivo - _comandado[i];

        if (fabsf(delta) <= paso) {
            _comandado[i] = objetivo;
        } else {
            _comandado[i] += (delta > 0 ? paso : -paso);
        }

        // Escribir solo si el angulo redondeado cambio. Mantener una
        // postura no genera trafico I2C, que es lo que permite que la
        // rampa quepa en el presupuesto del ciclo.
        const uint8_t redondeado = (uint8_t)lroundf(_comandado[i]);
        if (redondeado != _ultimo_escrito[i]) {
            _escribirPulso(i, _anguloAPulso(redondeado));
            _ultimo_escrito[i] = redondeado;
        }
    }
}

void ControlServos::frenarServo(uint8_t servo_id) {
    if (servo_id >= NUM_SERVOS) return;

    // Congelar el objetivo donde esta el comando AHORA. A partir de
    // aqui la rampa no tiene a donde avanzar y el dedo deja de apretar.
    const uint8_t aqui = (uint8_t)lroundf(_comandado[servo_id]);
    if (_objetivo[servo_id] != aqui) {
        _objetivo[servo_id] = aqui;
        Serial.printf("[FSR] Servo %d frenado en %d grados\n",
                      servo_id, aqui);
    }
}

bool ControlServos::enMovimiento(uint8_t servo_id) const {
    if (servo_id >= NUM_SERVOS) return false;
    return fabsf((float)_objetivo[servo_id] - _comandado[servo_id]) > 0.5f;
}

uint8_t ControlServos::getAnguloActual(uint8_t servo_id) const {
    if (servo_id >= NUM_SERVOS) return 0;
    return (uint8_t)lroundf(_comandado[servo_id]);
}

void ControlServos::setAnguloServo(uint8_t servo_id, uint8_t angulo) {
    if (servo_id >= NUM_SERVOS) return;
    // Salto inmediato: se sincronizan comando y objetivo para que la
    // rampa no intente deshacerlo en el siguiente tick.
    _comandado[servo_id] = (float)angulo;
    _objetivo[servo_id]  = angulo;
    _ultimo_escrito[servo_id] = angulo;
    _escribirPulso(servo_id, _anguloAPulso(angulo));
}

// ========== PRIVADAS ==========

uint16_t ControlServos::_anguloAPulso(uint8_t angulo) {
    // Mapear 0-180 grados a 500-2500 microsegundos
    float pulso_us = 500.0f + (angulo / 180.0f) * 2000.0f;

    // PCA9685: 12 bits (0-4096), 50 Hz (20 ms)
    // 1 cuenta = 20000 us / 4096 ≈ 4.88 us
    uint16_t cuentas = (uint16_t)(pulso_us * 4096.0f / 20000.0f);
    return constrain(cuentas, 102, 512);   // 500-2500 us
}

void ControlServos::_escribirPulso(uint8_t servo_id, uint16_t pulso) {
    _pca.setPWM(servo_id, 0, pulso);
}
