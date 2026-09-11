"""
analizar_fronteras.py - Cuantifica las ventanas que cruzan discontinuidades
===========================================================================
Protesis transradial - Auditoria de la linea base sobre NinaPro DB5

MOTIVO:
  Al preparar la ruta LMG se detecto que deslizar la ventana sobre un
  array del que se han eliminado filas produce ventanas que cruzan el
  hueco y mezclan el final de un bloque con el principio de otro. La
  ruta EMG hace exactamente eso: mapear_etiquetas descarta las filas
  cuyo restimulus no esta en el mapeo del ejercicio, y el ventaneo
  posterior corre sobre el array ya compactado.

  Este script CUANTIFICA cuantas de las ventanas de la linea base estan
  afectadas. No corrige nada y no reejecuta ningun entrenamiento: los
  resultados publicados en resultados_cv/ se conservan tal cual. El
  numero sirve para declarar la limitacion en la discusion con una cifra
  propia en vez de con una conjetura.

TIPOS DE FRONTERA:
  hueco      La ventana abarca indices que no eran consecutivos en la
             grabacion original, porque el filtrado por etiqueta elimino
             las filas intermedias. Es la mas grave: la senal tiene un
             salto fisico en mitad de la ventana.
  repeticion La ventana abarca mas de un valor de 'repetition'. Importa
             porque el esquema de la linea base agrupaba justamente por
             repeticion: una ventana asi pertenece a dos grupos a la vez.
  etiqueta   La ventana abarca mas de una clase. El voto mayoritario le
             asigna una sola, asi que parte de su contenido contradice
             su etiqueta.
  ejercicio  Imposible por construccion: cada archivo .mat se ventanea
             por separado y solo despues se concatena. Se verifica.

USO:
  python analizar_fronteras.py --mat ./NinaPro_DB5/
"""

import argparse
import json
import os

import numpy as np

from preprocesamiento_ninapro import (
    CargadorNinaProDB5,
    MAPEO_E1, MAPEO_E2, MAPEO_E3,
    NOMBRES_GESTOS, NUM_CLASES,
    STRIDE_SAMPLES, VENTANA_SAMPLES,
    mapear_etiquetas,
    remuestrear_acelerometro,
    seleccionar_canales,
    submuestrear_clase_0,
)

# Bits del vector de banderas. Se empaquetan en un entero para poder
# pasarlos por el mismo camino de indexado que usa el submuestreo.
BIT_HUECO      = 1
BIT_REPETICION = 2
BIT_ETIQUETA   = 4


def analizar_archivo(labels_mapeadas, mask, repetition, nombre):
    """
    Replica el bucle de ventaneo de SlidingWindowNinaPro contando las
    fronteras que cruza cada ventana. Devuelve (banderas, etiquetas).

    El bucle es deliberadamente identico al del preprocesamiento
    (mismo rango, mismo stride, mismo criterio de descarte) para que el
    conteo corresponda una a una con las ventanas reales.
    """
    idx_original = np.where(mask)[0]          # indices en la grabacion
    labels_filtradas = labels_mapeadas[mask]
    rep_filtrada = repetition[mask]
    n = len(idx_original)

    banderas = []
    etiquetas = []

    for inicio in range(0, n - VENTANA_SAMPLES + 1, STRIDE_SAMPLES):
        fin = inicio + VENTANA_SAMPLES

        etiquetas_en_ventana = labels_filtradas[inicio:fin]
        validas = etiquetas_en_ventana[etiquetas_en_ventana >= 0]
        if len(validas) == 0:
            continue
        etiquetas.append(int(np.bincount(validas).argmax()))

        f = 0
        # Hueco: los indices originales dejaron de ser consecutivos
        if np.any(np.diff(idx_original[inicio:fin]) != 1):
            f |= BIT_HUECO
        # Mas de una repeticion dentro de la ventana
        if len(np.unique(rep_filtrada[inicio:fin])) > 1:
            f |= BIT_REPETICION
        # Mas de una etiqueta dentro de la ventana
        if len(np.unique(etiquetas_en_ventana)) > 1:
            f |= BIT_ETIQUETA
        banderas.append(f)

    return np.array(banderas, dtype=np.int32), np.array(etiquetas, dtype=np.int32)


