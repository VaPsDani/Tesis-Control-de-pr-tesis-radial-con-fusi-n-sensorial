"""
indice_rendimiento.py - Tarea 2: LED verde con espaciador vs IR sin espaciador
===============================================================================
Experimento de hardware propio pedido por el asesor. El hardware aun no
esta armado; el analisis queda listo para correr sobre los CSV de captura.

ENTRADA:
  Uno o varios CSV con el formato del Modulo 1 (captura_sesion.py) mas una
  columna 'condicion' con la configuracion optica (p. ej. 'verde_espaciador'
  e 'ir_sin_espaciador'). Si el CSV trae la columna 'fase' (Tarea 4), se
  usan solo las fases estables; si no, las etiquetas.

DOS MODOS, porque miden cosas distintas:

  --modo indice
    Indice de rendimiento, que compara configuraciones opticas con
    independencia del hardware:

        I = dS / (L * R)

        dS  = | media de la senal en el gesto - media en el reposo |   [V]
        L   = intensidad radiante del LED                          [mW/sr]
        R   = responsividad del fotodiodo a la longitud de onda del
              LED                                                  [A/W]

    Normalizar por L y por R separa la calidad del ACOPLAMIENTO OPTICO
    (espaciador, geometria, tejido) de cuanta luz emite el LED y de cuan
    sensible es el fotodiodo a ese color.

  --modo clasificacion
    Exactitud de clasificacion por condicion, con el mismo clasificador y
    el mismo particionado. La literatura muestra que un mejor indice no
    siempre implica mejor clasificacion: un cambio de amplitud grande pero
    igual para todos los gestos sube I y no ayuda a separarlos.

  --modo ambos   (por defecto)

UNIDADES — ATENCION:
  La luminosidad de los LED verdes suele darse en milicandelas (mcd), que
  es una unidad FOTOMETRICA: pondera por la sensibilidad del ojo humano,
  que a 940 nm es practicamente cero. Un LED IR tiene ~0 mcd aunque emita
  mucha potencia. Comparar un verde en mcd con un IR en mW/sr hace que I
  sea arbitrario. Este script EXIGE unidades radiometricas (mW/sr) para
  todas las condiciones.

  La responsividad del OPT101 depende de la longitud de onda: su maximo
  esta hacia 750-850 nm y cae hacia el verde. Hay que tomar R de la curva
  del datasheet A LA LONGITUD DE ONDA DE CADA LED, no el valor tipico de
  la portada (0.45 A/W a 650 nm).

VALIDACION CRUZADA:
  Agrupa por SUJETO. Con un unico sujeto eso es imposible: el script se
  niega por defecto y solo acepta agrupar por repeticion con
  --permitir_intra_sujeto, marcando el resultado como intra-sujeto.

USO:
  python indice_rendimiento.py --csv sesiones/*.csv --parametros opticas.json

  opticas.json:
  {
    "verde_espaciador":  {"intensidad_mW_sr": 12.0, "responsividad_A_W": 0.30,
                          "longitud_onda_nm": 525},
    "ir_sin_espaciador": {"intensidad_mW_sr": 20.0, "responsividad_A_W": 0.38,
                          "longitud_onda_nm": 940}
  }
"""

import argparse
import glob
import json
import os
import sys

import numpy as np
import pandas as pd

AQUI = os.path.dirname(os.path.abspath(__file__))
MODULO2 = os.path.abspath(os.path.join(AQUI, "..", ".."))
sys.path.insert(0, MODULO2)

CANALES = ["v1", "v2", "v3", "v4", "v5"]
UNIDADES_PROHIBIDAS = ("mcd", "cd", "lm", "lux", "lx")


def cargar(rutas):
    dfs = [pd.read_csv(r) for r in rutas]
    df = pd.concat(dfs, ignore_index=True)
    if "condicion" not in df.columns:
        raise SystemExit("Falta la columna 'condicion' en el CSV.")
    faltan = [c for c in CANALES + ["label", "subject_id"] if c not in df.columns]
    if faltan:
        raise SystemExit(f"Faltan columnas del formato del Modulo 1: {faltan}")
    return df


