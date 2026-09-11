/*
 * adquisicion_datos.ino - Modulo 1: Adquisicion de Datos
 * ======================================================
 * Protesis transradial - Fusion sensorial y Deep Learning
 *
 * OBJETIVO:
 *   Adquirir senales de 5 fotodiodos LMG (OPT101 via MUX+ADC) y los
 *   6 ejes crudos del MPU6050 para construir el dataset de entrenamiento.
 *
 * LECTURA OPTICA (Tarea 3, ver optica_lmg.h):
 *   Un LED a la vez: solo se enciende el del canal que se lee, para que
 *   la luz de un modulo no llegue al fotodiodo del vecino. Con el
 *   ADS1015, ademas, trama oscura: v = L - D. optica_lmg.cpp es el MISMO
 *   archivo que en Modulo3.
 *
 * VENTANA DESLIZANTE (lado PC):
 *   Los datos se envian en crudo por Serial a 100 Hz.
 *   El script en Python (Modulo 2) aplicara:
 *     - Ventana de 200 ms → 20 muestras a 100 Hz
 *     - Stride de 20 ms → 2 muestras de avance
 *
 * PROTOCOLO SERIAL — 12 campos por linea:
 *   timestamp_ms,v1,v2,v3,v4,v5,ax,ay,az,gx,gy,gz
 *
 *   El timestamp es el millis() del ESP32, no la hora de la PC. Es el
 *   reloj bueno para el espaciado entre muestras: el cristal deriva
 *   10-40 ppm (18-36 ms en 15 min) mientras que el sellado en la PC
 *   sufre el latency timer del conversor USB-serie (16 ms por defecto en
 *   CP210x/CH340) mas el jitter del scheduler, sin cota superior.
 *
 * ESQUEMA COMPLETO DEL CSV — lo escribe el script de captura del
 * Modulo 2, no este firmware:
 *
 *   subject_id, repetition_id, timestamp_ms, v1..v5,
 *   ax, ay, az, gx, gy, gz, label, bloque_tipo, en_margen, es_calibracion
 *
 *   De esas, el firmware aporta las 12 de arriba. Las demas las anade la
 *   PC, que es quien conoce el protocolo de la sesion. La columna fase
 *   se calcula despues, sobre el CSV cerrado (Modulo2 fases.py).
 *
 * QUE SE GUARDA Y QUE CONSUME EL MODELO:
 *   El modelo usa 8 canales: v1..v5 + ax, ay, az. El giroscopio se
 *   guarda igualmente porque sus bytes ya viajan en la misma lectura
 *   I2C de 14 bytes, asi que almacenarlo no cuesta tiempo de bus, y
 *   recuperarlo despues obligaria a repetir toda la campana con los 10
 *   voluntarios. El descarte de gx, gy, gz ocurre en
 *   preprocesamiento.py, nunca en el firmware.
 *
 *   Comandos:
 *     'L' → empezar a etiquetar (modo label). Antes de la primera
 *           muestra emite las lineas [OPTICA_*] con la ganancia y el
 *           reposo por canal, que la PC guarda en el JSON de la sesion.
 *     'S' → detener etiquetado
 *     'R' → reset (descarta buffer)
 *     'M' → marcador de sincronizacion: emite una linea [MARK] con el
 *           millis() actual, para que la PC ancle el cambio de bloque
 *           al reloj del ESP32
 *     'A' → autocalibrar la corriente de los LED (~10 s, mano en reposo)
 *     'T' → autotest del ciclo de muestreo
 *     'K' → reemitir las lineas [OPTICA_*]
 *
 * PRESUPUESTO TEMPORAL POR CICLO (analitico; el autotest mide el real):
 *   Por lectura: 50 us MUX + 200 us asentamiento del LED + conversion
 *   + ~240 us de I2C. MPU6050, 14 bytes a 400 kHz: ~0.4 ms.
 *     ADS1115, solo L          : 5 x 1.65 ms + 0.4 ≈  8.7 ms   cabe
 *     ADS1015, L y D           : 10 x 0.74 ms + 0.65 ≈ 8.1 ms  cabe
 *     ADS1115, L y D           : 10 x 1.6 ms       ≈ 16.7 ms   NO cabe
 *   De ahi que la trama oscura vaya ligada al ADS1015 (config.h).
 *
 * ANCHO DE BANDA:
 *   12 campos ≈ 122 bytes por linea a 100 Hz = 12200 B/s. A 115200
 *   baudios 8N1 el enlace da 11520 B/s, un 6% POR DEBAJO de lo
 *   necesario: se desbordaria. De ahi los 921600 baudios (92160 B/s,
 *   13% de uso).
 */

