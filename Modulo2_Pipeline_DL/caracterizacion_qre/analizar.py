"""
analizar.py - Caracterizacion preliminar de los modulos QRE1113
================================================================
Protesis transradial - OMG (QRE1113) + IMU

PRUEBA PRELIMINAR CON LA PLACA, NO FORMA PARTE DEL CONJUNTO DE DATOS.

Entradas:
  --csv     uno o varios CSV de capturar.py (con su JSON al lado)
  --log_c   texto del monitor serie tras el comando C (asentamiento)
  --log_t   texto tras el comando T (autotest)
  --log_x   texto tras el comando X (diafonia)
  Los tres registros son opcionales: lo que falta sale como "sin dato".

Por modulo (v = V_apag - V_enc, en mV, mayor con mas luz):
  V_enc y V_apag   medias en reposo. V_enc = amb - v.
  sigma            desviacion de v en reposo (ruido).
  DeltaS           por gesto: |media de v en la meseta, sin su primer
                   segundo - media de v en el reposo previo, sin su primer
                   segundo|, promediado sobre las repeticiones.
  DeltaS/sigma     por gesto, y el minimo de los cuatro.
  CV               coeficiente de variacion de DeltaS entre repeticiones.
  movimiento       desviacion de v durante el recorrido con la mano
                   relajada, y su razon frente al DeltaS minimo: cerca de
                   1 o mas, el movimiento del brazo se confunde con un gesto.
  luz              luz encendida menos apagada, sobre V_apag y sobre v.
  satura           V_enc por debajo de 250 mV en algun gesto, o bandera
                   SATURADO en el autotest.
  t95, t99         del registro de C (el peor de encender y apagar).
  diafonia         del registro de X, en % de la senal propia.

Si hay varios CSV, cada metrica se promedia por modulo entre archivos.

Salidas en --salida: tabla_6_1.csv y .md, figura_6_1.png (DeltaS/sigma,
modulos x gestos), figura_6_2.png (las 8 senales con los gestos
sombreados), figura_6_3.png (movimiento relajado frente a gesto),
metricas_modulos.csv (todas las metricas) y resumen.md.

USO:
  python analizar.py --csv capturas/P01_sin_carcasa_*.csv --log_c c.txt --log_t t.txt --log_x x.txt
"""

import argparse
import glob
import json
import os
import re
import sys

import numpy as np
import pandas as pd

_M2 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_M2, "common"))
from canales import CANALES_AMB, CANALES_OPT, NUM_OPT     # noqa: E402

GESTOS = ["Pinch", "Tripod", "Power", "Finger_Ext"]
NOMBRE_GESTO = {"Pinch": "pinza", "Tripod": "tripode", "Power": "puno",
                "Finger_Ext": "extension"}
ETIQUETA_GESTO = {"Pinch": "pinza", "Tripod": "trípode", "Power": "puño",
                  "Finger_Ext": "extensión"}
PERIODO_MS = 10
RECORTE_S = 1.0                 # primer segundo de cada tramo, fuera
UMBRAL_SATURADO_MV = 250.0      # el mismo que el autotest del firmware


# ============================================================
# TRAMOS
# ============================================================
def tramos(df):
    """Indice de tramo: cada bloque contiguo de la misma fase y gesto."""
    clave = df["fase"].astype(str) + "|" + df["gesto"].fillna("").astype(str)
    return (clave != clave.shift()).cumsum()


def recortar(g):
    n = int(RECORTE_S * 1000 / PERIODO_MS)
    return g.iloc[n:] if len(g) > n else g.iloc[0:0]


def deltas_por_gesto(df):
    """
    {gesto: array (repeticiones, NUM_OPT)} con v de la meseta menos v del
    reposo previo, los dos sin su primer segundo. Con signo: el valor
    absoluto se toma despues, para el CV y la media.
    """
    seg = tramos(df)
    grupos = [(f, g) for f, g in df.groupby(seg, sort=True)]
    salida = {g: [] for g in GESTOS}
    for i in range(1, len(grupos)):
        _, actual = grupos[i]
        _, previo = grupos[i - 1]
        if (actual["fase"].iloc[0] != "gesto"
                or previo["fase"].iloc[0] != "reposo"):
            continue
        a, p = recortar(actual), recortar(previo)
        if len(a) == 0 or len(p) == 0:
            continue
        salida[actual["gesto"].iloc[0]].append(
            a[CANALES_OPT].mean().to_numpy() - p[CANALES_OPT].mean().to_numpy())
    return {g: np.array(v) for g, v in salida.items() if v}


