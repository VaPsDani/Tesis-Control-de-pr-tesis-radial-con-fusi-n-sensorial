# Manual de armado del hardware

Para armar el brazalete LMG y la prótesis desde cero, sin experiencia previa en
electrónica. Cada paso dice qué hacer y qué resultado esperar. Si un paso no da
el resultado esperado, no siga adelante: vaya a la sección de fallas típicas.

Actualizado: 2026-09-24, para `FIRMWARE_VERSION` M1-2026.09.24 y M3-2026.09.24.

Fuentes: `claude/nota-diseno-modulos-lmg.md`, `Modulo1_Adquisicion_Datos/config.h`,
`Modulo3_Inferencia_Control/config.h` y el proyecto de KiCad del módulo,
`Documents/KiCad/LMG_Sensor` (archivos de fabricación, instrucciones de
soldadura del PCB y tabla de interfaz con la carcasa en su carpeta `fab/`). Si
este manual y el firmware no coinciden, manda el firmware y hay que corregir el
manual.

**Qué cambió respecto de la versión anterior de este manual**

- Cada módulo LMG es ahora un **PCB propio** con un conector de 4 pines (VCC,
  GND, OUT, LED). El OPT101 va soldado directo, **sin zócalo**, y el LED va en el
  mismo PCB, **sin pestaña aparte**.
- **Ya no hay multiplexor CD74HC4067.** Las cinco salidas OUT entran directas a
  **dos ADS1115**, uno en 0x48 y otro en 0x49.
- Los cinco **FSR** del Módulo 3 van al **ADC interno del ESP32**, con un
  divisor de **22 kohm** en lugar de 10 kohm y un condensador de 100 nF.
- El **LED 2** pasa del GPIO14 al **GPIO25**.
- Corrección: la versión anterior indicaba un puente entre los pines 2 y 3 del
  OPT101. **Era un error.** El pin 2 va sin conexión y el puente es entre los
  pines 4 y 5. En el PCB del módulo ese puente ya es una pista.

**Regla de oro: nunca conecte la batería mientras cablea.** Todo se cablea con
el sistema apagado y se enciende solo para las pruebas.

---

## 1. Glosario

| Término | Qué significa |
|---|---|
| **GPIO** | Pin de propósito general del ESP32. El firmware lo puede poner en alto (3.3 V) o en bajo (0 V), o usarlo para leer. |
| **Ánodo** | Pata positiva de un LED o diodo. La corriente entra por ahí. En un LED de 5 mm es la pata larga. |
| **Cátodo** | Pata negativa. La corriente sale por ahí hacia tierra. En un LED de 5 mm es el lado plano del reborde. |
| **Vf** | Voltaje directo. Lo que el LED "consume" cuando conduce. En el LED IR de 940 nm es de unos 1.3 V. |
| **Resistencia limitadora** | Resistencia en serie con el LED que fija la corriente. En este proyecto va soldada en el PCB de cada módulo (100 ohm). |
| **Riel** | Línea de alimentación común a la que se conectan varios componentes, por ejemplo el riel de 3.3 V o el de 6.0 V. |
| **Tierra común** | Todos los negativos unidos entre sí. Sin tierra común, dos circuitos no pueden compararse voltajes y las lecturas salen sin sentido. |
| **I2C** | Bus de dos cables, SDA (datos) y SCL (reloj), al que se conectan varios chips en paralelo. Cada uno tiene una dirección distinta, por ejemplo 0x48. |
| **Pull-up** | Resistencia que une SDA o SCL con 3.3 V. El bus I2C la necesita para funcionar. Casi todas las placas de módulo traen las suyas. |
| **PWM** | Señal cuadrada que se enciende y apaga muy rápido. Variando cuánto tiempo está encendida se regula el brillo de un LED o la posición de un servo. |
| **ADC** | Conversor analógico a digital. Traduce un voltaje a un número. El ADS1115 es de 16 bits; el ESP32 trae además uno propio, de 12 bits y menos preciso. |
| **Divisor** | Dos resistencias en serie. El voltaje del punto medio depende de la relación entre ambas. Así se convierte la resistencia de un FSR en un voltaje legible. |
| **Conector J1** | Los 4 pines de cada módulo LMG: 1 VCC, 2 GND, 3 OUT, 4 LED. |

---

## 2. Lista de materiales

### Electrónica principal

| Componente | Cantidad | Para qué sirve |
|---|---|---|
| ESP32 WROOM 32 devkit | 1 por módulo (1 y 3) | Cerebro. Lee sensores, corre el modelo y manda los servos. |
| ADS1115 (placa de módulo) | **2** por ESP32 | Convierte a números el voltaje de los cinco sensores ópticos, con 16 bits. El primero lee los módulos 1 a 3 y el segundo los 4 y 5. |
| MPU6050 (placa GY-521) | 1 | Mide aceleración y giro del antebrazo, que entran al modelo junto al LMG. |
| PCA9685 | 1 | Genera las señales de los 5 servos sin ocupar pines del ESP32. Solo Módulo 3. |
| **PCB del módulo LMG** | 5 | Ver la lista del módulo, abajo. |
| Cable de 4 hilos | 5 tramos | Une el conector J1 de cada módulo con la placa principal: VCC, GND, OUT y LED. |
| FSR402 | 2 | Sensor de presión de la yema del pulgar y del índice. Solo Módulo 3. |
| DF9-40 | 3 | Sensor de presión de las yemas medio, anular y meñique. Solo Módulo 3. |
| **Resistencia de 22 kohm, 1 %** | 5 | Divisor de cada FSR. Reemplaza a la de 10 kohm. Solo Módulo 3. |
| **Condensador cerámico de 100 nF** | 5 | Uno en cada pin del ADC de los FSR, a tierra. Filtra el ruido del ADC del ESP32. Solo Módulo 3. |
| Servo MG90S | 5 | Mueve cada dedo. Solo Módulo 3. |

