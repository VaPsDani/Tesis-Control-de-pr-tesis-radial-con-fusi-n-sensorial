/*
 * inferencia_control.ino - Modulo 3: Inferencia en Tiempo Real y Control
 * =====================================================================
 * Protesis transradial - Fusion sensorial y Deep Learning (TinyML)
 *
 * FLUJO PRINCIPAL (cada 20 ms = 1 stride):
 *
 *   [1] Leer sensores predictivos (LMG + IMU) → 1 muestra cada 10 ms
 *   [2] Acumular en buffer circular (ventana de 200 ms = 20 muestras)
 *   [3] Cada 20 ms (2 muestras):
 *       a. Extraer ventana completa del buffer
 *       b. Ejecutar inferencia TFLite Micro → clase de gesto
 *       c. Si el gesto cambio: enviar PWM al PCA9685
 *   [4] LAZO CERRADO (simultaneo al cierre):
 *       a. Leer FSR de los dedos via MUX + ADS1115
 *       b. Si FSR > umbral: DETENER servo especifico
 *       c. Mantener presion constante
 *
 * MAQUINA DE ESTADOS:
 *   Los gestos se ejecutan como maquina de estados:
 *     - Estado REPOSO: modelo en idle, servos abiertos
 *     - Estado TRANSICION: nuevo gesto detectado, comenzar cierre
 *     - Estado AGARRE: gesto mantenido, monitorear FSR continuamente
 *     - Estado LIBERACION: gesto termino, abrir servos
 *
 * TIMING CRITICO:
 *   - Muestreo: cada 10 ms (100 Hz)
 *   - Inferencia: cada 20 ms (50 Hz)
 *   - Lectura FSR: entre inferencias
 *   - Control servos: bajo demanda (cuando cambia gesto o FSR dispara)
 *   - Sin delays bloqueantes: todo con millis()
 */

#include <Wire.h>
#include "config.h"
#include "mux_ads1115.h"
#include "sensor_imu.h"
#include "sliding_window.h"
#include "inferencia.h"
#include "control_servos.h"
#include "feedback_fsr.h"
#include "calibracion.h"

// ======================== INSTANCIAS GLOBALES ========================
MUX_ADS1115     muxAds;
SensorIMU       imu;
SlidingWindow   ventana;
MotorInferencia tflite;
ControlServos   servos;
FeedbackFSR     feedback;
Calibrador      calibrador;

// ======================== INSTRUMENTACION DE LATENCIA ========================
// Presupuesto por ciclo de inferencia (cada 20 ms). Se mide en vivo en
// vez de estimarse, porque el coste real depende del modelo cuantizado.
unsigned long tMuestreoUs   = 0;   // 5 LMG + IMU
unsigned long tInferenciaUs = 0;   // Invoke() de TFLite
uint32_t      ciclosMedidos = 0;
unsigned long acumMuestreoUs = 0;
unsigned long acumInferenciaUs = 0;

// ======================== VARIABLES DE ESTADO ========================
uint8_t gestoActual     = GESTO_REST;
uint8_t gestoAnterior   = GESTO_REST;
bool    sistemaActivo   = false;
bool    primeraInferencia = true;

// ======================== VARIABLES DE TIEMPO ========================
unsigned long tUltimoMuestreo    = 0;
unsigned long tUltimaInferencia  = 0;

// Contador de muestras entre inferencias (cada STRIDE muestras)
uint8_t contadorMuestras = 0;

// ======================== BUFFERS DE DATOS ========================
float muestra[NUM_FEATURES];                    // 1 muestra actual
float ventanaCompleta[TAMANO_VENTANA][NUM_FEATURES];  // ventana para inferencia
float valoresLMG[NUM_LMG];
float ax, ay, az;               // acelerometro: los 3 canales de IMU del modelo

