"""
entrenamiento.py - Bucle de entrenamiento con validacion interna y reentreno
=============================================================================
Protesis transradial - Codigo compartido por todos los experimentos

QUE HACE:
  Entrena un pliegue con una particion de validacion tomada del PROPIO
  conjunto de entrenamiento, nunca del test, y despues reentrena con todo
  el train reproduciendo las epocas y el calendario de tasa de aprendizaje
  que se eligieron.

POR QUE EXISTE:
  Las primeras corridas pasaban el pliegue de test como validation_data.
  EarlyStopping con restore_best_weights y ReduceLROnPlateau elegian la
  epoca mirando el test, lo que da cifras optimistas. Medido sobre el
  experimento de normalizacion, la fuga valia +1.27 puntos de exactitud.

  Este modulo es el unico sitio donde se entrena, de modo que los cuatro
  experimentos comparten exactamente el mismo mecanismo y no pueden
  divergir sin que se note.

AGNOSTICO DEL DATASET:
  No conoce NinaPro ni el brazalete. Los nombres de las clases y su
  numero entran por parametro, con valores por defecto genericos.
"""

import time

import numpy as np
import tensorflow as tf
from sklearn.metrics import f1_score

from modelo import construir_modelo, compilar_modelo

# Suavizado de etiquetas con el que se obtuvo la referencia SI2.
# Cambiarlo rompe la comparabilidad entre corridas.
LABEL_SMOOTHING = 0.1


def nombres_por_defecto(num_clases: int):
    """Nombres genericos cuando el experimento no pasa los suyos."""
    return [f"clase_{i}" for i in range(num_clases)]


def augmentar_muestra(X, y):
    """
    Data augmentation ligero sobre cada ventana de entrenamiento.

    Identico a la referencia SI2: ruido gaussiano, escalado global y
    desplazamiento temporal de +/- 1 muestra. Se aplica solo al conjunto
    de entrenamiento, nunca al de validacion.
    """
    noise = tf.random.normal(tf.shape(X), mean=0.0, stddev=0.02)
    X = X + noise
    factor = tf.random.uniform([], minval=0.95, maxval=1.05)
    X = X * factor
    shift = tf.random.uniform([], minval=-1, maxval=2, dtype=tf.int32)
    X = tf.roll(X, shift=shift, axis=0)
    return X, y



def fijar_semilla(seed: int, fold_idx: int, determinismo: bool = False) -> None:
    """
    Fija la semilla al inicio de cada pliegue.

    Se usa seed + fold_idx y no la semilla desnuda a proposito: si se
    fijara una sola vez al arrancar, el estado del RNG al empezar el
    pliegue k dependeria de cuanto azar consumieron los pliegues
    anteriores, que varia con el numero de epocas de cada uno. Dos
    corridas que difieren en cualquier cosa (el stride, por ejemplo)
    divergirian desde el primer pliegue que cambiara de longitud.
    Reanclando por pliegue, el pliegue k arranca del mismo estado en
    todas las corridas y las diferencias son atribuibles a lo que se
    quiso cambiar.

    'determinismo' activa enable_op_determinism(), que fuerza kernels
    deterministas en GPU. Da reproducibilidad bit a bit pero puede
    rechazar el kernel cuDNN del LSTM y degradar mucho la velocidad, asi
    que queda opcional: sin el, fijar la semilla ya elimina la varianza
    de inicializacion, de barajado y de augmentation, que es la que
    domina.
    """
    tf.keras.utils.set_random_seed(seed + fold_idx)
    if determinismo:
        tf.config.experimental.enable_op_determinism()


