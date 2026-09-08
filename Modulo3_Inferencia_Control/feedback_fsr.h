/*
 * feedback_fsr.h - Lazo de realimentacion de fuerza con FSR
 *
 * QUE HACE:
 *   Mantiene el ultimo valor de cada FSR de yema y decide que servos
 *   deben frenarse. La LECTURA fisica ocurre en el bucle principal,
 *   porque el ADS1115 se comparte con los canales LMG.
 *
 * ESCANEO ROTATIVO:
 *   Cada ciclo de 10 ms se lee UN solo FSR, no los cinco. El escaneo
 *   rota entre los dedos que estan cerrando en el gesto actual, asi que
 *   la tasa efectiva por sensor es 100 Hz / n_dedos_activos: 50 Hz en
 *   Pinch, 33 Hz en Tripod y 20 Hz en Power.
 *
 *   Eso baja el ciclo de 11 canales de ADC a 6 y hace que quepa en los
 *   10 ms, que es lo que antes no ocurria.
 *
 * POR QUE BASTA CON ESAS TASAS:
 *   La fuerza de agarre es mecanicamente lenta; un dedo tarda cientos de
 *   ms en cerrarse sobre un objeto. Lo que determina el sobrecierre no
 *   es la tasa de lectura sola, sino su producto por la velocidad a la
 *   que avanza el dedo. Con los servos moviendose a tope (~600 grados/s
 *   en un MG90S) ninguna tasa razonable bastaria; con una rampa
 *   controlada de 180 grados/s, 20 Hz dejan el sobrecierre en 9 grados.
 *
 *   Ver la nota sobre frenarServo() en control_servos.h: mientras el
 *   freno no actue sobre una rampa, el sobrecierre no depende de esta
 *   tasa en absoluto.
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

    // Canal del MUX correspondiente al FSR de cada dedo.
    static uint8_t canalDe(uint8_t dedo);

    // Bitmap de dedos que cierran en un gesto dado.
    static uint8_t dedosActivos(uint8_t gesto_id);

    // Registra la lectura de UN sensor (escaneo rotativo).
    void actualizar(uint8_t dedo, float valor_mv, unsigned long ahora);

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