### Lista de cada PCB de módulo (por 5)

La lista exacta, con referencias y huellas, está en
`LMG_Sensor/fab/bom/LMG_Sensor_BOM.csv`.

| Componente | Cantidad por módulo | Notas |
|---|---|---|
| OPT101P, DIP-8 | 1 | **Sin zócalo**: el zócalo cambia la altura del sensor. |
| LED IR de 940 nm | 1 | De 5 mm, por sus patas, o SMD sostenido por dos pines de 0.64 mm. Se suelda en **una sola** de las tres posiciones (9, 11 o 13 mm). |
| Resistencia de 100 ohm, 1206 | 1 | R1. Limita la corriente del LED a unos 18 mA. |
| Condensador de 100 nF, 1206 | 1 | C1. Desacople del OPT101. |
| Tira de pines 1 x 4, paso 2.54 mm | 1 | J1. |

### Alimentación

| Componente | Cantidad | Para qué sirve |
|---|---|---|
| LiPo 2S 1500 mAh con XT60 | 1 | Batería. Da 7.4 V nominales, 8.4 V a plena carga. |
| Conector XT60 hembra | 1 | Recibe la batería. Aguanta el pico de corriente de los 5 servos, que el JST no aguanta. |
| Interruptor de 3 A o más | 1 | Corta la batería antes de los reguladores. |
| XL4015 | 2 | Reductor. Uno baja a 5.0 V para la lógica y otro a 6.0 V para los servos. |
| Cargador iMax B3 | 1 | Carga la LiPo 2S. |
| Bolsa ignífuga para LiPo | 1 | Contiene el fuego si la batería falla durante la carga. |
| Capacitor electrolítico de 470 a 1000 uF, 16 V | 1 | Se pone en el riel de 6.0 V. Amortigua el tirón de corriente cuando arrancan los servos. |
| Capacitor cerámico de 100 nF | 5 | Uno junto a la alimentación de cada placa I2C (dos ADS1115, MPU6050, PCA9685). Filtra el ruido. |

### Mecánica y taller

| Componente | Cantidad | Para qué sirve |
|---|---|---|
| Silicona de platino Silika RTV 1510, Shore 10A | 1 kg | Es el transductor. El taco se comprime cuando el músculo se abulta y eso cambia la luz que llega al fotodiodo. |
| Filamento PLA negro | 1 rollo | Carcasa de los módulos. El negro evita que la luz viaje por dentro del plástico. |
| Tornillos M2 e insertos roscados M2 | 2 por módulo | Sujetan el PCB a la carcasa. Ver la tabla de interfaz. |
| Cinta aislante negra | 1 | Tapa por la cara superior el anillo sin cobre del pin 2 del OPT101. |
| Cable de silicona AWG 26 y AWG 20 | varios | AWG 26 para señales, AWG 20 para la alimentación de los servos. |
| Termorretráctil surtido | 1 | Aísla cada unión soldada. |
| Cinta de correa y velcro | 1 | Sujeta el brazalete al antebrazo con tensión pareja. |

### Instrumentos

| Instrumento | Para qué sirve |
|---|---|
| Multímetro | Mide voltaje, continuidad, resistencia y corriente. Es el único modo de saber qué está pasando. |
| Vernier o calibrador | Mide las piezas reales antes de imprimir y la altura del OPT101 soldado. |
| Cautín con punta fina y estaño delgado | Soldar los PCB y los cables. |
| Cámara de un celular | Los LED IR no se ven a simple vista, pero la cámara sí los muestra. |

---

## 3. Advertencias de seguridad

> ### ⚠ ADVERTENCIA 1: el OPT101 va a 3.3 V, nunca a 5 V
> Alimentado a 5 V su salida puede llegar a casi 4 V, y entra directa al
> ADS1115, que está alimentado a 3.3 V: una entrada por encima de la
> alimentación más 0.3 V lo daña. Alimentado a 3.3 V la salida no pasa de unos
> 2.15 V y todo queda protegido. El pin 1 (VCC) del conector J1 va **siempre** al
> riel de 3.3 V.

> ### ⚠ ADVERTENCIA 2: los servos nunca se alimentan del pin 5 V del ESP32
> Cinco MG90S piden picos de varios amperios. El regulador de la placa del
> ESP32 entrega unos cientos de miliamperios. Conectarlos ahí reinicia la placa
> en el mejor caso y la quema en el peor. Los servos van al riel de 6.0 V del
> segundo XL4015, con su propia tierra unida a la del resto.

