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

    _ads.setGain(GAIN_ONE);   // +/-4.096 V, 0.125 mV/LSB (ADS_GAIN_MV)

    // 860 SPS -> 1.163 ms por conversion. Con el default de 128 SPS
    // (7.8 ms) los 5 canales LMG tardarian ~39 ms y el muestreo caeria
    // a ~25 Hz, incompatible con la ventana de 20 muestras a 100 Hz.
    //
    // ADVERTENCIA DE PRESUPUESTO EN ESTE MODULO: en los ciclos de
    // agarre este bucle lee ademas los 6 FSR por el mismo ADC
    // (~10 ms) y ejecuta la inferencia, sobre un presupuesto de 10 ms.
    // setDataRate mejora el ADC 4.7x pero NO resuelve ese conflicto:
    // 5 LMG + 6 FSR = 11 conversiones = ~18 ms. Para sostener 100 Hz
    // reales con lazo cerrado hay que bajar la tasa de lectura de los
    // FSR o moverlos a un segundo ADS1115 (direccion 0x49).
    _ads.setDataRate(RATE_ADS1115_860SPS);

    return true;
}

float MUX_ADS1115::leerCanal(uint8_t canal) {
    _seleccionarCanal(canal);

    // Asentamiento del MUX: lo que manda no es el t_on del CD74HC4067
    // (~1 us) sino la carga del capacitor de muestreo del ADS1115 a
    // traves de la Ron del MUX. 5 us era optimista y produce diafonia
    // entre canales adyacentes; 50 us cuestan 250 us por ciclo.
    delayMicroseconds(50);

    int16_t raw = _ads.readADC_SingleEnded(0);
    return raw * ADS_GAIN_MV;   // conversion a mV
}

void MUX_ADS1115::_seleccionarCanal(uint8_t canal) {
    digitalWrite(PIN_MUX_S0, (canal >> 0) & 1);
    digitalWrite(PIN_MUX_S1, (canal >> 1) & 1);
    digitalWrite(PIN_MUX_S2, (canal >> 2) & 1);
    digitalWrite(PIN_MUX_S3, (canal >> 3) & 1);
}