def cargar_parametros(ruta, condiciones):
    with open(ruta, encoding="utf-8") as f:
        par = json.load(f)
    for cond, d in par.items():
        for clave in d:
            if any(u in clave.lower() for u in UNIDADES_PROHIBIDAS):
                raise SystemExit(
                    f"'{cond}' usa una unidad fotometrica ({clave}). La "
                    f"candela pondera por la vision humana y un LED IR tiene "
                    f"~0 mcd. Use intensidad radiante en mW/sr.")
        if "intensidad_mW_sr" not in d or "responsividad_A_W" not in d:
            raise SystemExit(f"'{cond}' necesita intensidad_mW_sr y "
                             f"responsividad_A_W.")
    faltan = sorted(set(condiciones) - set(par))
    if faltan:
        raise SystemExit(f"Sin parametros opticos para: {faltan}")
    return par


def mascaras(df):
    """Reposo y gesto ESTABLES. Usa 'fase' si existe; si no, etiquetas."""
    base = np.ones(len(df), dtype=bool)
    if "es_calibracion" in df.columns:
        base &= df.es_calibracion.values == 0
    if "fase" in df.columns:
        reposo = base & (df.fase.values == "reposo")
        gesto = base & (df.fase.values == "meseta")
        origen = "columna fase (reposo estable vs meseta)"
    else:
        if "en_margen" in df.columns:
            base &= df.en_margen.values == 0
        reposo = base & (df.label.values == 0)
        gesto = base & (df.label.values > 0)
        origen = "etiquetas y en_margen (sin columna fase)"
    return reposo, gesto, origen


def modo_indice(df, par):
    reposo, gesto, origen = mascaras(df)
    print(f"Tramos estables desde: {origen}")
    filas = []
    for (cond, sid), g in df.groupby(["condicion", "subject_id"]):
        idx = g.index.values
        r_mask, g_mask = reposo[idx], gesto[idx]
        L = par[cond]["intensidad_mW_sr"]
        R = par[cond]["responsividad_A_W"]
        for c in CANALES:
            v = g[c].values / 1000.0          # el Modulo 1 entrega mV
            s_r = v[r_mask].mean()            # S-barra-r: media de reposo
            for gest in sorted(g.label[g_mask].unique()):
                m = g_mask & (g.label.values == gest)
                dS = abs(v[m].mean() - s_r)
                filas.append(dict(condicion=cond, subject_id=sid, canal=c,
                                  gesto=int(gest), S_reposo_V=s_r, dS_V=dS,
                                  indice_I=dS / (L * R)))
    t = pd.DataFrame(filas)
    resumen = t.groupby("condicion").indice_I.agg(["mean", "std", "count"])
    print("\nIndice I por condicion (media sobre sujetos, canales y gestos):")
    print(resumen.to_string())

    conds = sorted(t.condicion.unique())
    n_suj = t.subject_id.nunique()
    if len(conds) == 2 and n_suj >= 2:
        from scipy.stats import wilcoxon
        por_suj = t.groupby(["subject_id", "condicion"]).indice_I.mean() \
            .unstack()
        w = wilcoxon(por_suj[conds[0]], por_suj[conds[1]])
        print(f"\nWilcoxon pareado por sujeto ({conds[0]} vs {conds[1]}): "
              f"p = {w.pvalue:.4f}")
        # Con n sujetos, el menor p bilateral que puede dar Wilcoxon es
        # 2 / 2^n. Con n <= 5 nunca baja de 0.0625: ningun resultado
        # puede ser significativo al 5%, pase lo que pase con los datos.
        p_min = 2.0 / 2 ** n_suj
        if p_min >= 0.05:
            print(f"  AVISO: con {n_suj} sujetos el menor p alcanzable es "
                  f"{p_min:.4f}. El test no puede dar significancia al 5%; "
                  f"hacen falta al menos 6 sujetos. Reporte el tamano del "
                  f"efecto, no el p.")
    return t


