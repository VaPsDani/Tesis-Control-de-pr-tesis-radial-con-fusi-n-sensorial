#!/bin/bash
# tanda_a_b.sh - Tarea A (exactitud por sujeto) y Tarea B (CNN sin fuga)
#
# Cola de trabajos con P trabajadores sobre la misma GPU. Cada trabajador:
#   - toma el trabajo de menor prioridad disponible (mv atomico),
#   - espera a que haya RAM libre y a que pasen ESPERA_ENTRE_ARRANQUES
#     segundos desde el ultimo arranque, para no arrancar todos a la vez
#     y ver RAM libre que un momento despues ya no lo esta,
#   - termina cuando la cola y los trabajos en curso estan vacios.
#
# Al terminar los dos trabajos de A se corre analisis_por_sujeto.py. Si el
# intervalo bootstrap del cociente de desviaciones incluye 1.0 con extremo
# superior < 1.15, se ENCOLAN el deja-un-sujeto-fuera de sujeto y sujeto_rest
# por delante del resto de B, sin intervencion (regla acordada).
#
# Relanzable: lo que ya esta en hecho/ no se repite; lo que quedo en
# corriendo/ por una interrupcion vuelve a la cola.
#
# Uso:  bash ~/tanda/tanda_a_b.sh 4
set -u
source "$HOME/env-tesis.sh"
export TF_FORCE_GPU_ALLOW_GROWTH=true

M2=/mnt/c/Users/danie/OneDrive/Documents/GitHub/Tesis-Control-de-pr-tesis-radial-con-fusi-n-sensorial/.claude/worktrees/groupkfold-subject-validation-9509f7/Modulo2_Pipeline_DL
L=$M2/experimentos/lmg_wavelength
PY="$HOME/venv-tesis/bin/python"
T="$HOME/tanda"
YO="$T/tanda_a_b.sh"
COLA=$T/cola; CORR=$T/corriendo; HECHO=$T/hecho; LOGS=$T/logs; MARCAS=$T/marcas
UMBRAL_RAM_MB=${UMBRAL_RAM_MB:-3000}
ESPERA_ENTRE_ARRANQUES=${ESPERA_ENTRE_ARRANQUES:-120}
OUT_A=$M2/resultados_cv/por_sujeto
OUT_LOSO=$M2/resultados_cv/por_sujeto_loso
REF=$M2/resultados_cv/rehecho_val_interna
D="--data $HOME/data/lmg_wavelength_dataset --cache $HOME/cache_lmg"
# Identico a la corrida cc872da (rehacer_capitulo.sh) salvo agrupamiento y folds.
ECV="--mat $HOME/data/NinaPro_DB5 --agrupamiento sujeto --validacion interna --reentrenar --early_stopping_start 10 --epochs 100 --batch_size 32 --lr 1e-3 --seed 42 --cache $HOME/cache_ninapro.npz"
mkdir -p "$COLA" "$CORR" "$HECHO" "$LOGS" "$MARCAS" "$OUT_A" "$OUT_LOSO"

log() { echo "### $* $(date +%H:%M:%S)" >> "$T/tanda.log"; }

encolar() {           # prioridad nombre comando...
  local prio=$1 nombre=$2; shift 2
  local f="${prio}_${nombre}.job"
  [ -e "$HECHO/$f" ] || [ -e "$CORR/$f" ] || [ -e "$COLA/$f" ] && return 0
  printf '%s\n' "set -o pipefail" "cd $M2" "$*" > "$COLA/$f"
}

# ------------------------------------------------------------------ ganchos
if [ "${1:-}" = "--gancho-A" ]; then
  touch "$MARCAS/A_$2"
  if [ -e "$MARCAS/A_sujeto" ] && [ -e "$MARCAS/A_sujeto_rest" ] && mkdir "$MARCAS/A_analizado" 2>/dev/null; then
    log "ANALISIS por sujeto (5 pliegues)"
    "$PY" -u "$M2/analisis_por_sujeto.py" \
      --sujeto "$OUT_A/predicciones_A_sujeto.npz" --rest "$OUT_A/predicciones_A_sujeto_rest.npz" \
      --salida "$OUT_A" --etiqueta "5 pliegues" \
      --ref_sujeto "$REF/metricas_sujeto_norm-sujeto.json" --ref_rest "$REF/metricas_sujeto_norm-sujeto_rest.json" \
      > "$LOGS/analisis_A.log" 2>&1 || { log "FALLO analisis A (ver logs/analisis_A.log)"; exit 1; }
    log "$(grep -E '^   IC 95%' "$LOGS/analisis_A.log" | head -1 | sed 's/^ *//')"
    if grep -q '"lanzar_loso": true' "$OUT_A/analisis_por_sujeto.json"; then
      encolar 00a LOSO_sujeto "$PY -u entrenamiento_cv.py $ECV --normalizacion sujeto --folds 10 --etiqueta LOSO_sujeto --output_dir $OUT_LOSO && bash $YO --gancho-LOSO sujeto"
      encolar 00b LOSO_sujeto_rest "$PY -u entrenamiento_cv.py $ECV --normalizacion sujeto_rest --folds 10 --etiqueta LOSO_sujeto_rest --output_dir $OUT_LOSO && bash $YO --gancho-LOSO sujeto_rest"
      log "DECISION: el intervalo incluye 1 por poco -> deja-un-sujeto-fuera ENCOLADO"
    else
      log "DECISION: no hace falta deja-un-sujeto-fuera"
    fi
  fi
  exit 0
