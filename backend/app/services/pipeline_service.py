"""
La regla de capacidad cargada, y el entrenamiento de un pipeline por petición.

Dos cosas que conviene no confundir:

- La **regla** (`modelo/reglas.json`) se carga una vez al arrancar. Es un
  insumo fijo para todos: el resultado de barrer presupuestos de historial en el
  notebook de investigación, frente a los 73.5 s que costó derivarla. Por eso no
  se recalcula nunca. Son unos KB: el artefacto completo (`metadata.joblib`, con
  el Random Forest del autor) ya no se carga para servir, porque nadie lo usaba
  desde que se quitó la demostración.
- El **pipeline de un corredor** se entrena en cada cálculo, con el historial
  que manda su navegador, y entrena solo el modelo que la regla le asigne: de
  0.6 s (base física) a unos 13 s en el peor caso (Random Forest con el historial
  completo, medido con 1 vCPU). No se guarda: la API no tiene estado, así que
  cualquier proceso puede atender cualquier petición.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pandas as pd

from app.core.errors import ReglasNoDisponibles
from app.core.logging import get_logger
from app.services.historial_service import Historial
from stamina_core import ARCHIVO_REGLAS, EstrategiaPipeline, cargar_reglas

log = get_logger(__name__)


class PipelineService:
    """Envuelve la regla de capacidad y sabe entrenar el pipeline de un corredor."""

    def __init__(self, carpeta_modelo: Path) -> None:
        self.carpeta = Path(carpeta_modelo)
        self._reglas: dict[str, pd.DataFrame] | None = None
        self._metadatos: dict = {}
        self._error: str | None = None
        self._candado = threading.Lock()

    # --- La regla -----------------------------------------------------------

    def cargar(self) -> None:
        """
        Carga `reglas.json`. Se llama al arrancar.

        No revienta el arranque si falla: se guarda el motivo y `/health` lo
        reporta. Así la API sube igual y se puede diagnosticar desde fuera, en
        vez de tener un proceso que no arranca sin decir por qué.
        """
        ruta = self.carpeta / ARCHIVO_REGLAS
        try:
            self._reglas, self._metadatos = cargar_reglas(ruta)
            self._error = None
            log.info(
                "Regla de capacidad cargada",
                extra={"ruta": str(ruta), "regimenes": sorted(self._reglas)},
            )
        except Exception as error:
            self._reglas, self._metadatos = None, {}
            self._error = f"{type(error).__name__}: {error}"
            log.error(
                "No se pudo cargar la regla de capacidad",
                extra={"ruta": str(ruta), "motivo": self._error},
            )

    @property
    def disponible(self) -> bool:
        return self._reglas is not None

    @property
    def reglas(self) -> dict[str, pd.DataFrame]:
        """La tabla de capacidad. Insumo fijo: se consulta, no se recalcula."""
        if self._reglas is None:
            raise ReglasNoDisponibles(
                f"No se pudo cargar la regla de capacidad desde {self.carpeta}.",
                details={"motivo": self._error, "carpeta": str(self.carpeta)},
            )
        return self._reglas

    # --- Entrenamiento por corredor -----------------------------------------

    def entrenar(self, historial: Historial, km_objetivo: float) -> EstrategiaPipeline:
        """
        El pipeline de este corredor para esta distancia.

        Usa la `reglas` cargada, no una recalculada. El candado evita que dos
        peticiones simultáneas en el mismo proceso peleen por los hilos de
        scikit-learn, que con `n_jobs=-1` se comería la máquina.
        """
        t0 = time.perf_counter()
        with self._candado:
            propio = EstrategiaPipeline(self.reglas, verboso=False)
            propio.fit(historial.dataset, historial.sesiones, km_objetivo=km_objetivo)

        log.info(
            "Pipeline de usuario entrenado",
            extra={
                "horas": round(propio.horas_, 1),
                "km_objetivo": round(km_objetivo, 1),
                "modelo": propio.modelo_nombre_,
                "segundos": round(time.perf_counter() - t0, 2),
            },
        )
        return propio

    # --- Metadatos -----------------------------------------------------------

    def info(self) -> dict:
        """Lo que reporta `/health` sobre la regla."""
        if self._reglas is None:
            return {"cargadas": False, "carpeta": str(self.carpeta), "motivo": self._error}

        return {
            "cargadas": True,
            "carpeta": str(self.carpeta),
            "version_artefacto": self._metadatos.get("version"),
            "creado": self._metadatos.get("creado"),
            "regimenes": sorted(self._reglas),
        }
