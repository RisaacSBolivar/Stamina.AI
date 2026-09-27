"""
Configuración de la aplicación.

Todos los campos tienen default, así que la API arranca sin un solo `.env`.
Nada de claves ni identificadores escritos en el código: las credenciales de
Garmin las introduce el usuario en cada sesión y no se guardan en ningún sitio
(ver `services/garmin_service.py`).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator

# `NoDecode` vive en pydantic_settings, no en pydantic. Sin él, una lista leída
# de una variable de entorno se intenta parsear como JSON y `STAMINA_CORS_ORIGINS`
# con valores separados por comas revienta.
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from stamina_core.config import MODELO_PUBLICADO


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        env_prefix="STAMINA_",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Aplicación ---------------------------------------------------------
    app_name: str = "Stamina.AI"
    environment: Literal["dev", "test", "prod"] = "dev"
    debug: bool = True
    api_v1_prefix: str = "/api/v1"

    cors_origins: Annotated[list[str], NoDecode] = Field(
        default=["http://localhost:4200", "http://127.0.0.1:4200"]
    )

    # --- Modelo -------------------------------------------------------------
    # Carpeta con `reglas.json`, lo único que la API carga. Vacío =
    # `backend/modelo/`. Solo hace falta si se guarda en otro sitio.
    modelo_dir: str = ""

    # --- Garmin -------------------------------------------------------------
    # La API no guarda nada entre peticiones: el historial procesado viaja en el
    # navegador y vuelve en cada cálculo. Garmin es la excepción, porque el login
    # (con MFA) y la descarga necesitan una sesión viva en el servidor. Donde eso
    # no se pueda garantizar, False lo apaga y la interfaz lo dice.
    garmin_habilitado: bool = True
    # La sesión de Garmin caduca pronto: sostiene un cliente autenticado contra
    # una cuenta real de terceros, y cuanto menos viva, mejor.
    ttl_garmin_segundos: int = 15 * 60

    # --- Límites de subida --------------------------------------------------
    max_archivos_historial: int = 1000
    max_bytes_por_archivo: int = 25 * 1024 * 1024
    max_bytes_gpx: int = 25 * 1024 * 1024
    # El historial procesado que manda el navegador. 100 000 tramos de 100 m son
    # unas 800 h de carrera: un tope contra entradas absurdas, no contra nadie real.
    max_tramos_historial: int = 100_000
    max_bytes_historial: int = 20 * 1024 * 1024

    # --- Rendimiento --------------------------------------------------------
    # Cuántos procesos parsean los .FIT a la vez. Vacío = los de `stamina_core`
    # (6), nunca más que núcleos haya. En una función de 1 vCPU conviene 1: el
    # paralelo ahí duplica el tiempo (medido: 15.6 s contra 32.8 s con 47 .FIT).
    procesos_parseo: int | None = None

    # --- Garmin -------------------------------------------------------------
    garmin_horas_objetivo_max: float = 300.0
    garmin_pausa_descarga_s: float = 0.6

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _separar_origenes(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def carpeta_modelo(self) -> Path:
        """Dónde está `reglas.json`: el configurado o, si no, `backend/modelo/`."""
        if self.modelo_dir:
            return Path(self.modelo_dir)
        return MODELO_PUBLICADO

    @property
    def es_produccion(self) -> bool:
        return self.environment == "prod"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
