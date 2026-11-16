# Módulo 1: adquisición de datos (OMG)

Firmware del ESP32 que adquiere a 100 Hz las señales de **8 módulos QRE1113**
(OMG, optomiografía) con el **ADC interno** del ESP32 y los 6 ejes del MPU6050,
y las envía por serie a la aplicación de captura del Módulo 2
(`Modulo2_Pipeline_DL/captura/`). Todo se evalúa fuera de línea: este firmware
solo adquiere.

> **Desde `M1-2026.11.13-QRE`** el sensor es otro. Estas sesiones **no se
> mezclan** con las de `M1-2026.10.22` o anteriores (OPT101 con ADS1115, 5
> canales). El firmware LMG está en el tag `lmg-final-2026-11-13`. La versión
> queda en el JSON de cada sesión (`version_firmware`). Cableado y pruebas en
> `claude/manual-armado-hardware.md`.

## Conexiones

Placa: DevKit ESP32 WROOM de 38 pines. La tabla vive en `config.h`
(`PIN_OUT`, `PIN_IR`) y el firmware la imprime al arrancar con líneas
`[PINES]`.

| Módulo | JST pin 3, OUT (ADC) | JST pin 4, IR (LED) |
|---|---|---|
| 1 | GPIO36 (VP/SP, ADC1_CH0) | GPIO13 |
| 2 | GPIO39 (VN/SN, ADC1_CH3) | GPIO27 |
| 3 | GPIO34 (ADC1_CH6) | GPIO23 |
| 4 | GPIO35 (ADC1_CH7) | GPIO19 |
| 5 | GPIO32 (ADC1_CH4) | GPIO18 |
| 6 | GPIO33 (ADC1_CH5) | GPIO17 |
| 7 | GPIO25 (ADC2_CH8) | GPIO16 |
| 8 | GPIO26 (ADC2_CH9) | GPIO4 |

En todos los módulos: JST pin 1 (VCC) a **3,3 V**, pin 2 a GND, y **pin 5 (Led)
sin conectar**. El MPU6050 va por I2C en SDA = GPIO21 y SCL = GPIO22, a 400 kHz.

Los OUT de los módulos 7 y 8 (GPIO25 y 26) son del ADC2, que el driver de WiFi
toma para sí. Por eso el firmware nunca inicia el WiFi (ni incluye `WiFi.h`)
y apaga el Bluetooth al arrancar, y lo informa con la línea `[RADIO]`. No usa ninguna librería externa: solo las del
núcleo ESP32.

## Número de módulos: el interruptor

Se usan los módulos 1 a `NUM_OPT` de la tabla de arriba. **Hoy `NUM_OPT = 4`**,
para las pruebas con 4 módulos: sus 4 OUT quedan en ADC1. El diseño final es 8.

Para cambiarlo hay que tocar **dos números y nada más**, y tienen que ser
iguales:

- `#define NUM_OPT` en `Modulo1_Adquisicion_Datos/config.h`
- `NUM_OPT` en `Modulo2_Pipeline_DL/common/canales.py`

Todo lo demás sale de ahí: el CSV (15 campos con 4 módulos, 23 con 8), la
captura, el preprocesamiento, las composiciones (4 y 7 canales, u 8 y 11) y los
tests. Si los dos números no coinciden, la captura descarta todas las líneas.
Las sesiones grabadas con un número de módulos no se mezclan con las de otro:
`preprocesamiento.py` las rechaza.

## Lectura óptica

Cada QRE1113 tiene un LED IR de 940 nm y un fototransistor en el mismo
encapsulado. OUT es el colector, con 47 kΩ a VCC: **más luz da menos tensión**.
A oscuras OUT queda en unos 3,3 V, por encima del tope del ADC con 11 dB
(~3,1 V), así que dentro de la carcasa la lectura con el LED apagado queda en el
tope. Es normal.

Cada ciclo de 10 ms:

