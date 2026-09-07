#include "calibracion.h"
#include <Preferences.h>
#include <math.h>

static const char *NVS_NAMESPACE = "calib";
static const char *NVS_CLAVE_MEDIA = "media";
static const char *NVS_CLAVE_SD    = "sd";
static const char *NVS_CLAVE_N     = "nfeat";

// Patrones de destellos y pulsos hapticos. Se distinguen por CUANTAS
// veces se repiten, no por su duracion, para que sean contables por una
// persona sin entrenamiento.
static const uint8_t PATRON_OK           = 1;   // calibracion correcta
static const uint8_t PATRON_FALLIDA      = 3;   // intento fallido
static const uint8_t PATRON_AUSENTE      = 2;   // nunca se calibro

Calibrador::Calibrador()
    : _nMuestras(0), _enStaging(0), _ventanasCompletas(0),
      _calibrado(false), _capturando(false),
      _tInicio(0), _tUltimaMuestra(0),
      _ultimaUs(0), _acumUs(0), _nNorm(0),
      _estado(CALIB_ESTADO_AUSENTE), _tUltimoAviso(0),
      _senalHaptica(nullptr) {
    _reiniciarAcumuladores();
    for (int i = 0; i < NUM_FEATURES; i++) {
        _media[i] = 0.0f;
        _sd[i]    = 1.0f;
        _invSd[i] = 1.0f;
    }
}

void Calibrador::_reiniciarAcumuladores() {
    for (int i = 0; i < NUM_FEATURES; i++) {
        _s1[i] = 0.0;
        _s2[i] = 0.0;
    }
    _nMuestras = 0;
    _enStaging = 0;
    _ventanasCompletas = 0;
}

bool Calibrador::begin() {
#if PIN_LED >= 0
    pinMode(PIN_LED, OUTPUT);
    digitalWrite(PIN_LED, LOW);
#endif
    const bool hay = _cargarNVS();
    _estado = hay ? CALIB_ESTADO_OK : CALIB_ESTADO_AUSENTE;
    return hay;
}

// ============================================================
// SENALIZACION
// ============================================================
// El usuario final no tiene consola. Un fallo de calibracion que solo
// aparezca en Serial es, en la practica, un fallo silencioso: la
// persona cree que recalibro y opera con las estadisticas de otra
// sesion, quiza con el brazalete en otra posicion.
void Calibrador::_senalizar(uint8_t nDestellos) {
#if PIN_LED >= 0
    for (uint8_t i = 0; i < nDestellos; i++) {
        digitalWrite(PIN_LED, HIGH);
        delay(120);
        digitalWrite(PIN_LED, LOW);
        delay(120);
    }
#endif
#if SENAL_HAPTICA_HABILITADA
    // Canal primario: se percibe con la protesis puesta, que es
    // justamente la situacion en la que ocurre el fallo.
    if (_senalHaptica) _senalHaptica(nDestellos);
#endif
}

void Calibrador::atenderAvisos(unsigned long ahora) {
    if (_estado == CALIB_ESTADO_OK) return;
    if (_capturando) return;   // no interrumpir una captura en curso

    if (ahora - _tUltimoAviso < (unsigned long)CALIB_AVISO_PERIODO_MS) return;
    _tUltimoAviso = ahora;

    if (_estado == CALIB_ESTADO_NO_CONFIRM) {
        Serial.println("[CALIB] AVISO PERSISTENTE: el ultimo intento de "
                       "calibracion FALLO. Se sigue operando con la "
                       "calibracion anterior, que puede no corresponder a "
                       "la colocacion actual del brazalete. Envie 'C' para "
                       "reintentar.");
        _senalizar(PATRON_FALLIDA);
    } else {
        Serial.println("[CALIB] AVISO PERSISTENTE: no hay calibracion. La "
                       "inferencia corre sobre senal cruda, en una escala "
                       "distinta a la del entrenamiento. Envie 'C'.");
        _senalizar(PATRON_AUSENTE);
    }
}

// ============================================================
// CAPTURA
// ============================================================
void Calibrador::iniciar(unsigned long ahora) {
    _reiniciarAcumuladores();
    _capturando = true;
    _tInicio = ahora;
    _tUltimaMuestra = 0;

    Serial.printf("[CALIB] Iniciando. Tipo: %s\n",
                  (CALIB_TIPO == CALIB_SOLO_REPOSO)
                      ? "solo reposo" : "secuencia de gestos");
    Serial.printf("[CALIB] Bloque de %lu ms, margenes %lu/%lu ms. "
                  "Quedese quieto.\n",
                  (unsigned long)CALIB_DURACION_MS,
                  (unsigned long)CALIB_MARGEN_INICIAL_MS,
                  (unsigned long)CALIB_MARGEN_FINAL_MS);
}