> ### ⚠ ADVERTENCIA 3: ajustar y medir cada XL4015 antes de conectar carga
> El XL4015 sale de fábrica en un voltaje cualquiera. Conéctelo a la batería
> **sin nada en la salida**, mida la salida con el multímetro y gire el
> potenciómetro hasta 5.0 V en uno y 6.0 V en el otro. Recién entonces
> conecte lo que alimenta. Un XL4015 que salió en 12 V destruye el ESP32 en un
> segundo.

> ### ⚠ ADVERTENCIA 4: la LiPo se carga en bolsa ignífuga y con supervisión
> El iMax B3 no tiene telemetría y es lento. Cargue siempre dentro de la bolsa,
> sobre una superficie que no arda, y no deje la carga sin vigilancia ni de
> noche. Una LiPo hinchada, golpeada o mojada se retira de servicio, no se
> carga.

> ### ⚠ ADVERTENCIA 5: respete la polaridad del LED y del OPT101
> En el LED de 5 mm la **pata larga es el ánodo** y va en el pad marcado «+»
> (pad redondo, «A» en la cara superior). El lado plano del reborde es el
> cátodo (pad cuadrado, «K»). El OPT101 lleva el **pin 1 en el pad de esquinas
> redondeadas**, marcado «1» en la cara superior. Un OPT101 al revés recibe la
> alimentación invertida y se quema al primer encendido.

> ### ⚠ ADVERTENCIA 6: nunca los cinco LED encendidos a la vez
> Cuelgan directo del GPIO a través de la resistencia de 100 ohm del módulo. Uno
> solo son unos 18 mA, que el pin tolera. El firmware enciende uno a la vez a
> propósito, tanto por la corriente como para evitar que la luz de un módulo
> llegue al fotodiodo del vecino. No escriba código de prueba que los encienda
> todos juntos.

---

## 4. Cableado

Colores sugeridos. Lo importante es ser consistente, porque el color es lo que
permite rastrear un error sin desarmar.

| Color | Significado |
|---|---|
| Rojo | 3.3 V |
| Naranja | 5.0 V |
| Amarillo | 6.0 V de servos |
| Negro | Tierra |
| Azul | SDA |
| Verde | SCL |
| Blanco | Señal analógica (OUT de un módulo, punto medio de un FSR) |
| Morado | Control de LED |

### 4.1 Tabla de conexiones completa

Es la tabla de referencia. Las secciones que siguen la detallan.

**Módulos LMG: conector J1 de cada módulo**

| Módulo | J1-1 VCC | J1-2 GND | J1-3 OUT | J1-4 LED |
|---|---|---|---|---|
| 1 | Riel de 3.3 V | Riel de tierra | ADS1115 **#1** (0x48), entrada **A0** | ESP32 **GPIO13** |
| 2 | Riel de 3.3 V | Riel de tierra | ADS1115 **#1** (0x48), entrada **A1** | ESP32 **GPIO25** |
| 3 | Riel de 3.3 V | Riel de tierra | ADS1115 **#1** (0x48), entrada **A2** | ESP32 **GPIO27** |
| 4 | Riel de 3.3 V | Riel de tierra | ADS1115 **#2** (0x49), entrada **A0** | ESP32 **GPIO16** |
| 5 | Riel de 3.3 V | Riel de tierra | ADS1115 **#2** (0x49), entrada **A1** | ESP32 **GPIO17** |

**Los dos ADS1115**

| Pin | ADS1115 #1 | ADS1115 #2 |
|---|---|---|
| ADDR | **Riel de tierra** → dirección **0x48** | **Riel de 3.3 V** → dirección **0x49** |
| A0 | OUT del módulo 1 | OUT del módulo 4 |
| A1 | OUT del módulo 2 | OUT del módulo 5 |
| A2 | OUT del módulo 3 | Riel de tierra (sin uso) |
| A3 | Riel de tierra (sin uso) | Riel de tierra (sin uso) |
| VDD | Riel de 3.3 V | Riel de 3.3 V |
| GND | Riel de tierra | Riel de tierra |
| SDA / SCL | GPIO21 / GPIO22 | GPIO21 / GPIO22 |
| ALRT | Sin conexión | Sin conexión |

**FSR del Módulo 3: ADC interno del ESP32, solo pines del ADC1**

| Dedo | Sensor | Pin del ESP32 | Canal | Resistencia del punto medio a tierra | Condensador del punto medio a tierra |
|---|---|---|---|---|---|
| Pulgar | FSR402 | **GPIO32** | ADC1_CH4 | **22 kohm, 1 %** | 100 nF |
| Índice | FSR402 | **GPIO33** | ADC1_CH5 | **22 kohm, 1 %** | 100 nF |
| Medio | DF9-40 | **GPIO34** | ADC1_CH6 | **22 kohm, 1 %** | 100 nF |
| Anular | DF9-40 | **GPIO35** | ADC1_CH7 | **22 kohm, 1 %** | 100 nF |
| Meñique | DF9-40 | **GPIO36** (VP) | ADC1_CH0 | **22 kohm, 1 %** | 100 nF |

GPIO39 queda libre como reserva del ADC1. **No use pines del ADC2** (0, 2, 4,
12 a 15, 25 a 27) para los FSR: el ADC2 deja de funcionar cuando el WiFi está
activo. El GPIO25 sí se usa, pero como salida del LED 2, y eso no le afecta.

**Resto del bus I2C**

| Pin | Hasta |
|---|---|
| MPU6050, AD0 | Riel de tierra → dirección **0x68** |
| PCA9685, A0 a A5 | Sin puentes soldados → dirección **0x40** |

