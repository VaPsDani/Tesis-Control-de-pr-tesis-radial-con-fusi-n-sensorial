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

// ======================== INSTANCIAS GLOBALES ========================
MUX_ADS1115     muxAds;
SensorIMU       imu;
SlidingWindow   ventana;
MotorInferencia tflite;
ControlServos   servos;
FeedbackFSR     feedback;

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
float valoresFSR[6];

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
                   "  'M' → Modo manual: 1=Rest 2=Pinch 3=Tripod 4=Power 5=Ext\n");

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
        }
    }

    if (!sistemaActivo) return;

    // ========== BUCLE DE MUESTREO (100 Hz - cada 10 ms) ==========
    if (ahora - tUltimoMuestreo >= INTERVALO_MUESTRA_MS) {
        tUltimoMuestreo = ahora;

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

        // --- Insertar en buffer circular ---
        ventana.addSample(muestra);
        contadorMuestras++;

        // ========== BUCLE DE INFERENCIA (50 Hz - cada 20 ms) ==========
        if (contadorMuestras >= STRIDE && ventana.isFull()) {
            contadorMuestras = 0;

            // Extraer ventana completa (20 muestras en orden cronologico)
            ventana.getWindow(ventanaCompleta);

            // --- Ejecutar inferencia ---
            uint8_t gestoPredicho = tflite.predecir(ventanaCompleta);
            gestoActual = gestoPredicho;

            // --- Actuar sobre el gesto ---
            if (gestoActual != gestoAnterior || primeraInferencia) {
                primeraInferencia = false;

                Serial.printf("[INFERENCIA] Gesto: %s (clase %d)\n",
                              ControlServos::gestos[gestoActual].nombre,
                              gestoActual);

                servos.ejecutarGesto(gestoActual);
                gestoAnterior = gestoActual;
            }

            // ========== LAZO CERRADO: LEER FSR ==========
            // Solo cuando estamos en un gesto de agarre (no Rest, no Extension)
            if (gestoActual == GESTO_PINCH ||
                gestoActual == GESTO_TRIPOD ||
                gestoActual == GESTO_POWER) {

                // Leer los 6 FSR a traves del MUX
                valoresFSR[0] = muxAds.leerCanal(CH_FSR_PULGAR);
                valoresFSR[1] = muxAds.leerCanal(CH_FSR_INDICE);
                valoresFSR[2] = muxAds.leerCanal(CH_FSR_MEDIO);
                valoresFSR[3] = muxAds.leerCanal(CH_FSR_ANULAR);
                valoresFSR[4] = muxAds.leerCanal(CH_FSR_MENIQUE);
                valoresFSR[5] = muxAds.leerCanal(CH_FSR_PALMA);

                feedback.leerFSR(valoresFSR);

                // Verificar umbrales
                uint8_t frenar = feedback.verificarUmbrales(valoresFSR);

                // Frenar servos segun bitmap (bits 0-4 corresponden a servos 0-4)
                if (frenar & 0x01) servos.frenarServo(SERVO_PULGAR);
                if (frenar & 0x02) servos.frenarServo(SERVO_INDICE);
                if (frenar & 0x04) servos.frenarServo(SERVO_MEDIO);
                if (frenar & 0x08) servos.frenarServo(SERVO_ANULAR);
                if (frenar & 0x10) servos.frenarServo(SERVO_MENIQUE);

                // Debug FSR (cada 10 ciclos para no saturar Serial)
                static uint8_t debugCounter = 0;
                if (++debugCounter >= 10) {
                    debugCounter = 0;
                    Serial.printf("[FSR] P:%.0f I:%.0f M:%.0f A:%.0f Mn:%.0f Pl:%.0f (mV)\n",
                                  valoresFSR[0], valoresFSR[1], valoresFSR[2],
                                  valoresFSR[3], valoresFSR[4], valoresFSR[5]);
                    if (frenar) {
                        Serial.printf("[FSR] Frenando servos: 0x%02X\n", frenar);
                    }
                }
            }
        }
    }
}
