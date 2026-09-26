/*
 * config.h - Configuracion de hardware para el Modulo 3: Inferencia y Control
 * Protesis transradial - Fusion sensorial y Deep Learning
 *
 * HARDWARE:
 *   - ESP32 WROOM 32
 *   - LMG: 5 fotodiodos OPT101, cada uno en su PCB de modulo con conector
 *          de 4 pines (VCC, GND, OUT, LED). OUT entra directo a dos ADC:
 *          modulos 1-3 al ADS1115 #1 (0x48), modulos 4-5 al #2 (0x49).
 *          Sin multiplexor.
 *   - IMU: MPU6050 via I2C
 *   - FSR: 5 sensores de presion, uno por yema (2x FSR402 + 3x DF9-40),
 *          leidos por el ADC INTERNO del ESP32 (ADC1). No alimentan al
 *          clasificador: solo cierran el lazo de fuerza.
 *   - Servos: 5x MG90S via Driver PCA9685 (I2C)
 *
 * PINOUT I2C:
 *   Bus I2C: SDA=GPIO21, SCL=GPIO22  (400 kHz)
 *   ADS1115 #1: 0x48 (ADDR a GND)   LMG 1, 2, 3 en AIN0, AIN1, AIN2
 *   ADS1115 #2: 0x49 (ADDR a VDD)   LMG 4, 5 en AIN0, AIN1
 *   MPU6050:    0x68 (IMU)
 *   PCA9685:    0x40 (Driver Servos)
 *
 * LED LMG: GPIO 13, 25, 27, 16, 17 (PWM, 100 ohm en serie al LED, en el
 *          PCB de cada modulo)
 *
 * FSR (ADC1, atenuacion 11 dB, divisor con 22 kohm a GND):
 *   Pulgar GPIO32, Indice GPIO33, Medio GPIO34, Anular GPIO35,
 *   Menique GPIO36. GPIO39 queda libre (ADC1 de reserva).
 */

#ifndef CONFIG_H
#define CONFIG_H

#include <cstdint>

// ======================== VERSION ========================
// Se emite al arrancar como [FW] version=... SUBIRLA al cambiar algo que
// altere la senal: pines, asentamiento, trama oscura o ADC.
#define FIRMWARE_VERSION  "M3-2026.09.24"

// SESIONES QUE NO SE MEZCLAN SIN COMPROBAR (igual que en Modulo1):
//   Desde la version 2026.09.24 la cadena optica cambio: sin multiplexor
//   CD74HC4067, dos ADS1115 y GAIN_TWO en lugar de GAIN_ONE, y el LED 2
//   en GPIO25 en lugar de GPIO14. Un modelo entrenado con sesiones de
//   Modulo1 anteriores a M1-2026.09.24 no se despliega aqui, ni se
//   mezclan sesiones de antes y de despues, sin comprobar que el reposo
//   y la excursion por canal son comparables.

// ======================== I2C ========================
#define PIN_SDA         21
#define PIN_SCL         22
#define I2C_FREQ        400000

// ======================== ADC DE LOS CANALES LMG ========================
// Todo este bloque, hasta la autocalibracion, es IDENTICO al de Modulo1:
// optica_lmg.cpp y adc_lmg.cpp son el mismo archivo en ambos modulos.
//
// Dos ADC en el mismo bus I2C, sin multiplexor. Solo leen canales
// opticos: los FSR van al ADC interno del ESP32 (seccion FSR, abajo).
#define ADS_ADDR_1      0x48    // ADDR a GND
#define ADS_ADDR_2      0x49    // ADDR a VDD

// Canal LMG -> ADC (0 = ADS_ADDR_1, 1 = ADS_ADDR_2) y entrada AINx.
#define LMG1_ADS        0
#define LMG1_AIN        0
#define LMG2_ADS        0
#define LMG2_AIN        1
#define LMG3_ADS        0
#define LMG3_AIN        2
#define LMG4_ADS        1
#define LMG4_AIN        0
#define LMG5_ADS        1
#define LMG5_AIN        1

#define ADC_ADS1115     0
#define ADC_ADS1015     1

