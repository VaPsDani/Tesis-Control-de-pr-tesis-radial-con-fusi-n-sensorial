# Imágenes de los gestos

Pictogramas que ve el participante durante las fases de preparación y
contracción. Van en PNG, con estos nombres exactos.

| Archivo | Gesto | Estado |
|---|---|---|
| `Rest.png` | Reposo, mano relajada | pendiente |
| `Pinch.png` | Pinza, pulgar contra índice | pendiente |
| `Tripod.png` | Trípode, pulgar con índice y medio | pendiente |
| `Power.png` | Puño de fuerza | pendiente |
| `Finger_Ext.png` | Extensión de los dedos | pendiente |

Recomendaciones:

- 300 por 300 píxeles, que es el marco que reserva la pantalla.
- Fondo claro o transparente, trazo grueso y alto contraste, porque se ven a
  un metro de distancia.
- La misma mano en las cinco, y siempre desde el mismo ángulo. Cambiar de
  punto de vista entre gestos hace dudar al participante.
- Solo PNG. Tkinter carga PNG sin librerías adicionales, pero no JPG.

Si falta alguna, la sesión funciona igual: aparece el marco vacío y el
operador ve un aviso al iniciar.
