#include "optica_omg.h"
#include <Preferences.h>
#include "driver/gpio.h"

static const char *NVS_NS = "omg";

OpticaOMG::OpticaOMG()
    : _tOn(T_ON_US_DEFECTO), _tOff(T_OFF_US_DEFECTO), _cap(DRIVE_CAP_DEFECTO) {}

void OpticaOMG::begin() {
    analogReadResolution(ADC_BITS);
    for (uint8_t k = 0; k < NUM_OPT; k++) {
        analogSetPinAttenuation(PIN_OUT[k], ADC_11db);
        pinMode(PIN_IR[k], OUTPUT);
        digitalWrite(PIN_IR[k], LOW);
    }
    _aplicarDriveCap();
    _cargarNVS();
}

void OpticaOMG::_aplicarDriveCap() {
    // Despues de pinMode: la capacidad queda fijada a mano y no la de
    // fabrica.
    for (uint8_t k = 0; k < NUM_OPT; k++) {
        gpio_set_drive_capability((gpio_num_t)PIN_IR[k], (gpio_drive_cap_t)_cap);
    }
}

void OpticaOMG::encender(uint8_t k) { digitalWrite(PIN_IR[k], HIGH); }
void OpticaOMG::apagar(uint8_t k)   { digitalWrite(PIN_IR[k], LOW); }
void OpticaOMG::encenderTodos() { for (uint8_t k = 0; k < NUM_OPT; k++) encender(k); }
void OpticaOMG::apagarTodos()   { for (uint8_t k = 0; k < NUM_OPT; k++) apagar(k); }

float OpticaOMG::leerMv(uint8_t k) {
    const uint8_t pin = PIN_OUT[k];
#if DESCARTAR_PRIMERA
    (void)analogRead(pin);
#endif
    uint32_t s = 0;
    for (uint8_t i = 0; i < N_MUESTRAS; i++) s += analogReadMilliVolts(pin);
    return s / (float)N_MUESTRAS;
}

void OpticaOMG::medir(float vApag[NUM_OPT], float vEnc[NUM_OPT]) {
    // 1. Trama oscura.
    apagarTodos();
    delayMicroseconds(_tOff);
    for (uint8_t k = 0; k < NUM_OPT; k++) vApag[k] = leerMv(k);

    // 2. Trama iluminada.
#if MODO_LED == MODO_SIMULTANEO
    encenderTodos();
    delayMicroseconds(_tOn);
    for (uint8_t k = 0; k < NUM_OPT; k++) vEnc[k] = leerMv(k);
    apagarTodos();
#else
    for (uint8_t k = 0; k < NUM_OPT; k++) {
        encender(k);
        delayMicroseconds(_tOn);
        vEnc[k] = leerMv(k);
        apagar(k);
    }
#endif
}

bool OpticaOMG::fijarTOn(uint32_t us) {
    if (us > T_MAX_US) return false;
    _tOn = us;
    _guardarNVS();
    return true;
}

bool OpticaOMG::fijarTOff(uint32_t us) {
    if (us > T_MAX_US) return false;
    _tOff = us;
    _guardarNVS();
    return true;
}

bool OpticaOMG::fijarDriveCap(uint8_t cap) {
    if (cap > 3) return false;
    _cap = cap;
    _aplicarDriveCap();
    return true;
}

void OpticaOMG::_guardarNVS() {
    Preferences p;
    if (!p.begin(NVS_NS, false)) return;
    p.putUInt("t_on", _tOn);
    p.putUInt("t_off", _tOff);
    p.end();
}

void OpticaOMG::_cargarNVS() {
    Preferences p;
    if (!p.begin(NVS_NS, true)) return;     // sin datos: los de config.h
    _tOn  = p.getUInt("t_on", T_ON_US_DEFECTO);
    _tOff = p.getUInt("t_off", T_OFF_US_DEFECTO);
    p.end();
    if (_tOn > T_MAX_US)  _tOn = T_ON_US_DEFECTO;
    if (_tOff > T_MAX_US) _tOff = T_OFF_US_DEFECTO;
}

static void imprimirLista(const char *etiqueta, const uint8_t *v) {
    Serial.print(etiqueta);
    for (uint8_t k = 0; k < NUM_OPT; k++) {
        Serial.print(v[k]);
        Serial.print(k + 1 < NUM_OPT ? "," : "\n");
    }
}