### 4.2 Alimentación

| Desde | Hasta | Color | Notas |
|---|---|---|---|
| LiPo 2S, XT60 positivo | Interruptor, terminal 1 | Rojo AWG 20 | El interruptor corta solo el positivo. |
| Interruptor, terminal 2 | XL4015 número 1, IN+ | Rojo AWG 20 | Este regulador es el de 5.0 V. |
| Interruptor, terminal 2 | XL4015 número 2, IN+ | Rojo AWG 20 | Este es el de 6.0 V. Los dos cuelgan del mismo interruptor. |
| LiPo 2S, XT60 negativo | XL4015 número 1, IN- | Negro AWG 20 | |
| LiPo 2S, XT60 negativo | XL4015 número 2, IN- | Negro AWG 20 | |
| XL4015 número 1, OUT+ | ESP32, pin VIN | Naranja | Ajustado a 5.0 V **antes** de conectar. Ver advertencia 3. |
| XL4015 número 1, OUT- | ESP32, pin GND | Negro | |
| XL4015 número 2, OUT+ | PCA9685, borne V+ de potencia | Amarillo AWG 20 | Es el borne verde de tornillo, no el pin VCC. |
| XL4015 número 2, OUT- | PCA9685, borne GND de potencia | Negro AWG 20 | |
| XL4015 número 1, OUT- | XL4015 número 2, OUT- | Negro | **Tierra común.** Sin esto nada funciona. |
| Capacitor de 470 a 1000 uF, positivo | Riel de 6.0 V | Amarillo | Respete la polaridad del electrolítico. |
| Capacitor de 470 a 1000 uF, negativo | Tierra | Negro | |
| ESP32, pin 3V3 | Riel de 3.3 V | Rojo | De aquí cuelgan los cinco módulos LMG (J1-1), los dos ADS1115, el MPU6050, los FSR y la lógica del PCA9685. |
| ESP32, pin GND | Riel de tierra | Negro | |

### 4.3 Bus I2C

Los chips van en paralelo sobre los mismos dos cables: los dos ADS1115 y el
MPU6050 en el Módulo 1, y además el PCA9685 en el Módulo 3.

| Desde | Hasta | Color | Notas |
|---|---|---|---|
| ESP32, GPIO21 | SDA de ADS1115 #1, ADS1115 #2, MPU6050 y PCA9685 | Azul | |
| ESP32, GPIO22 | SCL de ADS1115 #1, ADS1115 #2, MPU6050 y PCA9685 | Verde | |
| Riel de 3.3 V | VDD o VCC de las cuatro placas | Rojo | En el PCA9685, solo la lógica. La potencia entra por el borne de tornillo. |
| Riel de tierra | GND de las cuatro placas | Negro | |
| ADS1115 #1, ADDR | Riel de tierra | Negro | **0x48**. |
| ADS1115 #2, ADDR | Riel de 3.3 V | Rojo | **0x49**. Si la placa trae una resistencia de ADDR a tierra, no pasa nada: el cable a 3.3 V manda. |

**Las resistencias de pull-up**

Cada placa de módulo trae sus propias pull-up en SDA y SCL, y todas quedan en
paralelo. Con los valores habituales de estas placas:

| Placa | Pull-up habitual |
|---|---|
| ADS1115 (placa azul o morada genérica) | 10 kohm |
| MPU6050 (GY-521) | 4.7 kohm |
| PCA9685 | 10 kohm |

| Equipo | Placas en paralelo | Resistencia resultante |
|---|---|---|
| Módulo 1 | 2 ADS1115 + MPU6050 | 10 ‖ 10 ‖ 4.7 = **~2.4 kohm** |
| Módulo 3 | 2 ADS1115 + MPU6050 + PCA9685 | 10 ‖ 10 ‖ 4.7 ‖ 10 = **~2.0 kohm** |

Para 400 kHz a 3.3 V, el rango bueno es de unos **1.5 a 3.3 kohm**: por debajo
de ~1 kohm los chips no alcanzan a bajar la línea, y por encima de ~3.3 kohm la
señal sube demasiado lento. **Con los valores habituales no hay que quitar
ninguna.**

La versión anterior de este manual decía que se quitaran las de dos de las
tres placas. No lo haga: si queda una sola de 10 kohm, el bus es demasiado
lento para 400 kHz.

**Cómo comprobarlo** (con todo cableado y **sin alimentación**):

1. Multímetro en resistencia, puntas entre SDA y el riel de 3.3 V. Esa lectura
   es directamente la resistencia de todas las pull-up en paralelo.
2. Repetir entre SCL y 3.3 V.
3. Entre 1.5 y 3.3 kohm: no toque nada.
4. Por debajo de 1.5 kohm (alguna placa trae 2.2 kohm o menos): quite primero las
   dos pull-up de la placa del **ADS1115 #2**, y vuelva a medir. Para
   encontrarlas, busque con continuidad las resistencias que van del pin SDA y
   del pin SCL al pin VDD de esa placa; suelen estar marcadas 103 (10 kohm), 472
   (4.7 kohm) o 222 (2.2 kohm). Desuéldelas o corte la pista de una de sus patas.
   Las otras resistencias de la placa (la de ADDR y la de ALRT) no se tocan.
