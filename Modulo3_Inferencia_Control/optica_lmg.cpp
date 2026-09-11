#include "optica_lmg.h"
#include <Preferences.h>

static const uint8_t PINES_LED[NUM_LMG] = {
    PIN_LED_LMG_1, PIN_LED_LMG_2, PIN_LED_LMG_3, PIN_LED_LMG_4, PIN_LED_LMG_5,
};
static const uint8_t CANALES_LMG[NUM_LMG] = {
    CH_LMG_1, CH_LMG_2, CH_LMG_3, CH_LMG_4, CH_LMG_5,
};

static const char *NVS_NS = "optica";

static const uint16_t DUTY_NOMINAL =
    (uint16_t)(AUTOCAL_DUTY_NOMINAL_FRAC * LED_DUTY_MAX);

OpticaLMG::OpticaLMG(MUX_ADS1115 &adc)
    : _adc(adc), _debil(0), _cambio(false) {
    for (uint8_t i = 0; i < NUM_LMG; i++) {
        _duty[i]   = DUTY_NOMINAL;
        _reposo[i] = 0.0f;
        _oscura[i] = 0.0f;
    }
}

bool OpticaLMG::begin() {
    for (uint8_t i = 0; i < NUM_LMG; i++) {
        // API LEDC del core ESP32 3.x: el canal se asigna solo.
        if (!ledcAttach(PINES_LED[i], LED_PWM_FREQ_HZ, LED_PWM_BITS)) {
            Serial.printf("[OPTICA] ERROR: no se pudo asignar PWM al GPIO %u\n",
                          PINES_LED[i]);
            return false;
        }
        ledcWrite(PINES_LED[i], 0);
    }
    if (_cargarNVS()) {
        Serial.println("[OPTICA] Ganancias recuperadas de NVS.");
    } else {
        Serial.println("[OPTICA] Sin ganancias guardadas: corriente nominal "
                       "hasta autocalibrar.");
    }
    return true;
}

void OpticaLMG::_encender(uint8_t i) { ledcWrite(PINES_LED[i], _duty[i]); }
void OpticaLMG::_apagar(uint8_t i)   { ledcWrite(PINES_LED[i], 0); }

void OpticaLMG::apagarTodos() {
    for (uint8_t i = 0; i < NUM_LMG; i++) ledcWrite(PINES_LED[i], 0);
}

float OpticaLMG::leerCanal(uint8_t i) {
    if (i >= NUM_LMG) return 0.0f;

    // Todos apagados antes de seleccionar el canal: ningun LED vecino
    // puede iluminar este fotodiodo (crosstalk optico).
    apagarTodos();
    _adc.seleccionar(CANALES_LMG[i]);

#if TRAMA_OSCURA_HABILITADA
    // D: solo luz ambiental. El asentamiento cubre la cola del LED que
    // estaba encendido en la lectura anterior.
    delayMicroseconds(ASENTAMIENTO_LED_US);
    const float D = _adc.leerActual();

    // L: ambiental + LED propio. Se toma inmediatamente despues de D para
    // acortar dt todo lo que el ADC permite (ver optica_lmg.h: aun asi no
    // basta para cancelar el parpadeo de 120 Hz).
    _encender(i);
    delayMicroseconds(ASENTAMIENTO_LED_US);
    const float L = _adc.leerActual();
    _apagar(i);

    _oscura[i] = D;
    return L - D;
#else
    _encender(i);
    delayMicroseconds(ASENTAMIENTO_LED_US);
    const float L = _adc.leerActual();
    _apagar(i);
    return L;
#endif
}

void OpticaLMG::leerTodos(float destino[NUM_LMG]) {
    for (uint8_t i = 0; i < NUM_LMG; i++) destino[i] = leerCanal(i);
}

float OpticaLMG::_medir(uint8_t i, uint16_t n) {
    double s = 0.0;
    for (uint16_t k = 0; k < n; k++) s += leerCanal(i);
    return (float)(s / n);
}

// Busqueda binaria del duty que deja el reposo en el objetivo. La senal
// crece con la corriente del LED, asi que la relacion es monotona.
uint16_t OpticaLMG::_buscarDuty(uint8_t i, float objetivo) {
    uint16_t lo = 1, hi = LED_DUTY_MAX, mejor = hi;
    float mejor_err = 1e9f;
    while (lo <= hi) {
        const uint16_t mid = lo + (hi - lo) / 2;
        _duty[i] = mid;
        const float r = _medir(i, AUTOCAL_MUESTRAS);
        const float err = fabsf(r - objetivo);
        if (err < mejor_err) { mejor_err = err; mejor = mid; }
        if (r < objetivo) lo = mid + 1;
        else if (mid == 0) break;
        else hi = mid - 1;
    }
    return mejor;
}

