/*
 * inferencia_control.ino - Modulo 3: Inferencia en Tiempo Real y Control
 * =====================================================================
 * Protesis transradial - Fusion sensorial y Deep Learning (TinyML)
 *
 * REPARTO ENTRE NUCLEOS (config.h, intercambio_nucleos.h):
 *
 *   NUCLEO 0 - tarea de tiempo real, cada 10 ms, con TODO el I2C:
 *     [1] Comandos por Serial
 *     [2] Leer sensores predictivos (LMG + IMU) → 1 muestra cada 10 ms
 *     [3] Rampa de servos (PCA9685)
 *     [4] LAZO CERRADO: los 5 FSR (ADC interno) y frenado, cada 10 ms
 *     [5] Acumular en buffer circular (ventana de 200 ms = 20 muestras) y,
 *         cada STRIDE muestras, publicar una copia normalizada de la
 *         ventana para el nucleo 1
 *     [6] Leer el ultimo gesto del nucleo 1 y, si cambio, fijar el
 *         objetivo de los servos
 *
 *   NUCLEO 1 - loop() de Arduino, solo inferencia:
 *     Espera una ventana, la copia, ejecuta TFLite Micro y deja el gesto.
 *     Calculo puro: ningun periferico, ni Serial.
 *
 * MAQUINA DE ESTADOS:
 *   Los gestos se ejecutan como maquina de estados:
 *     - Estado REPOSO: modelo en idle, servos abiertos
 *     - Estado TRANSICION: nuevo gesto detectado, comenzar cierre
 *     - Estado AGARRE: gesto mantenido, monitorear FSR continuamente
 *     - Estado LIBERACION: gesto termino, abrir servos
 *
 * TIMING CRITICO:
 *   - Muestreo: cada 10 ms (100 Hz), con xTaskDelayUntil en el nucleo 0
 *   - Inferencia: sobre la ventana mas reciente, en el nucleo 1; si tarda
 *     mas que el stride, las ventanas intermedias se descartan
 *   - Lectura FSR: los 5 en cada ciclo de 10 ms
 *   - Rampa de servos: cada RAMPA_PERIODO_MS, en el nucleo 0; nunca se
 *     congela por una inferencia
 */

#include <Wire.h>
#include "config.h"
#include "adc_lmg.h"
#include "optica_lmg.h"
#include "sensor_imu.h"
#include "sliding_window.h"
#include "inferencia.h"
#include "control_servos.h"
#include "feedback_fsr.h"
#include "calibracion.h"
#include "intercambio_nucleos.h"

// ======================== INSTANCIAS GLOBALES ========================
// Todas las usa solo el nucleo 0, salvo 'tflite', que solo usa el nucleo 1
// (despues de begin()), e 'intercambio', que es el punto de encuentro.
ADC_LMG         adcLmg;
OpticaLMG       optica(adcLmg);
SensorIMU       imu;
SlidingWindow   ventana;
MotorInferencia tflite;
ControlServos   servos;
FeedbackFSR     feedback;
Calibrador      calibrador;

// ======================== NUCLEOS ========================
IntercambioNucleos intercambio;
TaskHandle_t       tareaInferencia  = nullptr;   // loop() de Arduino, nucleo 1
TaskHandle_t       tareaTiempoReal  = nullptr;   // nucleo 0
SemaphoreHandle_t  semHardwareListo = nullptr;
SemaphoreHandle_t  semModeloListo   = nullptr;
// Ventana propia del nucleo 1 (solo la toca loop())
float ventanaInferencia[TAMANO_VENTANA][NUM_FEATURES];

// ======================== INSTRUMENTACION DE LATENCIA ========================
// Se mide en vivo en vez de estimarse, porque el coste real depende del
// modelo cuantizado. Todo esto lo escribe y lo lee el nucleo 0.
unsigned long tMuestreoUs     = 0;   // 5 LMG + IMU
unsigned long tInferenciaUs   = 0;   // Reset + Invoke, medido en el nucleo 1
uint32_t      ciclosMedidos   = 0;   // resultados de inferencia recibidos
unsigned long acumMuestreoUs  = 0;
unsigned long acumInferenciaUs = 0;
unsigned long peorInferenciaUs = 0;
// Latencia ventana -> gesto: desde que el nucleo 0 publica la ventana hasta
// que lee su resultado. Es la parte de la latencia que anade el firmware.
unsigned long peorLatenciaUs  = 0;
unsigned long acumLatenciaUs  = 0;
// Ciclo del nucleo 0 (10 ms): duracion y ciclos que no cupieron
uint32_t      ciclosTR        = 0;
uint32_t      ciclosExcedidos = 0;
unsigned long peorCicloUs     = 0;
unsigned long acumCicloUs     = 0;
uint32_t      nResultadoVisto = 0;
// Los resultados de ventanas publicadas antes de 'S', 'A' o una
// calibracion no se aplican: se clasificaron con otra senal.
uint32_t      ventanaValidaDesde = 1;
ResultadoInferencia ultimoResultado;

