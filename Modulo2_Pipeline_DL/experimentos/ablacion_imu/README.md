# Ablación de la IMU

**Pregunta que responde:** ¿aporta la unidad inercial algo sobre la LMG sola, y
ese aporte cambia cuando el brazo se mueve?

Es la comparación central del trabajo. **Ningún trabajo publicado de
lightmiografía incorpora unidades inerciales**, así que el vacío es propio, y
se mide sobre datos propios, con los mismos sujetos, la misma instrumentación y
el mismo protocolo en todas las celdas.

## Diseño factorial 2×2

| | estática | dinámica |
|---|---|---|
| **solo_lmg** (5 canales ópticos) | celda 1 | celda 2 |
| **lmg_imu** (5 ópticos + 3 del acelerómetro) | celda 3 | celda 4 |

- **Factor A, composición de la entrada.** Lo único que cambia son las columnas
  que alimentan al modelo.
- **Factor B, condición postural.** Lo único que cambia son las repeticiones
  sobre las que se mide. En la estática el brazo no se mueve, y en la dinámica
  recorre tres posiciones durante la contracción sin soltar el gesto.

Las cuatro celdas salen del **mismo conjunto de datos**, con las mismas
ventanas, el mismo submuestreo de Rest, la misma partición y la misma semilla.
`verificar_identidad_de_configuracion()` compara la configuración de las cuatro
y falla si algo que debería ser idéntico difiere. Se comprueba en vez de
confiar, porque este es el tipo de fallo que no da ningún síntoma.

## Cómo se entrena, y tres preguntas distintas

| `--entrenamiento` | Qué ve el modelo | Qué pregunta responde |
|---|---|---|
| **`mixto`, por defecto** | Las dos condiciones mezcladas | **Cuánto aporta la IMU, y si aporta más bajo variación postural. Es la prueba principal** |
| `por_condicion` | Solo la condición que se evalúa | Cuánto rinde un modelo especializado por postura |
| `estatica_a_dinamica` | Solo repeticiones estáticas | Qué ocurre cuando el entrenamiento no incluye variación postural |

**La prueba principal del aporte inercial es `mixto`, y la cifra que responde
es su interacción.** Ahí las dos celdas de una misma fila comparten pesos, así
que la diferencia entre ellas viene de la condición y no de haber entrenado con
la mitad de los datos.

### Qué ocurre cuando el entrenamiento no incluye variación postural

`--entrenamiento estatica_a_dinamica` entrena solo con las repeticiones
estáticas y evalúa sobre las dos condiciones de los sujetos de test. La
distancia entre las dos celdas es la caída por cambio de postura.

**Este modo está sesgado contra la IMU, y hay que decirlo al leer sus cifras.**
En la condición estática el brazo está fijo, así que el acelerómetro lee casi
siempre el mismo vector de gravedad: los valores de la condición dinámica caen
fuera de la distribución de entrenamiento **por la física del protocolo**, no
por azar ni por un defecto del modelo. Además, entrenando solo con el brazo
quieto el modelo nunca ve la relación entre postura y señal óptica, que es
justo lo que tendría que aprender para compensarla.

De ahí la lectura correcta:

| Si sale | Lo que significa | Lo que NO significa |
|---|---|---|
| `lmg_imu` cae más que `solo_lmg` | Que la fusión inercial **necesita variación postural en los datos de entrenamiento** | Que la IMU no compense la postura |
| `lmg_imu` cae menos | Que la IMU aporta robustez incluso sin haber visto la postura en entrenamiento | |

El reporte de este modo incluye una **comprobación del rango del acelerómetro
en entrenamiento frente al de test**, canal por canal y sobre los valores ya
normalizados, que son los que entran al modelo. Si los de test caen fuera, lo
declara explícitamente como desplazamiento de distribución, con la fracción de
muestras fuera del rango y fuera del intervalo p1 a p99, y la separación de
medias en desviaciones del entrenamiento.

Se reporta la caída en puntos absolutos y en porcentaje del valor estático,
porque con exactitudes de partida distintas entre composiciones la absoluta
sola engaña, y la diferencia de caídas con su contraste pareado por sujeto.

**Las cifras absolutas de un modo no se comparan con las de otro**, porque
`estatica_a_dinamica` entrena con la mitad de los datos. Lo comparable es
siempre la distancia dentro de una misma corrida.

| Decisión | Valor |
|---|---|
| Validación | GroupKFold por sujeto, k = 5, con verificación de fuga y autotest |
| Selección de época | Validación interna sobre un sujeto separado del train, nunca del test, y reentreno con todo el train |
| Normalización | Por sujeto, con la media y la desviación de **su bloque de calibración** |
| Ventana y stride | 200 ms y 20 ms |
| Semilla | 42 |