def modo_clasificacion(df, args):
    from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
    from sklearn.metrics import accuracy_score, f1_score
    from sklearn.model_selection import GroupKFold

    reposo, gesto, _ = mascaras(df)
    usar = reposo | gesto
    n_suj = df.subject_id.nunique()
    if n_suj >= 2:
        grupo_col, rotulo = "subject_id", "INTER-sujeto (por sujeto)"
    elif args.permitir_intra_sujeto:
        grupo_col, rotulo = "repetition_id", "INTRA-sujeto (por repeticion)"
        print("AVISO: un solo sujeto. Se agrupa por repeticion; el resultado "
              "mide separabilidad dentro de la persona, no generalizacion.")
    else:
        raise SystemExit(
            "Un solo sujeto: la validacion por sujeto es imposible. Anada "
            "sujetos o use --permitir_intra_sujeto, que agrupa por "
            "repeticion y rotula el resultado como intra-sujeto.")

    w = int(round(args.ventana_ms * 100 / 1000.0))
    paso = max(1, int(round(args.stride_ms * 100 / 1000.0)))
    filas = []
    for cond, g in df[usar].groupby("condicion"):
        F, y, grupos = [], [], []
        # ventanas dentro de tramos contiguos de la misma clase y grupo
        clave = (g.label.astype(str) + "|" + g[grupo_col].astype(str)).values
        cortes = np.flatnonzero(clave[1:] != clave[:-1]) + 1
        vals = g[CANALES].values
        for a, z in zip(np.r_[0, cortes], np.r_[cortes, len(g)]):
            if z - a < w:
                continue
            vista = np.lib.stride_tricks.sliding_window_view(
                vals[a:z], w, axis=0)[::paso]
            F.append(np.concatenate([vista.mean(-1), vista.std(-1)], axis=1))
            y.append(np.full(len(vista), g.label.values[a]))
            grupos.append(np.full(len(vista), g[grupo_col].values[a]))
        F, y, grupos = np.concatenate(F), np.concatenate(y), np.concatenate(grupos)
        k = min(5, len(np.unique(grupos)))
        accs, f1s = [], []
        for tr, te in GroupKFold(n_splits=k).split(F, y, grupos):
            m = LinearDiscriminantAnalysis(solver="lsqr", shrinkage="auto")
            p = m.fit(F[tr], y[tr]).predict(F[te])
            accs.append(accuracy_score(y[te], p))
            f1s.append(f1_score(y[te], p, average="macro", zero_division=0))
        filas.append(dict(condicion=cond, validacion=rotulo, pliegues=k,
                          n_ventanas=len(y), acc_media=np.mean(accs),
                          acc_std=np.std(accs), f1_media=np.mean(f1s),
                          f1_std=np.std(f1s)))
    t = pd.DataFrame(filas)
    print("\nExactitud de clasificacion por condicion (LDA):")
    print(t.to_string(index=False))
    return t


def main():
    p = argparse.ArgumentParser(description="Indice de rendimiento optico")
    p.add_argument("--csv", nargs="+", required=True)
    p.add_argument("--parametros", required=False,
                   help="JSON con intensidad_mW_sr y responsividad_A_W "
                        "por condicion (obligatorio en modo indice)")
    p.add_argument("--modo", choices=["indice", "clasificacion", "ambos"],
                   default="ambos")
    p.add_argument("--ventana_ms", type=float, default=200)
    p.add_argument("--stride_ms", type=float, default=20)
    p.add_argument("--permitir_intra_sujeto", action="store_true")
    p.add_argument("--output", default=os.path.join(AQUI, "resultados"))
    args = p.parse_args()
    os.makedirs(args.output, exist_ok=True)

    rutas = sorted({r for patron in args.csv for r in glob.glob(patron)})
    df = cargar(rutas)
    print(f"{len(rutas)} CSV, condiciones: {sorted(df.condicion.unique())}, "
          f"sujetos: {sorted(df.subject_id.unique().tolist())}")

    if args.modo in ("indice", "ambos"):
        if not args.parametros:
            raise SystemExit("El modo indice necesita --parametros.")
        par = cargar_parametros(args.parametros, df.condicion.unique())
        modo_indice(df, par).to_csv(
            os.path.join(args.output, "indice_rendimiento.csv"), index=False)
    if args.modo in ("clasificacion", "ambos"):
        modo_clasificacion(df, args).to_csv(
            os.path.join(args.output, "clasificacion_por_condicion.csv"),
            index=False)


if __name__ == "__main__":
    main()