// ======================== VARIABLES DE ESTADO ========================
uint8_t gestoActual       = GESTO_REST;
uint8_t gestoAnterior     = GESTO_REST;
bool    sistemaActivo     = false;
bool    primeraInferencia = true;
// Un comando bloqueante rompe el periodo: el ciclo no se mide y el
// planificador se resincroniza en vez de encadenar ciclos atrasados.
bool    cicloInterrumpido = false;

// Contador de muestras entre inferencias (cada STRIDE muestras)
uint8_t contadorMuestras = 0;

// ======================== BUFFERS DE DATOS ========================
float muestra[NUM_FEATURES];                    // 1 muestra actual
float ventanaCompleta[TAMANO_VENTANA][NUM_FEATURES];  // copia a publicar
float valoresLMG[NUM_LMG];
float ax, ay, az;               // acelerometro: los 3 canales de IMU del modelo

// ======================== LECTURA DE FSR ========================
// Los cinco en cada ciclo de 10 ms, con el ADC interno del ESP32 (ver
// feedback_fsr.h). Se mide su coste para el presupuesto del ciclo.
unsigned long tFSRUs        = 0;    // coste de leer los 5 FSR en el ciclo
unsigned long acumFSRUs     = 0;
uint32_t      lecturasFSR   = 0;    // ciclos en que se leyeron

// ======================== SENAL HAPTICA ========================
// Pulso breve con los servos, contable por el usuario. Es el canal que
// funciona con la protesis puesta y sin consola, que es la situacion en
// la que ocurre un fallo de calibracion. Se pasa al calibrador como
// callback para no acoplarlo con el control de servos.
//
// Escribe al PCA9685 directamente y bloquea ~600 ms: corre en el nucleo 0
// (desde atenderAvisos) y marca el ciclo como interrumpido.
void senalHaptica(uint8_t repeticiones) {
    const uint8_t gestoPrevio = gestoActual;
    for (uint8_t i = 0; i < repeticiones; i++) {
        servos.ejecutarGesto(GESTO_POWER);      // flexion parcial
        delay(120);
        servos.ejecutarGesto(GESTO_REST);       // vuelta a reposo
        delay(120);
    }
    servos.ejecutarGesto(gestoPrevio);
    cicloInterrumpido = true;
}

