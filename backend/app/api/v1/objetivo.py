"""
El selector de objetivo de carrera.

Cada opción se traduce a un `tiempo_objetivo_h` sugerido, y a nada más. No se
amplía la firma de `predecir_ruta()`: amortiguar o amplificar la curva cambiaría
la forma cuya habilidad se midió, y la habilidad reportada dejaría de aplicar.

La sugerencia es una calculadora sobre el historial del propio corredor, no una
salida del modelo, y la respuesta lo dice para que la interfaz no pueda
presentarla como tal.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import Config
from app.schemas.api import OpcionObjetivo, PeticionSugerencia, Sugerencia
from app.services import historial_service
from stamina_core import opciones, sugerir_tiempo_objetivo

router = APIRouter(prefix="/objetivo", tags=["objetivo"])


@router.get(
    "/opciones",
    response_model=list[OpcionObjetivo],
    summary="Las cuatro opciones del selector",
)
def listar_opciones() -> list[OpcionObjetivo]:
    """Para que la interfaz no escriba a mano ni las etiquetas ni los factores."""
    return [OpcionObjetivo(**opcion) for opcion in opciones()]


@router.post(
    "/sugerencia",
    response_model=Sugerencia,
    summary="Sugerir un tiempo objetivo a partir del historial",
)
def sugerencia(peticion: PeticionSugerencia, config: Config) -> Sugerencia:
    """
    Extrapola el mejor esfuerzo reciente del corredor con Riegel.

    Si no hay ninguna sesión de al menos 5 km, `tiempo_objetivo_h` viene en null
    y `motivo` lo explica: entonces el tiempo lo teclea el usuario. El campo
    `editable` es siempre verdadero.
    """
    historial = historial_service.desde_tramos(
        peticion.tramos.model_dump(), limite=config.max_tramos_historial
    )
    resultado = sugerir_tiempo_objetivo(historial.sesiones, peticion.km_objetivo, peticion.objetivo)
    return Sugerencia(**resultado)
