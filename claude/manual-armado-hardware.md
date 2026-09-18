# Manual de armado del hardware

Para armar el brazalete LMG y la prótesis desde cero, sin experiencia previa en
electrónica. Cada paso dice qué hacer y qué resultado esperar. Si un paso no da
el resultado esperado, no siga adelante: vaya a la sección de fallas típicas.

Fuentes: `claude/nota-diseno-modulos-lmg.md`, `Modulo1_Adquisicion_Datos/config.h`
y `Modulo3_Inferencia_Control/config.h`. Si este manual y el firmware no
coinciden, manda el firmware y hay que corregir el manual.

**Regla de oro: nunca conecte la batería mientras cablea.** Todo se cablea con
el sistema apagado y se enciende solo para las pruebas.

---

## 1. Glosario

| Término | Qué significa |
|---|---|
| **GPIO** | Pin de propósito general del ESP32. El firmware lo puede poner en alto (3.3 V) o en bajo (0 V), o usarlo para leer. |
| **Ánodo** | Pata positiva de un LED o diodo. La corriente entra por ahí. |
| **Cátodo** | Pata negativa. La corriente sale por ahí hacia tierra. En un LED 1206 suele marcarse con una línea o una muesca. |
| **Vf** | Voltaje directo. Lo que el LED "consume" cuando conduce. En el LED IR de 940 nm es de unos 1.3 V. |
| **Resistencia limitadora** | Resistencia en serie con el LED que fija la corriente. Sin ella, el LED toma toda la que pueda y se quema, y puede dañar el pin. |
| **Riel** | Línea de alimentación común a la que se conectan varios componentes, por ejemplo el riel de 3.3 V o el de 6.0 V. |
| **Tierra común** | Todos los negativos unidos entre sí. Sin tierra común, dos circuitos no pueden compararse voltajes y las lecturas salen sin sentido. |
| **I2C** | Bus de dos cables, SDA (datos) y SCL (reloj), al que se conectan varios chips en paralelo. Cada uno tiene una dirección distinta, por ejemplo 0x48. |
| **PWM** | Señal cuadrada que se enciende y apaga muy rápido. Variando cuánto tiempo está encendida se regula el brillo de un LED o la posición de un servo. |
| **Multiplexor (MUX)** | Llave selectora electrónica. El CD74HC4067 conecta uno de sus 16 canales a una sola salida, según el número binario que reciba en S0 a S3. |
| **ADC** | Conversor analógico a digital. Traduce un voltaje a un número. El ADS1115 es de 16 bits, así que reparte el rango en 65 536 escalones. |

---

## 2. Lista de materiales

### Electrónica principal

| Componente | Cantidad | Para qué sirve |
|---|---|---|
| ESP32 WROOM 32 devkit | 1 por módulo (1 y 3) | Cerebro. Lee sensores, corre el modelo y manda los servos. |
| ADS1115 | 1 | Convierte a números el voltaje de los sensores, con 16 bits de resolución. |
| CD74HC4067 | 1 | Lleva los 10 sensores analógicos a la única entrada usada del ADS1115. |
| MPU6050 | 1 | Mide aceleración y giro del antebrazo, que entran al modelo junto al LMG. |
| PCA9685 | 1 | Genera las señales de los 5 servos sin ocupar pines del ESP32. |
| OPT101P (DIP-8) | 5 | Fotodiodo con amplificador incorporado. Es el sensor que mide la luz que devuelve la piel. |
| LED IR SMD 1206, 940 nm | 5 (más repuestos) | Ilumina el músculo a través de la piel. |
| Resistencia de 100 ohm | 5 | Limita la corriente de cada LED a unos 20 mA. |
| FSR402 | 2 | Sensor de presión de la yema del pulgar y del índice. |
| DF9-40 | 3 | Sensor de presión de las yemas medio, anular y meñique. |
| Resistencia de 10 kohm | 5 | Forma el divisor que convierte la resistencia de cada FSR en un voltaje legible. |
| Servo MG90S | 5 | Mueve cada dedo. |

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
| Capacitor cerámico de 100 nF | 4 o 5 | Uno junto a la alimentación de cada placa I2C. Filtra el ruido. |