// ======================== INSTRUMENTACION ========================
void reportarLatencias() {
    // ===== Nucleo 1: inferencia =====
    Serial.println("[LATENCIA] Inferencia (nucleo 1):");
    if (ciclosMedidos == 0) {
        Serial.println("[LATENCIA]   Aun no hay inferencias.");
    } else {
        const float medInferencia = acumInferenciaUs / (float)ciclosMedidos;
        const float medLatencia   = acumLatenciaUs / (float)ciclosMedidos;
        Serial.printf("[LATENCIA]   Reset + Invoke   : medio %8.1f us, peor %8lu us\n",
                      medInferencia, peorInferenciaUs);
        Serial.printf("[LATENCIA]   Ventana -> gesto : medio %8.1f us, peor %8lu us "
                      "(requisito < 150000 us)\n", medLatencia, peorLatenciaUs);
        Serial.printf("[LATENCIA]   Inferencias: %lu   descartadas: %lu   errores: %lu\n",
                      (unsigned long)ciclosMedidos,
                      (unsigned long)ultimoResultado.descartadas,
                      (unsigned long)ultimoResultado.errores);
        if (ultimoResultado.descartadas > 0) {
            Serial.printf("[LATENCIA]   La inferencia tarda mas que el stride (%d ms): "
                          "se clasifica siempre la ventana mas reciente.\n",
                          STRIDE * INTERVALO_MUESTRA_MS);
        }
    }

    // La normalizacion son TAMANO_VENTANA * NUM_FEATURES = 160 restas y
    // multiplicaciones, con la division ya resuelta al calibrar. La hace el
    // nucleo 0 al publicar la ventana. A 240 MHz con FPU deberia quedar en
    // el orden de 1-2 us; si se aleja mucho, revisar si el compilador esta
    // emitiendo operaciones en software.
    const uint32_t nNorm = calibrador.normalizacionesRealizadas();
    const float medNorm  = nNorm
        ? calibrador.normalizacionAcumuladaUs() / (float)nNorm
        : 0.0f;
    if (nNorm > 0 && medNorm > 50.0f) {
        Serial.printf("[LATENCIA] AVISO: la normalizacion tarda %.1f us, muy "
                      "por encima de los ~2 us esperados para 160 "
                      "multiplicaciones con FPU.\n", medNorm);
    }

    // ===== Nucleo 0: ciclo de 10 ms =====
    // Este es EL numero que decide si el muestreo corre a 100 Hz. Incluye
    // todo el ciclo: LMG, IMU, rampa, FSR, frenado, publicar la ventana
    // (con la normalizacion) y leer el gesto. Los comandos bloqueantes
    // ('A', 'T', senal haptica) no cuentan.
    Serial.println("[LATENCIA] Ciclo de tiempo real (nucleo 0, 10 ms):");
    const float medMuestreo = lecturasFSR ? acumMuestreoUs / (float)lecturasFSR : 0.0f;
    const float medFSR      = lecturasFSR ? acumFSRUs / (float)lecturasFSR : 0.0f;
    Serial.printf("[LATENCIA]   5 LMG + IMU      : %8.1f us\n", medMuestreo);
    Serial.printf("[LATENCIA]   5 FSR (ADC int.) : %8.1f us (%lu ciclos)\n",
                  medFSR, (unsigned long)lecturasFSR);
    Serial.printf("[LATENCIA]   Normalizacion    : %8.1f us (%lu ventanas)\n",
                  medNorm, (unsigned long)nNorm);
    if (ciclosTR > 0) {
        Serial.printf("[LATENCIA]   CICLO COMPLETO   : medio %8.1f us, peor %8lu us "
                      "(de 10000 us)\n", acumCicloUs / (float)ciclosTR, peorCicloUs);
        Serial.printf("[LATENCIA]   Ciclos: %lu   que no cupieron en 10 ms: %lu\n",
                      (unsigned long)ciclosTR, (unsigned long)ciclosExcedidos);
        if (peorCicloUs > 10000UL) {
            Serial.println("[LATENCIA] ERROR: el ciclo NO cabe en 10 ms. El "
                           "muestreo no corre a 100 Hz y la ventana del modelo "
                           "no mide 200 ms.");
        } else if (peorCicloUs > 9000UL) {
            Serial.printf("[LATENCIA] AVISO: solo %lu us de margen en el peor "
                          "ciclo. Ver LED_SETTLE_US en config.h.\n",
                          10000UL - peorCicloUs);
        }
    }

    // Tasa efectiva real de cada FSR, medida y no supuesta.
    Serial.println("[LATENCIA] Tasa efectiva por FSR:");
    feedback.info();
}

