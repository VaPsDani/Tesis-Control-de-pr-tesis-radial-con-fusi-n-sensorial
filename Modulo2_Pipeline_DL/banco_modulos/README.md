# Banco de variantes del módulo LMG

Para elegir entre las 6 variantes del PCB (LED pasante o SMD, a 9, 11 y 13 mm
del OPT101) midiéndolas sobre el mismo antebrazo, una por una.

## Modo del firmware con un solo módulo conectado

**No hay un modo especial, y no hace falta.** El firmware del Módulo 1 lee
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

Comandos del firmware, en este orden. El script manda los dos primeros solo:

| Comando | Quién lo manda | Para qué |
|---|---|---|
| `A` | el script, al empezar cada prueba | autocalibra la corriente del LED |
| `L` | el script | empieza a emitir muestras |
| `S` | el script, al terminar | detiene la emisión |
| `T` | tú, una vez al día | autotest del ciclo, confirma que cabe en 10 ms |

**La autocalibración va a avisar que hay 4 canales DEBIL y va a devolver
fallo. Es lo esperado**, son los 4 sin módulo. Lo único que importa es que el
canal conectado quede en unos **700 mV en reposo**. El script imprime la
respuesta completa del firmware para que lo compruebes.

**No saltes la autocalibración entre variantes.** Un LED a 9 mm entrega más luz
al fotodiodo que uno a 13 mm. Sin recalibrar, la variante más cercana ganaría
por la distancia y no por la calidad del acoplamiento, que es lo que quieres
medir. Con `A` en cada variante, las 6 se comparan en el mismo punto de
operación, y el duty al que quedó cada una se guarda en el JSON de la prueba.

## Protocolo, 80 s por variante

| Bloque | Duración |
|---|---|
| Reposo | 10 s |
| Puño 5 s + reposo 5 s | 3 veces |
| Pinza 5 s + reposo 5 s | 3 veces |
| Brazo en movimiento, **sin ningún gesto** | 10 s |

El bloque final es el que separa una variante que mide músculo de una que mide
el módulo bailando sobre la piel. Sin él, una variante con mal acoplamiento
mecánico puede dar buen SNR y aun así ser la peor en uso real.

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

Capturar, una vez por variante y ronda. Son 12 corridas de 80 s.

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
la **repetibilidad del montaje**. Una variante con SNR alto que cambia mucho al
recolocarla no sirve para 10 participantes.

## Métricas

Todas se calculan sobre el canal conectado, descartando el primer segundo y el
último medio segundo de cada bloque, que es el mismo margen que usa el
protocolo de la tesis para la contracción.

| Métrica | Definición |
|---|---|
| `snr_puno`, `snr_pinza` | (media de contracción − media de reposo) / desviación estándar del reposo |
| `artefacto_mov` | desviación estándar durante el movimiento sin gesto / desviación estándar del reposo |
| `n_saturadas` | muestras en 1900 mV o más, sobre el archivo completo |
| `dif_rondas` | diferencia de SNR de pinza entre las dos rondas |

El umbral de 1900 mV sale del firmware: el fondo de escala útil son 2000 mV y
la autocalibración no deja pasar del 95 %. Una variante satura a partir de 10
muestras recortadas, o sea 0.1 s acumulado, para que un pico suelto de red no
descalifique a nadie.

## Regla de decisión, fijada antes de medir

1. Se descartan las variantes que saturan.
2. Gana la de mayor SNR de pinza.
3. Si otra queda a menos del **10 %** de esa, empatan, y desempata la de menor
   artefacto de movimiento.

Se usa la pinza y no el puño porque es el gesto de menor amplitud de los
cuatro del protocolo. La variante que distingue bien la pinza distingue bien
todo lo demás, y al revés no.

## Salidas

| Archivo | Contenido |
|---|---|
| `<variante>_r<ronda>_<fecha>.csv` | Datos crudos etiquetados por fase |
| `<variante>_r<ronda>_<fecha>.json` | Duty del LED, reposo por canal, huecos, versión del firmware |
| `metricas_pruebas.csv` | Una fila por corrida |
| `metricas_variantes.csv` | Una fila por variante |
| `snr_pinza.png` | Barras de SNR de pinza, una por ronda |

## Qué no hace

No decide por ti si la diferencia entre variantes es estadísticamente
significativa. Con 2 rondas no hay con qué: esto es una selección de hardware,
no un experimento. Si dos variantes quedan empatadas y la regla no te
convence, mide una tercera ronda de esas dos.
