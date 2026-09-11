/*
 * adquisicion_datos.ino - Modulo 1: Adquisicion de Datos
 * ======================================================
 * Protesis transradial - Fusion sensorial y Deep Learning
 *
 * OBJETIVO:
 *   Adquirir senales de 5 fotodiodos LMG (OPT101 via MUX+ADS1115) y los
 *   6 ejes crudos del MPU6050 para construir el dataset de entrenamiento.
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
 * ESQUEMA COMPLETO DEL CSV (17 columnas) — lo escribe el script de
 * captura del Modulo 2, no este firmware:
 *
 *   subject_id, repetition_id, timestamp_ms, v1..v5,
 *   ax, ay, az, gx, gy, gz, label, bloque_tipo, en_margen, es_calibracion
 *
 *   De esas, el firmware aporta las 12 de arriba. Las otras cinco
 *   (subject_id, repetition_id, label, bloque_tipo, en_margen,
 *   es_calibracion) las anade la PC, que es quien conoce el protocolo
 *   de la sesion. El esquema queda fijado aqui para que no haya un
 *   segundo cambio de formato mas adelante.
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
 *     'L' → empezar a etiquetar (modo label)
 *     'S' → detener etiquetado
 *     'R' → reset (descarta buffer)
 *     'M' → marcador de sincronizacion: emite una linea [MARK] con el
 *           millis() actual, para que la PC ancle el cambio de bloque
 *           al reloj del ESP32
 *
 * PRESUPUESTO TEMPORAL POR CICLO (medido tras fijar 860 SPS):
 *   - 5 canales LMG: 5 × (1.163 ms conversion + ~0.5 ms overhead I2C
 *     + 50 us asentamiento del MUX) ≈ 8.3 ms
 *   - MPU6050, 14 bytes a 400 kHz                        ≈ 0.4 ms
 *   - Total por ciclo                                    ≈ 8.7 ms
 *   Entra en los 10 ms con ~13% de margen. Sin el setDataRate del
 *   Bloque B el ADC corria a 128 SPS y el ciclo tomaba ~39 ms (~25 Hz).
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
#include "sensor_imu.h"

// ======================== INSTANCIAS GLOBALES ========================
MUX_ADS1115 muxAds;
SensorIMU imu;

// ======================== VARIABLES DE CONTROL ========================
unsigned long tAnterior = 0;
bool adquiriendo = false;
unsigned long contadorMuestras = 0;

// ======================== BUFFER DE LECTURA ========================
float valoresLMG[NUM_LMG];
float ax, ay, az;   // acelerometro: entra al modelo
float gx, gy, gz;   // giroscopio: solo al CSV, no al modelo

void setup() {
    Serial.begin(BAUDIOS);
    Wire.begin(PIN_SDA, PIN_SCL);
    Wire.setClock(I2C_FREQ);

    Serial.println("[INIT] Inicializando MUX + ADS1115...");
    if (!muxAds.begin()) {
        Serial.println("[ERROR] ADS1115 no detectado");
        while (1) delay(10);
    }
    Serial.println("[OK] ADS1115 listo");

    Serial.println("[INIT] Inicializando MPU6050...");
    if (!imu.begin()) {
        Serial.println("[ERROR] MPU6050 no detectado");
        while (1) delay(10);
    }
    Serial.println("[OK] MPU6050 listo");

    // Cabecera de los campos que aporta el firmware. Las 5 columnas
    // restantes del esquema (subject_id, repetition_id, label,
    // bloque_tipo, en_margen, es_calibracion) las anade el script de
    // captura del Modulo 2.
    Serial.println("[INFO] timestamp_ms,v1,v2,v3,v4,v5,ax,ay,az,gx,gy,gz");
    Serial.println("[READY] Envie 'L' para iniciar, 'S' para detener, "
                   "'M' para marcar sincronizacion.");
}

void loop() {
    // ========== 1. ATENDER COMANDOS SERIAL ==========
    if (Serial.available() > 0) {
        char c = Serial.read();
        if (c == 'L') {
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
        }
    }

    // ========== 2. MUESTREO NO BLOQUEANTE (100 Hz) ==========
    unsigned long ahora = millis();
    if (ahora - tAnterior >= INTERVALO_MS) {
        tAnterior = ahora;

        // --- Leer 5 LMG via MUX + ADS1115 ---
        // Cada lectura: seleccionar canal MUX → esperar 5 us → leer ADC
        valoresLMG[0] = muxAds.leerCanal(CH_LMG_1);
        valoresLMG[1] = muxAds.leerCanal(CH_LMG_2);
        valoresLMG[2] = muxAds.leerCanal(CH_LMG_3);
        valoresLMG[3] = muxAds.leerCanal(CH_LMG_4);
        valoresLMG[4] = muxAds.leerCanal(CH_LMG_5);

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
