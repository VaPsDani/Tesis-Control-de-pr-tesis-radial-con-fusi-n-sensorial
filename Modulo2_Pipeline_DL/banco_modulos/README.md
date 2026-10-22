# Banco de variantes del módulo LMG

Para elegir entre las 6 variantes del PCB (LED pasante o SMD, a 9, 11 y 13 mm
del OPT101) midiéndolas sobre el mismo antebrazo, una por una.

## Modo del firmware con un solo módulo conectado

**No hace falta un modo de un solo canal.** El firmware del Módulo 1 lee
siempre los 5 canales. Los 4 que no tienen módulo conectado devuelven basura y
se ignoran en el análisis, que solo mira el canal que le indiques.

Conecta el módulo al **canal LMG1**, que es el más simple de verificar:

| Señal del módulo | Va a |
|---|---|
| OUT | ADS1115 #1 (**0x48**), entrada **AIN0** |
| LED | **GPIO13** del ESP32 |
| VCC | 3.3 V |
| GND | GND común |

Si lo conectas a otro canal, pasa `--canal N` al script.

## Corriente fija de 13 mA

Las seis variantes se miden con la **misma corriente media del LED, 13 mA**,
fijada por PWM. No se autocalibra. El banco quiere saber cuánta señal saca
cada variante de la misma luz, y eso es justo lo que el índice I divide por
Φe. Una variante con el LED muy cerca del fotodiodo puede saturar con esa
corriente, y por eso la saturación descalifica.

### Paso con el multímetro, una vez por tipo de LED

1. Multímetro en mA, **en serie** con el LED del módulo (entre GPIO13 y el
   pin LED del módulo).
2. En el monitor serie, a 921600 baudios, enviar `W1`. El LED del canal 1
   queda encendido fijo al máximo (duty 511 de 511) y la adquisición se
   detiene.
3. Anotar la corriente. Enviar `S` para apagarlo.
4. Calcular y guardar el duty de ese tipo de LED:

```bash
python Modulo2_Pipeline_DL/banco_modulos/banco.py duty --tipo SMD --corriente_100_ma 18.2
```

```bash
python Modulo2_Pipeline_DL/banco_modulos/banco.py duty --tipo PASANTE --corriente_100_ma 18.5
```

El duty es 511 × 13 / corriente medida. Con los 18 mA de diseño sale 369
(72 %). El OPT101 responde hasta unos 14 kHz y el PWM va a 100 kHz, así que
el fotodiodo ve la media. Cada tipo de LED lleva su propio duty: con
distinto voltaje directo, al 100 % pasan corrientes distintas por la misma
resistencia de 100 Ω. Basta medir una variante de cada tipo.

Hasta que midas, los dos tipos tienen el duty provisional 369, calculado con
los 18 mA de diseño. La captura y el análisis avisan mientras siga así.

## Comandos del firmware

| Comando | Quién lo manda | Para qué |
|---|---|---|
| `W1` | tú, una vez por tipo de LED | LED del canal 1 fijo al máximo, para el multímetro |
| `D369` | el script, al empezar cada prueba | duty fijo del tipo de LED de la variante, sin autocalibrar y sin guardarlo |
| `L` | el script | empieza a emitir muestras |
| `S` | el script, al terminar, o tú tras `W1` | detiene la emisión y apaga el LED fijo |
| `T` | tú, una vez al día | autotest del ciclo, confirma que cabe en 10 ms |

`D` no se guarda en la memoria del ESP32. Al reiniciarlo vuelve la
calibración de las sesiones, así que el banco no la pisa.

## Parámetros, en `parametros_banco.json`

| Campo | Qué es | De dónde sale |
|---|---|---|
| `corriente_media_ma` | 13 | el artículo |
| `corriente_100_ma` y `duty` | corriente al 100 % y duty, por tipo de LED | el subcomando `duty` |
| `rp_a_por_w` | responsividad del fotodiodo del OPT101 a 940 nm, en A/W | hoja de datos del OPT101 |
| `phi_e_mw.PASANTE` y `phi_e_mw.SMD` | flujo radiante de cada LED en mW **a 13 mA** | hoja de datos de cada LED |

