/*
 * config.h - Configuracion de hardware para el Modulo 1: Adquisicion de Datos
 * Protesis transradial - Fusion sensorial y Deep Learning
 *
 * PINOUT:
 *   I2C-1: SDA=GPIO21, SCL=GPIO22  → ADS1115 (0x48), MPU6050 (0x68)
 *   MUX:   S0=GPIO32, S1=GPIO33, S2=GPIO25, S3=GPIO26, EN=GND
 *   LED LMG: GPIO 16, 17, 18, 19, 23 (PWM, via transistor)
 *   Serial: 921600 baud
 */

#ifndef CONFIG_H
#define CONFIG_H

// ======================== SERIAL ========================
// 921600 y no 115200. Con 12 campos por linea (~122 bytes) a 100 Hz
// hacen falta 12200 B/s, y 115200 baudios 8N1 solo dan 11520 B/s: el
// enlace se queda un 6% corto y el buffer se desborda. A 921600 el uso
// baja al 13%.
#define BAUDIOS         921600

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

// ======================== ADC ========================
// Todo este bloque, hasta la autocalibracion, es IDENTICO al de Modulo3.
// optica_lmg.cpp y mux_ads1115.cpp son el mismo archivo en ambos
// modulos: la senal con que se entrena tiene que ser la misma con que
// se infiere. La justificacion completa de cada valor esta en
// Modulo3_Inferencia_Control/config.h.
#define ADS_ADDR        0x48

#define ADC_ADS1115     0
#define ADC_ADS1015     1

// DECISION (Tarea 3.c): ADS1015, la unica opcion que cabe en 10 ms con
// trama oscura (~8.6 ms en Modulo3, ~8.1 ms aqui sin FSR; con ADS1115,
// ~18 ms). Analitico: el firmware mide el ciclo real al arrancar.
// MIENTRAS SIGA SOLDADO EL ADS1115, dejar ADC_ADS1115.
#ifndef ADC_MODELO                      // -DADC_MODELO=1 para compilar la otra rama
#define ADC_MODELO      ADC_ADS1115
#endif

#if ADC_MODELO == ADC_ADS1015
  #define ADC_CONVERSION_US  303
#else
  #define ADC_CONVERSION_US  1163
#endif
#define ADC_OVERHEAD_I2C_US  240     // estimado a 400 kHz; el autotest mide
#define ASENTAMIENTO_MUX_US   50

// mV por LSB, solo informativo: la conversion usa computeVolts().
#if ADC_MODELO == ADC_ADS1015
  #define ADS_GAIN_MV   2.0f     // 12 bits, GAIN_ONE
#else
  #define ADS_GAIN_MV   0.125f   // 16 bits, GAIN_ONE
#endif

// ======================== LED DE LOS MODULOS LMG (Tarea 3.a) ========================
// Un pin por LED: se enciende solo el del canal que se lee. Cada pin
// comanda un transistor, no el LED directamente. Validos en el WROOM 32;
// en un WROVER, 16 y 17 son de la PSRAM. CONFIRMAR CONTRA EL PCB.
#define PIN_LED_LMG_1   16
#define PIN_LED_LMG_2   17
#define PIN_LED_LMG_3   18
#define PIN_LED_LMG_4   19
#define PIN_LED_LMG_5   23

#define LED_PWM_FREQ_HZ   100000     // >> 14 kHz de ancho de banda del OPT101
#define LED_PWM_BITS      9          // 100 kHz x 2^9 <= 80 MHz
#define LED_DUTY_MAX      ((1 << LED_PWM_BITS) - 1)

// ======================== TRAMA OSCURA (Tarea 3.b) ========================
// L - D. Ligada al ADS1015: con el ADS1115 el ciclo no cabe y el residuo
// del parpadeo de 120 Hz tras restar seria del 113%.
#define TRAMA_OSCURA_HABILITADA  (ADC_MODELO == ADC_ADS1015)
#define ASENTAMIENTO_LED_US      200

// ======================== AUTOCALIBRACION DE GANANCIA (Tarea 3.d) ========================
#define FONDO_ESCALA_UTIL_MV       3700.0f
#define AUTOCAL_OBJETIVO_FRAC      0.35f
#define AUTOCAL_LIMITE_FRAC        0.95f
#define AUTOCAL_UMBRAL_DISPERSION  1.5f
#define AUTOCAL_DUTY_NOMINAL_FRAC  0.60f
#define AUTOCAL_MUESTRAS           24
#define AUTOCAL_VERIFICAR_GESTO_MAX 1

// ======================== MPU6050 ========================
#define MPU_ADDR        0x68

// ======================== MUESTREO ========================
#define INTERVALO_MS    10          // 10 ms entre muestras → 100 Hz
#define NUM_LMG         5           // fotodiodos OPT101

// Canales de IMU que entran AL MODELO: solo el acelerometro.
// El cuarto canal anterior (qw = |a|/2 saturado) era una funcion
// determinista de los otros tres y se elimino. Con 3, el vector queda
// en 8 canales, la misma forma que la linea base sobre NinaPro DB5
// (5 sEMG + 3 ACC).
#define NUM_IMU         3           // ax, ay, az
#define TOTAL_FEATURES  (NUM_LMG + NUM_IMU)   // 8

// Canales que se GUARDAN EN EL CSV: los 6 ejes crudos de la IMU.
// Los bytes del giroscopio ya viajan en la misma lectura I2C de 14
// bytes, asi que almacenarlos no cuesta tiempo de bus. El filtrado a
// los 8 canales del modelo ocurre en preprocesamiento.py.
#define NUM_IMU_CSV     6           // ax, ay, az, gx, gy, gz
#define TOTAL_CSV       (NUM_LMG + NUM_IMU_CSV)   // 11 + timestamp

// Cerrojo en tiempo de compilacion. Que el firmware emita un numero de
// canales distinto al que espera el modelo no produce ningun error: el
// CSV sale con otra forma y el fallo aparece mucho despues, en el
// entrenamiento o peor, en la inferencia. Estas aserciones lo
// convierten en un error de compilacion.
static_assert(TOTAL_FEATURES == 8,
              "TOTAL_FEATURES debe ser 8 (5 LMG + 3 ACC), la misma forma que "
              "la linea base sobre NinaPro DB5 y que NUM_FEATURES del Modulo 3.");
static_assert(TOTAL_CSV == 11,
              "El CSV guarda 11 senales (5 LMG + 6 ejes de IMU) mas el "
              "timestamp. El giroscopio se guarda aunque el modelo no lo use; "
              "el descarte ocurre en preprocesamiento.py.");

#endif
