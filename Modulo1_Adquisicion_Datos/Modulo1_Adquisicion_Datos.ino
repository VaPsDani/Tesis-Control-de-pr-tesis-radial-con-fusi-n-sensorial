/*
 * Modulo1_Adquisicion_Datos.ino - Modulo 1: Adquisicion de Datos (OMG)
 * ====================================================================
 * Protesis transradial - OMG (QRE1113) + IMU sobre ESP32
 *
 * OBJETIVO:
 *   Adquirir a 100 Hz las senales de 8 modulos QRE1113 con el ADC interno
 *   del ESP32 y los 6 ejes del MPU6050, para el dataset de entrenamiento.
 *   Todo se evalua fuera de linea: este firmware solo adquiere.
 *
 * TRAMA DE CADA CICLO (config.h, optica_omg.h):
 *   1. LED apagados, espera T_OFF_US, lee los 8 canales   -> V_apag
 *   2. LED encendidos, espera T_ON_US, lee los 8, apaga   -> V_enc
 *   3. Lee el MPU6050
 *   4. v = V_apag - V_enc (mV, positivo con mas luz), amb = V_apag
 *   5. Emite la linea CSV
 *
 * PROTOCOLO SERIAL, 23 campos por linea:
 *   timestamp_ms,v1..v8,ax,ay,az,gx,gy,gz,amb1..amb8
 *
 *   El timestamp es el millis() del ESP32 al empezar el ciclo, el reloj
 *   bueno para el espaciado entre muestras. Las demas columnas del CSV
 *   (sujeto, etiqueta, bloque...) las agrega la app de captura.
 *
 *   Al modelo entran v1..v8 y ax, ay, az (11 canales). El giroscopio y la
 *   trama oscura se guardan para el analisis y se descartan en
 *   preprocesamiento.py.
 *
 * COMANDOS:
 *   L        iniciar la emision de muestras (antes, las lineas de config)
 *   S        detener
 *   R        detener y reiniciar el contador
 *   M        marcador de sincronizacion: [MARK] con el millis() actual
 *   K        reemitir version, pines, [OPTICA_*] y la linea [IMU]
 *   T        autotest: 1000 ciclos (media, p95 y maximo), y por canal
 *            V_enc, V_apag y v en reposo con sus banderas
 *   C        curva de asentamiento por canal y T_ON_US / T_OFF_US sugeridos
 *   X        diafonia entre canales
 *   D<0-3>   capacidad de salida de los 8 LED, hasta reiniciar. Ej. "D3"
 *   E<us>    T_ON_US, se guarda en NVS. Ej. "E400"
 *   O<us>    T_OFF_US, se guarda en NVS. Ej. "O400"
 *   T, C y X detienen la emision mientras corren.
 */

#include <Wire.h>
#include "config.h"
#include "optica_omg.h"
#include "sensor_imu.h"

OpticaOMG optica;
SensorIMU imu;

bool adquiriendo = false;
unsigned long contadorMuestras = 0;
uint32_t proximoUs = 0;

float vApag[NUM_OPT], vEnc[NUM_OPT];
float ax, ay, az, gx, gy, gz;
char linea[BYTES_LINEA_MAX + 64];

// ======================== CICLO ========================
// Pasos 1 a 3 de la trama.
void medirCiclo() {
    optica.medir(vApag, vEnc);
    imu.leerIMUCompleta(ax, ay, az, gx, gy, gz);
}

// Pasos 4 y 5: la linea CSV en el buffer. Devuelve su largo.
int formatearLinea(unsigned long t) {
    int n = snprintf(linea, sizeof(linea), "%lu", t);
    for (uint8_t k = 0; k < NUM_OPT; k++) {
        n += snprintf(linea + n, sizeof(linea) - n, ",%.1f", vApag[k] - vEnc[k]);
    }
    n += snprintf(linea + n, sizeof(linea) - n, ",%.4f,%.4f,%.4f,%.4f,%.4f,%.4f",
                  ax, ay, az, gx, gy, gz);
    for (uint8_t k = 0; k < NUM_OPT; k++) {
        n += snprintf(linea + n, sizeof(linea) - n, ",%.1f", vApag[k]);
    }
    n += snprintf(linea + n, sizeof(linea) - n, "\n");
    return n;
}