### Mecánica y taller

| Componente | Cantidad | Para qué sirve |
|---|---|---|
| Silicona de platino Silika RTV 1510, Shore 10A | 1 kg | Es el transductor. El taco se comprime cuando el músculo se abulta y eso cambia la luz que llega al fotodiodo. |
| Filamento PLA negro | 1 rollo | Carcasa de los módulos. El negro evita que la luz viaje por dentro del plástico. |
| Perfboard o PCB, y recortes de fibra | 1 | Placa de cada módulo y pestañas para los LED. |
| Zócalo DIP-8 | 5 | Permite quitar y poner el OPT101 sin desoldar. |
| Alambre esmaltado delgado (AWG 30) | 2 m | Cablea el LED de la pestaña a la placa sin estorbar. |
| Cable de silicona AWG 26 y AWG 20 | varios | AWG 26 para señales, AWG 20 para la alimentación de los servos. |
| Termorretráctil surtido | 1 | Aísla cada unión soldada. |
| Cinta de correa y velcro | 1 | Sujeta el brazalete al antebrazo con tensión pareja. |

### Instrumentos

| Instrumento | Para qué sirve |
|---|---|
| Multímetro | Mide voltaje, continuidad y corriente. Es el único modo de saber qué está pasando. |
| Vernier o calibrador | Mide las piezas reales antes de imprimir. |
| Cautín con punta fina y estaño delgado | Soldar el SMD y los cables. |
| Cámara de un celular | Los LED IR no se ven a simple vista, pero la cámara sí los muestra. |

---

## 3. Advertencias de seguridad

> ### ⚠ ADVERTENCIA 1: el OPT101 va a 3.3 V, nunca a 5 V
> Su salida llega hasta cerca de su alimentación menos 1 V. Alimentado a 5 V
> puede entregar casi 4 V a la entrada del ADS1115, que está alimentado a
> 3.3 V, y una entrada por encima de la alimentación más 0.3 V lo daña.
> Alimentado a 3.3 V la salida nunca pasa de unos 2.0 V y todo queda protegido.

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

> ### ⚠ ADVERTENCIA 5: respete la polaridad del LED
> El LED 1206 tiene una marca que indica el cátodo. Al revés no enciende, y en
> algunos casos se degrada. Antes de pegarlo en la carcasa, pruébelo con la
> cámara del celular, porque después de colar la silicona ya no se puede
> cambiar.

> ### ⚠ ADVERTENCIA 6: nunca los cinco LED encendidos a la vez
> Cuelgan directo del GPIO con 100 ohm. Uno solo son unos 20 mA, que el pin
> tolera. El firmware enciende uno a la vez a propósito, tanto por la corriente
> como para evitar que la luz de un módulo llegue al fotodiodo del vecino. No
> escriba código de prueba que los encienda todos juntos.

---

## 4. Tabla de cableado, cable por cable

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
| Blanco | Señal analógica |
| Morado | Control de LED |
| Gris | Direcciones del MUX |

### 4.1 Alimentación

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
| ESP32, pin 3V3 | Riel de 3.3 V | Rojo | De aquí cuelgan OPT101, ADS1115, MPU6050, MUX y la lógica del PCA9685. |
| ESP32, pin GND | Riel de tierra | Negro | |

### 4.2 Bus I2C

Los tres chips van en paralelo sobre los mismos dos cables.

