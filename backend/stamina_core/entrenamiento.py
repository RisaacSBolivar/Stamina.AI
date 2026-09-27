"""
Compilación de la estrategia a entrenamiento estructurado (.FIT y JSON).

Sección 7.2 del notebook. El `.FIT` se escribe a mano byte a byte siguiendo el
FIT Protocol y se relee con `fitparse` para verificar CRC y estructura; el JSON
sigue el esquema de la API de Garmin Connect.

Estado de la verificación: el archivo se relee sin errores, Garmin Connect
aceptó la subida por API asignándole identificador, y el entrenamiento se ha
probado en un reloj físico.
"""

from __future__ import annotations

import struct
from datetime import UTC, datetime

import pandas as pd

# --- Intensidades y etiquetas ------------------------------------------------
# El FIT define también recovery(4) e interval(5), pero se dejan todos en activo
# salvo el arranque: en un reloj viejo esas intensidades no siempre se muestran
# bien, y lo que importa es el objetivo de ritmo, no la etiqueta.
INTENSIDAD_ACTIVO = 0
INTENSIDAD_CALENTAMIENTO = 2

ETIQUETA_ZONA = {
    "Recuperación": "Recup",
    "Crucero": "Crucero",
    "Exigencia alta": "Exig alta",
    "Exigencia crítica": "Exig critica",
}

MIN_KM_POR_PASO = 2.0


def compilar_pasos(tabla_km: pd.DataFrame, min_km_por_paso: float = MIN_KM_POR_PASO):
    """
    Convierte la tabla por kilómetro en pasos de entrenamiento.

    Agrupa kilómetros contiguos de la misma zona y fusiona los bloques cortos
    con el anterior, para que el entrenamiento sea seguible.
    """
    tabla = tabla_km.sort_values("km").copy()
    bloques = (tabla["zona"] != tabla["zona"].shift()).cumsum()

    crudos = []
    for _, bloque in tabla.groupby(bloques):
        crudos.append(
            {
                "km_inicio": int(bloque["km"].min()) - 1,
                "km_fin": int(bloque["km"].max()),
                "zona": bloque["zona"].iat[0],
                "ritmo_min": bloque["ritmo_objetivo"].min(),
                "ritmo_max": bloque["ritmo_objetivo"].max(),
                "fc_min": bloque["fc_objetivo"].min(),
                "fc_max": bloque["fc_objetivo"].max(),
                "minutos": bloque["tiempo_min"].sum(),
            }
        )

    pasos: list[dict] = []
    for crudo in crudos:
        largo = crudo["km_fin"] - crudo["km_inicio"]
        if pasos and largo < min_km_por_paso:
            previo = pasos[-1]
            previo["km_fin"] = crudo["km_fin"]
            previo["ritmo_min"] = min(previo["ritmo_min"], crudo["ritmo_min"])
            previo["ritmo_max"] = max(previo["ritmo_max"], crudo["ritmo_max"])
            previo["fc_min"] = min(previo["fc_min"], crudo["fc_min"])
            previo["fc_max"] = max(previo["fc_max"], crudo["fc_max"])
            previo["minutos"] += crudo["minutos"]
        else:
            pasos.append(dict(crudo))

    for posicion, paso in enumerate(pasos):
        paso["km"] = paso["km_fin"] - paso["km_inicio"]
        paso["nombre"] = (
            f"K{paso['km_inicio']}-{paso['km_fin']} {ETIQUETA_ZONA.get(paso['zona'], paso['zona'])}"
        )
        paso["notas"] = (
            f"{paso['ritmo_min']:.2f}-{paso['ritmo_max']:.2f} min/km, "
            f"FC {paso['fc_min']:.0f}-{paso['fc_max']:.0f}"
        )
        es_arranque = posicion == 0 and paso["zona"] == "Recuperación"
        paso["intensidad"] = INTENSIDAD_CALENTAMIENTO if es_arranque else INTENSIDAD_ACTIVO

    return pd.DataFrame(pasos)


# --- Codificador de archivos .FIT de entrenamiento ---------------------------
# El formato es: cabecera de 14 bytes, una tanda de registros y un CRC de 2.
# Cada tipo de mensaje se declara una vez (mensaje de definición) y después se
# escriben los datos referenciando esa definición. Referencia: FIT Protocol.

