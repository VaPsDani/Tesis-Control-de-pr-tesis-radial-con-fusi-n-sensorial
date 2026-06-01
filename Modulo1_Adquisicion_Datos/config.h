/*
 * config.h - Configuracion de hardware para el Modulo 1: Adquisicion de Datos
 * Protesis transradial - Fusion sensorial y Deep Learning
 *
 * PINOUT:
 *   I2C-1: SDA=GPIO21, SCL=GPIO22  → ADS1115 (0x48), MPU6050 (0x68)
 *   MUX:   S0=GPIO32, S1=GPIO33, S2=GPIO25, S3=GPIO26, EN=GND
 *   Serial: 115200 baud
 */

#ifndef CONFIG_H
#define CONFIG_H

// ======================== I2C ========================
#define PIN_SDA         21
#define PIN_SCL         22
#define I2C_FREQ        400000      // 400 kHz (modo Fast)

// ======================== MUX CD74HC4067 ========================
#define PIN_MUX_S0      32
#define PIN_MUX_S1      33
#define PIN_MUX_S2      25
#define PIN_MUX_S3      26

// Canales del MUX asignados a cada sensor LMG (fotodiodos OPT101)
#define CH_LMG_1        0
#define CH_LMG_2        1
#define CH_LMG_3        2
#define CH_LMG_4        3
#define CH_LMG_5        4

// ======================== ADS1115 ========================
#define ADS_ADDR        0x48
#define ADS_GAIN        0.1875e-3   // 0.1875 mV por LSB (GAIN=1, ±4.096V)

// ======================== MPU6050 ========================
#define MPU_ADDR        0x68

// ======================== MUESTREO ========================
#define INTERVALO_MS    10          // 10 ms entre muestras → 100 Hz
#define NUM_LMG         5
#define NUM_IMU         4           // qw, qx, qy, qz
#define TOTAL_FEATURES  (NUM_LMG + NUM_IMU)   // 9

#endif
