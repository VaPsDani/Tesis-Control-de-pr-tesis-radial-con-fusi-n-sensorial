# Manual de armado del hardware (OMG con QRE1113)

Versión del 2026-11-13, para el firmware `M1-2026.11.13-QRE`. El manual de la
etapa LMG (OPT101, ADS1115, servos, FSR) está en el tag `lmg-final-2026-11-13`.

Fuentes: `Modulo1_Adquisicion_Datos/config.h` (única fuente de verdad de los
pines) y la PCB `qre` del asesor (KiCad 10, 19,5 x 10,8 mm).

## 1. Qué se arma

| Pieza | Cantidad | Para qué |
|---|---|---|
| DevKit ESP32 WROOM de 38 pines | 1 | Adquisición y ADC |
| MPU6050 (placa GY-521) | 1 | Acelerómetro y giroscopio |
| Módulo QRE1113 (PCB `qre`) | 8 | Un canal óptico cada uno |
| Cable JST ZH de 5 vías, paso 1,5 mm | 8 | Módulo a ESP32 |
| Carcasas de los módulos y brazalete | 8 | Contacto con la piel |
| Cinta Kapton | 1 rollo | Aislar pistas y soldaduras en las pruebas sin carcasa |

Ya no hay ADS1115, PCA9685, servos, FSR, XL4015 ni batería: el ESP32 se
alimenta por USB.

### Cada módulo

El QRE1113GR trae un LED IR de 940 nm y un fototransistor en el mismo
encapsulado. Va **en contacto con la piel, sin silicona**.

| Pin del JST | Señal | Qué es |
|---|---|---|
| 1 | VCC | 3,3 V |
| 2 | GND | Tierra |
| 3 | OUT | Colector del fototransistor, con R2 = 47 kΩ a VCC. **Más luz da menos tensión.** |
| 4 | IR | Ánodo del LED del QRE. El cátodo va a GND por R1 = 100 Ω. En alto, unos 20 mA |
| 5 | Led | Tres LED externos del PCB (D1 a D3, R3 = 100 Ω). **No se usa: sin conectar** |

## 2. Advertencias

> ### ⚠ 1. VCC de los módulos a 3,3 V, nunca a 5 V
> OUT entra directo al ADC del ESP32. Con 5 V, a oscuras OUT subiría a 5 V y
> quemaría el pin. **Ya pasó una vez con un GPIO conectado a 5 V.** El pin 1 de
> cada JST va al pin **3V3** del ESP32. El pin 5V (o VIN) está en el otro
> extremo de la misma fila: compruebe la serigrafía antes de conectar.

> ### ⚠ 2. El pin 5 del JST (Led) queda sin conectar
> Si se conecta a un GPIO o a VCC enciende los LED externos del PCB, que
> agregan luz que el firmware no controla.

> ### ⚠ 3. Ningún GPIO a más de 3,3 V
> Ni para probar. Para comprobar un cable basta tocar 3V3 y GND.

> ### ⚠ 4. Pines que no se usan
> 0 y 12 (arranque), 6 a 11 (flash: SD2, SD3, CMD, CLK, SD0, SD1), 1 y 3 (la
> comunicación serie con la PC). Un cable en el 12 impide que el ESP32 arranque
> o se programe.

## 3. Cableado

### 3.1 Módulos ópticos

| Módulo | JST 1 VCC | JST 2 GND | JST 3 OUT | JST 4 IR | JST 5 |
|---|---|---|---|---|---|
| 1 | 3V3 | GND | GPIO36 (VP/SP) | GPIO13 | nada |
| 2 | 3V3 | GND | GPIO39 (VN/SN) | GPIO27 | nada |
| 3 | 3V3 | GND | GPIO34 | GPIO23 | nada |
| 4 | 3V3 | GND | GPIO35 | GPIO19 | nada |
| 5 | 3V3 | GND | GPIO32 | GPIO18 | nada |
| 6 | 3V3 | GND | GPIO33 | GPIO17 | nada |
| 7 | 3V3 | GND | GPIO25 | GPIO16 | nada |
| 8 | 3V3 | GND | GPIO26 | GPIO4 | nada |

Los OUT de los módulos 1 a 6 van al ADC1 y los de 7 y 8 al ADC2, que funciona
porque el firmware no usa WiFi. 16 y 17 valen porque la placa es WROOM (en una
WROVER son de la PSRAM). Libres para otros usos: 14, 5 y 15. El 2 solo como
indicador.

### 3.2 MPU6050

| MPU6050 | ESP32 |
|---|---|
| VCC | 3V3 |
| GND | GND |
| SDA | GPIO21 |
| SCL | GPIO22 |
| AD0 | GND (dirección 0x68) |
| XDA, XCL, INT | nada |