**Por qué se normaliza con la calibración y no con todo el train:** es lo único
que el firmware puede medir en el brazo de una persona, pedir 15 s de reposo
antes de empezar. Normalizar con todo el train supondría conocer de antemano
los gestos de ese sujeto, que en uso real no se tienen. Además, el bloque de
calibración no entra ni al entrenamiento ni a la evaluación, así que usarlo
para normalizar no filtra nada del test.

## Qué se reporta

Por celda: exactitud, F1 macro, AUC y matriz de confusión, con el desglose por
pliegue y por sujeto.

Contrastes, **pareados por sujeto y no por pliegue**, porque con 10 sujetos y
k = 5 contrastar por pliegue deja n = 5 y además los dos sujetos de un mismo
pliegue comparten modelo:

| Contraste | Qué mide |
|---|---|
| Efecto principal de A | `lmg_imu` frente a `solo_lmg` |
| Efecto principal de B | dinámica frente a estática |
| Aporte de la IMU en cada condición | por separado, quieto y en movimiento |
| **Interacción** | si el aporte de la IMU es mayor con el brazo en movimiento |
| **Caída entre posturas** | cuánto pierde cada composición al evaluar en dinámica, con la diferencia de caídas entre las dos |

La diferencia de caídas coincide numéricamente con la interacción, con el signo
cambiado. Se reporta aparte porque con `estatica_a_dinamica` significa otra
cosa: en `mixto` es cuánto aporta la IMU en cada condición, y allí cuánto
aguanta cada composición una postura que no estuvo en su entrenamiento.

**En una corrida en modo `mixto`, la interacción es la cifra que responde a la
pregunta.** Si la IMU sirve sobre todo para compensar el movimiento del brazo,
su aporte tiene que ser mayor en la condición dinámica. Con entrenamiento solo
estático la misma aritmética no dice eso, y el informe lo advierte según el
modo que registre el CSV.

Se reportan ANOVA de medidas repetidas 2×2, Wilcoxon pareado y t pareada con
su tamaño de efecto. Con 10 sujetos el p mínimo alcanzable por Wilcoxon es
0.002, y con menos de 6 sujetos ningún resultado puede bajar de 0.05. El script
lo imprime siempre, en vez de dejar que se lea un p sin contexto.

## Estado

**Pendiente de datos.** El piloto todavía no está grabado, así que aquí no hay
resultados. El experimento corre de principio a fin sobre sesiones sintéticas,
que sirven para comprobar que las cuatro celdas quedan equilibradas, que la
partición no filtra y que la estadística no se rompe. **No producen resultados
publicables.**

## Uso

```bash
python ablacion_imu.py --simulado --n_sujetos_sim 10
python ablacion_imu.py --sesiones "../../sesiones/*.csv"
python ablacion_imu.py --sesiones "../../sesiones/*.csv" \
    --entrenamiento estatica_a_dinamica --output resultados_generalizacion
python estadistica.py --csv resultados/ablacion_imu_por_sujeto.csv
```

Conviene correr las dos: `mixto` para el 2×2 y `estatica_a_dinamica` para la
generalización, cada una en su carpeta de salida, porque el CSV por sujeto
lleva el modo en una columna pero los archivos se sobrescriben.

| Archivo | Qué hace |
|---|---|
| `datos.py` | Carga los CSV, ventanea con metadatos, submuestrea Rest y normaliza por calibración |
| `ablacion_imu.py` | Corre las cuatro celdas y guarda métricas, matrices y predicciones |
| `estadistica.py` | Efectos principales, interacción y contrastes pareados |

## Salidas

| Archivo | Contenido |
|---|---|
| `resultados/ablacion_imu.json` | Configuración verificada, métricas por celda, por pliegue y por sujeto, caída entre posturas y el rango del acelerómetro en `rango_acelerometro_train_vs_test` |
| `resultados/ablacion_imu_por_sujeto.csv` | Una fila por celda y sujeto, que es la entrada de la estadística |
| `resultados/predicciones.npz` | Probabilidades por ventana, con sujeto, condición y repetición |
| `resultados/estadistica.txt` y `.json` | Contrastes |
| `resultados/matriz_confusion_*.png` | Una por celda |

## Lo que este experimento no puede responder

- **De dónde viene el aporte.** Que el acelerómetro ayude no dice si es porque
  informa de la postura del brazo o porque correlaciona con el gesto. Habría
  que mirar canal a canal.
- **Nada sobre el giroscopio.** Se graba en el CSV pero no entra al vector del
  modelo, que son 8 canales. Añadirlo sería otro nivel del factor A y otra
  corrida.
- **Transferencia a un amputado.** Los sujetos del piloto tienen las dos manos.