Si la hoja da Φe a otra corriente, por ejemplo a 20 mA, en la zona baja la
curva Φe frente a corriente es casi recta y Φe a 13 mA ≈ Φe a 20 mA × 13 / 20.
Si la hoja trae la curva, mejor leerla ahí. El nombre de la variante empieza
por el tipo de LED (`SMD_11mm`, `PASANTE_9mm`) y así el script sabe qué Φe
usar. Sin estos valores `analizar` muestra lo demás y dice qué falta, pero
no calcula I ni ordena.

## Protocolo, 160 s por variante

| Bloque | Duración |
|---|---|
| Reposo | 10 s |
| Puño 5 s + reposo 5 s | 7 veces |
| Pinza 5 s + reposo 5 s | 7 veces |
| Brazo en movimiento, mano relajada, **sin ningún gesto** | 10 s |

El bloque final es el que separa una variante que mide músculo de una que mide
el módulo bailando sobre la piel. Sin él, una variante con mal acoplamiento
mecánico puede dar buen índice y aun así ser la peor en uso real.

### Cómo se hace el bloque de movimiento

La ventana ilumina tres posiciones, una tras otra, con un tono en cada cambio.
Son **las mismas de la condición dinámica de la tesis**, en su orden y a su
ritmo.

| Segundos | Posición |
|---|---|
| 0 a 3.3 | Abajo, al costado |
| 3.3 a 6.7 | Al frente, sin apoyo |
| 6.7 a 10 | Mano por encima del hombro |

Se pasa de una a otra sin parar, a velocidad normal y sin sacudir. La mano va
relajada todo el tiempo, con los dedos sueltos, **y sin girar la muñeca**:
rotar el antebrazo cambia la forma de los músculos justo debajo del sensor y
mediría otra cosa.

Se usan esas tres por dos motivos. El artefacto que interesa es el del
movimiento que harán los participantes, no el de uno cualquiera. Y un
recorrido fijo hace comparable la métrica: es una división entre cuánto se
mueve la señal al mover el brazo y cuánto en reposo, así que si con una
variante mueves el brazo con más ganas, esa variante sale peor por tu culpa y
no por el PCB. **Mismo recorrido, misma velocidad y misma amplitud en las 12
corridas.**

## Cómo correr

Primero el paso con el multímetro. Después capturar, una vez por variante y ronda. Son 12 corridas de 160 s.

```bash
python Modulo2_Pipeline_DL/banco_modulos/banco.py capturar --variante SMD_11mm --ronda 1 --puerto COM3
```

Analizar las 12, cuando estén todas.

```bash
python Modulo2_Pipeline_DL/banco_modulos/banco.py analizar
```

Probar el flujo sin hardware, con el tiempo acortado.

```bash
python Modulo2_Pipeline_DL/banco_modulos/banco.py capturar --variante PRUEBA --ronda 1 --simulado --escala 0.5
```

Al capturar se abre una **ventana a pantalla completa** con la fase en
grande, el color de fondo, la foto del gesto y la cuenta atrás, igual que la
app de captura, y suena un tono en cada cambio. Está pensada para leerse a un
metro, con una mano ocupada en el gesto. **Escape** sale de pantalla completa
y cerrar la ventana aborta la prueba.

| Fondo | Qué toca |
|---|---|
| Azul | Reposo |
| Verde | Puño o pinza |
| Ámbar | Mover el brazo sin gesto |

Con `--sin-ventana` guía solo por consola, que es también lo que hace por su
cuenta si no hay entorno gráfico.

Los CSV y los JSON quedan en `banco_modulos/pruebas/`. Una prueba abortada deja
su CSV incompleto: bórralo antes de analizar, porque `analizar` lee todo lo
que haya en la carpeta.

Para instalar todo desde cero en la computadora de la universidad, ver
`Modulo1_Adquisicion_Datos/gui_captura/README.md`, sección "Puesta en marcha
en otra computadora". Es la misma instalación para los dos programas.