bool Calibrador::acumular(const float muestra[NUM_FEATURES],
                          unsigned long ahora) {
    if (!_capturando) return false;

    const unsigned long transcurrido = ahora - _tInicio;

    // Fin del bloque: se cierra sin considerar el margen final.
    if (transcurrido >= (unsigned long)CALIB_DURACION_MS) {
        finalizar();
        return false;
    }

    // Margenes. Se descartan por el mismo motivo que en el protocolo de
    // captura: al inicio el usuario todavia se esta acomodando, y al
    // final anticipa el fin del bloque.
    if (transcurrido < (unsigned long)CALIB_MARGEN_INICIAL_MS) {
        return true;
    }
    if (transcurrido >= (unsigned long)(CALIB_DURACION_MS
                                        - CALIB_MARGEN_FINAL_MS)) {
        return true;
    }

    // Deteccion de hueco temporal. Mismo criterio que
    // preprocesamiento.py: un salto mayor a 3 periodos de muestreo
    // rompe la continuidad. Promediar dos tramos separados por un hueco
    // no describiria ningun estado real del usuario.
    if (_tUltimaMuestra != 0) {
        const unsigned long dt = ahora - _tUltimaMuestra;
        if (dt > (unsigned long)(3 * INTERVALO_MUESTRA_MS)) {
            Serial.printf("[CALIB] ABORTADA: hueco de %lu ms entre muestras "
                          "(maximo %d ms). La calibracion debe salir de un "
                          "tramo continuo.\n",
                          dt, 3 * INTERVALO_MUESTRA_MS);
            abortar();
            return false;
        }
    }
    _tUltimaMuestra = ahora;

    // Staging: la muestra entra en la ventana en curso. Solo cuando la
    // ventana se completa se pliega a los acumuladores, de modo que
    // ninguna estadistica proviene de una ventana parcial ni de una que
    // cruce el limite del bloque.
    for (int i = 0; i < NUM_FEATURES; i++) {
        _staging[_enStaging][i] = muestra[i];
    }
    _enStaging++;

    if (_enStaging >= TAMANO_VENTANA) {
        _plegarStaging();
    }

    return true;
}

void Calibrador::_plegarStaging() {
    for (int t = 0; t < TAMANO_VENTANA; t++) {
        for (int i = 0; i < NUM_FEATURES; i++) {
            const double v = (double)_staging[t][i];
            _s1[i] += v;
            _s2[i] += v * v;
        }
    }
    _nMuestras += TAMANO_VENTANA;
    _ventanasCompletas++;
    _enStaging = 0;
}

bool Calibrador::finalizar() {
    _capturando = false;

    // La ventana parcial pendiente se descarta a proposito: incluirla
    // significaria estadisticas procedentes de una ventana que no cabe
    // entera en el bloque.
    if (_enStaging > 0) {
        Serial.printf("[CALIB] Descartadas %u muestras de la ventana "
                      "incompleta final.\n", _enStaging);
        _enStaging = 0;
    }

    if (_ventanasCompletas < CALIB_MIN_VENTANAS) {
        Serial.printf("[CALIB] FALLIDA: solo %u ventanas completas, "
                      "minimo %d. No se guarda nada.\n",
                      (unsigned)_ventanasCompletas, CALIB_MIN_VENTANAS);
        // El estado NO vuelve a OK aunque hubiera una calibracion previa
        // valida: el usuario acaba de pedir recalibrar y no lo consiguio.
        _estado = CALIB_ESTADO_NO_CONFIRM;
        _tUltimoAviso = 0;    // avisar de inmediato, sin esperar el periodo
        _senalizar(PATRON_FALLIDA);
        return false;
    }

    const double n = (double)_nMuestras;
    for (int i = 0; i < NUM_FEATURES; i++) {
        const double media = _s1[i] / n;
        // var = E[x^2] - E[x]^2. Se satura a 0 porque la cancelacion
        // puede dar un negativo diminuto en un canal casi constante.
        double var = _s2[i] / n - media * media;
        if (var < 0.0) var = 0.0;

        _media[i] = (float)media;
        _sd[i]    = (float)sqrt(var);
        _invSd[i] = 1.0f / (_sd[i] + CALIB_EPSILON);
    }

    _calibrado = true;
    _estado = CALIB_ESTADO_OK;    // unico punto donde vuelve a OK
    _senalizar(PATRON_OK);

    Serial.printf("[CALIB] OK: %u ventanas completas (%lu muestras, %.1f s)\n",
                  (unsigned)_ventanasCompletas, (unsigned long)_nMuestras,
                  _nMuestras * INTERVALO_MUESTRA_MS / 1000.0f);
    info();

    if (!_guardarNVS()) {
        Serial.println("[CALIB] AVISO: no se pudo persistir en NVS. La "
                       "calibracion vale para esta sesion pero se perdera "
                       "al reiniciar.");
    }
    return true;
}

