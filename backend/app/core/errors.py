"""
Errores de dominio, con su código HTTP y su identificador estable.

Cada clase lleva `status_code` y `code` como atributos de clase, y un único
manejador los serializa todos como `{"error": {"code", "message", "details"}}`.
Así el frontend distingue casos por `code` y no parseando el mensaje.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse


class StaminaError(Exception):
    """Raíz de todos los errores propios."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "stamina_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


# --- La regla de capacidad --------------------------------------------------


class ReglasNoDisponibles(StaminaError):
    """No se pudo cargar `reglas.json`. Sin la regla no se sabe qué modelo entrenar."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "reglas_no_disponibles"


# --- Entrada del usuario -----------------------------------------------------


class ArchivoInvalido(StaminaError):
    """El archivo no se pudo leer o no pasó el control de calidad."""

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "archivo_invalido"


class FormatoNoSoportado(StaminaError):
    """
    Formato que el pipeline no sabe leer.

    Hoy es el caso de `.TCX`: el diseño de solución lo menciona, pero no existe
    parser en ninguna parte del proyecto. Se dice claramente en vez de fingir.
    """

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "formato_no_soportado"


class HistorialInsuficiente(StaminaError):
    """Ningún archivo del historial sobrevivió al control de calidad."""

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "historial_insuficiente"


class RecursoNoEncontrado(StaminaError):
    """El identificador no existe o su sesión ya caducó."""

    status_code = status.HTTP_404_NOT_FOUND
    code = "recurso_no_encontrado"


class ConfirmacionRequerida(StaminaError):
    """
    Falta la confirmación explícita del usuario.

    Ninguna operación que toque la cuenta de Garmin —descargar el historial o
    subir un entrenamiento— se dispara sin `confirmado=true`. Nunca es automática.
    """

    status_code = status.HTTP_428_PRECONDITION_REQUIRED
    code = "confirmacion_requerida"


# --- Garmin ------------------------------------------------------------------


class GarminError(StaminaError):
    """Fallo hablando con Garmin Connect (API no oficial, puede cambiar sin aviso)."""

    status_code = status.HTTP_502_BAD_GATEWAY
    code = "garmin_error"


class GarminAutenticacion(GarminError):
    """Credenciales rechazadas, o sesión caducada."""

    status_code = status.HTTP_401_UNAUTHORIZED
    code = "garmin_autenticacion"


class GarminNoDisponible(StaminaError):
    """
    La conexión con Garmin está apagada en este despliegue.

    Necesita una sesión viva en el servidor entre peticiones (login, MFA y una
    descarga de minutos), y un despliegue sin estado no la garantiza. En local
    funciona; en la versión publicada se suben los .FIT a mano.
    """

    status_code = status.HTTP_403_FORBIDDEN
    code = "garmin_no_disponible"


class GarminLimite(GarminError):
    """
    Garmin no deja pasar ahora: 429, o rechazo previo a comprobar credenciales.

    Se agrupan porque para quien lo usa la acción es la misma —esperar y, si
    corre prisa, subir los .FIT a mano— y porque distinguirlo desde fuera no
    siempre se puede: la librería prueba varias vías y solo reporta la última.
    """

    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "garmin_limite"


def register_exception_handlers(app: FastAPI) -> None:
    """Un solo manejador para toda la jerarquía."""

    @app.exception_handler(StaminaError)
    async def _manejar(_: Request, exc: StaminaError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            },
        )