def main():
    parser = argparse.ArgumentParser(
        description="Cuenta ventanas que cruzan discontinuidades en DB5"
    )
    parser.add_argument("--mat", type=str, required=True)
    parser.add_argument("--output_dir", type=str, default="resultados_cv")
    args = parser.parse_args()

    cargador = CargadorNinaProDB5(args.mat)
    archivos = cargador.cargar_todos()

    todas_banderas = []
    todas_etiquetas = []
    todos_sujetos = []
    por_ejercicio = {}

    for idx, (emg_raw, acc_raw, labels, repetition, sid, eid) in enumerate(archivos):
        nombre = cargador.archivos[idx].name

        if "E2" in nombre:
            mapeo = MAPEO_E2
        elif "E3" in nombre:
            mapeo = MAPEO_E3
        else:
            mapeo = MAPEO_E1

        mask, labels_mapeadas = mapear_etiquetas(labels, mapeo)
        if mask.sum() == 0:
            continue

        banderas, etiquetas = analizar_archivo(
            labels_mapeadas, mask, repetition, nombre
        )
        todas_banderas.append(banderas)
        todas_etiquetas.append(etiquetas)
        todos_sujetos.append(np.full(len(banderas), sid, dtype=np.int32))

        clave = f"E{eid}"
        d = por_ejercicio.setdefault(clave, {"ventanas": 0, "hueco": 0,
                                             "repeticion": 0, "etiqueta": 0})
        d["ventanas"] += len(banderas)
        d["hueco"] += int((banderas & BIT_HUECO).astype(bool).sum())
        d["repeticion"] += int((banderas & BIT_REPETICION).astype(bool).sum())
        d["etiqueta"] += int((banderas & BIT_ETIQUETA).astype(bool).sum())

    banderas = np.concatenate(todas_banderas)
    etiquetas = np.concatenate(todas_etiquetas)
    sujetos = np.concatenate(todos_sujetos)
    y = np.eye(NUM_CLASES, dtype=np.float32)[etiquetas]

    n_antes = len(banderas)

    # Aplicar EL MISMO submuestreo que la linea base. Se pasa el vector
    # de banderas por el hueco de 'grupos' para que reciba exactamente el
    # mismo indexado (misma semilla, misma secuencia de RNG) que
    # recibieron X, y y los grupos en la corrida original. X se sustituye
    # por un array minimo porque submuestrear_clase_0 solo lo indexa.
    X_dummy = np.zeros((n_antes, 1, 1), dtype=np.float32)
    _, y_bal, banderas_bal, sujetos_bal = submuestrear_clase_0(
        X_dummy, y, banderas, sujetos
    )

    n = len(banderas_bal)
    etiquetas_bal = y_bal.argmax(axis=1)

    hueco = (banderas_bal & BIT_HUECO).astype(bool)
    rep = (banderas_bal & BIT_REPETICION).astype(bool)
    lab = (banderas_bal & BIT_ETIQUETA).astype(bool)
    cualquiera = hueco | rep | lab

    print("\n" + "=" * 72)
    print("VENTANAS QUE CRUZAN DISCONTINUIDADES - LINEA BASE NinaPro DB5")
    print("=" * 72)
    print(f"  Ventanas antes del submuestreo de Rest : {n_antes}")
    print(f"  Ventanas del dataset final             : {n}")
    print()
    print(f"  {'Tipo de frontera':<24}{'Ventanas':>12}{'% del total':>14}")
    print(f"  {'-'*50}")
    for nombre, m in (("Hueco en la grabacion", hueco),
                      ("Cambio de repeticion", rep),
                      ("Cambio de etiqueta", lab),
                      ("Cualquiera de las tres", cualquiera)):
        print(f"  {nombre:<24}{int(m.sum()):>12}{100*m.mean():>13.2f}%")
    print()
    print(f"  Cambio de ejercicio: 0 por construccion. Cada archivo .mat")
    print(f"  se ventanea por separado y solo despues se concatenan las")
    print(f"  ventanas, asi que ninguna puede abarcar E2 y E3 a la vez.")

    print()
    print(f"  Reparto por clase de las ventanas afectadas:")
    print(f"  {'Clase':<14}{'Total':>10}{'Afectadas':>12}{'%':>9}")
    print(f"  {'-'*45}")
    for c in range(NUM_CLASES):
        m = etiquetas_bal == c
        n_c = int(m.sum())
        n_a = int(cualquiera[m].sum())
        pct = 100 * n_a / n_c if n_c else 0.0
        print(f"  {NOMBRES_GESTOS[c]:<14}{n_c:>10}{n_a:>12}{pct:>8.2f}%")

    print()
    print(f"  Reparto por ejercicio (antes del submuestreo):")
    print(f"  {'Ejercicio':<12}{'Ventanas':>11}{'Hueco':>10}{'Repeticion':>13}")
    print(f"  {'-'*46}")
    for k in sorted(por_ejercicio):
        d = por_ejercicio[k]
        print(f"  {k:<12}{d['ventanas']:>11}{d['hueco']:>10}"
              f"{d['repeticion']:>13}")

    resultado = {
        "_nota": "Auditoria de la linea base. NO corrige nada ni reejecuta "
                 "entrenamientos; los resultados de resultados_cv/ se "
                 "conservan. El numero se declara como limitacion.",
        "n_ventanas_antes_submuestreo": int(n_antes),
        "n_ventanas_final": int(n),
        "cruzan_hueco": int(hueco.sum()),
        "cruzan_repeticion": int(rep.sum()),
        "cruzan_etiqueta": int(lab.sum()),
        "cruzan_cualquiera": int(cualquiera.sum()),
        "pct_cruzan_cualquiera": round(100 * float(cualquiera.mean()), 4),
        "cruzan_ejercicio": 0,
        "por_clase": {
            NOMBRES_GESTOS[c]: {
                "total": int((etiquetas_bal == c).sum()),
                "afectadas": int(cualquiera[etiquetas_bal == c].sum()),
            }
            for c in range(NUM_CLASES)
        },
        "por_ejercicio_antes_submuestreo": por_ejercicio,
    }

    os.makedirs(args.output_dir, exist_ok=True)
    ruta = os.path.join(args.output_dir, "analisis_fronteras.json")
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(resultado, f, indent=2, ensure_ascii=False)
    print(f"\n[JSON] {ruta}")


if __name__ == "__main__":
    main()
