"""
Zonas de exigencia: k-Means sobre terreno, esfuerzo y posición.

Sección 4.2 del notebook. k = 4 se eligió mirando codo y silueta. Las zonas no
predicen nada: le ponen nombre a lo que el modelo ya predijo, para que la
estrategia se pueda leer y compilar en pasos de entrenamiento.
"""

from __future__ import annotations

import pandas as pd

from .config import NOMBRES_ZONA, VARS_ZONA


def ordenar_zonas(datos: pd.DataFrame, modelo_kmeans, escalador):
    """
    Le pone nombre a cada clúster según qué tan exigente es.

    Devuelve (diccionario cluster -> nombre, tabla con el perfil de cada zona).
    El orden lo fija un índice de exigencia que suma la FC relativa tipificada y
    el costo del terreno tipificado, así que los nombres son estables aunque
    k-Means numere los clústeres en otro orden entre corridas.
    """
    etiquetas = modelo_kmeans.predict(escalador.transform(datos[VARS_ZONA]))

    perfil = (
        datos.assign(cluster=etiquetas)
        .groupby("cluster")
        .agg(
            tramos=("v_ratio", "size"),
            pendiente=("pendiente", "mean"),
            costo=("costo_rel", "mean"),
            v_ratio=("v_ratio", "mean"),
            fc_ratio=("fc_ratio", "mean"),
            frac=("frac_recorrido", "mean"),
        )
    )

    def tipificar(serie):
        return (serie - serie.mean()) / (serie.std() + 1e-9)

    perfil["exigencia"] = tipificar(perfil["fc_ratio"]) + tipificar(perfil["costo"])
    perfil = perfil.sort_values("exigencia")
    perfil["zona"] = NOMBRES_ZONA[: len(perfil)]

    return dict(zip(perfil.index, perfil["zona"], strict=True)), perfil