// ======================== AUTOTEST TEMPORAL ========================
// Mide el ciclo de muestreo REAL: 5 LMG (con trama oscura si esta
// habilitada) + 5 FSR + acelerometro, sin inferencia. El presupuesto de
// config.h es analitico; este es el numero que decide si el hardware
// montado sostiene 100 Hz. Se ejecuta al arrancar y con 'T'.
void autotestTemporal() {
    const uint16_t N = 200;
    unsigned long suma = 0, sumaLMG = 0, sumaFSR = 0, peor = 0;
    for (uint16_t k = 0; k < N; k++) {
        const unsigned long t0 = micros();
        optica.leerTodos(valoresLMG);
        const unsigned long t1 = micros();
        feedback.leerTodos(t1);
        const unsigned long t2 = micros();
        imu.leerAcelerometro(ax, ay, az);
        const unsigned long dt = micros() - t0;
        suma += dt;
        sumaLMG += t1 - t0;
        sumaFSR += t2 - t1;
        if (dt > peor) peor = dt;
    }
    feedback.reiniciar();   // que el autotest no deje lecturas validas

    const float medio   = suma / (float)N;
    const float medLMG  = sumaLMG / (float)N;
    const float medFSR  = sumaFSR / (float)N;
    const float periodo = INTERVALO_MUESTRA_MS * 1000.0f;
    const uint8_t convLMG = NUM_LMG * (TRAMA_OSCURA_HABILITADA ? 2 : 1);
    const float estimado =
        convLMG * (ADC_CONVERSION_US + ADC_OVERHEAD_I2C_US + LED_SETTLE_US)
        + NUM_FSR * FSR_MUESTRAS * FSR_US_POR_MUESTRA
        + 400.0f;

    Serial.printf("[AUTOTEST] ADC %s, trama oscura %s, %u ciclos\n",
                  ADC_MODELO == ADC_ADS1015 ? "ADS1015" : "ADS1115",
                  TRAMA_OSCURA_HABILITADA ? "SI" : "NO", N);
    Serial.printf("[AUTOTEST]   5 LMG (%u conversiones): %8.1f us\n",
                  convLMG, medLMG);
    Serial.printf("[AUTOTEST]   5 FSR (ADC interno)  : %8.1f us\n", medFSR);
    Serial.printf("[AUTOTEST]   ciclo completo medio : %8.1f us "
                  "(%.1f%% de %.0f us)\n", medio, 100.0f * medio / periodo, periodo);
    Serial.printf("[AUTOTEST]   ciclo completo peor  : %8lu us\n", peor);
    Serial.printf("[AUTOTEST]   estimado analitico   : %8.1f us\n", estimado);
    Serial.println("[AUTOTEST]   (sin rampa de servos: el ciclo real con rampa lo "
                   "da 'I', CICLO COMPLETO)");
    if (peor > periodo) {
        Serial.println("[AUTOTEST] ERROR: el ciclo NO cabe en el periodo de "
                       "muestreo. La ventana del modelo no mide 200 ms. Ver "
                       "la decision de ADC en config.h.");
    } else if (peor > 0.9f * periodo) {
        Serial.printf("[AUTOTEST] AVISO: solo %.0f us de margen en el peor "
                      "caso.\n", periodo - peor);
    } else {
        Serial.println("[AUTOTEST] OK: el ciclo cabe con margen.");
    }
}

// ======================== NUCLEO 0: INICIALIZACION ========================
// El I2C (Wire.begin) y todos sus dispositivos se inicializan DESDE el
// nucleo 0, para que el controlador y su interrupcion queden en el mismo
// nucleo que los usa.
void inicializarHardware() {
    // ========== 1. Inicializar I2C ==========
    Wire.begin(PIN_SDA, PIN_SCL);
    Wire.setClock(I2C_FREQ);
    Serial.println("[I2C] Bus inicializado a 400 kHz (nucleo 0)");

    Serial.printf("[FW] version=%s modulo=3 adc=%s adc_arq=2xADS gain=2 "
                  "trama_oscura=%d led_settle_us=%d fs_hz=%d nucleos=TR0/INF1\n",
                  FIRMWARE_VERSION,
                  ADC_MODELO == ADC_ADS1015 ? "ADS1015" : "ADS1115",
                  TRAMA_OSCURA_HABILITADA ? 1 : 0,
                  LED_SETTLE_US, 1000 / INTERVALO_MUESTRA_MS);

    // ========== 2. Inicializar los dos ADC de los LMG ==========
    Serial.print("[ADC] Inicializando 0x48 y 0x49... ");
    if (!adcLmg.begin()) {
        Serial.printf("ERROR - 0x48 %s, 0x49 %s. Revise el cableado I2C y "
                      "el pin ADDR (0x49 = ADDR a VDD).\n",
                      adcLmg.presente(0) ? "OK" : "FALTA",
                      adcLmg.presente(1) ? "OK" : "FALTA");
        while (1) delay(10);
    }
    Serial.println("OK");

    // ========== 2a. FSR en el ADC interno ==========
    feedback.begin();

    // ========== 2b. LED de los modulos LMG ==========
    // Antes que nada que lea el ADC: sin esto los LED quedan en el estado
    // de arranque de los GPIO y la primera lectura no es valida.
    if (!optica.begin()) {
        while (1) delay(10);
    }

    // ========== 3. Inicializar MPU6050 ==========
    Serial.print("[MPU6050] Inicializando... ");
    if (!imu.begin()) {
        Serial.println("ERROR - No detectado");
        while (1) delay(10);
    }
    Serial.println("OK");

    // ========== 3b. Autotest del ciclo de muestreo ==========
    autotestTemporal();

    // ========== 4. Inicializar PCA9685 ==========
    Serial.print("[PCA9685] Inicializando servos... ");
    if (!servos.begin()) {
        Serial.println("ERROR - No detectado");
        while (1) delay(10);
    }
    Serial.println("OK");

    // ========== 5. Calibracion ==========
    calibrador.registrarSenalHaptica(senalHaptica);
    Serial.print("[CALIB] Buscando calibracion guardada... ");
    if (calibrador.begin()) {
        Serial.println("encontrada");
    } else {
        Serial.println("no hay");
        Serial.println("[CALIB] AVISO: sin calibracion, la inferencia corre "
                       "sobre senal cruda. El modelo se entreno con datos "
                       "normalizados por sujeto, asi que la exactitud caera "
                       "de forma notable. Envie 'C' para calibrar.");
    }
}

