"""
Compara el experimento de normalizacion original (callbacks sobre el
pliegue de test) con el rehecho (validacion interna + reentreno, semilla 42).
Genera comparativa_corregida.txt en este directorio.
"""
import json
import os

import numpy as np
from scipy.stats import ttest_rel, wilcoxon

AQUI = os.path.dirname(os.path.abspath(__file__))
ORIG = os.path.dirname(AQUI)

CONFIGS = [
    ("ninguna",     "metricas_groupkfold_sujeto_norm-ninguna.json",     "metricas_sujeto_norm-ninguna.json"),
    ("global",      "metricas_groupkfold_sujeto_norm-global.json",      "metricas_sujeto_norm-global.json"),
    ("sujeto",      "metricas_groupkfold_sujeto_norm-sujeto.json",      "metricas_sujeto_norm-sujeto.json"),
    ("sujeto_rest", "metricas_groupkfold_sujeto_norm-sujeto_rest.json", "metricas_sujeto_norm-sujeto_rest.json"),
    ("repeticion",  "metricas_groupkfold_repeticion_es10.json",         "metricas_repeticion_norm-ninguna.json"),
]


def pliegues(ruta):
    r = json.load(open(ruta, encoding="utf-8"))
    return next(v for v in r.values()
                if isinstance(v, list) and v and isinstance(v[0], dict) and "accuracy" in v[0])


def serie(pl, clave="accuracy", seleccion=False):
    return np.array([(p["seleccion"] if seleccion else p)[clave] for p in pl]) * 100


datos = {}
for nombre, f_orig, f_nuevo in CONFIGS:
    po, pn = pliegues(os.path.join(ORIG, f_orig)), pliegues(os.path.join(AQUI, f_nuevo))
    datos[nombre] = dict(
        acc_o=serie(po), acc_n=serie(pn), f1_o=serie(po, "f1_macro"), f1_n=serie(pn, "f1_macro"),
        acc_sel=serie(pn, seleccion=True),
        sujetos=[p.get("sujetos_test") for p in pn],
        epocas=[p["epochs"] for p in pn],
        umbral=[p["seleccion"]["restaurada_en_el_umbral"] for p in pn],
    )

L = []
w = L.append
sd = lambda a: a.std(ddof=0)          # misma convencion que el capitulo  # noqa: E731

w("EXPERIMENTO DE NORMALIZACION: ORIGINAL FRENTE A CORREGIDO")
w("=" * 78)
w("Original : EarlyStopping y ReduceLROnPlateau vigilaban el pliegue de TEST; sin semilla.")
w("Corregido: validacion interna (1 grupo separado del train) para elegir epoca y")
w("           calendario de lr; reentreno con todo el train del pliegue; semilla 42.")
w("Desviaciones con ddof=0, la convencion del capitulo original.")
w("")
w("1. RESULTADOS POR CONFIGURACION (accuracy %, 5 pliegues)")
w(f"   {'config':<12}{'original':>16}{'corregido':>16}{'cambio':>8}{'F1 orig':>9}{'F1 corr':>9}"
  f"{'sel. 7':>8}{'reentr.':>9}")
for n, d in datos.items():
    w(f"   {n:<12}{d['acc_o'].mean():8.2f} +- {sd(d['acc_o']):5.2f}{d['acc_n'].mean():8.2f} +- "
      f"{sd(d['acc_n']):5.2f}{d['acc_n'].mean()-d['acc_o'].mean():+8.2f}{d['f1_o'].mean():9.2f}"
      f"{d['f1_n'].mean():9.2f}{d['acc_sel'].mean():8.2f}{d['acc_n'].mean()-d['acc_sel'].mean():+9.2f}")
w("   'sel. 7' = modelo de la fase de seleccion, entrenado sin el grupo de validacion.")
w("   'reentr.' = lo que aporta reentrenar con todo el train sobre ese modelo.")
w("")

