"""
ablacion_imu.py - Aporta la IMU sobre la LMG sola?
===================================================
Protesis transradial - Experimento central del trabajo

DISENO FACTORIAL 2x2:

  Factor A, que alimenta al modelo
    solo_lmg   5 canales opticos
    lmg_imu    5 canales opticos + 3 del acelerometro

  Factor B, condicion postural de las repeticiones evaluadas
    estatica   el brazo no se mueve
    dinamica   el brazo recorre tres posiciones durante la contraccion

LO UNICO QUE CAMBIA ENTRE CELDAS son las columnas de entrada (A) y las
repeticiones sobre las que se mide (B). Arquitectura, hiperparametros,
ventana, stride, submuestreo de Rest, particion y semilla son identicos,
y verificar_identidad_de_configuracion() lo comprueba en vez de confiar
en que asi sea.

TRES MODOS DE ENTRENAMIENTO, TRES PREGUNTAS DISTINTAS (--entrenamiento):

  mixto (por defecto)
      Un modelo por nivel de A, entrenado con las dos condiciones
      mezcladas, que es como se usaria una protesis real, y medido por
      separado en cada una. El factor B es una particion de la
      EVALUACION y no un cambio del entrenamiento, asi que las dos
      celdas de una fila comparten pesos y su diferencia viene de la
      condicion, no de haber entrenado con la mitad de los datos.
      Pregunta: cuanto aporta la IMU en cada condicion.

  por_condicion
      Un modelo por celda, entrenado y evaluado dentro de la misma
      condicion. Pregunta: cuanto rinde un modelo especializado por
      postura. NO mide generalizacion, porque nunca se le pide predecir
      una postura que no vio.

  estatica_a_dinamica
      GENERALIZACION ENTRE POSTURAS. Entrena SOLO con repeticiones
      estaticas y evalua sobre las dos condiciones de los sujetos de
      test: la celda dinamica es entonces terreno desconocido y la
      distancia con la estatica es la caida por cambio de postura.
      Pregunta, y es la prueba directa de que la IMU compensa el efecto
      de posicion: la caida tiene que ser MENOR en lmg_imu.

  Los tres modos usan la misma particion, la misma semilla y la misma
  arquitectura. Lo que cambia es que ve el modelo en entrenamiento, y
  por eso las cifras absolutas de un modo NO se comparan con las de
  otro: en estatica_a_dinamica se entrena con la mitad de los datos.
  Lo comparable es siempre la distancia DENTRO de una misma corrida.

VALIDACION:
  GroupKFold por sujeto, k=5, con la verificacion de fuga de
  common/validacion.py y su autotest. Cada pliegue entrena con validacion
  interna y reentreno, nunca mirando el test.

NORMALIZACION:
  Por sujeto, con la media y la desviacion de SU bloque de calibracion,
  que es lo unico que el firmware puede medir antes de empezar.

USO:
  python ablacion_imu.py --sesiones "../../sesiones/*.csv"
  python ablacion_imu.py --sesiones "..." --entrenamiento estatica_a_dinamica
  python ablacion_imu.py --simulado          (sin piloto, para probar)
"""

# Rutas del Modulo 2 tras la reorganizacion: common/ tiene el codigo
# compartido por todos los experimentos y produccion/ el pipeline del
# modelo que se despliega.
import os as _os
import sys as _sys
_M2 = _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                     "..", ".."))
for _d in (_M2, _os.path.join(_M2, "common"), _os.path.join(_M2, "produccion"),
           _os.path.join(_M2, "captura")):
    if _d not in _sys.path:
        _sys.path.insert(0, _d)

import argparse
import json
import os
import time
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix, roc_auc_score

import datos as D
from metricas import graficar_matriz_confusion, metricas, por_sujeto
from validacion import autotest_verificador, generar_particiones

CONDICIONES = list(D.CONDICIONES_POSTURALES)     # estatica, dinamica
COMPOSICIONES = list(D.COMPOSICIONES)            # solo_lmg, lmg_imu