TABLA_CRC = [
    0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
    0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400,
]  # fmt: skip

EPOCA_FIT = datetime(1989, 12, 31, tzinfo=UTC)

# Tipos base del FIT (el bit alto marca los que ocupan más de un byte)
T_ENUM, T_UINT16, T_UINT32, T_UINT32Z, T_STRING = 0x00, 0x84, 0x86, 0x8C, 0x07

LARGO_NOMBRE = 24
LARGO_NOTAS = 40

# (número de campo, tamaño, tipo) según el perfil FIT de cada mensaje
CAMPOS_FILE_ID = [
    (0, 1, T_ENUM),
    (1, 2, T_UINT16),
    (2, 2, T_UINT16),
    (3, 4, T_UINT32Z),
    (4, 4, T_UINT32),
]
CAMPOS_WORKOUT = [(4, 1, T_ENUM), (6, 2, T_UINT16), (8, LARGO_NOMBRE, T_STRING)]
CAMPOS_PASO = [
    (254, 2, T_UINT16),
    (0, LARGO_NOMBRE, T_STRING),
    (1, 1, T_ENUM),
    (2, 4, T_UINT32),
    (3, 1, T_ENUM),
    (4, 4, T_UINT32),
    (5, 4, T_UINT32),
    (6, 4, T_UINT32),
    (7, 1, T_ENUM),
    (8, LARGO_NOTAS, T_STRING),
]


def crc_fit(datos, crc: int = 0) -> int:
    """CRC de 16 bits del protocolo FIT, con la tabla de 16 entradas."""
    for byte in datos:
        tmp = TABLA_CRC[crc & 0xF]
        crc = ((crc >> 4) & 0x0FFF) ^ tmp ^ TABLA_CRC[byte & 0xF]
        tmp = TABLA_CRC[crc & 0xF]
        crc = ((crc >> 4) & 0x0FFF) ^ tmp ^ TABLA_CRC[(byte >> 4) & 0xF]
    return crc


def mensaje_definicion(local: int, numero_global: int, campos) -> bytes:
    """Declara qué campos trae cada mensaje de datos de ese tipo."""
    cuerpo = b"\x00\x00" + struct.pack("<H", numero_global) + bytes([len(campos)])
    for numero, tamano, tipo in campos:
        cuerpo += bytes([numero, tamano, tipo])
    return bytes([0x40 | local]) + cuerpo


def texto_fijo(texto: str, tamano: int) -> bytes:
    """Texto a campo de largo fijo, sin cortar a la mitad un carácter UTF-8."""
    crudo = texto.encode("utf-8")[: tamano - 1]
    crudo = crudo.decode("utf-8", errors="ignore").encode("utf-8")
    return crudo + b"\x00" * (tamano - len(crudo))


def compilar_workout_fit(pasos: pd.DataFrame, nombre: str = "Estrategia") -> bytes:
    """Los pasos como contenido de un archivo .FIT de entrenamiento."""
    creado = int((datetime.now(UTC) - EPOCA_FIT).total_seconds())
    registros = b""

    # file_id: le dice al reloj que esto es un entrenamiento (tipo 5)
    registros += mensaje_definicion(0, 0, CAMPOS_FILE_ID)
    registros += bytes([0]) + struct.pack("<BHHII", 5, 255, 0, 1, creado)

    # workout: deporte y cuántos pasos vienen
    registros += mensaje_definicion(1, 26, CAMPOS_WORKOUT)
    registros += bytes([1]) + struct.pack("<BH", 1, len(pasos)) + texto_fijo(nombre, LARGO_NOMBRE)

    # workout_step: uno por paso
    registros += mensaje_definicion(2, 27, CAMPOS_PASO)
    for indice, paso in enumerate(pasos.itertuples()):
        distancia_cm = int(round(paso.km * 1000 * 100))  # escala 100
        velocidad_lenta = int(round(1000 / 60 / paso.ritmo_max * 1000))  # m/s x 1000
        velocidad_rapida = int(round(1000 / 60 / paso.ritmo_min * 1000))

        registros += bytes([2])
        registros += struct.pack("<H", indice)
        registros += texto_fijo(paso.nombre, LARGO_NOMBRE)
        # duración por distancia (1), objetivo de velocidad (0) con rango propio
        registros += struct.pack(
            "<BIBIIIB",
            1,
            distancia_cm,
            0,
            0,
            velocidad_lenta,
            velocidad_rapida,
            paso.intensidad,
        )
        registros += texto_fijo(paso.notas, LARGO_NOTAS)

    cabecera = struct.pack("<BBHI4s", 14, 0x20, 2140, len(registros), b".FIT")
    cabecera += struct.pack("<H", crc_fit(cabecera))

    contenido = cabecera + registros
    contenido += struct.pack("<H", crc_fit(contenido))
    return contenido


