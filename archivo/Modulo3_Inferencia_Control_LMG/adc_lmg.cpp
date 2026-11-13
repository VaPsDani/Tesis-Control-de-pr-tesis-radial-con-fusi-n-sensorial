#include "adc_lmg.h"

static const uint8_t DIRECCION_ADS[2] = { ADS_ADDR_1, ADS_ADDR_2 };

// Canal LMG -> ADC (0 = 0x48, 1 = 0x49) y entrada AINx de ese ADC.
static const uint8_t ADS_DE_LMG[NUM_LMG] = {
    LMG1_ADS, LMG2_ADS, LMG3_ADS, LMG4_ADS, LMG5_ADS,
};
static const uint8_t AIN_DE_LMG[NUM_LMG] = {
    LMG1_AIN, LMG2_AIN, LMG3_AIN, LMG4_AIN, LMG5_AIN,
};

// Registros del ADS1x15.
static const uint8_t REG_CONVERSION = 0x00;
static const uint8_t REG_CONFIG     = 0x01;

// Registro de configuracion (igual en ADS1115 y ADS1015):
//   bit 15     OS = 1: inicia una conversion (al leer: 1 = no convierte)
//   bits 14:12 MUX = 1xx: AINx contra GND, x = bits 13:12
//   bits 11:9  PGA = 010: +/-2.048 V (GAIN_TWO)
//   bit 8      MODE = 1: single-shot
//   bits 7:5   DR: 111 = 860 SPS en el ADS1115, 110 = 3300 SPS en el ADS1015
//   bits 4:0   comparador deshabilitado (COMP_QUE = 11, ALERT en alta Z)
static const uint16_t CFG_OS     = 0x8000;
static const uint16_t CFG_MUX_SE = 0x4000;
static const uint16_t CFG_PGA_2  = 0x0400;
static const uint16_t CFG_SINGLE = 0x0100;
#if ADC_MODELO == ADC_ADS1015
static const uint16_t CFG_DR     = 0x00C0;   // 3300 SPS, 303 us
#else
static const uint16_t CFG_DR     = 0x00E0;   // 860 SPS, 1163 us
#endif
static const uint16_t CFG_SIN_COMP = 0x0003;

// Medicion de la conversion: intentos por punto de la busqueda. Todos
// tienen que haber terminado para dar el punto por bueno.
static const uint8_t INTENTOS_MEDICION = 8;

ADC_LMG::ADC_LMG()
    : _canal(0), _erroresI2C(0), _tUltimoAviso(0), _tUltimoAvisoI2C(0) {
    for (uint8_t k = 0; k < 2; k++) {
        _presente[k]     = false;
        _esperaUs[k]     = ADC_ESPERA_US;
        _convMedidaUs[k] = 0;
    }
    reiniciarRecortes();
}

bool ADC_LMG::begin() {
    for (uint8_t k = 0; k < 2; k++) {
        Wire.beginTransmission(DIRECCION_ADS[k]);
        _presente[k] = Wire.endTransmission() == 0;
    }
    if (!(_presente[0] && _presente[1])) return false;
    verificarEspera();
    return true;
}

// Escribe la configuracion con OS = 1. t0 queda en el fin de la
// escritura (la condicion de STOP), que es cuando el chip arranca.
bool ADC_LMG::_iniciar(uint8_t k, uint8_t ain, unsigned long &t0) {
    const uint16_t cfg = CFG_OS | CFG_MUX_SE | ((uint16_t)(ain & 0x03) << 12) |
                         CFG_PGA_2 | CFG_SINGLE | CFG_DR | CFG_SIN_COMP;
    Wire.beginTransmission(DIRECCION_ADS[k]);
    Wire.write(REG_CONFIG);
    Wire.write((uint8_t)(cfg >> 8));
    Wire.write((uint8_t)(cfg & 0xFF));
    const bool ok = Wire.endTransmission() == 0;
    t0 = micros();
    return ok;
}

// Lee 2 bytes del registro al que apunte el puntero, sin escribirlo.
bool ADC_LMG::_leer16(uint8_t k, uint16_t &valor) {
    if (Wire.requestFrom(DIRECCION_ADS[k], (uint8_t)2) != 2) return false;
    valor = ((uint16_t)Wire.read() << 8) | Wire.read();
    return true;
}