def configuracion_de_celda(args, composicion: str, condicion: str) -> dict:
    """
    Todo lo que define una celda. Lo que no sea la composicion de canales
    o la condicion evaluada tiene que coincidir entre las cuatro.
    """
    return {
        "composicion": composicion,
        "condicion": condicion,
        "ventana_ms": args.ventana_ms,
        "stride_ms": args.stride_ms,
        "folds": args.folds,
        "agrupamiento": "sujeto",
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "lr": args.lr,
        "early_stopping_start": args.early_stopping_start,
        "semilla": args.seed,
        "normalizacion": "sujeto_calibracion",
        "submuestreo_rest": args.ratio_rest,
        "entrenamiento": args.entrenamiento,
        "num_clases": D.NUM_CLASES,
    }


def verificar_identidad_de_configuracion(configs: dict) -> str:
    """
    Falla si dos celdas difieren en algo que no sean sus dos factores.

    Es la comprobacion que sostiene todo el experimento: si una celda
    corriera con otra semilla o con otro numero de epocas, la diferencia
    medida ya no seria atribuible a la IMU ni a la postura. Se verifica
    en vez de confiar, porque este es justo el tipo de fallo que no da
    ningun sintoma.
    """
    libres = {"composicion", "condicion"}
    referencia = None
    for nombre, cfg in sorted(configs.items()):
        fijo = {k: v for k, v in cfg.items() if k not in libres}
        if referencia is None:
            referencia, nombre_ref = fijo, nombre
            continue
        difieren = {k: (referencia[k], fijo[k]) for k in fijo
                    if referencia[k] != fijo[k]}
        if difieren:
            raise AssertionError(
                f"Las celdas {nombre_ref} y {nombre} difieren en algo que "
                f"deberia ser identico: {difieren}")
    n_canales = {c: len(D.COMPOSICIONES[configs[c]["composicion"]])
                 for c in configs}
    return ("[VERIFICACION] Las 4 celdas comparten arquitectura, "
            "hiperparametros, ventana, stride, particion y semilla. "
            f"Canales por celda: {n_canales}")


def auc_seguro(y_true_int, prob) -> float:
    """AUC macro one-vs-rest, o NaN si falta alguna clase en el test."""
    try:
        return float(roc_auc_score(
            np.eye(D.NUM_CLASES)[y_true_int], prob,
            multi_class="ovr", average="macro"))
    except ValueError:
        return float("nan")


def entrenar_composicion(v: D.Ventanas, composicion: str, args) -> dict:
    """
    Corre los k pliegues de un nivel del factor A y devuelve las
    predicciones de todas las ventanas de evaluacion.
    """
    from entrenamiento import entrenar_con_validacion_interna   # carga TF

    cols = D.indices_de_canales(composicion)
    stats = D.estadisticas_de_calibracion(v)

    # El entrenamiento y la evaluacion excluyen la calibracion: es reposo
    # basal, ya se uso para normalizar, y dejarla dentro inflaria Rest.
    uso = v.es_calibracion == 0
    vu = v.subconjunto(uso)
    X = D.seleccionar_canales(vu, composicion)
    X = D.normalizar_por_calibracion(X, vu.sujeto, stats, cols)
    Y = np.eye(D.NUM_CLASES, dtype=np.float32)[vu.y]

    print(autotest_verificador(vu.sujeto, seed=args.seed))

    prob = np.zeros((len(vu), D.NUM_CLASES), dtype=np.float32)
    pliegue_de = np.full(len(vu), -1, dtype=np.int16)
    for k, (tr, te) in enumerate(generar_particiones(
            X, vu.y, vu.repeticion, vu.sujeto, "sujeto",
            n_splits=args.folds, seed=args.seed)):
        if args.entrenamiento == "por_condicion":
            # Variante: el modelo solo ve la condicion que se evalua.
            # Se corre una vez por condicion y se combinan las salidas.
            for cond in CONDICIONES:
                m_tr = tr[vu.condicion[tr] == cond]
                m_te = te[vu.condicion[te] == cond]
                if not len(m_tr) or not len(m_te):
                    continue
                _, p, _ = entrenar_con_validacion_interna(
                    X[m_tr], Y[m_tr], vu.sujeto[m_tr],
                    X[m_te], Y[m_te], vu.sujeto[m_te], k,
                    args.epochs, args.batch_size, args.lr,
                    early_stopping_start=args.early_stopping_start,
                    seed=args.seed, num_clases=D.NUM_CLASES,
                    nombres_clases=D.NOMBRES_GESTOS)
                prob[m_te] = p
                pliegue_de[m_te] = k
        elif args.entrenamiento == "estatica_a_dinamica":
            # PRUEBA DE GENERALIZACION ENTRE POSTURAS.
            #
            # El modelo entrena SOLO con repeticiones estaticas y se
            # evalua sobre las dos condiciones de los sujetos de test.
            # La celda dinamica es entonces generalizacion pura: el
            # modelo nunca vio el brazo en movimiento. La celda estatica
            # es la referencia en condicion conocida, medida sobre los
            # mismos sujetos de test, y la distancia entre las dos es la
            # caida por cambio de postura.
            #
            # Con entrenamiento mixto esto no se puede medir, porque el
            # modelo ya habria visto repeticiones dinamicas, y con
            # por_condicion tampoco, porque cada modelo se queda dentro
            # de su condicion.
            m_tr = tr[vu.condicion[tr] == D.CONDICION_ESTATICA]
            if not len(m_tr):
                raise ValueError(
                    f"El pliegue {k} no tiene repeticiones estaticas en "
                    f"train: revise el reparto de condiciones del CSV.")
            _, p, _ = entrenar_con_validacion_interna(
                X[m_tr], Y[m_tr], vu.sujeto[m_tr],
                X[te], Y[te], vu.sujeto[te], k,
                args.epochs, args.batch_size, args.lr,
                early_stopping_start=args.early_stopping_start,
                seed=args.seed, num_clases=D.NUM_CLASES,
                nombres_clases=D.NOMBRES_GESTOS)
            prob[te] = p
            pliegue_de[te] = k
        else:
            _, p, _ = entrenar_con_validacion_interna(
                X[tr], Y[tr], vu.sujeto[tr], X[te], Y[te], vu.sujeto[te], k,
                args.epochs, args.batch_size, args.lr,
                early_stopping_start=args.early_stopping_start,
                seed=args.seed, num_clases=D.NUM_CLASES,
                nombres_clases=D.NOMBRES_GESTOS)
            prob[te] = p
            pliegue_de[te] = k

    return {"ventanas": vu, "prob": prob, "pliegue": pliegue_de}


