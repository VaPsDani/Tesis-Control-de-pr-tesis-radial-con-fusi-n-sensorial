# Validación del pipeline sobre LMG real (`lmg_wavelength_dataset`)

Dataset público de New Dexterity: 10 sujetos × 4 configuraciones de iluminación
× 5 repeticiones, 40 canales LMG, 200 archivos. Se clona en `data/` (excluido
por `.gitignore`); no declara licencia, así que no se redistribuye.

**Toda validación cruzada agrupa por sujeto** (GroupKFold, k=5), nunca por
ventana ni por repetición.

## Hechos que hubo que medir, porque el dataset no los declara

| Hecho | Cómo se estableció |
|---|---|
| **fs = 83.2 Hz** | Desde la alternancia del LED: en `125both` el ciclo dura 250 ms y en `250both` 500 ms; el periodo dominante da 83.02 y 83.43 Hz de forma independiente. El control `green`, sin alternancia, no muestra ese pico. |
| **Orden fijo de gestos** en los 200 archivos | pinch, tripod, full, key, extension, con bloques de 834 muestras (10.0 s) exactos. Esa exactitud indica que la etiqueta sigue a la señal visual, no al movimiento. |
| **Anticipación de ~250 ms** | La señal se mueve antes del cambio de etiqueta; el 72% de las transiciones ya supera el 10% de su excursión en los 500 ms previos. |
| **Sin ubicación anatómica** de los canales | No documentada: se reportan índices. |

Las dos últimas son limitaciones a declarar: con orden fijo, cada gesto hereda
siempre el estado que deja el anterior (hiperemia, fatiga) y ocupa siempre la
misma posición temporal, así que parte de la separabilidad puede ser deriva
temporal y no el gesto. **Nuestro protocolo contrabalancea el orden justamente
por esto.** El orden de las 4 configuraciones de luz sí está contrabalanceado
entre sujetos, así que el análisis 1.b no queda confundido con la fatiga.

**Mapeo de clases:** `full` es nuestro Power. `key` se **descarta** (no está en
el repertorio de la prótesis; fundirlo con Pinch contaminaría esa clase). Sus
filas se eliminan *después* de detectar las fases, porque el reposo que sigue a
`key` necesita su detección de relajación.

**Configuraciones con alternancia:** en `125both` y `250both` el LED alterna
verde e IR a 2-4 Hz, dentro de la banda del gesto, con una varianza de 5.6x y
9.3x la excursión del propio gesto. Se aplica una media móvil **centrada** de
exactamente un ciclo, cuyos ceros caen sobre la fundamental y todos sus
armónicos; la relación ruido/excursión baja a 0.23 y 0.18, comparable a `ir`
(0.14) y `green` (0.09). Al ser centrada no introduce retardo, pero **difumina
el onset medio ciclo a cada lado**, que es la salvedad de esas dos
configuraciones.

---

## 1.a Ventana, solapamiento y frecuencia de muestreo

Rejilla de ventana {100, 150, 200, 250, 300} ms × solapamiento
{50, 60, 70, 75, 80, 90}% × fs {83.2, 41.6} Hz = 60 celdas nominales, que tras
redondear a muestras colapsan en **48 configuraciones efectivas distintas** (a
41.6 Hz, 100 ms son 4 muestras: pedir 90% de solapamiento da un stride de 0.4,
que redondea a 1, o sea 75% real). Se reportan los valores efectivos, no los
nominales. Etapa 1: LDA sobre las 60 celdas. Etapa 2: CNN sobre las mejores.

### El solapamiento alto no ayuda con partición por sujeto

Promediando sobre ventanas a 83.2 Hz, F1 macro por solapamiento:

| | 50% | 60% | 70% | 75% | 80% | 90% | ganancia 50 a 90 |
|---|---|---|---|---|---|---|---|
| todas las ventanas | 0.3715 | 0.3606 | 0.3536 | 0.3692 | 0.3582 | 0.3697 | **-0.002** |
| a N de entrenamiento igualado | 0.3715 | 0.3610 | 0.3552 | 0.3722 | 0.3646 | 0.3763 | **+0.005** |

