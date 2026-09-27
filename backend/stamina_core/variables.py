"""
Ingeniería de variables: terreno, posición y conversiones de ritmo.

Copiado tal cual de la sección 2 del notebook. Es la parte que más pesó en los
resultados medidos (más que la elección de modelo), así que se mueve de sitio
sin tocar una sola fórmula.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import SPLIT_M


def costo_minetti(gradiente):
    """
    Costo energético de correr en J/kg/m según la pendiente.

    Polinomio de Minetti et al. (2002). El gradiente va en tanto por uno y se
    recorta a ±45%, que es el rango donde el ajuste es válido.
    """
    g = np.clip(gradiente, -0.45, 0.45)
    return 155.4 * g**5 - 30.4 * g**4 - 43.3 * g**3 + 46.3 * g**2 + 19.5 * g + 3.6


COSTO_LLANO = costo_minetti(0.0)


def variables_terreno(tabla: pd.DataFrame, split_m: int = SPLIT_M) -> pd.DataFrame:
    """
    Agrega las variables de terreno y posición a los tramos de UNA actividad.

    Ojo: espera recibir una sola actividad, porque usa diff() y cumsum() a lo
    largo de la ruta. Si se le pasa el dataset completo mezcla carreras.
    """
    t = tabla.sort_values("split").copy()

    # Terreno inmediato y su vecindad
    t["pendiente"] = (t["elev"].diff() / split_m * 100).fillna(0)
    t["pendiente_prev"] = t["pendiente"].shift(1).fillna(0)
    t["pendiente_sig"] = t["pendiente"].shift(-1).fillna(0)
    t["pendiente_roll3"] = t["pendiente"].rolling(3, min_periods=1).mean()
    t["costo_rel"] = costo_minetti(t["pendiente"] / 100) / COSTO_LLANO
    t["costo_roll5"] = t["costo_rel"].rolling(5, min_periods=1).mean()

    # Posición en escala física
    t["dist_km"] = (t["split"] + 1) * split_m / 1000
    t["distancia_total_km"] = t["dist_km"].max()
    t["dpos_acum"] = t["elev"].diff().fillna(0).clip(lower=0).cumsum()

    # La misma posición, pero acotada o en log
    t["frac_recorrido"] = t["dist_km"] / t["distancia_total_km"]
    t["log_dist_km"] = np.log(t["dist_km"])
    t["log_dist_total"] = np.log(t["distancia_total_km"])
    t["dpos_por_km"] = t["dpos_acum"] / t["dist_km"]
    t["frac_dpos"] = t["dpos_acum"] / max(t["dpos_acum"].max(), 1e-6)
    return t


def a_ritmo(velocidad):
    """m/s a min/km."""
    return 1000 / 60 / np.maximum(velocidad, 0.01)
