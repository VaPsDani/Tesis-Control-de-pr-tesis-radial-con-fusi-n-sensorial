/*
 * config.h - Configuracion de hardware del Modulo 1: Adquisicion de Datos
 * Protesis transradial - OMG (QRE1113) + IMU sobre ESP32
 *
 * Unica fuente de verdad de los pines, los tiempos de la trama y el
 * formato del CSV. El firmware imprime la tabla de pines al arrancar.
 *
 * PLACA: DevKit ESP32 WROOM de 38 pines. Serial a 921600 baudios.
 */

#ifndef CONFIG_H
#define CONFIG_H

#include <stdint.h>

// ======================== VERSION ========================
// La emite el firmware como [FW] version=..., y la app de captura la
// guarda en el JSON de cada sesion. SUBIRLA al cambiar algo que altere la
// senal: pines, tiempos de la trama, ADC, promedio o capacidad de los LED.
#define FIRMWARE_VERSION  "M1-2026.11.13-QRE"

// SESIONES QUE NO SE MEZCLAN SIN COMPROBAR:
//   M1-2026.11.13-QRE cambia de sensor: 8 modulos QRE1113 (LED IR y
//   fototransistor en el mismo encapsulado, en contacto con la piel)
//   leidos con el ADC interno del ESP32, en lugar de 5 OPT101 leidos con
//   dos ADS1115. CSV con 8 canales opticos y su trama oscura. Estas
//   sesiones NO se mezclan con las de M1-2026.10.22 o anteriores: otro
//   sensor, otro numero de canales y otra polaridad. El firmware LMG
//   sigue en el tag lmg-final-2026-11-13.

// ======================== SERIAL ========================
// Linea de datos, peor caso (valores con signo y del ancho maximo):
//   timestamp_ms            "4294967," hasta  8 bytes (~71 min: 7 cifras)
//   v1..v8   "-3100.0,"     8 bytes x 8 =    64
//   ax..az   "-1.2345,"     8 bytes x 3 =    24
//   gx..gz   "-250.0000,"  10 bytes x 3 =    30
//   amb1..8  "3100.0,"      7 bytes x 8 =    56   (el ultimo con \n)
//   total                                ~  182 bytes por linea
// A 100 Hz son 18 200 B/s. 921600 baudios 8N1 dan 92 160 B/s: uso del
// ~20 % en el peor caso. A 115200 (11 520 B/s) NO cabria.
#define BAUDIOS            921600
#define BYTES_LINEA_MAX    182
// Buffer de transmision: una linea entera cabe sin bloquear el ciclo.
#define SERIAL_TX_BUFFER   1024

// ======================== I2C (MPU6050) ========================
#define PIN_SDA            21
#define PIN_SCL            22
#define I2C_FREQ           400000      // 400 kHz

// ======================== MODULOS OPTICOS (QRE1113GR) ========================
// Conector J1 de cada modulo, JST ZH B5B-ZR (paso 1,5 mm):
//   1 VCC   3,3 V, OBLIGATORIO: OUT entra directo al ADC del ESP32.
//   2 GND
//   3 OUT   colector del fototransistor, R2 = 47 kohm a VCC, emisor a
//           GND. MAS LUZ DA MENOS TENSION. A oscuras queda en ~3,3 V.
//   4 IR    anodo del LED del QRE. Catodo a GND por R1 = 100 ohm. GPIO
//           en alto lo enciende: ~20 mA con 3,3 V (VF ~1,2 V a 20 mA).
//   5 Led   tres LED externos del PCB (D1 a D3, R3) que NO se usan: SIN
//           CONECTAR.
#define NUM_OPT            8

// TABLA DE PINES. Modulo k (1 a 8) -> OUT al ADC, IR al LED.
//   Modulo | OUT (ADC)                  | IR (LED)
//   1      | GPIO36 (VP/SP, ADC1_CH0)   | GPIO13
//   2      | GPIO39 (VN/SN, ADC1_CH3)   | GPIO27
//   3      | GPIO34 (ADC1_CH6)          | GPIO23
//   4      | GPIO35 (ADC1_CH7)          | GPIO19
//   5      | GPIO32 (ADC1_CH4)          | GPIO18
//   6      | GPIO33 (ADC1_CH5)          | GPIO17
//   7      | GPIO25 (ADC2_CH8)          | GPIO16
//   8      | GPIO26 (ADC2_CH9)          | GPIO4
// El ADC2 (25 y 26) funciona porque el WiFi nunca se inicia y el
// Bluetooth se apaga al arrancar (setup, linea [RADIO]).
// NO USAR: 0 y 12 (arranque), 6 a 11 (flash: SD2, SD3, CMD, CLK, SD0,
// SD1), 1 y 3 (serie). El 2 solo como indicador (LED de la placa).
// Libres: 14, 5, 15. 16 y 17 valen porque es WROOM (en WROVER son de la
// PSRAM).
static const uint8_t PIN_OUT[NUM_OPT] = {36, 39, 34, 35, 32, 33, 25, 26};
static const uint8_t PIN_IR[NUM_OPT]  = {13, 27, 23, 19, 18, 17, 16, 4};
static const char *const CANAL_ADC[NUM_OPT] = {
    "ADC1_CH0", "ADC1_CH3", "ADC1_CH6", "ADC1_CH7",
    "ADC1_CH4", "ADC1_CH5", "ADC2_CH8", "ADC2_CH9"};

