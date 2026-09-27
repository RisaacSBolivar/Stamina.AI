"""
Consulta de la regla de capacidad.

Este endpoint existe para que **ni el frontend ni ninguna otra parte del sistema
escriban el umbral en el código**. El resultado depende de las horas *y* de la
distancia objetivo, y la tabla cambiaría si se volviera a correr el notebook.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import ServicioPipeline
from app.schemas.api import Capacidad
from stamina_core import consultar_capacidad

router = APIRouter(tags=["capacidad"])


@router.get(
    "/capacidad",
    response_model=Capacidad,
    summary="Qué modelo asigna la regla para unas horas y una distancia",
)
def capacidad(
    servicio: ServicioPipeline,
    horas: float = Query(ge=0, le=100_000, description="Horas acumuladas de carrera"),
    km_objetivo: float = Query(gt=0, le=500, description="Distancia de la carrera objetivo"),
) -> Capacidad:
    """
    Devuelve el modelo asignado y, si la respuesta es ritmo constante, el motivo real.

    El motivo importa: para una carrera corta, "te faltan horas" sería falso. En
    el régimen corto ni con todo el historial medido se personaliza, así que el
    factor limitante es la distancia. Ver `regimen_fiable`.
    """
    return Capacidad(**consultar_capacidad(horas, km_objetivo, servicio.reglas))