#include <Wire.h>
#include "config.h"
#include "mux_ads1115.h"
#include "optica_lmg.h"
#include "sensor_imu.h"

// ======================== INSTANCIAS GLOBALES ========================
MUX_ADS1115 muxAds;
OpticaLMG   optica(muxAds);
SensorIMU   imu;

// ======================== VARIABLES DE CONTROL ========================
unsigned long tAnterior = 0;
bool adquiriendo = false;
unsigned long contadorMuestras = 0;

// ======================== BUFFER DE LECTURA ========================
float valoresLMG[NUM_LMG];
float ax, ay, az;   // acelerometro: entra al modelo
float gx, gy, gz;   // giroscopio: solo al CSV, no al modelo

// Lineas que la PC guarda en el JSON de la sesion. El reposo por canal
// es el S-barra-r del indice de rendimiento; la ganancia permite saber
// despues si dos sesiones se capturaron con la misma corriente de LED.
void emitirOptica() {
    Serial.printf("[OPTICA_CONFIG] adc=%s trama_oscura=%d pwm_hz=%d bits=%d\n",
                  ADC_MODELO == ADC_ADS1015 ? "ADS1015" : "ADS1115",
                  TRAMA_OSCURA_HABILITADA ? 1 : 0, LED_PWM_FREQ_HZ, LED_PWM_BITS);
    Serial.print("[OPTICA_DUTY] ");
    for (uint8_t i = 0; i < NUM_LMG; i++) {
        Serial.print(optica.duty(i));
        Serial.print(i + 1 < NUM_LMG ? "," : "\n");
    }
    Serial.print("[OPTICA_REPOSO] ");
    for (uint8_t i = 0; i < NUM_LMG; i++) {
        Serial.print(optica.reposoMedio(i), 2);
        Serial.print(i + 1 < NUM_LMG ? "," : "\n");
    }
}

// Mide el ciclo de muestreo REAL (5 LMG + IMU completa). El presupuesto
// de arriba es analitico; este numero es el que decide.
void autotestTemporal() {
    const uint16_t N = 200;
    unsigned long suma = 0, peor = 0;
    for (uint16_t k = 0; k < N; k++) {
        const unsigned long t0 = micros();
        optica.leerTodos(valoresLMG);
        imu.leerIMUCompleta(ax, ay, az, gx, gy, gz);
        const unsigned long dt = micros() - t0;
        suma += dt;
        if (dt > peor) peor = dt;
    }
    const float medio   = suma / (float)N;
    const float periodo = INTERVALO_MS * 1000.0f;
    Serial.printf("[AUTOTEST] ADC %s, trama oscura %s: ciclo medio %.1f us, "
                  "peor %lu us, de %.0f us disponibles\n",
                  ADC_MODELO == ADC_ADS1015 ? "ADS1015" : "ADS1115",
                  TRAMA_OSCURA_HABILITADA ? "SI" : "NO", medio, peor, periodo);
    if (peor > periodo) {
        Serial.println("[AUTOTEST] ERROR: el ciclo NO cabe en 10 ms. El CSV "
                       "no saldria a 100 Hz.");
    } else if (peor > 0.9f * periodo) {
        Serial.println("[AUTOTEST] AVISO: menos del 10% de margen.");
    } else {
        Serial.println("[AUTOTEST] OK");
    }
}