void OpticaOMG::imprimirConfig() const {
    Serial.printf("[OPTICA_CONFIG] sensor=QRE1113 adc=interno bits=%d "
                  "atenuacion=11db n_muestras=%d descartar_primera=%d modo=%s "
                  "t_on_us=%lu t_off_us=%lu drive_cap=%u vcc_v=%.1f r1_ohm=%d "
                  "r2_ohm=%d fs_hz=%d\n",
                  ADC_BITS, N_MUESTRAS, DESCARTAR_PRIMERA,
                  MODO_LED == MODO_SIMULTANEO ? "simultaneo" : "secuencial",
                  (unsigned long)_tOn, (unsigned long)_tOff, _cap, VCC_MODULO_V,
                  R1_OHM, R2_OHM, 1000000 / INTERVALO_US);
    imprimirLista("[OPTICA_PINES_OUT] ", PIN_OUT);
    imprimirLista("[OPTICA_PINES_IR] ", PIN_IR);
    // Capacidad releida de cada pin: la que de verdad tiene el GPIO.
    uint8_t cap[NUM_OPT];
    for (uint8_t k = 0; k < NUM_OPT; k++) {
        gpio_drive_cap_t c = GPIO_DRIVE_CAP_DEFAULT;
        gpio_get_drive_capability((gpio_num_t)PIN_IR[k], &c);
        cap[k] = (uint8_t)c;
    }
    imprimirLista("[OPTICA_DRIVE_CAP] ", cap);
}

void OpticaOMG::imprimirPines() const {
    Serial.println("[PINES] Confirme esta tabla contra el cableado real:");
    for (uint8_t k = 0; k < NUM_OPT; k++) {
        Serial.printf("[PINES] modulo %u: OUT GPIO%u (%s)  IR GPIO%u\n", k + 1,
                      PIN_OUT[k], CANAL_ADC[k], PIN_IR[k]);
    }
    Serial.printf("[PINES] I2C MPU6050: SDA GPIO%d, SCL GPIO%d. Pin 5 (Led) "
                  "de cada JST sin conectar. VCC de los modulos a 3,3 V.\n",
                  PIN_SDA, PIN_SCL);
}

// ======================== 'C': ASENTAMIENTO ========================
// Muestras crudas del ADC, lo mas rapido que deja (~20 us de objetivo),
// durante 3 ms despues de encender o de apagar el LED del canal.
static const uint16_t N_CURVA = 200;
static const uint32_t VENTANA_CURVA_US = 3000;
static const uint32_t PASO_CURVA_US = 20;
static const uint8_t  N_PREVIAS = 10;

struct Curva {
    uint32_t t[N_CURVA];
    uint16_t x[N_CURVA];
    uint16_t n;
};
static Curva curva;

struct Tiempos {
    float t90, t95, t99;   // us
    float delta;           // cuentas del ADC, final menos inicial
    float paso;            // us medios entre muestras
    bool  asentado;        // el final ya no se movia al cerrar la ventana
};

static float mediaInicial(uint8_t pin) {
    uint32_t s = 0;
    for (uint8_t i = 0; i < N_PREVIAS; i++) s += analogRead(pin);
    return s / (float)N_PREVIAS;
}

static void muestrear(uint8_t pin, uint32_t t0) {
    curva.n = 0;
    while (curva.n < N_CURVA) {
        const uint32_t t = micros() - t0;
        if (t > VENTANA_CURVA_US) break;
        curva.x[curva.n] = analogRead(pin);
        curva.t[curva.n] = t;
        curva.n++;
        while (micros() - t0 < t + PASO_CURVA_US) { }
    }
}

static float mediaTramo(uint16_t a, uint16_t b) {
    float s = 0;
    for (uint16_t i = a; i < b; i++) s += curva.x[i];
    return b > a ? s / (b - a) : 0;
}

// t_p: el instante a partir del cual la senal, suavizada con 3 muestras,
// ya no sale de una banda de (1 - p) * |delta| alrededor del final.
// Con un ADC de 12 bits ruidoso, t99 puede quedar inflado por el ruido:
// por eso se imprime tambien delta.
static Tiempos analizar(float x0) {
    Tiempos r = {0, 0, 0, 0, 0, false};
    const uint16_t n = curva.n;
    if (n < 10) return r;
    const uint16_t n20 = n / 5;
    const float xf = mediaTramo(n - n20, n);
    r.delta = xf - x0;
    r.paso = (curva.t[n - 1] - curva.t[0]) / (float)(n - 1);
    r.asentado = fabsf(mediaTramo(n - 2 * n20, n - n20) - xf) <= 0.01f * fabsf(r.delta);
    const float p[3] = {0.90f, 0.95f, 0.99f};
    float *salida[3] = {&r.t90, &r.t95, &r.t99};
    for (uint8_t j = 0; j < 3; j++) {
        const float banda = (1.0f - p[j]) * fabsf(r.delta);
        *salida[j] = curva.t[0];
        for (int i = n - 2; i >= 1; i--) {
            const float suave = (curva.x[i - 1] + curva.x[i] + curva.x[i + 1]) / 3.0f;
            if (fabsf(suave - xf) > banda) {
                *salida[j] = curva.t[i + 1];
                break;
            }
        }
    }
    return r;
}

