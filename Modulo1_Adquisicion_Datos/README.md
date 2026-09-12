# Módulo 1 — Adquisición de datos

Firmware del ESP32 que adquiere 5 canales LMG (OPT101 vía MUX CD74HC4067 +
ADC ADS1115/ADS1015) y los 6 ejes del MPU6050 a 100 Hz, y los envía por serie
a la aplicación de captura del Módulo 2 (`Modulo2_Pipeline_DL/captura/`).

## Lectura óptica

- **Un LED a la vez.** Cada módulo LMG tiene su propio pin PWM (GPIO 16, 17, 18,
  19, 23; confirmar contra el PCB, cada pin gobierna un transistor). Solo se
  enciende el LED del canal que se está leyendo, lo que elimina el crosstalk
  óptico entre módulos vecinos.
- **Trama oscura** (`v = L − D`, con 200 µs de asentamiento). Cancela la
  componente continua de la luz ambiental. **No** cancela el parpadeo de 120 Hz
  de las lámparas: D y L quedan separadas por una conversión completa del ADC. La
  trama oscura va ligada al ADS1015; con el ADS1115 el ciclo no cabe en 10 ms.
  El razonamiento y el presupuesto temporal están en
  `Modulo3_Inferencia_Control/config.h` y en `optica_lmg.h`.
- `optica_lmg.*` y `mux_ads1115.*` son **idénticos** en los módulos 1 y 3:
  la señal con que se entrena es la misma con que se infiere.

Comandos serie: `L` iniciar, `S` detener, `M` marcador de sincronización,
`A` autocalibrar los LED (~10 s, mano en reposo), `T` autotest del ciclo de
muestreo, `K` reemitir la ganancia y el reposo por canal.

## Procedimiento de una sesión

1. Colocar el brazalete y enviar `A`. La autocalibración deja el reposo en ~35%
   del fondo de escala, comprueba que una contracción máxima no recorte y
   guarda en NVS la corriente y el valor de reposo de cada canal (S̄r).
2. Iniciar la sesión en la aplicación de captura. Al recibir `L`, el firmware
   emite las líneas `[OPTICA_*]` y la PC guarda la corriente y S̄r en el JSON de
   la sesión.
3. Al cerrar la sesión, la aplicación añade al CSV la columna `fase`
   (`anotar_fases.py`) y deja al lado un `<csv>_fases.json` con el informe por
   gesto.

## Protocolo de captura

### 1. Secuencia intercalada y repetida, no por bloques de un mismo gesto

La sesión no graba todas las repeticiones de un gesto seguidas. Cada una de las
6 repeticiones presenta **los 4 gestos activos** (Pinch, Tripod, Power,
Finger_Ext) una vez, en orden contrabalanceado, y la secuencia se repite. Cada
gesto va precedido de 8 s de reposo:

```
calibración 15 s | reposo 8 s · gesto A 15 s | reposo · gesto C | reposo · gesto B | reposo · gesto D | … ×6
```

- **Por qué intercalar.** Grabar por bloques confunde el gesto con el tiempo:
  la deriva del sensor, la fatiga y la hiperemia acumulada quedarían asociadas
  a cada clase, y el clasificador podría separar las clases por la hora y no
  por el gesto.
- **Por qué contrabalancear.** Con orden fijo, cada gesto hereda siempre el
  estado del anterior y el participante anticipa cuál viene. El dataset
  público `lmg_wavelength_dataset`, de orden fijo, lo muestra: la señal
  empieza a moverse unos 250 ms **antes** de la instrucción, y el 72% de las
  transiciones supera el 10% de su excursión en los 500 ms previos. El orden se
  genera por sujeto (semilla = `subject_id`) eligiendo, entre 4000 candidatos,
  el de menor desbalance de pares ordenados consecutivos
  (`captura/protocolo.py`).

### 2. Rest se deriva de los reposos entre gestos, con recorte de bordes

No hay bloques de Rest propios: la clase Rest sale de los 24 periodos de reposo
entre gestos (ratio Rest:activa de 1.63:1). Para que no entren a Rest ni el
transitorio de relajación ni la anticipación del gesto siguiente:

- la **relajación** se detecta por señal: dura desde el fin del gesto hasta que
  la señal entra de forma sostenida en la banda de su línea base;