// ======================== NUCLEO 0: COMANDOS ========================
void atenderComandos() {
    if (Serial.available() <= 0) return;
    char cmd = Serial.read();
    switch (cmd) {
        case 'G': sistemaActivo = true;
                  ventanaValidaDesde = intercambio.ultimaVentana() + 1;
                  Serial.println("[CMD] Control por gestos ACTIVADO");
                  break;
        case 'S': sistemaActivo = false;
                  gestoActual = GESTO_REST;
                  servos.ejecutarGesto(GESTO_REST);
                  ventana.reset();
                  ventanaValidaDesde = intercambio.ultimaVentana() + 1;
                  Serial.println("[CMD] Sistema DETENIDO - Servos en reposo");
                  break;
        case '1': gestoActual = GESTO_REST; servos.ejecutarGesto(GESTO_REST); break;
        case '2': gestoActual = GESTO_PINCH; servos.ejecutarGesto(GESTO_PINCH); break;
        case '3': gestoActual = GESTO_TRIPOD; servos.ejecutarGesto(GESTO_TRIPOD); break;
        case '4': gestoActual = GESTO_POWER; servos.ejecutarGesto(GESTO_POWER); break;
        case '5': gestoActual = GESTO_EXTENSION; servos.ejecutarGesto(GESTO_EXTENSION); break;
        case 'C': calibrador.iniciar(millis());
                  ventanaValidaDesde = intercambio.ultimaVentana() + 1;
                  break;
        case 'X': calibrador.borrar(); break;
        case 'A':
            // Bloqueante (~10 s): con el control detenido y la mano
            // en reposo, para que los servos no se muevan mientras se
            // mide el reposo.
            sistemaActivo = false;
            gestoActual = GESTO_REST;
            servos.ejecutarGesto(GESTO_REST);
            ventana.reset();
            ventanaValidaDesde = intercambio.ultimaVentana() + 1;
            optica.autocalibrar(AUTOCAL_VERIFICAR_GESTO_MAX);
            // Si la corriente cambio, el z-score guardado se calculo
            // con otra ganancia y ya no corresponde a la senal. Se
            // borra para que el aviso persistente obligue a recalibrar
            // en vez de normalizar con una escala equivocada.
            if (optica.cambioGanancia() && calibrador.tieneCalibracion()) {
                Serial.println("[OPTICA] La ganancia cambio: la "
                               "calibracion z-score queda obsoleta y se "
                               "borra. Envie 'C'.");
                calibrador.borrar();
            }
            Serial.println("[CMD] Envie 'G' para reactivar el control.");
            cicloInterrumpido = true;
            break;
        case 'T': autotestTemporal(); cicloInterrumpido = true; break;
        case 'I': calibrador.info(); optica.info(); reportarLatencias(); break;
    }
}

