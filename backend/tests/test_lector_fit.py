"""
El lector propio de `.FIT` tiene que dar exactamente lo mismo que fitparse.

`stamina_core.lector_fit` sustituye a fitparse en `procesar_fit` porque es unas
diez veces más rápido. Estas pruebas lo comparan con fitparse registro a
registro: en carreras sintéticas y en un archivo hecho a mano con los casos
raros del formato (timestamps comprimidos que dan la vuelta, `speed` y
`altitude` sin `enhanced_*`, valores inválidos, una definición big-endian, la
distancia comprimida y acumulada, dos `.FIT` encadenados). Con los 492 `.FIT`
reales del autor se comprobó lo mismo el 2026-09-26: 686 de 686 archivos
idénticos, contando los de la demo y los sintéticos.
"""

from __future__ import annotations

import io
import os
import struct

import fitparse
import pandas as pd
import pytest

from stamina_core import ingesta
from stamina_core.config import CAMPOS_FIT
from stamina_core.entrenamiento import (
    CAMPOS_FILE_ID,
    EPOCA_FIT,
    T_UINT16,
    T_UINT32,
    crc_fit,
    mensaje_definicion,
)
from stamina_core.lector_fit import (
    CAMPOS_RECORD,
    DelegarEnFitparse,
    FitIlegible,
    crc,
    leer_records,
)

from .fit_sintetico import INICIO, actividad_fit

T_SINT8, T_UINT8, T_BYTE = 0x01, 0x02, 0x0D


def con_fitparse(datos: bytes) -> list[dict]:
    """Lo que hacía `procesar_fit` antes: fitparse, reducido a `CAMPOS_FIT`."""
    mensajes = fitparse.FitFile(io.BytesIO(datos)).get_messages("record")
    return [{c.name: c.value for c in fila if c.name in CAMPOS_FIT} for fila in mensajes]


def envolver(cuerpo: bytes) -> bytes:
    """Cabecera de 14 bytes con su CRC, los mensajes y el CRC del archivo."""
    cabecera = struct.pack("<BBHI4s", 14, 0x20, 2140, len(cuerpo), b".FIT")
    cabecera += struct.pack("<H", crc_fit(cabecera))
    contenido = cabecera + cuerpo
    return contenido + struct.pack("<H", crc_fit(contenido))


def file_id(creado: int) -> bytes:
    return (
        mensaje_definicion(0, 0, CAMPOS_FILE_ID)
        + bytes([0])
        + struct.pack("<BHHII", 4, 255, 0, 1, creado)
    )


def archivo_raro() -> bytes:
    """Un .FIT con todo lo que un reloj puede grabar distinto de lo habitual."""
    # Los 5 bits bajos cerca de 31, para que el timestamp comprimido dé la vuelta.
    t0 = int((INICIO - EPOCA_FIT).total_seconds()) | 0x1C
    cuerpo = file_id(t0)

    # Reloj antiguo: `speed` y `altitude` de 16 bits, sin `enhanced_*`.
    cuerpo += mensaje_definicion(
        1,
        20,
        [(253, 4, T_UINT32), (5, 4, T_UINT32), (3, 1, T_UINT8), (4, 1, T_UINT8),
         (6, 2, T_UINT16), (2, 2, T_UINT16), (13, 1, T_SINT8)],
    )  # fmt: skip
    for i, (fc, temperatura) in enumerate([(150, 18), (0xFF, 0x7F), (152, 19)]):
        cuerpo += bytes([1]) + struct.pack(
            "<IIBBHHb", t0 + i, 300 * i, fc, 85, 3100 + i, 3000 + i, temperatura
        )

    # Un evento con timestamp: es la base de los comprimidos que vienen después.
    cuerpo += mensaje_definicion(3, 21, [(253, 4, T_UINT32), (0, 1, T_UINT8)])
    cuerpo += bytes([3]) + struct.pack("<IB", t0 + 3, 0)

    # Records con cabecera de timestamp comprimido (sin campo 253).
    cuerpo += mensaje_definicion(
        2,
        20,
        [(5, 4, T_UINT32), (3, 1, T_UINT8), (4, 1, T_UINT8), (73, 4, T_UINT32), (78, 4, T_UINT32)],
    )
    for i in range(1, 8):
        cabecera = 0x80 | (2 << 5) | ((t0 + 3 + i) & 0x1F)
        cuerpo += bytes([cabecera]) + struct.pack(
            "<IBBII", 900 + 300 * i, 150 + i, 86, 3050 + i, (100 + 500) * 5 + i
        )

    # Una definición big-endian.
    campos_be = [(253, 4, T_UINT32), (5, 4, T_UINT32), (3, 1, T_UINT8), (73, 4, T_UINT32)]
    cuerpo += bytes([0x44, 0, 1]) + struct.pack(">HB", 20, len(campos_be))
    cuerpo += b"".join(bytes(c) for c in campos_be)
    cuerpo += bytes([4]) + struct.pack(">IIBI", t0 + 20, 4000, 155, 3200)

    # `compressed_speed_distance`: 3 bytes con velocidad (12 bits) y distancia
    # (12 bits, acumulada: da la vuelta a los 4096).
    cuerpo += mensaje_definicion(5, 20, [(253, 4, T_UINT32), (8, 3, T_BYTE), (3, 1, T_UINT8)])
    distancia = 0
    for i in range(6):
        distancia = (distancia + 1500) % 4096
        empaquetado = (300 + i) | (distancia << 12)
        cuerpo += bytes([5]) + struct.pack("<I", t0 + 30 + i) + empaquetado.to_bytes(3, "little")
        cuerpo += bytes([150])

    return envolver(cuerpo)


