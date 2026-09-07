"""
analizar_particion.py - Comparacion de esquemas de particion SIN entrenar
=========================================================================
Protesis transradial - Validacion con dataset NinaPro DB5

PARA QUE SIRVE:
  Con 10 sujetos y 5 clases, un GroupKFold agrupado por sujeto puede
  dejar pliegues desbalanceados en distribucion de clases. Este script
  responde esa pregunta ANTES de gastar horas de GPU: carga el dataset,
  construye las particiones con GroupKFold y con StratifiedGroupKFold, y
  reporta lado a lado la composicion de cada pliegue.

  No entrena nada y no toca ningun resultado guardado.

USO:
  python analizar_particion.py --mat ./NinaPro_DB5/
  python analizar_particion.py --mat ./NinaPro_DB5/ --cache cache.npz
"""

import argparse
import json
import os

import numpy as np

from preprocesamiento_ninapro import (
    cargar_procesar_dataset,
    NOMBRES_GESTOS,
    NUM_CLASES,
)
from particion import (
    autotest_verificador,
    describir_pliegue,
    formatear_pliegue,
    generar_particiones,
    obtener_vector_grupos,
)


def cargar_dataset(ruta_mat: str, cache: str = None):
    """Carga el dataset, con cache opcional en .npz para iterar rapido."""
    if cache and os.path.exists(cache):
        print(f"[CACHE] Leyendo dataset preprocesado de {cache}")
        d = np.load(cache)
        return d["X"], d["y"], d["grupos"], d["sujetos"]

    X, y, grupos, sujetos = cargar_procesar_dataset(ruta_mat)

    if cache:
        print(f"[CACHE] Guardando dataset preprocesado en {cache}")
        np.savez_compressed(
            cache, X=X, y=y, grupos=grupos, sujetos=sujetos
        )
    return X, y, grupos, sujetos


def desbalance_de_clases(descripciones: list) -> dict:
    """
    Cuantifica que tan desigual es la distribucion de clases entre pliegues.

    Para cada clase se toma la proporcion que representa dentro del test de
    cada pliegue y se reporta min, max y desviacion estandar entre pliegues.
    Un esquema mejor estratificado tendra rangos y desviaciones menores.
    """
    resumen = {}
    for clase in NOMBRES_GESTOS:
        props = [d["proporciones_test"][clase] for d in descripciones]
        resumen[clase] = {
            "min": round(float(np.min(props)), 4),
            "max": round(float(np.max(props)), 4),
            "rango": round(float(np.max(props) - np.min(props)), 4),
            "std": round(float(np.std(props)), 4),
            "por_pliegue": [round(float(p), 4) for p in props],
        }
    todas_std = [resumen[c]["std"] for c in NOMBRES_GESTOS]
    todos_rangos = [resumen[c]["rango"] for c in NOMBRES_GESTOS]
    resumen["_global"] = {
        "std_promedio": round(float(np.mean(todas_std)), 4),
        "rango_maximo": round(float(np.max(todos_rangos)), 4),
    }
    return resumen


