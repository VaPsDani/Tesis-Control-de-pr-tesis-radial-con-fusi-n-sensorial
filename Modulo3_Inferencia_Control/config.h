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

// FSR que participan en el LAZO DE CONTROL: uno por yema, cinco.
//
// El de palma queda FUERA del escaneo, no porque el sensor sobre en el
// hardware sino porque la ley de control actual no puede usarlo: el
// lazo frena servos individuales cuando la yema correspondiente supera
// su umbral, y no existe un "servo de palma" que frenar. De hecho ya era
// codigo muerto: verificarUmbrales calculaba su bit 5 y el .ino solo
// actuaba sobre los bits 0..4.
//
// Podria servir para detectar el tipo de agarre o el deslizamiento,
// pero eso es otra ley de control. Incluirlo cuesta un 17% de tasa de
// refresco a los otros cinco (20 Hz -> 16.7 Hz).
#define NUM_FSR         5
#define NUM_FSR_HW      6   // los que existen fisicamente

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
// el producto de esta velocidad por la latencia de deteccion, que es
// SOLO el periodo de escaneo del FSR: la frenada ocurre en el mismo
// bucle de 10 ms en que se lee el sensor, no en el de inferencia.
// Hacerla esperar a una inferencia anadia hasta 20 ms, o sea 3.6
// grados mas de sobrecierre por nada.
//
// Peor caso barriendo todas las fases posibles del escaneo rotativo
// (simulado sobre la logica exacta de actualizarRampa, no medido en
// hardware):
//
//   Pinch  (2 dedos, 50 Hz)   20 ms ->  3.6 grados   (2.0% del rango)
//   Tripod (3 dedos, 33 Hz)   30 ms ->  7.2 grados   (4.0%)
//   Power  (5 dedos, 20 Hz)   50 ms -> 10.8 grados   (6.0%)
//   Plan B (Power a 10 Hz)   100 ms -> 18.0 grados  (10.0%)
//
// Referencia de lo que habia antes: sin rampa, el MG90S viajaba libre
// a ~600 grados/s hasta el tope comandado, o sea 90 grados de
// sobrecierre (50%) a cualquier tasa de lectura.
//
// El peor caso cae en Power, que es agarre de fuerza y donde el
// sobrecierre molesta menos.
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

// ======================== ESCANEO DESACOPLADO DEL ADC ========================
// El problema: LMG y FSR comparten un unico ADS1115 multiplexado. Leer
// 5 LMG + 6 FSR son 11 conversiones, ~15-18 ms, sobre un presupuesto de
// 10 ms. El ciclo no cerraba.
//
// La solucion no es acelerar el ADC, que ya esta a 860 SPS, sino
// reconocer que los dos grupos NO necesitan la misma tasa:
//
//   LMG   100 Hz obligatorio. Alimentan la ventana de 20 muestras del
//         modelo; a menos tasa la ventana deja de ser de 200 ms.
//   FSR   la fuerza de agarre es mecanicamente lenta. Un dedo tarda
//         cientos de ms en cerrarse sobre un objeto.
//
// Por eso cada ciclo de 10 ms lee los 5 LMG y UN SOLO FSR, rotando. El
// ciclo pasa de 11 canales a 6.
#define FSR_POR_CICLO   1

// PLAN B DEL PRESUPUESTO, escrito antes de necesitarlo.
//
// El presupuesto analitico del ciclo es ~8.8 ms sobre 10, un 12% de
// margen, y el overhead de I2C que lo sustenta esta estimado y no
// medido. Si en el bring-up el comando 'I' reporta que el ciclo no
// cabe, poner esta constante a 2 libera ~1.4 ms leyendo un FSR cada dos
// ciclos en vez de cada uno.
//
// Coste de la degradacion: la tasa por sensor se reduce a la mitad
// (Power pasa de 20 a 10 Hz) y el sobrecierre con la rampa de 180
// grados/s sube de 10.8 a 18.0 grados, un 10% del recorrido. Sigue
// siendo aceptable para un agarre de fuerza, y muy lejos de los 90
// grados que producia la version sin rampa.
//
// Que quede aqui y no haya que rediseniar nada en pleno bring-up es el
// motivo de escribirlo ahora.
#define FSR_CADA_N_CICLOS   1   // 2 = plan B degradado

// ESCANEO ADAPTATIVO: solo se rotan los FSR de los dedos que estan
// cerrando en el gesto actual. De los angulos de control_servos.cpp:
//
//              Pulgar Indice Medio Anular Menique   dedos que cierran
//   Rest          0      0      0     0      0             0
//   Pinch       180    120      0     0      0             2
//   Tripod      180    150    120     0      0             3
//   Power       180    170    170   150    140             5
//   Extension     0      0      0     0      0             0
//
// La tasa efectiva por FSR es 100 Hz / n_dedos_activos:
//   Pinch   2 dedos -> 50.0 Hz por FSR
//   Tripod  3 dedos -> 33.3 Hz por FSR
//   Power   5 dedos -> 20.0 Hz por FSR
//
// La tasa mas alta cae en Pinch, que es el agarre delicado, y la mas
// baja en Power, que es donde la fuerza se quiere alta. El reparto
// favorece justo donde importa.
//
// Bitmap de dedos que cierran, indexado por gesto. Bit i = servo i.
#define FSR_ACTIVOS_REST        0x00
#define FSR_ACTIVOS_PINCH       0x03   // pulgar + indice
#define FSR_ACTIVOS_TRIPOD      0x07   // pulgar + indice + medio
#define FSR_ACTIVOS_POWER       0x1F   // los cinco
#define FSR_ACTIVOS_EXTENSION   0x00

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