// ======================== INFORMACION ========================
void emitirVersion() {
    Serial.printf("[FW] version=%s modulo=1 sensor=QRE1113 adc=interno "
                  "canales_opticos=%d fs_hz=%d\n", FIRMWARE_VERSION, NUM_OPT,
                  1000000 / INTERVALO_US);
}

void emitirTodo() {
    emitirVersion();
    optica.imprimirPines();
    optica.imprimirConfig();
    imu.imprimirConfig();
}

// ======================== 'T': AUTOTEST ========================
static uint32_t tiemposUs[1000];

static int compararU32(const void *a, const void *b) {
    const uint32_t x = *(const uint32_t *)a, y = *(const uint32_t *)b;
    return (x > y) - (x < y);
}

void autotest() {
    const uint16_t N = 1000;
    double sEnc[NUM_OPT] = {0}, sApag[NUM_OPT] = {0}, sV[NUM_OPT] = {0},
           sV2[NUM_OPT] = {0};
    Serial.println("[AUTOTEST] 1000 ciclos (10 s). Mano en reposo y quieta.");
    for (uint16_t i = 0; i < N; i++) {
        const uint32_t t0 = micros();
        medirCiclo();
        formatearLinea(millis());           // el ciclo real incluye formatear
        tiemposUs[i] = micros() - t0;
        for (uint8_t k = 0; k < NUM_OPT; k++) {
            const float v = vApag[k] - vEnc[k];
            sEnc[k] += vEnc[k]; sApag[k] += vApag[k]; sV[k] += v; sV2[k] += v * v;
        }
        while (micros() - t0 < INTERVALO_US) { }
    }
    double suma = 0;
    for (uint16_t i = 0; i < N; i++) suma += tiemposUs[i];
    qsort(tiemposUs, N, sizeof(uint32_t), compararU32);
    const uint32_t p95 = tiemposUs[(uint16_t)ceilf(0.95f * N) - 1];
    const uint32_t peor = tiemposUs[N - 1];
    Serial.printf("[AUTOTEST] ciclo: medio %.1f us, p95 %lu us, maximo %lu us, "
                  "de %d us disponibles\n", suma / N, (unsigned long)p95,
                  (unsigned long)peor, INTERVALO_US);
    if (peor > INTERVALO_US) {
        Serial.println("[AUTOTEST] ERROR: el ciclo NO cabe en 10 ms. El CSV no "
                       "saldria a 100 Hz.");
    } else if (peor > 0.9f * INTERVALO_US) {
        Serial.println("[AUTOTEST] AVISO: menos del 10% de margen.");
    } else {
        Serial.println("[AUTOTEST] ciclo OK");
    }

    // Banderas PROVISIONALES (config.h).
    for (uint8_t k = 0; k < NUM_OPT; k++) {
        const float enc = sEnc[k] / N, apag = sApag[k] / N, v = sV[k] / N;
        const float sd = sqrtf(fmaxf(0.0f, (float)(sV2[k] / N) - v * v));
        String b;
        if (enc < UMBRAL_SATURADO_MV) b += " SATURADO";
        if (v < UMBRAL_SIN_SENAL_MV) b += " SIN_SENAL";
        if (fabsf(apag - enc) < UMBRAL_LED_APAGADO_MV) b += " LED_NO_ENCIENDE";
        if (apag >= UMBRAL_TOPE_ADC_MV) b += " TOPE_ADC(informativo)";
        Serial.printf("[AUTOTEST] modulo %u: V_enc=%.1f V_apag=%.1f v=%.1f "
                      "sd_v=%.2f mV%s\n", k + 1, enc, apag, v, sd,
                      b.length() ? b.c_str() : " OK");
    }
    imu.imprimirConfig();
}