def test_el_crc_es_el_mismo_que_el_del_compilador():
    datos = os.urandom(4096)
    assert crc(datos) == crc_fit(datos)
    assert crc(datos[2000:], crc(datos[:2000])) == crc_fit(datos)


def test_lee_los_mismos_campos_que_pide_procesar_fit():
    assert {nombre for nombre, _, _ in CAMPOS_RECORD.values()} == set(CAMPOS_FIT)


@pytest.mark.parametrize(
    ("minutos", "velocidad", "con_altitud"),
    [(20, 3.0, True), (7, 2.4, True), (15, 3.3, False)],
)
def test_igual_que_fitparse_en_carreras_sinteticas(minutos, velocidad, con_altitud):
    datos = actividad_fit(minutos=minutos, velocidad_ms=velocidad, con_altitud=con_altitud)
    assert leer_records(datos) == con_fitparse(datos)


def test_igual_que_fitparse_en_los_casos_raros():
    datos = archivo_raro()
    esperado = con_fitparse(datos)
    # Que el archivo de verdad ejercite lo que dice ejercitar.
    assert any(r.get("heart_rate") is None for r in esperado)
    assert sum("enhanced_speed" in r and "timestamp" in r for r in esperado) > 10
    assert leer_records(datos) == esperado


def test_igual_que_fitparse_con_archivos_encadenados():
    datos = archivo_raro() + actividad_fit(minutos=3)
    assert leer_records(datos) == con_fitparse(datos)


def test_un_crc_roto_es_ilegible_para_los_dos():
    datos = bytearray(actividad_fit(minutos=3))
    datos[-1] ^= 0xFF
    with pytest.raises(FitIlegible):
        leer_records(bytes(datos))
    with pytest.raises(Exception):  # noqa: B017 — fitparse lanza su propio tipo
        con_fitparse(bytes(datos))
    assert ingesta.procesar_fit(bytes(datos), nombre="roto")[0] == "archivo ilegible"


def test_los_campos_de_desarrollador_se_los_deja_a_fitparse():
    t0 = int((INICIO - EPOCA_FIT).total_seconds())
    definicion = mensaje_definicion(1, 20, [(253, 4, T_UINT32), (3, 1, T_UINT8)])
    # Bit 5 de la cabecera: la definición trae además un campo de desarrollador.
    definicion = bytes([definicion[0] | 0x20]) + definicion[1:] + bytes([1, 0, 1, 0])
    datos = envolver(file_id(t0) + definicion + bytes([1]) + struct.pack("<IBB", t0, 150, 7))

    with pytest.raises(DelegarEnFitparse):
        leer_records(datos)


def test_procesar_fit_da_los_mismos_tramos_que_con_fitparse(monkeypatch):
    datos = actividad_fit(minutos=25)
    motivo, tramos = ingesta.procesar_fit(datos, nombre="2024-03-01_1")

    # El mismo archivo, obligando a pasar por fitparse (el camino de siempre).
    def sin_lector_propio(_datos):
        raise DelegarEnFitparse("prueba")

    monkeypatch.setattr(ingesta, "leer_records", sin_lector_propio)
    motivo_fp, tramos_fp = ingesta.procesar_fit(datos, nombre="2024-03-01_1")

    assert motivo == motivo_fp == "ok"
    pd.testing.assert_frame_equal(tramos, tramos_fp)