def medir_celda(salida: dict, condicion: str) -> dict:
    """
    Metricas de una celda: las ventanas de UNA condicion, evaluadas con
    las predicciones del nivel de A correspondiente.
    """
    vu = salida["ventanas"]
    m = (vu.condicion == condicion) & (salida["pliegue"] >= 0)
    y_true = vu.y[m]
    prob = salida["prob"][m]
    y_pred = prob.argmax(axis=1)

    global_ = metricas(y_true, y_pred, D.NOMBRES_GESTOS)
    global_["auc"] = auc_seguro(y_true, prob)

    sujetos = vu.sujeto[m]
    por_suj = por_sujeto(y_true, y_pred, sujetos, D.NOMBRES_GESTOS)
    for s in por_suj:
        ms = sujetos == s
        por_suj[s]["auc"] = auc_seguro(y_true[ms], prob[ms])

    pliegues = salida["pliegue"][m]
    por_pliegue = {}
    for k in sorted(set(pliegues.tolist())):
        mk = pliegues == k
        por_pliegue[int(k)] = metricas(y_true[mk], y_pred[mk],
                                       D.NOMBRES_GESTOS)

    return {
        "global": global_,
        "por_sujeto": por_suj,
        "por_pliegue": por_pliegue,
        "matriz_confusion": confusion_matrix(
            y_true, y_pred, labels=list(range(D.NUM_CLASES))).tolist(),
        "n_ventanas": int(m.sum()),
    }