// ======================== SETUP Y LOOP ========================
void setup() {
    Serial.setTxBufferSize(SERIAL_TX_BUFFER);
    Serial.begin(BAUDIOS);
    Wire.begin(PIN_SDA, PIN_SCL);
    Wire.setClock(I2C_FREQ);

    // Los OUT de los modulos 7 y 8 (GPIO25 y 26) son ADC2, que el driver
    // de WiFi toma para si. El WiFi nunca se inicia: no se incluye WiFi.h,
    // que ademas enlazaria su pila entera (de 24% a 70% de la flash). El
    // Bluetooth se apaga explicitamente.
    btStop();
    Serial.println("[RADIO] WiFi sin iniciar y Bluetooth apagado (ADC2 libre para los modulos 7 y 8)");

    optica.begin();
    emitirVersion();
    optica.imprimirPines();

    Serial.println("[INIT] Inicializando MPU6050...");
    if (!imu.begin()) {
        Serial.println("[ERROR] MPU6050 no detectado o mal configurado");
        while (1) delay(10);
    }
    Serial.println("[OK] MPU6050 listo");
    optica.imprimirConfig();
    imu.imprimirConfig();

    Serial.println("[INFO] timestamp_ms,v1,v2,v3,v4,v5,v6,v7,v8,ax,ay,az,gx,gy,gz,"
                   "amb1,amb2,amb3,amb4,amb5,amb6,amb7,amb8");
    Serial.println("[READY] L iniciar, S detener, M marcar, K configuracion, "
                   "T autotest, C asentamiento, X diafonia, D<0-3> capacidad "
                   "de los LED, E<us> T_ON_US, O<us> T_OFF_US.");
    proximoUs = micros();
}

void atenderComandos() {
    if (Serial.available() <= 0) return;
    const char c = Serial.read();
    switch (c) {
        case 'L':
            emitirTodo();
            adquiriendo = true;
            contadorMuestras = 0;
            Serial.println("[START] Adquiriendo datos...");
            proximoUs = micros();
            break;
        case 'S':
            adquiriendo = false;
            Serial.printf("[STOP] Muestras adquiridas: %lu\n", contadorMuestras);
            break;
        case 'R':
            adquiriendo = false;
            contadorMuestras = 0;
            Serial.println("[RESET] Buffer descartado");
            break;
        case 'M':
            Serial.printf("[MARK] %lu\n", millis());
            break;
        case 'K':
            emitirTodo();
            break;
        case 'T':
            adquiriendo = false;
            emitirVersion();
            optica.imprimirConfig();
            autotest();
            break;
        case 'C':
            adquiriendo = false;
            optica.curvaAsentamiento();
            break;
        case 'X':
            adquiriendo = false;
            optica.diafonia();
            break;
        case 'D': {
            const long v = Serial.parseInt();
            if (v < 0 || v > 3 || !optica.fijarDriveCap((uint8_t)v)) {
                Serial.printf("[ERROR] Capacidad fuera de rango: %ld (0 a 3)\n", v);
            } else {
                Serial.printf("[OPTICA] capacidad de los LED = %ld hasta reiniciar\n", v);
                optica.imprimirConfig();
            }
            break;
        }
        case 'E':
        case 'O': {
            const long v = Serial.parseInt();
            const bool ok = v >= 0 && (c == 'E' ? optica.fijarTOn((uint32_t)v)
                                                : optica.fijarTOff((uint32_t)v));
            if (!ok) {
                Serial.printf("[ERROR] %s fuera de rango: %ld (0 a %d us)\n",
                              c == 'E' ? "T_ON_US" : "T_OFF_US", v, T_MAX_US);
            } else {
                Serial.printf("[OPTICA] %s = %ld us, guardado en NVS\n",
                              c == 'E' ? "T_ON_US" : "T_OFF_US", v);
                optica.imprimirConfig();
            }
            break;
        }
        default:
            break;
    }
}

void loop() {
    atenderComandos();

    // Ciclo de 10 ms contra un reloj fijo: proximoUs avanza de a 10 ms,
    // asi un ciclo tardio no corre a los siguientes. Si se atraso mas de
    // un ciclo (un comando largo), se resincroniza sin recuperar.
    const uint32_t ahora = micros();
    if ((int32_t)(ahora - proximoUs) < 0) return;
    proximoUs += INTERVALO_US;
    if ((int32_t)(ahora - proximoUs) > (int32_t)INTERVALO_US) proximoUs = ahora + INTERVALO_US;

    const unsigned long t = millis();
    medirCiclo();
    if (adquiriendo) {
        const int n = formatearLinea(t);
        Serial.write((const uint8_t *)linea, n);
        contadorMuestras++;
    }
}
