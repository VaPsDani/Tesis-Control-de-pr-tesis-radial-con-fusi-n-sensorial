# Experimento: LED verde con espaciador vs. LED IR sin espaciador

Pedido por el asesor. El hardware todavía no está armado; el análisis queda
listo para correr en cuanto existan las capturas.

## Qué compara

Dos configuraciones ópticas del brazalete LMG:

- **verde con espaciador de silicona**: LED verde, separado de la piel por una capa
  de silicona que modifica el acoplamiento óptico.
- **infrarrojo sin espaciador**: el LED IR de 940 nm de nuestro diseño, en contacto
  directo.

## Cómo capturar

Con `captura_sesion.py`, añadiendo al CSV una columna `condicion` con el nombre de
la configuración. **Mismos sujetos en ambas condiciones**, porque el análisis es
pareado por sujeto, y con el orden de condiciones contrabalanceado entre sujetos,
para que la configuración no quede confundida con la fatiga ni con el orden. Así
está diseñado `lmg_wavelength_dataset`, y por eso su comparación es interpretable.

## Dos medidas, y por qué hacen falta las dos

**Índice de rendimiento** (`--modo indice`):

$$I = \frac{\Delta S}{L \cdot R}, \qquad \Delta S = \left|\bar S_{gesto} - \bar S_{reposo}\right|$$

con $L$ la intensidad radiante del LED (mW/sr) y $R$ la responsividad del
fotodiodo (A/W). Normalizar por $L$ y $R$ separa la calidad del **acoplamiento
óptico** —espaciador, geometría, tejido— de cuánta luz emite el LED y de cuán
sensible es el fotodiodo a ese color.

**Exactitud de clasificación** (`--modo clasificacion`): mismo clasificador (LDA),
mismo particionado, cada condición por separado.

No son redundantes. Un cambio de amplitud grande pero **igual para todos los
gestos** sube $I$ y no ayuda a separarlos. El test sintético del script lo muestra
a propósito: la condición con mayor índice es la que peor clasifica.

## Trampas que el script evita

- **Unidades fotométricas.** La luminosidad de los LED verdes suele darse en
  milicandelas. La candela pondera por la sensibilidad del ojo, que a 940 nm es
  prácticamente cero: un LED IR tiene ~0 mcd aunque emita mucha potencia. Mezclar
  mcd y mW/sr hace el índice arbitrario. **El script rechaza cualquier unidad
  fotométrica** y exige mW/sr para todas las condiciones.
- **Responsividad a la longitud de onda correcta.** La del OPT101 depende del color:
  su máximo cae hacia 750–850 nm y baja hacia el verde. Hay que leer $R$ en la curva
  del datasheet **a la longitud de onda de cada LED**, no usar el valor típico de la
  portada (0.45 A/W a 650 nm).
- **Validación por sujeto.** Con un solo sujeto es imposible y el script se niega.
  `--permitir_intra_sujeto` agrupa por repetición y rotula el resultado como
  intra-sujeto.
- **Tamaño de muestra.** Con $n$ sujetos, el menor $p$ bilateral de Wilcoxon es
  $2/2^n$. Con 5 sujetos o menos nunca baja de 0.0625, así que ningún resultado puede
  ser significativo al 5%. **Hacen falta al menos 6 sujetos.** Con menos, reportar el
  tamaño del efecto y no el $p$.

## Uso

```bash
python indice_rendimiento.py --csv "sesiones/*.csv" --parametros opticas.json
```

`opticas.json`:

```json
{
  "verde_espaciador":  {"intensidad_mW_sr": 12.0, "responsividad_A_W": 0.30,
                        "longitud_onda_nm": 525},
  "ir_sin_espaciador": {"intensidad_mW_sr": 20.0, "responsividad_A_W": 0.38,
                        "longitud_onda_nm": 940}
}
```

Los valores del ejemplo son ilustrativos; hay que sustituirlos por los de los
datasheets de los componentes reales.

Salidas en `resultados/`: `indice_rendimiento.csv` (por condición, sujeto, canal y
gesto) y `clasificacion_por_condicion.csv`.
