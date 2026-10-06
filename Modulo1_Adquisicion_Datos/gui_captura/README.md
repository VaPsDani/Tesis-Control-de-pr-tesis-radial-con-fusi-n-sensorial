# Aplicación de captura guiada, manual del operador

Guía al participante durante la sesión y graba los datos ya etiquetados.
Dos ventanas: una para el participante, a pantalla completa, y otra para el
operador, con los controles y el monitor de señal.

## Dónde vive el código

La aplicación es la del Módulo 2, en `Modulo2_Pipeline_DL/captura/`. No se
duplicó aquí a propósito: el CSV que escribe lo leen `preprocesamiento.py`,
`anotar_fases.py` y `verificar_piloto.py`, y dos aplicaciones de captura con
esquemas distintos habrían partido el dataset en dos.

| Archivo | Qué hace |
|---|---|
| `Modulo2_Pipeline_DL/captura_sesion.py` | Punto de entrada |
| `captura/config_captura.py` | **Todos** los tiempos, colores y valores por defecto |
| `captura/protocolo.py` | Secuencia de bloques y contrabalanceo |
| `captura/adquisicion.py` | Lectura del puerto y escritura del CSV |
| `captura/interfaz.py` | Las dos ventanas |
| `captura/sesion.py` | Orquestador |
| `Modulo1_Adquisicion_Datos/gui_captura/assets/` | Imágenes de los gestos |

## Puesta en marcha en otra computadora, desde cero

Los **dos** programas que se llevan a la universidad viven en este mismo
repositorio y comparten instalación:

| Programa | Para qué | Cuándo |
|---|---|---|
| `Modulo2_Pipeline_DL/captura_sesion.py` | Sesiones de los 10 participantes | La campaña |
| `Modulo2_Pipeline_DL/banco_modulos/banco.py` | Elegir entre las 6 variantes del PCB | Antes de la campaña |

Cinco pasos. Python 3.12 desde python.org, marcando **Add python.exe to
PATH** en el instalador.

```bash
git clone https://github.com/<tu-usuario>/Tesis-Control-de-pr-tesis-radial-con-fusi-n-sensorial.git
```

```bash
cd Tesis-Control-de-pr-tesis-radial-con-fusi-n-sensorial
```

```bash
python -m venv .venv
```

```bash
.venv\Scripts\activate
```

```bash
pip install -r Modulo2_Pipeline_DL/requirements-captura.txt
```

Eso instala pyserial, numpy, pandas y matplotlib, y **nada más**. TensorFlow
no se instala: ni la sesión ni el banco lo usan. Tkinter ya viene con Python
en Windows. En Linux hace falta `sudo apt install python3-tk`.

**No uses Docker.** Los dos programas necesitan el puerto COM del ESP32, una
ventana gráfica y el altavoz. Docker Desktop en Windows no pasa puertos USB al
contenedor, así que habría que resolver tres problemas para no ahorrar
ninguno.

### Comprobación antes de salir de casa

Las dos deben correr sin hardware conectado. Si fallan aquí, fallan allá.

```bash
python Modulo2_Pipeline_DL/captura_sesion.py --simulado
```

```bash
python Modulo2_Pipeline_DL/banco_modulos/banco.py capturar --variante PRUEBA --ronda 1 --simulado --escala 0.5
```

```bash
python -m pytest Modulo2_Pipeline_DL/tests -q
```

Los tests necesitan `pip install pytest`, que no está en el requirements de
captura a propósito.

### Ya en la universidad

Conecta el ESP32 y averigua el puerto. En Windows sale en el Administrador de
dispositivos, bajo Puertos (COM y LPT), como COM3, COM4 y demás.

```bash
python Modulo2_Pipeline_DL/captura_sesion.py --puerto COM3 --participante S01
```

```bash
python Modulo2_Pipeline_DL/banco_modulos/banco.py capturar --variante SMD_11mm --ronda 1 --puerto COM3
```