// DECISION (Tarea 3.c): ADS1015 para poder usar la trama oscura. Sin
// multiplexor y con los FSR fuera del ADS, el ciclo de 10 ms queda asi:
//
//                     5 LMG               +MPU   +5 FSR (ADC ESP32)   total
//   ADS1115 solo L     8.52 ms            0.4    ~0.5                 9.4 ms  SI
//   ADS1115 L y D     17.03 ms            0.4    ~0.5                17.9 ms  NO
//   ADS1015 L y D      8.43 ms            0.4    ~0.5                 9.3 ms  SI
//
//   (ANALITICO, no medido: 1163 o 303 us de conversion + ~240 us de I2C
//   + 300 us de asentamiento del LED por lectura; ~25 us por muestra del
//   ADC del ESP32. El firmware lo mide al arrancar; ver autotestTemporal().)
//
//   60 Hz de muestreo seria ademas la peor eleccion en Peru, porque el
//   parpadeo de 120 Hz de las lamparas se plegaria exactamente a DC.
//
//   Coste del ADS1015: 12 bits en lugar de 16. A GAIN_TWO son 1 mV/LSB:
//   con el reposo autocalibrado a 700 mV (35% de 2000), un cambio de
//   gesto del 5-20% son 35-140 mV, o sea 35-140 LSB. (A GAIN_ONE eran
//   17-70 LSB; con el OPT101 a 5 V, 30-130.)
//
// Pin compatible y misma libreria. MIENTRAS SIGAN SOLDADOS LOS ADS1115,
// dejar ADC_ADS1115: con trama oscura el ciclo no cabe en 10 ms y el
// autotest de arranque lo reporta. Los dos ADC tienen que ser del mismo
// modelo.
#ifndef ADC_MODELO                      // -DADC_MODELO=1 para compilar la otra rama
#define ADC_MODELO      ADC_ADS1115
#endif

#if ADC_MODELO == ADC_ADS1015
  #define ADC_CONVERSION_US  303
#else
  #define ADC_CONVERSION_US  1163
#endif
#define ADC_OVERHEAD_I2C_US  240     // estimado a 400 kHz; el autotest mide

// ======================== LED DE LOS MODULOS LMG (Tarea 3.a) ========================
// Un pin por LED para encender solo el del canal que se lee y eliminar el
// crosstalk optico entre modulos vecinos.
//
// No son pines de arranque (0, 2, 5, 12, 15), no son de la flash (6-11)
// ni solo de entrada (34-39), y todos admiten LEDC. Validos en el
// WROOM 32; en un WROVER, 16 y 17 son de la PSRAM.
//
// LED 2 en GPIO25 y no en GPIO14: el 14 emite pulsos durante el
// arranque del ESP32 y hacia parpadear el LED. El 25 quedo libre al
// quitar el multiplexor y no los emite.
//
// HARDWARE: ataque directo desde el GPIO con la resistencia de 100 ohm
// que va soldada en el PCB de cada modulo. Con un LED IR de 940 nm
// (Vf ~1.3 V) son ~18 mA; el techo fisico es (3.3 V - Vf) / 100 ohm, y
// el PWM solo baja la media, nunca el pico. Solo se enciende un LED a la
// vez, asi que la corriente nunca se multiplica por cinco.
#define PIN_LED_LMG_1   13
#define PIN_LED_LMG_2   25
#define PIN_LED_LMG_3   27
#define PIN_LED_LMG_4   16
#define PIN_LED_LMG_5   17

// PWM para regular la corriente de cada LED (autocalibracion). 100 kHz
// queda muy por encima de los 14 kHz de ancho de banda del OPT101, que lo
// promedia, y cada conversion del ADC integra ademas decenas de ciclos.
// LEDC: frecuencia x 2^bits <= 80 MHz -> a 100 kHz caben 9 bits.
#define LED_PWM_FREQ_HZ   100000
#define LED_PWM_BITS      9
#define LED_DUTY_MAX      ((1 << LED_PWM_BITS) - 1)

// ======================== TRAMA OSCURA (Tarea 3.b) ========================
// Valor del canal = L (LED encendido) - D (apagado). Cancela la continua
// de la luz ambiental; NO el parpadeo de 120 Hz (ver optica_lmg.h).
//
// Va ligada al modelo de ADC a proposito. Con el ADS1115, restar D
// empeora las cosas por dos lados: el ciclo pasa a ~18 ms y deja de
// correr a 100 Hz, y D y L quedan separadas ~1.6 ms, con lo que el
// residuo del parpadeo de 120 Hz sube al 113%, mas que sin restar.
// Mientras siga soldado el ADS1115 se lee solo L, un LED a la vez.
#define TRAMA_OSCURA_HABILITADA  (ADC_MODELO == ADC_ADS1015)
// Asentamiento del OPT101 con su realimentacion interna de 1 MOhm:
// ~80 us. La nota de diseno fija 300 us. Son 600 us por ciclo mas que
// los 200 anteriores (5 canales + 1 trama oscura), y el presupuesto de
// abajo esta calculado con 300. Si hay que recuperar esos 600 us, este
// es el primer sitio donde mirar: 200 sigue dando 2.5 veces el tiempo
// de respuesta del fotodiodo.
#define LED_SETTLE_US            300

