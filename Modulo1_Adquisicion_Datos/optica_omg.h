/*
 * optica_omg.h - Lectura de los 8 modulos QRE1113 con el ADC interno
 *
 * Cada modulo: LED IR y fototransistor en el mismo encapsulado. OUT es el
 * colector, con 47 kohm a VCC: mas luz da menos tension. La trama de cada
 * ciclo (config.h) lee primero con todos los LED apagados (V_apag) y
 * despues con los LED encendidos (V_enc). El firmware entrega
 *   v[k]   = V_apag[k] - V_enc[k]   (mV, positivo y mayor con mas luz)
 *   amb[k] = V_apag[k]              (luz ambiente que llega al sensor)
 *
 * T_ON_US y T_OFF_US se guardan en NVS. La capacidad de salida de los LED
 * no: 'D' la cambia solo hasta el siguiente reinicio.
 */

#ifndef OPTICA_OMG_H
#define OPTICA_OMG_H

#include <Arduino.h>
#include "config.h"

class OpticaOMG {
public:
    OpticaOMG();

    // ADC (12 bits, 11 dB en cada pin), LED apagados con su capacidad de
    // salida, y T_ON_US / T_OFF_US de la NVS.
    void begin();

    // Pasos 1 y 2 de la trama: V_apag y V_enc de los 8 canales, en mV.
    void medir(float vApag[NUM_OPT], float vEnc[NUM_OPT]);

    // Promedio de N_MUESTRAS lecturas calibradas del canal k, en mV.
    float leerMv(uint8_t k);

    void encender(uint8_t k);
    void apagar(uint8_t k);
    void encenderTodos();
    void apagarTodos();

    // Comandos de configuracion. Devuelven false si el valor no vale.
    bool fijarTOn(uint32_t us);      // 'E', guarda en NVS
    bool fijarTOff(uint32_t us);     // 'O', guarda en NVS
    bool fijarDriveCap(uint8_t cap); // 'D', 0 a 3, sin guardar

    uint32_t tOnUs() const  { return _tOn; }
    uint32_t tOffUs() const { return _tOff; }
    uint8_t  driveCap() const { return _cap; }

    // Lineas [OPTICA_*] que la app de captura guarda en el JSON.
    void imprimirConfig() const;
    // Tabla de pines legible, para confirmarla contra el cableado.
    void imprimirPines() const;

    // 'C': curva de asentamiento por canal, al encender y al apagar su
    // LED. Imprime t90, t95 y t99 y sugiere T_ON_US y T_OFF_US.
    void curvaAsentamiento();
    // 'X': diafonia. Por canal k, su LED apagado y los otros 7 encendidos,
    // frente a todos apagados.
    void diafonia();

private:
    uint32_t _tOn, _tOff;
    uint8_t  _cap;

    void _aplicarDriveCap();
    void _guardarNVS();
    void _cargarNVS();
};

#endif