| Desde | Hasta | Color | Notas |
|---|---|---|---|
| ESP32, GPIO21 | ADS1115, SDA | Azul | |
| ESP32, GPIO21 | MPU6050, SDA | Azul | |
| ESP32, GPIO21 | PCA9685, SDA | Azul | |
| ESP32, GPIO22 | ADS1115, SCL | Verde | |
| ESP32, GPIO22 | MPU6050, SCL | Verde | |
| ESP32, GPIO22 | PCA9685, SCL | Verde | |
| Riel de 3.3 V | ADS1115, VDD | Rojo | A 3.3 V, igual que el OPT101. |
| Riel de 3.3 V | MPU6050, VCC | Rojo | |
| Riel de 3.3 V | PCA9685, VCC | Rojo | Solo la lógica. La potencia entra por el borne de tornillo. |
| Riel de tierra | ADS1115, GND | Negro | |
| Riel de tierra | MPU6050, GND | Negro | |
| Riel de tierra | PCA9685, GND | Negro | |
| ADS1115, ADDR | Riel de tierra | Negro | ADDR a tierra fija la dirección **0x48**. |
| MPU6050, AD0 | Riel de tierra | Negro | AD0 a tierra fija la dirección **0x68**. |
| PCA9685, A0 a A5 | sin puente | | Sin puentes soldados la dirección es **0x40**. |

Las tres placas de módulo traen resistencias de pull-up en SDA y SCL. Con tres
en paralelo el bus sigue funcionando a 400 kHz. Si aparecen errores de lectura,
quite los pull-up de dos de las tres placas.

### 4.3 Direcciones del multiplexor

| Desde | Hasta | Color | Notas |
|---|---|---|---|
| ESP32, GPIO32 | CD74HC4067, S0 | Gris | Bit menos significativo. |
| ESP32, GPIO33 | CD74HC4067, S1 | Gris | |
| ESP32, GPIO25 | CD74HC4067, S2 | Gris | |
| ESP32, GPIO26 | CD74HC4067, S3 | Gris | Bit más significativo. |
| CD74HC4067, EN | Riel de tierra | Negro | EN activo en bajo. A tierra el MUX queda siempre habilitado. |
| CD74HC4067, VCC | Riel de 3.3 V | Rojo | La misma alimentación que las señales que conmuta. |
| CD74HC4067, GND | Riel de tierra | Negro | |
| CD74HC4067, SIG | ADS1115, A0 | Blanco | Única entrada del ADC que se usa. A1, A2 y A3 quedan libres. |

### 4.4 Canales analógicos del multiplexor

Se usan 10 de los 16 canales. Los canales 10 a 15 quedan libres.

| Desde | Hasta | Color | Notas |
|---|---|---|---|
| OPT101 número 1, pin 5 (salida) | CD74HC4067, C0 | Blanco | Módulo LMG 1. |
| OPT101 número 2, pin 5 | CD74HC4067, C1 | Blanco | Módulo LMG 2. |
| OPT101 número 3, pin 5 | CD74HC4067, C2 | Blanco | Módulo LMG 3. |
| OPT101 número 4, pin 5 | CD74HC4067, C3 | Blanco | Módulo LMG 4. |
| OPT101 número 5, pin 5 | CD74HC4067, C4 | Blanco | Módulo LMG 5. |
| Divisor del FSR402 del pulgar, punto medio | CD74HC4067, C5 | Blanco | Solo Módulo 3. |
| Divisor del FSR402 del índice, punto medio | CD74HC4067, C6 | Blanco | Solo Módulo 3. |
| Divisor del DF9-40 del medio, punto medio | CD74HC4067, C7 | Blanco | Solo Módulo 3. |
| Divisor del DF9-40 del anular, punto medio | CD74HC4067, C8 | Blanco | Solo Módulo 3. |
| Divisor del DF9-40 del meñique, punto medio | CD74HC4067, C9 | Blanco | Solo Módulo 3. |

Cada FSR se cablea como divisor: una pata al riel de 3.3 V, la otra pata al
punto medio, y del punto medio una resistencia de 10 kohm a tierra. El punto
medio es lo que se lee. Sin la resistencia de 10 kohm la lectura queda flotando
y da valores sin sentido.

### 4.5 LED de los cinco módulos LMG

