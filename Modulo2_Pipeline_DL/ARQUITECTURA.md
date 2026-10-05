# Arquitectura e hiperparámetros del modelo

Todo lo que el artículo dice que está en el repositorio, con el archivo y la
función de donde sale cada valor. Si este documento y el código no coinciden,
manda el código y hay que corregir el documento.

Código: `common/modelo.py` (`construir_modelo`, `compilar_modelo`,
`MecanismoAtencion`) y `common/entrenamiento.py` (`entrenar_pliegue`,
`entrenar_con_validacion_interna`). Se entrena con Keras 2 (`tf_keras`).

## Arquitectura, CNN-BiLSTM-Attention

Entrada: ventana de 20 pasos (200 ms a 100 Hz) por C canales. C = 5 en la
configuración A (solo LMG) y C = 8 en la B (LMG y acelerómetro).

| # | Capa | Configuración | Salida |
|---|---|---|---|
| 1 | Conv1D `conv1d_1` | 64 filtros, núcleo 3, `padding="same"`, ReLU, L2 1e-4 en el núcleo | 20 × 64 |
| 2 | BatchNormalization `bn_1` | Valores por defecto de Keras 2 | 20 × 64 |
| 3 | Conv1D `conv1d_2` | 128 filtros, núcleo 3, `padding="same"`, ReLU, L2 1e-4 en el núcleo | 20 × 128 |
| 4 | BatchNormalization `bn_2` | Valores por defecto de Keras 2 | 20 × 128 |
| 5 | Bidirectional(LSTM) `bilstm_1` | 32 unidades por sentido, `return_sequences=True`, activaciones por defecto (tanh y sigmoide), L2 1e-4 en el núcleo de entrada | 20 × 64 |
| 6 | Atención `atencion` | Aditiva, 64 unidades, sin sesgo, ecuación abajo | 64 |
| 7 | Dense `dense_1` | 64 unidades, ReLU, L2 1e-4 | 64 |
| 8 | Dropout `dropout` | Tasa 0.5 | 64 |
| 9 | Dense `salida_gesto` | 5 unidades, softmax | 5 |

### Ecuación de la atención

Sea h_t, con t = 1 a 20, la salida de la BiLSTM en el paso t, un vector de 64
componentes (32 de cada sentido concatenados). Con W1 de 64 × 64 y W2 de
64 × 1, ambos entrenables, sin términos de sesgo:

```
e_t     = tanh(h_t · W1) · W2
alfa_t  = exp(e_t) / suma_k exp(e_k)
c       = suma_t alfa_t · h_t
```

El vector de contexto c, de 64 componentes, es lo que pasa a `dense_1`. Es
atención aditiva sobre la propia secuencia, sin una consulta externa: cada
paso recibe una puntuación según su contenido y el resultado es la media de
los pasos ponderada por esas puntuaciones. El comentario del código la llama
Bahdanau. Se diferencia de la de Bahdanau en que no hay estado de un
decodificador que actúe de consulta.

### Parámetros

Medido con `count_params()` en TensorFlow 2.21 y tf_keras 2.21, y
coincidente con el cálculo a mano.

| | Configuración A, C = 5 | Configuración B, C = 8 |
|---|---|---|
| Total | 76 357 | 76 933 |
| Entrenables | 75 973 | 76 549 |
| No entrenables (medias y varianzas de BatchNormalization) | 384 | 384 |

Desglose para C = 8: Conv1D 1 600, BN 256, Conv1D 24 704, BN 512, BiLSTM
41 216, atención 4 160, Dense 4 160, salida 325.

## Entrenamiento

| Parámetro | Valor | Dónde |
|---|---|---|
| Optimizador | Adam, tasa inicial 1e-3 | `compilar_modelo`, `--lr` |
| Pérdida | Entropía cruzada categórica con suavizado de etiquetas 0.1 | `LABEL_SMOOTHING` en `entrenamiento.py` |
| Pesos por clase | total / (5 × ventanas de la clase), con las ventanas de entrenamiento de cada pliegue, como `sample_weight` | `pesos_de_clase` |
| Tamaño de lote | 32 | `--batch_size` |
| Épocas máximas | 100 | `--epochs` |
| Detención temprana | Vigila `val_loss`, paciencia 15, `start_from_epoch` = 10, restaura los mejores pesos | `entrenar_pliegue` |
| Reducción de la tasa | Vigila `val_loss`, factor 0.5, paciencia 7, mínimo 1e-6 | `entrenar_pliegue` |
| Validación | 1 sujeto separado del entrenamiento de cada pliegue, nunca del de prueba | `entrenar_con_validacion_interna` |
| Reentreno | Con todos los sujetos de entrenamiento, el mismo número de épocas que restauró la detención temprana y el mismo calendario de tasa que se registró, sin validación | `entrenar_con_validacion_interna` |
| Barajado | Búfer de 1024 ventanas en cada época | `entrenar_pliegue` |

### Aumento de datos, solo en entrenamiento

Por ventana, en este orden:

1. Ruido gaussiano de media 0 y desviación 0.02.
2. Escalado global por un factor uniforme entre 0.95 y 1.05.
3. Desplazamiento temporal circular de −1, 0 o +1 muestras (`tf.roll`).

### Semillas

| Qué | Semilla |
|---|---|
| Inicialización, barajado y aumento del pliegue k | `tf.keras.utils.set_random_seed(42 + k)`, reanclada al empezar cada pliegue |
| Sujeto de validación del pliegue k | `RandomState(42 + 1000 + k)` |
| Partición | GroupKFold, determinista, no usa semilla |

La semilla base es `--seed`, 42 por defecto.

## Datos de entrada

| Paso | Valor |
|---|---|
| Ventana y paso | 20 y 2 muestras, 200 y 20 ms a 100 Hz |
| Normalización de la LMG | z por canal con la media y la desviación del bloque de calibración |
| Normalización del acelerómetro | g menos la media del bloque de calibración, sin dividir |
| Etiquetado | Variante `dinamica_meseta` de `produccion/fases.py`, versión 4 |

Todo sale de `produccion/preprocesamiento.py`, `preparar_sesion`, que es la
misma función para la ablación, la producción y la conversión INT8.
