"""
El cálculo de la estrategia: de un .GPX y un historial a la tabla por kilómetro.

Todo en una petición, sin nada guardado entre medias: el historial llega en
tramos (lo que devolvió `POST /historial/archivos`), se entrena el modelo que la
regla le asigne a ese corredor y la respuesta trae la estrategia, sus señales de
capacidad, los pasos para el reloj y el `.FIT` ya generado.
"""

from __future__ import annotations

from fastapi import APIRouter, File, Form, UploadFile

from app.api.deps import Config, ServicioPipeline
from app.core.errors import ArchivoInvalido
from app.schemas.api import Estrategia, TramosHistorial
from app.services import estrategia_service, historial_service

router = APIRouter(tags=["estrategia"])


@router.post(
    "/estrategia",
    response_model=Estrategia,
    summary="Calcular la estrategia de ritmo para una ruta",
)
async def calcular_estrategia(
    servicio: ServicioPipeline,
    config: Config,
    gpx: UploadFile = File(description="Ruta objetivo en .GPX"),
    historial: UploadFile = File(
        description="El historial procesado (los `tramos` de `POST /historial/archivos`), en JSON"
    ),
    tiempo_objetivo_h: float = Form(gt=0.1, le=24, description="Tiempo objetivo en horas"),
    temperatura_c: float = Form(default=18.0, ge=-30, le=55),
) -> Estrategia:
    """
    Entrena el modelo de este corredor y calcula su estrategia para la ruta.

    El historial va como archivo y no como campo de formulario porque un
    historial largo pasa de 1 MB, que es el tope de un campo de texto en el
    multipart de Starlette.

    El `km_objetivo` con el que se consulta la regla **sale de la propia ruta**,
    no de lo que diga el usuario: es la distancia que va a correr de verdad.
    """
    nombre = gpx.filename or "ruta.gpx"
    if not nombre.lower().endswith(".gpx"):
        raise ArchivoInvalido(
            f"«{nombre}» no es un .GPX. La ruta objetivo se carga en ese formato.",
            details={"archivo": nombre},
        )

    contenido = await gpx.read()
    if len(contenido) > config.max_bytes_gpx:
        raise ArchivoInvalido(f"El .GPX pesa más de {config.max_bytes_gpx // (1024 * 1024)} MB.")

    crudo = await historial.read()
    if len(crudo) > config.max_bytes_historial:
        raise ArchivoInvalido("El historial procesado es demasiado grande.")
    try:
        tramos = TramosHistorial.model_validate_json(crudo)
    except ValueError as error:
        raise ArchivoInvalido(
            "El historial no tiene el formato esperado. Vuelve a subir tus .FIT.",
            details={"motivo": str(error)[:300]},
        ) from error

    perfil = estrategia_service.perfil_de_gpx(contenido, nombre)
    km_ruta = float((perfil["split"].max() + 1) * 100 / 1000)

    datos = historial_service.desde_tramos(tramos.model_dump(), limite=config.max_tramos_historial)
    pipeline = servicio.entrenar(datos, km_ruta)

    estrategia = estrategia_service.calcular(
        pipeline,
        perfil,
        tiempo_objetivo_h,
        temperatura_c,
        nombre_ruta=nombre.rsplit(".", 1)[0],
    )
    return Estrategia(**estrategia_service.a_respuesta(estrategia))