def entrenar_pliegue(X_train, y_train, X_val, y_val, fold_idx,
                     epochs, batch_size, lr, early_stopping_start=0,
                     seed=None, determinismo=False,
                     X_test=None, y_test=None, lr_por_epoca=None,
                     num_clases=None, nombres_clases=None):
    """
    Construye, entrena y evalua el modelo en un pliegue.
    Retorna (history, y_pred, metricas_dict).

    lr_por_epoca: si se pasa, es un REENTRENAMIENTO. Sin EarlyStopping, sin
    ReduceLROnPlateau y sin datos de validacion: se entrena exactamente
    len(lr_por_epoca) epocas reproduciendo ese calendario de tasa de
    aprendizaje, que salio de la fase de seleccion con validacion interna.
    X_val e y_val se ignoran y pueden ser None.

    X_val, y_val alimentan a EarlyStopping y ReduceLROnPlateau.
    X_test, y_test son los que se evaluan y predicen. Si no se pasan se
    evalua sobre X_val, que es el comportamiento historico: la validacion
    ERA el pliegue de test, y la epoca restaurada se elegia mirando el
    test (sesgo optimista).
    """
    # El numero de clases sale de la forma de y si el experimento no lo
    # pasa, de modo que common/ no necesita conocer el dataset.
    num_clases = num_clases or int(y_train.shape[1])
    nombres = nombres_clases or nombres_por_defecto(num_clases)

    reentreno = lr_por_epoca is not None
    if reentreno:
        epochs = len(lr_por_epoca)
    val_es_test = X_test is None
    if val_es_test:
        X_test, y_test = X_val, y_val
    if seed is not None:
        fijar_semilla(seed, fold_idx, determinismo)
    print(f"\n{'='*60}")
    print(f"  PLIEGUE {fold_idx + 1}")
    if reentreno:
        print(f"  REENTRENO con todo el train: {X_train.shape[0]} | "
              f"Test: {X_test.shape[0]} | {epochs} epocas con el calendario "
              f"de lr de la seleccion")
    else:
        print(f"  Train: {X_train.shape[0]} | Val: {X_val.shape[0]}"
              + (" (= test)" if val_es_test else f" | Test: {X_test.shape[0]}"))
    print(f"{'='*60}")

    clases, counts = np.unique(y_train.argmax(axis=1), return_counts=True)
    print(f"  Distribucion train: {dict(zip(clases.tolist(), counts.tolist()))}")

    modelo = construir_modelo(
        window_size=X_train.shape[1],
        num_features=X_train.shape[2],
        num_clases=num_clases,
    )
    modelo = compilar_modelo(modelo, lr=lr, label_smoothing=LABEL_SMOOTHING)

    # start_from_epoch descarta las primeras epocas del seguimiento de
    # 'best', no solo del contador de paciencia: con el umbral en 10,
    # restore_best_weights no puede devolver los pesos de la epoca 1.
    # Sin el, un pliegue cuyo val_loss sube desde la epoca 2 restaura un
    # modelo practicamente sin entrenar y su accuracy no mide nada.
    early_stopping = tf.keras.callbacks.EarlyStopping(
        monitor="val_loss",
        patience=15,
        restore_best_weights=True,
        start_from_epoch=early_stopping_start,
        verbose=0,
    )
    # Registra la tasa de aprendizaje con que EMPIEZA cada epoca, para que
    # un reentreno pueda reproducir el calendario que eligio ReduceLROnPlateau.
    registro_lr = []

    class RegistroLR(tf.keras.callbacks.Callback):
        def on_epoch_begin(self, epoch, logs=None):
            registro_lr.append(float(np.array(self.model.optimizer.learning_rate)))

    if reentreno:
        calendario = list(lr_por_epoca)
        callbacks = [
            tf.keras.callbacks.LearningRateScheduler(
                lambda epoca, lr_actual: calendario[epoca], verbose=0),
            RegistroLR(),
        ]
    else:
        callbacks = [
            early_stopping,
            tf.keras.callbacks.ReduceLROnPlateau(
                monitor="val_loss",
                factor=0.5,
                patience=7,
                min_lr=1e-6,
                verbose=0,
            ),
            RegistroLR(),
        ]

    train_ds = tf.data.Dataset.from_tensor_slices((X_train, y_train))
    train_ds = train_ds.map(augmentar_muestra, num_parallel_calls=tf.data.AUTOTUNE)
    train_ds = train_ds.shuffle(1024).batch(batch_size).prefetch(tf.data.AUTOTUNE)
    if reentreno:
        val_ds = None
    else:
        val_ds = tf.data.Dataset.from_tensor_slices((X_val, y_val))
        val_ds = val_ds.batch(batch_size).prefetch(tf.data.AUTOTUNE)

    t0 = time.time()
    history = modelo.fit(
        train_ds,
        validation_data=val_ds,
        epochs=epochs,
        callbacks=callbacks,
        verbose=0,
    )
    duracion = time.time() - t0

    loss, accuracy, auc = modelo.evaluate(X_test, y_test, verbose=0)
    y_pred = modelo.predict(X_test, verbose=0)

    y_true_int = y_test.argmax(axis=1)
    y_pred_int = y_pred.argmax(axis=1)
    f1_macro = f1_score(y_true_int, y_pred_int, average="macro", zero_division=0)
    f1_clases = f1_score(
        y_true_int, y_pred_int, average=None,
        labels=range(num_clases), zero_division=0,
    )

    n_epocas = len(history.history["loss"])
    paro_temprano = (not reentreno) and n_epocas < epochs

    # Dos numeros distintos que conviene no confundir:
    #  - epoca_argmin_global: donde esta el minimo de val_loss en toda la
    #    curva, incluidas las epocas anteriores al umbral.
    #  - epoca_restaurada: la que EarlyStopping realmente devolvio en los
    #    pesos, que con start_from_epoch>0 nunca es anterior al umbral.
    # Reportar solo el primero mentiria sobre que modelo se evaluo.
    if reentreno:
        # No hay validacion: el modelo evaluado es el de la ultima epoca.
        epoca_argmin_global = None
        epoca_restaurada = n_epocas
        en_el_umbral = False
    else:
        epoca_argmin_global = int(np.argmin(history.history["val_loss"])) + 1
        epoca_restaurada = int(getattr(early_stopping, "best_epoch", 0)) + 1
        en_el_umbral = epoca_restaurada <= early_stopping_start + 1

    print(f"  Resultados Pliegue {fold_idx + 1}:")
    print(f"    Loss:       {loss:.4f}")
    print(f"    Accuracy:   {accuracy:.4f} ({accuracy*100:.2f}%)")
    print(f"    AUC:        {auc:.4f}")
    print(f"    F1 macro:   {f1_macro:.4f}")
    print(f"    Epocas:     {n_epocas} "
          f"(early stopping: {'si' if paro_temprano else 'no, tope de epocas'})")
    print(f"    Epoca restaurada:  {epoca_restaurada}"
          f"{'  <-- pegada al umbral' if en_el_umbral else ''}")
    print(f"    Argmin val_loss:   {epoca_argmin_global}")
    print(f"    Duracion:   {duracion/60:.1f} min")

    metricas = {
        "loss": float(loss),
        "accuracy": float(accuracy),
        "auc": float(auc),
        "f1_macro": float(f1_macro),
        "f1_por_clase": {
            nombres[i]: float(f1_clases[i]) for i in range(num_clases)
        },
        "epochs": int(n_epocas),
        "epoca_restaurada": epoca_restaurada,
        "epoca_argmin_global": epoca_argmin_global,
        "restaurada_en_el_umbral": bool(en_el_umbral),
        "detuvo_por_early_stopping": bool(paro_temprano),
        "duracion_seg": round(duracion, 1),
        "n_val_callbacks": 0 if reentreno else int(X_val.shape[0]),
        "n_test": int(X_test.shape[0]),
        "n_train": int(X_train.shape[0]),
        "lr_por_epoca": registro_lr,
        "reentreno": bool(reentreno),
    }

    del modelo
    tf.keras.backend.clear_session()

    return history, y_pred, metricas


