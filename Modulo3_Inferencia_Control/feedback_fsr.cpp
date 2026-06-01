#include "feedback_fsr.h"

FeedbackFSR::FeedbackFSR() {
    for (int i = 0; i < 6; i++) {
        _ultimos_valores[i] = 0.0f;
    }

    // Establecer umbrales por defecto (desde config.h)
    umbrales[0] = UMBRAL_FSR_PULGAR;
    umbrales[1] = UMBRAL_FSR_INDICE;
    umbrales[2] = UMBRAL_FSR_MEDIO;
    umbrales[3] = UMBRAL_FSR_ANULAR;
    umbrales[4] = UMBRAL_FSR_MENIQUE;
    umbrales[5] = UMBRAL_FSR_PALMA;
}

bool FeedbackFSR::leerFSR(float valores[6]) {
    // Nota: la lectura del MUX + ADS1115 se realiza desde el main loop
    // para compartir el ADC entre LMG y FSR. Esta funcion solo
    // actualiza el cache de ultimos valores.
    for (int i = 0; i < 6; i++) {
        _ultimos_valores[i] = valores[i];
    }
    return true;
}

uint8_t FeedbackFSR::verificarUmbrales(const float valores[6]) {
    uint8_t bitmap = 0;

    for (int i = 0; i < 6; i++) {
        if (valores[i] >= umbrales[i]) {
            bitmap |= (1 << i);
        }
    }

    return bitmap;
}

float FeedbackFSR::getUltimoValor(uint8_t idx) const {
    if (idx >= 6) return 0.0f;
    return _ultimos_valores[idx];
}