// ======================== NUCLEO 0: RESULTADO DE LA INFERENCIA ========================
// Lee el ultimo gesto que dejo el nucleo 1 y, si procede, actua. Es el
// unico sitio donde un gesto inferido llega a los servos.
void atenderResultado(unsigned long ahoraUs) {
    ResultadoInferencia r;
    if (!intercambio.leerResultado(r, nResultadoVisto)) return;
    ultimoResultado = r;

    const unsigned long latencia = ahoraUs - r.tVentanaUs;
    tInferenciaUs = r.tInferenciaUs;
    acumInferenciaUs += r.tInferenciaUs;
    acumLatenciaUs   += latencia;
    if (r.tInferenciaUs > peorInferenciaUs) peorInferenciaUs = r.tInferenciaUs;
    if (latencia > peorLatenciaUs) peorLatenciaUs = latencia;
    ciclosMedidos++;

    // Resultado de una ventana anterior a 'S', 'A' o una calibracion, o con
    // el control parado: no se aplica.
    if (!sistemaActivo || calibrador.capturando() || r.secVentana < ventanaValidaDesde) return;

    gestoActual = r.gesto;

    // --- Actuar sobre el gesto ---
    if (gestoActual != gestoAnterior || primeraInferencia) {
        primeraInferencia = false;
        // Al cambiar de gesto cambian los dedos que cierran: las
        // lecturas anteriores quedan rancias y no deben frenar
        // un dedo que acaba de empezar a moverse.
        feedback.reiniciar();

        Serial.printf("[INFERENCIA] Gesto: %s (clase %d)\n",
                      ControlServos::gestos[gestoActual].nombre,
                      gestoActual);

        // Solo fija el objetivo: el movimiento lo hace la rampa, en este
        // mismo nucleo y en cada ciclo.
        servos.ejecutarGesto(gestoActual);
        gestoAnterior = gestoActual;
    }

    // ========== LAZO CERRADO: solo traza ==========
    // Ni la lectura ni la frenada ocurren aqui: viven en el ciclo de 10 ms.
    const uint8_t activosInf = FeedbackFSR::dedosActivos(gestoActual);
    if (activosInf) {
        static uint8_t debugCounter = 0;
        if (++debugCounter >= 25) {     // ~2 Hz con un resultado cada 20 ms
            debugCounter = 0;
            Serial.printf("[FSR] P:%.0f I:%.0f M:%.0f A:%.0f Mn:%.0f "
                          "(mV, activos=0x%02X)\n",
                          feedback.getUltimoValor(0),
                          feedback.getUltimoValor(1),
                          feedback.getUltimoValor(2),
                          feedback.getUltimoValor(3),
                          feedback.getUltimoValor(4),
                          activosInf);
            for (uint8_t d = 0; d < NUM_FSR; d++) {
                if ((activosInf & (1 << d)) && !servos.enMovimiento(d)) {
                    Serial.printf("[FSR] Dedo %d detenido en %d grados\n",
                                  d, servos.getAnguloActual(d));
                }
            }
        }
    }
}