def entrenar_con_validacion_interna(X_train, y_train, grupos_train,
                                    X_test, y_test, grupos_test, fold_idx,
                                    epochs, batch_size, lr,
                                    early_stopping_start=10, seed=None,
                                    determinismo=False, modo="interna",
                                    val_grupos=1, reentrenar=True, n_max=None,
                                    num_clases=None, nombres_clases=None):
    """
    El mismo mecanismo para entrenamiento_cv.py y para los scripts de
    experimentos/: nadie debe volver a pasar el test como validation_data.

    modo 'interna'       separa val_grupos grupos enteros del train (nunca
                         del test, con verificacion) para EarlyStopping y
                         ReduceLROnPlateau. Con reentrenar, entrena despues
                         desde cero con TODO el train durante las epocas y el
                         calendario de lr elegidos, y evalua ese modelo.
    modo 'reducido_test' control: los mismos grupos fuera del train, pero los
                         callbacks vigilan el test.
    modo 'test'          comportamiento historico, optimista.

    grupos_*: el vector con que se agrupa la particion (sujetos, o
    repeticiones si el agrupamiento es por repeticion).

    n_max: tope de ventanas de entrenamiento. Se aplica despues de separar
    la validacion, por separado en la seleccion y en el reentreno. Si ambos
    superan el tope, el reentreno no gana ventanas: solo la diversidad del
    grupo anadido.

    Returns: (history de la seleccion, probabilidades sobre test, metricas)
    """
    if reentrenar and modo != "interna":
        raise ValueError("reentrenar solo tiene sentido con modo 'interna'")
    rng_tope = np.random.RandomState((seed or 0) + 2000 + fold_idx)

    def tope(Xa, ya):
        if n_max is None or len(Xa) <= n_max:
            return Xa, ya
        idx = np.sort(rng_tope.choice(len(Xa), n_max, replace=False))
        return Xa[idx], ya[idx]

    if modo == "test":
        X_fit, y_fit = tope(X_train, y_train)
        X_mon, y_mon, X_eval, y_eval = X_test, y_test, None, None
        grupos_val = []
    else:
        rng_val = np.random.RandomState((seed or 0) + 1000 + fold_idx)
        grupos_val = sorted(rng_val.choice(
            np.unique(grupos_train), val_grupos, replace=False).tolist())
        en_val = np.isin(grupos_train, grupos_val)
        fuga_test = set(grupos_val) & set(np.unique(grupos_test).tolist())
        fuga_train = set(grupos_val) & set(np.unique(grupos_train[~en_val]).tolist())
        assert not fuga_test, f"validacion interna con grupos de test: {fuga_test}"
        assert not fuga_train, f"validacion interna con grupos de train: {fuga_train}"
        X_fit, y_fit = tope(X_train[~en_val], y_train[~en_val])
        if modo == "interna":
            X_mon, y_mon = X_train[en_val], y_train[en_val]
        else:
            X_mon, y_mon = X_test, y_test
        X_eval, y_eval = X_test, y_test
        print(f"  Validacion {modo}: grupos {grupos_val} "
              f"({int(en_val.sum())} ventanas separadas del train)")

    history, y_pred, metricas = entrenar_pliegue(
        X_fit, y_fit, X_mon, y_mon, fold_idx, epochs, batch_size, lr,
        early_stopping_start=early_stopping_start,
        seed=seed, determinismo=determinismo,
        X_test=X_eval, y_test=y_eval,
        num_clases=num_clases, nombres_clases=nombres_clases,
    )
    metricas["validacion"] = modo
    metricas["grupos_validacion"] = list(grupos_val)

    if reentrenar:
        # Fase 2: todo el train, las epocas y el calendario de lr que eligio
        # la validacion interna. El test sigue sin intervenir en ninguna
        # decision.
        n_ep = max(1, int(metricas["epoca_restaurada"]))
        calendario = metricas["lr_por_epoca"][:n_ep]
        X_re, y_re = tope(X_train, y_train)
        _, y_pred, metricas_final = entrenar_pliegue(
            X_re, y_re, None, None, fold_idx, epochs, batch_size, lr,
            seed=seed, determinismo=determinismo,
            X_test=X_test, y_test=y_test, lr_por_epoca=calendario,
            num_clases=num_clases, nombres_clases=nombres_clases,
        )
        metricas_final["validacion"] = "interna+reentreno"
        metricas_final["grupos_validacion"] = list(grupos_val)
        # El diagnostico de early stopping es el de la SELECCION, la unica
        # fase con val_loss.
        for clave in ("epoca_restaurada", "epoca_argmin_global",
                      "restaurada_en_el_umbral", "detuvo_por_early_stopping"):
            metricas_final[clave] = metricas[clave]
        metricas_final["seleccion"] = {
            k: metricas[k] for k in
            ("accuracy", "f1_macro", "auc", "loss", "epochs",
             "epoca_restaurada", "restaurada_en_el_umbral",
             "detuvo_por_early_stopping", "n_train", "duracion_seg")
        }
        print(f"    Seleccion: acc {metricas['accuracy']:.4f} -> reentreno "
              f"(todo el train): acc {metricas_final['accuracy']:.4f}")
        metricas = metricas_final

    return history, y_pred, metricas

