"""
Del historial subido a horas acumuladas y dataset de modelado.

Las horas son el insumo de la regla de capacidad, así que este módulo es el que
decide qué puede ofrecerle el sistema a cada persona. De ahí que el control de
calidad se reporte entero: si a alguien se le cayeron 30 archivos, tiene derecho
a saber por qué antes de leer un disclaimer sobre su historial.

**El servidor no guarda el historial.** Los `.FIT` se parsean a tramos de 100 m
(`a_tramos`) y esos tramos vuelven al navegador, que los manda de nuevo en cada
cálculo (`desde_tramos`). Así la API no tiene estado, los `.FIT` se pueden subir
por tandas —con progreso y sin ninguna petición enorme— y el historial no se
queda en ningún servidor. Los tramos no llevan coordenadas: velocidad, pulso, cadencia,
altitud, temperatura, tiempo y fecha por cada 100 m.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from app.core.errors import ArchivoInvalido, FormatoNoSoportado, HistorialInsuficiente
from app.core.logging import get_logger
from stamina_core import construir_dataset, parsear_lote, perfil_temporal

log = get_logger(__name__)

EXTENSIONES_ACEPTADAS = {".fit"}

# Las columnas de los tramos, en el orden en que las deja `procesar_fit` (y el
# de `splits.parquet`). Es el contrato con el navegador: lo que viaja y vuelve.
COLUMNAS_TRAMOS = [
    "split",
    "v",
    "fc",
    "cadencia",
    "elev",
    "temperatura",
    "t_fin",
    "n_registros",
    "actividad",
    "fecha",
]
COLUMNAS_TEXTO = {"actividad", "fecha"}
COLUMNAS_ENTERAS = {"split", "n_registros"}


@dataclass
class Historial:
    """El historial de un usuario, ya procesado y listo para entrenar."""

    splits: pd.DataFrame
    sesiones: pd.DataFrame
    dataset: pd.DataFrame
    control_calidad: dict[str, int] = field(default_factory=dict)

    @property
    def horas(self) -> float:
        return float(self.sesiones["minutos"].sum() / 60)

    @property
    def n_sesiones(self) -> int:
        return int(len(self.sesiones))

    @property
    def km_totales(self) -> float:
        return float(self.sesiones["km"].sum())

    @property
    def rango_fechas(self) -> tuple[str, str]:
        return str(self.sesiones["fecha"].min()), str(self.sesiones["fecha"].max())

    def resumen(self) -> dict:
        desde, hasta = self.rango_fechas
        return {
            "horas": round(self.horas, 2),
            "sesiones": self.n_sesiones,
            "km_totales": round(self.km_totales, 1),
            "desde": desde,
            "hasta": hasta,
        }


def validar_extension(nombre: str) -> None:
    """
    Rechaza lo que el pipeline no sabe leer, diciendo por qué.

    El `.TCX` aparece en el diseño de solución, pero no hay parser en ninguna
    parte del proyecto. Es más honesto devolverlo con el motivo que aceptarlo y
    fallar en silencio.
    """
    extension = Path(nombre).suffix.lower()

    if extension in EXTENSIONES_ACEPTADAS:
        return

    if extension == ".tcx":
        raise FormatoNoSoportado(
            "Todavía no hay lector de .TCX. El pipeline trabaja con .FIT, que es "
            "lo que exporta Garmin en formato original.",
            details={"archivo": nombre, "aceptados": sorted(EXTENSIONES_ACEPTADAS)},
        )

    raise FormatoNoSoportado(
        f"«{nombre}» no es un archivo de actividad .FIT.",
        details={"archivo": nombre, "aceptados": sorted(EXTENSIONES_ACEPTADAS)},
    )


def procesar_subida(archivos: list[tuple[str, bytes]], n_jobs: int | None = None) -> Historial:
    """
    Parsea los .FIT subidos y arma el historial.

    Cada archivo se identifica por su nombre sin extensión. Si el nombre no
    sigue la convención `AAAA-MM-DD_<id>.fit`, la fecha se lee de dentro del
    propio archivo (ver `stamina_core.ingesta._fecha_de`): sin eso, el orden
    cronológico —y por tanto las horas acumuladas— saldría mal.
    """
    if not archivos:
        raise ArchivoInvalido("No llegó ningún archivo.")

    tablas: list[pd.DataFrame] = []
    motivos: dict[str, int] = {}
    por_parsear: list[tuple[str, bytes]] = []

    for nombre, contenido in archivos:
        validar_extension(nombre)

        if not contenido:
            motivos["archivo vacío"] = motivos.get("archivo vacío", 0) + 1
            continue

        por_parsear.append((nombre, contenido))

    # `parsear_lote` reparte el trabajo entre procesos cuando hay bastantes
    # archivos y se queda secuencial cuando no compensa arrancar el pool. El
    # recuento de motivos se lleva aquí, que es donde se sabe qué significa cada
    # uno para el usuario.
    for motivo, tramos in parsear_lote(por_parsear, n_jobs=n_jobs):
        motivos[motivo] = motivos.get(motivo, 0) + 1
        if motivo == "ok" and tramos is not None:
            tablas.append(tramos)

    if not tablas:
        raise HistorialInsuficiente(
            "Ningún archivo pasó el control de calidad. El pipeline necesita "
            "sesiones de carrera continua con altitud, frecuencia cardíaca y "
            "cadencia grabadas.",
            details={"control_calidad": motivos, "archivos": len(archivos)},
        )

    historial = desde_splits(pd.concat(tablas, ignore_index=True), motivos)

    log.info(
        "Historial procesado",
        extra={
            "archivos": len(archivos),
            "actividades": historial.n_sesiones,
            "horas": round(historial.horas, 1),
            "control_calidad": motivos,
        },
    )
    return historial


def desde_splits(splits: pd.DataFrame, control_calidad: dict | None = None) -> Historial:
    """
    Arma un `Historial` a partir de tramos ya parseados.

    Dos normalizaciones, las dos por la misma razón —que el resultado no dependa
    de cómo llegaron los archivos—:

    - Un mismo archivo subido dos veces, o en dos tandas, contaría doble en las
      horas, y las horas son justo lo que consulta la regla de capacidad.
    - Se ordena por actividad y tramo, como el historial del notebook. Si no, el
      orden de subida (el del navegador, o el de las tandas) cambiaría el orden
      de las filas y con él el muestreo del Random Forest.
    """
    splits = (
        splits.drop_duplicates(subset=["actividad", "split"], keep="first")
        .sort_values(["actividad", "split"], kind="stable")
        .reset_index(drop=True)
    )
    return Historial(
        splits=splits,
        sesiones=perfil_temporal(splits),
        dataset=construir_dataset(splits),
        control_calidad=control_calidad or {},
    )


def a_tramos(splits: pd.DataFrame) -> dict[str, list]:
    """Los tramos en columnas, listos para JSON. Los NaN viajan como null."""
    tramos = {}
    for columna in COLUMNAS_TRAMOS:
        serie = splits[columna]
        if columna in COLUMNAS_TEXTO:
            tramos[columna] = serie.astype(str).tolist()
        elif columna in COLUMNAS_ENTERAS:
            tramos[columna] = serie.astype(int).tolist()
        else:
            tramos[columna] = [None if pd.isna(x) else float(x) for x in serie]
    return tramos


def desde_tramos(
    tramos: dict[str, list],
    control_calidad: dict | None = None,
    limite: int | None = None,
) -> Historial:
    """El camino de vuelta: de las columnas que manda el navegador a un `Historial`."""
    n_tramos = len(tramos["split"])
    if limite is not None and n_tramos > limite:
        raise ArchivoInvalido(f"El historial trae {n_tramos} tramos; el máximo es {limite}.")
    datos = {}
    for columna in COLUMNAS_TRAMOS:
        valores = tramos[columna]
        if columna in COLUMNAS_TEXTO:
            datos[columna] = pd.Series(valores, dtype="str")
        elif columna in COLUMNAS_ENTERAS:
            datos[columna] = pd.Series(valores, dtype="int64")
        else:
            datos[columna] = pd.Series(
                [np.nan if x is None else x for x in valores], dtype="float64"
            )
    splits = pd.DataFrame(datos)

    if splits.empty:
        raise HistorialInsuficiente("El historial llegó vacío: no hay ningún tramo.")
    return desde_splits(splits, control_calidad)