def reposo_recortado(df):
    seg = tramos(df)
    trozos = [recortar(g) for _, g in df.groupby(seg, sort=True)
              if g["fase"].iloc[0] == "reposo"]
    return pd.concat(trozos) if trozos else df.iloc[0:0]


# ============================================================
# METRICAS DE UN ARCHIVO
# ============================================================
def metricas_archivo(df):
    """DataFrame con una fila por modulo (1..8)."""
    rep = reposo_recortado(df)
    v_rep = rep[CANALES_OPT].to_numpy(float)
    amb_rep = rep[CANALES_AMB].to_numpy(float)
    sigma = v_rep.std(axis=0, ddof=1) if len(v_rep) > 1 else np.full(NUM_OPT, np.nan)
    d = deltas_por_gesto(df)

    filas = []
    for k in range(NUM_OPT):
        f = {"modulo": k + 1,
             "V_apag_reposo_mV": amb_rep[:, k].mean() if len(amb_rep) else np.nan,
             "V_enc_reposo_mV": (amb_rep[:, k] - v_rep[:, k]).mean() if len(v_rep) else np.nan,
             "sigma_mV": sigma[k]}
        for g in GESTOS:
            nombre = NOMBRE_GESTO[g]
            if g in d:
                ds = np.abs(d[g][:, k])
                f[f"DeltaS_{nombre}_mV"] = ds.mean()
                f[f"CV_{nombre}"] = (ds.std(ddof=1) / ds.mean()
                                     if len(ds) > 1 and ds.mean() > 0 else np.nan)
            else:
                f[f"DeltaS_{nombre}_mV"] = np.nan
                f[f"CV_{nombre}"] = np.nan
            f[f"DeltaS_sigma_{nombre}"] = f[f"DeltaS_{nombre}_mV"] / sigma[k]
        ds_min = np.nanmin([f[f"DeltaS_{NOMBRE_GESTO[g]}_mV"] for g in GESTOS])
        f["DeltaS_sigma_min"] = np.nanmin([f[f"DeltaS_sigma_{NOMBRE_GESTO[g]}"]
                                           for g in GESTOS])
        mov = df[df["fase"] == "movimiento"][CANALES_OPT[k]].to_numpy(float)
        f["sd_movimiento_mV"] = mov.std(ddof=1) if len(mov) > 1 else np.nan
        f["movimiento_sobre_DeltaS_min"] = f["sd_movimiento_mV"] / ds_min
        enc = df[df["fase"] == "luz_encendida"]
        apa = df[df["fase"] == "luz_apagada"]
        f["luz_sobre_V_apag_mV"] = (enc[CANALES_AMB[k]].mean()
                                    - apa[CANALES_AMB[k]].mean())
        f["luz_sobre_v_mV"] = enc[CANALES_OPT[k]].mean() - apa[CANALES_OPT[k]].mean()
        ges = df[df["fase"] == "gesto"]
        v_enc_ges = ges[CANALES_AMB[k]] - ges[CANALES_OPT[k]]
        f["V_enc_min_gesto_mV"] = v_enc_ges.min() if len(ges) else np.nan
        filas.append(f)
    return pd.DataFrame(filas)


# ============================================================
# REGISTROS DE TEXTO DE LOS COMANDOS C, T Y X
# ============================================================
RE_C = re.compile(r"\[ASENTAMIENTO\] modulo (\d+) (encender|apagar): .*?"
                  r"t95=([\d.]+) us t99=([\d.]+) us")
RE_X = re.compile(r"\[DIAFONIA\] modulo (\d+): .*?diafonia=(-?[\d.]+) mV "
                  r"\((-?[\d.nan]+)%")
RE_T = re.compile(r"\[AUTOTEST\] modulo (\d+): .*?mV ?(.*)$")


def leer_log(ruta):
    if not ruta:
        return []
    with open(ruta, encoding="utf-8", errors="ignore") as f:
        return f.read().splitlines()


def asentamiento(lineas):
    """{modulo: (t95, t99)} con el peor de encender y apagar."""
    r = {}
    for l in lineas:
        m = RE_C.search(l)
        if m:
            k = int(m.group(1))
            t95, t99 = float(m.group(3)), float(m.group(4))
            a, b = r.get(k, (0.0, 0.0))
            r[k] = (max(a, t95), max(b, t99))
    return r


def diafonia(lineas):
    """{modulo: % de su senal}."""
    r = {}
    for l in lineas:
        m = RE_X.search(l)
        if m:
            try:
                r[int(m.group(1))] = float(m.group(3))
            except ValueError:
                r[int(m.group(1))] = np.nan
    return r


def banderas(lineas):
    """{modulo: texto de banderas del autotest}."""
    r = {}
    for l in lineas:
        m = RE_T.search(l)
        if m:
            r[int(m.group(1))] = m.group(2).strip()
    return r