void Calibrador::abortar() {
    _capturando = false;
    _reiniciarAcumuladores();

    // Se conserva la calibracion anterior para no dejar el dispositivo
    // inservible, pero el estado queda NO CONFIRMADA y el aviso se
    // repite cada CALIB_AVISO_PERIODO_MS hasta que una calibracion
    // termine bien. Ni se pierde la funcionalidad ni se falla en
    // silencio.
    _estado = CALIB_ESTADO_NO_CONFIRM;
    _tUltimoAviso = 0;

    Serial.println("[CALIB] Captura ABORTADA. Se conserva la calibracion "
                   "anterior, si la habia, pero queda marcada como NO "
                   "CONFIRMADA: puede no corresponder a la colocacion "
                   "actual del brazalete. Reintente con 'C'.");
    _senalizar(PATRON_FALLIDA);
}

// ============================================================
// NORMALIZACION
// ============================================================
void Calibrador::normalizar(float ventana[TAMANO_VENTANA][NUM_FEATURES]) {
    if (!_calibrado) return;

    const unsigned long t0 = micros();

    // z = (x - media) * inv_sd. La division se hizo una sola vez al
    // calibrar, asi que aqui son TAMANO_VENTANA * NUM_FEATURES = 160
    // restas y multiplicaciones.
    for (int t = 0; t < TAMANO_VENTANA; t++) {
        for (int i = 0; i < NUM_FEATURES; i++) {
            ventana[t][i] = (ventana[t][i] - _media[i]) * _invSd[i];
        }
    }

    _ultimaUs = micros() - t0;
    _acumUs += _ultimaUs;
    _nNorm++;
}

// ============================================================
// PERSISTENCIA EN NVS
// ============================================================
bool Calibrador::_guardarNVS() {
    Preferences prefs;
    if (!prefs.begin(NVS_NAMESPACE, false)) return false;

    prefs.putUChar(NVS_CLAVE_N, (uint8_t)NUM_FEATURES);
    const size_t bytes = sizeof(float) * NUM_FEATURES;
    const bool ok =
        prefs.putBytes(NVS_CLAVE_MEDIA, _media, bytes) == bytes &&
        prefs.putBytes(NVS_CLAVE_SD, _sd, bytes) == bytes;

    prefs.end();
    if (ok) {
        Serial.printf("[CALIB] Guardada en NVS (%d medias + %d desviaciones)\n",
                      NUM_FEATURES, NUM_FEATURES);
    }
    return ok;
}

bool Calibrador::_cargarNVS() {
    Preferences prefs;
    if (!prefs.begin(NVS_NAMESPACE, true)) return false;

    const uint8_t nGuardado = prefs.getUChar(NVS_CLAVE_N, 0);
    if (nGuardado != NUM_FEATURES) {
        // Guardada con otro numero de canales: descartar en vez de leer
        // basura. Ocurre al cambiar el vector de entrada, como en el
        // paso de 9 a 8 canales.
        if (nGuardado != 0) {
            Serial.printf("[CALIB] Calibracion guardada con %u canales, el "
                          "firmware espera %d. Se ignora; recalibre.\n",
                          nGuardado, NUM_FEATURES);
        }
        prefs.end();
        return false;
    }

    const size_t bytes = sizeof(float) * NUM_FEATURES;
    const bool ok =
        prefs.getBytes(NVS_CLAVE_MEDIA, _media, bytes) == bytes &&
        prefs.getBytes(NVS_CLAVE_SD, _sd, bytes) == bytes;
    prefs.end();

    if (!ok) return false;

    for (int i = 0; i < NUM_FEATURES; i++) {
        _invSd[i] = 1.0f / (_sd[i] + CALIB_EPSILON);
    }
    _calibrado = true;
    Serial.println("[CALIB] Calibracion recuperada de NVS:");
    info();
    return true;
}

void Calibrador::borrar() {
    Preferences prefs;
    if (prefs.begin(NVS_NAMESPACE, false)) {
        prefs.clear();
        prefs.end();
    }
    _calibrado = false;
    Serial.println("[CALIB] Calibracion borrada de NVS.");
}

void Calibrador::info() const {
    if (!_calibrado) {
        Serial.println("[CALIB] Sin calibracion. La inferencia corre sobre "
                       "senal cruda, en una escala distinta a la del "
                       "entrenamiento.");
        return;
    }
    Serial.println("[CALIB] canal      media         sd");
    for (int i = 0; i < NUM_FEATURES; i++) {
        const char *nombre = (i < NUM_LMG) ? "LMG" : "ACC";
        const int   idx    = (i < NUM_LMG) ? i + 1 : i - NUM_LMG + 1;
        Serial.printf("[CALIB]   %s%d  %+11.4f  %10.4f\n",
                      nombre, idx, _media[i], _sd[i]);
    }
}