// ======================== AUTOCALIBRACION DE GANANCIA (Tarea 3.d) ========================
// Fondo de escala UTIL: el menor entre el del ADC (2048 mV a GAIN_TWO) y
// la excursion maxima del OPT101. Alimentado a 3.3 V, TI garantiza
// Vs - 1.3 V = 2.0 V (tipico Vs - 1.15 V = 2.15 V; SBBS002B). De ahi
// 2000: reposo objetivo 35% = 700 mV, gesto maximo < 95% = 1900 mV.
// El valor anterior, 3700, correspondia al OPT101 a 5 V.
#define FONDO_ESCALA_UTIL_MV       2000.0f
#define AUTOCAL_OBJETIVO_FRAC      0.35f    // reposo en el 35% del FS
#define AUTOCAL_LIMITE_FRAC        0.95f    // el gesto maximo no pasa del 95%
// Si max/min del reposo entre canales es menor que esto a corriente
// nominal, no se ajusta por canal: basta la normalizacion en software.
#define AUTOCAL_UMBRAL_DISPERSION  1.5f
#define AUTOCAL_DUTY_NOMINAL_FRAC  0.60f
#define AUTOCAL_MUESTRAS           24
#define AUTOCAL_VERIFICAR_GESTO_MAX 1

// GAIN_TWO (+/-2.048 V) en los dos ADC: solo leen canales opticos, y el
// OPT101 a 3.3 V no pasa de ~2.15 V. Ver adc_lmg.h.
// mV por LSB, solo informativo: la conversion usa computeVolts().
#if ADC_MODELO == ADC_ADS1015
  #define ADS_GAIN_MV   1.0f       // 12 bits, GAIN_TWO
  #define ADC_RAW_MAX   2047       // codigo de recorte
#else
  #define ADS_GAIN_MV   0.0625f    // 16 bits, GAIN_TWO
  #define ADC_RAW_MAX   32767      // codigo de recorte
#endif

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

// NOTA DE DISENO: los 5 dedos conservan servo y GDL independientes.
// En el repertorio actual de 5 gestos, anular y menique solo se mueven
// en Power y podrian acoplarse mecanicamente a un unico actuador. No se
// hace: esa dependencia es propiedad del REPERTORIO, no de la mano.
// Acoplarlos cerraria la puerta a ampliar el conjunto de gestos, y el
// proyecto se libera como hardware abierto.

// ======================== POSTURAS DE REST Y EXTENSION ========================
// Antes, Rest y Extension eran motrizmente IDENTICOS: {0,0,0,0,0} los
// dos. El modelo distinguia 5 clases pero la mano hacia 4 cosas, y
// confundir Rest con Extension no tenia ninguna consecuencia motora.
// Eso impedia demostrar en la validacion funcional que el sistema
// distingue las cinco clases.
//
// LIMITE DEL MECANISMO, que conviene tener presente:
//   _anguloAPulso mapea 0..180 grados a 500..2500 us, asi que 0 es el
//   suelo del rango comandable: NO hay margen por debajo. La
//   hiperextension anatomica pura (ir mas alla del neutro) no se puede
//   comandar sin remapear el rango o rediseniar el mecanismo.
//
//   Lo que si es correcto, y ademas anatomicamente mas fiel, es que
//   REPOSO NO SEA EXTENSION COMPLETA. Una mano relajada tiene flexion
//   pasiva de los dedos por tension tendinosa residual; no queda
//   plana. Asi que Rest pasa a una postura relajada con ligera flexion
//   y Extension se queda en el 0 del rango.
//
//   Si al montar los tendones el cero mecanico del dedo se fija en la
//   postura relajada, entonces comandar 0 SI es hiperextension real.
//   Eso se decide en el ensamblaje y es un punto de ajuste del
//   bring-up, no una constante de software.
//
// Ambos valores son parametrizables para afinarlos con la mano impresa.
// La diferencia de 25 grados en los cinco dedos es visible a simple
// vista, que es el requisito de la validacion funcional.
#define ANGULO_REST        25   // relajado, ligera flexion pasiva
#define ANGULO_EXTENSION    0   // extension completa (suelo del rango)

