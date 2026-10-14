/*
 * adc_lmg.h - Los dos ADC de los canales opticos LMG (ADS1115 o ADS1015)
 *
 * Este archivo es IDENTICO en Modulo1 y Modulo3, igual que optica_lmg:
 * la captura y la inferencia tienen que leer los sensores exactamente
 * igual.
 *
 * HARDWARE (desde FIRMWARE_VERSION 2026.09.24, sin multiplexor):
 *   ADC #1, 0x48, ADDR a GND:  AIN0 = LMG1, AIN1 = LMG2, AIN2 = LMG3
 *   ADC #2, 0x49, ADDR a VDD:  AIN0 = LMG4, AIN1 = LMG5
 *   Las entradas sin uso (AIN3 del #1, AIN2 y AIN3 del #2) van a GND.
 *   La salida OUT de cada modulo entra DIRECTA al ADC: ya no hay CD74HC4067
 *   en medio, ni su resistencia de encendido, ni su espera de asentamiento.
 *   El mapeo canal -> (ADC, entrada) esta en config.h (LMGn_ADS, LMGn_AIN).
 *
 * POR QUE DOS ADC Y NO LECTURA EN PARALELO:
 *   Solo puede haber un LED encendido a la vez (crosstalk optico), asi
 *   que las cinco conversiones LMG siguen siendo secuenciales aunque haya
 *   dos chips. Lo que se gana es sacar los FSR del ADS1115 (pasan al ADC
 *   interno del ESP32) y quitar la espera del multiplexor.
 *
 * GANANCIA: GAIN_TWO (+/-2.048 V) en todos los canales.
 *   Los dos ADC solo leen canales opticos. El OPT101 a 3.3 V garantiza
 *   2.0 V de excursion (tipico 2.15 V) y la autocalibracion limita el
 *   gesto maximo a 1900 mV, asi que el rango util cabe con 148 mV de
 *   holgura. Una entrada por encima de 2.048 V no dana el chip (el limite
 *   absoluto es VDD + 0.3 V); solo se lee como el maximo.
 *
 * RECORTE:
 *   Si una conversion llega al codigo maximo (32767 en el ADS1115, 2047 en
 *   el ADS1015) la entrada estaba en 2.048 V o mas: la lectura no es
 *   valida. Se cuenta por canal y se avisa por serie, como mucho una vez
 *   por segundo para no desbaratar el ciclo de 10 ms.
 *
 * SELECCION Y CONVERSION SEPARADAS:
 *   La trama oscura necesita DOS conversiones del mismo canal, una con el
 *   LED apagado y otra encendido. seleccionar() fija el canal y
 *   leerActual() lo convierte; el multiplexor interno del ADS se conmuta
 *   al inicio de cada conversion y no necesita espera propia.
 *
 * LECTURA CON Wire DIRECTO Y ESPERA FIJA (desde 2026.10.14):
 *   Antes se usaba readADC_SingleEnded() de Adafruit_ADS1X15, que por
 *   lectura hace: escribir la configuracion, escribir los dos umbrales
 *   (para el modo RDY del pin ALERT, que aqui no se cablea), sondear el
 *   bit OS del registro de configuracion hasta que termina y leer el
 *   resultado. Con el core 3.x cada transaccion I2C cuesta ~280 us
 *   (medido a 400 kHz), y eso dejaba la lectura en ~1910 us para una
 *   conversion de ~1125 us.
 *
 *   Ahora, por lectura:
 *     1. Escribir la configuracion con OS = 1 (inicia la conversion).
 *     2. Mientras convierte, apuntar el registro de puntero al de
 *        conversion (0x00). Va DENTRO de la espera: no cuesta tiempo.
 *     3. Esperar hasta ADC_ESPERA_US contados desde el fin de 1.
 *     4. Leer 2 bytes, una sola vez, sin sondear.
 *   Lo que se lee es lo mismo que antes: misma configuracion (MUX, PGA,
 *   modo single-shot, tasa). Lo unico distinto es el comparador, que se
 *   deja deshabilitado (COMP_QUE = 11, ALERT en alta impedancia) porque
 *   no se usa; no toca la conversion.
 *
 * EL RIESGO DE LA ESPERA FIJA, Y COMO SE CUBRE:
 *   Si la conversion no termino al leer, el registro de conversion
 *   devuelve la ANTERIOR de ese chip, que es OTRO canal. Seria crosstalk
 *   silencioso, peor que un ciclo lento. La hoja de datos admite +/-10%
 *   en la tasa, asi que una espera de 1200 us no cubre por si sola un
 *   ADS1115 en el extremo lento (1163 x 1.1 + 25 us de encendido =
 *   ~1305 us). Por eso begin() MIDE el tiempo real de conversion de cada
 *   chip, por el mismo camino de lectura, y si no deja al menos
 *   ADC_ESPERA_MARGEN_PCT de holgura sube la espera de ESE chip y lo
 *   avisa por serie. Nunca se lee un resultado a medias: en el peor caso
 *   el ciclo se alarga y el autotest lo reporta. verificarEspera() repite
 *   la medicion (el autotest 'T' la llama).
 */

#ifndef ADC_LMG_H
#define ADC_LMG_H

#include <Arduino.h>
#include <Wire.h>
#include "config.h"

class ADC_LMG {
public:
    ADC_LMG();

    // Inicializa los dos ADC y mide su tiempo de conversion. Devuelve
    // false si falta alguno; presente() dice cual.
    bool begin();
    bool presente(uint8_t adc) const { return adc < 2 && _presente[adc]; }

    // Fija el canal LMG (0..NUM_LMG-1) que convertira leerActual().
    void seleccionar(uint8_t canal);

    // Convierte el canal YA seleccionado. En mV.
    float leerActual();

    // seleccionar + leerActual. En mV.
    float leerCanal(uint8_t canal);

    // Mide otra vez la conversion de cada chip, ajusta la espera si hace
    // falta e imprime una linea [ADC] por chip.
    void verificarEspera();

    // Espera en uso y conversion medida (us) de cada ADC (0 o 1).
    uint16_t esperaUs(uint8_t adc) const { return adc < 2 ? _esperaUs[adc] : 0; }
    uint16_t conversionMedidaUs(uint8_t adc) const {
        return adc < 2 ? _convMedidaUs[adc] : 0;
    }

    // Conversiones que llegaron al maximo, por canal, desde el arranque o
    // desde el ultimo reiniciarRecortes().
    uint32_t recortes(uint8_t canal) const {
        return canal < NUM_LMG ? _recortes[canal] : 0;
    }
    void reiniciarRecortes();

    // Transacciones I2C que fallaron (NACK o bytes de menos).
    uint32_t erroresI2C() const { return _erroresI2C; }

private:
    bool     _iniciar(uint8_t k, uint8_t ain, unsigned long &t0);
    bool     _leer16(uint8_t k, uint16_t &valor);
    uint16_t _medirConversionUs(uint8_t k);

    bool          _presente[2];
    uint16_t      _esperaUs[2];
    uint16_t      _convMedidaUs[2];
    uint8_t       _canal;
    uint32_t      _recortes[NUM_LMG];
    uint32_t      _erroresI2C;
    unsigned long _tUltimoAviso;
    unsigned long _tUltimoAvisoI2C;
};

#endif