5. Por encima de 3.3 kohm (alguna placa venía sin pull-up): añada una
   resistencia de 4.7 kohm de SDA a 3.3 V y otra de SCL a 3.3 V en la placa
   principal.

### 4.4 Los cinco módulos LMG

Cada módulo se une a la placa principal con un cable de 4 hilos, según la tabla
4.1. Mantenga el hilo OUT (blanco) lo más corto posible y lejos de los cables de
los servos: es una señal analógica pequeña.

- **VCC (J1-1)**, siempre al riel de 3.3 V. Ver advertencia 1.
- **GND (J1-2)**, al riel de tierra.
- **OUT (J1-3)**, a su entrada del ADS1115. Ya no pasa por ningún multiplexor.
- **LED (J1-4)**, a su GPIO. La resistencia de 100 ohm ya está en el PCB del
  módulo: el cable va directo del GPIO al pin 4.

**Si la placa es un ESP32 WROVER y no un WROOM 32**, los GPIO 16 y 17 están
tomados por la PSRAM y hay que reasignar los LED 4 y 5, por ejemplo al GPIO 26 y
al 18, y cambiar `PIN_LED_LMG_4` y `PIN_LED_LMG_5` en los dos `config.h`.

### 4.5 Los FSR (solo Módulo 3)

Cada FSR se cablea como divisor:

1. Una pata del FSR al riel de 3.3 V.
2. La otra pata del FSR al pin del ESP32 de la tabla 4.1. Ese es el punto medio.
3. Del punto medio, una resistencia de **22 kohm** a tierra.
4. Del punto medio, un condensador de **100 nF** a tierra, lo más cerca posible
   del pin del ESP32.

Sin la resistencia de 22 kohm la lectura queda flotando y da valores sin
sentido.

**Por qué 22 kohm y no 10 kohm.** El ADC del ESP32 casi no distingue voltajes
por debajo de unos 150 mV, y con 10 kohm los umbrales de frenado quedaban en
180 a 200 mV, justo en ese borde. Con 22 kohm la misma presión da unos 370 a
410 mV. A cambio, las presiones fuertes llegan antes al tope del ADC: por encima
de ~0.8 N la lectura pierde precisión. Si al calibrar los umbrales con los FSR
reales quedan por encima de ~0.6 N, conviene volver a 10 o 15 kohm y recalcular
los umbrales (fórmula en `Modulo3_Inferencia_Control/config.h`).

### 4.6 Servos al PCA9685 (solo Módulo 3)

| Desde | Hasta | Color | Notas |
|---|---|---|---|
| Servo del pulgar, cable naranja o blanco | PCA9685, canal 0, pin de señal | Blanco | El firmware usa `SERVO_PULGAR = 0`. |
| Servo del índice | PCA9685, canal 1, pin de señal | Blanco | |
| Servo del medio | PCA9685, canal 2, pin de señal | Blanco | |
| Servo del anular | PCA9685, canal 3, pin de señal | Blanco | |
| Servo del meñique | PCA9685, canal 4, pin de señal | Blanco | |
| Servo, cable rojo (los cinco) | PCA9685, pin V+ de su canal | Amarillo | Viene del riel de 6.0 V a través del borne de tornillo. |
| Servo, cable marrón o negro (los cinco) | PCA9685, pin GND de su canal | Negro | |

Cada canal del PCA9685 tiene tres pines en el orden GND, V+, señal. El conector
del servo entra directo si se respeta ese orden.

---

## 5. Armado de un módulo LMG

Repita cinco veces. **Los cinco módulos tienen que salir iguales**: mismo
espesor de taco, misma posición del LED y misma altura. Una diferencia
mecánica entre módulos entra al modelo como si fuera señal muscular.

**Orientación del PCB.** La **cara inferior** mira a la piel y queda dentro de
la carcasa. En ella solo van el cuerpo del OPT101 y el LED. Todo lo demás (C1,
R1, J1) va en la **cara superior**, que mira hacia afuera.

**Paso 1. Soldar el PCB.** Siga el orden y las comprobaciones de
`LMG_Sensor/fab/LEEME_fabricacion.md`. En resumen:

1. C1 y R1 en la cara superior, si no vienen montados de fábrica.
2. El OPT101 se inserta desde la cara inferior, **sin zócalo** y hasta el tope
   de sus patas, con el **pin 1 en el pad de esquinas redondeadas**. Se sueldan
   por la cara superior **las 8 patas**, incluidas la 2, la 6 y la 7, que no se
   conectan a nada: así se sellan los agujeros contra la luz.
3. Tapar por la cara superior, con cinta aislante negra, el anillo sin cobre
   que rodea al pin 2.
4. Un solo LED, en la posición elegida (9, 11 o 13 mm), desde la cara inferior,
   con el ánodo en el pad «+». Su altura se ajusta con un separador para que la
   punta quede en el plano de la piel (Z_piel, ver el paso 3).
5. Tapar con estaño los 4 agujeros de las otras dos posiciones del LED, sin unir
   nunca la fila de ánodos con la de cátodos.
6. J1 en la cara superior; cortar a ras las puntas que asoman por la inferior.

**Paso 2. Probar el módulo antes de montarlo.** Pruebas 2 y 3 de la sección 7.
Es el último momento cómodo para corregir un error.

