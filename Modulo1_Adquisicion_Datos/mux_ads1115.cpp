#include "mux_ads1115.h"

MUX_ADS1115::MUX_ADS1115() {}

bool MUX_ADS1115::begin() {
    // Configurar pines del MUX como salidas
    pinMode(PIN_MUX_S0, OUTPUT);
    pinMode(PIN_MUX_S1, OUTPUT);
    pinMode(PIN_MUX_S2, OUTPUT);
    pinMode(PIN_MUX_S3, OUTPUT);

    // Inicializar ADS1115
    // GAIN_ONE  → ±4.096V, resolucion 0.125 mV (default)
    // GAIN_TWOTHIRDS → ±6.144V, resolucion 0.1875 mV
    _ads.setGain(GAIN_ONE);
    return _ads.begin(ADS_ADDR);
}

float MUX_ADS1115::leerCanal(uint8_t canal) {
    _seleccionarCanal(canal);
    delayMicroseconds(5);      // t_on del MUX ~ 1 us, margen 5 us
    
    // Leer el ADS1115 (canal A0 single-ended)
    int16_t raw = _ads.readADC_SingleEnded(0);
    
    // Convertir a mV: raw * 0.125 mV (con GAIN_ONE)
    float voltaje = raw * 0.125f;
    return voltaje;
}

void MUX_ADS1115::_seleccionarCanal(uint8_t canal) {
    digitalWrite(PIN_MUX_S0, (canal >> 0) & 1);
    digitalWrite(PIN_MUX_S1, (canal >> 1) & 1);
    digitalWrite(PIN_MUX_S2, (canal >> 2) & 1);
    digitalWrite(PIN_MUX_S3, (canal >> 3) & 1);
}
