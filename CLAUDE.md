# Instrucciones para Claude en este repositorio

Tesis de control de prótesis transradial con LMG e IMU sobre ESP32. Tres
módulos: adquisición, pipeline de aprendizaje profundo e inferencia con
control.

## Inicio de cada sesión

Estas cuatro reglas existen porque ya pasó: una sesión trabajó durante días
sobre una rama que iba 11 commits por detrás de `main`, y por eso afirmó que
el firmware usaba `TensorFlowLite_ESP32` cuando hacía tiempo que usaba
`Chirale_TensorFLowLite`, y que no existía el experimento de cuantización
INT8 cuando sí existía.

1. **Sincronizar antes de leer o tocar nada.** Al empezar, ejecutar
   `git fetch` y comparar la rama actual con `origin/main`. Si hay
   diferencia, sincronizar **antes** de leer o modificar cualquier archivo,
   y avisar al usuario de cuántos commits había de diferencia.

   ```bash
   git fetch origin
   git rev-list --count HEAD..origin/main   # commits que faltan aqui
   git rev-list --count origin/main..HEAD   # commits que no estan en main
   ```

2. **Trabajar directamente sobre `main`**, salvo que el usuario pida otra
   cosa.

3. **Verificar antes de afirmar.** Antes de decir qué versión, qué librería
   o qué archivo usa el proyecto, comprobar que se está leyendo la última
   versión de `main`. Una respuesta sobre versiones o dependencias que sale
   de una copia desactualizada es una respuesta equivocada, y en esta tesis
   esas afirmaciones acaban escritas en el documento.

4. **Cerrar cada bloque con commit y push.** Al terminar un bloque de
   trabajo aprobado por el usuario, hacer commit y push para que la
   siguiente sesión lo vea. Lo que no se sube, la siguiente sesión no lo
   tiene, y si el worktree se recicla se pierde.

## Cosas del proyecto que conviene no olvidar

- **Un solo entorno de trabajo** desde 2026-10-05: `requirements.txt`,
  TensorFlow 2.21 y `tf_keras` 2.21 con GPU, en `~/venv-tesis-221`. Keras 2
  porque es el único con el que la LSTM cuantiza a INT8. Su `activate` ya
  agrega las rutas de CUDA y fija Keras 2 (`herramientas/rutas_cuda_venv.sh`).
  Aparte quedan `requirements-tflm.txt` (intérprete de TFLite Micro en PC,
  Python 3.13), `requirements-captura.txt` (la PC de captura) y
  `requirements-tf216-historico.txt`, solo como registro de con qué salieron
  los resultados preliminares ya publicados.
- **Toda validación cruzada agrupa por sujeto**, nunca partición aleatoria.
- **Los callbacks nunca ven el test.** Se entrena con validación interna y
  reentreno, ver `common/entrenamiento.py`.
- **No romper los experimentos ya publicados** ni el tag
  `si2-groupkfold-repeticion`.
- **El dataset externo no se versiona**, va en `.gitignore`.
- Si algo que pide el usuario no coincide con el código real, decírselo en
  vez de improvisar.