**Paso 3. Medir las alturas reales.** Con el vernier:

- desde la cara inferior del PCB hasta la ventana del OPT101 (según TI, entre
  3.43 y 4.19 mm),
- la longitud del LED, desde la base de su reborde hasta la punta.

Con esas medidas se calcula el plano de la piel,
**Z_piel = −(espesor del taco + PCB a ventana)**, y el separador del LED. Las
fórmulas y los valores vigentes están en `LMG_Sensor/fab/Tabla_interfaz_carcasa.md`.

**Paso 4. Montar en la carcasa.** La carcasa se diseña alrededor del modelo 3D
del PCB (`LMG_Sensor/fab/3d/`). El PCB se atornilla con dos tornillos M2 a los
insertos de la carcasa. Entre el pozo del LED y la cavidad del sensor va un
**tabique opaco** hasta la cara de contacto: si queda corto, la luz pasa por
encima y el módulo mide su propio LED en vez del músculo.

> **No deje hueco de aire entre el LED y la piel.** El aire refleja en cada
> cambio de medio, no transmite la deformación y deja que la luz del LED llegue
> al detector rebotando por dentro de la carcasa, que es exactamente la señal
> falsa que arruina la medición.

**Paso 5. Colar la silicona.**
Mezcle partes A y B en relación 1 a 1 por peso, sin batir fuerte, durante unos
2 minutos. Tiene de 15 a 20 minutos de trabajo. Vierta despacio en la cavidad
del OPT101 hasta el espesor del taco marcado en la carcasa. Golpee suavemente
la pieza contra la mesa para que suban las burbujas. **La silicona llena solo
la cavidad del fotodiodo, no cubre el LED**, salvo una capa de protección de
0.5 a 1 mm si decide protegerlo.

**Paso 6. Curar.**
De 4 a 6 horas a temperatura ambiente, sobre una superficie nivelada y sin
moverla. No acelere con calor. Al terminar, el taco debe quedar trabado en las
ranuras laterales de la carcasa y hundirse con la presión del dedo, volviendo
solo a su forma.

**Paso 7. Registrar.**
Anote para cada módulo la posición del LED usada, la altura medida del OPT101,
el espesor final del taco y el separador del LED. Esos números son parte de la
bitácora del experimento.

---

## 6. Medidas a verificar con vernier

Las cotas del PCB (contorno, agujeros, posiciones) son exactas y están en
`LMG_Sensor/fab/Tabla_interfaz_carcasa.md`. Lo que hay que medir en las piezas
reales, porque varía de una unidad a otra:

| Qué se mide | Valor esperado | Medido |
|---|---|---|
| Cara inferior del PCB → ventana del OPT101 soldado | 3.43 a 4.19 mm (plano de TI) | ____________ |
| LED: base del reborde → punta | ~8.6 mm en un LED de 5 mm típico | ____________ |
| Espesor del taco de silicona | el de la tabla de interfaz | ____________ |
| Diámetro exterior del inserto M2 comprado | la tabla de interfaz supone 3.5 mm | ____________ |
| Ancho de la correa del brazalete | según la correa comprada | ____________ |
| Espesor de la correa | según la correa comprada | ____________ |

Imprima **una sola carcasa** primero, meta el PCB en seco y verifique que topa
donde debe. Recién entonces imprima las otras cuatro. Imprimir en negro, sin
soportes, con la cara de contacto sobre la cama, y con paredes y tabique al 100
por ciento de relleno.

---

## 7. Secuencia de pruebas

Cada prueba supone que la anterior pasó. **No conecte la etapa siguiente si la
actual no da el resultado esperado.**

### Prueba 1. Continuidad y voltajes, sin ningún componente conectado

| Paso | Qué hacer | Resultado esperado |
|---|---|---|
| 1.1 | Multímetro en continuidad. Puntas en el riel de 3.3 V y en el de tierra. | Sin pitido. Si pita, hay un corto y no se conecta nada. |
| 1.2 | Repetir entre el riel de 5.0 V y tierra, y entre el de 6.0 V y tierra. | Sin pitido en ninguno. |
| 1.3 | Puntas en dos puntos cualesquiera del riel de tierra. | Pitido. La tierra tiene que ser común en todo el montaje. |
| 1.4 | Conectar la batería con **las salidas de los XL4015 al aire**. Medir OUT+ contra OUT- del primero. | Un valor cualquiera. Girar el potenciómetro hasta leer **5.00 V**. |
| 1.5 | Igual con el segundo XL4015. | Ajustar hasta leer **6.00 V**. |
| 1.6 | Desconectar la batería. Volver a medir continuidad de 1.1. | Sin pitido. |

### Prueba 2. Un módulo LMG, solo

| Paso | Qué hacer | Resultado esperado |
|---|---|---|
| 2.1 | Sin alimentar, continuidad entre J1-1 (VCC) y J1-2 (GND). | Sin pitido. |
| 2.2 | Continuidad entre los pines 4 y 5 del OPT101. | Pitido: es el puente de realimentación. |
| 2.3 | Continuidad entre el pin 2 del OPT101 y cualquier otro pin o el plano. | Sin pitido en ninguno. El pin 2 va aislado. |
| 2.4 | Alimentar J1-1 con 3.3 V y J1-2 a tierra. Medir el consumo en serie con el multímetro en modo corriente. | Del orden de 0.1 a 0.3 mA (el OPT101 consume ~120 uA). El chip no se calienta. Si algo se calienta, desconecte de inmediato. |
| 2.5 | Medir J1-3 (OUT) con luz ambiente. | Un valor estable entre 0.1 y 2.0 V. |
| 2.6 | Tapar la ventana del OPT101 con el dedo. | La salida baja de forma clara, hasta cerca de 0 V. |
| 2.7 | Apuntarle una linterna. | La salida sube y se queda pegada cerca de 2.0 a 2.15 V, que es su saturación a 3.3 V. |

