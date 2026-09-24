# Nota de diseño, construcción de los 5 módulos LMG

Actualizada: 2026-09-24 (sección "Estado vigente"); cuerpo original del
2026-09-18. Fuentes: Godoy et al., *Lightmyography Based Decoding of
Human Intention Using Temporal Multi-Channel Transformers*, IROS 2022 (Fig. 1 y
Sec. III-A), Shahmohammadi et al. 2023 (Sci Rep 13:327), Guan et al. 2025
(HDLMG), Khalikov et al. 2026 (Sci Rep, optomiografía), `Modulo1/config.h`,
`Modulo3/config.h`, ficha CIS 2026 v2.

## Estado vigente (2026-09-24)

Esta sección manda sobre el resto de la nota. Lo que sigue más abajo se
conserva como historia de las decisiones; donde contradice a esta sección, está
superado y lo indica.

**Construcción del módulo: un PCB propio por módulo.** Proyecto de KiCad
`Documents/KiCad/LMG_Sensor`, con archivos de fabricación, instrucciones de
soldadura y tabla de interfaz con la carcasa en `LMG_Sensor/fab/`.

| Aspecto | Antes (perfboard) | Ahora (PCB del módulo) |
|---|---|---|
| Conexión | cables sueltos a la placa principal | **conector J1 de 4 pines: 1 VCC, 2 GND, 3 OUT, 4 LED** |
| OPT101 | en zócalo DIP-8 | **soldado directo, sin zócalo**, en la cara inferior (la de la piel) |
| LED | en una pestaña aparte, con hilos esmaltados | **en el mismo PCB**, cara inferior, en una de **tres posiciones: 9, 11 o 13 mm** del centro del OPT101 |
| Altura del LED | al ras de la cara de contacto | se ajusta al soldar para que su punta quede en el **plano de la piel, Z_piel** (tabla de interfaz) |
| Resistencia del LED | en la placa principal | **R1, 100 ohm, en el PCB del módulo** |
| Desacople del OPT101 | no había | **C1, 100 nF, en el PCB del módulo** |
| Puente de realimentación | puente a mano | **pista del PCB entre los pines 4 y 5**; el pin 2 queda sin conexión |

**Cadena de lectura (firmware M1-2026.09.24 y M3-2026.09.24):**

- **Sin multiplexor CD74HC4067.** Las salidas OUT entran directas a **dos
  ADS1115**: el #1 en 0x48 (ADDR a GND) lee los módulos 1, 2 y 3 por A0, A1 y
  A2; el #2 en 0x49 (ADDR a VDD) lee los módulos 4 y 5 por A0 y A1.
- **GAIN_TWO (±2.048 V)** en los dos, porque solo leen canales ópticos. El
  firmware avisa si una lectura llega al máximo (`[ADC] AVISO ... recorta`) y
  cuenta los recortes por sesión (`[OPTICA_RECORTES]`, que queda en el JSON).
- **LED:** GPIO **13, 25, 27, 16, 17**. El LED 2 pasó del GPIO14 al 25, porque
  el 14 emite pulsos durante el arranque.
- **FSR (Módulo 3):** ADC interno del ESP32, solo ADC1: GPIO 32, 33, 34, 35 y
  36, a 11 dB. Divisor de **22 kohm** en lugar de 10 kohm, con 100 nF en cada
  pin. Umbrales recalculados a 410 y 372 mV. Se leen los cinco en cada ciclo de
  10 ms; ya no hay escaneo rotativo.
- **Tiempo de ciclo estimado:** Módulo 1 ~8.9 ms, Módulo 3 ~9.4 ms (peor ciclo
  ~9.8 ms con la escritura de la rampa de servos). El autotest del arranque mide
  el real.
- **Sesiones:** las grabadas antes de M1-2026.09.24 y las grabadas después no se
  mezclan sin comprobar que su reposo y su excursión por canal son comparables.

**Pendiente de unificar: espesor del taco.** Esta nota fijaba 4 mm frente al
OPT101. La tabla de interfaz del PCB calcula Z_piel con un taco de 5 mm. Hay
que decidir uno y dejarlo en los dos documentos.

El cableado completo, cable por cable, está en `claude/manual-armado-hardware.md`.

## El principio que manda todo el diseño

Godoy et al. describen el mecanismo así:

