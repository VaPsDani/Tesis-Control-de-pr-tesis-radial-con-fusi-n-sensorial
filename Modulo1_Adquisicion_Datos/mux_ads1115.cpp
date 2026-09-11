#include "mux_ads1115.h"

MUX_ADS1115::MUX_ADS1115() {}

bool MUX_ADS1115::begin() {
    // Configurar pines del MUX como salidas
    pinMode(PIN_MUX_S0, OUTPUT);
    pinMode(PIN_MUX_S1, OUTPUT);
    pinMode(PIN_MUX_S2, OUTPUT);
    pinMode(PIN_MUX_S3, OUTPUT);

    // ORDEN CRITICO: begin() antes que cualquier configuracion.
    // setGain() y setDataRate() escriben sobre el estado interno del
    // objeto y lo transmiten en la siguiente conversion; llamarlos antes
    // de begin() opera sobre un driver todavia sin inicializar.
    if (!_ads.begin(ADS_ADDR)) {
        return false;
    }

    // GAIN_ONE  -> +/-4.096 V, 0.125 mV por LSB  (ver ADS_GAIN_MV)
    // GAIN_TWOTHIRDS -> +/-6.144 V, 0.1875 mV por LSB
    _ads.setGain(GAIN_ONE);

    // TASA DE CONVERSION - imprescindible para llegar a 100 Hz.
    //
    // La libreria arranca por defecto a 128 SPS, o sea 7.8 ms por
    // conversion. Con 5 canales eso son ~39 ms por ciclo y el sistema
    // corre a ~25 Hz, no a los 100 Hz que asume el resto del pipeline
    // (ventana de 200 ms = 20 muestras, stride de 20 ms = 2 muestras).
    //
    // A 860 SPS cada conversion tarda 1.163 ms:
    //   5 canales x (1.163 ms + ~0.5 ms de overhead I2C) = ~8.3 ms
    //   lectura del MPU6050 (14 bytes a 400 kHz)         = ~0.4 ms
    //   TOTAL por ciclo                                  = ~8.7 ms
    // Entra en el presupuesto de 10 ms, con ~13% de margen.
    //
    // Contrapartida honesta: a 860 SPS el ruido RMS del ADS1115 es
    // mayor que a 128 SPS. Es el precio inevitable de sostener 100 Hz
    // con un unico ADC multiplexado.
    _ads.setDataRate(RATE_ADS1115_860SPS);

    return true;
}

float MUX_ADS1115::leerCanal(uint8_t canal) {
    _seleccionarCanal(canal);

    // Asentamiento del MUX antes de convertir.
    //
    // El t_on del CD74HC4067 es de ~1 us, pero lo que manda no es la
    // conmutacion del MUX sino la carga del capacitor de muestreo del
    // ADS1115 a traves de la Ron del multiplexor (~70 ohm tipico) mas
    // la impedancia de salida del OPT101. Los 5 us anteriores eran
    // optimistas: con una constante RC de ese orden se necesitan varias
    // decenas de microsegundos para asentar dentro de 1 LSB, o de lo
    // contrario aparece diafonia entre canales adyacentes.
    //
    // 50 us cuestan 250 us por ciclo completo (5 canales), un 2.5% del
    // presupuesto de 10 ms. Barato comparado con medir el canal vecino.
    delayMicroseconds(50);

    // Leer el ADS1115 (canal A0 single-ended)
    int16_t raw = _ads.readADC_SingleEnded(0);

    // Convertir a mV usando la constante unica de config.h
    return raw * ADS_GAIN_MV;
}

void MUX_ADS1115::_seleccionarCanal(uint8_t canal) {
    digitalWrite(PIN_MUX_S0, (canal >> 0) & 1);
    digitalWrite(PIN_MUX_S1, (canal >> 1) & 1);
    digitalWrite(PIN_MUX_S2, (canal >> 2) & 1);
    digitalWrite(PIN_MUX_S3, (canal >> 3) & 1);
}
