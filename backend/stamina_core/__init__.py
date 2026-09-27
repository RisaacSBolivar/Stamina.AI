"""
stamina_core — el pipeline de investigación de Stamina.AI, como módulo importable.

Extraído del notebook de investigación (`notebook_StaminAI.ipynb`) sin cambiar
comportamiento: las mismas fórmulas, los mismos hiperparámetros y el mismo
formato de `metadata.joblib`. Lo único que
cambia es dónde vive el código, que es justo lo que el notebook dejaba anotado
como pendiente para poder construir la app.

Uso típico desde el backend:

    from stamina_core import EstrategiaPipeline
    from stamina_core.config import MODELO_PUBLICADO

    pipeline = EstrategiaPipeline.cargar(MODELO_PUBLICADO, verboso=False)
    ruta = pipeline.predecir_ruta("ruta.gpx", tiempo_objetivo_h=4.0, temperatura_c=18.0)
    tabla = pipeline.tabla_km(ruta)

Importar este paquete **no** carga TensorFlow: la red se importa solo si el
artefacto la necesita.
"""

from __future__ import annotations

from .config import (
    K_ZONAS,
    NOMBRES_ZONA,
    SEMILLA,
    SPLIT_M,
    VARS_ACOTADAS,
    VARS_MODELO,
    VARS_TABULARES,
    VARS_ZONA,
    Rutas,
)
from .entrenamiento import (
    compilar_pasos,
    compilar_workout_fit,
    verificar_workout_fit,
    workout_json,
)
from .hiperparametros import ALPHA_RIDGE, CONFIG_CNN, PARAMS_BOSQUE
from .ingesta import (
    cargar_ruta_objetivo,
    cargar_splits,
    construir_dataset,
    listar_fit,
    parsear_lote,
    perfil_temporal,
    procesar_fit,
    procesar_gpx,
)
from .modelos import BaseFisica, ModeloTabular, RedTerreno, RitmoConstante
from .objetivos import OBJETIVOS, opciones, sugerir_tiempo_objetivo
from .pipeline import EstrategiaPipeline
from .reglas import (
    ARCHIVO_REGLAS,
    MARGEN_RUIDO,
    NIVEL_CAPACIDAD,
    REGIMEN_CORTO,
    REGIMEN_MARATON,
    RITMO_CONSTANTE,
    UMBRAL_HABILIDAD,
    candidatos,
    cargar_reglas,
    consultar_capacidad,
    elegir_modelo,
    guardar_reglas,
    regimen_de,
)
from .variables import a_ritmo, costo_minetti, variables_terreno
from .zonas import ordenar_zonas

__version__ = "6.0"

__all__ = [
    "ALPHA_RIDGE",
    "ARCHIVO_REGLAS",
    "CONFIG_CNN",
    "K_ZONAS",
    "MARGEN_RUIDO",
    "NIVEL_CAPACIDAD",
    "NOMBRES_ZONA",
    "OBJETIVOS",
    "PARAMS_BOSQUE",
    "REGIMEN_CORTO",
    "REGIMEN_MARATON",
    "RITMO_CONSTANTE",
    "SEMILLA",
    "SPLIT_M",
    "UMBRAL_HABILIDAD",
    "VARS_ACOTADAS",
    "VARS_MODELO",
    "VARS_TABULARES",
    "VARS_ZONA",
    "BaseFisica",
    "EstrategiaPipeline",
    "ModeloTabular",
    "RedTerreno",
    "RitmoConstante",
    "Rutas",
    "a_ritmo",
    "candidatos",
    "cargar_reglas",
    "cargar_ruta_objetivo",
    "cargar_splits",
    "compilar_pasos",
    "compilar_workout_fit",
    "construir_dataset",
    "consultar_capacidad",
    "costo_minetti",
    "elegir_modelo",
    "guardar_reglas",
    "listar_fit",
    "opciones",
    "ordenar_zonas",
    "parsear_lote",
    "perfil_temporal",
    "procesar_fit",
    "procesar_gpx",
    "regimen_de",
    "sugerir_tiempo_objetivo",
    "variables_terreno",
    "verificar_workout_fit",
    "workout_json",
]