> "The LED sends a light signal that reaches the skin through a compressible
> silicone medium and the change of light after being reflected on the skin
> surface is detected using the photodetector."

El taco de silicona **es el transductor**, no la carcasa. Si las ópticas tocan
la piel no hay medio compresible y no hay señal LMG.

| Requisito | Valor | Razón |
|---|---|---|
| Silicona | **transparente o incolora**, curado por platino | La luz la atraviesa en ambos sentidos |
| Dureza | blanda, Shore A menor o igual a 10 | Tiene que deformarse con el abultamiento de la piel |
| Espesor del taco | 4 mm frente al OPT101, **igual en los 5 módulos** | Espesores distintos dan respuestas distintas a la misma contracción |
| Ópticas | OPT101 detrás del taco, LED tocando la piel (en Z_piel) | Ver la sección del LED SMD y el estado vigente |
| Aislamiento LED a fotodiodo | tabique opaco hasta la cara de contacto | La silicona transparente y el PLA claro conducen luz directa |

## Cambio a LED SMD 1206 (decisión del 2026-09-18)

> **Superado en parte (2026-09-24).** El LED ya no va en una pestaña aparte: va
> en el PCB del módulo, en la cara inferior, y su altura se ajusta al soldar
> para que toque la piel. El PCB admite el LED de 5 mm por sus patas o un SMD
> sostenido por dos pines. La separación deja de ser 12.7 mm: hay tres
> posiciones, 9, 11 y 13 mm. Siguen vigentes el LED tocando la piel, el OPT101
> detrás del taco, la prohibición del hueco de aire y el tabique opaco.

El asesor pidió LED planos tipo SMD. Se compraron LED **IR 940 nm en encapsulado
1206** (AliExpress, lote de 20, variante "1206 Emitter"). Los LED IR de 5 mm que
ya estaban comprados quedan como material de banco de pruebas.

**Antecedente citable**: Khalikov et al. (2026) usan el **Kingbright
KP-3216F3C**, un SMD 1206 de 940 nm (1.2 mW, 120 grados), con el fototransistor
KP-3216P3C, y una separación LED a detector de **12.45 mm**. Guan et al. (2025)
montan los IR sobre circuito flexible, doblados para que toquen la piel mientras
los verdes quedan 5 mm atrás. Shahmohammadi et al. (2023) obtuvieron la mejor
señal IR con **0 mm de silicona**, en contacto con la piel, y la mejor señal
verde a 5 mm.

Consecuencias de diseño:

- **El LED va al ras de la cara de contacto**, o bajo una capa de protección de
  silicona transparente de 0.5 a 1 mm como máximo.
- **El OPT101 se queda detrás del taco de 4 mm.** La silicona solo llena la
  ventana frente al OPT101.
- **Prohibido el hueco de aire** entre el LED y la piel. El aire refleja en cada
  cambio de medio, no transmite la deformación y deja que la luz del LED llegue
  al detector rebotando por dentro de la carcasa.
- **El LED no puede ir en la misma placa que el OPT101.** El cuerpo del OPT101
  tiene unos 4.5 a 5 mm, así que el LED quedaría hundido esa distancia. Va
  soldado en una pestaña aparte, un recorte de PCB o fibra, pegada en el plano
  de contacto y cableada con dos hilos esmaltados hacia la placa principal.
- **Separación LED a centro del OPT101: 12.7 mm** (5 por 2.54, para que caiga en
  la grilla del perfboard y quede cerca de los 12.45 mm de Khalikov). Reemplaza
  los 15.24 mm de la versión anterior.
- **Tabique opaco de 2 mm** entre LED y OPT101, desde la cara de contacto hasta
  arriba.
- **Los 5 módulos son idénticos**: mismo espesor de taco, misma separación,
  misma resistencia, mismo riel. La luminosidad del LED y la responsividad del
  detector aparecen en el índice I, así que una asimetría mecánica entre módulos
  entra al modelo como si fuera señal muscular.

## Conexión eléctrica de un módulo

- **OPT101 alimentado a 3.3 V**, no a 5 V. Su salida llega hasta unos 2.15 V,
  así que a 3.3 V nunca supera el límite de entrada del ADS1115 (VDD más 0.3 V).
  GND común. La salida OUT (J1-3) va directa a una entrada de uno de los dos
  ADS1115 (ver el estado vigente).
