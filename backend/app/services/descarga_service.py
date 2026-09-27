"""
La descarga de Garmin como tarea con progreso.

Bajar el historial tarda entre diez y veinte minutos: hay 0.6 s de pausa
obligatoria por actividad contra el límite de peticiones de Garmin, más lo que
tarde cada archivo. Resolverlo en una sola petición HTTP tenía dos problemas: el
usuario veía un botón en «Descargando…» sin saber si la aplicación seguía viva, y
la petición quedaba abierta un cuarto de hora.

Así que la petición arranca la tarea y se va; el progreso se consulta aparte. El
porcentaje es real, no decorativo: `objetivo_horas` se conoce antes de empezar.

Lo que no cambia: nada se guarda en disco y la descarga sigue necesitando
confirmación explícita. El historial reunido se queda en la propia
tarea hasta que el navegador lo recoge en tramos; `POST /sesion/olvidar` lo
suelta. Todo esto necesita un proceso vivo entre peticiones, y por eso Garmin
solo funciona donde `garmin_habilitado` está encendido.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from app.core.errors import StaminaError
from app.core.logging import get_logger
from app.services import garmin_service, historial_service
from app.services.almacen import AlmacenTTL

log = get_logger(__name__)

Estado = Literal["en_curso", "terminada", "fallida", "cancelada"]


@dataclass
class TareaDescarga:
    """Lo que se sabe de una descarga en marcha."""

    objetivo_horas: float
    estado: Estado = "en_curso"
    actividades: int = 0
    horas: float = 0.0
    iniciada_en: float = field(default_factory=time.monotonic)

    historial: Any = None
    error: str | None = None
    codigo_error: str | None = None

    # El interruptor que mira el hilo. Un `Event` y no un bool porque lo
    # escribe el hilo de la peticion HTTP y lo lee el de la descarga.
    cancelacion: threading.Event = field(default_factory=threading.Event)

    @property
    def segundos(self) -> float:
        return round(time.monotonic() - self.iniciada_en, 1)

    @property
    def porcentaje(self) -> float:
        """Sobre las horas pedidas, que se conocen de antemano."""
        if self.objetivo_horas <= 0:
            return 0.0
        return round(min(100.0, 100 * self.horas / self.objetivo_horas), 1)


def lanzar(sesion: Any, objetivo_horas: float, tareas: AlmacenTTL) -> str:
    """
    Arranca la descarga en segundo plano y devuelve el identificador a consultar.

    El hilo se queda con la sesión por referencia, así que una descarga larga no
    se corta porque la sesión caduque en el almacén a mitad.
    """
    tarea = TareaDescarga(objetivo_horas=objetivo_horas)
    tarea_id = tareas.guardar(tarea)

    hilo = threading.Thread(
        target=_ejecutar,
        args=(tarea_id, tarea, sesion, tareas),
        name=f"descarga-garmin-{tarea_id}",
        daemon=True,
    )
    hilo.start()
    return tarea_id


def pedir_cancelacion(tarea_id: str, tareas: AlmacenTTL) -> TareaDescarga:
    """
    Marca la descarga para que pare, y devuelve la tarea ya en «cancelada».

    El estado se cambia aqui sin esperar al hilo: la interfaz tiene que
    responder al instante, y el hilo tardara como mucho una actividad en darse
    cuenta. Cancelar algo que ya termino no hace nada, que es lo correcto.
    """
    tarea: TareaDescarga = tareas.obtener(tarea_id)
    if tarea.estado == "en_curso":
        tarea.cancelacion.set()
        tarea.estado = "cancelada"
        tareas.reemplazar(tarea_id, tarea)
    return tarea


def _ejecutar(tarea_id: str, tarea: TareaDescarga, sesion: Any, tareas: AlmacenTTL) -> None:
    def anotar(actividades: int, horas: float) -> None:
        tarea.actividades = actividades
        tarea.horas = round(horas, 2)
        # Renueva la caducidad: mientras la descarga avance, la tarea sigue viva.
        tareas.reemplazar(tarea_id, tarea)

    try:
        splits, motivos = garmin_service.descargar_historial(
            sesion,
            tarea.objetivo_horas,
            progreso=anotar,
            cancelado=tarea.cancelacion.is_set,
        )
        # La cancelacion puede llegar justo cuando la descarga acaba de
        # terminar. En ese caso gana la persona: lo bajado se descarta.
        if tarea.cancelacion.is_set():
            raise garmin_service.DescargaCancelada

        tarea.historial = historial_service.desde_splits(splits, motivos)
        tarea.estado = "terminada"

    except garmin_service.DescargaCancelada:
        # No es un fallo: se para y no se guarda nada.
        tarea.estado = "cancelada"
    except StaminaError as error:
        tarea.estado = "fallida"
        tarea.error = error.message
        tarea.codigo_error = error.code
    except Exception as error:  # noqa: BLE001 - el hilo no puede dejar escapar nada
        tarea.estado = "fallida"
        tarea.error = "Algo falló durante la descarga."
        tarea.codigo_error = type(error).__name__
        log.exception("Descarga de Garmin fallida", extra={"tarea": tarea_id})

    tareas.reemplazar(tarea_id, tarea)
    log.info(
        "Descarga de Garmin terminada",
        extra={
            "tarea": tarea_id,
            "estado": tarea.estado,
            "actividades": tarea.actividades,
            "segundos": tarea.segundos,
        },
    )