// Tiempo desde el fin de la escritura de la configuracion hasta la
// primera lectura que encuentra la conversion terminada, por el MISMO
// camino que leerActual(): espera hasta t0 + T y una lectura de 2 bytes.
// Tras escribir la configuracion el puntero queda en ella, asi que esa
// lectura devuelve el bit OS. Busqueda binaria sobre T. 0 si falla.
uint16_t ADC_LMG::_medirConversionUs(uint8_t k) {
    // La entrada del primer canal LMG de este chip.
    uint8_t ain = 0;
    for (uint8_t i = NUM_LMG; i-- > 0; ) {
        if (ADS_DE_LMG[i] == k) ain = AIN_DE_LMG[i];
    }
    uint16_t lo = ADC_CONVERSION_US / 2;
    uint16_t hi = 2 * ADC_CONVERSION_US + 200;
    bool algunoTermino = false;
    while (hi - lo > 4) {
        const uint16_t T = lo + (hi - lo) / 2;
        bool todos = true;
        for (uint8_t n = 0; n < INTENTOS_MEDICION && todos; n++) {
            unsigned long t0;
            uint16_t cfg = 0;
            if (!_iniciar(k, ain, t0)) return 0;
            while (micros() - t0 < T) { }
            if (!_leer16(k, cfg)) return 0;
            todos = (cfg & CFG_OS) != 0;
            // Que la conversion en curso acabe antes de la siguiente: un
            // OS = 1 escrito mientras convierte no inicia otra.
            delayMicroseconds(2 * ADC_CONVERSION_US);
        }
        if (todos) { hi = T; algunoTermino = true; }
        else       { lo = T; }
    }
    return algunoTermino ? hi : 0;
}

void ADC_LMG::verificarEspera() {
    for (uint8_t k = 0; k < 2; k++) {
        if (!_presente[k]) continue;
        const uint16_t medida = _medirConversionUs(k);
        _convMedidaUs[k] = medida;
        if (medida == 0) {
            // Sin medicion fiable: la espera mas larga que se probo.
            _esperaUs[k] = 2 * ADC_CONVERSION_US + 200;
            Serial.printf("[ADC] ERROR: 0x%02X no termino ninguna conversion "
                          "medible (bus I2C?). Espera %u us.\n",
                          DIRECCION_ADS[k], _esperaUs[k]);
            continue;
        }
        const uint16_t necesaria =
            (uint16_t)ceilf(medida * (1.0f + ADC_ESPERA_MARGEN_PCT / 100.0f));
        _esperaUs[k] = necesaria > ADC_ESPERA_US ? necesaria : (uint16_t)ADC_ESPERA_US;
        Serial.printf("[ADC] 0x%02X conversion medida %u us, espera %u us "
                      "(holgura %.1f%%)\n", DIRECCION_ADS[k], medida,
                      _esperaUs[k], 100.0f * (_esperaUs[k] - medida) / medida);
        if (_esperaUs[k] > ADC_ESPERA_US) {
            Serial.printf("[ADC] AVISO: 0x%02X convierte mas lento que lo "
                          "previsto; espera subida de %u a %u us. El ciclo "
                          "se alarga: ver el autotest.\n", DIRECCION_ADS[k],
                          (unsigned)ADC_ESPERA_US, _esperaUs[k]);
        }
    }
}

void ADC_LMG::seleccionar(uint8_t canal) {
    _canal = canal < NUM_LMG ? canal : 0;
}

float ADC_LMG::leerActual() {
    const uint8_t k = ADS_DE_LMG[_canal];
    unsigned long t0;
    uint16_t palabra = 0;
    bool ok = _iniciar(k, AIN_DE_LMG[_canal], t0);

    // Puntero al registro de conversion mientras el chip convierte.
    Wire.beginTransmission(DIRECCION_ADS[k]);
    Wire.write(REG_CONVERSION);
    ok = (Wire.endTransmission() == 0) && ok;

    while (micros() - t0 < _esperaUs[k]) { }
    ok = _leer16(k, palabra) && ok;

    if (!ok) {
        // Lectura invalida: 0 mV, que en reposo (~700 mV) salta a la vista.
        _erroresI2C++;
        const unsigned long ahora = millis();
        if (ahora - _tUltimoAvisoI2C >= 1000) {
            _tUltimoAvisoI2C = ahora;
            Serial.printf("[ADC] AVISO: fallo I2C leyendo LMG%u (%lu en "
                          "total). Revise el bus.\n", _canal + 1,
                          (unsigned long)_erroresI2C);
        }
        return 0.0f;
    }

#if ADC_MODELO == ADC_ADS1015
    const int16_t raw = ((int16_t)palabra) >> 4;   // 12 bits, justificados a la izquierda
#else
    const int16_t raw = (int16_t)palabra;
#endif

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
    // 0.0625 mV/LSB en el ADS1115 y 1 mV/LSB en el ADS1015, a GAIN_TWO.
    // Es lo mismo que daba computeVolts() de Adafruit.
    return raw * ADS_GAIN_MV;
}

float ADC_LMG::leerCanal(uint8_t canal) {
    seleccionar(canal);
    return leerActual();
}

void ADC_LMG::reiniciarRecortes() {
    for (uint8_t i = 0; i < NUM_LMG; i++) _recortes[i] = 0;
}
