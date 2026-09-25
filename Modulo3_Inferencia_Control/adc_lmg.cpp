#include "adc_lmg.h"

static const uint8_t DIRECCION_ADS[2] = { ADS_ADDR_1, ADS_ADDR_2 };

// Canal LMG -> ADC (0 = 0x48, 1 = 0x49) y entrada AINx de ese ADC.
static const uint8_t ADS_DE_LMG[NUM_LMG] = {
    LMG1_ADS, LMG2_ADS, LMG3_ADS, LMG4_ADS, LMG5_ADS,
};
static const uint8_t AIN_DE_LMG[NUM_LMG] = {
    LMG1_AIN, LMG2_AIN, LMG3_AIN, LMG4_AIN, LMG5_AIN,
};

ADC_LMG::ADC_LMG() : _canal(0), _tUltimoAviso(0) {
    _presente[0] = _presente[1] = false;
    reiniciarRecortes();
}

bool ADC_LMG::begin() {
    for (uint8_t k = 0; k < 2; k++) {
        // ORDEN CRITICO: begin() antes de configurar. setGain() sobre un
        // driver sin inicializar opera en el vacio.
        _presente[k] = _ads[k].begin(DIRECCION_ADS[k]);
        if (!_presente[k]) continue;

        // La libreria envia la ganancia con cada conversion, asi que
        // fijarla una vez basta para los dos canales de cada chip.
        _ads[k].setGain(GAIN_TWO);   // +/-2.048 V

        // Tasa maxima de cada modelo. El default de la libreria (128 SPS
        // en el ADS1115) dejaba el muestreo en ~25 Hz.
#if ADC_MODELO == ADC_ADS1015
        _ads[k].setDataRate(RATE_ADS1015_3300SPS);   // 303 us por conversion
#else
        _ads[k].setDataRate(RATE_ADS1115_860SPS);    // 1163 us por conversion
#endif
    }
    return _presente[0] && _presente[1];
}

void ADC_LMG::seleccionar(uint8_t canal) {
    _canal = canal < NUM_LMG ? canal : 0;
}

float ADC_LMG::leerActual() {
    const uint8_t k = ADS_DE_LMG[_canal];
    const int16_t raw = _ads[k].readADC_SingleEnded(AIN_DE_LMG[_canal]);

    if (raw >= ADC_RAW_MAX) {
        _recortes[_canal]++;
        const unsigned long ahora = millis();
        if (ahora - _tUltimoAviso >= 1000) {
            _tUltimoAviso = ahora;
            Serial.printf("[ADC] AVISO: LMG%u recorta (codigo %d, entrada >= "
                          "2048 mV). Lectura no valida; revise la "
                          "autocalibracion ('A').\n", _canal + 1, raw);
        }
    }
    // computeVolts conoce ganancia y resolucion: 0.0625 mV/LSB en el
    // ADS1115 y 1 mV/LSB en el ADS1015, ambos a GAIN_TWO.
    return _ads[k].computeVolts(raw) * 1000.0f;
}

float ADC_LMG::leerCanal(uint8_t canal) {
    seleccionar(canal);
    return leerActual();
}

void ADC_LMG::reiniciarRecortes() {
    for (uint8_t i = 0; i < NUM_LMG; i++) _recortes[i] = 0;
}