fi
if [ "${1:-}" = "--gancho-LOSO" ]; then
  touch "$MARCAS/LOSO_$2"
  if [ -e "$MARCAS/LOSO_sujeto" ] && [ -e "$MARCAS/LOSO_sujeto_rest" ] && mkdir "$MARCAS/LOSO_analizado" 2>/dev/null; then
    "$PY" -u "$M2/analisis_por_sujeto.py" \
      --sujeto "$OUT_LOSO/predicciones_LOSO_sujeto.npz" --rest "$OUT_LOSO/predicciones_LOSO_sujeto_rest.npz" \
      --salida "$OUT_LOSO" --etiqueta "deja-un-sujeto-fuera" > "$LOGS/analisis_LOSO.log" 2>&1 \
      && log "ANALISIS LOSO: $(grep -E '^   IC 95%' "$LOGS/analisis_LOSO.log" | head -1 | sed 's/^ *//')" \
      || log "FALLO analisis LOSO"
  fi
  exit 0
fi

# ------------------------------------------------------------------ trabajador
trabajador() {
  local id=$1 job nombre libre ultimo ahora
  sleep $(( (id - 1) * 20 ))
  while true; do
    job=$(ls "$COLA" 2>/dev/null | sort | head -1)
    if [ -z "$job" ]; then
      [ -z "$(ls "$CORR" 2>/dev/null)" ] && break
      sleep 30; continue
    fi
    libre=$(awk '/MemAvailable/ {print int($2 / 1024)}' /proc/meminfo)
    if [ "$libre" -lt "$UMBRAL_RAM_MB" ]; then sleep 60; continue; fi
    ultimo=$(cat "$T/ultimo_arranque" 2>/dev/null || echo 0)
    ahora=$(date +%s)
    if [ $((ahora - ultimo)) -lt "$ESPERA_ENTRE_ARRANQUES" ]; then sleep 10; continue; fi
    mv "$COLA/$job" "$CORR/$job" 2>/dev/null || continue
    echo "$ahora" > "$T/ultimo_arranque"
    nombre=${job%.job}
    log "INICIO $nombre (trabajador $id, RAM libre $libre MB)"
    if bash "$CORR/$job" > "$LOGS/$nombre.log" 2>&1; then
      log "FIN_OK $nombre $(grep -E 'Accuracy: +[0-9.]+% \+/-' "$LOGS/$nombre.log" | tail -1 | sed 's/^ *//')"
    else
      log "FALLO $nombre (ver logs/$nombre.log)"
    fi
    mv "$CORR/$job" "$HECHO/$job"
  done
}

# ------------------------------------------------------------------ principal
P=${1:-4}
for f in "$CORR"/*.job; do [ -e "$f" ] && mv "$f" "$COLA/"; done
log "TANDA con $P trabajadores, RAM libre $(awk '/MemAvailable/ {print int($2 / 1024)}' /proc/meminfo) MB"

# A: por sujeto, primero
encolar 10 A_sujeto      "$PY -u entrenamiento_cv.py $ECV --normalizacion sujeto --folds 5 --etiqueta A_sujeto --output_dir $OUT_A && bash $YO --gancho-A sujeto"
encolar 11 A_sujeto_rest "$PY -u entrenamiento_cv.py $ECV --normalizacion sujeto_rest --folds 5 --etiqueta A_sujeto_rest --output_dir $OUT_A && bash $YO --gancho-A sujeto_rest"
# B: 1.b repartida por configuracion (era la etapa mas larga)
for c in green ir 250both 125both; do
  encolar 2${c:0:1}_1b_$c "$PY -u $L/analisis_longitud_onda.py --modelo cnn --configs $c --sufijo _corregido --seed 42 $D --output $L/resultados"
done
# B: 1.a en dos mitades
encolar 30 1a_celdas012 "$PY -u $L/analisis_ventana.py --etapa cnn --top 6 --celdas 0 1 2 --seed 42 $D --output $L/resultados"
encolar 31 1a_celdas345 "$PY -u $L/analisis_ventana.py --etapa cnn --top 6 --celdas 3 4 5 --seed 42 $D --output $L/resultados"
# B: 1.d solo CNN, sin tocar LDA/SVM/RF
encolar 40 1d_cnn "$PY -u $L/analisis_clasicos.py --modelos CNN --sufijo _cnn_corregido --seed 42 $D --output $L/resultados"
# B: ablacion con CNN
encolar 50 ablacion_cnn "$PY -u experimentos/ablacion_fases/ablacion_fases.py --lmg_publico --modelo cnn --seed 42 --data $HOME/data/lmg_wavelength_dataset --cache $HOME/cache_lmg"

for i in $(seq 1 "$P"); do trabajador "$i" & done
wait

log "COLA VACIA: pasos finales en CPU"
cd "$M2"
"$PY" -u "$L/analisis_longitud_onda.py" --modelo cnn --sufijo _corregido --solo_estadistica $D --output "$L/resultados" > "$LOGS/final_1b_estadistica.log" 2>&1 \
  && log "FIN_OK 1b estadistica fusionada" || log "FALLO 1b estadistica (ver logs/final_1b_estadistica.log)"
"$PY" -u "$L/comparativa_fuga_cnn.py" > "$LOGS/final_comparativa.log" 2>&1 \
  && log "FIN_OK comparativa antes/despues" || log "FALLO comparativa (ver logs/final_comparativa.log)"
log "TANDA COMPLETA"