| Desde | Hasta | Color | Notas |
|---|---|---|---|
| ESP32, GPIO13 | Resistencia de 100 ohm del módulo 1 | Morado | |
| Resistencia de 100 ohm del módulo 1 | LED 1, ánodo | Morado | |
| LED 1, cátodo | Riel de tierra | Negro | |
| ESP32, GPIO14 | Resistencia de 100 ohm del módulo 2 | Morado | |
| Resistencia de 100 ohm del módulo 2 | LED 2, ánodo | Morado | |
| LED 2, cátodo | Riel de tierra | Negro | |
| ESP32, GPIO27 | Resistencia de 100 ohm del módulo 3 | Morado | |
| Resistencia de 100 ohm del módulo 3 | LED 3, ánodo | Morado | |
| LED 3, cátodo | Riel de tierra | Negro | |
| ESP32, GPIO16 | Resistencia de 100 ohm del módulo 4 | Morado | |
| Resistencia de 100 ohm del módulo 4 | LED 4, ánodo | Morado | |
| LED 4, cátodo | Riel de tierra | Negro | |
| ESP32, GPIO17 | Resistencia de 100 ohm del módulo 5 | Morado | |
| Resistencia de 100 ohm del módulo 5 | LED 5, ánodo | Morado | |
| LED 5, cátodo | Riel de tierra | Negro | |

La resistencia va del lado del GPIO, antes del LED. Da lo mismo eléctricamente
si va antes o después, pero ponerla siempre del mismo lado hace que el error se
vea de un vistazo.

**Si la placa es un ESP32 WROVER y no un WROOM 32**, los GPIO 16 y 17 están
tomados por la PSRAM y hay que reasignar esos dos LED, por ejemplo a GPIO 18 y
19, y cambiar `PIN_LED_LMG_4` y `PIN_LED_LMG_5` en los dos `config.h`.

### 4.6 Alimentación de los cinco OPT101

| Desde | Hasta | Color | Notas |
|---|---|---|---|
| Riel de 3.3 V | OPT101 número 1, pin 1 (V+) | Rojo | **Nunca a 5 V.** Ver advertencia 1. |
| Riel de tierra | OPT101 número 1, pin 8 (GND) | Negro | |
| OPT101 número 1, pin 2 | OPT101 número 1, pin 3 | Puente corto | Une la salida del fotodiodo a la entrada del amplificador y deja activa la realimentación interna de 1 Mohm. |
| igual para los módulos 2, 3, 4 y 5 | | | Cinco veces lo mismo. |

Verifique la numeración de pines contra la ficha del OPT101P antes de soldar. Si
usa el breakout CJMCU-101, el puente ya viene hecho en la placa y solo hay que
cablear alimentación, tierra y salida.

### 4.7 Servos al PCA9685

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

## 5. Armado mecánico de un módulo LMG

Repita cinco veces. **Los cinco módulos tienen que salir iguales**: mismo
espesor de taco, misma separación y mismo pegado. Una diferencia mecánica entre
módulos entra al modelo como si fuera señal muscular.

**Paso 1. Soldar el LED en su pestaña.**
Recorte un trozo de placa de fibra de unos 6 por 8 mm. Estañe dos islas
separadas 3.2 mm. Coloque el LED 1206 con la marca de cátodo hacia la isla que
irá a tierra y suelde primero un lado, luego el otro. El LED queda plano contra
la pestaña, sin quedar inclinado.

**Paso 2. Probar el LED antes de pegar nada.**
Conecte el ánodo a 3.3 V a través de la resistencia de 100 ohm y el cátodo a
tierra. Mire el LED con la cámara del celular. Debe verse un punto blanco o
violeta pálido. Si no se ve, revise polaridad y soldadura. Este es el último
momento cómodo para corregirlo.

**Paso 3. Cablear la pestaña.**
Suelde dos hilos esmaltados, uno al ánodo y otro al cátodo. Deje unos 5 cm.
Raspe y estañe las puntas del otro extremo. Los hilos salen por el canal lateral
de la carcasa hacia la placa del módulo.

**Paso 4. Pegar la pestaña al ras de la cara de contacto.**
La cara del LED queda **a nivel de la superficie que toca la piel**, no hundida.
Use una gota de cianoacrilato en los bordes de la pestaña, nunca sobre el LED.
Compruebe con el vernier que no sobresale ni se hunde más de 0.2 mm.