bool OpticaLMG::autocalibrar(bool verificarGestoMax) {
    const float FS       = FONDO_ESCALA_UTIL_MV;
    const float objetivo = AUTOCAL_OBJETIVO_FRAC * FS;
    uint16_t previos[NUM_LMG];
    for (uint8_t i = 0; i < NUM_LMG; i++) previos[i] = _duty[i];
    _debil = 0;

    Serial.printf("[OPTICA] Autocalibracion: reposo objetivo %.0f mV "
                  "(%.0f%% de %.0f mV). Mantenga la mano quieta.\n",
                  objetivo, 100 * AUTOCAL_OBJETIVO_FRAC, FS);

    // ---- 1. Todos a corriente nominal: medir la dispersion ----
    float r[NUM_LMG];
    float rmin = 1e9f, rmax = -1e9f;
    for (uint8_t i = 0; i < NUM_LMG; i++) {
        _duty[i] = DUTY_NOMINAL;
        r[i] = _medir(i, AUTOCAL_MUESTRAS);
        rmin = min(rmin, r[i]);
        rmax = max(rmax, r[i]);
    }
    const float dispersion = rmin > 1.0f ? rmax / rmin : 1e9f;
    Serial.printf("[OPTICA] Reposo a corriente nominal: dispersion "
                  "max/min = %.2f (umbral %.2f)\n",
                  dispersion, AUTOCAL_UMBRAL_DISPERSION);

    // ---- 2. Decidir: corriente fija o ajuste por canal ----
    if (dispersion < AUTOCAL_UMBRAL_DISPERSION && rmax < AUTOCAL_LIMITE_FRAC * FS) {
        // Dispersion baja: la normalizacion por canal en software basta.
        // Ajustar sin necesidad solo anadiria variacion entre sesiones.
        Serial.println("[OPTICA] Dispersion baja: se mantiene corriente fija "
                       "y la normaliza el software.");
    } else {
        Serial.println("[OPTICA] Dispersion alta: ajuste por canal.");
        for (uint8_t i = 0; i < NUM_LMG; i++) {
            _duty[i] = _buscarDuty(i, objetivo);
            if (_duty[i] >= LED_DUTY_MAX - 1 &&
                _medir(i, AUTOCAL_MUESTRAS) < 0.5f * objetivo) {
                // Ni al maximo llega a la mitad del objetivo: acoplamiento
                // pobre o sensor despegado. Se avisa, no se oculta.
                _debil |= (1 << i);
            }
        }
    }

    // ---- 3. Reposo final por canal: el S-barra-r ----
    for (uint8_t i = 0; i < NUM_LMG; i++) {
        _reposo[i] = _medir(i, 2 * AUTOCAL_MUESTRAS);
    }

    // ---- 4. Opcional: el gesto maximo no debe recortar ----
    if (verificarGestoMax) {
        Serial.println("[OPTICA] Contraiga la mano AL MAXIMO durante 3 s...");
        delay(1500);
        float pico[NUM_LMG] = {0};
        const unsigned long t0 = millis();
        while (millis() - t0 < 3000) {
            for (uint8_t i = 0; i < NUM_LMG; i++) {
                pico[i] = max(pico[i], leerCanal(i));
            }
        }
        for (uint8_t i = 0; i < NUM_LMG; i++) {
            if (pico[i] > AUTOCAL_LIMITE_FRAC * FS) {
                // Reducir la corriente en proporcion para devolver el pico
                // al 90% del limite, y remedir el reposo.
                const float f = 0.9f * AUTOCAL_LIMITE_FRAC * FS / pico[i];
                _duty[i] = (uint16_t)max(1.0f, _duty[i] * f);
                _reposo[i] = _medir(i, 2 * AUTOCAL_MUESTRAS);
                Serial.printf("[OPTICA] Canal %u recortaba (pico %.0f mV): "
                              "corriente reducida.\n", i + 1, pico[i]);
            }
        }
    }

    apagarTodos();

    // ---- 5. Detectar si la ganancia cambio ----
    _cambio = false;
    for (uint8_t i = 0; i < NUM_LMG; i++) {
        const float rel = fabsf((float)_duty[i] - previos[i]) /
                          max((float)previos[i], 1.0f);
        if (rel > 0.05f) _cambio = true;
    }

    _guardarNVS();
    info();
    if (_debil) {
        Serial.printf("[OPTICA] AVISO: canales debiles (bitmap 0x%02X). "
                      "Revise el contacto del modulo con la piel.\n", _debil);
    }
    return _debil == 0;
}

bool OpticaLMG::_guardarNVS() {
    Preferences p;
    if (!p.begin(NVS_NS, false)) return false;
    p.putUChar("n", NUM_LMG);
    p.putBytes("duty", _duty, sizeof(_duty));
    p.putBytes("reposo", _reposo, sizeof(_reposo));
    p.end();
    return true;
}

bool OpticaLMG::_cargarNVS() {
    Preferences p;
    if (!p.begin(NVS_NS, true)) return false;
    const bool ok = p.getUChar("n", 0) == NUM_LMG &&
                    p.getBytes("duty", _duty, sizeof(_duty)) == sizeof(_duty) &&
                    p.getBytes("reposo", _reposo, sizeof(_reposo)) == sizeof(_reposo);
    p.end();
    return ok;
}

void OpticaLMG::info() const {
    Serial.println("[OPTICA] canal  duty   %max   reposo(mV)  %FS   oscura(mV)");
    for (uint8_t i = 0; i < NUM_LMG; i++) {
        Serial.printf("[OPTICA]   %u   %4u  %5.1f  %10.1f  %5.1f  %10.1f%s\n",
                      i + 1, _duty[i], 100.0f * _duty[i] / LED_DUTY_MAX,
                      _reposo[i], 100.0f * _reposo[i] / FONDO_ESCALA_UTIL_MV,
                      _oscura[i], (_debil & (1 << i)) ? "  DEBIL" : "");
    }
}
