#!/usr/bin/env bash
# corrida_completa.sh - Toda la evaluacion de la Etapa 3, sobre la GPU.
#
# Dos trabajos en paralelo, cada uno en orden:
#   A  ablacion mixta (k = 5, guarda el modelo de cada pliegue), estadistica
#      confirmatoria y exploratoria, perdida por cuantizacion INT8 de
#      lmg_imu pliegue a pliegue (A21, A23), y el modelo final de la
#      configuracion que elige la regla A22, convertido a INT8 con el .h
#      para el Modulo 3.
#   B  prueba de generalizacion postural (entrena con estaticas, A17) y
#      LOSO de produccion con lmg_imu, como complemento (A14).
# Dos y no tres: con 9 GB de RAM en WSL, tres procesos de TensorFlow
# arriesgan quedarse sin memoria.
#
# Uso, desde WSL, para que no la corte cerrar la terminal:
#   setsid nohup bash corrida_completa.sh --simulado ~/etapa3 > ~/etapa3.log 2>&1 &
#   setsid nohup bash corrida_completa.sh "ruta/sesiones/*.csv" ~/real > ~/real.log 2>&1 &
# Y en Windows, para que no se suspenda:
#   powershell -File mantener_despierto.ps1 -Patron corrida_completa.sh
set -u
M2="$(cd "$(dirname "$0")/.." && pwd)"
source "$HOME/venv-tesis-221/bin/activate"
export TF_FORCE_GPU_ALLOW_GROWTH=true
ENTRADA="$1"; OUT="$2"; mkdir -p "$OUT"
AB="$M2/experimentos/ablacion_imu"

if [ "$ENTRADA" = "--simulado" ]; then
    (cd "$AB" && python -c "import datos as D; D.generar_sesiones_sinteticas('$OUT/sesiones', n_sujetos=10, semilla=42)")
    SES="$OUT/sesiones/*.csv"
else
    SES="$ENTRADA"
fi
echo "$(date -Is) inicio, sesiones: $SES"

(
    python -u "$AB/ablacion_imu.py" --sesiones "$SES" --guardar_modelos \
        --output "$OUT/ablacion_mixto" > "$OUT/A1_ablacion_mixto.log" 2>&1 &&
    python -u "$AB/estadistica.py" --csv "$OUT/ablacion_mixto/ablacion_imu_por_sujeto.csv" \
        > "$OUT/A2_estadistica.txt" 2>&1 &&
    python -u "$M2/produccion/perdida_cuantizacion.py" --ablacion "$OUT/ablacion_mixto" \
        --sesiones "$SES" --composicion lmg_imu > "$OUT/A3_perdida_int8.log" 2>&1 &&
    ELEGIDA=$(python -c "import json; print(json.load(open('$OUT/ablacion_mixto/ablacion_imu.json'))['regla_de_despliegue']['elegida'])") &&
    python -u "$M2/produccion/entrenar_modelo.py" --sesiones "$SES" --modo final \
        --composicion "$ELEGIDA" --output "$OUT/produccion_final" > "$OUT/A4_produccion_final.log" 2>&1 &&
    python -u "$M2/produccion/convertir_tflite.py" --modelo "$OUT/produccion_final/modelo_final.keras" \
        --info "$OUT/produccion_final/final_$ELEGIDA.json" --sesiones "$SES" \
        --output_dir "$OUT/produccion_final" > "$OUT/A5_conversion_int8.log" 2>&1
    echo "$(date -Is) trabajo A terminado, codigo $?"
) &
(
    python -u "$AB/ablacion_imu.py" --sesiones "$SES" --entrenamiento estatica_a_dinamica \
        --output "$OUT/ablacion_estatica_a_dinamica" > "$OUT/B1_estatica_a_dinamica.log" 2>&1 &&
    python -u "$M2/produccion/entrenar_modelo.py" --sesiones "$SES" --modo loso \
        --composicion lmg_imu --output "$OUT/produccion_loso" > "$OUT/B2_produccion_loso.log" 2>&1
    echo "$(date -Is) trabajo B terminado, codigo $?"
) &
wait
echo "$(date -Is) FIN" | tee "$OUT/FIN"
