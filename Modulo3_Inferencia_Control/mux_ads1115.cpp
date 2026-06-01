#include "mux_ads1115.h"

MUX_ADS1115::MUX_ADS1115() {}

bool MUX_ADS1115::begin() {
    pinMode(PIN_MUX_S0, OUTPUT);
    pinMode(PIN_MUX_S1, OUTPUT);
    pinMode(PIN_MUX_S2, OUTPUT);
    pinMode(PIN_MUX_S3, OUTPUT);

    _ads.setGain(GAIN_ONE);
    return _ads.begin(ADS_ADDR);
}

float MUX_ADS1115::leerCanal(uint8_t canal) {
    _seleccionarCanal(canal);
    delayMicroseconds(5);

    int16_t raw = _ads.readADC_SingleEnded(0);
    return raw * ADS_GAIN_MV;   // conversion a mV
}

void MUX_ADS1115::_seleccionarCanal(uint8_t canal) {
    digitalWrite(PIN_MUX_S0, (canal >> 0) & 1);
    digitalWrite(PIN_MUX_S1, (canal >> 1) & 1);
    digitalWrite(PIN_MUX_S2, (canal >> 2) & 1);
    digitalWrite(PIN_MUX_S3, (canal >> 3) & 1);
}
