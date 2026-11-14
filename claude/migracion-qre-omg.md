# Migración a QRE1113 / OMG (2026-11-13)

Decisión tomada con el asesor. Este documento guarda el inventario del
repositorio antes de migrar y las decisiones que guían cada bloque.

**Punto de retorno:** el tag anotado `lmg-final-2026-11-13` apunta a
`e4193a0`, la última versión LMG (OPT101 con ADS1115, 5 canales, Módulo 3
con control). Para volver: `git checkout lmg-final-2026-11-13`.

## Qué cambia

| | Antes (LMG) | Ahora (OMG) |
|---|---|---|
| Sensor | OPT101 y LED IR aparte, detrás de silicona | QRE1113GR (onsemi): LED IR de 940 nm y fototransistor en el mismo encapsulado, en contacto con la piel, sin silicona |
| Canales ópticos | 5 | 8 |
| PCB | LMG v2, del tesista | `qre` del asesor, 19,5 x 10,8 mm, KiCad 10 |
| Conector | 4 pines (VCC, GND, OUT, LED) | JST ZH B5B-ZR, paso 1,5 mm: VCC, GND, OUT, IR, Led |
| Conversión | Dos ADS1115 por I2C | ADC interno del ESP32, 12 bits, 11 dB |
| Señal | Más luz da más tensión | Más luz da **menos** tensión (colector con 47 kΩ a VCC). El firmware entrega v = V_apag - V_enc, positiva y mayor cuando vuelve más luz |
| Configuraciones | A = 5 ópticos, B = 5 + 3 | A = 8 ópticos, B = 8 + 3 = 11 |
| Nombres | `solo_lmg`, `lmg_imu` | `solo_omg`, `omg_imu` |
| Alcance | Fuera de línea, INT8, ESP32 en línea, mano, servos, FSR | **Solo fuera de línea** |

No cambian: el protocolo de captura (582 s), el preprocesamiento, las
ventanas de 200 ms con paso de 20 ms, las fases, GroupKFold k = 5 con
7 + 1 + 2, LOSO y la estadística (Wilcoxon pareado con Holm, d_z).

"LMG" se queda solo donde se refiere al dataset público `lmg_wavelength`,
a experimentos ya publicados o a código archivado.

## Diferencias entre el prompt y el código real

1. **Pines I2C.** El prompt dice que el MPU6050 cambia "solo sus pines
   I2C" a 21 y 22. El código vigente (`e4193a0`, 22 de octubre) ya los
   había movido a SDA = 33 y SCL = 14. La tabla nueva los devuelve a 21 y
   22. Es un cambio respecto de lo último en `main`, no un regreso a lo que
   estaba.
2. **Versión anterior.** La última versión del firmware LMG es
   `M1-2026.10.22`, como dice el prompt.
3. **`Modulo1_Adquisicion_Datos/gui_captura/`** no está en el prompt. Solo
   tiene el manual del operador y las fotos de los gestos, que usa la app
   de captura (`config_captura.py:169`). Se mantiene y se actualiza el
   manual.

## Inventario

Búsqueda con `git grep` de: LMG, OPT101, ADS1115, ADS1015, adc_lmg,
optica_lmg, FSR, servo, PCA9685, latencia, prueba_en_linea, calibrar_fsr,
banco, indice, NUM_LMG, v5, COLUMNAS_LMG, CANALES_LMG, solo_lmg, lmg_imu.

### Archivar (`git mv` a `archivo/`)

| Qué | Por qué |
|---|---|
| `Modulo3_Inferencia_Control/` entero | Inferencia en el ESP32, servos, PCA9685, FSR, latencia: fuera del alcance |
| `Modulo2_Pipeline_DL/banco_modulos/` | Banco de variantes LMG e índice I |
| `produccion/calibrar_fsr.py`, `prueba_en_linea.py`, `planilla_agarres.csv` | FSR y prueba en línea |
| `tests/test_banco_modulos.py`, `test_calibrar_fsr.py`, `test_prueba_en_linea.py` | Tests de lo archivado, fuera de la colección de pytest |
| `experimentos/optica_espaciador/` | Índice de rendimiento del espaciador de silicona, con v1..v5 fijos |
| `claude/nota-diseno-modulos-lmg.md`, `claude/viabilidad-tflite-micro.md` | Diseño del módulo LMG y del despliegue |
| `Modulo1_Adquisicion_Datos/adc_lmg.*`, `optica_lmg.*` | Siguen en el tag y en `archivo/Modulo3_Inferencia_Control_LMG/`, que tiene copias idénticas |