### Prueba 3. El LED del módulo

| Paso | Qué hacer | Resultado esperado |
|---|---|---|
| 3.1 | Con el módulo alimentado como en la prueba 2, llevar J1-4 (LED) a 3.3 V. Medir el voltaje **sobre R1**. | De 1.8 a 2.0 V, que dividido entre 100 ohm son de 18 a 20 mA. **Más de 2.0 V serían más de 20 mA**: revise el LED. |
| 3.2 | Mirar el LED con la cámara del celular en un cuarto en penumbra. | Punto blanco o violeta visible en la pantalla. |
| 3.3 | Apoyar el módulo sobre el dorso de la mano y medir J1-3 con J1-4 a tierra y con J1-4 a 3.3 V. | La diferencia debe ser de al menos 100 mV. Si es menor, revise el acoplamiento y que nada tape el fotodiodo. |
| 3.4 | Con el LED encendido, apretar el puño despacio. | La lectura cambia de forma repetible al contraer y relajar. Esa es la señal LMG. |

### Prueba 4. Los dos ADS1115

| Paso | Qué hacer | Resultado esperado |
|---|---|---|
| 4.1 | Con el ESP32 conectado, correr un escaneo I2C. | Aparecen **0x48** y **0x49**. Si falta 0x49, revise que el ADDR del ADS1115 #2 vaya a 3.3 V. El firmware también lo dice al arrancar. |
| 4.2 | Poner un divisor de dos resistencias iguales entre 3.3 V y tierra, y llevar su punto medio a la entrada A0 del ADS1115 #1. | El firmware lee unos 1650 mV en el canal LMG 1. |
| 4.3 | Mover ese divisor a A1 y A2 del #1, y a A0 y A1 del #2. | El valor aparece en el canal LMG 2, 3, 4 y 5 respectivamente, y no en los otros. |
| 4.4 | Conectar los cinco módulos y enviar 'A' (autocalibración) con la mano en reposo. | Termina sin avisos de canal DEBIL y deja el reposo cerca de 700 mV en cada canal. |
| 4.5 | Tapar un solo módulo y observar los cinco canales. | Cambia solo el canal tapado. Si cambian otros, hay diafonía: revise los tabiques de las carcasas y el cableado. |
| 4.6 | Durante una captura, vigilar la consola. | No debe aparecer ningún `[ADC] AVISO: LMGn recorta`, y `[OPTICA_RECORTES]` debe dar cero en los cinco canales. |

### Prueba 5. La IMU

| Paso | Qué hacer | Resultado esperado |
|---|---|---|
| 5.1 | Escaneo I2C con el MPU6050 conectado. | Aparecen **0x48**, **0x49** y **0x68**. |
| 5.2 | Leer el acelerómetro con la placa quieta y horizontal. | Un eje marca cerca de 1 g y los otros dos cerca de 0. |
| 5.3 | Girar la placa 90 grados. | El valor de 1 g se traslada a otro eje. |
| 5.4 | Dejar quieta la placa un minuto y observar la lectura. | Ruido pequeño y sin deriva grande. |

### Prueba 6. Los FSR (solo Módulo 3)

| Paso | Qué hacer | Resultado esperado |
|---|---|---|
| 6.1 | Enviar 'I' sin tocar ningún FSR. | Los cinco valores cerca de 0 mV. |
| 6.2 | Tocar suavemente la yema del pulgar. | Su valor sube con claridad por encima de ~400 mV. Solo cambia ese dedo. |
| 6.3 | Apretar fuerte. | El valor sube hacia ~3000 mV y se estanca: es el tope del ADC, esperado. |
| 6.4 | Repetir con cada dedo y anotar el valor con el que quiere que el dedo frene. | Esos valores son los `UMBRAL_FSR_*` de `Modulo3_Inferencia_Control/config.h`. |

### Prueba 7. Los servos, al final

| Paso | Qué hacer | Resultado esperado |
|---|---|---|
| 7.1 | Escaneo I2C con el PCA9685 conectado. | Aparecen 0x48, 0x49, 0x68 y **0x40**. |
| 7.2 | Con el riel de 6.0 V **medido** y un solo servo conectado, mandarlo a 0 grados y a 180. | Se mueve a ambos extremos sin vibrar ni zumbar al llegar. |
| 7.3 | Medir el voltaje del riel de 6.0 V mientras el servo arranca. | No debe caer por debajo de 5.5 V. Si cae, falta capacitor o el cable es muy delgado. |
| 7.4 | Repetir con cada servo, uno a la vez. | Los cinco responden en su canal correcto. |
| 7.5 | Recién ahora, los cinco a la vez, con la mano sin carga. | Se mueven juntos y el ESP32 no se reinicia. Un reinicio aquí significa que la alimentación de los servos está contaminando la de la lógica. |

