"""
comparar_resultados.py - Tabla comparativa entre configuraciones
=================================================================
Protesis transradial - Validacion con dataset NinaPro DB5

Lee los JSON de 'resultados_cv/' y produce la comparativa lado a lado:
accuracy, F1 macro, AUC, F1 por clase y epoca restaurada por pliegue.

Responde ademas de forma explicita a la pregunta del experimento de
normalizacion: si los pliegues que colapsaban dejan de restaurar pesos
pegados al umbral de early stopping.

USO:
  python comparar_resultados.py --dir resultados_cv
  python comparar_resultados.py --dir resultados_cv --salida comparativa.txt
"""

import argparse
import glob
import json
import os

import numpy as np

CLASES = ["Rest", "Pinch", "Tripod", "Power", "Finger_Ext"]

# Orden de presentacion y nombres cortos. Las claves son nombres de archivo
# EXACTOS: emparejar por subcadena hacia que 'metricas_groupkfold_sujeto'
# fuese prefijo de todos los 'metricas_groupkfold_sujeto_norm-*'.
ETIQUETAS_CORTAS = {
    "metricas_groupkfold_repeticion_SI2.json": "repeticion (SI2)",
    "metricas_groupkfold_repeticion_es10.json": "repeticion es=10",
    "metricas_groupkfold_sujeto.json": "sujeto es=0",
    "metricas_groupkfold_sujeto_norm-ninguna.json": "sujeto + ninguna",
    "metricas_groupkfold_sujeto_norm-global.json": "sujeto + global",
    "metricas_groupkfold_sujeto_norm-sujeto.json": "sujeto + sujeto",
    "metricas_groupkfold_sujeto_norm-sujeto_rest.json": "sujeto + sujeto_rest",
}
ORDEN_PREFERIDO = list(ETIQUETAS_CORTAS)


def clave_orden(ruta: str) -> int:
    base = os.path.basename(ruta)
    return (ORDEN_PREFERIDO.index(base) if base in ORDEN_PREFERIDO
            else len(ORDEN_PREFERIDO))


def etiqueta_corta(ruta: str, datos: dict = None) -> str:
    """
    Nombre corto para las tablas. Con nombre de archivo conocido usa el
    del catalogo; si no, lo deriva del contenido del propio JSON, que es
    mas fiable que adivinar desde el nombre.
    """
    base = os.path.basename(ruta)
    if base in ETIQUETAS_CORTAS:
        return ETIQUETAS_CORTAS[base]
    if datos:
        ag = val(datos, "esquema", "agrupamiento", default="?")
        nm = val(datos, "config", "normalizacion", default="ninguna")
        es = val(datos, "config", "early_stopping_start", default=0)
        return f"{ag} + {nm} es={es}"
    return base.removeprefix("metricas_").removesuffix(".json")


def leer(ruta: str) -> dict:
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def val(d: dict, *camino, default=None):
    """Acceso tolerante: los JSON antiguos no tienen todas las claves."""
    cur = d
    for k in camino:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def resumir(ruta: str) -> dict:
    r = leer(ruta)
    ag = r.get("agregado", {})
    por_clase = r.get("por_clase_global", {})

    # La linea base SI2 transcrita guarda el F1 macro en 'agregado'; las
    # corridas propias lo calculan por pliegue.
    f1_macro = ag.get("f1_macro_media", ag.get("f1_macro"))

    # Idem con la loss: la transcripcion solo tiene la lista por pliegue.
    loss_media = ag.get("loss_media")
    if loss_media is None and ag.get("loss_por_fold"):
        loss_media = float(np.mean(ag["loss_por_fold"]))

    return {
        "archivo": os.path.basename(ruta),
        "etiqueta": etiqueta_corta(ruta, r),
        "agrupamiento": val(r, "esquema", "agrupamiento", default="?"),
        "normalizacion": val(r, "config", "normalizacion", default="ninguna"),
        "es_start": val(r, "config", "early_stopping_start", default=0),
        "accuracy_media": ag.get("accuracy_media"),
        "accuracy_std": ag.get("accuracy_std"),
        "accuracy_por_fold": ag.get("accuracy_por_fold", []),
        "f1_macro": f1_macro,
        "auc_media": ag.get("auc_media"),
        "loss_media": loss_media,
        "epochs_por_fold": ag.get("epochs_por_fold", []),
        "epoca_restaurada_por_fold": ag.get("epoca_restaurada_por_fold", []),
        "pegados_al_umbral": ag.get("pliegues_restaurados_en_el_umbral"),
        "f1_por_clase": {
            c: (por_clase.get(c, {}).get("f1") if isinstance(por_clase.get(c), dict)
                else val(r, "f1_por_clase", c))
            for c in CLASES
        },
        "sujetos_test_por_fold": [
            p.get("sujetos_test") for p in r.get("pliegues", [])
        ],
    }