def caida_entre_posturas(celdas: dict) -> dict:
    """
    Cuanto se pierde al evaluar en dinamica respecto de estatica.

    Con --entrenamiento estatica_a_dinamica es LA cifra del experimento:
    el modelo solo vio el brazo quieto, asi que la celda dinamica es
    generalizacion pura y la distancia con la estatica mide el efecto de
    cambiar de postura. Si la IMU compensa ese efecto, la caida tiene que
    ser MENOR en lmg_imu que en solo_lmg.

    La caida se da en puntos absolutos y en porcentaje del valor
    estatico: con exactitudes de partida distintas entre composiciones,
    la absoluta sola puede enganar.
    """
    salida = {}
    for composicion in COMPOSICIONES:
        est = celdas[f"{composicion}|{D.CONDICION_ESTATICA}"]
        din = celdas[f"{composicion}|{D.CONDICION_DINAMICA}"]
        a_est = est["global"]["accuracy"]
        a_din = din["global"]["accuracy"]

        # Por sujeto, que es lo que despues se contrasta de forma pareada.
        sujetos = sorted(set(est["por_sujeto"]) & set(din["por_sujeto"]))
        por_suj = {
            s: {
                "estatica": est["por_sujeto"][s]["accuracy"],
                "dinamica": din["por_sujeto"][s]["accuracy"],
                "caida": est["por_sujeto"][s]["accuracy"]
                         - din["por_sujeto"][s]["accuracy"],
            } for s in sujetos
        }
        caidas = np.array([v["caida"] for v in por_suj.values()])

        salida[composicion] = {
            "accuracy_estatica": a_est,
            "accuracy_dinamica": a_din,
            "caida_absoluta": a_est - a_din,
            "caida_relativa": (a_est - a_din) / a_est if a_est else float("nan"),
            "caida_media_por_sujeto": float(caidas.mean()) if len(caidas) else float("nan"),
            "caida_sd_por_sujeto": float(caidas.std(ddof=1)) if len(caidas) > 1 else float("nan"),
            "por_sujeto": por_suj,
        }

    if len(COMPOSICIONES) == 2:
        a, b = COMPOSICIONES
        salida["diferencia_de_caidas"] = {
            "definicion": f"caida({a}) - caida({b})",
            "absoluta": (salida[a]["caida_absoluta"]
                         - salida[b]["caida_absoluta"]),
            "lectura": (f"positivo significa que {b} aguanta mejor el cambio "
                        f"de postura, que es lo que se espera si la IMU "
                        f"compensa el efecto de posicion"),
        }
    return salida