// ======================== ESCANEO ROTATIVO DE FSR ========================
// Un solo FSR por ciclo, rotando entre los dedos que cierran en el gesto
// actual. El ciclo pasa de 11 canales de ADC a 6, que es lo que hace que
// quepa en los 10 ms.
uint8_t       fsrRotacion   = 0;    // indice del proximo dedo a leer
unsigned long tFSRUs        = 0;    // coste de la lectura del FSR del ciclo
unsigned long acumFSRUs     = 0;
uint32_t      lecturasFSR   = 0;

// ======================== SENAL HAPTICA ========================
// Pulso breve con los servos, contable por el usuario. Es el canal que
// funciona con la protesis puesta y sin consola, que es la situacion en
// la que ocurre un fallo de calibracion. Se pasa al calibrador como
// callback para no acoplarlo con el control de servos.
//
// Se ejecuta solo fuera del bucle de inferencia, asi que los ~600 ms del
// patron mas largo no comprometen el presupuesto de 20 ms por ciclo.
void senalHaptica(uint8_t repeticiones) {
    const uint8_t gestoPrevio = gestoActual;
    for (uint8_t i = 0; i < repeticiones; i++) {
        servos.ejecutarGesto(GESTO_POWER);      // flexion parcial
        delay(120);
        servos.ejecutarGesto(GESTO_REST);       // vuelta a reposo
        delay(120);
    }
    servos.ejecutarGesto(gestoPrevio);
}

// ======================== INSTRUMENTACION ========================
// Desglose del presupuesto por ciclo de inferencia. El coste de la
// normalizacion se mide igual que el resto, para que quede en la
// instrumentacion de latencia y no como una estimacion aparte.
void reportarLatencias() {
    Serial.println("[LATENCIA] Desglose por ciclo de inferencia (20 ms):");

    if (ciclosMedidos == 0) {
        Serial.println("[LATENCIA] Aun no hay ciclos medidos.");
        return;
    }

    const float medMuestreo   = acumMuestreoUs   / (float)ciclosMedidos;
    const float medInferencia = acumInferenciaUs / (float)ciclosMedidos;

    const uint32_t nNorm = calibrador.normalizacionesRealizadas();
    const float medNorm  = nNorm
        ? calibrador.normalizacionAcumuladaUs() / (float)nNorm
        : 0.0f;

    const float medFSR = lecturasFSR
        ? acumFSRUs / (float)lecturasFSR : 0.0f;
    const float total = medMuestreo + medNorm + medInferencia;

    Serial.printf("[LATENCIA]   Muestreo (5 LMG + IMU) : %8.1f us  %5.1f%%\n",
                  medMuestreo, 100.0f * medMuestreo / total);
    Serial.printf("[LATENCIA]   Normalizacion          : %8.1f us  %5.1f%%\n",
                  medNorm, 100.0f * medNorm / total);
    Serial.printf("[LATENCIA]   Inferencia TFLite      : %8.1f us  %5.1f%%\n",
                  medInferencia, 100.0f * medInferencia / total);
    Serial.printf("[LATENCIA]   TOTAL                  : %8.1f us "
                  "(%.1f%% de los 20000 us disponibles)\n",
                  total, 100.0f * total / 20000.0f);
    Serial.printf("[LATENCIA]   Ciclos medidos: %lu   Normalizaciones: %lu\n",
                  (unsigned long)ciclosMedidos, (unsigned long)nNorm);

    // ===== Presupuesto del ciclo de 10 ms =====
    // Este es EL numero que decide si el escaneo desacoplado funciona.
    // El ciclo de muestreo debe caber en INTERVALO_MUESTRA_MS; si no,
    // el sistema no corre a 100 Hz y la ventana del modelo deja de ser
    // de 200 ms, por mucho que el ciclo de inferencia vaya holgado.
    Serial.println("[LATENCIA] Presupuesto del ciclo de muestreo (10 ms):");
    Serial.printf("[LATENCIA]   5 LMG + IMU            : %8.1f us\n",
                  medMuestreo);
    Serial.printf("[LATENCIA]   1 FSR (rotativo)       : %8.1f us "
                  "(%lu lecturas)\n", medFSR, (unsigned long)lecturasFSR);
    const float ciclo = medMuestreo + medFSR;
    Serial.printf("[LATENCIA]   TOTAL CICLO 10 ms      : %8.1f us "
                  "(%.1f%% de 10000 us)\n", ciclo, 100.0f * ciclo / 10000.0f);
    if (ciclo > 10000.0f) {
        Serial.println("[LATENCIA] ERROR: el ciclo NO cabe en 10 ms. El "
                       "muestreo no corre a 100 Hz y la ventana del modelo "
                       "no mide 200 ms.");
    } else if (ciclo > 9000.0f) {
        Serial.printf("[LATENCIA] AVISO: solo %.0f us de margen. Considere "
                      "leer un FSR cada dos ciclos.\n", 10000.0f - ciclo);
    }

    // Tasa efectiva real de cada FSR, medida y no supuesta.
    Serial.println("[LATENCIA] Tasa efectiva por FSR:");
    feedback.info();

    // La normalizacion son TAMANO_VENTANA * NUM_FEATURES = 160 restas y
    // multiplicaciones, con la division ya resuelta al calibrar. A
    // 240 MHz con FPU deberia quedar en el orden de 1-2 us, o sea
    // despreciable frente a la inferencia. Si la medida se aleja mucho
    // de eso, conviene revisar si el compilador esta emitiendo
    // operaciones en software.
    if (nNorm > 0 && medNorm > 50.0f) {
        Serial.printf("[LATENCIA] AVISO: la normalizacion tarda %.1f us, muy "
                      "por encima de los ~2 us esperados para 160 "
                      "multiplicaciones con FPU.\n", medNorm);
    }
}