Cada vez que abras una consola nueva hay que volver a activar el entorno con
`.venv\Scripts\activate`.

## Instalación mínima, si solo quieres la app de captura

Python 3.12. Tkinter viene con la biblioteca estándar, así que la única
dependencia para grabar es pyserial.

```bash
pip install pyserial
```

En Linux hay que instalar Tkinter aparte.

```bash
sudo apt install python3-tk
```

Prueba de que todo está en su sitio, sin hardware.

```bash
python Modulo2_Pipeline_DL/captura_sesion.py --simulado
```

Ojo: así no se instala pandas, y sin pandas la sesión graba bien pero **no
puede anotar la columna `fase` al cerrar** ni correr `verificar_piloto.py`.
Para una sesión de verdad, usa el requirements de arriba.

## Imágenes de los gestos

En `gui_captura/assets/`, en PNG, con estos nombres exactos.

| Archivo | Gesto |
|---|---|
| `Rest.png` | Reposo |
| `Pinch.png` | Pinza |
| `Tripod.png` | Trípode |
| `Power.png` | Puño de fuerza |
| `Finger_Ext.png` | Extensión de dedos |

Tkinter carga PNG sin librerías extra. Tamaño recomendado de 300 por 300
píxeles, fondo transparente o claro. Si falta alguna, la sesión corre igual y
en el marco aparece un recuadro vacío, pero el operador ve un aviso al iniciar.

## Antes de que llegue el participante

1. Conecte el ESP32 y anote el puerto. En Windows sale en el Administrador de
   dispositivos como COM3, COM4 y demás.
2. Coloque el brazalete y ajuste la correa.
3. Abra la aplicación.

```bash
python Modulo2_Pipeline_DL/captura_sesion.py --puerto COM3 --participante S01
```

4. Una vez al día, con nadie puesto el brazalete, pulse **Autotest del ciclo
   (T)**. Confirma que el muestreo cabe en los 10 ms de los 100 Hz. Antes
   del resultado, el registro muestra dos líneas que hay que comprobar: `[FW] version=M1-2026.10.05` y la del acelerómetro, que tiene que
   terminar en `OK` y decir `DLPF_CFG=4` y `AFS_SEL=0`. Es la lectura de los
   registros desde la propia placa, no lo que el código manda. La misma
   línea queda guardada en el JSON de cada sesión.
5. Con el participante ya con el brazalete puesto y en reposo, pulse
   **Autocalibrar LED (A)**. Dura unos 15 s y al final pide una contracción
   máxima de 3 s, que hay que pedirle en voz alta cuando aparezca el aviso.

Los dos botones abren el puerto, mandan el comando al firmware, muestran su
respuesta en el registro del operador y **cierran el puerto al terminar**, de
modo que ya no hace falta el monitor serie del IDE de Arduino. Se
deshabilitan mientras la sesión corre, porque el puerto no se puede abrir dos
veces.

## Paso a paso de la sesión

### 1. Configuración

En la ventana del operador, rellene:

| Campo | Qué poner |
|---|---|
| `subject_id` | Número entero, 1, 2, 3. Es la semilla del contrabalanceo |
| `id anonimo` | S01, S02. Es lo que va al CSV, nunca el nombre |
| `puerto` y `baudios` | Los baudios ya vienen en 921600, que es el del firmware |
| `carpeta` | Dónde se guardan el CSV y el JSON |
| Datos del participante | Edad, sexo, mano dominante, brazo registrado, longitud y circunferencia del antebrazo en cm, posición del brazalete en cm y punto de cierre de la correa |

`brazo_registrado` viene relleno con "derecho", porque el artículo registra
siempre el brazo derecho de participantes diestros. Solo se toca si hubiera
una excepción, que entonces queda escrita en el JSON.

`punto_cierre_correa` es texto libre: el agujero o la marca donde quedó
cerrada la correa, por ejemplo "agujero 4". Con eso la tensión se puede
repetir si hay que volver a grabar a la misma persona.

