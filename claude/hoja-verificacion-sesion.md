# Hoja de verificación de sesión

Participante `S____`  ·  subject_id `____`  ·  Fecha `__________`  ·  Hora inicio `______`

---

## Antes de que llegue (5 min)

- [ ] Laptop cargada y enchufada, Windows sin actualizaciones pendientes
- [ ] ESP32 conectado, LED de la placa encendido
- [ ] Brazalete y correa a la mano, piel del antebrazo limpia y seca
- [ ] Monitor serie a **921600** muestra `[FW] version=M1-2026.09.24` y `[READY]`
- [ ] Autocalibración: enviar **`A`** con el brazo en reposo, esperar unos 10 s
  - [ ] Reposo de cada canal entre **500 y 900 mV** (objetivo 700, el 35 % de 2000)
  - [ ] Ningún canal marcado **DEBIL**
  - [ ] Dispersión max/min **menor que 1.5**
- [ ] **Cerrar el monitor serie** antes de abrir la app, el puerto no se comparte

## Arranque de la app

```
python Modulo2_Pipeline_DL\captura_sesion.py --puerto COM__ --participante S__
```

- [ ] `subject_id` escrito en la ventana (1 a 10, es la semilla del orden)
- [ ] Carpeta de salida `Modulo2_Pipeline_DL\sesiones`
- [ ] Datos del participante: edad `___`  sexo `___`  mano dominante `_______`
      circunferencia antebrazo `____` cm  posición del brazalete `____` cm

## Prueba de conexión (botón Probar conexión)

Pedir **3 contracciones fuertes** y mirar la ventana.

- [ ] Los **5 canales** dicen `responde`, ninguno `plano`
- [ ] Tasa entre **95 y 105** muestras/s
- [ ] Huecos en **0**
- [ ] Cerrar la ventana de prueba antes de Iniciar

## Guion de instrucciones al participante

- [ ] "Mire solo la pantalla. Yo no le voy a hablar durante la grabación."
- [ ] "Primero 15 s quieto, brazo relajado sobre la mesa. No mueva la mano."
- [ ] "Después, cada gesto tiene tres momentos: **PREPÁRESE**, **CONTRAIGA** y
      **DESCANSE**."
- [ ] "En CONTRAIGA suba la fuerza poco a poco durante el primer segundo,
      siguiendo la barra amarilla, y manténgala los 10 s."
- [ ] "Cuando diga **BRAZO QUIETO**, no mueva el brazo."
- [ ] "Cuando diga **BRAZO EN MOVIMIENTO**, recorra las tres posiciones que se
      iluminan abajo sin soltar el gesto y sin parar. Suena un tono en cada
      cambio, no hace falta que mire."
- [ ] "Si se equivoca de gesto, dígalo y siga. Yo lo marco."

## Durante la grabación (8.7 min)

Vigilar el panel del operador cada minuto.

| Indicador | Bien | Qué hago si no |
|---|---|---|
| muestras/s | 95 a 105 | Anotar en observaciones, seguir |
| huecos | 0 | Anotar el minuto, seguir |
| cola | estable | Cerrar otros programas |
| 5 trazos | todos se mueven | **Pausar**, revisar el módulo, reanudar |

- [ ] Gesto equivocado: pulsar **Descartar repeticion** y seguir
- [ ] Movimiento en la calibración: **Abortar** y repetir la sesión completa
- [ ] Cable suelto: la app pausa sola, recolocar y pulsar **Reanudar**

## Al terminar

- [ ] Anotar observaciones en la app **antes** de cerrar la ventana
- [ ] Verificar el archivo:

```
python Modulo2_Pipeline_DL\produccion\verificar_piloto.py --csv Modulo2_Pipeline_DL\sesiones\s__________.csv
```

- [ ] El VEREDICTO dice **Sin problemas**.  Si no, anotar cuántos: `____`
- [ ] Respaldo 1: copiar la carpeta `sesiones` a la memoria USB
- [ ] Respaldo 2: copiar a otra carpeta del disco, por ejemplo `Documentos\respaldo_tesis`
- [ ] Los tres archivos del participante están en los dos sitios:
      `.csv`, `.json`, `_fases.json`

## Notas de esta sesión

```
Hora de fin: ______   Repeticiones descartadas: ______

Incidencias:
_______________________________________________________________

_______________________________________________________________
```

**Regla de oro:** si dudas entre seguir y repetir, repite. Una sesión dura
9 minutos y un dato malo contamina el análisis de los 10 participantes.
