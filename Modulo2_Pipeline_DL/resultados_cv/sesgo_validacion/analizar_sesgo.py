import glob, json, os
import numpy as np
from scipy.stats import ttest_rel, wilcoxon

D = "/mnt/c/Users/danie/OneDrive/Documents/GitHub/Tesis-Control-de-pr-tesis-radial-con-fusi-n-sensorial/.claude/worktrees/groupkfold-subject-validation-9509f7/Modulo2_Pipeline_DL/resultados_cv"


def cargar(ruta):
    r = json.load(open(ruta, encoding="utf-8"))
    pl = r.get("metricas_por_pliegue") or r.get("pliegues") or r.get("metricas_por_fold")
    if pl is None:
        for v in r.values():
            if isinstance(v, list) and v and isinstance(v[0], dict) and "accuracy" in v[0]:
                pl = v
                break
    acc = np.array([p["accuracy"] for p in pl]) * 100
    f1 = np.array([p["f1_macro"] for p in pl]) * 100
    ep = [p.get("epoca_restaurada") for p in pl]
    return acc, f1, ep


runs = {}
for modo in ("interna", "reducido_test", "test"):
    f = sorted(glob.glob(os.path.join(D, "sesgo_validacion", f"metricas_sujeto_seed42_val-{modo}*.json")))
    runs[modo] = cargar(f[-1])
orig = cargar(os.path.join(D, "metricas_groupkfold_sujeto_norm-sujeto.json"))

print("accuracy por pliegue (%)")
for m, (a, f1, ep) in list(runs.items()) + [("original_sin_semilla", orig)]:
    print(f"  {m:<22} " + "  ".join(f"{v:6.2f}" for v in a)
          + f"   media {a.mean():6.2f} +/- {a.std(ddof=1):5.2f}   F1 {f1.mean():6.2f}   epocas {ep}")


def contraste(nombre, a, b):
    d = a - b
    t = ttest_rel(a, b)
    try:
        w = wilcoxon(a, b).pvalue
    except ValueError:
        w = float("nan")
    print(f"  {nombre:<44} media {d.mean():+5.2f}  sd {d.std(ddof=1):4.2f}  "
          f"por pliegue [{', '.join(f'{v:+.1f}' for v in d)}]  "
          f"t p={t.pvalue:.3f}  Wilcoxon p={w:.3f} (minimo 0.062)")


I, R, T = runs["interna"][0], runs["reducido_test"][0], runs["test"][0]
print()
print("descomposicion (accuracy, puntos)")
contraste("fuga         = reducido_test - interna", R, I)
contraste("menos datos  = test - reducido_test", T, R)
contraste("total        = test - interna", T, I)
contraste("reproducir   = test(seed42) - original", T, orig[0])
