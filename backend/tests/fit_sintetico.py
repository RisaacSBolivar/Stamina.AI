"""
Actividades `.FIT` fabricadas para las pruebas, sin un solo dato real.

Los `.FIT` del historial del autor no viven en el repositorio: llevan GPS y
frecuencia cardíaca, son datos personales. Pero la subida de historial es el
flujo central de la API y no puede quedarse sin probar en un clon limpio. Así
que aquí se escriben carreras sintéticas, byte a byte, con el mismo codificador
que compila los entrenamientos (`stamina_core.entrenamiento`).

Solo llevan mensajes `record` con los campos que lee `procesar_fit`, y **ninguna
coordenada**: la posición no hace falta para nada del pipeline.
"""

from __future__ import annotations

import math
import struct
from datetime import UTC, datetime, timedelta
from pathlib import Path

from stamina_core.entrenamiento import (
    CAMPOS_FILE_ID,
    EPOCA_FIT,
    T_UINT32,
    crc_fit,
    mensaje_definicion,
)

T_SINT8, T_UINT8 = 0x01, 0x02

# Mensaje `record` (número global 20): (número de campo, tamaño, tipo base).
CAMPOS_RECORD = [
    (253, 4, T_UINT32),  # timestamp, segundos desde la época FIT
    (5, 4, T_UINT32),  # distance, escala 100 (cm)
    (3, 1, T_UINT8),  # heart_rate, bpm
    (4, 1, T_UINT8),  # cadence, rpm
    (73, 4, T_UINT32),  # enhanced_speed, escala 1000 (mm/s)
    (78, 4, T_UINT32),  # enhanced_altitude, escala 5 y desfase 500
    (13, 1, T_SINT8),  # temperature, °C
]
# El mismo mensaje sin altitud, para fabricar lo que el control de calidad descarta.
CAMPOS_RECORD_SIN_ALTITUD = [c for c in CAMPOS_RECORD if c[0] != 78]

INICIO = datetime(2024, 3, 1, 7, 0, tzinfo=UTC)


def actividad_fit(
    inicio: datetime = INICIO,
    minutos: float = 20.0,
    velocidad_ms: float = 3.0,
    con_altitud: bool = True,
) -> bytes:
    """
    Una carrera continua a 1 Hz, como la grabaría un reloj.

    Velocidad, pulso y altitud ondulan un poco para que los tramos de 100 m no
    salgan todos iguales; la cadencia y la temperatura son fijas.
    """
    campos = CAMPOS_RECORD if con_altitud else CAMPOS_RECORD_SIN_ALTITUD
    creado = int((inicio - EPOCA_FIT).total_seconds())

    registros = mensaje_definicion(0, 0, CAMPOS_FILE_ID)
    # file_id: tipo 4 = actividad (el 5 que usan los entrenamientos es otra cosa)
    registros += bytes([0]) + struct.pack("<BHHII", 4, 255, 0, 1, creado)

    registros += mensaje_definicion(1, 20, campos)
    distancia = 0.0
    for segundo in range(int(minutos * 60)):
        velocidad = velocidad_ms + 0.3 * math.sin(segundo / 90)
        distancia += velocidad
        altitud = 100 + 20 * math.sin(distancia / 800)

        registros += bytes([1])
        registros += struct.pack("<II", creado + segundo, round(distancia * 100))
        registros += struct.pack("<BB", 140 + segundo // 60, 85)
        registros += struct.pack("<I", round(velocidad * 1000))
        if con_altitud:
            registros += struct.pack("<I", round((altitud + 500) * 5))
        registros += struct.pack("<b", 18)

    cabecera = struct.pack("<BBHI4s", 14, 0x20, 2140, len(registros), b".FIT")
    cabecera += struct.pack("<H", crc_fit(cabecera))

    contenido = cabecera + registros
    return contenido + struct.pack("<H", crc_fit(contenido))


def escribir_historial(carpeta: Path, n: int = 16) -> list[str]:
    """
    `n` carreras en días consecutivos, con el nombre `AAAA-MM-DD_<id>.fit`.

    La cuarta sale sin altitud a propósito: así el lote tiene un motivo de
    descarte real, como el historial del autor, y las pruebas de paralelo
    comprueban también que los motivos llegan en el mismo orden.
    """
    carpeta.mkdir(parents=True, exist_ok=True)
    rutas = []
    for indice in range(n):
        dia = INICIO + timedelta(days=indice)
        nombre = f"{dia:%Y-%m-%d}_{9000000000 + indice}.fit"
        contenido = actividad_fit(dia, minutos=20 + indice % 5, con_altitud=indice != 3)
        (carpeta / nombre).write_bytes(contenido)
        rutas.append(str(carpeta / nombre))
    return rutas
