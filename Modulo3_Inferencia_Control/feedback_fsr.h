/*
 * feedback_fsr.h - Lazo de realimentacion de fuerza con FSR
 *
 * QUE HACE:
 *   Lee los FSR de las yemas con el ADC INTERNO del ESP32, guarda el
 *   ultimo valor de cada uno y decide que servos deben frenarse.
 *
 * LECTURA (desde FIRMWARE_VERSION M3-2026.09.24):
 *   Los FSR ya no pasan por el ADS1115, que queda solo para los canales
 *   opticos. Van a pines del ADC1 (config.h, PIN_FSR_*), con atenuacion
 *   de 11 dB y analogReadMilliVolts(), que aplica la calibracion de
 *   fabrica grabada en el chip. Cada lectura promedia FSR_MUESTRAS
 *   conversiones.
 *
 *   Cada muestra cuesta ~25 us, asi que se leen LOS CINCO EN CADA CICLO
 *   de 10 ms: 100 Hz por sensor en cualquier gesto. El escaneo rotativo
 *   anterior (un FSR por ciclo, 20 Hz por sensor en Power) ya no hace
 *   falta.
 *
 * POR QUE BASTA:
 *   El sobrecierre es la velocidad de la rampa por la latencia de
 *   deteccion. Con 180 grados/s y ~12 ms (un ciclo + el filtro RC del
 *   divisor) son ~2.2 grados en cualquier gesto.
 *
 * DIAGNOSTICO:
 *   Se guarda el instante de la ultima lectura de cada sensor para poder
 *   reportar la tasa efectiva real, en vez de suponerla.
 */

#ifndef FEEDBACK_FSR_H
#define FEEDBACK_FSR_H

#include <Arduino.h>
#include "config.h"

class FeedbackFSR {
public:
    FeedbackFSR();

    // Configura resolucion y atenuacion del ADC en los pines de los FSR.
    void begin();

    // Pin del ADC1 correspondiente al FSR de cada dedo.
    static uint8_t pinDe(uint8_t dedo);

    // Bitmap de dedos que cierran en un gesto dado.
    static uint8_t dedosActivos(uint8_t gesto_id);

    // Lee un FSR (promedio de FSR_MUESTRAS). En mV en el pin del ADC.
    static float leerMv(uint8_t dedo);

    // Lee los cinco FSR y registra sus valores.
    void leerTodos(unsigned long ahora_us);

    // Registra la lectura de un sensor.
    void actualizar(uint8_t dedo, float valor_mv, unsigned long ahora_us);

    // Bitmap de servos cuyo umbral se ha superado. Solo considera los
    // sensores efectivamente leidos desde el ultimo gesto: un valor
    // rancio no debe frenar un dedo que acaba de empezar a cerrarse.
    uint8_t verificarUmbrales(uint8_t dedos_activos) const;

    // Invalida las lecturas al cambiar de gesto.
    void reiniciar();

    float getUltimoValor(uint8_t dedo) const;
    bool  esValido(uint8_t dedo) const;

    // Tasa efectiva medida de cada sensor, en Hz. 0 si no hay dos
    // lecturas todavia.
    float tasaEfectiva(uint8_t dedo) const;
    void  info() const;

    float umbrales[NUM_FSR];

private:
    float         _valores[NUM_FSR];
    bool          _valido[NUM_FSR];
    unsigned long _t_ultima[NUM_FSR];
    unsigned long _periodo_us[NUM_FSR];   // media movil del periodo
};

#endif