// ======================== NUCLEO 0: CICLO DE 10 ms ========================
void cicloTiempoReal() {
    const unsigned long ahora = millis();

    // ========== ATENDER COMANDOS SERIAL ==========
    atenderComandos();

    // Aviso persistente si la calibracion no esta confirmada. Va antes
    // del return de sistemaActivo a proposito: el usuario tiene que
    // enterarse aunque el control por gestos este detenido.
    calibrador.atenderAvisos(ahora);

    // El resultado se lee aunque el control este parado, para no aplicar
    // despues uno viejo.
    atenderResultado(micros());

    if (!sistemaActivo) return;

    const unsigned long tMuestreo0 = micros();

    // --- Leer 5 LMG: un LED a la vez, con trama oscura ---
    // Identico a Modulo1 (optica_lmg.cpp es el mismo archivo): el
    // modelo tiene que ver aqui la misma senal con que se entreno.
    optica.leerTodos(valoresLMG);

    // --- Leer MPU6050 (solo acelerometro: el modelo no usa giro) ---
    imu.leerAcelerometro(ax, ay, az);

    // --- Empaquetar muestra: x(t) = [v1..v5, ax, ay, az] ---
    // 8 canales, el mismo orden y la misma forma con la que se
    // entrena en el Modulo 2. Si este orden cambiara sin cambiar el
    // preprocesamiento, no habria error de compilacion: el modelo
    // recibiria canales permutados y devolveria basura.
    for (uint8_t i = 0; i < NUM_LMG; i++) {
        muestra[i] = valoresLMG[i];
    }
    muestra[NUM_LMG + 0] = ax;
    muestra[NUM_LMG + 1] = ay;
    muestra[NUM_LMG + 2] = az;

    tMuestreoUs = micros() - tMuestreo0;
    acumMuestreoUs += tMuestreoUs;

    // ===== RAMPA DE SERVOS =====
    // En el ciclo de 10 ms para que su periodo real sea RAMPA_PERIODO_MS
    // y no dependa de la inferencia, que corre en el otro nucleo. Solo
    // escribe al PCA9685 los servos cuyo angulo cambio, asi que mantener
    // una postura no cuesta nada.
    servos.actualizarRampa(ahora);

    // ===== LOS 5 FSR, EN CADA CICLO =====
    // Se leen los cinco aunque el gesto no cierre todos los dedos: cuesta
    // ~0.5 ms y mantiene constante la duracion del ciclo.
    const unsigned long tf0 = micros();
    feedback.leerTodos(tf0);
    tFSRUs = micros() - tf0;
    acumFSRUs += tFSRUs;
    lecturasFSR++;

    // FRENAR AQUI MISMO, en el ciclo en que se lee el sensor. Solo se
    // frenan los dedos que cierran en el gesto actual.
    const uint8_t activos = FeedbackFSR::dedosActivos(gestoActual);
    if (activos) {
        const uint8_t frenar = feedback.verificarUmbrales(activos);
        if (frenar & 0x01) servos.frenarServo(SERVO_PULGAR);
        if (frenar & 0x02) servos.frenarServo(SERVO_INDICE);
        if (frenar & 0x04) servos.frenarServo(SERVO_MEDIO);
        if (frenar & 0x08) servos.frenarServo(SERVO_ANULAR);
        if (frenar & 0x10) servos.frenarServo(SERVO_MENIQUE);
    }

    // ========== MODO CALIBRACION ==========
    // Mientras se calibra, las muestras van al calibrador y NO se publican
    // ventanas: los servos no deben moverse mientras el usuario intenta
    // quedarse quieto.
    if (calibrador.capturando()) {
        calibrador.acumular(muestra, ahora);
        ventanaValidaDesde = intercambio.ultimaVentana() + 1;
        return;
    }

    // --- Insertar en buffer circular ---
    ventana.addSample(muestra);
    contadorMuestras++;

    // ========== PUBLICAR VENTANA PARA EL NUCLEO 1 (cada STRIDE) ==========
    if (contadorMuestras >= STRIDE && ventana.isFull()) {
        contadorMuestras = 0;

        // Extraer ventana completa (20 muestras en orden cronologico)
        ventana.getWindow(ventanaCompleta);

        // --- Normalizar con la calibracion del usuario ---
        // Aqui, en el nucleo 0, que es el unico que toca el calibrador:
        // el nucleo 1 recibe la ventana lista. Si no hay calibracion, no
        // hace nada.
        calibrador.normalizar(ventanaCompleta);

        // Copia atomica y aviso al nucleo 1
        intercambio.publicarVentana(ventanaCompleta, micros());
        xTaskNotifyGive(tareaInferencia);
    }
}

// ======================== NUCLEO 0: TAREA DE TIEMPO REAL ========================
void tareaTiempoRealFn(void *) {
    inicializarHardware();
    xSemaphoreGive(semHardwareListo);
    xSemaphoreTake(semModeloListo, portMAX_DELAY);   // espera a TFLite (nucleo 1)
    sistemaActivo = true;

    const TickType_t periodo = pdMS_TO_TICKS(INTERVALO_MUESTRA_MS);
    TickType_t ultimo = xTaskGetTickCount();
    for (;;) {
        cicloInterrumpido = false;
        const unsigned long t0 = micros();
        cicloTiempoReal();
        const unsigned long dt = micros() - t0;

        if (cicloInterrumpido) {
            // Un comando bloqueante: no se mide y se retoma el periodo desde
            // ahora, en vez de encadenar ciclos atrasados.
            ultimo = xTaskGetTickCount();
            continue;
        }
        if (sistemaActivo) {
            ciclosTR++;
            acumCicloUs += dt;
            if (dt > peorCicloUs) peorCicloUs = dt;
        }
        // xTaskDelayUntil devuelve pdFALSE si el plazo ya habia pasado: el
        // ciclo no cupo en 10 ms. Se cuenta y se resincroniza.
        if (xTaskDelayUntil(&ultimo, periodo) == pdFALSE) {
            if (sistemaActivo) ciclosExcedidos++;
            ultimo = xTaskGetTickCount();
        }
    }
}