# ============================================================
# TABLA, FIGURAS Y RESUMEN
# ============================================================
def combinar(metricas, log_c, log_t, log_x):
    tabla = pd.concat(metricas).groupby("modulo", as_index=False).mean(numeric_only=True)
    c, x, t = asentamiento(log_c), diafonia(log_x), banderas(log_t)
    tabla["t95_us"] = tabla["modulo"].map(lambda k: c.get(k, (np.nan,) * 2)[0])
    tabla["t99_us"] = tabla["modulo"].map(lambda k: c.get(k, (np.nan,) * 2)[1])
    tabla["diafonia_pct"] = tabla["modulo"].map(lambda k: x.get(k, np.nan))
    tabla["banderas_T"] = tabla["modulo"].map(lambda k: t.get(k, "sin dato"))
    tabla["satura"] = ((tabla["V_enc_min_gesto_mV"] < UMBRAL_SATURADO_MV)
                       | tabla["banderas_T"].str.contains("SATURADO"))
    return tabla


COLUMNAS_6_1 = (["modulo", "V_enc_reposo_mV", "V_apag_reposo_mV", "sigma_mV"]
                + [f"DeltaS_{NOMBRE_GESTO[g]}_mV" for g in GESTOS]
                + ["DeltaS_sigma_min", "satura"])


def tabla_markdown(t):
    cab = ["Módulo", "V_enc reposo (mV)", "V_apag reposo (mV)", "σ (mV)",
           "ΔS pinza", "ΔS trípode", "ΔS puño", "ΔS extensión",
           "ΔS/σ mínimo", "Satura"]
    lineas = ["| " + " | ".join(cab) + " |", "|" + "---|" * len(cab)]
    for _, r in t[COLUMNAS_6_1].iterrows():
        celdas = [str(int(r["modulo"]))]
        for c in COLUMNAS_6_1[1:-1]:
            celdas.append("sin dato" if pd.isna(r[c]) else f"{r[c]:.1f}")
        celdas.append("sí" if r["satura"] else "no")
        lineas.append("| " + " | ".join(celdas) + " |")
    return "\n".join(lineas) + "\n"


def figuras(tabla, df_ejemplo, salida):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # 6.1: DeltaS/sigma, modulos x gestos.
    m = tabla[[f"DeltaS_sigma_{NOMBRE_GESTO[g]}" for g in GESTOS]].to_numpy(float)
    fig, ax = plt.subplots(figsize=(6.5, 5))
    im = ax.imshow(m, cmap="viridis", aspect="auto")
    ax.set_xticks(range(len(GESTOS)), [ETIQUETA_GESTO[g] for g in GESTOS])
    ax.set_yticks(range(len(tabla)), [f"módulo {int(k)}" for k in tabla["modulo"]])
    for i in range(m.shape[0]):
        for j in range(m.shape[1]):
            if np.isfinite(m[i, j]):
                ax.text(j, i, f"{m[i, j]:.0f}", ha="center", va="center",
                        color="white" if m[i, j] < np.nanmax(m) / 2 else "black")
    fig.colorbar(im, label="ΔS / σ")
    ax.set_title("ΔS / σ por módulo y gesto")
    fig.tight_layout()
    fig.savefig(os.path.join(salida, "figura_6_1.png"), dpi=150)
    plt.close(fig)

    # 6.2: las 8 senales con los gestos sombreados.
    t = (df_ejemplo["timestamp_ms"] - df_ejemplo["timestamp_ms"].iloc[0]) / 1000.0
    fig, axes = plt.subplots(NUM_OPT, 1, figsize=(12, 1.4 * NUM_OPT), sharex=True)
    gesto = (df_ejemplo["fase"] == "gesto").to_numpy()
    for k, ax in enumerate(axes):
        ax.plot(t, df_ejemplo[CANALES_OPT[k]], lw=0.6)
        ax.fill_between(t, 0, 1, where=gesto, transform=ax.get_xaxis_transform(),
                        alpha=0.15, color="tab:green")
        ax.set_ylabel(f"v{k + 1}\n(mV)", rotation=0, labelpad=22, fontsize=8)
    axes[-1].set_xlabel("tiempo (s)")
    axes[0].set_title("Señales v de los 8 módulos, gestos sombreados")
    fig.tight_layout()
    fig.savefig(os.path.join(salida, "figura_6_2.png"), dpi=150)
    plt.close(fig)

    # 6.3: movimiento relajado frente a gesto, por modulo.
    fig, ax = plt.subplots(figsize=(8, 4.5))
    x = np.arange(len(tabla))
    ax.bar(x - 0.2, tabla["sd_movimiento_mV"], 0.4, label="σ de v, brazo en movimiento relajado")
    ax.bar(x + 0.2, tabla[[f"DeltaS_{NOMBRE_GESTO[g]}_mV" for g in GESTOS]].min(axis=1),
           0.4, label="ΔS mínimo de los gestos")
    ax.set_xticks(x, [f"{int(k)}" for k in tabla["modulo"]])
    ax.set_xlabel("módulo")
    ax.set_ylabel("mV")
    ax.set_title("Movimiento del brazo sin gesto frente al gesto más débil")
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(salida, "figura_6_3.png"), dpi=150)
    plt.close(fig)