def verificar_workout_fit(contenido: bytes) -> dict:
    """
    Relee el .FIT con `fitparse` y devuelve lo que Garmin vería.

    Es la prueba del codificador: si el CRC o la estructura estuvieran mal,
    `fitparse` lanzaría una excepción aquí.
    """
    import io  # noqa: PLC0415

    import fitparse  # noqa: PLC0415

    archivo = fitparse.FitFile(io.BytesIO(contenido))
    archivo.parse()

    pasos = []
    for mensaje in archivo.get_messages("workout_step"):
        campos = {c.name: c.value for c in mensaje}
        pasos.append(
            {
                "paso": campos.get("wkt_step_name"),
                "distancia_m": campos.get("duration_distance"),
                "ritmo_lento": round(1000 / 60 / campos["custom_target_speed_low"], 2),
                "ritmo_rapido": round(1000 / 60 / campos["custom_target_speed_high"], 2),
                "notas": campos.get("notes"),
            }
        )

    cabecera = next(archivo.get_messages("workout"))
    return {
        "cabecera": {c.name: c.value for c in cabecera},
        "pasos": pasos,
        "bytes": len(contenido),
    }


# --- El mismo entrenamiento para la API de Garmin Connect --------------------
# Los identificadores siguen los del módulo garminconnect.workout.

ID_DEPORTE_CARRERA = 1
ID_PASO_INTERVALO = 3
ID_CONDICION_DISTANCIA = 3  # ojo: el 1 es lap.button, no distancia
ID_OBJETIVO_VELOCIDAD = 5


def workout_json(pasos: pd.DataFrame, nombre: str, segundos_estimados: float) -> dict:
    """
    Arma el payload de entrenamiento para la API de Garmin Connect.

    `ID_CONDICION_DISTANCIA = 3` no es negociable: en la primera subida real se
    usó el 1, que es la constante que parece obvia en `garminconnect.workout`, y
    Garmin lo devolvió convertido en `lap.button` — los pasos quedaron esperando
    que el corredor apretara el botón de vuelta en vez de avanzar solos a los
    12 km.
    """
    pasos_json = []

    for orden, paso in enumerate(pasos.itertuples(), start=1):
        pasos_json.append(
            {
                "type": "ExecutableStepDTO",
                "stepOrder": orden,
                "stepType": {
                    "stepTypeId": ID_PASO_INTERVALO,
                    "stepTypeKey": "interval",
                    "displayOrder": ID_PASO_INTERVALO,
                },
                "endCondition": {
                    "conditionTypeId": ID_CONDICION_DISTANCIA,
                    "conditionTypeKey": "distance",
                    "displayOrder": ID_CONDICION_DISTANCIA,
                    "displayable": True,
                },
                "endConditionValue": float(paso.km * 1000),
                "targetType": {
                    "workoutTargetTypeId": ID_OBJETIVO_VELOCIDAD,
                    "workoutTargetTypeKey": "speed.zone",
                    "displayOrder": ID_OBJETIVO_VELOCIDAD,
                },
                "targetValueOne": round(1000 / 60 / paso.ritmo_max, 3),
                "targetValueTwo": round(1000 / 60 / paso.ritmo_min, 3),
                "description": paso.notas,
            }
        )

    deporte = {
        "sportTypeId": ID_DEPORTE_CARRERA,
        "sportTypeKey": "running",
        "displayOrder": 1,
    }

    return {
        "workoutName": nombre,
        "description": "Estrategia generada por Stamina.AI",
        "sportType": deporte,
        "estimatedDurationInSecs": int(segundos_estimados),
        "workoutSegments": [{"segmentOrder": 1, "sportType": deporte, "workoutSteps": pasos_json}],
    }
