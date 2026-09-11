#include "mux_ads1115.h"

MUX_ADS1115::MUX_ADS1115() {}

bool MUX_ADS1115::begin() {
    pinMode(PIN_MUX_S0, OUTPUT);
    pinMode(PIN_MUX_S1, OUTPUT);
    pinMode(PIN_MUX_S2, OUTPUT);
    pinMode(PIN_MUX_S3, OUTPUT);

    // ORDEN CRITICO: begin() antes de configurar. setGain() sobre un
    // driver sin inicializar opera en el vacio.
    if (!_ads.begin(ADS_ADDR)) {
        return false;
    }

    _ads.setGain(GAIN_ONE);   // +/-4.096 V

    // Tasa maxima de cada modelo. El default de la libreria (128 SPS en
    // el ADS1115) dejaba el muestreo en ~25 Hz.
#if ADC_MODELO == ADC_ADS1015
    _ads.setDataRate(RATE_ADS1015_3300SPS);   // 303 us por conversion
#else
    _ads.setDataRate(RATE_ADS1115_860SPS);    // 1163 us por conversion
#endif
    return true;
}

void MUX_ADS1115::seleccionar(uint8_t canal) {
    _seleccionarCanal(canal);
    // Asentamiento del MUX: lo que manda no es el t_on del CD74HC4067
    // (~1 us) sino la carga del capacitor de muestreo del ADC a traves
    // de la Ron del MUX. 5 us producian diafonia entre canales.
    delayMicroseconds(ASENTAMIENTO_MUX_US);
}

float MUX_ADS1115::leerActual() {
    const int16_t raw = _ads.readADC_SingleEnded(0);
    // computeVolts conoce ganancia y resolucion del modelo: 0.125 mV/LSB
    // en el ADS1115 de 16 bits, 2 mV/LSB en el ADS1015 de 12 bits.
    return _ads.computeVolts(raw) * 1000.0f;
}

float MUX_ADS1115::leerCanal(uint8_t canal) {
    seleccionar(canal);
    return leerActual();
}

void MUX_ADS1115::_seleccionarCanal(uint8_t canal) {
    digitalWrite(PIN_MUX_S0, (canal >> 0) & 1);
    digitalWrite(PIN_MUX_S1, (canal >> 1) & 1);
    digitalWrite(PIN_MUX_S2, (canal >> 2) & 1);
    digitalWrite(PIN_MUX_S3, (canal >> 3) & 1);
}