1. Todos los LED apagados, espera `T_OFF_US`, lee los 8 canales: `V_apag`.
2. LED encendidos (los 8 a la vez por defecto, `MODO_LED`), espera `T_ON_US`,
   lee los 8 y apaga: `V_enc`.
3. Lee el MPU6050.
4. `v = V_apag − V_enc` en mV, positiva y mayor cuando vuelve más luz.
   `amb = V_apag`.
5. Emite la línea.

Cada lectura promedia `N_MUESTRAS` (4, provisional) lecturas calibradas
(`analogReadMilliVolts`), descartando la primera tras cambiar de canal. La
capacidad de salida de los 8 GPIO de los LED se fija a mano
(`GPIO_DRIVE_CAP_2`) y se imprime al arrancar.

**Valores provisionales hasta medirlos con la placa:** `T_ON_US` y `T_OFF_US`
(1000 µs), `N_MUESTRAS` y los umbrales de las banderas del autotest.

## Formato de la línea

```
timestamp_ms,v1,...,v8,ax,ay,az,gx,gy,gz,amb1,...,amb8
```

22 señales más el timestamp, unos 182 bytes en el peor caso. A 100 Hz son
18 200 B/s, el 20 % de lo que dan 921 600 baudios. Al modelo entran `v1..v8` y
`ax, ay, az`. El giroscopio y `amb` se guardan para el análisis.

## Comandos

| Comando | Qué hace |
|---|---|
| `L` | Empieza a emitir. Antes emite versión, pines, `[OPTICA_*]` e `[IMU]`, que la app guarda en el JSON |
| `S` | Detiene |
| `R` | Detiene y reinicia el contador |
| `M` | Marcador de sincronización: `[MARK]` con el `millis()` actual |
| `K` | Reemite la configuración |
| `T` | Autotest: 1000 ciclos con media, p95 y máximo, y por canal `V_enc`, `V_apag`, `v` y su desviación en reposo, con banderas `SATURADO`, `SIN_SENAL`, `LED_NO_ENCIENDE` y `TOPE_ADC` (informativo), más la línea `[IMU]` |
| `C` | Curva de asentamiento por canal, al encender y al apagar su LED: t90, t95 y t99, y `T_ON_US` / `T_OFF_US` sugeridos (t99 + 20 %) |
| `X` | Diafonía: por canal, con su LED apagado y los otros 7 encendidos, frente a todos apagados |
| `D<0-3>` | Capacidad de salida de los 8 LED, para la prueba de saturación. No se guarda: al reiniciar vuelve a 2 |
| `E<us>` | Fija `T_ON_US` y lo guarda en NVS |
| `O<us>` | Fija `T_OFF_US` y lo guarda en NVS |

`T`, `C` y `X` detienen la emisión mientras corren. Ya no hay autocalibración
por canal: `A` y `W` no existen.

## Primera prueba con la placa

1. Medir 3,3 V en el pin 1 del JST de cada módulo.
2. `T`: que el ciclo quepa en 10 ms y ningún canal tenga banderas.
3. `C`: aplicar los tiempos sugeridos con `E` y `O`, y repetir `T`.
4. `X`: si algún canal pasa del 5 %, probar `MODO_LED = MODO_SECUENCIAL`.

Detalle en `claude/manual-armado-hardware.md`.

## Procedimiento de una sesión

1. Colocar el brazalete y comprobar con `T` que no hay banderas.
2. Iniciar la sesión en la aplicación de captura. Al recibir `L`, el firmware
   emite la configuración y la PC la guarda en el JSON de la sesión.
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

La clase Rest sale de los 24 periodos de reposo entre gestos y de los 3
reposos en movimiento. Para que no entren a Rest ni el
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

**Detección del onset** (`Modulo2_Pipeline_DL/produccion/fases.py`). Con la media y la
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
estadísticas de la sesión, sirve de respaldo, y es la base única con `--modo_base
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
equivalente sobre señal óptica es un resultado propio.

```bash
python Modulo2_Pipeline_DL/experimentos/ablacion_fases/ablacion_fases.py --csv Modulo2_Pipeline_DL/captura/sesiones/*.csv
```