**El análisis necesita pandas y matplotlib**, que están en el entorno de
proyecto (`~/venv-tesis-221`), no necesariamente en el Python que usas para
capturar. La captura solo necesita pyserial.

## Orden de las 12 corridas

1. Ronda 1: las 6 variantes, en el orden que quieras.
2. **Despega el módulo y vuelve a colocarlo** antes de cada prueba de la
   ronda 2.
3. Ronda 2: las 6 variantes **en orden inverso** al de la ronda 1.

Invertir el orden importa. Si midieras las dos rondas en la misma secuencia, la
fatiga y el calentamiento de la piel se acumularían siempre sobre las mismas
variantes y no podrías distinguir ese efecto del de la variante.

La diferencia entre rondas no es un control de calidad, es un resultado: mide
la **repetibilidad del montaje**. Una variante con buen índice que cambia mucho
al recolocarla no sirve para 10 participantes.

## Métricas

Todas se calculan sobre el canal conectado, descartando el primer segundo y el
último medio segundo de cada bloque, que es el mismo margen que usa el
protocolo de la tesis para la contracción.

| Métrica | Definición |
|---|---|
| `ds_puno_mv`, `ds_pinza_mv` | ΔS: media de cada contracción menos la del reposo que la precede, promediada sobre las 7 repeticiones. Restar el reposo vecino quita la deriva lenta. |
| `i_puno`, `i_pinza` | I = \|ΔS\| / (Φe · Rp), en mV/mA. Φe en mW por Rp en A/W da mA. |
| `snr_puno`, `snr_pinza` | \|ΔS\| / desviación estándar del reposo |
| `cv_pinza` | repetibilidad dentro de la prueba: desviación de ΔS entre las 7 pinzas / \|ΔS\| |
| `dif_rondas_pct` | repetibilidad del montaje: diferencia de \|ΔS\| de pinza entre las dos rondas, en % de la media. Es el mismo % que el de I. |
| `artefacto_mov` | desviación estándar durante el movimiento sin gesto / desviación estándar del reposo |
| `n_saturadas` | muestras en 1900 mV o más, sobre el archivo completo |

Se usa el valor absoluto de ΔS porque, según dónde quede el módulo, la
contracción puede subir o bajar la señal. Lo que importa es cuánto cambia.

El umbral de 1900 mV es el 95 % del fondo de escala útil de 2000 mV, el mismo
límite que usa la autocalibración de las sesiones. Una variante satura a
partir de 10 muestras recortadas, o sea 0.1 s acumulado, para que un pico
suelto de red no descalifique a nadie.

## Regla de decisión, fijada antes de medir

**Mayor I sin saturar y con menor artefacto.**

1. Se descartan las variantes que saturan.
2. Gana la de mayor I de pinza.
3. Si otra queda a menos del **10 %** de esa, empatan, y desempata la de menor
   artefacto de movimiento.

La tabla final aplica la misma regla una y otra vez a las que quedan, así que
el puesto 1 es la ganadora, el 2 la que ganaría sin ella, y así. Las que
saturan van al final.

Se usa la pinza y no el puño porque es el gesto de menor amplitud de los
cuatro del protocolo. La variante que distingue bien la pinza distingue bien
todo lo demás, y al revés no.

Rp es el mismo en las seis variantes (el mismo OPT101), así que no cambia el
orden, solo la escala de I. Φe sí cambia el orden entre pasante y SMD.

## Salidas

| Archivo | Contenido |
|---|---|
| `<variante>_r<ronda>_<fecha>.csv` | Datos crudos etiquetados por fase |
| `<variante>_r<ronda>_<fecha>.json` | Duty usado, reposo por canal, huecos, versión del firmware |
| `metricas_pruebas.csv` | Una fila por corrida |
| `tabla_variantes.csv` | La tabla final, una fila por variante, ordenada por la regla |
| `i_pinza.png` | Barras de I de pinza, una por ronda |

## Qué no hace

No decide por ti si la diferencia entre variantes es estadísticamente
significativa. Con 2 rondas no hay con qué: esto es una selección de hardware,
no un experimento. Si dos variantes quedan empatadas y la regla no te
convence, mide una tercera ronda de esas dos.