def analizar_esquema(
    X, y_int, grupos_rep, sujetos, agrupamiento, n_splits, estratificado
):
    """Construye las particiones de un esquema y las describe."""
    nombre = ("StratifiedGroupKFold" if estratificado else "GroupKFold")
    print("\n" + "=" * 72)
    print(f"ESQUEMA: {nombre}(k={n_splits}) agrupado por {agrupamiento.upper()}")
    print("=" * 72)

    particiones = generar_particiones(
        X, y_int, grupos_rep, sujetos,
        agrupamiento=agrupamiento,
        n_splits=n_splits,
        estratificado=estratificado,
    )

    descripciones = []
    for i, (idx_tr, idx_te) in enumerate(particiones):
        d = describir_pliegue(
            i, idx_tr, idx_te, y_int, sujetos, grupos_rep, NOMBRES_GESTOS
        )
        descripciones.append(d)
        print(formatear_pliegue(d, agrupamiento))

    n_sujetos_test = [len(d["sujetos_test"]) for d in descripciones]
    print(f"\n  Sujetos por pliegue de test: {n_sujetos_test}")
    print(f"  Ventanas por pliegue de test: "
          f"{[d['n_test'] for d in descripciones]}")

    desbalance = desbalance_de_clases(descripciones)
    print(f"\n  Dispersion de la proporcion de cada clase en test:")
    print(f"    {'Clase':<14}{'min':>9}{'max':>9}{'rango':>9}{'std':>9}")
    for clase in NOMBRES_GESTOS:
        r = desbalance[clase]
        print(f"    {clase:<14}{r['min']:>9.4f}{r['max']:>9.4f}"
              f"{r['rango']:>9.4f}{r['std']:>9.4f}")
    print(f"    {'-'*50}")
    print(f"    std promedio entre clases: "
          f"{desbalance['_global']['std_promedio']:.4f}")
    print(f"    rango maximo:              "
          f"{desbalance['_global']['rango_maximo']:.4f}")

    return {
        "validador": nombre,
        "agrupamiento": agrupamiento,
        "n_splits": n_splits,
        "sujetos_por_pliegue_test": n_sujetos_test,
        "pliegues": descripciones,
        "desbalance_clases": desbalance,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Compara GroupKFold vs StratifiedGroupKFold agrupados "
                    "por sujeto, sin entrenar."
    )
    parser.add_argument("--mat", type=str, required=True,
                        help="Directorio con los .mat de NinaPro DB5")
    parser.add_argument("--folds", type=int, default=5,
                        help="Numero de pliegues (default: 5)")
    parser.add_argument("--cache", type=str, default=None,
                        help="Ruta .npz para cachear el dataset preprocesado")
    parser.add_argument("--output_dir", type=str, default="resultados_cv",
                        help="Directorio donde guardar el analisis en JSON")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    X, y, grupos_rep, sujetos = cargar_dataset(args.mat, args.cache)
    y_int = y.argmax(axis=1)

    print("\n" + "=" * 72)
    print("AUTOTEST DEL VERIFICADOR DE FUGA")
    print("=" * 72)
    print(autotest_verificador(sujetos))

    print("\n" + "=" * 72)
    print("DATASET")
    print("=" * 72)
    print(f"  Ventanas: {X.shape[0]}  |  forma: {X.shape[1:]}")
    print(f"  Sujetos:  {sorted(np.unique(sujetos).tolist())}")
    print(f"  Repeticiones: {sorted(np.unique(grupos_rep).tolist())}")
    print(f"  Distribucion global de clases:")
    for c in range(NUM_CLASES):
        n = int((y_int == c).sum())
        print(f"    {NOMBRES_GESTOS[c]:<14}{n:>8}  ({100*n/len(y_int):5.2f}%)")

    resultados = {}

    # Esquema de la linea base, solo como referencia de contraste
    resultados["repeticion_groupkfold"] = analizar_esquema(
        X, y_int, grupos_rep, sujetos, "repeticion", args.folds, False
    )

    resultados["sujeto_groupkfold"] = analizar_esquema(
        X, y_int, grupos_rep, sujetos, "sujeto", args.folds, False
    )

    resultados["sujeto_stratifiedgroupkfold"] = analizar_esquema(
        X, y_int, grupos_rep, sujetos, "sujeto", args.folds, True
    )

    # --- Veredicto comparativo ---
    print("\n" + "=" * 72)
    print("COMPARATIVA: GroupKFold vs StratifiedGroupKFold (por sujeto)")
    print("=" * 72)
    g = resultados["sujeto_groupkfold"]["desbalance_clases"]
    s = resultados["sujeto_stratifiedgroupkfold"]["desbalance_clases"]
    print(f"  {'Clase':<14}{'std GKF':>12}{'std SGKF':>12}{'mejora':>12}")
    for clase in NOMBRES_GESTOS:
        mejora = g[clase]["std"] - s[clase]["std"]
        print(f"  {clase:<14}{g[clase]['std']:>12.4f}{s[clase]['std']:>12.4f}"
              f"{mejora:>+12.4f}")
    print(f"  {'-'*50}")
    print(f"  {'std promedio':<14}{g['_global']['std_promedio']:>12.4f}"
          f"{s['_global']['std_promedio']:>12.4f}"
          f"{g['_global']['std_promedio'] - s['_global']['std_promedio']:>+12.4f}")
    print(f"  {'rango maximo':<14}{g['_global']['rango_maximo']:>12.4f}"
          f"{s['_global']['rango_maximo']:>12.4f}"
          f"{g['_global']['rango_maximo'] - s['_global']['rango_maximo']:>+12.4f}")
    print("\n  (valores menores = pliegues mas homogeneos en clases)")
    print("  Sujetos por pliegue de test:")
    print(f"    GroupKFold           : "
          f"{resultados['sujeto_groupkfold']['sujetos_por_pliegue_test']}")
    print(f"    StratifiedGroupKFold : "
          f"{resultados['sujeto_stratifiedgroupkfold']['sujetos_por_pliegue_test']}")

    ruta = os.path.join(args.output_dir, "analisis_particiones.json")
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(resultados, f, indent=2, ensure_ascii=False)
    print(f"\n[JSON] Analisis guardado en {ruta}")


if __name__ == "__main__":
    main()
