# Benchmark de inferencia en el ESP32

> **Etapa LMG/NinaPro, hoy trabajo futuro (2026-11-13).** Con el cambio a
> QRE1113/OMG, la cuantización INT8 y el despliegue en el ESP32 quedan fuera
> del alcance: todo se evalúa fuera de línea. Este sketch se conserva sin
> adaptar. Sus archivos `resolver_modelo_lmg.h` y `reverse_v2_lmg.*` son
> copias de los del firmware de control, que ahora está en
> `archivo/Modulo3_Inferencia_Control_LMG/`. Ver `archivo/README.md`.

Mide el tiempo de inferencia del modelo INT8 en el ESP32, sin sensores: 100
ejecuciones sobre una ventana fija y el perfil por operación de TFLite
Micro. Detalles en la cabecera de `Benchmark_Inferencia.ino`.