### Cambiar

| Archivo | Qué tiene hoy |
|---|---|
| `Modulo1_Adquisicion_Datos/` (`config.h`, `.ino`, `README.md`) | Firmware LMG con ADS1115, 5 canales, autocalibración `A`, banco `D` y `W` |
| `captura/adquisicion.py:59, 70, 91, 303` | `CAMPOS_FIRMWARE` y `CAMPOS_CSV` con v1..v5, `ultimo_lmg = valores[:5]` |
| `captura/interfaz.py:13, 442, 498, 554` | Monitor de 5 canales |
| `captura/sesion.py:222` | Texto de 5 canales |
| `captura/protocolo.py:78`, `captura_sesion.py:49` | Textos "LMG" |
| `produccion/preprocesamiento.py:33, 50, 84, 111-117, 191, 202` | `COLUMNAS_MODELO` con v1..v5, `CANALES_LMG`, `COMPOSICIONES` `solo_lmg` y `lmg_imu` |
| `produccion/anotar_fases.py:27, 69, 106` | `COLUMNAS_LMG` escrito a mano |
| `produccion/reporte_preprocesamiento.py:24, 122, 169-172` | `CANALES_LMG` y textos |
| `produccion/verificar_piloto.py` | Lee las columnas del CSV |
| `produccion/entrenar_modelo.py:9, 164` | `--composicion` por defecto `lmg_imu` |
| `produccion/fases.py:5, 68` | Docstrings |
| `common/modelo.py:7-37, 115, 181` | Docstrings con 5 LMG + 3 |
| `experimentos/ablacion_imu/` (`ablacion_imu.py`, `datos.py:190`, `estadistica.py`, `README.md`) | Niveles `solo_lmg` y `lmg_imu`, generador sintético de 5 canales |
| `herramientas/analizar_hiperemia.py:69` | `CANALES_LMG` escrito a mano |
| `herramientas/corrida_completa.sh:7, 11, 41, 54` | `lmg_imu` y los pasos INT8 |
| `tests/test_ablacion_imu.py`, `test_preprocesamiento.py`, `test_validacion.py` | Formas (20, 8) y nombres |
| `README.md`, `ARQUITECTURA.md`, `requirements-captura.txt:23` | Textos, canales, banco |
| `claude/manual-armado-hardware.md`, `hoja-verificacion-sesion.md`, `valores-para-articulo.md`, `CLAUDE.md` | Documentación del hardware LMG |
| `Modulo1_Adquisicion_Datos/gui_captura/README.md` | Manual del operador |

### Mantener sin cambios de resultados

| Qué | Por qué |
|---|---|
| `experimentos/validacion_preliminar_emg/` | Publicado. Su "ruta LMG" son comentarios sobre NinaPro a (20, 8) |
| `experimentos/lmg_wavelength/` | Dataset público LMG |
| `experimentos/ablacion_fases/` | Publicado, sobre el dataset público |
| `experimentos/cuantizacion_int8/` | Publicado sobre NinaPro. Importa de `convertir_tflite` solo `representative_dataset_gen`, `verificar_operaciones` y `convertir_a_tflite`, que no dependen de los canales |
| `produccion/convertir_tflite.py`, `perdida_cuantizacion.py` | No se mueven. **Cambio posterior del usuario:** el INT8 se usará para medir fuera de línea cuánto se degrada el modelo, así que se adaptaron a `solo_omg` y `omg_imu` en el bloque 4. Sin despliegue: se quitó `--copiar_al_modulo3` |
| `Benchmark_Inferencia/` | Igual: etapa LMG, trabajo futuro |
| `common/keras_legado.py`, `common/metricas.py` | Sus menciones de LMG se refieren al dataset público |
| `requirements-tf216-historico.txt` | Registro histórico |
| Tag `si2-groupkfold-repeticion` | No se toca |

## Bloques

| Bloque | Qué |
|---|---|
| 0 | Sincronizar, tag de retorno, este inventario |
| 1 | Archivar lo que sale del alcance |
| 2 | Firmware del Módulo 1 con QRE1113 y ADC interno (**tabla de pines a confirmar**) |
| 3 | App de captura y modo de caracterización |
| 4 | Pipeline a 8 y 11 canales |
| 5 | Análisis de la caracterización preliminar |
| 6 | Documentación |
| 7 | Valores para el artículo |