La longitud, la circunferencia, la posición del brazalete y el cierre se
anotan porque, sin ellos, un sujeto que rinde peor que los demás queda sin
explicación posible.

### 2. Prueba de conexión

Pulse **Probar conexión**. Se abre una ventana con los cinco canales en crudo.

**Pida tres contracciones fuertes** y mire la columna de estado.

| Lo que ve | Qué significa |
|---|---|
| Los cinco dicen "responde" | Buena colocación, puede empezar |
| Uno dice "plano" | Módulo despegado, LED apagado o cable suelto |
| La tasa no está cerca de 100 | El adaptador USB no sostiene los baudios |
| Aparecen huecos | Se están perdiendo muestras |

Arregle lo que haga falta y repita. Esta prueba no graba nada. Ciérrela antes
de iniciar.

### 3. Instrucciones al participante

Antes de pulsar Iniciar, explique:

- **Postura de referencia**: sentado, antebrazo sobre la mesa **con la palma
  hacia abajo**, codo a 90 grados y la mano fuera del borde. Ya no es "pulgar
  hacia arriba".
- Mire la pantalla, no el teclado ni su mano.
- En **PREPARESE** verá el gesto que viene, con cuenta de 3, 2 y 1. Si la
  repetición es con movimiento, además se ilumina la posición de partida:
  hay que llevar el brazo ahí con la mano relajada, sin hacer el gesto
  todavía.
- En **CONTRAIGA** ejecute el gesto **con fuerza moderada** y manténgalo los
  10 s. **Suba la fuerza poco a poco durante el primer segundo**, siguiendo
  la barra amarilla, sin dar un golpe.
- En **DESCANSE** relaje la mano del todo. Después de una repetición con
  movimiento, **primero suelte el gesto y después vuelva el antebrazo a la
  mesa**. Al revés, la vuelta a la mesa quedaría grabada todavía con el gesto.
- La **extensión es de dedos y muñeca a la vez**, como en la foto: la mano
  se abre y se dobla hacia atrás. La pantalla lo recuerda con "Extienda dedos
  y muñeca". Extender solo los dedos es otro gesto, porque activa otros
  músculos del antebrazo.
- Antes de pulsar Iniciar, **practique los cuatro gestos con el
  participante**, y en especial la extensión, hasta que la haga siempre igual.
- Si se equivoca de gesto, que lo diga y siga. No hay que disimular.

Explique además las dos clases de repetición, porque van mezcladas en la misma
sesión y la pantalla avisa de cuál toca ya en la fase de preparación.

| La pantalla dice | Qué tiene que hacer |
|---|---|
| **BRAZO QUIETO** | Mantener el gesto sin mover el brazo, en la postura de referencia, con el antebrazo sobre la mesa y la palma hacia abajo |
| **BRAZO EN MOVIMIENTO** | Mantener el gesto mientras recorre las tres posiciones que se iluminan abajo, una cada 3.3 s, pasando de una a otra sin parar, sin soltar el gesto y **sin girar el antebrazo** |
| **SIN GESTO** con fondo verde y **MUEVA EL BRAZO** | Es un **reposo en movimiento**: recorrer las tres posiciones igual que arriba, pero **con la mano relajada**, sin hacer ningún gesto |

Hay 3 reposos en movimiento por sesión, intercalados entre los gestos. Su
preparación dice "Ahora viene: reposo con el brazo en movimiento" y no
muestra la barra de fuerza, porque no hay fuerza que subir. Son importantes:
le enseñan al modelo que mover el brazo no significa hacer un gesto.

En las repeticiones con movimiento, **la casilla de la primera posicion ya se ilumina durante la preparacion**, con el aviso de llevar el brazo ahi con la mano relajada. El gesto empieza recien con el fondo verde. Asi la contraccion no se gasta llevando el brazo a su sitio, que era lo que convertia el primer tramo de 3.3 s en un traslado etiquetado como si el brazo ya estuviera colocado.

