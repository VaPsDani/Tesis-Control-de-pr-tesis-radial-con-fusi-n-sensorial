/*
 * feedback_fsr.h - Lazo cerrado con sensores FSR
 *
 * LOGICA DE RETROALIMENTACION:
 *   Mientras la protesis esta ejecutando un gesto de agarre (Pinch,
 *   Tripod, Power), se leen continuamente los 6 sensores FSR a traves
 *   del MUX + ADS1115.
 *
 *   Cada FSR corresponde a un dedo:
 *     FSR[0] → Pulgar  (FSR402)
 *     FSR[1] → Indice  (FSR402)
 *     FSR[2] → Medio   (DF9-40)
 *     FSR[3] → Anular  (DF9-40)
 *     FSR[4] → Menique (DF9-40)
 *     FSR[5] → Palma   (DF9-40)
 *
 *   Si la lectura del FSR supera el UMBRAL_FSR_*, se frena el servo
 *   correspondiente. Esto evita que la protesis aplaste el objeto
 *   mientras mantiene una presion constante.
 *
 *   Los valores de umbral se calibran experimentalmente y dependen
 *   de la sensibilidad de cada FSR y su ubicacion.
 *
 * TIMING:
 *   - La lectura de 6 FSR + 5 LMG toma ~16 ms
 *   - El lazo de feedback corre en cada ciclo de 20 ms
 */

#ifndef FEEDBACK_FSR_H
#define FEEDBACK_FSR_H

#include <Arduino.h>
#include "config.h"
#include "mux_ads1115.h"

class FeedbackFSR {
public:
    FeedbackFSR();

    // Lee todos los FSR, retorna true si alguno supera el umbral
    bool leerFSR(float valores[6]);

    // Verifica umbrales y retorna un bitmap de servos a frenar
    // bit 0 = pulgar, bit 1 = indice, ..., bit 5 = palma
    // Retorna un bitmap de 6 bits (solo 5 servos, la palma no tiene servo directo)
    uint8_t verificarUmbrales(const float valores[6]);

    // Obtiene el ultimo valor de un FSR especifico
    float getUltimoValor(uint8_t idx) const;

    // Array de umbrales para cada FSR (configurable en runtime)
    float umbrales[6];

private:
    float _ultimos_valores[6];

    // Canales del MUX para cada FSR
    const uint8_t _canales_fsr[6] = {
        CH_FSR_PULGAR,
        CH_FSR_INDICE,
        CH_FSR_MEDIO,
        CH_FSR_ANULAR,
        CH_FSR_MENIQUE,
        CH_FSR_PALMA,
    };
};

#endif