static void imprimirTiempos(uint8_t k, const char *fase, const Tiempos &r) {
    Serial.printf("[ASENTAMIENTO] modulo %u %s: delta=%.0f cuentas t90=%.0f us "
                  "t95=%.0f us t99=%.0f us paso=%.1f us%s\n", k + 1, fase,
                  r.delta, r.t90, r.t95, r.t99, r.paso,
                  r.asentado ? "" : "  AVISO: no asentado en 3 ms");
}

void OpticaOMG::curvaAsentamiento() {
    Serial.println("[ASENTAMIENTO] Curva por modulo, su LED solo. Mano quieta.");
    float maxOn = 0, maxOff = 0;
    bool todosAsentados = true;
    for (uint8_t k = 0; k < NUM_OPT; k++) {
        const uint8_t pin = PIN_OUT[k];
        apagarTodos();
        delayMicroseconds(VENTANA_CURVA_US);
        (void)analogRead(pin);                 // canal nuevo
        float x0 = mediaInicial(pin);
        encender(k);
        muestrear(pin, micros());
        const Tiempos on = analizar(x0);

        x0 = mediaInicial(pin);
        apagar(k);
        muestrear(pin, micros());
        const Tiempos off = analizar(x0);

        imprimirTiempos(k, "encender", on);
        imprimirTiempos(k, "apagar", off);
        maxOn  = max(maxOn, on.t99);
        maxOff = max(maxOff, off.t99);
        todosAsentados &= on.asentado && off.asentado;
    }
    apagarTodos();
    const uint32_t sugOn  = (uint32_t)ceilf(1.2f * maxOn);
    const uint32_t sugOff = (uint32_t)ceilf(1.2f * maxOff);
    Serial.printf("[ASENTAMIENTO] peor t99: encender %.0f us, apagar %.0f us. "
                  "Sugerido (t99 + 20%%): T_ON_US=%lu T_OFF_US=%lu. Para "
                  "aplicarlo: E%lu y O%lu\n", maxOn, maxOff,
                  (unsigned long)sugOn, (unsigned long)sugOff,
                  (unsigned long)sugOn, (unsigned long)sugOff);
    if (!todosAsentados) {
        Serial.println("[ASENTAMIENTO] AVISO: algun canal no se asento en 3 ms; "
                       "el t99 de ese canal es solo una cota inferior.");
    }
}

// ======================== 'X': DIAFONIA ========================
// Por modulo k, promediando 20 veces:
//   base    todos los LED apagados
//   otros   los otros 7 encendidos, el de k apagado
//   propio  solo el de k encendido
// diafonia = base - otros (cuanta luz de los vecinos llega a k), en mV y
// en % de la senal propia, base - propio.
void OpticaOMG::diafonia() {
    const uint8_t REP = 20;
    Serial.println("[DIAFONIA] Por modulo, 20 repeticiones. Mano quieta.");
    for (uint8_t k = 0; k < NUM_OPT; k++) {
        float base = 0, otros = 0, propio = 0;
        for (uint8_t r = 0; r < REP; r++) {
            apagarTodos();
            delayMicroseconds(_tOff);
            base += leerMv(k);

            for (uint8_t j = 0; j < NUM_OPT; j++) if (j != k) encender(j);
            delayMicroseconds(_tOn);
            otros += leerMv(k);
            apagarTodos();

            delayMicroseconds(_tOff);
            encender(k);
            delayMicroseconds(_tOn);
            propio += leerMv(k);
            apagar(k);
        }
        base /= REP; otros /= REP; propio /= REP;
        const float diaf = base - otros;
        const float senal = base - propio;
        const float pct = fabsf(senal) > 1.0f ? 100.0f * diaf / senal : NAN;
        Serial.printf("[DIAFONIA] modulo %u: base=%.1f otros=%.1f propio=%.1f mV "
                      "diafonia=%.1f mV (%.1f%% de su senal de %.1f mV)%s\n",
                      k + 1, base, otros, propio, diaf, pct, senal,
                      fabsf(pct) > 5.0f ? "  AVISO: mas del 5%" : "");
    }
    apagarTodos();
}
