/*
 * config.h - Configuracion de hardware para el Modulo 3: Inferencia y Control
 * Protesis transradial - Fusion sensorial y Deep Learning
 *
 * HARDWARE:
 *   - ESP32 WROOM 32
 *   - LMG: 5 fotodiodos OPT101 via MUX CD74HC4067 + ADC ADS1115
 *   - IMU: MPU6050 via I2C
 *   - FSR: 6 sensores de presion (2x FSR402 + 4x DF9-40) via MUX + ADS1115
 *   - Servos: 5x MG90S via Driver PCA9685 (I2C)
 *
 * PINOUT I2C:
 *   Bus I2C: SDA=GPIO21, SCL=GPIO22  (400 kHz)
 *   ADS1115: 0x48   (ADC LMG + FSR via MUX)
 *   MPU6050: 0x68   (IMU)
 *   PCA9685: 0x40   (Driver Servos)
 *
 * MUX CD74HC4067 (compartido LMG + FSR):
 *   S0=32, S1=33, S2=25, S3=26, EN=GND
 *   Canales 0-4:   LMG 1..5
 *   Canales 5-10:  FSR 1..6
 */

#ifndef CONFIG_H
#define CONFIG_H

#include <cstdint>

// ======================== I2C ========================
#define PIN_SDA         21
#define PIN_SCL         22
#define I2C_FREQ        400000

// ======================== MUX CD74HC4067 ========================
#define PIN_MUX_S0      32
#define PIN_MUX_S1      33
#define PIN_MUX_S2      25
#define PIN_MUX_S3      26

// Canales LMG (sensores predictivos)
#define CH_LMG_1        0
#define CH_LMG_2        1
#define CH_LMG_3        2
#define CH_LMG_4        3
#define CH_LMG_5        4

// Canales FSR (sensores de retroalimentacion)
#define CH_FSR_PULGAR   5   // FSR402 - dedo pulgar
#define CH_FSR_INDICE   6   // FSR402 - dedo indice
#define CH_FSR_MEDIO    7   // DF9-40
#define CH_FSR_ANULAR   8   // DF9-40
#define CH_FSR_MENIQUE  9   // DF9-40
#define CH_FSR_PALMA    10  // DF9-40 - presion en la palma

// ======================== ADS1115 ========================
#define ADS_ADDR        0x48
#define ADS_GAIN_MV     0.125f  // mV por LSB (GAIN_ONE, ±4.096V)

// ======================== MPU6050 ========================
#define MPU_ADDR        0x68

// ======================== PCA9685 ========================
#define PCA9685_ADDR    0x40
// Rango PWM para MG90S: 500-2500 us
#define SERVO_PULSE_MIN  500    // 0 grados
#define SERVO_PULSE_MAX  2500   // 180 grados
#define NUM_SERVOS       5

// Indices de servos (mapeo a dedos)
#define SERVO_PULGAR    0
#define SERVO_INDICE    1
#define SERVO_MEDIO     2
#define SERVO_ANULAR    3
#define SERVO_MENIQUE   4

// ======================== VENTANA DESLIZANTE ========================
// Frecuencia de muestreo: 100 Hz (cada 10 ms)
// Ventana: 200 ms → 20 muestras
// Stride:  20 ms  → 2 muestras de avance entre inferencias
#define INTERVALO_MUESTRA_MS    10   // 100 Hz
#define INTERVALO_INFERENCIA_MS 20   // 50 Hz (cada 2 muestras)
#define TAMANO_VENTANA          20   // muestras por ventana
#define STRIDE                   2   // muestras entre inferencias
#define NUM_LMG                  5   // fotodiodos OPT101
#define NUM_IMU                  3   // ax, ay, az (sin giroscopio)
#define NUM_FEATURES             (NUM_LMG + NUM_IMU)   // 8
#define NUM_CLASES               5   // Rest, Pinch, Tripod, Power, Ext.

// Cerrojo en tiempo de compilacion. Un desajuste entre el numero de
// canales del firmware y el del modelo NO produce error: el interprete
// leeria el tensor con la forma equivocada y devolveria basura en
// ejecucion. Estas aserciones convierten ese fallo silencioso en un
// error de compilacion.
static_assert(NUM_FEATURES == 8,
              "NUM_FEATURES debe ser 8 (5 LMG + 3 ACC). Si cambia, hay que "
              "reentrenar el modelo y regenerar modelo_gestos_tflite.h; "
              "inferencia.cpp valida la forma del tensor contra esta constante.");
static_assert(TAMANO_VENTANA == 20,
              "TAMANO_VENTANA debe ser 20 (200 ms a 100 Hz), igual que en "
              "preprocesamiento.py.");

// ======================== UMBRALES FSR ========================
// Umbral de presion para detener servo (lazo cerrado)
// Valores en mV, calibrar experimentalmente
#define UMBRAL_FSR_PULGAR   200.0f
#define UMBRAL_FSR_INDICE   200.0f
#define UMBRAL_FSR_MEDIO    180.0f
#define UMBRAL_FSR_ANULAR   180.0f
#define UMBRAL_FSR_MENIQUE  180.0f
#define UMBRAL_FSR_PALMA    150.0f

// ======================== GESTOS ========================
enum Gesto : uint8_t {
    GESTO_REST      = 0,
    GESTO_PINCH     = 1,
    GESTO_TRIPOD    = 2,
    GESTO_POWER     = 3,
    GESTO_EXTENSION = 4,
};

#endif