---

## 8. Fallas típicas

| Síntoma | Causa probable | Qué revisar |
|---|---|---|
| El escaneo I2C no encuentra nada | Falta alimentación, o SDA y SCL están cruzados | Medir 3.3 V en cada placa. Confirmar que SDA va a GPIO21 y SCL a GPIO22. |
| El firmware dice `0x49 FALTA` | El ADDR del ADS1115 #2 no está en 3.3 V | ADDR del #2 a 3.3 V. Si aparece 0x48 dos veces no es posible: los dos ADDR están a tierra. |
| Aparecen 0x48 y 0x49 pero no 0x68 | AD0 del MPU6050 al aire o en alto | AD0 a tierra da 0x68. En alto da 0x69. |
| Errores de lectura I2C intermitentes | Pull-up fuera de rango | Medir SDA y SCL contra 3.3 V sin alimentación (sección 4.3). |
| El ESP32 se reinicia al mover los servos | Los servos comparten alimentación con la lógica, o falta capacitor en el riel de 6.0 V | Separar los rieles, unir solo las tierras, añadir el electrolítico de 470 a 1000 uF. |
| Un canal LMG lee el valor de otro | El OUT de un módulo está en la entrada equivocada | Revisar la tabla 4.1: módulos 1-3 a A0-A2 del #1, módulos 4-5 a A0-A1 del #2. |
| `[ADC] AVISO: LMGn recorta` | La entrada llegó a 2048 mV | Repetir la autocalibración ('A'). Si persiste, demasiada luz: revise el tabique y que el LED no ilumine directo al fotodiodo. |
| La salida del OPT101 está siempre cerca de 0 V | Falta el puente de los pines 4 y 5, el pin 2 está unido a algo, o el sensor está tapado | Pruebas 2.2 y 2.3. Comprobar con una linterna. |
| La salida del OPT101 está siempre saturada | Demasiada luz ambiente, o el LED ilumina directo al fotodiodo | Revisar el tabique opaco, la cinta negra del pin 2 y que no haya hueco de aire bajo el LED. |
| El LED no se ve en la cámara del celular | Polaridad invertida, soldadura fría o el cable de J1-4 no llega al GPIO | Medir el voltaje sobre R1 con J1-4 a 3.3 V. Si es 0 V, no circula corriente. |
| El LED 2 parpadea al arrancar | El cable del LED 2 sigue en el GPIO14 | Desde esta versión el LED 2 va al **GPIO25**. |
| La señal LMG no cambia al contraer el músculo | El taco de silicona no está comprimido contra la piel, o la correa está floja | Tensar la correa. Verificar que el taco toca la piel y que el LED está en Z_piel. |
| Un módulo da una señal mucho más débil que los otros | Taco más grueso, LED más bajo o mal contacto con la piel | El firmware lo reporta como canal DEBIL en la autocalibración. Comparar las medidas del paso 7 de la sección 5 con las de los otros cuatro. |
| Las cinco señales suben a la vez al encender un solo LED | Diafonía óptica entre módulos vecinos | Tabique corto, carcasa impresa en filamento claro o silicona desbordada sobre el LED. |
| La lectura oscila al ritmo de las luces del ambiente | Parpadeo de 120 Hz de las lámparas de la red de 60 Hz | Es conocido y está analizado en `optica_lmg.h`. Para comparar sesiones, capture siempre con la misma iluminación. |
| Un FSR lee 0 aunque se toque suavemente | El toque queda por debajo de los ~150 mV que distingue el ADC del ESP32 | Verificar que la resistencia sea de 22 kohm y no de 10 kohm. |
| Los FSR leen cualquier cosa | Falta la resistencia de 22 kohm a tierra, o el FSR está en un pin del ADC2 | Sin la resistencia el punto medio queda flotando. Solo pines 32 a 36 y 39. |
| El firmware avisa que el ciclo no cabe en 10 ms | El presupuesto temporal está al límite | Es un aviso real del autotest, no un fallo de armado. Ver el presupuesto en `Modulo3_Inferencia_Control/config.h`. |
| La batería se calienta o se hincha | Celda dañada o cargador mal configurado | Retirar de servicio. No volver a cargarla. |

---

## 9. Orden de trabajo recomendado

1. Fabricar los PCB de los módulos (`LMG_Sensor/fab/`).
2. Soldar **un solo módulo** y pasar las pruebas 2 y 3.
3. Imprimir una sola carcasa, alrededor del modelo 3D del PCB, y verificar el
   encaje en seco.
4. Cablear la placa principal con los dos ADS1115 y el MPU6050, y pasar las
   pruebas 1, 4 y 5 con ese módulo.
5. Soldar los otros cuatro módulos, imprimir las cinco carcasas, colar y curar.
6. Brazalete completo: autocalibración y prueba 4 con los cinco módulos.
7. Solo para el Módulo 3: FSR (prueba 6) y, al final, los servos (prueba 7).

**Sesiones de datos.** Las sesiones grabadas con el firmware anterior
(M1-2026.09.18 o antes, con multiplexor) y las grabadas desde M1-2026.09.24 no
se mezclan en un mismo entrenamiento sin comprobar antes que su reposo y su
excursión por canal son comparables. Cada sesión guarda su versión en el JSON.