El control a N igualado separa el efecto del solapamiento del simple aumento de
ventanas: subir del 50% al 90% multiplica las ventanas por 4 (25 116 a 99 926
con ventana de 200 ms) y mejora el F1 en 0.005, **dentro del ruido entre
pliegues (±0.10)**. Con partición por sujeto, el solapamiento alto solo infla el
recuento de ventanas; el beneficio que suele atribuirse aparece cuando ventanas
vecinas, casi idénticas, caen a ambos lados de la partición.

### Latencia

La latencia de ventaneo es la ventana efectiva (204 ms para la de 200 ms
nominal a 83.2 Hz); el solapamiento fija el **periodo entre decisiones**, no la
latencia. A 200 ms y 50% de solapamiento: 204 ms de latencia y una decisión cada
96 ms; al 88%, la misma latencia con una decisión cada 24 ms.

### 41.6 Hz no es peor que 83.2 Hz

| fs | F1 medio | F1 máximo |
|---|---|---|
| 83.2 Hz | 0.3638 | 0.3982 |
| 41.6 Hz (submuestreo con anti-alias) | **0.3720** | **0.4135** |

Submuestrear a la mitad, con `scipy.signal.decimate` y fase cero, nunca con
`[::2]`, no degrada nada. Es coherente con que el LMG es una señal lenta, y
**tiene consecuencia directa en el presupuesto del firmware**: si el piloto lo
confirma, la frecuencia de muestreo tiene holgura y la trama oscura cabría
incluso con un ADC lento. Las diferencias siguen dentro del ruido, así que es
una hipótesis a verificar con datos propios, no una conclusión.

**CNN:** pendiente (etapa de GPU en curso).

---

## 1.b Longitud de onda: sin efecto

LDA, métricas por sujeto, las 4 configuraciones sobre los mismos 10 sujetos.

| | green | ir | 250both | 125both |
|---|---|---|---|---|
| accuracy | 0.4653 | 0.4433 | 0.4416 | 0.4182 |
| F1 macro | 0.4185 | 0.3769 | 0.3859 | 0.3392 |

- **ANOVA de medidas repetidas** (factor sujeto): F(3,27) = 0.209, **p = 0.889**
- **Friedman** (no exige esfericidad): chi2 = 1.080, p = 0.782
- **Verde vs IR**, la comparación limpia: t pareada p = 0.776, Wilcoxon
  p = 0.922, diferencia media +0.022 a favor del verde

No se detecta efecto de la longitud de onda, **coincidiendo con Guan et al.
(p = 0.245)**. Dos salvedades: `AnovaRM` no aplica corrección de esfericidad
(por eso se contrasta con Friedman), y **el IR del dataset es de 880 nm mientras
que nuestro LED es de 940 nm**, así que la conclusión se extrapola, no se
traslada.

**CNN:** pendiente (etapa de GPU en curso).

---

## 1.c Cuántos canales hacen falta

El dataset tiene 40 canales; el brazalete tiene 5. La pregunta es si 5 módulos
son una limitación presupuestaria o una decisión defendible.

### Curva por eliminación hacia atrás (LDA, F1 macro)

| canales | 40 | 30 | 20 | **15** | 10 | 8 | 6 | 5 | 4 | 3 | 2 | 1 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| F1 | 0.387 | 0.513 | 0.548 | **0.564** | 0.549 | 0.528 | 0.510 | 0.486 | 0.473 | 0.457 | 0.409 | 0.335 |

La curva **no es monótona**: quitar canales mejora el desempeño hasta un máximo
alrededor de 15, y 5 canales (0.486) superan a los 40 (0.387). Con 40 canales
son 80 características para un LDA con covarianza agrupada, y la maldición de la
dimensionalidad domina.

