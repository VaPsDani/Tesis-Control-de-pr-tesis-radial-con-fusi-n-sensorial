/*
 * optica_lmg.h - Control individual de los LED, trama oscura y
 *                autocalibracion de ganancia de los 5 modulos LMG
 *
 * Este archivo es IDENTICO en Modulo1 y Modulo3: la captura y la
 * inferencia tienen que ver la senal optica exactamente igual, o el
 * modelo se entrenaria con una senal y se desplegaria con otra.
 *
 * TRES FUNCIONES:
 *
 * 1. UN LED A LA VEZ (Tarea 3.a)
 *    Solo se enciende el LED del canal que se esta leyendo. Con todos
 *    encendidos, la luz de un modulo llega al fotodiodo del vecino a
 *    traves del tejido: crosstalk optico.
 *
 * 2. TRAMA OSCURA (Tarea 3.b)
 *    Por canal: todos apagados -> asentar -> leer D -> encender el LED
 *    del canal -> asentar -> leer L -> apagar. Valor = L - D.
 *
 *    QUE CANCELA Y QUE NO:
 *      Cancela la COMPONENTE CONTINUA de la luz ambiental (sol, nivel
 *      medio de una lampara), que es la mayor parte de su efecto.
 *
 *      NO cancela el parpadeo de 120 Hz de las lamparas (red de 60 Hz
 *      en Peru). Para cancelarlo, D y L tendrian que tomarse dentro de
 *      ~100 us; pero cada una es una conversion completa del ADC, asi
 *      que quedan separadas por conversion + asentamiento. El residuo
 *      del parpadeo tras restar es 2*|sin(pi*120*dt)|:
 *
 *        dt = 100 us  (lo deseable)         ->   7.5 %
 *        dt ~ 0.7 ms  (ADS1015 a 3300 SPS)  ->  55   %
 *        dt ~ 1.6 ms  (ADS1115 a 860 SPS)   -> 113   %, peor que no restar
 *
 *      Ningun ADC detras de I2C a estas tasas llega a 100 us. El
 *      parpadeo residual se pliega: a 100 Hz de muestreo, los 120 Hz
 *      caen en 20 Hz, fuera de la banda del gesto (<5 Hz) y justo en un
 *      cero de la media de 200 ms. A 60 Hz de muestreo caerian en DC.
 *
 * 3. AUTOCALIBRACION DE GANANCIA (Tarea 3.d)
 *    Ajusta por PWM la corriente de cada LED para que el reposo quede en
 *    ~35% del fondo de escala y el gesto maximo no recorte. Guarda el
 *    valor de reposo por canal, que es el S-barra-r del indice de
 *    rendimiento.
 *
 *    Si la dispersion entre canales es baja, NO ajusta: deja la corriente
 *    fija y la diferencia entre canales la absorbe la normalizacion por
 *    canal en software. Ajustar sin necesidad solo introduce otra fuente
 *    de variacion entre sesiones.
 *
 *    PWM a 100 kHz: muy por encima de los 14 kHz de ancho de banda del
 *    OPT101, que lo promedia, y ademas cada conversion del ADC integra
 *    decenas de ciclos.
 */

#ifndef OPTICA_LMG_H
#define OPTICA_LMG_H

#include <Arduino.h>
#include "config.h"
#include "mux_ads1115.h"

class OpticaLMG {
public:
    explicit OpticaLMG(MUX_ADS1115 &adc);

    // Configura el PWM de los 5 LED (apagados) y carga la calibracion
    // guardada. Devuelve false si no pudo asignar un canal PWM.
    bool begin();

    // Lectura de un canal LMG (0..NUM_LMG-1), en mV, con trama oscura
    // si esta habilitada. Deja todos los LED apagados al salir.
    float leerCanal(uint8_t idx);
    void  leerTodos(float destino[NUM_LMG]);

    void apagarTodos();

    // Autocalibracion de ganancia. Bloqueante, ~10 s. El usuario debe
    // estar en reposo. Si verificarGestoMax, pide ademas una contraccion
    // maxima para comprobar que nada recorta.
    bool autocalibrar(bool verificarGestoMax);

    // True si la ultima autocalibracion cambio alguna corriente mas de
    // un 5%. En ese caso las estadisticas de normalizacion por sujeto
    // guardadas quedan obsoletas: se calcularon con otra ganancia.
    bool cambioGanancia() const { return _cambio; }

    float    reposoMedio(uint8_t idx) const { return _reposo[idx]; }   // S-r
    float    ultimaOscura(uint8_t idx) const { return _oscura[idx]; }  // D
    uint16_t duty(uint8_t idx) const { return _duty[idx]; }
    void     info() const;

private:
    MUX_ADS1115 &_adc;
    uint16_t _duty[NUM_LMG];
    float    _reposo[NUM_LMG];
    float    _oscura[NUM_LMG];
    uint8_t  _debil;          // bitmap: canal que ni al maximo alcanza
    bool     _cambio;

    void  _encender(uint8_t idx);
    void  _apagar(uint8_t idx);
    float _medir(uint8_t idx, uint16_t n);
    uint16_t _buscarDuty(uint8_t idx, float objetivo_mv);
    bool  _guardarNVS();
    bool  _cargarNVS();
};

#endif