- **LED IR con la resistencia de 100 ohm del PCB** desde un GPIO del ESP32
  (unos 18 mA con Vf de 1.3 V). Cátodo a GND. El GPIO se conecta a J1-4.
- **Un GPIO por LED**: 13, 25, 27, 16, 17. Nunca los 5 encendidos a la vez si
  cuelgan directo del GPIO.

## Firmware

Lo que pedía esta nota, en su redacción original, era agregar el control de LED
porque se creía que no existía. Ver el apéndice del final: ya existe. Lo que
esta nota fija y el firmware toma como entrada es:

- Pines `PIN_LED_LMG_1..5` en 13, 25, 27, 16, 17 (el LED 2 estaba en el 14
  hasta el 2026-09-24).
- `LED_SETTLE_US` de 300 us.
- Trama oscura con **una sola trama por ciclo, rotando de canal**, no cinco.
- `setDataRate(RATE_ADS1115_860SPS)`. Con el valor por defecto de la librería
  Adafruit (128 SPS) cada lectura cuesta unos 8 ms y no se llega a 100 Hz.
- **Orden de operaciones**: primero resta de trama oscura, después normalización
  por reposo del sujeto.

## Compras

| Ítem | Dónde | Precio | Estado |
|---|---|---|---|
| **OPT101P** por 5, DIP-8 | AliExpress, 889 Sold Store (Choice, envío gratis) | S/ 92.11 el lote | pedido |
| **LED IR SMD 1206, 940 nm** por 20 | AliExpress, AXZHDZ (Choice), variante "1206 Emitter" | S/ 5.79 el lote | **pedido**, llega cerca del 25 de septiembre |
| LED IR 5 mm 940 nm | ya disponibles | | solo para banco de pruebas |
| **Silicona de platino** | Silika, Jr. Puno 552 Tda. 201 (Mesa Redonda) | S/ 70 el kg | pendiente |

**Mouser quedó descartado**: tarifa plana de S/ 200 de envío a Perú. Para
original TI certificado, DigiKey o LCSC.

**Verificación al recibir el OPT101**: el auténtico es de plástico transparente
con el dado cuadrado visible. Si llega un DIP-8 negro opaco, es falso.

**No se encontró LED IR SMD en tiendas de Lima.** Ni MercadoLibre Perú, ni
Naylamp, ni Paruro. Lo local disponible es el IR de 5 mm y los SMD en colores
visibles.

## Silicona: elegida la local

**Silika, Caucho de Silicona RTV PLATINO 1510, 1 kg (500 g A más 500 g B),
S/ 70**, rebajada de S/ 105.

Ficha del proveedor: "Semi-Traslúcido e **incoloro** en GEL. Dureza **Shore
10-A**. Consistencia similar al Tejido Humano MEDIUM. Compatible con todas las
siliconas de cura por adición o platino. Ratio 1:1 por peso o volumen. Tiempo de
trabajo 15-20 min. Curado 4-6 h. Viscosidad media. NO utiliza catalizador."

Comparación con la Dragon Skin FX-Pro que figura en el Excel de materiales:

| | Dragon Skin FX-Pro | Silika RTV Platino 1510 |
|---|---|---|
| Curado | platino | platino |
| Color | translúcido | semi-traslúcido incoloro |
| Dureza | Shore **2A** | Shore **10A** |
| Tiempo de trabajo | 12 min | 15-20 min |
| Curado | 40 min | 4-6 h |
| Precio | US$ 42.99 más envío, cerca de S/ 160 a 200 | **S/ 70** |
| Disponibilidad | importar de Amazon | Mesa Redonda, mismo día |

La única diferencia relevante es la dureza. Se empieza con la 1510 por precio y
disponibilidad. Si la señal sale débil, las perillas antes de importar son bajar
`pad_t` de 4 a 2.5 mm en el `.scad` y reimprimir, y subir la tensión de la
correa.

**Ojo**: los "RTV Tipo 4/5/6/7" de esa misma tienda (S/ 44 a 56) son de
**estaño**, no de platino. No sirven.

**El pigmento negro del BOM ya no hace falta**: el taco va transparente y la
carcasa se imprime en filamento negro.

