"""
Fixtures compartidas.

Los tests de la fase 1 comparan contra los números que dejó impresos el
notebook de investigación (`notebook_StaminAI.ipynb`, que vive fuera de este
repositorio) en su última corrida. No se inventan tolerancias: la
estrategia de Atenas se reproduce al centésimo porque el pipeline es
determinista (semilla 42, sin reentrenar nada).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# El paquete vive en backend/, junto a este directorio de tests.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stamina_core import Rutas  # noqa: E402

# Una copia mínima de lo que dejó el notebook, con su misma disposición:
# `data/procesado/splits.parquet`, el `.GPX` de Atenas y las dos salidas del
# entrenamiento de referencia. No hay `dataset.parquet` (se reconstruye desde
# `splits`) ni ningún `.FIT` real: esos son datos personales y no se versionan.
DATOS_DE_PRUEBA = Path(__file__).resolve().parent / "datos"


@pytest.fixture(scope="session")
def rutas() -> Rutas:
    """Las carpetas de datos de prueba, en `tests/datos/`."""
    return Rutas(raiz=DATOS_DE_PRUEBA)


@pytest.fixture(scope="session")
def fits_sinteticos(tmp_path_factory) -> list[str]:
    """
    Dieciséis carreras `.FIT` fabricadas, sin GPS (ver `fit_sintetico.py`).

    Sustituyen a los `.FIT` reales en todo lo que prueba el parseo y la subida.
    La cuarta no trae altitud, así que el lote tiene un descarte de verdad.
    """
    from .fit_sintetico import escribir_historial

    return escribir_historial(tmp_path_factory.mktemp("fit"))


# --- El historial del notebook, compartido por las dos baterías -------------


@pytest.fixture(scope="session")
def splits(rutas: Rutas):
    """Los 15 959 tramos de 100 m del historial del autor (`tests/datos/`)."""
    import pandas as pd

    if not rutas.splits.exists():
        pytest.skip(f"Falta la caché procesada en {rutas.splits}")
    return pd.read_parquet(rutas.splits)


@pytest.fixture(scope="session")
def sesiones(splits):
    from stamina_core import perfil_temporal

    return perfil_temporal(splits)


@pytest.fixture(scope="session")
def pool(sesiones) -> list[str]:
    """
    El conjunto de entrenamiento del notebook (sección 1.4).

    Se apartan la primera y la última maratón, más las cuatro carreras de 10-40 km
    más recientes. Queda determinista a partir de sesiones.parquet.
    """
    maratones = sesiones[sesiones["km"] > 40].sort_values("fecha")["actividad"].tolist()
    prueba = [maratones[0], maratones[-1]] + (
        sesiones[(sesiones["km"] > 10) & (sesiones["km"] <= 40)]
        .sort_values("fecha")
        .tail(4)["actividad"]
        .tolist()
    )
    return [a for a in sesiones["actividad"] if a not in prueba]


@pytest.fixture(scope="session")
def pipeline(rutas: Rutas):
    """
    El pipeline entrenado que dejó el notebook, cargado desde el módulo nuevo.

    Es de alcance `session` porque cargar 24 MB de RandomForest tarda lo suyo y
    el objeto es inmutable para lo que hacen los tests.
    """
    from stamina_core import EstrategiaPipeline

    if not (rutas.modelo / "metadata.joblib").exists():
        pytest.skip(f"No está el artefacto en {rutas.modelo}")

    return EstrategiaPipeline.cargar(rutas.modelo, verboso=False)


# --- Valores de referencia de la corrida del notebook -----------------------
# Se citan secciones del notebook y no números de celda: esos cambian en cuanto
# se añade o se quita una.

# Secciones 5.1 y 7: primeros cinco kilómetros de la estrategia de Atenas,
# con 4.0 h de objetivo y 18 °C.
TIEMPO_OBJETIVO_H = 4.0
TEMPERATURA_C = 18.0

RITMO_PRIMEROS_5_KM = [5.06, 4.87, 4.85, 4.86, 4.86]
FC_PRIMEROS_5_KM = [150.02, 155.51, 156.72, 156.11, 155.77]
ZONA_PRIMEROS_5_KM = ["Crucero"] * 5

# Sección 1.1 / metadatos.json
ACTIVIDADES_ESPERADAS = 460
SPLITS_ESPERADOS = 15_959
ARCHIVOS_FIT_ESPERADOS = 492
HORAS_TOTALES_ESPERADAS = 137.4

# Sección 5.1: el artefacto guardado
MODELO_ESPERADO = "RandomForest"
HORAS_ARTEFACTO = 124.7
HABILIDAD_ARTEFACTO = 0.303

# Sección 7.1: el entrenamiento estructurado ya verificado
PASOS_ESPERADOS = 7
DISTANCIAS_PASOS_M = [12000.0, 4000.0, 3000.0, 5000.0, 4000.0, 3000.0, 12000.0]