> **No deje hueco de aire entre el LED y la piel.** El aire refleja en cada
> cambio de medio, no transmite la deformación y deja que la luz del LED llegue
> al detector rebotando por dentro de la carcasa, que es exactamente la señal
> falsa que arruina la medición.

**Paso 5. Colocar el OPT101 detrás del taco.**
El OPT101 va en su zócalo DIP-8, mirando hacia la ventana, a 12.7 mm del centro
del LED, con el tabique opaco de 2 mm entre los dos. El tabique llega desde la
cara de contacto hasta arriba. Si queda corto, la luz pasa por encima y el
módulo mide su propio LED en vez del músculo.

**Paso 6. Colar la silicona.**
Mezcle partes A y B en relación 1 a 1 por peso, sin batir fuerte, durante unos
2 minutos. Tiene de 15 a 20 minutos de trabajo. Vierta despacio en la ventana
del OPT101 hasta el espesor de 4 mm marcado en la carcasa. Golpee suavemente la
pieza contra la mesa para que suban las burbujas. **La silicona llena solo la
ventana del fotodiodo, no cubre el LED**, salvo una capa de protección de 0.5 a
1 mm si decide protegerlo.

**Paso 7. Curar.**
De 4 a 6 horas a temperatura ambiente, sobre una superficie nivelada y sin
moverla. No acelere con calor. Al terminar, el taco debe quedar trabado en las
ranuras laterales de la carcasa y hundirse con la presión del dedo, volviendo
solo a su forma.

**Paso 8. Registrar.**
Anote para cada módulo el espesor final del taco y la separación medida. Esos
cinco pares de números son parte de la bitácora del experimento.

---

## 6. Medidas a verificar con vernier antes de imprimir

Mida las piezas reales que compró, porque las nominales rara vez coinciden.
Anote en la última columna y ajuste el `.scad` antes de imprimir las cinco
carcasas.

| Qué se mide | Valor esperado | Parámetro del `.scad` | Medido |
|---|---|---|---|
| Alto del cuerpo del OPT101P o del breakout CJMCU-101 | 4.5 a 5.0 mm | `opt_h` | ____________ |
| Ancho del cuerpo del OPT101P | 9.8 mm aprox. | `opt_w` | ____________ |
| Largo del cuerpo del OPT101P | 6.5 mm aprox. | `opt_l` | ____________ |
| Alto del zócalo DIP-8 montado | 3.0 mm aprox. | `zocalo_h` | ____________ |
| Largo del LED 1206 | 3.2 mm | `smd_l` | ____________ |
| Ancho del LED 1206 | 1.6 mm | `smd_w` | ____________ |
| Alto del LED 1206 | 1.1 mm | `smd_h` | ____________ |
| Espesor de la pestaña de fibra con el LED soldado | 1.6 mm más el LED | `pestana_t` | ____________ |
| Espesor del taco de silicona | 4.0 mm | `pad_t` | ____________ |
| Separación entre el LED y el centro del OPT101 | 12.7 mm | `sep_led_opt` | ____________ |
| Espesor del tabique opaco | 2.0 mm | `tabique_t` | ____________ |
| Ancho de la correa del brazalete | según la correa comprada | `correa_w` | ____________ |
| Espesor de la correa | según la correa comprada | `correa_t` | ____________ |

Imprima **una sola carcasa** primero, meta las piezas en seco y verifique que
topan donde deben. Recién entonces imprima las otras cuatro. Imprimir en negro,
sin soportes, con la cara de contacto sobre la cama, y con paredes y tabique al
100 por ciento de relleno.

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

### Prueba 2. Un solo OPT101 en protoboard

