"""
Sesión con Garmin Connect: login, MFA y cierre.

Ver la cabecera de `app/services/garmin_service.py` para las garantías y el
riesgo residual. Resumen: nada se persiste, la sesión caduca en 15 minutos y
ninguna operación sobre la cuenta ocurre sin confirmación explícita.
"""

from __future__ import annotations

import contextlib

from fastapi import APIRouter, status

from app.api.deps import Config, ConGarmin, SesionesGarmin
from app.schemas.api import PeticionLoginGarmin, PeticionMfaGarmin, SesionGarmin
from app.services import garmin_service

# Todo el router depende de que este despliegue tenga Garmin encendido.
router = APIRouter(prefix="/garmin", tags=["garmin"], dependencies=[ConGarmin])

AVISO_CREDENCIALES = (
    "Tus credenciales no se guardan: ni en disco, ni en base de datos, ni en los "
    "logs. La sesión vive solo en memoria y caduca sola. Ninguna descarga ni "
    "subida ocurre sin que la confirmes."
)


def _respuesta(sesion, sesion_id: str, ttl: int) -> SesionGarmin:
    return SesionGarmin(
        sesion_garmin_id=sesion_id,
        autenticada=sesion.autenticada,
        requiere_mfa=sesion.estado_mfa is not None,
        correo=sesion.correo_enmascarado,
        caduca_en_segundos=ttl,
        aviso=AVISO_CREDENCIALES,
    )


@router.post(
    "/login",
    response_model=SesionGarmin,
    status_code=status.HTTP_201_CREATED,
    summary="Iniciar sesión en Garmin Connect",
)
def login(peticion: PeticionLoginGarmin, sesiones: SesionesGarmin, config: Config) -> SesionGarmin:
    """
    Primer paso. Si la cuenta tiene MFA, la respuesta trae `requiere_mfa=true`.

    La contraseña se usa para autenticar y se borra del cliente en cuanto el
    login termina. No se llama a `login(tokenstore)`, que es lo que guardaría un
    token en disco.
    """
    sesion = garmin_service.iniciar_sesion(peticion.correo, peticion.contrasena.get_secret_value())
    sesion_id = sesiones.guardar(sesion)
    return _respuesta(sesion, sesion_id, config.ttl_garmin_segundos)


@router.post(
    "/mfa",
    response_model=SesionGarmin,
    summary="Completar el login con el código de verificación",
)
def mfa(peticion: PeticionMfaGarmin, sesiones: SesionesGarmin, config: Config) -> SesionGarmin:
    """Segundo paso, solo si el login devolvió `requiere_mfa=true`."""
    sesion = sesiones.obtener(peticion.sesion_garmin_id)
    garmin_service.completar_mfa(sesion, peticion.codigo.get_secret_value())
    sesiones.reemplazar(peticion.sesion_garmin_id, sesion)
    return _respuesta(sesion, peticion.sesion_garmin_id, config.ttl_garmin_segundos)


@router.delete(
    "/sesion/{sesion_garmin_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cerrar la sesión de Garmin",
)
def cerrar(sesion_garmin_id: str, sesiones: SesionesGarmin) -> None:
    """
    Suelta el cliente autenticado antes de que caduque solo.

    Conviene llamarlo al terminar: cuanto menos viva una sesión contra una
    cuenta real, mejor.
    """
    # Cerrar algo que ya caducó o que nunca existió no es un error.
    with contextlib.suppress(Exception):
        garmin_service.cerrar_sesion(sesiones.obtener(sesion_garmin_id))
    sesiones.borrar(sesion_garmin_id)