// ======================== SETUP (nucleo 1) ========================
void setup() {
    // Bufer de transmision de 1 KB: sin el, Serial escribe directo en la
    // FIFO de 128 B de la UART y, si esta llena, BLOQUEA a 87 us por byte a
    // 115200. La traza de FSR (~235 B) podia retener asi ~9 ms el ciclo de
    // 10 ms del nucleo 0. Con el bufer, imprimir no espera.
    Serial.setTxBufferSize(1024);
    Serial.begin(115200);
    delay(100);
    Serial.println("\n\n============================================");
    Serial.println("Protesis Transradial - Inferencia y Control");
    Serial.println("============================================");

    // setup() y loop() corren en la misma tarea de Arduino, en el nucleo 1:
    // es la tarea a la que el nucleo 0 avisa cuando hay una ventana nueva.
    tareaInferencia  = xTaskGetCurrentTaskHandle();
    semHardwareListo = xSemaphoreCreateBinary();
    semModeloListo   = xSemaphoreCreateBinary();

    // ========== 1-4. Hardware, desde el nucleo 0 ==========
    xTaskCreatePinnedToCore(tareaTiempoRealFn, "tiempo_real",
                            PILA_TIEMPO_REAL_BYTES, nullptr,
                            PRIORIDAD_TIEMPO_REAL, &tareaTiempoReal,
                            NUCLEO_TIEMPO_REAL);
    xSemaphoreTake(semHardwareListo, portMAX_DELAY);

    // ========== 5. Inicializar TFLite Micro (nucleo 1) ==========
    Serial.print("[TFLITE] Cargando modelo... ");
    if (!tflite.begin()) {
        Serial.println("ERROR - Fallo al cargar modelo");
        while (1) delay(10);
    }
    Serial.println("OK");
    tflite.info();

    // ========== 6. Reportar configuracion ==========
    Serial.printf("[CONFIG] Ventana: %d ms (%d muestras)\n",
                  TAMANO_VENTANA * INTERVALO_MUESTRA_MS, TAMANO_VENTANA);
    Serial.printf("[CONFIG] Stride: %d ms (%d muestras)\n",
                  STRIDE * INTERVALO_MUESTRA_MS, STRIDE);
    Serial.printf("[CONFIG] Ventana publicada cada %d ms; se infiere la mas "
                  "reciente\n", INTERVALO_INFERENCIA_MS);
    Serial.printf("[CONFIG] Nucleo %d: tiempo real + I2C | nucleo %d: inferencia\n",
                  NUCLEO_TIEMPO_REAL, xPortGetCoreID());
    Serial.println("[READY] Sistema listo. Envie:\n"
                   "  'G' → Activar control por gestos\n"
                   "  'S' → Detener (servos a reposo)\n"
                   "  'M' → Modo manual: 1=Rest 2=Pinch 3=Tripod 4=Power 5=Ext\n"
                   "  'C' → Calibrar (15 s quieto, sin mover el brazo)\n"
                   "  'X' → Borrar la calibracion guardada\n"
                   "  'A' → Autocalibrar la corriente de los LED\n"
                   "  'T' → Autotest del ciclo de muestreo\n"
                   "  'I' → Info de calibracion y desglose de latencias\n");

    xSemaphoreGive(semModeloListo);   // el nucleo 0 empieza a muestrear
}

// ======================== LOOP (nucleo 1): SOLO INFERENCIA ========================
// Calculo puro: espera una ventana del nucleo 0, la copia, clasifica y
// deja el gesto. No toca ningun periferico ni Serial.
void loop() {
    if (ulTaskNotifyTake(pdTRUE, portMAX_DELAY) == 0) return;

    uint32_t tVentanaUs = 0;
    const uint32_t sec = intercambio.copiarVentana(ventanaInferencia, tVentanaUs);

    const uint32_t t0 = micros();
    const uint8_t gesto = tflite.predecir(ventanaInferencia);
    const uint32_t dt = micros() - t0;

    intercambio.publicarResultado(gesto, sec, tVentanaUs, dt, tflite.ultimaOk());
}