| Paso | Qué hacer | Resultado esperado |
|---|---|---|
| 2.1 | Montar un OPT101 en protoboard, V+ a 3.3 V, GND a tierra, puente del pin 2 al 3. | La placa no se calienta. Si algo se calienta, desconecte de inmediato. |
| 2.2 | Medir el consumo en serie con el multímetro en modo corriente. | Del orden de 1 mA. |
| 2.3 | Medir la salida, pin 5, con luz ambiente de la habitación. | Entre 0.1 y 2.0 V, un valor estable. |
| 2.4 | Tapar el sensor con el dedo. | La salida baja de forma clara, hasta cerca de 0 V. |
| 2.5 | Apuntarle una linterna. | La salida sube y se queda pegada cerca de 2.0 V, que es su saturación a 3.3 V. |

### Prueba 3. El LED, junto al OPT101

| Paso | Qué hacer | Resultado esperado |
|---|---|---|
| 3.1 | Conectar el LED con su resistencia de 100 ohm entre 3.3 V y tierra. Medir el voltaje **en la resistencia**. | De 1.8 a 2.0 V, que dividido entre 100 ohm son de 18 a 20 mA. |
| 3.2 | Mirar el LED con la cámara del celular en un cuarto en penumbra. | Punto blanco o violeta visible en la pantalla. |
| 3.3 | Poner el LED a unos 12.7 mm del OPT101, apuntando ambos al dorso de la mano, y medir la salida del OPT101 con el LED apagado y con el LED encendido. | La diferencia entre las dos debe ser de al menos 100 mV. Si es menor, revise la distancia, el acoplamiento y que nada tape el fotodiodo. |
| 3.4 | Con el LED encendido, apretar el puño despacio. | La lectura cambia de forma repetible al contraer y relajar. Esa es la señal LMG. |

### Prueba 4. El multiplexor completo

| Paso | Qué hacer | Resultado esperado |
|---|---|---|
| 4.1 | Con el ESP32 conectado, correr un escaneo I2C. | Aparece **0x48**. Si no, revise SDA, SCL y alimentación del ADS1115. |
| 4.2 | Alimentar el MUX, EN a tierra, SIG al pin A0 del ADS1115. Poner un divisor conocido, por ejemplo 3.3 V a través de dos resistencias iguales, en el canal C0. | El firmware lee alrededor de 1650 mV en el canal 0. |
| 4.3 | Mover ese mismo divisor al canal C1, luego al C2, y así hasta el C9. | El valor aparece en el canal correspondiente y no en los otros. |
| 4.4 | Conectar los cinco OPT101 y leer los canales 0 a 4 con todos los LED apagados. | Cinco valores parecidos entre sí, que suben al acercar una linterna a cada módulo por separado. |
| 4.5 | Tapar un solo módulo y leer los cinco canales. | Cambia solo el canal tapado. Si cambian otros, hay diafonía y hay que revisar el tabique, el cableado y el asentamiento del MUX. |

### Prueba 5. La IMU

| Paso | Qué hacer | Resultado esperado |
|---|---|---|
| 5.1 | Escaneo I2C con el MPU6050 conectado. | Aparecen **0x48** y **0x68**. |
| 5.2 | Leer el acelerómetro con la placa quieta y horizontal. | Un eje marca cerca de 1 g y los otros dos cerca de 0. |
| 5.3 | Girar la placa 90 grados. | El valor de 1 g se traslada a otro eje. |
| 5.4 | Dejar quieta la placa un minuto y observar la lectura. | Ruido pequeño y sin deriva grande. |

### Prueba 6. Los servos, al final

| Paso | Qué hacer | Resultado esperado |
|---|---|---|
| 6.1 | Escaneo I2C con el PCA9685 conectado. | Aparecen 0x48, 0x68 y **0x40**. |
| 6.2 | Con el riel de 6.0 V **medido** y un solo servo conectado, mandarlo a 0 grados y a 180. | Se mueve a ambos extremos sin vibrar ni zumbar al llegar. |
| 6.3 | Medir el voltaje del riel de 6.0 V mientras el servo arranca. | No debe caer por debajo de 5.5 V. Si cae, falta capacitor o el cable es muy delgado. |
| 6.4 | Repetir con cada servo, uno a la vez. | Los cinco responden en su canal correcto. |
| 6.5 | Recién ahora, los cinco a la vez, con la mano sin carga. | Se mueven juntos y el ESP32 no se reinicia. Un reinicio aquí significa que la alimentación de los servos está contaminando la de la lógica. |