// ======================== RAMPA DE CIERRE ========================
// Los servos NO saltan al angulo objetivo: avanzan por rampa. Sin esto
// el lazo de fuerza no puede existir, porque frenar un servo que ya
// llego al tope no sirve de nada; con rampa, frenar significa congelar
// el avance.
//
// EL COMPROMISO, para ajustarlo en el bring-up con la mano impresa:
//   Mas rapido  cierre mas natural, pero mas sobrecierre entre la
//               deteccion del umbral FSR y la frenada.
//   Mas lento   menos sobrecierre, pero el agarre se siente perezoso.
//
// 180 grados/s cierra el recorrido completo en 1 s. El sobrecierre es
// el producto de esta velocidad por la latencia de deteccion. Desde que
// los cinco FSR se leen en cada ciclo de 10 ms (ADC del ESP32), esa
// latencia es un periodo de muestreo mas el filtro RC del divisor
// (22 kohm x 100 nF = 2.2 ms), en cualquier gesto:
//
//   Cualquier gesto   ~12 ms ->  ~2.2 grados   (~1.2% del rango)
//
// La frenada ocurre en el mismo bucle de 10 ms en que se lee el sensor,
// no en el de inferencia. (Con el escaneo rotativo anterior, por el
// ADS1115 compartido, el peor caso era Power a 20 Hz: 10.8 grados.)
//
// Referencia de lo que habia antes: sin rampa, el MG90S viajaba libre
// a ~600 grados/s hasta el tope comandado, o sea 90 grados de
// sobrecierre (50%) a cualquier tasa de lectura.
//
// EL VALOR OPTIMO DEPENDE DE LA INERCIA DE LOS DEDOS IMPRESOS, que
// todavia no se conoce. Con dedos pesados puede hacer falta bajarlo
// para que el servo no pierda pasos ni oscile al frenar; con dedos
// ligeros se puede subir. Ajustar aqui y remedir el sobrecierre.
#define RAMPA_GRADOS_POR_S   180

// Periodo de actualizacion de la rampa. A 50 Hz cada paso son 3.6
// grados, imperceptible en un dedo, y cuesta la mitad de escrituras I2C
// al PCA9685 que hacerlo a 100 Hz. Subirlo a cada ciclo (10 ms) suaviza
// el movimiento pero anade ~375 us al presupuesto de muestreo, que ya
// va justo.
#define RAMPA_PERIODO_MS     20

// ======================== VENTANA DESLIZANTE ========================
// Frecuencia de muestreo: 100 Hz (cada 10 ms)
// Ventana: 200 ms → 20 muestras
// Stride:  20 ms  → 2 muestras de avance entre inferencias
#define INTERVALO_MUESTRA_MS    10   // 100 Hz
// Cada cuanto se PUBLICA una ventana para el nucleo 1. Si la inferencia
// tarda mas, gana la ventana mas reciente (intercambio_nucleos.h). El
// valor definitivo se fija con Benchmark_Inferencia (latencia < 150 ms).
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

// ======================== REPARTO ENTRE NUCLEOS ========================
// Nucleo 0: tarea de tiempo real cada 10 ms con TODO el I2C (ADS1115,
//   MPU6050, PCA9685) y todo lo que tiene plazo: LMG, IMU, FSR, frenado,
//   rampa de servos, comandos por Serial.
// Nucleo 1: el loop() de Arduino, que solo infiere (calculo puro).
// Los servos no van con la inferencia: con el nucleo 1 ocupado decenas de
// ms, la rampa se congelaria y el frenado por FSR llegaria tarde. Y el
// bus I2C se usa desde un solo nucleo, sin coordinar accesos.
#define NUCLEO_TIEMPO_REAL        0
#define NUCLEO_INFERENCIA         1
// Por encima de las tareas normales (1) y muy por debajo de las del
// sistema (esp_timer 22, ipc 24).
#define PRIORIDAD_TIEMPO_REAL     5
#define PILA_TIEMPO_REAL_BYTES    8192

#if defined(ARDUINO_RUNNING_CORE) && ARDUINO_RUNNING_CORE != NUCLEO_INFERENCIA
#error "loop() tiene que correr en el nucleo 1 (ARDUINO_RUNNING_CORE=1): es el de la inferencia"
#endif