### Búsqueda exhaustiva

| k | modo | subconjuntos | mejor | F1 |
|---|---|---|---|---|
| 3 | completa | 9 880 | [1, 16, 27] | 0.471 |
| 4 | completa | 91 390 | [0, 14, 15, 28] | 0.508 |
| 5 | acotada al top-15 | 3 003 | [28, 0, 15, 3, 13] | 0.492 |
| 6 | acotada al top-15 | 5 005 | [28, 0, 15, 16, 25, 13] | 0.514 |

Para 5 y 6 canales la exhaustiva completa serían 658 008 y 3 838 380
combinaciones por configuración, de horas a días de cómputo: se acota a los 15
canales mejor situados en la eliminación y **se declara como búsqueda acotada**,
no completa.

### El número honesto: validación anidada

Elegir el mejor subconjunto con los mismos pliegues con que se reporta su
puntuación es optimista: entre miles de candidatos alguno sale bien por azar. En
la validación anidada, la selección completa se rehace dentro de cada pliegue
externo usando solo los sujetos de entrenamiento, y el subconjunto elegido se
evalúa en el sujeto de test, que nunca intervino en la elección.

| | F1 |
|---|---|
| Mejor 5 canales, seleccionado y evaluado en los mismos pliegues | 0.492 |
| **Mejor 5 canales, validación anidada** | **0.339 ± 0.055** |
| 5 canales al azar (mediana de 1 000) | 0.317 |
| Los 40 canales (no requiere selección, insesgado) | 0.387 |

**El sesgo del ganador vale 0.15 de F1**, más que cualquier diferencia entre
métodos de este experimento. Cada pliegue externo elige además un subconjunto
distinto ([37,0,15,17,18], [0,27,14,4,15], [34,0,16,28,13], [28,17,5,18,10],
[0,14,12,26,7]), lo que indica que la ubicación óptima no se transfiere entre
sujetos; solo el canal 0 y el entorno del 14 al 18 reaparecen.

**Lectura para el diseño:** con una selección honesta, 5 canales rinden 0.339
frente a 0.387 de los 40, y elegirlos bien aporta poco sobre tomarlos al azar
(0.339 vs 0.317). Es decir, **reducir de 40 a 5 sensores cuesta unos 0.05 de
F1**, y ese es el precio real de un brazalete de 5 módulos, sin el adorno del
subconjunto ganador. El dataset no documenta la ubicación anatómica, así que no
se puede traducir a posiciones sobre el antebrazo.

---

## 1.d Modelos clásicos frente a CNN

LDA, SVM (RBF), Random Forest y la CNN sobre la misma partición por sujeto, con
40 canales y con el mejor subconjunto de 5.

| modelo | 40 canales |
|---|---|
| LDA | acc 0.4456 ± 0.1061 · F1 0.3982 |
| SVM | acc 0.4348 ± 0.0577 · F1 0.3929 |
| Random Forest | acc 0.5031 ± 0.0427 · F1 0.4472 |
| CNN | acc 0.4299 ± 0.0937 · F1 0.3925 |

Con 40 canales **Random Forest supera a la CNN** (0.503 vs 0.430). La tabla del
subconjunto de 5 canales está pendiente (etapa en curso).

---

## Reproducir

```bash
git clone --depth 1 https://github.com/newdexterity/lmg_wavelength_dataset.git data/lmg_wavelength_dataset
python analisis_ventana.py --etapa lda
python analisis_canales.py --reusar
python analisis_longitud_onda.py --modelo lda
python analisis_clasicos.py --seed 42
python analisis_ventana.py --etapa cnn --top 6 --seed 42
```

Salidas en `resultados/`. El detector de fases (`Modulo2_Pipeline_DL/fases.py`)
se comparte con la captura propia; su versión y sus parámetros forman parte de
la clave de caché, porque una caché calculada con otra versión devolvería fases
equivocadas en silencio.