- del **reposo estable** que queda se descartan **500 ms al inicio y
  1000 ms al final** (fase `recorte`).

| Parámetro | Valor | Por qué |
|---|---|---|
| `recorte_reposo_ini_ms` | 500 ms | La relajación ya se detecta por señal. Este recorte es una guarda adicional contra el final del transitorio. |
| `recorte_reposo_fin_ms` | 1000 ms | La anticipación es el borde que más contamina (ver arriba). Además, 1000 ms es el inicio de la búsqueda del onset, así que la ventana de línea base termina justo donde podría empezar el movimiento. |

Son configurables en `fases.ParametrosFases` y en
`anotar_fases.py --recorte_ini --recorte_fin`.

### 3. La fase dinámica se etiqueta, no se descarta

El margen fijo de 1000 ms al inicio de cada contracción (`en_margen`) cortaba a
ciegas: recortaba movimiento real o dejaba reacción etiquetada como gesto,
según el participante. Ahora cada fila lleva una columna `fase`:

| Periodo | `fase` | Qué es |
|---|---|---|
| gesto | `reaccion` | desde la instrucción hasta el onset detectado; la mano sigue quieta |
| gesto | `dinamica` | desde el onset hasta la meseta; es lo que gobierna el control real |
| gesto | `meseta` | el gesto sostenido |
| reposo | `relajacion` | desde el fin del gesto hasta que la señal se asienta |
| reposo | `reposo` | reposo estable, la clase Rest |
| reposo | `recorte` | bordes del reposo estable que se descartan |

**Detección del onset** (`Modulo2_Pipeline_DL/fases.py`). Con la media y la
desviación por canal de la línea base se calcula la desviación multicanal
D(t) = √(media_c z_c²). El onset es la primera muestra en que D supera
μ_D + k·σ_D durante al menos T ms seguidos, con **k = 3** y **T = 50 ms** por
defecto (`--k`, `--t_ms`). La meseta empieza cuando D alcanza el 90% de su nivel
sostenido. La **IMU** confirma el movimiento: se exige que se aparte de su
propia línea base en los 500 ms posteriores al onset.

**Cotas de sanidad, que se marcan pero no descartan.** Un onset antes de
150 ms desde la instrucción (más rápido que una reacción visual) o después de
1000 ms (distracción, gesto débil), un onset negativo (anticipación), la falta
de confirmación de la IMU y una línea base todavía en deriva marcan el gesto
como `sospechoso`, con el motivo en `<csv>_fases.json`. Ningún tramo se borra.

**Línea base.** Por defecto se usa la del reposo inmediatamente anterior a cada
gesto (sus 2 s finales, antes del recorte). El bloque de calibración, que da el
S̄r de la sesión, sirve de respaldo, y es la base única con `--modo_base
calibracion`. No es la opción por defecto, aunque era la especificada, porque
una base tomada minutos antes es precisamente la que hizo fallar la primera
versión del detector sobre el dataset público. Con ella, la deriva y la
hiperemia bastaban para superar el umbral, y el onset caía en el borde de la
ventana de búsqueda en buena parte de los gestos. `anotar_fases.py
--comparar_bases` (que la aplicación de captura ejecuta siempre) reporta ambas
sobre cada sesión para decidirlo con el piloto.

**Entrenamiento.** La clase del gesto es `dinamica` + `meseta`, y la de Rest es
solo `reposo`. `reaccion` se excluye del entrenamiento pero se conserva en el
CSV. `preprocesamiento.cargar_csv(variante_fases=...)` aplica el criterio; si
el CSV no tiene la columna, o la tiene de una versión anterior del detector, la
calcula al vuelo. `en_margen` se sigue grabando, pero ya no decide qué filas
entran.

**Ablación.** `experimentos/ablacion_fases/ablacion_fases.py` compara las tres
variantes de entrenamiento (`solo_meseta`, `dinamica_meseta`,
`todo_con_reaccion`) sobre el **mismo** conjunto de test. Reporta la exactitud
por clase y por fase, la matriz de confusión y la fracción de ventanas de
reacción clasificadas como Rest. Chen et al. lo mostraron sobre sEMG; el
equivalente sobre LMG es un resultado propio.

```bash
python Modulo2_Pipeline_DL/experimentos/ablacion_fases/ablacion_fases.py --csv Modulo2_Pipeline_DL/captura/sesiones/*.csv
```
