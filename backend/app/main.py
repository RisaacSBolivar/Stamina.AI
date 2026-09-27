"""
Punto de entrada de la API.

La regla de capacidad se carga **una vez**, al arrancar, y se consulta en cada
petición: según el notebook, atender a un usuario sale 32 veces más barato que
recalcular la curva para él, y esa separación es justo lo que esta capa
preserva. Fuera de eso la API no guarda nada entre peticiones (salvo lo de
Garmin, que solo se enciende en local), así que puede correr sin estado.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import register_exception_handlers
from app.core.logging import get_logger, setup_logging
from app.schemas.api import RESPUESTAS_ERROR
from app.services import almacen
from app.services.pipeline_service import PipelineService

log = get_logger(__name__)

DESCRIPCION = """
Estrategia de ritmo kilómetro a kilómetro para una carrera, a partir del
historial del propio corredor.

**Cuando no hay evidencia suficiente, el sistema devuelve ritmo constante y
explica el motivo real** — que puede ser la falta de horas o la distancia
objetivo. El umbral no está escrito en ninguna parte del código: sale de
consultar `GET /capacidad`, porque depende de las dos cosas.

**La API no guarda el historial de nadie.** `POST /historial/archivos` devuelve
los tramos de 100 m (sin coordenadas) y el cliente los manda de vuelta en cada
cálculo; la estrategia trae consigo los pasos y el `.FIT`. Solo Garmin necesita
sesión en el servidor, y por eso solo existe donde `garmin_habilitado` está
encendido.

No es consejo médico ni sustituye a un entrenador.

El entrenamiento estructurado que se exporta está verificado en formato, Garmin
Connect acepta la subida por API y se ha probado en un reloj físico.
"""


def operation_id_legible(route: APIRoute) -> str:
    """
    `tag_nombreFuncion` en vez de `salud_api_v1_health_get`.

    Sin esto, los tipos que genera `openapi-typescript` salen ilegibles.
    """
    tag = route.tags[0] if route.tags else "default"
    return f"{tag}_{route.name}"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    setup_logging("DEBUG" if settings.debug else "INFO")
    almacen.configurar(settings.ttl_garmin_segundos)

    servicio = PipelineService(settings.carpeta_modelo)
    servicio.cargar()
    app.state.pipelines = servicio

    if not servicio.disponible:
        # Se arranca igual: /health lo reporta y así se puede diagnosticar desde
        # fuera, en vez de tener un proceso que muere sin decir por qué.
        log.warning(
            "La API arranca sin la regla de capacidad. Solo responderán /health "
            "y los endpoints que no la consultan."
        )

    log.info(
        "Stamina.AI arrancado",
        extra={
            "entorno": settings.environment,
            "reglas": servicio.disponible,
            "garmin": settings.garmin_habilitado,
        },
    )
    try:
        yield
    finally:
        log.info("Stamina.AI detenido")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=DESCRIPCION,
        lifespan=lifespan,
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
        generate_unique_id_function=operation_id_legible,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def contexto_peticion(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        request.state.request_id = request_id

        inicio = time.perf_counter()
        respuesta = await call_next(request)
        ms = (time.perf_counter() - inicio) * 1000

        respuesta.headers["X-Request-ID"] = request_id
        respuesta.headers["X-Response-Time-ms"] = f"{ms:.1f}"

        log.debug(
            "peticion",
            extra={
                "request_id": request_id,
                "metodo": request.method,
                "ruta": request.url.path,
                "estado": respuesta.status_code,
                "ms": round(ms, 1),
            },
        )
        return respuesta

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_v1_prefix, responses=RESPUESTAS_ERROR)

    @app.get("/", include_in_schema=False)
    def raiz() -> dict:
        return {
            "app": settings.app_name,
            "docs": "/docs",
            "openapi": "/openapi.json",
            "api": settings.api_v1_prefix,
        }

    return app


app = create_app()
