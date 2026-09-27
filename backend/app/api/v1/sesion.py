"""
Olvidar lo que quede en el servidor, cuando la persona decide salir.

El historial y la estrategia nunca se guardan en el servidor: viven en el
navegador y se van con él. Lo único que puede quedar aquí es de Garmin —la
sesión autenticada y una descarga, que retiene el historial reunido hasta que el
navegador lo recoge—, y son datos personales, así que cuando alguien dice «borra
mis datos» se sueltan ahora y no cuando caduquen.
"""

from __future__ import annotations

import contextlib

from fastapi import APIRouter, status

from app.api.deps import SesionesGarmin, Tareas
from app.schemas.api import PeticionOlvidar, ResultadoOlvidar
from app.services import descarga_service, garmin_service

router = APIRouter(prefix="/sesion", tags=["sesion"])


@router.post(
    "/olvidar",
    response_model=ResultadoOlvidar,
    status_code=status.HTTP_200_OK,
    summary="Soltar de memoria la sesión y la descarga de Garmin",
)
def olvidar(
    peticion: PeticionOlvidar,
    sesiones: SesionesGarmin,
    tareas: Tareas,
) -> ResultadoOlvidar:
    """
    Suelta todo lo que el cliente diga tener.

    Idempotente a propósito: borrar algo que ya caducó, o que nunca existió, no
    es un error. Lo que importa es que al volver no quede nada, no informar de
    qué había. Por eso tampoco valida los identificadores: si no existen, no
    pasa nada.
    """
    borrados: list[str] = []

    if peticion.sesion_garmin_id:
        # Sostiene un cliente autenticado contra una cuenta real, así que se
        # cierra antes de soltarla, igual que `DELETE /garmin/sesion/{id}`.
        with contextlib.suppress(Exception):
            garmin_service.cerrar_sesion(sesiones.obtener(peticion.sesion_garmin_id))
        sesiones.borrar(peticion.sesion_garmin_id)
        borrados.append("sesion_garmin")

    if peticion.tarea_id:
        # Si seguía descargando, que pare; y lo reunido se suelta con la tarea.
        with contextlib.suppress(Exception):
            descarga_service.pedir_cancelacion(peticion.tarea_id, tareas)
        tareas.borrar(peticion.tarea_id)
        borrados.append("descarga")

    return ResultadoOlvidar(borrados=borrados)