En las repeticiones con movimiento suena un tono agudo en cada cambio de
posición, así que no hace falta mirar la pantalla mientras se mueve el brazo.
De las 6 repeticiones de cada gesto, 3 son quietas y 3 con movimiento.

### 4. Durante la sesión

Pulse **Iniciar**. La sesión dura 9.7 min y va sola.

| Botón | Cuándo se usa |
|---|---|
| **Pausar** y **Reanudar** | El participante necesita parar. El CSV queda completo hasta esa fila |
| **Descartar repeticion** | El participante hizo un gesto distinto al pedido. Marca esa repetición y sigue |
| **Abortar** | Termina y guarda lo capturado |

Vigile el panel de adquisición.

| Indicador | Valor bueno |
|---|---|
| muestras por segundo | Entre 95 y 105, en verde |
| huecos | Cero. En rojo desde el primero |
| cola | Estable, sin crecer |
| Monitor de los 5 canales | Cinco trazos que se mueven, ninguno plano ni pegado arriba |

Si el puerto se cae, la sesión **se pausa sola**, el participante ve una
pantalla de espera y el CSV queda a salvo. Revise el cable, espere a que el
registro diga que el enlace volvió y pulse Reanudar.

### 5. Al terminar

En la carpeta de salida quedan tres archivos por sesión.

| Archivo | Contenido |
|---|---|
| `s01_estatico_<fecha>.csv` | Los datos etiquetados |
| `s01_estatico_<fecha>.json` | Metadatos: fecha, duración, secuencia de gestos, puerto, versión del firmware, descartes y estadísticas |
| `s01_estatico_<fecha>_fases.json` | Resumen de la anotación de fases, que corre sola al cerrar |

Anote en observaciones cualquier incidencia antes de cerrar la ventana.

## Qué hay en el CSV

**El CSV guarda los 12 campos crudos que emite el firmware. El modelo consume
8 canales.** No son lo mismo y conviene no confundirlos.

| Columnas | Origen |
|---|---|
| `timestamp_ms`, `v1` a `v5`, `ax`, `ay`, `az`, `gx`, `gy`, `gz` | Firmware, 12 campos |
| `subject_id`, `repetition_id`, `label`, `bloque_tipo`, `condicion_postural`, `en_margen`, `es_calibracion` | Protocolo |
| `id_participante`, `posicion_brazo`, `ts_pc_ms`, `descartada` | Sesión guiada |
| `fase` | La añade `anotar_fases.py` al cerrar |

**`condicion_postural`** vale `estatica` o `dinamica` y va **por repetición**,
no por sesión. Es el factor B del experimento de ablación de la IMU. Queda
vacía en la calibración, que no pertenece a ninguna de las dos.

**`posicion_brazo`** dice qué posición se estaba pidiendo **en ese instante**,
así que dentro de una misma contracción dinámica cambia dos veces. Queda vacía
en las repeticiones quietas. Sirve para comprobar después si los errores se
concentran en los cambios de posición.

El giroscopio se graba aunque el modelo no lo use. Sus bytes ya viajan en la
misma lectura I2C, así que no cuesta nada guardarlo, y es justo donde puede
hacer falta en las repeticiones con movimiento. El descarte a los 8 canales
ocurre en `preprocesamiento.py`, nunca en la captura. Una sesión no se repite,
y recuperar un canal después costaría volver a grabar con los diez
voluntarios.

**Ojo con la palabra fase.** En `bloque_tipo` las fases son calibración,
preparación, contracción, reposo y `reposo_dinamico`, que es el bloque de 10 s
del reposo en movimiento. La columna `fase` de `fases.py` es otra cosa:
reposo, dinámica, meseta y reacción.

**`en_margen` y `descartada` marcan, no borran.** El margen de entrada de
1000 ms de cada contracción se señala pero las filas se conservan, para poder
barrer ese valor sobre los datos del piloto sin volver a grabar.