---

## 8. Fallas típicas

| Síntoma | Causa probable | Qué revisar |
|---|---|---|
| El escaneo I2C no encuentra nada | Falta alimentación, o SDA y SCL están cruzados | Medir 3.3 V en cada placa. Confirmar que SDA va a GPIO21 y SCL a GPIO22. |
| Aparece 0x48 pero no 0x68 | AD0 del MPU6050 al aire o en alto | AD0 a tierra da 0x68. En alto da 0x69. |
| Aparece 0x49 en vez de 0x48 | ADDR del ADS1115 conectado a 3.3 V | ADDR a tierra. |
| El ESP32 se reinicia al mover los servos | Los servos comparten alimentación con la lógica, o falta capacitor en el riel de 6.0 V | Separar los rieles, unir solo las tierras, añadir el electrolítico de 470 a 1000 uF. |
| Todas las lecturas del MUX dan el mismo valor | EN del MUX al aire, o las líneas S0 a S3 no llegan | EN a tierra. Verificar continuidad de los cuatro cables de dirección. |
| Un canal del MUX arrastra el valor del anterior | El capacitor de muestreo del ADC no alcanzó a cargarse | Es el asentamiento del MUX. Está en `ASENTAMIENTO_MUX_US`, hoy en 50 us. Subirlo cuesta tiempo de ciclo. |
| La salida del OPT101 está siempre cerca de 0 V | Falta el puente del pin 2 al 3, o el sensor está tapado | Rehacer el puente. Comprobar con una linterna. |
| La salida del OPT101 está siempre saturada | Demasiada luz ambiente, o el LED ilumina directo al fotodiodo | Revisar el tabique opaco y que no haya hueco de aire bajo el LED. |
| El LED no se ve en la cámara del celular | Polaridad invertida, soldadura fría o resistencia equivocada | Medir el voltaje en la resistencia de 100 ohm. Si es 0 V, no circula corriente. |
| La señal LMG no cambia al contraer el músculo | El taco de silicona no está comprimido contra la piel, o la correa está floja | Tensar la correa. Verificar que el taco toca la piel y que el LED está al ras. |
| Un módulo da una señal mucho más débil que los otros | Taco más grueso, LED hundido o mal contacto con la piel | El firmware lo reporta como canal DEBIL en la autocalibración. Medir el taco con vernier y comparar con los otros cuatro. |
| Las cinco señales suben a la vez al encender un solo LED | Diafonía óptica entre módulos vecinos | Tabique corto, carcasa impresa en filamento claro o silicona desbordada sobre el LED. |
| La lectura oscila al ritmo de las luces del ambiente | Parpadeo de 120 Hz de las lámparas de la red de 60 Hz | Es conocido y está analizado en `optica_lmg.h`. Para comparar sesiones, capture siempre con la misma iluminación. |
| Los FSR leen cualquier cosa | Falta la resistencia de 10 kohm a tierra | Sin ella el punto medio del divisor queda flotando. |
| El firmware avisa que el ciclo no cabe en 10 ms | El presupuesto temporal está al límite | Es un aviso real del autotest, no un fallo de armado. Ver el presupuesto en `Modulo3_Inferencia_Control/config.h`. |
| La batería se calienta o se hincha | Celda dañada o cargador mal configurado | Retirar de servicio. No volver a cargarla. |

---

## 9. Orden de trabajo recomendado

1. Probar todo en protoboard, sin soldar nada definitivo, con los LED IR de
   5 mm que ya están comprados.
2. Imprimir una sola carcasa y verificar encaje en seco.
3. Imprimir las cinco, soldar las pestañas, colar y curar.
4. Cablear el brazalete completo y correr las pruebas 4 y 5.
5. Recién al final, la PCB con zócalo DIP-8 para que el OPT101 siga siendo
   desmontable.
