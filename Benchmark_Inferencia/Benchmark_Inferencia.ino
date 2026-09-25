/*
 * Benchmark_Inferencia.ino - Tiempo de inferencia del modelo en el ESP32
 * =======================================================================
 * Protesis transradial - Fusion sensorial y Deep Learning
 *
 * SOLO MIDE. Sin sensores, sin I2C, sin servos: carga el modelo INT8, lo
 * ejecuta 100 veces sobre una ventana fija y imprime el tiempo medio, el
 * minimo y el maximo. Despues ejecuta una inferencia mas con el perfilador
 * de TFLite Micro para ver cuanto tarda cada tipo de operacion.
 *
 * ARCHIVOS:
 *   - resolver_modelo_lmg.h, reverse_v2_lmg.h, reverse_v2_lmg.cpp: COPIAS
 *     de Modulo3_Inferencia_Control. Tienen que ser identicos, para medir
 *     exactamente el mismo codigo que corre en la protesis.
 *   - modelo_gestos_tflite.h: copiar aqui el que genera convertir_tflite.py
 *     (el mismo que va en Modulo3). No se versiona.
 *
 * USO: placa "ESP32 Dev Module", subir y abrir el monitor serie a 115200.
 *      Enviar 'R' para repetir la medicion.
 *
 * DEPENDENCIA: Chirale_TensorFLowLite 2.0.0.
 */

#include <Chirale_TensorFlowLite.h>
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_profiler.h"
#include "tensorflow/lite/schema/schema_generated.h"
#include "resolver_modelo_lmg.h"
#include "modelo_gestos_tflite.h"

// Los mismos valores que Modulo3 (inferencia.h y config.h)
constexpr size_t kArena = 40 * 1024;
constexpr int kVentana = 20;
constexpr int kCanales = 8;
constexpr int kClases = 5;
constexpr int kRepeticiones = 100;
constexpr unsigned long kPeriodoMuestraUs = 10000;   // 100 Hz
constexpr unsigned long kLatenciaMaxUs = 150000;     // requisito: < 150 ms

alignas(16) static uint8_t arena[kArena];
alignas(16) static uint8_t arenaPerfil[kArena];

static ResolverModeloLMG resolver;
static tflite::MicroInterpreter *interp = nullptr;

// Ventana fija con valores del orden de un z-score (la entrada real llega
// normalizada por la calibracion). El tiempo no depende de los valores.
static void llenarEntrada(float *x) {
    for (int t = 0; t < kVentana; t++)
        for (int c = 0; c < kCanales; c++)
            x[t * kCanales + c] = 0.8f * sinf(0.3f * t + 0.7f * c) + 0.1f * c - 0.3f;
}

static void medir() {
    Serial.println();
    Serial.println("==================== MEDICION ====================");
    Serial.printf("CPU %u MHz, nucleo %d, heap libre %u B\n",
                  getCpuFrequencyMhz(), xPortGetCoreID(), ESP.getFreeHeap());
    Serial.printf("Modelo: %u B | arena usada: %u / %u B\n",
                  modelo_gestos_tflite_len, (unsigned)interp->arena_used_bytes(),
                  (unsigned)kArena);

    TfLiteTensor *in = interp->input(0);
    TfLiteTensor *out = interp->output(0);

    // Primera inferencia aparte (calentamiento de caches). Reset() pone a
    // cero el estado de la LSTM, como hace predecir() en Modulo3: entra en
    // el tiempo medido porque forma parte de cada inferencia.
    llenarEntrada(in->data.f);
    unsigned long t0 = micros();
    interp->Reset();
    if (interp->Invoke() != kTfLiteOk) { Serial.println("ERROR: Invoke fallo"); return; }
    const unsigned long primera = micros() - t0;

    unsigned long suma = 0, maximo = 0, minimo = ~0UL;
    int clase = -1;
    for (int k = 0; k < kRepeticiones; k++) {
        llenarEntrada(in->data.f);          // incluye la copia de la entrada, como predecir()
        t0 = micros();
        interp->Reset();
        interp->Invoke();
        int cmax = 0;
        for (int i = 1; i < kClases; i++)
            if (out->data.f[i] > out->data.f[cmax]) cmax = i;
        const unsigned long dt = micros() - t0;
        clase = cmax;
        suma += dt;
        if (dt > maximo) maximo = dt;
        if (dt < minimo) minimo = dt;
    }
    const float medio = suma / (float)kRepeticiones;
    Serial.printf("Primera inferencia: %.2f ms\n", primera / 1000.0f);
    Serial.printf("%d inferencias: MEDIO %.2f ms | MIN %.2f ms | MAX %.2f ms\n",
                  kRepeticiones, medio / 1000.0f, minimo / 1000.0f, maximo / 1000.0f);
    Serial.printf("Clase de la ventana de prueba: %d (solo comprueba que corre)\n", clase);

    // Propuesta de intervalo entre inferencias, en multiplos del periodo de
    // muestreo: el maximo medido mas un 20 % de margen.
    const unsigned long necesario = (unsigned long)(maximo * 1.2f);
    const unsigned long muestras = (necesario + kPeriodoMuestraUs - 1) / kPeriodoMuestraUs;
    const unsigned long intervalo = muestras * kPeriodoMuestraUs;
    Serial.printf("Intervalo minimo entre inferencias: %lu ms (cada %lu muestras)\n",
                  intervalo / 1000, muestras);
    Serial.printf("Latencia peor caso ~ intervalo + inferencia = %.1f ms (%s 150 ms)\n",
                  (intervalo + maximo) / 1000.0f,
                  intervalo + maximo < kLatenciaMaxUs ? "cumple" : "NO cumple");

    // Perfil por tipo de operacion, en otra instancia (el perfilador anade
    // un poco de tiempo y no debe contaminar la medicion de arriba)
    tflite::MicroProfiler perfil;
    tflite::MicroInterpreter conPerfil(tflite::GetModel(modelo_gestos_tflite), resolver,
                                       arenaPerfil, kArena, nullptr, &perfil);
    if (conPerfil.AllocateTensors() == kTfLiteOk) {
        llenarEntrada(conPerfil.input(0)->data.f);
        conPerfil.Reset();
        conPerfil.Invoke();
        Serial.println("Tiempo por tipo de operacion (microsegundos):");
        perfil.LogTicksPerTagCsv();
    }
    Serial.println("==================================================");
    Serial.println("Envie 'R' para repetir.");
}

void setup() {
    Serial.begin(115200);
    delay(1500);
    Serial.println("\n[BENCHMARK] Inferencia CNN-BiLSTM-Attention INT8 (TFLite Micro)");

    const tflite::Model *modelo = tflite::GetModel(modelo_gestos_tflite);
    if (modelo->version() != TFLITE_SCHEMA_VERSION) {
        Serial.println("ERROR: version del esquema del modelo");
        return;
    }
    static tflite::MicroInterpreter interprete(modelo, resolver, arena, kArena);
    interp = &interprete;
    if (interp->AllocateTensors() != kTfLiteOk) {
        Serial.println("ERROR: AllocateTensors fallo (arena pequena u operacion no soportada)");
        interp = nullptr;
        return;
    }
    medir();
}

void loop() {
    if (interp && Serial.available() && Serial.read() == 'R') medir();
    delay(10);
}