// ======================== CALIBRACION / NORMALIZACION ========================
// El modelo se entrena con datos normalizados por sujeto (z-score por
// canal), asi que el firmware debe normalizar igual o le entregaria
// senales en otra escala. Ver calibracion.h para el fundamento.

// --- Tipo de calibracion ---
#define CALIB_SOLO_REPOSO        0
#define CALIB_SECUENCIA_GESTOS   1

// Decidido a partir del experimento de normalizacion sobre NinaPro DB5
// (resultados_cv/comparativa_final.txt):
//
//   sujeto      (todas las ventanas del sujeto) : 70.00% +/- 7.86%
//   sujeto_rest (solo ventanas de reposo)       : 69.11% +/- 3.92%
//
// La media es equivalente, la diferencia de 0.89 puntos queda por debajo
// del ruido entre corridas (~0.6 puntos), pero la desviacion entre
// sujetos se reduce a la mitad y el rango entre pliegues pasa de 20.9 a
// 12.1 puntos. Para una protesis, un sistema mas predecible entre
// usuarios vale mas que un pico ligeramente mas alto. Ademas la
// calibracion por reposo solo exige que el usuario se quede quieto, no
// que ejecute los cuatro gestos cada vez que se pone el dispositivo.
//
// Cambiar a CALIB_SECUENCIA_GESTOS exige reentrenar con la
// normalizacion equivalente; no basta con tocar esta constante.
#define CALIB_TIPO               CALIB_SOLO_REPOSO

// --- Parametros del bloque de calibracion ---
// Misma duracion y margenes que el bloque de calibracion del protocolo
// de captura, para que el firmware calcule sus estadisticas sobre la
// misma cantidad y el mismo tipo de senal con que se valido. Acortarlo
// es posible, pero habria que revalidarlo.
#define CALIB_DURACION_MS        15000   // 15 s de bloque
#define CALIB_MARGEN_INICIAL_MS   1000   // el usuario se acomoda
#define CALIB_MARGEN_FINAL_MS      500   // anticipa el fin del bloque
// 13.5 s utiles = 1350 muestras = 67 ventanas completas de 20.
#define CALIB_MIN_VENTANAS          30   // menos de 6 s utiles: se rechaza

// Piso del denominador del z-score. Evita dividir por cero en un canal
// constante sin distorsionar los reales: la desviacion mas pequena
// observada en el dataset es 0.0118, seis ordenes por encima.
#define CALIB_EPSILON            1e-8f

// --- Senalizacion al usuario ---
// Una calibracion que falla en silencio y conserva la anterior es el
// peor modo de fallo: el usuario cree que recalibro y esta operando con
// las estadisticas de otra sesion, posiblemente con el brazalete en
// otra posicion. El fallo TIENE que ser perceptible sin consola.
//
// Canales disponibles con el hardware existente:
//   Serial   siempre, pero el usuario final no tiene terminal
//   LED      GPIO 2, integrado en la mayoria de placas ESP32 devkit.
//            CONFIRMAR contra la placa real; si no lo tiene, poner
//            PIN_LED en -1 y queda el canal haptico.
//   Haptico  patron breve con los servos. No requiere hardware nuevo y
//            se percibe con la protesis puesta, que es la situacion en
//            la que ocurre el fallo. Es el canal primario.
// No hay zumbador en el BOM, asi que el tono queda descartado.
#define PIN_LED                  2      // -1 para deshabilitar
#define SENAL_HAPTICA_HABILITADA 1

// Estado de la calibracion, para que la senal sea PERSISTENTE y no un
// aviso puntual que el usuario puede perderse.
#define CALIB_ESTADO_OK          0   // vigente y confirmada
#define CALIB_ESTADO_AUSENTE     1   // nunca se calibro
#define CALIB_ESTADO_NO_CONFIRM  2   // hubo un intento fallido: se sigue
                                     // operando con la anterior, pero el
                                     // aviso se repite hasta recalibrar

// Periodo del aviso persistente mientras el estado no sea OK.
#define CALIB_AVISO_PERIODO_MS   5000