Cantidad necesaria: los 5 tacos son unos 10 g. Un kilo alcanza para decenas de
intentos.

Otros locales de Silika: Av. Ignacio Merino 2151 (Lince), Av. Caminos del Inca
257 int. 341 (Surco).

## Carcasa impresa

Archivos generados: `carcasa_modulo_LMG.stl` y `carcasa_modulo_LMG.scad`
(paramétrico). **Ambos quedaron desactualizados con el cambio a SMD** y hay que
regenerarlos con la separación de 12.7 mm y el asiento del SMD al ras.

La carcasa **es a la vez molde y alojamiento permanente**. Tabique opaco de 2 mm
de la cara de la piel hasta arriba. Ranuras laterales de anclaje para que el
taco curado quede trabado en el plástico.

Imprimir en **negro, sin soportes, cara Z=0 sobre la cama, paredes y tabique al
100 por ciento de relleno**.

**Antes de imprimir las 5**, medir con vernier y ajustar en el `.scad`: `opt_h`
(alto del cuerpo del OPT101 o del breakout CJMCU-101, estimado 4.5 a 5.0) y el
asiento del SMD (1206 nominal 3.2 por 1.6 por 1.1 mm).

## Alimentación del sistema

- **Batería LiPo 2S 1500 mAh con XT60.** El conector JST queda corto para el
  pico de corriente de 5 servos MG90S.
- **Dos XL4015 en el BOM**: uno a 5.0 V para el ESP32 y la lógica, otro a 6.0 V
  para los servos. Tierras comunes.
- **Nunca alimentar los servos desde el pin 5 V del ESP32.**
- **Cargador iMax B3**: sirve para 2S, es lento y sin telemetría. Cargar siempre
  en bolsa ignífuga y con supervisión.

## Secuencia de trabajo

1. **Protoboard, sin soldar nada.** El OPT101P es DIP-8 y se pincha directo.
   Validar alimentación, nivel de salida, lectura del ADS1115, disparo
   secuencial y resta de trama oscura, usando los LED IR de 5 mm.
2. **Imprimir una sola carcasa** de prueba, meter las piezas en seco y verificar
   que topan donde deben.
3. Imprimir las 5, colar, curar.
4. ~~Recién al final, PCB con zócalo DIP-8 para que el OPT101 siga siendo
   desmontable.~~ Superado: el PCB del módulo existe y lleva el OPT101 soldado
   sin zócalo, porque el zócalo cambia su altura.

## Parámetros del paper de referencia

- Muestreo del brazalete: **60 Hz**. El proyecto apunta a 100 Hz, que es mejor.
- Mejor ventana: **170 ms con 90 por ciento de solape**.
- Protocolo: 9 sujetos, 5 gestos (reposo, extensión, pinza, trípode, potencia),
  5 repeticiones, 10 s de reposo más 10 s de gesto.
- Exactitud sujeto específico: TMC-T 94.03, TMC-ViT 93.69, CNN 89.84, LSTM
  92.85, LDA 86.64, SVM 88.71, RF 87.72.
- Sujeto genérico: TMC-ViT 90.17 con ventana de 170 ms.

## Riesgos abiertos

- **Dureza 10A frente a 2A.** Puede que la señal salga más débil de lo deseado.
- **Presupuesto temporal del Módulo 3.** Ver el apéndice, que lo recalcula
  línea por línea.
- **Procedencia de los OPT101 de AliExpress.** Si el jurado exige trazabilidad,
  comprar además unidades certificadas en DigiKey o LCSC.

---

# Apéndice del 2026-09-17: contraste contra el firmware real

Añadido al revisar el firmware para aplicar esta nota. Corrige dos puntos del
cuerpo del documento.

## 1. El control de LED ya existe

La sección de firmware decía que no hay pines definidos y que `leerCanal()` solo
conmuta el MUX. No es así desde la Tarea 3. `optica_lmg.h` y `optica_lmg.cpp`,
idénticos en los Módulos 1 y 3, ya implementan:

- un LED por canal, encendido solo mientras se lee ese canal, contra la diafonía
  óptica entre módulos vecinos,
- trama oscura por canal, `valor = L - D`, con su análisis del residuo del
  parpadeo de 120 Hz,