// Valores del PCB del asesor, informativos (van al JSON de la sesion).
#define VCC_MODULO_V       3.3f
#define R1_OHM             100
#define R2_OHM             47000

// ======================== ADC INTERNO ========================
// 12 bits y atenuacion de 11 dB en cada pin, lectura calibrada con
// analogReadMilliVolts. Con 11 dB el tope util es ~3,1 V, por debajo de
// los 3,3 V de OUT a oscuras: dentro de la carcasa la lectura con el LED
// apagado queda en el tope, y eso es normal.
#define ADC_BITS           12
// Lecturas promediadas por canal y por fase. PROVISIONAL.
#define N_MUESTRAS         4
// Descartar la primera lectura tras cambiar de canal: el condensador de
// muestreo del ADC guarda carga del canal anterior, y con 47 kohm de
// fuente tarda en igualarse. PROVISIONAL.
#define DESCARTAR_PRIMERA  1

// ======================== LED ========================
// Capacidad de salida del GPIO, la misma en los 8 y fijada a mano (no se
// deja la de fabrica). 0 a 3 = GPIO_DRIVE_CAP_0 a GPIO_DRIVE_CAP_3. La
// cambia 'D' para la prueba de saturacion, sin guardarla: al reiniciar
// vuelve a la de aqui.
#define DRIVE_CAP_DEFECTO  2

// Modo de encendido en la fase iluminada.
//   SIMULTANEO  los 8 a la vez, una espera, se leen los 8. Por defecto.
//   SECUENCIAL  uno por uno: enciende k, espera, lee k, apaga k. Solo si
//               la prueba 'X' muestra diafonia. Con T_ON_US de 1000 us el
//               ciclo pasa de 10 ms: lo dice el autotest.
// Ojo en SIMULTANEO: los 8 LED piden ~160 mA juntos. Si el 3,3 V cae al
// encenderlos, OUT (colgado de VCC por R2) cae igual en todos los
// canales, y v lo arrastra como un artefacto comun. Lo detecta 'X'.
#define MODO_SIMULTANEO    0
#define MODO_SECUENCIAL    1
#define MODO_LED           MODO_SIMULTANEO

// ======================== TRAMA ========================
// Ciclo de 10 ms (100 Hz):
//   1. Todos los LED apagados, espera T_OFF_US, lee los 8 -> V_apag[k].
//   2. LED encendidos, espera T_ON_US, lee los 8 -> V_enc[k], apaga.
//   3. Lee el MPU6050.
//   4. v[k] = V_apag[k] - V_enc[k] en mV (positivo, mayor con mas luz).
//      amb[k] = V_apag[k].
//   5. Emite la linea CSV.
// T_ON_US y T_OFF_US PROVISIONALES hasta medirlos con 'C' (hoja de
// datos: 20 us con 1 kohm de carga, con 47 kohm sera bastante mas). Se
// cambian por serie ('E' y 'O') y se guardan en NVS.
#define T_ON_US_DEFECTO    1000
#define T_OFF_US_DEFECTO   1000
#define T_MAX_US           5000         // tope de los comandos E y O

#define INTERVALO_US       10000        // 100 Hz

// ======================== UMBRALES (PROVISIONALES) ========================
// Banderas del autotest, a revisar con la placa.
#define UMBRAL_SATURADO_MV     250.0f   // V_enc por debajo: satura con luz
#define UMBRAL_SIN_SENAL_MV     30.0f   // v por debajo: casi no vuelve luz
#define UMBRAL_LED_APAGADO_MV   10.0f   // |V_apag - V_enc| menor: el LED no enciende
#define UMBRAL_TOPE_ADC_MV    3050.0f   // V_apag en el tope del ADC (informativo)

// ======================== MPU6050 ========================
#define MPU_ADDR           0x68
// Rango y filtro, se escriben al arrancar y se releen (sensor_imu.cpp).
#define MPU_DLPF_CFG       4   // acelerometro 21 Hz, retardo 8.5 ms. Giroscopio 20 Hz, 8.3 ms
#define MPU_ACCEL_FS_SEL   0   // +/-2 g, 16384 LSB/g
#define MPU_GYRO_FS_SEL    0   // +/-250 grados/s, 131 LSB por grado/s

// ======================== CANALES ========================
// Al modelo entran los 8 opticos y el acelerometro (configuracion B).
#define NUM_IMU            3            // ax, ay, az
#define TOTAL_FEATURES     (NUM_OPT + NUM_IMU)             // 11
// Al CSV van ademas el giroscopio y la trama oscura de cada canal.
#define NUM_IMU_CSV        6            // ax, ay, az, gx, gy, gz
#define TOTAL_CSV          (NUM_OPT + NUM_IMU_CSV + NUM_OPT)  // 22 + timestamp

static_assert(TOTAL_FEATURES == 8 + 3,
              "Al modelo entran 8 canales opticos y 3 del acelerometro.");
static_assert(TOTAL_CSV == 22,
              "El CSV guarda 22 senales mas el timestamp: v1..v8, ax..gz y "
              "amb1..amb8.");

#endif