def main():
    p = argparse.ArgumentParser(description="Ablacion de la IMU (2x2)")
    p.add_argument("--sesiones", type=str,
                   default=os.path.join(_M2, "sesiones", "*.csv"),
                   help="Patron de los CSV de sesion")
    p.add_argument("--simulado", action="store_true",
                   help="Genera sesiones sinteticas y corre sobre ellas")
    p.add_argument("--n_sujetos_sim", type=int, default=10)
    p.add_argument("--ventana_ms", type=int, default=200)
    p.add_argument("--stride_ms", type=int, default=20)
    p.add_argument("--folds", type=int, default=5)
    p.add_argument("--epochs", type=int, default=100)
    p.add_argument("--batch_size", type=int, default=32)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--early_stopping_start", type=int, default=10)
    p.add_argument("--ratio_rest", type=float, default=1.0)
    p.add_argument("--entrenamiento",
                   choices=["mixto", "por_condicion", "estatica_a_dinamica"],
                   default="mixto",
                   help="mixto: entrena con las dos condiciones y mide en "
                        "cada una. por_condicion: un modelo por condicion. "
                        "estatica_a_dinamica: entrena solo con estaticas y "
                        "mide la caida al evaluar en dinamicas")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--output", type=str,
                   default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        "resultados"))
    args = p.parse_args()
    os.makedirs(args.output, exist_ok=True)

    patron = args.sesiones
    if args.simulado:
        patron = D.generar_sesiones_sinteticas(
            os.path.join(args.output, "sesiones_sinteticas"),
            n_sujetos=args.n_sujetos_sim, semilla=args.seed)

    # ---------- configuracion de las 4 celdas, verificada ----------
    configs = {f"{c}|{k}": configuracion_de_celda(args, c, k)
               for c in COMPOSICIONES for k in CONDICIONES}
    print(verificar_identidad_de_configuracion(configs))

    # ---------- datos, comunes a las 4 celdas ----------
    df = D.cargar_sesiones(patron)
    v = D.ventanear(df, args.ventana_ms, args.stride_ms)
    v = D.submuestrear_rest(v, semilla=args.seed, ratio=args.ratio_rest)

    reparto = {c: int(((v.condicion == c) & (v.es_calibracion == 0)).sum())
               for c in CONDICIONES}
    print(f"[DATOS] Ventanas por condicion: {reparto}")

    # ---------- las cuatro celdas ----------
    t0 = time.time()
    celdas, salidas = {}, {}
    for composicion in COMPOSICIONES:
        print(f"\n{'=' * 70}\n  FACTOR A = {composicion}\n{'=' * 70}")
        salidas[composicion] = entrenar_composicion(v, composicion, args)
        for condicion in CONDICIONES:
            nombre = f"{composicion}|{condicion}"
            celdas[nombre] = medir_celda(salidas[composicion], condicion)
            g = celdas[nombre]["global"]
            print(f"[CELDA] {nombre:<22} acc {g['accuracy']:.4f}  "
                  f"F1 {g['f1_macro']:.4f}  AUC {g['auc']:.4f}  "
                  f"n {celdas[nombre]['n_ventanas']}")
            graficar_matriz_confusion(
                np.array(celdas[nombre]["matriz_confusion"]),
                nombre.replace("|", " "), args.output,
                nombres_clases=D.NOMBRES_GESTOS)

    # ---------- caida por cambio de postura ----------
    caidas = caida_entre_posturas(celdas)
    print(f"\n{'=' * 70}")
    print("  CAIDA AL PASAR DE ESTATICA A DINAMICA")
    if args.entrenamiento == "estatica_a_dinamica":
        print("  (el modelo SOLO vio repeticiones estaticas: la celda "
              "dinamica es generalizacion pura)")
    else:
        print(f"  (entrenamiento '{args.entrenamiento}': el modelo TAMBIEN vio "
              "dinamicas, asi que esto no mide generalizacion)")
    print("=" * 70)
    print(f"  {'':<10}{'estatica':>11}{'dinamica':>11}{'caida':>9}"
          f"{'relativa':>11}{'por sujeto':>13}")
    for composicion in COMPOSICIONES:
        c = caidas[composicion]
        print(f"  {composicion:<10}{c['accuracy_estatica']:11.4f}"
              f"{c['accuracy_dinamica']:11.4f}{c['caida_absoluta']:+9.4f}"
              f"{100 * c['caida_relativa']:10.1f}%"
              f"{c['caida_media_por_sujeto']:+13.4f}")
    if "diferencia_de_caidas" in caidas:
        d = caidas["diferencia_de_caidas"]
        print(f"  {d['definicion']} = {d['absoluta']:+.4f}")
        print(f"  {d['lectura']}")

    # ---------- salidas ----------
    reporte = {
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "duracion_s": round(time.time() - t0, 1),
        "sesiones": patron,
        "simulado": bool(args.simulado),
        "entrenamiento": args.entrenamiento,
        "configuracion": configs,
        "verificacion_identidad": verificar_identidad_de_configuracion(configs),
        "ventanas_por_condicion": reparto,
        "celdas": celdas,
        "caida_entre_posturas": caidas,
    }
    ruta_json = os.path.join(args.output, "ablacion_imu.json")
    with open(ruta_json, "w", encoding="utf-8") as f:
        json.dump(reporte, f, indent=2, ensure_ascii=False)

    filas = []
    for nombre, celda in celdas.items():
        composicion, condicion = nombre.split("|")
        for s, m in celda["por_sujeto"].items():
            filas.append({"composicion": composicion, "condicion": condicion,
                          "sujeto": s, "accuracy": m["accuracy"],
                          "f1_macro": m["f1_macro"], "auc": m["auc"],
                          "n": m["n"], "entrenamiento": args.entrenamiento})
    ruta_csv = os.path.join(args.output, "ablacion_imu_por_sujeto.csv")
    pd.DataFrame(filas).to_csv(ruta_csv, index=False)

    np.savez_compressed(
        os.path.join(args.output, "predicciones.npz"),
        **{f"prob_{c}": salidas[c]["prob"] for c in COMPOSICIONES},
        **{f"pliegue_{c}": salidas[c]["pliegue"] for c in COMPOSICIONES},
        y=salidas[COMPOSICIONES[0]]["ventanas"].y,
        sujeto=salidas[COMPOSICIONES[0]]["ventanas"].sujeto,
        condicion=salidas[COMPOSICIONES[0]]["ventanas"].condicion.astype(str),
        repeticion=salidas[COMPOSICIONES[0]]["ventanas"].repeticion)

    print(f"\n[SALIDA] {ruta_json}")
    print(f"[SALIDA] {ruta_csv}")
    print("\nPara los contrastes: python estadistica.py "
          f"--csv {ruta_csv}")


if __name__ == "__main__":
    main()