- autocalibración de ganancia por PWM, que fija el reposo cerca del 35 por
  ciento del fondo de escala y guarda el reposo por canal en NVS,
- el orden de operaciones que pide esta nota: primero la resta de la trama
  oscura, después la normalización por reposo del sujeto, en `calibracion.cpp`.

El PWM no es un adorno. La autocalibración regula la corriente de cada LED por
duty, así que los pines se configuran con `ledcAttach` y no como salida digital.
Apagado equivale a duty 0.

## 2. Cambios aplicados a partir de esta nota

| Constante | Antes | Ahora | Motivo |
|---|---|---|---|
| `PIN_LED_LMG_1..5` | 16, 17, 18, 19, 23 | 13, 14, 27, 16, 17 | PCB de los módulos SMD |
| `ASENTAMIENTO_LED_US` | 200 | `LED_SETTLE_US` 300 | Esta nota |
| comentario del manejo del LED | transistor NPN o MOSFET | ataque directo con 100 ohm | Esta nota |
| `FONDO_ESCALA_UTIL_MV` | 3700 | 2000 | El OPT101 pasa a 3.3 V y satura hacia Vs menos 1.3 V |

## 3. El presupuesto temporal, recalculado

Costo por lectura con ADS1115 a 860 SPS, con el asentamiento de 300 us de esta
nota:

| lectura | MUX | LED | conversión | I2C | total |
|---|---|---|---|---|---|
| canal LMG con su LED | 50 | 300 | 1163 | 240 | 1753 us |
| trama oscura rotativa | 50 | 300 | 1163 | 240 | 1753 us |
| un FSR | 50 | | 1163 | 240 | 1453 us |
| IMU MPU6050 | | | | | 400 us |

Ciclo del Módulo 3 con la trama oscura rotativa:

| concepto | subtotal |
|---|---|
| 5 canales LMG | 8765 us |
| 1 trama oscura | 1753 us |
| IMU | 400 us |
| subtotal sin FSR | **10 918 us** |
| 1 FSR | 1453 us |
| total | **12 371 us** |

**Los 5 LMG más la trama oscura ya suman 10 518 us**, o sea que se pasan de los
10 ms antes de la IMU y antes de cualquier FSR. De ahí se sigue:

- **Bajar la tasa de los FSR no alcanza.** Leer un FSR en uno de cada cuatro
  ciclos deja el peor ciclo en 12 371 us y el ciclo típico en 10 918 us.
- **El segundo ADS1115 en 0x49 para los FSR tampoco alcanza.** Quita 1453 us y
  siguen faltando 918 us.
- **El Módulo 1 tampoco cabe**, y no tiene FSR: los mismos 10 918 us.

Lo que sí cierra la brecha, pendiente de decisión:

| medida | ahorro | ciclo |
|---|---|---|
| asentamiento de LED de vuelta a 200 us | 600 us | 10 318 us |
| leer la IMU dentro de la espera de una conversión del ADC | 400 us | 10 518 us |
| modo continuo en el ADS1115, sin reescribir configuración por lectura | 720 us | 10 198 us |
| las tres juntas | 1720 us | **9198 us, cabe** |
| ~~repartir los 5 LMG entre dos ADS1115 que convierten en paralelo~~ | ~~4400 us~~ | ~~6500 us~~ |

Las tres primeras son de firmware y dos de ellas atacan el costo de I2C, que en
`config.h` es un valor **estimado y no medido**, así que el margen real solo se
conoce midiendo. `autotestTemporal()` mide el ciclo real al arrancar y con el
comando 'T'.

**Mientras esto no se decida, `TRAMA_OSCURA_HABILITADA` sigue atada al ADS1015 y
con el ADS1115 soldado se lee solo L, un LED a la vez.**

**Corrección del 2026-09-24 a la última fila.** Dos ADS1115 no convierten los
LMG en paralelo: solo puede haber un LED encendido a la vez, así que las cinco
conversiones siguen siendo una detrás de otra. La razón válida para usar dos
ADS1115 es otra: sacar los FSR del ADC (pasan al ADC interno del ESP32) y
eliminar la espera del multiplexor. Con eso, y sin trama oscura, el ciclo queda
en ~8.9 ms en el Módulo 1 y ~9.4 ms en el Módulo 3. Es la arquitectura vigente
(ver el estado vigente, al principio).
