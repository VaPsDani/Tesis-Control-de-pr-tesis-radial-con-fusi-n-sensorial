# Ablación de fases: qué tramo del gesto entra al entrenamiento

Compara tres variantes de entrenamiento (`fases.VARIANTES_ABLACION`):

| variante | clase del gesto = |
|---|---|
| `solo_meseta` | el gesto sostenido |
| `dinamica_meseta` | la transición y el sostenido (**defecto del pipeline**) |
| `todo_con_reaccion` | además el tramo en que la mano sigue quieta |

Chen et al. mostraron sobre sEMG que incluir la transición cambia el
desempeño real; sobre LMG no existe el equivalente, y ese contraste es el
resultado que va al artículo.

## Cómo se mide

- **El conjunto de test es el mismo para las tres.** Si cada variante se
  evaluara sobre sus propias filas, `solo_meseta` se mediría sobre las ventanas
  más fáciles y ganaría por construcción. Las tres se evalúan sobre las mismas
  ventanas: gesto en `dinamica` o `meseta`, y reposo estable.
- **Exactitud por fase.** La dinámica es ~3% de un bloque de 15 s: apenas mueve
  la exactitud global, pero es lo que la prótesis debe reconocer para responder
  a tiempo. Por eso se reporta aparte.
- **Ventanas de reacción, aparte.** La mano sigue en reposo, así que lo deseable
  es que se clasifiquen como Rest. Entrenar con la reacción como gesto debería
  empeorarlo: ese es el coste de la tercera variante.
- Ventanas de 200 ms, stride 20 ms, sin cruzar bloques ni pausas. Cada ventana
  toma la fase de su **última** muestra: la decisión que tomaría la prótesis en
  ese instante con una ventana causal.
- GroupKFold por sujeto, con verificación de fuga. Con un solo sujeto hace falta
  `--permitir_intra_sujeto` y el resultado queda etiquetado intra-sujeto.

## Resultado sobre el dataset público (sustituto, no el resultado del artículo)

`lmg_wavelength_dataset`, configuración `ir`, LDA, 10 sujetos, GroupKFold por
sujeto. 185 843 ventanas; 77 806 de meseta, 2 661 de dinámica, 1 376 de reacción.

| variante | accuracy | F1 macro | acc dinámica | acc meseta | acc Rest | reacción→Rest |
|---|---|---|---|---|---|---|
| solo_meseta | 0.5821 | 0.4446 | 0.1608 | 0.3225 | 0.8753 | 0.5952 |
| dinamica_meseta | 0.5852 | 0.4494 | **0.1616** | 0.3289 | 0.8748 | 0.5923 |
| todo_con_reaccion | 0.5872 | 0.4531 | 0.1507 | 0.3334 | 0.8747 | 0.5850 |

**No hay efecto.** Wilcoxon pareado por sujeto (n = 10) contra
`dinamica_meseta`: todas las p ≥ 0.14 y las diferencias medias no pasan de
0.008, un orden por debajo de la desviación entre pliegues (0.11).

Tres razones para no leer esto como "la fase dinámica no importa":

1. **La anticipación contamina las fases.** En este dataset el movimiento
   empieza ~250 ms *antes* de la etiqueta, con orden fijo de gestos. La prueba
   está en la propia tabla: solo el 59% de las ventanas de "reacción" se
   clasifican como Rest, cuando por definición la mano debería estar quieta.
   Si la reacción ya contiene movimiento, la tercera variante deja de ser el
   contraste que se quería medir.
2. **La dinámica es casi inclasificable aquí** (0.16, por debajo del 0.20 de
   azar con 5 clases), y las clases activas se separan mal entre sí
   (Tripod 0.10, Pinch 0.25) aunque Rest sí se distinga (0.87). Con las clases
   poco separadas no hay margen donde el tramo de entrenamiento pueda notarse.
3. **Solo 2 661 ventanas de dinámica** frente a 77 806 de meseta.

Nuestro protocolo corrige (1) contrabalanceando el orden y mostrando el gesto
solo al empezar el bloque. Por eso **el contraste que vale es el del piloto**,
todavía sin grabar.

## Pendiente

`ablacion_fases.py --csv <sesiones del piloto>` en cuanto existan datos. Sobre
sesiones sintéticas con onset conocido la comparación sí discrimina
(dinámica 0.26 → 0.40 al incluir la transición; reacción→Rest 1.00 → 0.70 al
añadirla), lo que confirma que la medición funciona cuando las fases están bien
definidas.

```bash
python ablacion_fases.py --csv ../../captura/sesiones/*.csv
python ablacion_fases.py --lmg_publico --config ir --data ~/data/lmg_wavelength_dataset
```

Salidas en `resultados/<fuente>_<modelo>/`: `ablacion_global.csv`,
`ablacion_por_clase.csv`, `ablacion_por_grupo.csv`, `confusion_<variante>.csv`,
`ablacion_confusion.png` y `ablacion_estadistica.txt`.