// ======================== SETUP ========================
void setup() {
    Serial.begin(115200);
    delay(100);
    Serial.println("\n\n============================================");
    Serial.println("Protesis Transradial - Inferencia y Control");
    Serial.println("============================================");

    // ========== 1. Inicializar I2C ==========
    Wire.begin(PIN_SDA, PIN_SCL);
    Wire.setClock(I2C_FREQ);
    Serial.println("[I2C] Bus inicializado a 400 kHz");

    // ========== 2. Inicializar MUX + ADS1115 ==========
    Serial.print("[ADS1115] Inicializando... ");
    if (!muxAds.begin()) {
        Serial.println("ERROR - No detectado");
        while (1) delay(10);
    }
    Serial.println("OK");

    // ========== 3. Inicializar MPU6050 ==========
    Serial.print("[MPU6050] Inicializando... ");
    if (!imu.begin()) {
        Serial.println("ERROR - No detectado");
        while (1) delay(10);
    }
    Serial.println("OK");

    // ========== 4. Inicializar PCA9685 ==========
    Serial.print("[PCA9685] Inicializando servos... ");
    if (!servos.begin()) {
        Serial.println("ERROR - No detectado");
        while (1) delay(10);
    }
    Serial.println("OK");

    // ========== 5. Inicializar TFLite Micro ==========
    Serial.print("[TFLITE] Cargando modelo... ");
    if (!tflite.begin()) {
        Serial.println("ERROR - Fallo al cargar modelo");
        while (1) delay(10);
    }
    Serial.println("OK");
    tflite.info();

    // ========== 5b. Calibracion ==========
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

    // ========== 6. Reportar configuracion ==========
    Serial.printf("[CONFIG] Ventana: %d ms (%d muestras)\n",
                  TAMANO_VENTANA * INTERVALO_MUESTRA_MS, TAMANO_VENTANA);
    Serial.printf("[CONFIG] Stride: %d ms (%d muestras)\n",
                  STRIDE * INTERVALO_MUESTRA_MS, STRIDE);
    Serial.printf("[CONFIG] Inferencia: cada %d ms (%d Hz)\n",
                  INTERVALO_INFERENCIA_MS, 1000 / INTERVALO_INFERENCIA_MS);
    Serial.println("[READY] Sistema listo. Envie:\n"
                   "  'G' → Activar control por gestos\n"
                   "  'S' → Detener (servos a reposo)\n"
                   "  'M' → Modo manual: 1=Rest 2=Pinch 3=Tripod 4=Power 5=Ext\n"
                   "  'C' → Calibrar (15 s quieto, sin mover el brazo)\n"
                   "  'X' → Borrar la calibracion guardada\n"
                   "  'I' → Info de calibracion y desglose de latencias\n");

    sistemaActivo = true;
}

