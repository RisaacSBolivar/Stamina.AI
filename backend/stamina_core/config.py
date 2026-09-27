"""
Constantes del pipeline y resolución de rutas.

Todo lo que aquí vive salió del notebook de investigación
(`notebook_StaminAI.ipynb`, secciones 0.2, 2.1 y 4.1) y define la geometría de
los datos: el largo del tramo, las listas de variables, los nombres de las zonas. Cambiar cualquiera de estos valores
invalida el `metadata.joblib` ya entrenado y los números medidos en la
investigación, así que se tocan solo volviendo a correr el notebook completo.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# --- Donde vive el artefacto ------------------------------------------------

# `metadata.joblib` lo escribió el notebook de investigación, que vive fuera de
# este repositorio. La copia que carga la API es la de `backend/modelo/`, y es la
# única: un backend que dependiera de la carpeta de trabajo de un notebook no se
# podría desplegar en ningún sitio. Se ancla en el propio módulo para no tener
# que adivinar desde dónde se arranca.
MODELO_PUBLICADO = Path(__file__).resolve().parent.parent / "modelo"

# --- Semilla y geometría de los datos ---------------------------------------

SEMILLA = 42
SPLIT_M = 100  # largo del tramo de análisis, en metros
MIN_REGISTROS_SPLIT = 3  # menos de 3 lecturas en 100 m = tramo poco fiable

# --- Limpieza a nivel de tramo ----------------------------------------------

V_MIN, V_MAX = 1.0, 7.0  # m/s
FC_MIN = 60  # bpm

# Tratamiento del objetivo. Los valores salen de la comparación de la sección 2.4
# del notebook, donde winsorizar y suavizar movió la habilidad de -0.004 a 0.052.
LIMITES_V_RATIO = (0.70, 1.30)
LIMITES_FC_RATIO = (0.75, 1.25)
SUAVIZADO_OBJETIVO = 5  # 5 tramos = 500 m

# --- Listas de variables (sección 2.3-2.5) ----------------------------------

VARS_PENDIENTE = [
    "pendiente",
    "pendiente_prev",
    "pendiente_sig",
    "pendiente_roll3",
    "costo_rel",
    "costo_roll5",
]
VARS_POSICION = ["dist_km", "distancia_total_km", "dpos_acum"]
VARS_POSICION_ACOTADA = [
    "log_dist_km",
    "frac_recorrido",
    "log_dist_total",
    "dpos_por_km",
    "frac_dpos",
]

# v3 ganó para el bosque (escala física) y v4 para Ridge (escala acotada).
VARS_TABULARES = VARS_PENDIENTE + VARS_POSICION + ["temperatura"]
VARS_ACOTADAS = VARS_PENDIENTE + VARS_POSICION_ACOTADA + ["temperatura"]

# La unión se usa para recortar las variables de una ruta nueva al rango que el
# modelo vio en entrenamiento (ver EstrategiaPipeline.predecir_ruta).
VARS_MODELO = sorted(set(VARS_TABULARES + VARS_ACOTADAS))

# --- Zonas de exigencia (sección 4.2) ---------------------------------------

K_ZONAS = 4
VARS_ZONA = ["pendiente", "costo_rel", "v_ratio", "fc_ratio", "frac_recorrido"]
NOMBRES_ZONA = ["Recuperación", "Crucero", "Exigencia alta", "Exigencia crítica"]

# --- Red convolucional (sección 4.1) ----------------------------------------
# Se declaran aquí aunque la red casi nunca gane, porque `RedTerreno.desde_estado`
# las necesita para reconstruir un artefacto que sí la haya elegido.

CANALES = ["pendiente", "costo_rel"]  # lo que ve la parte convolucional
ESCALARES = VARS_POSICION_ACOTADA + CANALES  # lo que ve la rama densa

VENTANA_ATRAS = 15
VENTANA_ADELANTE = 5
VENTANA = VENTANA_ATRAS + 1 + VENTANA_ADELANTE

LIMITE_Z = 4.0  # recorte de las variables normalizadas, para que un outlier no domine

# --- Campos del .FIT (sección 0.3) ------------------------------------------

CAMPOS_FIT = [
    "timestamp",
    "distance",
    "heart_rate",
    "enhanced_speed",
    "enhanced_altitude",
    "cadence",
    "temperature",
]
# La temperatura es opcional: hay relojes y actividades que no la graban.
CAMPOS_NECESARIOS = [
    "distance",
    "heart_rate",
    "enhanced_speed",
    "enhanced_altitude",
    "cadence",
]

TIPOS_CARRERA = {
    "running",
    "trail_running",
    "treadmill_running",
    "track_running",
    "virtual_run",
    "ultra_run",
}


# --- Rutas -------------------------------------------------------------------


@dataclass(frozen=True)
class Rutas:
    """
    Las carpetas de datos, colgadas de una raíz.

    Es la disposición del notebook de investigación (`data/procesado/`,
    `data/rutas/`, `data/fit_files/` y `salidas/`). El backend no la necesita para
    servir peticiones; la usan las pruebas, que traen una copia mínima en
    `tests/datos/`, y quien quiera usar `cargar_splits` o `listar_fit` desde un
    script.
    """

    raiz: Path

    @property
    def datos(self) -> Path:
        return self.raiz / "data"

    @property
    def procesado(self) -> Path:
        return self.datos / "procesado"

    @property
    def rutas_gpx(self) -> Path:
        return self.datos / "rutas"

    @property
    def fit_files(self) -> Path:
        return self.datos / "fit_files"

    @property
    def modelo(self) -> Path:
        """De donde se lee `metadata.joblib`: siempre la copia publicada del backend."""
        return MODELO_PUBLICADO

    @property
    def salidas(self) -> Path:
        return self.raiz / "salidas"

    @property
    def splits(self) -> Path:
        return self.procesado / "splits.parquet"

    @property
    def dataset(self) -> Path:
        return self.procesado / "dataset.parquet"

    @property
    def atenas(self) -> Path:
        return self.procesado / "atenas.parquet"

    @property
    def metadatos(self) -> Path:
        return self.procesado / "metadatos.json"

    @property
    def gpx_atenas(self) -> Path:
        return self.rutas_gpx / "athens_marathon_the_authentic.gpx"
