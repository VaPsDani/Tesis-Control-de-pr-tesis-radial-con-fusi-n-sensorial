# Validación preliminar del pipeline sobre NinaPro DB5

**Pregunta que responde:** ¿el pipeline de clasificación funciona, antes de
tener datos propios con los que probarlo?

Es una **validación algorítmica**, no una comparación entre modalidades. El
dataset trae sEMG y acelerómetro de 10 sujetos, y sirve para comprobar que la
arquitectura, la partición, la normalización y el bucle de entrenamiento hacen
lo que dicen. Que las señales sean sEMG y no LMG es circunstancial: lo que se
valida es el código, no el sensor.

**Lo que este experimento NO es.** No compara LMG con sEMG. Esa comparación
tendría confusores irresolubles, porque serían sujetos distintos, con otra
instrumentación, otro protocolo y otra frecuencia de muestreo, y además
Shahmohammadi et al. ya la hicieron bien, con grabación simultánea de ambas
modalidades sobre los mismos participantes.

La entrada es de forma (40, 8), o sea 5 canales de sEMG más 3 de acelerómetro.
El vector del brazalete propio tiene la misma forma, 5 ópticos más 3 de
acelerómetro, y por eso el mismo pipeline sirve para los dos sin tocar la
arquitectura.

## Qué hay aquí

| Archivo | Qué hace |
|---|---|
| `cargar_ninapro.py` | Lee los .mat, filtra, ventanea y submuestrea Rest |
| `validar_pipeline.py` | Validación cruzada por grupos, con el reporte completo |
| `auditar_particion.py` | Compara esquemas de agrupamiento y mide la fuga de cada uno |
| `auditar_fronteras.py` | Cuenta ventanas que cruzan discontinuidades |
| `comparar_con_si2.py` | Contrasta una corrida contra la referencia transcrita |
| `analisis_por_sujeto.py` | Métricas por sujeto y contrastes pareados |
| `rehacer_capitulo.sh` | Relanza el capítulo de normalización con 4 procesos |
| `resultados_cv/` | Salidas de las corridas, con sus JSON y figuras |

## Resultados que sostienen decisiones del proyecto

- **Agrupar por sujeto y no por repetición.** Con agrupamiento por repetición
  la exactitud sale 82.98%, y con agrupamiento por sujeto baja a 68.2%. La
  diferencia es el sesgo intra-sujeto, no una mejora del modelo. La referencia
  por repetición está preservada bajo el tag `si2-groupkfold-repeticion`.
- **Normalizar por sujeto.** Frente a no normalizar, +12.04 puntos con t
  pareada p = 0.014. La normalización global no aporta nada sobre la de sujeto.
- **Calibrar solo con el reposo del sujeto** no se distingue de calibrar con
  todos sus datos, ni en media ni en dispersión. Ver `resultados_cv/por_sujeto`
  y `resultados_cv/por_sujeto_loso`.
- **La fuga por validación en el test vale +1.27 puntos**, medido con y sin el
  arreglo sobre la misma configuración.

## Reproducir

```bash
python validar_pipeline.py --mat ~/data/NinaPro_DB5 --agrupamiento sujeto \
    --validacion interna --reentrenar --seed 42
```