def resumen(tabla, metas, salida):
    participantes = sorted({m.get("participante", "sin dato") for m in metas})
    carcasas = sorted({m.get("carcasa", "carcasa sin dato") for m in metas})

    def rango(c, fmt="{:.1f}"):
        s = tabla[c].dropna()
        return ("sin dato" if s.empty else
                f"{fmt.format(s.min())} a {fmt.format(s.max())}")

    peor = tabla.loc[tabla["DeltaS_sigma_min"].idxmin()] if tabla["DeltaS_sigma_min"].notna().any() else None
    lineas = [
        "# Caracterización preliminar de los módulos QRE1113",
        "",
        f"> **Placa {', '.join(carcasas).replace('_', ' ')}, n = {len(participantes)} "
        f"participante(s), no forma parte del conjunto de datos.**",
        "",
        f"- Archivos: {len(metas)}. Participantes: {', '.join(participantes)}.",
        f"- V_enc en reposo: {rango('V_enc_reposo_mV')} mV. V_apag en reposo: "
        f"{rango('V_apag_reposo_mV')} mV.",
        f"- Ruido σ de v en reposo: {rango('sigma_mV', '{:.2f}')} mV.",
        f"- ΔS/σ mínimo por módulo: {rango('DeltaS_sigma_min')}."
        + (f" El peor es el módulo {int(peor['modulo'])}." if peor is not None else ""),
        f"- Coeficiente de variación de ΔS entre repeticiones (pinza): {rango('CV_pinza', '{:.2f}')}.",
        f"- Movimiento relajado / ΔS mínimo: {rango('movimiento_sobre_DeltaS_min', '{:.2f}')}.",
        f"- Luz de la sala sobre V_apag: {rango('luz_sobre_V_apag_mV')} mV, y sobre v: "
        f"{rango('luz_sobre_v_mV')} mV.",
        f"- Asentamiento: t95 {rango('t95_us', '{:.0f}')} µs, t99 {rango('t99_us', '{:.0f}')} µs.",
        f"- Diafonía: {rango('diafonia_pct')} % de la señal propia.",
        f"- Módulos que saturan: {', '.join(str(int(k)) for k in tabla.loc[tabla['satura'], 'modulo']) or 'ninguno'}.",
        "",
        "## Tabla 6.1",
        "",
        tabla_markdown(tabla),
    ]
    with open(os.path.join(salida, "resumen.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lineas))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", nargs="+", required=True)
    ap.add_argument("--log_c")
    ap.add_argument("--log_t")
    ap.add_argument("--log_x")
    ap.add_argument("--salida", default=os.path.join(os.path.dirname(
        os.path.abspath(__file__)), "resultados"))
    args = ap.parse_args(argv)

    rutas = sorted({r for p in args.csv for r in glob.glob(p)})
    if not rutas:
        print("No hay CSV.")
        return 1
    metricas, metas, dfs = [], [], []
    for r in rutas:
        df = pd.read_csv(r)
        dfs.append(df)
        metricas.append(metricas_archivo(df))
        j = os.path.splitext(r)[0] + ".json"
        metas.append(json.load(open(j, encoding="utf-8")) if os.path.exists(j) else {})

    tabla = combinar(metricas, leer_log(args.log_c), leer_log(args.log_t),
                     leer_log(args.log_x))
    os.makedirs(args.salida, exist_ok=True)
    tabla.to_csv(os.path.join(args.salida, "metricas_modulos.csv"), index=False)
    tabla[COLUMNAS_6_1].to_csv(os.path.join(args.salida, "tabla_6_1.csv"), index=False)
    with open(os.path.join(args.salida, "tabla_6_1.md"), "w", encoding="utf-8") as f:
        f.write(tabla_markdown(tabla))
    figuras(tabla, dfs[0], args.salida)
    resumen(tabla, metas, args.salida)
    print(tabla_markdown(tabla))
    print(f"[SALIDA] {args.salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
