/*
 * adquisicion_datos.ino - Modulo 1: Adquisicion de Datos
 * ======================================================
 * Protesis transradial - Fusion sensorial y Deep Learning
 *
 * OBJETIVO:
 *   Adquirir senales de 5 fotodiodos LMG (OPT101 via MUX+ADS1115) y
 *   cuaterniones del MPU6050 para construir el dataset de entrenamiento.
 *
 * VENTANA DESLIZANTE (lado PC):
 *   Los datos se envian en crudo por Serial a 100 Hz.
 *   El script en Python (Modulo 2) aplicara:
 *     - Ventana de 200 ms → 20 muestras a 100 Hz
 *     - Stride de 20 ms → 2 muestras de avance
 *
 * PROTOCOLO SERIAL:
 *   Formato: CSV (9 columnas)
 *   v1,v2,v3,v4,v5,qw,qx,qy,qz
 *
 *   Comandos:
 *     'L' → empezar a etiquetar (modo label)
 *     'S' → detener etiquetado
 *     'R' → reset (descarta buffer)
 *
 * SINCRONIZACION:
 *   - Sin delays bloqueantes: uso de millis() para mantener 100 Hz
 *   - La lectura del MUX + ADS1115 toma ~7 ms (5 canales × 1.4 ms)
 *   - La lectura del MPU6050 toma ~2 ms
 *   - Total por ciclo: ~9 ms → margen a 10 ms
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
float qw, qx, qy, qz;

void setup() {
    Serial.begin(115200);
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

    // Cabecera CSV
    Serial.println("[INFO] v1_LMG,v2_LMG,v3_LMG,v4_LMG,v5_LMG,qw_IMU,qx_IMU,qy_IMU,qz_IMU");
    Serial.println("[READY] Envie 'L' para iniciar adquisicion, 'S' para detener.");
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

        // --- Leer MPU6050 (pseudo-cuaterniones) ---
        imu.leerCuaterniones(qw, qx, qy, qz);

        // ========== 3. TRANSMITIR POR SERIAL ==========
        if (adquiriendo) {
            Serial.print(valoresLMG[0], 4); Serial.print(",");
            Serial.print(valoresLMG[1], 4); Serial.print(",");
            Serial.print(valoresLMG[2], 4); Serial.print(",");
            Serial.print(valoresLMG[3], 4); Serial.print(",");
            Serial.print(valoresLMG[4], 4); Serial.print(",");
            Serial.print(qw, 4); Serial.print(",");
            Serial.print(qx, 4); Serial.print(",");
            Serial.print(qy, 4); Serial.print(",");
            Serial.println(qz, 4);

            contadorMuestras++;
        }
    }
}
