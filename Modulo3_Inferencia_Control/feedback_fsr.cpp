#include "feedback_fsr.h"

static const uint8_t CANALES_FSR[NUM_FSR] = {
    CH_FSR_PULGAR, CH_FSR_INDICE, CH_FSR_MEDIO,
    CH_FSR_ANULAR, CH_FSR_MENIQUE,
};

static const char *NOMBRES_DEDO[NUM_FSR] = {
    "Pulgar", "Indice", "Medio", "Anular", "Menique",
};

FeedbackFSR::FeedbackFSR() {
    umbrales[0] = UMBRAL_FSR_PULGAR;
    umbrales[1] = UMBRAL_FSR_INDICE;
    umbrales[2] = UMBRAL_FSR_MEDIO;
    umbrales[3] = UMBRAL_FSR_ANULAR;
    umbrales[4] = UMBRAL_FSR_MENIQUE;
    reiniciar();
}

uint8_t FeedbackFSR::canalDe(uint8_t dedo) {
    return (dedo < NUM_FSR) ? CANALES_FSR[dedo] : CH_FSR_PULGAR;
}

uint8_t FeedbackFSR::dedosActivos(uint8_t gesto_id) {
    switch (gesto_id) {
        case GESTO_PINCH:     return FSR_ACTIVOS_PINCH;
        case GESTO_TRIPOD:    return FSR_ACTIVOS_TRIPOD;
        case GESTO_POWER:     return FSR_ACTIVOS_POWER;
        case GESTO_REST:      return FSR_ACTIVOS_REST;
        case GESTO_EXTENSION: return FSR_ACTIVOS_EXTENSION;
        default:              return 0x00;
    }
}

void FeedbackFSR::reiniciar() {
    for (uint8_t i = 0; i < NUM_FSR; i++) {
        _valores[i]    = 0.0f;
        _valido[i]     = false;
        _t_ultima[i]   = 0;
        _periodo_us[i] = 0;
    }
}

void FeedbackFSR::actualizar(uint8_t dedo, float valor_mv,
                             unsigned long ahora_us) {
    if (dedo >= NUM_FSR) return;

    if (_t_ultima[dedo] != 0) {
        const unsigned long dt = ahora_us - _t_ultima[dedo];
        // Media movil exponencial simple, para no guardar historial.
        _periodo_us[dedo] = _periodo_us[dedo]
            ? (_periodo_us[dedo] * 3 + dt) / 4
            : dt;
    }
    _t_ultima[dedo] = ahora_us;
    _valores[dedo]  = valor_mv;
    _valido[dedo]   = true;
}

uint8_t FeedbackFSR::verificarUmbrales(uint8_t dedos_activos) const {
    uint8_t bitmap = 0;
    for (uint8_t i = 0; i < NUM_FSR; i++) {
        if (!(dedos_activos & (1 << i))) continue;
        // Un valor rancio de un gesto anterior no debe frenar un dedo
        // que acaba de empezar a cerrarse.
        if (!_valido[i]) continue;
        if (_valores[i] >= umbrales[i]) {
            bitmap |= (1 << i);
        }
    }
    return bitmap;
}

float FeedbackFSR::getUltimoValor(uint8_t dedo) const {
    return (dedo < NUM_FSR) ? _valores[dedo] : 0.0f;
}

bool FeedbackFSR::esValido(uint8_t dedo) const {
    return (dedo < NUM_FSR) ? _valido[dedo] : false;
}

float FeedbackFSR::tasaEfectiva(uint8_t dedo) const {
    if (dedo >= NUM_FSR || _periodo_us[dedo] == 0) return 0.0f;
    return 1000000.0f / (float)_periodo_us[dedo];
}

void FeedbackFSR::info() const {
    Serial.println("[FSR] dedo      valor(mV)   umbral   tasa(Hz)  valido");
    for (uint8_t i = 0; i < NUM_FSR; i++) {
        Serial.printf("[FSR] %-9s %9.1f %8.1f %10.1f  %s\n",
                      NOMBRES_DEDO[i], _valores[i], umbrales[i],
                      tasaEfectiva(i), _valido[i] ? "si" : "no");
    }
}
