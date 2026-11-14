# Archivo de la etapa LMG

El 2026-11-13, de acuerdo con el asesor, el proyecto cambió de sensor y de
alcance:

- **Sensor:** del OPT101 con LED aparte (LMG, leído con dos ADS1115) al
  QRE1113GR, que trae LED y fototransistor en el mismo encapsulado (OMG,
  optomiografía, leído con el ADC interno del ESP32). De 5 a 8 canales.
- **Alcance:** todo se evalúa fuera de línea. Sin despliegue en el ESP32,
  sin mano impresa, servos, PCA9685, FSR, prueba en línea ni medición de
  latencia. Sin banco de variantes de módulo ni índice I. La cuantización
  INT8 se conserva solo para medir fuera de línea cuánto se degrada el
  modelo.

Lo que salió del alcance se movió aquí con `git mv`, sin borrar nada, para
que su historial siga disponible.

**Para volver a la versión LMG completa:**

```bash
git checkout lmg-final-2026-11-13
```

## Qué hay aquí

| Carpeta | Qué era |
|---|---|
| `Modulo3_Inferencia_Control_LMG/` | Firmware de inferencia y control: CNN-BiLSTM en TFLite Micro, servos con PCA9685, frenado por FSR, latencia, calibración de FSR |
| `Modulo2_Pipeline_DL/banco_modulos/` | Banco de las 6 variantes del módulo LMG e índice I |
| `Modulo2_Pipeline_DL/produccion/` | `calibrar_fsr.py`, `prueba_en_linea.py` y `planilla_agarres.csv` |
| `Modulo2_Pipeline_DL/tests_archivados/` | Tests de lo anterior. Pytest no los colecciona (`conftest.py`) |
| `Modulo2_Pipeline_DL/experimentos/optica_espaciador/` | Índice de rendimiento del espaciador de silicona |
| `claude/` | Nota de diseño del módulo LMG y viabilidad de TFLite Micro |

Los drivers `adc_lmg` y `optica_lmg` del Módulo 1 se quitaron sin
copiarlos aquí. Las copias idénticas están en
`Modulo3_Inferencia_Control_LMG/` y en el tag.

## Lo que no se movió

La conversión INT8 (`Modulo2_Pipeline_DL/produccion/convertir_tflite.py` y
`perdida_cuantizacion.py`) sigue en su lugar y se adaptó a los canales
nuevos: sirve para comparar fuera de línea el modelo flotante con el INT8.
El experimento ya publicado `experimentos/cuantizacion_int8`, sobre
NinaPro, importa de `convertir_tflite`. `Benchmark_Inferencia/`, que mide
la inferencia en el ESP32, es de la etapa LMG y hoy es trabajo futuro.

Este código archivado no se mantiene: puede no correr con el pipeline
actual de 8 canales.
