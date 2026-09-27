"""
Carga del historial: archivos subidos o descarga desde Garmin Connect.

El servidor **no se queda con el historial**. Los `.FIT` se procesan a tramos de
100 m y los tramos vuelven al navegador, que los manda de nuevo cuando los
necesita (resumen, sugerencia, estrategia). Por eso la subida se puede partir en
tandas —así hay progreso y ninguna petición es enorme— y ninguna petición depende
de que otra haya caído en el mismo proceso.
"""

from __future__ import annotations

from fastapi import APIRouter, File, UploadFile, status
from fastapi.concurrency import run_in_threadpool

from app.api.deps import Config, ConGarmin, ServicioPipeline, SesionesGarmin, Tareas
from app.core.errors import ArchivoInvalido, ConfirmacionRequerida
from app.schemas.api import (
    EstadoDescarga,
    HistorialProcesado,
    PeticionDescargaGarmin,
    PeticionResumen,
    ResumenHistorial,
)
from app.services import descarga_service, historial_service
from app.services.descarga_service import TareaDescarga
from stamina_core import consultar_capacidad

router = APIRouter(prefix="/historial", tags=["historial"])


def _procesado(historial) -> HistorialProcesado:
    return HistorialProcesado(
        tramos=historial_service.a_tramos(historial.splits),
        control_calidad=historial.control_calidad,
    )


@router.post(
    "/archivos",
    response_model=HistorialProcesado,
    summary="Procesar archivos .FIT del historial",
)
async def subir_archivos(
    config: Config,
    archivos: list[UploadFile] = File(description="Uno o más archivos .FIT"),
) -> HistorialProcesado:
    """
    Procesa los .FIT y devuelve el historial en tramos de 100 m, sin guardarlo.

    Si el historial no cabe en una petición, se sube por tandas y el navegador
    junta los tramos. El `.TCX` se rechaza con un 422 que lo explica: no hay
    lector en el proyecto.
    """
    if len(archivos) > config.max_archivos_historial:
        raise ArchivoInvalido(
            f"Demasiados archivos ({len(archivos)}). El máximo es {config.max_archivos_historial}.",
        )

    contenidos: list[tuple[str, bytes]] = []
    for archivo in archivos:
        historial_service.validar_extension(archivo.filename or "")
        datos = await archivo.read()
        if len(datos) > config.max_bytes_por_archivo:
            raise ArchivoInvalido(
                f"«{archivo.filename}» pesa más de "
                f"{config.max_bytes_por_archivo // (1024 * 1024)} MB.",
                details={"archivo": archivo.filename},
            )
        contenidos.append((archivo.filename or "sin_nombre.fit", datos))

    # Parsear es CPU pura y puede tardar minutos en una máquina pequeña. En el
    # bucle de eventos dejaría al servidor entero sin responder mientras tanto
    # (salud, progreso de Garmin, otras personas): con un solo proceso, como en
    # Render, eso es todo el servicio.
    procesado = await run_in_threadpool(
        historial_service.procesar_subida, contenidos, n_jobs=config.procesos_parseo
    )
    return _procesado(procesado)


@router.post(
    "/resumen",
    response_model=ResumenHistorial,
    summary="Horas, sesiones y capacidad de un historial procesado",
)
def resumir(
    peticion: PeticionResumen, servicio: ServicioPipeline, config: Config
) -> ResumenHistorial:
    """
    Lo que se le enseña al corredor en el paso 1: cuántas horas tiene, en cuántas
    sesiones, y —si se indica la distancia— qué le puede ofrecer la regla.
    """
    historial = historial_service.desde_tramos(
        peticion.tramos.model_dump(), limite=config.max_tramos_historial
    )
    capacidad = None
    if peticion.km_objetivo is not None:
        capacidad = consultar_capacidad(historial.horas, peticion.km_objetivo, servicio.reglas)
    return ResumenHistorial(**historial.resumen(), capacidad=capacidad)


# --- Garmin (solo donde hay estado en el servidor) ---------------------------


def _progreso(tarea_id: str, tarea: TareaDescarga) -> EstadoDescarga:
    """Traduce la tarea al contrato público, con el historial si ya terminó."""
    resultado = None
    if tarea.estado == "terminada" and tarea.historial is not None:
        resultado = _procesado(tarea.historial)

    return EstadoDescarga(
        tarea_id=tarea_id,
        estado=tarea.estado,
        actividades=tarea.actividades,
        horas=tarea.horas,
        objetivo_horas=tarea.objetivo_horas,
        porcentaje=tarea.porcentaje,
        segundos=tarea.segundos,
        resultado=resultado,
        error=tarea.error,
        codigo_error=tarea.codigo_error,
    )


@router.post(
    "/garmin",
    response_model=EstadoDescarga,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Arrancar la descarga del historial desde Garmin Connect",
    dependencies=[ConGarmin],
)
def descargar_de_garmin(
    peticion: PeticionDescargaGarmin,
    sesiones: SesionesGarmin,
    tareas: Tareas,
) -> EstadoDescarga:
    """
    Arranca la descarga y devuelve el identificador para seguirla.

    Devuelve 202 y no espera: reunir el historial lleva entre diez y veinte
    minutos, por la pausa obligatoria contra el límite de peticiones de Garmin.
    El progreso se consulta en `GET /historial/garmin/{tarea_id}`.

    Requiere `confirmado=true`: nunca se dispara sola. Lo descargado se parsea en
    memoria; no se guarda ningún archivo en el servidor.
    """
    if not peticion.confirmado:
        raise ConfirmacionRequerida(
            "Hace falta confirmación explícita para descargar el historial de tu cuenta de Garmin.",
            details={"campo": "confirmado"},
        )

    sesion = sesiones.obtener(peticion.sesion_garmin_id)
    tarea_id = descarga_service.lanzar(sesion, peticion.objetivo_horas, tareas)
    return _progreso(tarea_id, tareas.obtener(tarea_id))


@router.get(
    "/garmin/{tarea_id}",
    response_model=EstadoDescarga,
    summary="Consultar el progreso de una descarga",
    dependencies=[ConGarmin],
)
def progreso_de_garmin(tarea_id: str, tareas: Tareas) -> EstadoDescarga:
    """Cuántas actividades y horas lleva, y el historial en tramos al terminar."""
    return _progreso(tarea_id, tareas.obtener(tarea_id))


@router.post(
    "/garmin/{tarea_id}/cancelar",
    response_model=EstadoDescarga,
    summary="Cancelar una descarga en curso",
    dependencies=[ConGarmin],
)
def cancelar_descarga_de_garmin(tarea_id: str, tareas: Tareas) -> EstadoDescarga:
    """
    Para la descarga y descarta lo que llevara bajado.

    Responde en cuanto marca la tarea, sin esperar al hilo: cancelar tiene que
    sentirse inmediato. Lo ya reunido no se guarda — para quedarse con menos
    horas esta el selector, que para eso ofrece 50, 100 o 135.
    """
    tarea = descarga_service.pedir_cancelacion(tarea_id, tareas)
    return _progreso(tarea_id, tarea)
