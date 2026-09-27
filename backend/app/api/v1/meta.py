"""Salud y capacidades del servicio."""

from __future__ import annotations

import pandas as pd
import sklearn
from fastapi import APIRouter

from app.api.deps import Config, ServicioPipeline, SesionesGarmin, Tareas
from app.schemas.api import Salud

router = APIRouter(tags=["meta"])


@router.get("/health", response_model=Salud, summary="Estado del servicio y de la regla")
def salud(
    servicio: ServicioPipeline,
    config: Config,
    garmin: SesionesGarmin,
    tareas: Tareas,
) -> Salud:
    """
    Dice si la regla de capacidad está cargada, si Garmin está disponible y con
    qué versiones corre. Si algo falla al desplegar, lo delata en un vistazo.
    """
    info = servicio.info()
    return Salud(
        estado="ok" if info["cargadas"] else "degradado",
        app=config.app_name,
        version="0.1.0",
        entorno=config.environment,
        reglas=info,
        garmin_habilitado=config.garmin_habilitado,
        dependencias={"pandas": pd.__version__, "scikit-learn": sklearn.__version__},
        sesiones_activas={"garmin": len(garmin), "descargas": len(tareas)},
    )