def fmt(v, ancho=10, dec=4):
    if v is None:
        return " " * (ancho - 2) + "--"
    return f"{v:>{ancho}.{dec}f}"


def construir_tabla(resumenes: list) -> str:
    L = []
    W = 22

    L.append("=" * 100)
    L.append("COMPARATIVA DE CONFIGURACIONES - NinaPro DB5, CNN-BiLSTM-Attention")
    L.append("=" * 100)
    L.append("")

    # --- Identificacion ---
    L.append("-" * 100)
    L.append("CONFIGURACIONES")
    L.append("-" * 100)
    L.append(f"  {'Etiqueta':<{W}}{'Agrupamiento':>16}{'Normalizacion':>16}"
             f"{'es_start':>10}   Archivo")
    for s in resumenes:
        L.append(f"  {s['etiqueta']:<{W}}{s['agrupamiento']:>16}"
                 f"{s['normalizacion']:>16}{str(s['es_start']):>10}   "
                 f"{s['archivo']}")
    L.append("")

    # --- Metricas globales ---
    L.append("-" * 100)
    L.append("METRICAS GLOBALES")
    L.append("-" * 100)
    L.append(f"  {'Etiqueta':<{W}}{'Accuracy':>11}{'std':>10}{'F1 macro':>11}"
             f"{'AUC':>10}{'Loss':>10}")
    L.append(f"  {'-'*74}")
    for s in resumenes:
        L.append(f"  {s['etiqueta']:<{W}}{fmt(s['accuracy_media'], 11)}"
                 f"{fmt(s['accuracy_std'], 10)}{fmt(s['f1_macro'], 11)}"
                 f"{fmt(s['auc_media'], 10)}{fmt(s['loss_media'], 10)}")
    L.append("")
    L.append("  CUIDADO con la columna 'F1 macro': en las corridas propias es la")
    L.append("  MEDIA DE LOS F1 MACRO POR PLIEGUE, mientras que en la linea base")
    L.append("  SI2 transcrita es el F1 macro de las predicciones AGRUPADAS de")
    L.append("  los 5 pliegues. Son estadisticos distintos y no se comparan")
    L.append("  entre si. Para comparar contra la linea base use la tabla de F1")
    L.append("  por clase, que en todas las corridas se calcula sobre las")
    L.append("  predicciones agrupadas.")
    L.append("")

    # --- Accuracy por pliegue ---
    L.append("-" * 100)
    L.append("ACCURACY POR PLIEGUE")
    L.append("-" * 100)
    # La cabecera de sujetos solo tiene sentido con agrupamiento por
    # sujeto: en el esquema por repeticion los 10 sujetos estan en todos
    # los pliegues y la fila no informaria nada.
    ref = next((s for s in resumenes
                if s["agrupamiento"] == "sujeto"
                and s["sujetos_test_por_fold"]
                and all(s["sujetos_test_por_fold"])), None)
    if ref:
        cab = "  " + " " * W
        for st in ref["sujetos_test_por_fold"]:
            cab += f"{'s' + '+'.join(map(str, st)):>11}"
        L.append(cab + "   (sujetos de test)")
    L.append(f"  {'Etiqueta':<{W}}" + "".join(f"{'P' + str(i+1):>11}"
                                              for i in range(5)))
    L.append(f"  {'-'*(W+55)}")
    for s in resumenes:
        fila = f"  {s['etiqueta']:<{W}}"
        for a in s["accuracy_por_fold"]:
            fila += f"{a:>11.4f}"
        L.append(fila)
    L.append("")

    # --- Epoca restaurada ---
    L.append("-" * 100)
    L.append("EPOCA RESTAURADA POR PLIEGUE  (la que devolvio restore_best_weights)")
    L.append("-" * 100)
    L.append(f"  {'Etiqueta':<{W}}" + "".join(f"{'P' + str(i+1):>11}"
                                              for i in range(5))
             + "   Pegados al umbral")
    L.append(f"  {'-'*(W+75)}")
    for s in resumenes:
        fila = f"  {s['etiqueta']:<{W}}"
        er = s["epoca_restaurada_por_fold"]
        if not er:
            fila += f"{'(no registrada)':>55}"
            pegados = "--"
        else:
            for e in er:
                fila += f"{e:>11}"
            pegados = (str(s["pegados_al_umbral"])
                       if s["pegados_al_umbral"] else "ninguno")
        L.append(fila + f"   {pegados}")
    L.append("")
    L.append("  Nota: 'pegados al umbral' = pliegues cuya epoca restaurada no")
    L.append("  supera early_stopping_start + 1, es decir cuyo val_loss no")
    L.append("  mejoro tras el calentamiento. Con es_start=0 no aplica.")
    L.append("")

    # --- F1 por clase ---
    L.append("-" * 100)
    L.append("F1 POR CLASE")
    L.append("-" * 100)
    L.append(f"  {'Etiqueta':<{W}}" + "".join(f"{c[:10]:>12}" for c in CLASES))
    L.append(f"  {'-'*(W+60)}")
    for s in resumenes:
        fila = f"  {s['etiqueta']:<{W}}"
        for c in CLASES:
            v = s["f1_por_clase"].get(c)
            fila += f"{v:>12.4f}" if v is not None else f"{'--':>12}"
        L.append(fila)
    L.append("")

    return "\n".join(L)


