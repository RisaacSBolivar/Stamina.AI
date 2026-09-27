"""Agrega todos los routers de la v1 en un orden fijo."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.capacidad import router as capacidad_router
from app.api.v1.estrategia import router as estrategia_router
from app.api.v1.exportar import router as exportar_router
from app.api.v1.garmin import router as garmin_router
from app.api.v1.historial import router as historial_router
from app.api.v1.meta import router as meta_router
from app.api.v1.objetivo import router as objetivo_router
from app.api.v1.sesion import router as sesion_router

api_router = APIRouter()

# El orden es el del flujo del producto: salud, historial, capacidad, objetivo,
# estrategia, exportación. Garmin al final porque atraviesa varios pasos.
api_router.include_router(meta_router)
api_router.include_router(historial_router)
api_router.include_router(capacidad_router)
api_router.include_router(objetivo_router)
api_router.include_router(estrategia_router)
api_router.include_router(exportar_router)
api_router.include_router(garmin_router)
# Salir y no dejar rastro: cruza los tres almacenes, asi que va aparte.
api_router.include_router(sesion_router)
