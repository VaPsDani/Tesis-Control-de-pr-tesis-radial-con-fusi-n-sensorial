/*
 * calibracion.h - Normalizacion por sujeto en el dispositivo
 *
 * POR QUE EXISTE ESTE MODULO:
 *   Los experimentos sobre NinaPro DB5 midieron que normalizar cada
 *   sujeto con sus propias estadisticas sube la exactitud inter-sujeto
 *   de 56.99% a 70.00% (+13.01 puntos), y elimina el colapso en el que
 *   dos de los cinco pliegues devolvian pesos practicamente sin
 *   entrenar. La normalizacion global, estimada con los sujetos de
 *   entrenamiento, solo aportaba 1.58 puntos y aumentaba la dispersion.
 *
 *   La razon es que la escala varia mucho entre personas: sobre DB5, la
 *   desviacion estandar de un mismo canal cambia hasta 4.9x de un
 *   sujeto a otro, mientras las medias coinciden. El desajuste es de
 *   ESCALA, no de offset.
 *
 *   Si el modelo se entrena con datos normalizados por sujeto, el
 *   firmware TIENE que normalizar igual o le entregara senales en otra
 *   escala. De ahi este modulo.
 *
 * POR QUE NO ES FUGA DE DATOS:
 *   Calibrar con los propios datos del usuario no usa etiquetas, no
 *   cruza informacion entre personas y reproduce exactamente lo que
 *   ocurre al ponerse la protesis. Un modelo que exigiera conocer de
 *   antemano la escala del usuario no seria desplegable.
 *
 * ESTRATEGIA DE CALCULO:
 *   Una sola pasada acumulando suma y suma de cuadrados por canal:
 *     media = S1 / n
 *     var   = S2 / n - media^2
 *   No hace falta guardar las muestras ni recorrerlas dos veces. Se
 *   acumula en double porque a 100 Hz durante 15 s son 1500 muestras y
 *   las sumas de cuadrados crecen rapido; en float se perderia
 *   precision en los canales LMG, que estan en milivoltios.
 *
 *   Al cerrar se precalcula inv_sd = 1/(sd + EPS) para que normalizar
 *   una ventana sea una multiplicacion y no una division.
 *
 * SEGMENTACION, IGUAL QUE EN EL PIPELINE:
 *   preprocesamiento.py no deja que una ventana cruce el limite de un
 *   bloque, porque mezclaria dos regimenes de senal. Aqui se aplica el
 *   mismo criterio: las muestras se pliegan a los acumuladores en
 *   bloques de TAMANO_VENTANA completos, de modo que toda estadistica
 *   procede de ventanas integras contenidas en el bloque de
 *   calibracion. La ventana parcial del final se descarta, y si se
 *   detecta un hueco temporal la calibracion se aborta en vez de
 *   promediar dos tramos discontinuos.
 */

#ifndef CALIBRACION_H
#define CALIBRACION_H

#include <Arduino.h>
#include "config.h"

class Calibrador {
public:
    Calibrador();

    // Carga la calibracion guardada en NVS. Devuelve true si habia una.
    bool begin();
    bool tieneCalibracion() const { return _calibrado; }

    // --- Captura ---
    void iniciar(unsigned long ahora);
    bool capturando() const { return _capturando; }

    // Entrega una muestra al calibrador. Devuelve true mientras la
    // captura sigue en curso, false cuando ha terminado (por haber
    // completado el bloque o por haberse abortado).
    bool acumular(const float muestra[NUM_FEATURES], unsigned long ahora);

    // Cierra la captura, calcula media y desviacion y las persiste.
    // Devuelve false si no se reunieron ventanas completas suficientes.
    bool finalizar();
    void abortar();

    // --- Uso ---
    // Normaliza la ventana in situ. Si no hay calibracion, no toca nada:
    // es preferible inferir sin normalizar que aplicar una escala
    // inventada.
    void normalizar(float ventana[TAMANO_VENTANA][NUM_FEATURES]);

    void borrar();
    void info() const;

    // --- Estado y senalizacion ---
    // El estado NO vuelve a OK por si solo: un intento fallido deja
    // CALIB_ESTADO_NO_CONFIRM hasta que una calibracion termine bien.
    // Asi el usuario no puede creer que recalibro cuando no lo hizo.
    uint8_t estado() const { return _estado; }
    bool    requiereAviso() const { return _estado != CALIB_ESTADO_OK; }

    // Llamar en cada iteracion del loop. Repite el aviso mientras el
    // estado no sea OK, sin bloquear.
    void atenderAvisos(unsigned long ahora);

    // Callback para el patron haptico. Se inyecta desde el .ino para no
    // acoplar el calibrador con el control de servos.
    typedef void (*FnSenalHaptica)(uint8_t repeticiones);
    void registrarSenalHaptica(FnSenalHaptica fn) { _senalHaptica = fn; }

    // --- Instrumentacion de latencia (ver C3) ---
    unsigned long ultimaNormalizacionUs() const { return _ultimaUs; }
    unsigned long normalizacionAcumuladaUs() const { return _acumUs; }
    uint32_t      normalizacionesRealizadas() const { return _nNorm; }

private:
    // Acumuladores de la pasada unica
    double   _s1[NUM_FEATURES];
    double   _s2[NUM_FEATURES];
    uint32_t _nMuestras;

    // Staging de una ventana completa: solo se pliega a los
    // acumuladores cuando se llena, para que ninguna estadistica
    // provenga de una ventana que cruza el limite del bloque.
    float    _staging[TAMANO_VENTANA][NUM_FEATURES];
    uint8_t  _enStaging;
    uint16_t _ventanasCompletas;

    // Parametros resultantes
    float _media[NUM_FEATURES];
    float _sd[NUM_FEATURES];
    float _invSd[NUM_FEATURES];
    bool  _calibrado;

    // Control de la captura
    bool          _capturando;
    unsigned long _tInicio;
    unsigned long _tUltimaMuestra;

    // Instrumentacion
    unsigned long _ultimaUs;
    unsigned long _acumUs;
    uint32_t      _nNorm;

    // Senalizacion
    uint8_t        _estado;
    unsigned long  _tUltimoAviso;
    FnSenalHaptica _senalHaptica;

    void _senalizar(uint8_t nDestellos);
    void _reiniciarAcumuladores();
    void _plegarStaging();
    bool _guardarNVS();
    bool _cargarNVS();
};

#endif