// ======================== LOOP PRINCIPAL ========================
void loop() {
    unsigned long ahora = millis();

    // ========== ATENDER COMANDOS SERIAL ==========
    if (Serial.available() > 0) {
        char cmd = Serial.read();
        switch (cmd) {
            case 'G': sistemaActivo = true;
                      Serial.println("[CMD] Control por gestos ACTIVADO");
                      break;
            case 'S': sistemaActivo = false;
                      gestoActual = GESTO_REST;
                      servos.ejecutarGesto(GESTO_REST);
                      ventana.reset();
                      Serial.println("[CMD] Sistema DETENIDO - Servos en reposo");
                      break;
            case '1': gestoActual = GESTO_REST; servos.ejecutarGesto(GESTO_REST); break;
            case '2': gestoActual = GESTO_PINCH; servos.ejecutarGesto(GESTO_PINCH); break;
            case '3': gestoActual = GESTO_TRIPOD; servos.ejecutarGesto(GESTO_TRIPOD); break;
            case '4': gestoActual = GESTO_POWER; servos.ejecutarGesto(GESTO_POWER); break;
            case '5': gestoActual = GESTO_EXTENSION; servos.ejecutarGesto(GESTO_EXTENSION); break;
            case 'C': calibrador.iniciar(millis()); break;
            case 'X': calibrador.borrar(); break;
            case 'I': calibrador.info(); reportarLatencias(); break;
        }
    }

    // Aviso persistente si la calibracion no esta confirmada. Va antes
    // del return de sistemaActivo a proposito: el usuario tiene que
    // enterarse aunque el control por gestos este detenido.
    calibrador.atenderAvisos(ahora);

    if (!sistemaActivo) return;

    // ========== BUCLE DE MUESTREO (100 Hz - cada 10 ms) ==========
    if (ahora - tUltimoMuestreo >= INTERVALO_MUESTRA_MS) {
        tUltimoMuestreo = ahora;
        const unsigned long tMuestreo0 = micros();

        // --- Leer 5 LMG via MUX + ADS1115 ---
        valoresLMG[0] = muxAds.leerCanal(CH_LMG_1);
        valoresLMG[1] = muxAds.leerCanal(CH_LMG_2);
        valoresLMG[2] = muxAds.leerCanal(CH_LMG_3);
        valoresLMG[3] = muxAds.leerCanal(CH_LMG_4);
        valoresLMG[4] = muxAds.leerCanal(CH_LMG_5);

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

        // ===== RAMPA DE SERVOS =====
        // Va en el bucle de 10 ms para que su periodo real sea
        // RAMPA_PERIODO_MS y no dependa de cuando toque inferir. Solo
        // escribe al PCA9685 los servos cuyo angulo cambio, asi que
        // mantener una postura no cuesta nada.
        servos.actualizarRampa(ahora);

        // ===== UN FSR POR CICLO, ROTANDO =====
        // Va aqui, en el bucle de 10 ms, y no en el de inferencia: asi
        // la tasa efectiva por sensor es 100 Hz / n_dedos_activos y no
        // depende de cuando toque inferir. FSR_CADA_N_CICLOS a 2 activa
        // el plan B si el presupuesto real no da.
        static uint8_t divisorFSR = 0;
        const bool tocaFSR = (++divisorFSR >= FSR_CADA_N_CICLOS);
        if (tocaFSR) divisorFSR = 0;

        const uint8_t activos = FeedbackFSR::dedosActivos(gestoActual);
        if (activos && tocaFSR) {
            // Avanzar hasta el proximo dedo que este cerrando.
            uint8_t intentos = 0;
            while (intentos < NUM_FSR &&
                   !(activos & (1 << fsrRotacion))) {
                fsrRotacion = (fsrRotacion + 1) % NUM_FSR;
                intentos++;
            }
            if (activos & (1 << fsrRotacion)) {
                const unsigned long tf0 = micros();
                const float mv = muxAds.leerCanal(
                    FeedbackFSR::canalDe(fsrRotacion));
                tFSRUs = micros() - tf0;
                acumFSRUs += tFSRUs;
                lecturasFSR++;
                feedback.actualizar(fsrRotacion, mv, micros());
                fsrRotacion = (fsrRotacion + 1) % NUM_FSR;

                // FRENAR AQUI MISMO, no en el bucle de inferencia.
                // El lazo de fuerza no tiene por que esperar a una
                // inferencia: hacerlo anadia hasta 20 ms de latencia
                // gratis, que a 180 grados/s son 3.6 grados mas de
                // sobrecierre. Asi la latencia total es solo el periodo
                // de escaneo del FSR.
                const uint8_t frenar = feedback.verificarUmbrales(activos);
                if (frenar & 0x01) servos.frenarServo(SERVO_PULGAR);
                if (frenar & 0x02) servos.frenarServo(SERVO_INDICE);
                if (frenar & 0x04) servos.frenarServo(SERVO_MEDIO);
                if (frenar & 0x08) servos.frenarServo(SERVO_ANULAR);
                if (frenar & 0x10) servos.frenarServo(SERVO_MENIQUE);
            }
        }

        // ========== MODO CALIBRACION ==========
        // Mientras se calibra, las muestras van al calibrador y NO se
        // infiere: los servos no deben moverse mientras el usuario
        // intenta quedarse quieto.
        if (calibrador.capturando()) {
            calibrador.acumular(muestra, ahora);
            return;
        }

        // --- Insertar en buffer circular ---
        ventana.addSample(muestra);
        contadorMuestras++;

        // ========== BUCLE DE INFERENCIA (50 Hz - cada 20 ms) ==========
        if (contadorMuestras >= STRIDE && ventana.isFull()) {
            contadorMuestras = 0;

            // Extraer ventana completa (20 muestras en orden cronologico)
            ventana.getWindow(ventanaCompleta);

            // --- Normalizar con la calibracion del usuario ---
            // In situ, sobre la copia extraida del buffer; el buffer
            // circular conserva la senal cruda para la siguiente
            // ventana. Si no hay calibracion, no hace nada.
            calibrador.normalizar(ventanaCompleta);

            // --- Ejecutar inferencia ---
            const unsigned long tInf0 = micros();
            uint8_t gestoPredicho = tflite.predecir(ventanaCompleta);
            tInferenciaUs = micros() - tInf0;

            acumMuestreoUs   += tMuestreoUs;
            acumInferenciaUs += tInferenciaUs;
            ciclosMedidos++;

            gestoActual = gestoPredicho;

            // --- Actuar sobre el gesto ---
            if (gestoActual != gestoAnterior || primeraInferencia) {
                primeraInferencia = false;
                // Al cambiar de gesto cambian los dedos que cierran: las
                // lecturas anteriores quedan rancias y no deben frenar
                // un dedo que acaba de empezar a moverse.
                feedback.reiniciar();
                fsrRotacion = 0;

                Serial.printf("[INFERENCIA] Gesto: %s (clase %d)\n",
                              ControlServos::gestos[gestoActual].nombre,
                              gestoActual);

                servos.ejecutarGesto(gestoActual);
                gestoAnterior = gestoActual;
            }

            // ========== LAZO CERRADO: solo traza ==========
            // Ni la lectura ni la frenada ocurren aqui. Ambas viven en
            // el bucle de 10 ms, junto al escaneo del FSR: hacer que el
            // lazo de fuerza esperase a una inferencia anadia hasta
            // 20 ms de latencia, que a 180 grados/s son 3.6 grados mas
            // de sobrecierre por nada.
            const uint8_t activosInf = FeedbackFSR::dedosActivos(gestoActual);
            if (activosInf) {
                static uint8_t debugCounter = 0;
                if (++debugCounter >= 25) {     // ~2 Hz
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
    }
}