El MPU6050 es lo único que queda en el bus I2C. Su placa GY-521 trae pull-up de
4,7 kΩ, que bastan para 400 kHz.

### 3.3 Numeración

**Numere las 8 placas y sus carcasas del 1 al 8**, con marcador o etiqueta, y
use siempre la misma placa en la misma posición del brazalete. La app de
captura tiene un campo para anotar qué placa física va en cada posición. Si
una placa se cambia, se anota.

### 3.4 Pruebas con la placa al descubierto

Para las pruebas sin carcasa, **cubra con cinta Kapton las pistas y las
soldaduras de la cara que toca la piel**, dejando libre solo la ventana del
QRE1113. Sin eso la piel toca nodos del circuito y la lectura mide la piel como
resistencia, no la luz.

## 4. Primera prueba, en este orden

### 4.1 Alimentación

Con todo conectado, mida 3,3 V entre los pines 1 y 2 del JST de cada módulo. Si
no hay multímetro, revise visualmente que el cable del pin 1 vaya al pin 3V3 y
no al 5V.

### 4.2 Tabla de pines

Abra el monitor serie a 921 600 baudios y reinicie el ESP32. Las líneas
`[PINES]` muestran la tabla del firmware. **Compárela con el cableado real**
módulo por módulo.

### 4.3 `T`, autotest

Con la mano en reposo y el brazalete puesto, envíe `T`.

| Qué mirar | Bueno | Si no |
|---|---|---|
| `[AUTOTEST] ciclo: ... maximo` | Menos de 10 000 µs, idealmente menos de 9 000 | Bajar `N_MUESTRAS`, `T_ON_US` o `T_OFF_US` |
| Banderas por módulo | `OK` | Ver la tabla de abajo |
| `[IMU] ... OK` | `CONFIG=0x04 (DLPF_CFG=4) GYRO_CONFIG=0x00 ACCEL_CONFIG=0x00 (AFS_SEL=0) OK` | Revisar SDA, SCL y AD0 |

| Bandera | Qué significa | Qué revisar |
|---|---|---|
| `SATURADO` | Con el LED encendido OUT queda casi en 0: demasiada luz | Contacto con la piel, o bajar la capacidad con `D1` |
| `SIN_SENAL` | Vuelve muy poca luz | Que el sensor toque la piel |
| `LED_NO_ENCIENDE` | Encender el LED no cambia nada | Cable del pin 4 al GPIO correcto, soldadura del QRE |
| `TOPE_ADC` | Con el LED apagado OUT está en el tope del ADC | **Normal** dentro de la carcasa: es solo informativo |

### 4.4 `C`, asentamiento

Envíe `C` con la mano quieta. Por módulo imprime t90, t95 y t99 al encender y al
apagar su LED, y al final los valores sugeridos (t99 + 20 %). Aplíquelos con el
comando que imprime, por ejemplo `E350` y `O420`, y repita `T`. Los valores
quedan en la memoria del ESP32.

### 4.5 `X`, diafonía

Envíe `X`. Por módulo compara la lectura con los otros 7 LED encendidos frente
a todos apagados. Si algún módulo pasa del 5 % de su propia señal, la luz de
los vecinos le llega. Pruebe entonces `MODO_LED = MODO_SECUENCIAL` en
`config.h`, y confirme con `T` que el ciclo sigue cabiendo en 10 ms.

### 4.6 Prueba de saturación

`D0` a `D3` cambian la capacidad de salida de los 8 GPIO de los LED, y con ella
la corriente. No se guarda: al reiniciar vuelve a 2. Sirve para ver con `T` si
algún módulo satura con más corriente.

## 5. Fallas típicas

| Síntoma | Causa probable | Qué revisar |
|---|---|---|
| El ESP32 no aparece como puerto COM | Cable USB de solo carga | Probar con un cable que pase datos (por ejemplo, el del celular) |
| `[ERROR] MPU6050 no detectado` | SDA y SCL cruzados, o sin 3V3 | Tabla 3.2 |
| Un canal siempre en ~140 mV | El OUT no llega, o el pin del ESP32 está dañado | Tocar ese cable a 3V3: tiene que marcar ~3100 |
| Un canal siempre en el tope, también con luz | El LED no enciende o el sensor no ve la piel | Cámara del celular sobre el LED, `LED_NO_ENCIENDE` en `T` |
| Todos los `v` bajan juntos al encender los LED | Caída del 3,3 V con los 8 LED a la vez | `X`, y probar el modo secuencial |
| La lectura oscila con las luces del cuarto | Parpadeo de las lámparas | Capturar siempre con la misma iluminación |
