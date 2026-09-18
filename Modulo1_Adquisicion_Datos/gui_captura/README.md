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

## Instalación

Python 3.12. Tkinter viene con la biblioteca estándar, así que la única
dependencia es pyserial.

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

4. Con el participante en reposo, autocalibre los LED mandando `A` por un
   monitor serie, o hágalo antes de abrir la app. La autocalibración es
   bloqueante y dura unos 10 s.

## Paso a paso de la sesión

### 1. Configuración

En la ventana del operador, rellene:

| Campo | Qué poner |
|---|---|
| `subject_id` | Número entero, 1, 2, 3. Es la semilla del contrabalanceo |
| `id anonimo` | S01, S02. Es lo que va al CSV, nunca el nombre |
| `puerto` y `baudios` | Los baudios ya vienen en 921600, que es el del firmware |
| `bloque` | `estatico` o `dinamico` |
| `carpeta` | Dónde se guardan el CSV y el JSON |
| Datos del participante | Edad, sexo, mano dominante, circunferencia del antebrazo y posición del brazalete en cm |

La circunferencia y la posición del brazalete se anotan porque, sin ellas, un
sujeto que rinde peor que los demás queda sin explicación posible.

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

- Mire la pantalla, no el teclado ni su mano.
- En **PREPARESE** verá el gesto que viene, con cuenta de 3, 2 y 1.
- En **CONTRAIGA** ejecute el gesto y manténgalo los 10 s. **Suba la fuerza
  poco a poco durante el primer segundo**, siguiendo la barra amarilla, sin
  dar un golpe.
- En **DESCANSE** relaje la mano del todo.
- Si se equivoca de gesto, que lo diga y siga. No hay que disimular.
- En el bloque dinámico, además del gesto, la pantalla pide una posición del
  brazo. Muévase lento y continuo, sin sacudidas.

### 4. Durante la sesión

Pulse **Iniciar**. La sesión dura 8.7 min y va sola.

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
| `subject_id`, `repetition_id`, `label`, `bloque_tipo`, `en_margen`, `es_calibracion` | Protocolo |
| `id_participante`, `bloque_postura`, `posicion_brazo`, `ts_pc_ms`, `descartada` | Sesión guiada |
| `fase` | La añade `anotar_fases.py` al cerrar |

El giroscopio se graba aunque el modelo no lo use. Sus bytes ya viajan en la
misma lectura I2C, así que no cuesta nada guardarlo, y puede hacer falta en el
bloque dinámico. El descarte a los 8 canales ocurre en `preprocesamiento.py`,
nunca en la captura. Una sesión no se repite, y recuperar un canal después
costaría volver a grabar con los diez voluntarios.

**Ojo con la palabra fase.** En `bloque_tipo` las fases son calibración,
preparación, contracción y reposo. La columna `fase` de `fases.py` es otra
cosa: reposo, dinámica, meseta y reacción.

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

Cuatro gestos activos por seis repeticiones, con **orden contrabalanceado e
intercalado**: cada repetición presenta los cuatro gestos una vez, en un orden
que se elige para que todos los pares de gestos consecutivos aparezcan un
número parecido de veces. La semilla es el `subject_id`, así que la sesión es
reproducible y cada sujeto recibe un orden distinto. La secuencia usada queda
guardada en el JSON.

En el bloque dinámico las tres posiciones del brazo rotan por gesto, de modo
que cada gesto pasa dos veces por cada posición. Así la posición no queda
confundida con el gesto ni con la fatiga.

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
