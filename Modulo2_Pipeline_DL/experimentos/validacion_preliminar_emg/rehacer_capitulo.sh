#!/bin/bash
# Rehace el experimento de normalizacion con validacion interna y
# reentreno, 4 configuraciones a la vez en la misma GPU.
#
# Las cinco cifras del capitulo y su corrida equivalente:
#   56.99  sujeto + ninguna
#   58.57  sujeto + global
#   70.00  sujeto + sujeto
#   69.11  sujeto + sujeto_rest
#   83.62  repeticion + ninguna (control)
#
# Todas con --validacion interna --reentrenar --seed 42, early stopping
# desde la epoca 10, 5 pliegues, batch 32, lr 1e-3.

source "$HOME/env-tesis.sh"
# Imprescindible con varios procesos: sin esto cada TensorFlow reserva casi
# toda la VRAM al arrancar y el segundo proceso se queda sin memoria.
export TF_FORCE_GPU_ALLOW_GROWTH=true

CODE=/mnt/c/Users/danie/OneDrive/Documents/GitHub/Tesis-Control-de-pr-tesis-radial-con-fusi-n-sensorial/.claude/worktrees/groupkfold-subject-validation-9509f7/Modulo2_Pipeline_DL/experimentos/validacion_preliminar_emg
OUT="$CODE/resultados_cv/rehecho_val_interna"
LOGS="$HOME/rehacer_logs"
PARALELO=4
mkdir -p "$OUT" "$LOGS"

# 4 procesos necesitan ~8 GB; con los 7.2 GB por defecto de WSL no caben.
libre=$(free -m | awk '/Mem:/ {print $7}')
if [ "$libre" -lt 9000 ]; then
  echo "### ABORTADO: solo $libre MB libres en WSL; hacen falta ~9000 para $PARALELO procesos."
  echo "### Amplie la memoria de WSL en .wslconfig y reinicie con wsl --shutdown."
  exit 1
fi
echo "### RAM libre en WSL: $libre MB, $PARALELO procesos en paralelo"

correr() {
  etiqueta=$1; shift
  cd "$CODE"
  echo "### INICIO $etiqueta $(date +%H:%M:%S)"
  "$HOME/venv-tesis/bin/python" -u validar_pipeline.py \
    --mat "$HOME/data/NinaPro_DB5" "$@" \
    --validacion interna --reentrenar \
    --early_stopping_start 10 --folds 5 --epochs 100 --batch_size 32 --lr 1e-3 \
    --seed 42 --etiqueta "$etiqueta" \
    --cache "$HOME/cache_ninapro.npz" --output_dir "$OUT" \
    > "$LOGS/$etiqueta.log" 2>&1 \
    && echo "### FIN_OK $etiqueta $(date +%H:%M:%S) $(grep -E 'Accuracy: +[0-9.]+% \+/-' "$LOGS/$etiqueta.log" | tail -1)" \
    || echo "### FALLO $etiqueta rc=$? $(date +%H:%M:%S) (ver $LOGS/$etiqueta.log)"
}
export -f correr
export CODE OUT LOGS

printf '%s\n' \
  "sujeto_norm-sujeto --agrupamiento sujeto --normalizacion sujeto" \
  "sujeto_norm-sujeto_rest --agrupamiento sujeto --normalizacion sujeto_rest" \
  "sujeto_norm-global --agrupamiento sujeto --normalizacion global" \
  "sujeto_norm-ninguna --agrupamiento sujeto --normalizacion ninguna" \
  "repeticion_norm-ninguna --agrupamiento repeticion --normalizacion ninguna" \
| xargs -P "$PARALELO" -L 1 bash -c 'correr $0 "$@"'

echo "### CAPITULO COMPLETO $(date +%H:%M:%S)"