def veredicto_normalizacion(resumenes: list) -> str:
    """Responde la pregunta central del experimento."""
    por_et = {s["etiqueta"]: s for s in resumenes}
    base = por_et.get("sujeto + ninguna")
    L = []
    L.append("=" * 100)
    L.append("VEREDICTO: LA NORMALIZACION CORRIGE EL COLAPSO?")
    L.append("=" * 100)
    L.append("")

    if base is None:
        L.append("  Falta la corrida 'sujeto + ninguna'; no hay control.")
        return "\n".join(L)

    for et in ("sujeto + ninguna", "sujeto + global", "sujeto + sujeto",
               "sujeto + sujeto_rest"):
        s = por_et.get(et)
        if s is None:
            continue
        pegados = s["pegados_al_umbral"]
        delta = ((s["accuracy_media"] - base["accuracy_media"]) * 100
                 if s["accuracy_media"] and base["accuracy_media"] else None)
        L.append(f"  {et}")
        L.append(f"    Accuracy      : {s['accuracy_media']*100:.2f}% "
                 f"+/- {s['accuracy_std']*100:.2f}%"
                 + (f"   (delta vs ninguna: {delta:+.2f} pts)"
                    if delta is not None and et != "sujeto + ninguna" else ""))
        L.append(f"    Epocas restauradas: {s['epoca_restaurada_por_fold']}")
        if pegados:
            L.append(f"    Pliegues pegados al umbral: {pegados}  <-- el colapso")
            L.append(f"      persiste en esos pliegues, enmascarado por el umbral.")
        else:
            L.append(f"    Ningun pliegue pegado al umbral: todos mejoraron el")
            L.append(f"      val_loss despues del calentamiento.")
        L.append("")

    return "\n".join(L)


def main():
    parser = argparse.ArgumentParser(
        description="Compara los JSON de resultados de validacion cruzada"
    )
    parser.add_argument("--dir", type=str, default="resultados_cv",
                        help="Directorio con los metricas_*.json")
    parser.add_argument("--salida", type=str, default=None,
                        help="Archivo donde escribir la comparativa (opcional)")
    args = parser.parse_args()

    rutas = sorted(glob.glob(os.path.join(args.dir, "metricas_*.json")),
                   key=clave_orden)
    if not rutas:
        raise FileNotFoundError(f"No hay metricas_*.json en {args.dir}")

    resumenes = [resumir(r) for r in rutas]
    texto = construir_tabla(resumenes) + "\n" + veredicto_normalizacion(resumenes)

    print(texto)

    if args.salida:
        ruta = args.salida
        if not os.path.isabs(ruta):
            ruta = os.path.join(args.dir, ruta)
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(texto)
        print(f"\n[TEXTO] {ruta}")


if __name__ == "__main__":
    main()
