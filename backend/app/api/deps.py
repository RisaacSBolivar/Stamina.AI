"""
Dependencias compartidas de la API.

Se exportan como alias `Annotated` para que las firmas de los endpoints queden
cortas y legibles: `def endpoint(servicio: ServicioPipeline)`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.core.config import Settings, get_settings
from app.core.errors import GarminNoDisponible
from app.services.almacen import AlmacenTTL, sesiones_garmin, tareas
from app.services.pipeline_service import PipelineService


def obtener_servicio_pipeline(request: Request) -> PipelineService:
    """
    El servicio con la regla ya cargada.

    Normalmente lo crea el `lifespan` al arrancar. Si el entorno no lo ejecuta
    —hay runtimes sin servidor que no lo hacen—, se crea aquí en la primera
    petición: son unos KB y no se vuelve a leer mientras el proceso viva.
    """
    servicio = getattr(request.app.state, "pipelines", None)
    if servicio is None:
        servicio = PipelineService(get_settings().carpeta_modelo)
        servicio.cargar()
        request.app.state.pipelines = servicio
    return servicio


def obtener_sesiones_garmin() -> AlmacenTTL:
    return sesiones_garmin


def obtener_tareas() -> AlmacenTTL:
    return tareas


def exigir_garmin(config: Annotated[Settings, Depends(get_settings)]) -> None:
    """
    Corta cualquier ruta de Garmin si este despliegue no la tiene encendida.

    Garmin necesita una sesión viva en el servidor entre peticiones, y el
    despliegue sin estado no la garantiza. Mejor un 403 que lo diga que un
    login a medias que se pierde entre dos procesos.
    """
    if not config.garmin_habilitado:
        raise GarminNoDisponible(
            "La conexión con Garmin solo está disponible en la versión local de "
            "Stamina.AI. Exporta tus actividades desde Garmin Connect en formato "
            "original (.FIT) y súbelas como archivos."
        )


ServicioPipeline = Annotated[PipelineService, Depends(obtener_servicio_pipeline)]
SesionesGarmin = Annotated[AlmacenTTL, Depends(obtener_sesiones_garmin)]
Tareas = Annotated[AlmacenTTL, Depends(obtener_tareas)]
Config = Annotated[Settings, Depends(get_settings)]
ConGarmin = Depends(exigir_garmin)