## El protocolo, y por qué es así

| Bloque | Duración | Margen de entrada y salida |
|---|---|---|
| Calibración, una vez | 15 s | 1000 y 500 ms |
| Preparación | 3 s | entero en margen |
| Contracción | 10 s | 1000 y 500 ms |
| Reposo | 8 s | 2000 y 500 ms |
| Reposo en movimiento, en lugar de la contracción | 10 s | 1000 y 500 ms |

Total: 15 + (4 × 6 + 3) × (3 + 10 + 8) = 582 s, o sea 9.7 min.

Cuatro gestos activos por seis repeticiones, con **orden contrabalanceado e
intercalado**: cada repetición presenta los cuatro gestos una vez, en un orden
que se elige para que todos los pares de gestos consecutivos aparezcan un
número parecido de veces. La semilla es el `subject_id`, así que la sesión es
reproducible y cada sujeto recibe un orden distinto. La secuencia usada queda
guardada en el JSON.

**Las dos condiciones posturales van en la misma sesión**, 3 repeticiones
quietas y 3 con movimiento por gesto, repartidas con semilla derivada del
`subject_id`. Comparten sujeto, colocación del brazalete y calibración, que es
lo que hace pareada la comparación entre ellas. Si fueran dos sesiones
distintas, la diferencia entre condiciones vendría mezclada con la de montaje.

En las repeticiones con movimiento, las tres posiciones se recorren dentro de
la contracción, 3.3 s cada una, y el orden de partida rota entre repeticiones
para que ninguna posición caiga siempre en el primer tramo, que es el que
pierde su primer segundo por el margen de entrada.

**Reposo en movimiento.** Tres veces por sesión, con la misma temporización
que un gesto, el participante recorre las tres posiciones con la mano
relajada. Va etiquetado como Rest, en la condición dinámica, con
`bloque_tipo` igual a `reposo_dinamico`. Las repeticiones se parten en tres
tramos, de la 1 a la 2, de la 3 a la 4 y de la 5 a la 6, y en cada tramo se
sortea con semilla del `subject_id` una repetición y un lugar dentro de ella.
El orden de los gestos no cambia: el reposo se intercala entre ellos.

Sin él, en la condición dinámica "brazo en movimiento" significaría casi
siempre "hay gesto", y el acelerómetro podría acertar por ese atajo en vez de
por compensar la postura.

**El margen de entrada de 1000 ms no se reduce.** Como el orden está
contrabalanceado, el participante no puede anticipar el gesto, y elegir entre
cuatro alternativas añade tiempo de reacción.

## Cambiar tiempos o colores

Todo está en `captura/config_captura.py` y en ningún otro sitio. Al construir
la sesión se comprueba que los márgenes caben en su bloque y que la rampa no
se sale del margen de entrada, así que un error de edición sale al instante y
no a mitad de una sesión.

```bash
python Modulo2_Pipeline_DL/captura/protocolo.py dinamico
```

Eso imprime, sin grabar nada, el orden de gestos, la duración y el balance de
clases con los tiempos que haya puestos.

## Problemas frecuentes

| Síntoma | Causa probable |
|---|---|
| `could not open port` | Puerto equivocado, o el monitor serie del IDE de Arduino lo tiene tomado |
| Tasa de 50 en vez de 100 | El adaptador USB no sostiene 921600 |
| Todo plano en la prueba | El firmware no está adquiriendo, o los LED no se autocalibraron |
| Un canal plano | Módulo despegado o LED muerto. Ver el manual de armado |
| La ventana del participante tapa la del operador | Salga de pantalla completa con Escape |
| Aviso de imágenes faltantes | Faltan PNG en `assets/`. La sesión corre igual |
| `ya existe. Los CSV de sesion nunca se sobrescriben` | Está repitiendo una sesión en el mismo segundo. Espere o cambie de carpeta |
