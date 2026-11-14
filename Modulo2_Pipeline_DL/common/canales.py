"""
canales.py - Unica fuente de verdad de los canales del hardware OMG
====================================================================
Protesis transradial - OMG (QRE1113) + IMU

Lo importan la captura, el preprocesamiento, las fases, los reportes y
los analisis. Nada de "v1".."v8" escrito a mano en otro archivo. Sin
dependencias, para que la PC de captura no necesite nada mas.

Tiene que coincidir con Modulo1_Adquisicion_Datos/config.h (NUM_OPT y el
orden del CSV del firmware).
"""

NUM_OPT = 8

CANALES_OPT = [f"v{i}" for i in range(1, NUM_OPT + 1)]       # senal: V_apag - V_enc
CANALES_ACC = ["ax", "ay", "az"]
CANALES_GIRO = ["gx", "gy", "gz"]
CANALES_AMB = [f"amb{i}" for i in range(1, NUM_OPT + 1)]     # trama oscura, V_apag

# Linea que emite el firmware M1-2026.11.13-QRE, en orden.
CAMPOS_FIRMWARE = (["timestamp_ms"] + CANALES_OPT + CANALES_ACC
                   + CANALES_GIRO + CANALES_AMB)
