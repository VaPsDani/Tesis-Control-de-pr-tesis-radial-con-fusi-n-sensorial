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
 */

#ifndef ADC_LMG_H
#define ADC_LMG_H

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_ADS1X15.h>
#include "config.h"

class ADC_LMG {
public:
    ADC_LMG();

    // Inicializa los dos ADC. Devuelve false si falta alguno; presente()
    // dice cual.
    bool begin();
    bool presente(uint8_t adc) const { return adc < 2 && _presente[adc]; }

    // Fija el canal LMG (0..NUM_LMG-1) que convertira leerActual().
    void seleccionar(uint8_t canal);

    // Convierte el canal YA seleccionado. En mV.
    float leerActual();

    // seleccionar + leerActual. En mV.
    float leerCanal(uint8_t canal);

    // Conversiones que llegaron al maximo, por canal, desde el arranque o
    // desde el ultimo reiniciarRecortes().
    uint32_t recortes(uint8_t canal) const {
        return canal < NUM_LMG ? _recortes[canal] : 0;
    }
    void reiniciarRecortes();

private:
#if ADC_MODELO == ADC_ADS1015
    Adafruit_ADS1015 _ads[2];
#else
    Adafruit_ADS1115 _ads[2];
#endif
    bool          _presente[2];
    uint8_t       _canal;
    uint32_t      _recortes[NUM_LMG];
    unsigned long _tUltimoAviso;
};

#endif