void setup() {
    Serial.begin(BAUDIOS);
    Wire.begin(PIN_SDA, PIN_SCL);
    Wire.setClock(I2C_FREQ);

    Serial.println("[INIT] Inicializando MUX + ADC...");
    if (!muxAds.begin()) {
        Serial.println("[ERROR] ADC no detectado");
        while (1) delay(10);
    }
    Serial.println("[OK] ADC listo");

    if (!optica.begin()) {
        Serial.println("[ERROR] No se pudo configurar el PWM de los LED");
        while (1) delay(10);
    }

    Serial.println("[INIT] Inicializando MPU6050...");
    if (!imu.begin()) {
        Serial.println("[ERROR] MPU6050 no detectado");
        while (1) delay(10);
    }
    Serial.println("[OK] MPU6050 listo");

    autotestTemporal();
    optica.info();

    // Cabecera de los campos que aporta el firmware. Las columnas
    // restantes del esquema las anade el script de captura del Modulo 2.
    Serial.println("[INFO] timestamp_ms,v1,v2,v3,v4,v5,ax,ay,az,gx,gy,gz");
    Serial.println("[READY] Envie 'L' para iniciar, 'S' para detener, "
                   "'M' para marcar sincronizacion, 'A' para autocalibrar "
                   "los LED, 'T' para el autotest.");
}

void loop() {
    // ========== 1. ATENDER COMANDOS SERIAL ==========
    if (Serial.available() > 0) {
        char c = Serial.read();
        if (c == 'L') {
            // Antes de la primera muestra, para que la PC tenga la
            // ganancia y el reposo de la sesion aunque se aborte.
            emitirOptica();
            adquiriendo = true;
            contadorMuestras = 0;
            Serial.println("[START] Adquiriendo datos...");
        } else if (c == 'S') {
            adquiriendo = false;
            Serial.print("[STOP] Muestras adquiridas: ");
            Serial.println(contadorMuestras);
        } else if (c == 'R') {
            adquiriendo = false;
            contadorMuestras = 0;
            Serial.println("[RESET] Buffer descartado");
        } else if (c == 'M') {
            // Marcador de sincronizacion. La PC lo envia en cada cambio
            // de bloque y aqui se devuelve con el millis() del ESP32,
            // de modo que ambos relojes quedan anclados cada ~15 s. Asi
            // la deriva acumulada nunca excede un bloque (0.6 ms a
            // 40 ppm) en vez de los 18-36 ms de una sesion completa.
            Serial.print("[MARK] ");
            Serial.println(millis());
        } else if (c == 'A') {
            // Bloqueante: no se emite ninguna muestra mientras dura, asi
            // que no se hace durante una sesion sino antes de iniciarla.
            const bool estaba = adquiriendo;
            adquiriendo = false;
            optica.autocalibrar(AUTOCAL_VERIFICAR_GESTO_MAX);
            emitirOptica();
            adquiriendo = estaba;
        } else if (c == 'T') {
            autotestTemporal();
        } else if (c == 'K') {
            emitirOptica();
        }
    }

    // ========== 2. MUESTREO NO BLOQUEANTE (100 Hz) ==========
    unsigned long ahora = millis();
    if (ahora - tAnterior >= INTERVALO_MS) {
        tAnterior = ahora;

        // --- Leer 5 LMG: un LED a la vez, con trama oscura si procede ---
        optica.leerTodos(valoresLMG);

        // --- Leer MPU6050: los 6 ejes crudos ---
        // Se piden los 6 aunque el modelo use 3: los bytes del
        // giroscopio ya vienen en la misma transaccion I2C.
        imu.leerIMUCompleta(ax, ay, az, gx, gy, gz);

        // ========== 3. TRANSMITIR POR SERIAL ==========
        if (adquiriendo) {
            // timestamp del ESP32 primero: es el reloj con el que la PC
            // asignara las etiquetas.
            Serial.print(ahora); Serial.print(",");
            for (uint8_t i = 0; i < NUM_LMG; i++) {
                Serial.print(valoresLMG[i], 4); Serial.print(",");
            }
            Serial.print(ax, 4); Serial.print(",");
            Serial.print(ay, 4); Serial.print(",");
            Serial.print(az, 4); Serial.print(",");
            Serial.print(gx, 4); Serial.print(",");
            Serial.print(gy, 4); Serial.print(",");
            Serial.println(gz, 4);

            contadorMuestras++;
        }
    }
}