// ======================== FSR: ADC INTERNO DEL ESP32 ========================
// Los FSR ya no comparten el ADS1115 con los LMG: van al ADC interno del
// ESP32, SOLO pines del ADC1 (32-36 y 39). El ADC2 no se usa: deja de
// funcionar mientras el WiFi esta activo.
//
// Cada lectura cuesta ~25 us por muestra en lugar de ~1.45 ms, asi que se
// leen LOS CINCO EN CADA CICLO de 10 ms (100 Hz por sensor, en cualquier
// gesto). Ya no hay escaneo rotativo ni plan B.
// Un FSR por yema, cinco. El sensor de palma (antes en el canal 10 del
// multiplexor) se DESCARTO del diseno: la ley de control frena servos
// individuales cuando la yema correspondiente supera su umbral, y no
// existe un servo de palma que frenar.
#define NUM_FSR          5

#define PIN_FSR_PULGAR   32     // FSR402
#define PIN_FSR_INDICE   33     // FSR402
#define PIN_FSR_MEDIO    34     // DF9-40
#define PIN_FSR_ANULAR   35     // DF9-40
#define PIN_FSR_MENIQUE  36     // DF9-40

// Atenuacion de 11 dB: rango util de ~150 a ~2450 mV, el unico que
// contiene a la vez los umbrales (~400 mV) y las lecturas de mas fuerza.
// Un voltaje mayor no dana el pin: solo se lee como el maximo.
// (Se traduce a ADC_11db en feedback_fsr.cpp.)
#define FSR_ATENUACION_DB  11

// Muestras promediadas por lectura. El condensador de 100 nF en cada pin
// ya filtra el ruido; el promedio quita el del propio ADC del ESP32.
#define FSR_MUESTRAS       4
#define FSR_US_POR_MUESTRA 25   // estimado para el presupuesto; el autotest mide

// El FSR va de 3.3 V al punto medio, y del punto medio una resistencia
// fija a GND: V = FSR_VCC_MV * R_FIJA / (R_FIJA + R_FSR).
// 22 kohm (serie E24, 1%) en lugar de 10 kohm: sube el voltaje de un
// toque suave por encima de la zona ciega del ADC (<150 mV). A cambio,
// por encima de ~0.8 N el ADC pierde precision y hacia ~5 N satura. Si
// al calibrar los umbrales pasan de ~0.6 N, volver a 10-15 kohm.
#define FSR_VCC_MV         3300.0f
#define FSR_R_FIJA_OHM     22000.0f

// Los dedos que cierran en cada gesto, para frenar solo esos. De los
// angulos de control_servos.cpp:
//
//              Pulgar Indice Medio Anular Menique   dedos que cierran
//   Rest          0      0      0     0      0             0
//   Pinch       180    120      0     0      0             2
//   Tripod      180    150    120     0      0             3
//   Power       180    170    170   150    140             5
//   Extension     0      0      0     0      0             0
//
// Bitmap de dedos que cierran, indexado por gesto. Bit i = servo i.
#define FSR_ACTIVOS_REST        0x00
#define FSR_ACTIVOS_PINCH       0x03   // pulgar + indice
#define FSR_ACTIVOS_TRIPOD      0x07   // pulgar + indice + medio
#define FSR_ACTIVOS_POWER       0x1F   // los cinco
#define FSR_ACTIVOS_EXTENSION   0x00

// ======================== UMBRALES FSR ========================
// Umbral de presion para detener el servo (lazo cerrado), en mV en el
// pin del ADC. CALIBRAR CON LOS FSR REALES: estos valores son la misma
// FUERZA que los umbrales anteriores, recalculada para el divisor nuevo.
//
//   Umbral anterior (10 kohm)  ->  R del FSR  ->  umbral nuevo (22 kohm)
//   200 mV                     ->  155 kohm   ->  410 mV
//   180 mV                     ->  173 kohm   ->  372 mV
//
//   Formula: V = FSR_VCC_MV * FSR_R_FIJA_OHM / (FSR_R_FIJA_OHM + R_FSR)
//
// Esa fuerza es un toque muy ligero (~0.04 N en la curva tipica del
// FSR402, por debajo de su rango especificado de 0.2-20 N). Los DF9-40 no
// tienen curva fiable publicada: calibrarlos por separado.
#define UMBRAL_FSR_PULGAR   410.0f
#define UMBRAL_FSR_INDICE   410.0f
#define UMBRAL_FSR_MEDIO    372.0f
#define UMBRAL_FSR_ANULAR   372.0f
#define UMBRAL_FSR_MENIQUE  372.0f

// ======================== GESTOS ========================
enum Gesto : uint8_t {
    GESTO_REST      = 0,
    GESTO_PINCH     = 1,
    GESTO_TRIPOD    = 2,
    GESTO_POWER     = 3,
    GESTO_EXTENSION = 4,
};

#endif