w("2. POR PLIEGUE (corregido)")
w(f"   {'pliegue':<9}{'sujetos test':<14}" + "".join(f"{n:>12}" for n in datos if n != "repeticion"))
for i in range(5):
    w(f"   {i+1:<9}{str(datos['sujeto']['sujetos'][i]):<14}"
      + "".join(f"{datos[n]['acc_n'][i]:12.2f}" for n in datos if n != "repeticion"))
w(f"   epocas restauradas en la seleccion: " + ", ".join(f"{n} {datos[n]['epocas']}" for n in datos))
pegados = {n: sum(d["umbral"]) for n, d in datos.items()}
w(f"   pliegues con la epoca restaurada pegada al umbral: {pegados}")
w("")

w("3. CONTRASTES PAREADOS POR PLIEGUE (mismas particiones por sujeto en las 4 configuraciones)")
w("   Con 5 pliegues el Wilcoxon no puede bajar de p = 0.062: ninguna diferencia puede")
w("   declararse significativa a 0.05 con este diseno, ni en el original ni en el corregido.")
w(f"   {'contraste':<24}{'original':>12}{'corregido':>12}   por pliegue (corregido)          t p    Wilcoxon p")
for a, b in (("sujeto", "ninguna"), ("sujeto", "global"), ("global", "ninguna"),
             ("sujeto", "sujeto_rest"), ("sujeto_rest", "ninguna")):
    do = datos[a]["acc_o"] - datos[b]["acc_o"]
    dn = datos[a]["acc_n"] - datos[b]["acc_n"]
    tp = ttest_rel(datos[a]["acc_n"], datos[b]["acc_n"]).pvalue
    wp = wilcoxon(datos[a]["acc_n"], datos[b]["acc_n"]).pvalue
    w(f"   {a + ' - ' + b:<24}{do.mean():+12.2f}{dn.mean():+12.2f}   "
      f"[{', '.join(f'{x:+.1f}' for x in dn)}]  {tp:6.3f}  {wp:8.3f}")
w("")
r_o = sd(datos["sujeto_rest"]["acc_o"]) / sd(datos["sujeto"]["acc_o"])
r_n = sd(datos["sujeto_rest"]["acc_n"]) / sd(datos["sujeto"]["acc_n"])
w(f"   desviacion de sujeto_rest relativa a sujeto: original {r_o:.2f}, corregido {r_n:.2f}")
gap_o = datos["repeticion"]["acc_o"].mean() - datos["ninguna"]["acc_o"].mean()
gap_n = datos["repeticion"]["acc_n"].mean() - datos["ninguna"]["acc_n"].mean()
w(f"   brecha intra-sujeto (repeticion) frente a inter-sujeto (ninguna): original {gap_o:+.2f}, "
  f"corregido {gap_n:+.2f}")
w("")

w("4. LECTURA")
w("   - La correccion baja todas las cifras entre 0.7 y 3.9 puntos. Afecta mas a las")
w("     configuraciones con particion por sujeto que al control por repeticion.")
w("   - Sobrevive: normalizar por sujeto supera en ~12 puntos a no normalizar y a la")
w("     normalizacion global. La brecha intra frente a inter sujeto se mantiene en ~27 puntos.")
w("   - Se refuerza: la normalizacion global no aporta nada frente a no normalizar.")
w("   - Se debilita: sujeto_rest ya no iguala a sujeto en media y reduce su dispersion")
w("     entre pliegues en torno a un tercio, no a la mitad. Ninguna de las dos diferencias")
w("     es demostrable con 5 pliegues; hace falta comparar por sujeto (n = 10).")
w("   - El pliegue 4 (sujetos 5 y 10) explica la gran dispersion de global y ninguna: con")
w("     estadisticas ajenas esos sujetos caen a 36-43%, con las suyas recuperan 63-67%.")

texto = "\n".join(L)
print(texto)
with open(os.path.join(AQUI, "comparativa_corregida.txt"), "w", encoding="utf-8") as f:
    f.write(texto + "\n")
