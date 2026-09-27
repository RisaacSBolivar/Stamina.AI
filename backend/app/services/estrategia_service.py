"""
De una ruta .GPX a la respuesta completa de estrategia.

La respuesta lleva siempre las señales de capacidad (`horas_`, `modelo_nombre_`,
`habilidad_esperada_` y el resultado de consultar `reglas`), para que la
interfaz **nunca tenga que inferir** si la estrategia está personalizada o si es
ritmo constante, ni por qué.

Y lleva también lo que hace falta para llevarla al reloj —los pasos compilados y
el `.FIT` ya generado—, porque la API no guarda la estrategia: no hay una
segunda petición que pueda ir a buscarla.
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.core.errors import ArchivoInvalido
from app.core.logging import get_logger
from stamina_core import (
    EstrategiaPipeline,
    compilar_pasos,
    compilar_workout_fit,
    consultar_capacidad,
    procesar_gpx,
    workout_json,
)

log = get_logger(__name__)

# Lo que se puede afirmar del archivo generado. Viaja en la respuesta para que
# la interfaz no tenga que acordarse de ponerlo.
AVISO_RELOJ = (
    "El archivo está verificado en formato (se relee con fitparse), Garmin "
    "Connect acepta la subida por API y el entrenamiento se ha probado en un "
    "reloj físico."
)


@dataclass
class Estrategia:
    """Todo lo que sale de un cálculo, antes de convertirlo en respuesta."""

    ruta: pd.DataFrame
    tabla_km: pd.DataFrame
    capacidad: dict[str, Any]
    nombre_ruta: str
    tiempo_objetivo_h: float
    temperatura_c: float
    modelo: str
    horas: float
    habilidad_esperada: float

    @property
    def km_totales(self) -> float:
        return float(self.ruta["dist_km"].max())

    @property
    def segundos_estimados(self) -> float:
        return float(self.ruta["tiempo_split_min"].sum() * 60)

    @property
    def nombre_entrenamiento(self) -> str:
        """
        El nombre que verá el reloj.

        El campo del `.FIT` son 24 bytes con su terminador, o sea 23 usables, y
        el sufijo de horas se lleva tres. Se corta por separador cuando se puede,
        para no dejar nombres partidos a media palabra («athens_maratho»).
        """
        sufijo = f" {self.tiempo_objetivo_h:.0f}h"
        disponible = 23 - len(sufijo)

        nombre = self.nombre_ruta.strip()
        if len(nombre) > disponible:
            recorte = nombre[:disponible]
            # Si hay un separador en la segunda mitad, se corta ahí.
            corte = max(recorte.rfind(c) for c in " _-")
            nombre = recorte[:corte] if corte > disponible // 2 else recorte

        return f"{nombre.rstrip(' _-')}{sufijo}"


def perfil_de_gpx(contenido: bytes, nombre: str) -> pd.DataFrame:
    """Lee el .GPX y devuelve el perfil en tramos de 100 m."""
    try:
        perfil = procesar_gpx(contenido)
    except Exception as error:
        raise ArchivoInvalido(
            f"No pude leer «{nombre}» como .GPX: {error}",
            details={"archivo": nombre},
        ) from error

    if len(perfil) < 10:
        raise ArchivoInvalido(
            f"«{nombre}» tiene solo {len(perfil)} tramos de 100 m. "
            "Hace falta una ruta de al menos 1 km.",
            details={"archivo": nombre, "tramos": len(perfil)},
        )
    return perfil


def calcular(
    pipeline: EstrategiaPipeline,
    perfil: pd.DataFrame,
    tiempo_objetivo_h: float,
    temperatura_c: float,
    nombre_ruta: str,
) -> Estrategia:
    """Corre la predicción y empaqueta todo lo que la interfaz necesita."""
    t0 = time.perf_counter()
    ruta = pipeline.predecir_ruta(perfil, tiempo_objetivo_h, temperatura_c)
    tabla = pipeline.tabla_km(ruta)

    km = float(ruta["dist_km"].max())
    capacidad = consultar_capacidad(pipeline.horas_, km, pipeline.reglas)

    log.info(
        "Estrategia calculada",
        extra={
            "km": round(km, 1),
            "tiempo_objetivo_h": tiempo_objetivo_h,
            "modelo": pipeline.modelo_nombre_,
            "personalizada": capacidad["personalizada"],
            "segundos": round(time.perf_counter() - t0, 3),
        },
    )

    return Estrategia(
        ruta=ruta,
        tabla_km=tabla,
        capacidad=capacidad,
        nombre_ruta=nombre_ruta,
        tiempo_objetivo_h=float(tiempo_objetivo_h),
        temperatura_c=float(temperatura_c),
        modelo=pipeline.modelo_nombre_,
        horas=float(pipeline.horas_),
        habilidad_esperada=float(pipeline.habilidad_esperada_),
    )


def pasos_a_lista(pasos: pd.DataFrame) -> list[dict]:
    """Los pasos compilados, con tipos nativos para JSON."""
    return [
        {
            "km_inicio": int(p.km_inicio),
            "km_fin": int(p.km_fin),
            "km": float(p.km),
            "zona": str(p.zona),
            "ritmo_min": float(p.ritmo_min),
            "ritmo_max": float(p.ritmo_max),
            "fc_min": float(p.fc_min),
            "fc_max": float(p.fc_max),
            "minutos": float(p.minutos),
            "nombre": str(p.nombre),
            "notas": str(p.notas),
        }
        for p in pasos.itertuples()
    ]


def a_respuesta(estrategia: Estrategia) -> dict:
    """
    La estrategia como diccionario para la API.

    `altimetria` va aparte de `tabla_km` a propósito: la gráfica del frontend
    necesita el perfil en tramos de 100 m para que la línea de elevación salga
    suave, mientras que el ritmo se lee por kilómetro.
    """
    ruta, tabla = estrategia.ruta, estrategia.tabla_km
    pipeline_indicadores = EstrategiaPipeline.indicadores(ruta)

    pasos = compilar_pasos(tabla)
    nombre = estrategia.nombre_entrenamiento
    contenido_fit = compilar_workout_fit(pasos, nombre)

    return {
        "ruta": {
            "nombre": estrategia.nombre_ruta,
            "km_totales": round(estrategia.km_totales, 2),
            "tramos": len(ruta),
        },
        "entrada": {
            "tiempo_objetivo_h": estrategia.tiempo_objetivo_h,
            "temperatura_c": estrategia.temperatura_c,
        },
        "capacidad": estrategia.capacidad,
        "indicadores": pipeline_indicadores,
        "tabla_km": [
            {
                "km": int(fila.km),
                "ritmo_objetivo": float(fila.ritmo_objetivo),
                "fc_objetivo": float(fila.fc_objetivo),
                "pendiente": float(fila.pendiente),
                "elevacion": float(fila.elevacion),
                "zona": str(fila.zona),
                "tiempo_min": float(fila.tiempo_min),
                "tiempo_acum_min": float(fila.tiempo_acum_min),
            }
            for fila in tabla.itertuples()
        ],
        "altimetria": [
            {"dist_km": round(float(d), 3), "elevacion": float(e)}
            for d, e in zip(ruta["dist_km"], ruta["elev"], strict=True)
        ],
        "reparto_zonas": (ruta["zona"].value_counts(normalize=True).mul(100).round(1).to_dict()),
        "entrenamiento": {
            "nombre": nombre,
            "pasos": pasos_a_lista(pasos),
            "segundos_estimados": estrategia.segundos_estimados,
            "payload_garmin": workout_json(pasos, nombre, estrategia.segundos_estimados),
            "aviso": AVISO_RELOJ,
        },
        "fit": {
            "nombre_archivo": nombre.replace(" ", "_").replace("/", "_") + ".fit",
            "contenido_base64": base64.b64encode(contenido_fit).decode("ascii"),
        },
    }
