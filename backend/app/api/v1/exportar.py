"""
Subida del entrenamiento a Garmin Connect.

La descarga del `.FIT` ya no es una ruta: el archivo viaja dentro de la respuesta
de `POST /estrategia` (son unos cientos de bytes) y el navegador lo guarda sin
volver a preguntar. Lo que queda aquí es la subida a la cuenta, que es una
acción **separada y explícita**: exige `confirmado=true` en cada petición y,
como cualquier cosa de Garmin, solo existe donde hay sesión en el servidor.
"""

from __future__ import annotations

import pandas as pd
from fastapi import APIRouter

from app.api.deps import ConGarmin, SesionesGarmin
from app.core.errors import ConfirmacionRequerida
from app.schemas.api import PeticionSubidaGarmin, ResultadoSubida
from app.services import garmin_service
from app.services.estrategia_service import AVISO_RELOJ
from stamina_core import workout_json

router = APIRouter(prefix="/exportar", tags=["exportar"])


@router.post(
    "/garmin",
    response_model=ResultadoSubida,
    summary="Subir el entrenamiento a la cuenta de Garmin",
    dependencies=[ConGarmin],
)
def subir_a_garmin(peticion: PeticionSubidaGarmin, sesiones: SesionesGarmin) -> ResultadoSubida:
    """
    Sube el entrenamiento. Requiere confirmación explícita en cada llamada.

    El JSON de Garmin se vuelve a construir aquí a partir de los pasos, en vez de
    aceptar el que mande el cliente: así el `conditionTypeId` lo pone siempre el
    servidor. La respuesta incluye lo que Garmin interpretó de cada paso. Si
    `todos_por_distancia` saliera falso, los pasos estarían esperando el botón de
    vuelta en vez de avanzar solos: es exactamente el bug que produjo usar
    `conditionTypeId = 1` en lugar del 3.
    """
    if not peticion.confirmado:
        raise ConfirmacionRequerida(
            "Hace falta confirmación explícita para subir el entrenamiento a tu cuenta de Garmin.",
            details={"campo": "confirmado"},
        )

    sesion = sesiones.obtener(peticion.sesion_garmin_id)

    entrenamiento = peticion.entrenamiento
    pasos = pd.DataFrame([paso.model_dump() for paso in entrenamiento.pasos])
    payload = workout_json(pasos, entrenamiento.nombre, entrenamiento.segundos_estimados)

    resultado = garmin_service.subir_entrenamiento(sesion, payload)
    return ResultadoSubida(**resultado, aviso=AVISO_RELOJ)
