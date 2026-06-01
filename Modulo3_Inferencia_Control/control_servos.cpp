#include "control_servos.h"

// ============================================================
// Configuracion de gestos predefinidos
// ============================================================
// Orden servos: [Pulgar, Indice, Medio, Anular, Menique]
// 0° = abierto, 180° = cerrado
const ConfigGesto ControlServos::gestos[NUM_CLASES] = {
    // GESTO_REST
    { {0, 0, 0, 0, 0}, "Rest" },
    // GESTO_PINCH
    { {180, 120, 0, 0, 0}, "Pinch" },     // pulgar + indice cierran
    // GESTO_TRIPOD
    { {180, 150, 120, 0, 0}, "Tripod" },   // pulgar + indice + medio
    // GESTO_POWER
    { {180, 170, 170, 150, 140}, "Power" }, // todos cierran (fuerza)
    // GESTO_EXTENSION
    { {0, 0, 0, 0, 0}, "Extension" },      // todos abren
};

// ============================================================
ControlServos::ControlServos() : _inicializado(false) {
    for (int i = 0; i < NUM_SERVOS; i++) {
        _angulos_actuales[i] = 0;
    }
}

bool ControlServos::begin() {
    // Inicializar PCA9685
    _pca = Adafruit_PWMServoDriver(PCA9685_ADDR, Wire);
    _pca.begin();
    // Frecuencia de 50 Hz para servos (periodo de 20 ms)
    _pca.setPWMFreq(50);
    delay(10);

    // Posicion inicial: todos abiertos (Rest)
    ejecutarGesto(GESTO_REST);
    _inicializado = true;
    return true;
}

void ControlServos::ejecutarGesto(uint8_t gesto_id) {
    if (gesto_id >= NUM_CLASES) gesto_id = GESTO_REST;

    Serial.printf("[SERVO] Gesto: %s\n", gestos[gesto_id].nombre);

    for (int i = 0; i < NUM_SERVOS; i++) {
        uint8_t angulo = gestos[gesto_id].angulos[i];
        _angulos_actuales[i] = angulo;
        uint16_t pulso = _anguloAPulso(angulo);
        _escribirPulso(i, pulso);
    }
}

void ControlServos::frenarServo(uint8_t servo_id) {
    if (servo_id >= NUM_SERVOS) return;

    // No mover mas: mantener el angulo actual
    // (Ya esta en esa posicion, no hay que hacer nada adicional)
    Serial.printf("[FSR] Servo %d frenado en %d grados\n",
                  servo_id, _angulos_actuales[servo_id]);
}

uint8_t ControlServos::getAnguloActual(uint8_t servo_id) const {
    if (servo_id >= NUM_SERVOS) return 0;
    return _angulos_actuales[servo_id];
}

void ControlServos::setAnguloServo(uint8_t servo_id, uint8_t angulo) {
    if (servo_id >= NUM_SERVOS) return;
    _angulos_actuales[servo_id] = angulo;
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
