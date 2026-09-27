"""
Traducción del selector de objetivo de carrera a parámetros del pipeline.

El problema: el diseño de solución pide un selector de cuatro opciones
—terminar sin fatiga, mejor marca, ritmo conservador, maximizar rendimiento—
pero `predecir_ruta()` solo recibe `tiempo_objetivo_h` y `temperatura_c`, y el
anclaje fija el tiempo total *exacto*. La forma de la curva la pone el modelo;
el nivel lo pone el tiempo. No hay ningún otro parámetro sobre el que mapear.

La decisión tomada con el autor: **cada opción solo sugiere un tiempo objetivo**.
No se amplía la firma de `predecir_ruta()`, porque amortiguar o amplificar la
curva cambiaría la forma cuya habilidad se midió, y la habilidad reportada
dejaría de aplicar.

Lo de aquí es una **calculadora sobre el historial**, no una salida del modelo, y
la interfaz tiene que decirlo así. El tiempo devuelto es editable: es un punto
de partida, no una predicción.

La temperatura no se deriva del objetivo. Es un dato de la carrera que introduce
el usuario, con 18 °C como default (el mismo que el pipeline).
"""

from __future__ import annotations

import pandas as pd

# Exponente de Riegel (1981). T2 = T1 * (D2/D1)^1.06 es la extrapolación clásica
# entre distancias de carrera; es literatura, no algo ajustado con estos datos.
EXPONENTE_RIEGEL = 1.06

# Distancia mínima de un esfuerzo para servir de referencia. Por debajo de 5 km
# la extrapolación a maratón es demasiado optimista.
KM_MINIMO_REFERENCIA = 5.0

# Cuántas sesiones recientes se miran buscando el mejor esfuerzo.
SESIONES_RECIENTES = 40

OBJETIVOS = {
    "maximizar rendimiento": {
        "factor": 1.00,
        "etiqueta": "Maximizar rendimiento",
        "descripcion": "El tiempo que tu historial sugiere como techo, sin margen.",
    },
    "mejor marca": {
        "factor": 1.02,
        "etiqueta": "Mejor marca",
        "descripcion": "Apenas por debajo del techo, buscando marca personal.",
    },
    "terminar sin fatiga": {
        "factor": 1.06,
        "etiqueta": "Terminar sin fatiga",
        "descripcion": "Con margen para llegar entero al final.",
    },
    "ritmo conservador": {
        "factor": 1.10,
        "etiqueta": "Ritmo conservador",
        "descripcion": "El más prudente: prioriza acabar cómodo.",
    },
}

OBJETIVO_POR_DEFECTO = "terminar sin fatiga"


def sugerir_tiempo_objetivo(
    sesiones_usuario: pd.DataFrame,
    km_objetivo: float,
    objetivo: str = OBJETIVO_POR_DEFECTO,
) -> dict:
    """
    Sugiere un `tiempo_objetivo_h` a partir del propio historial del corredor.

    Toma su mejor esfuerzo reciente por encima de `KM_MINIMO_REFERENCIA`,
    lo extrapola a la distancia objetivo con Riegel y aplica el factor de la
    opción elegida.

    Devuelve siempre `editable: True` y el método empleado, para que la interfaz
    pueda presentarlo como sugerencia y no como resultado del modelo. Si el
    historial no da para una referencia, `tiempo_objetivo_h` viene en None y
    `motivo` explica por qué: entonces el usuario tiene que teclear su tiempo.
    """
    if objetivo not in OBJETIVOS:
        raise ValueError(f"Objetivo desconocido: {objetivo!r}. Opciones: {sorted(OBJETIVOS)}")

    factor = OBJETIVOS[objetivo]["factor"]
    base = _mejor_esfuerzo(sesiones_usuario)

    if base is None:
        return {
            "objetivo": objetivo,
            "etiqueta": OBJETIVOS[objetivo]["etiqueta"],
            "km_objetivo": round(float(km_objetivo), 2),
            "tiempo_objetivo_h": None,
            "editable": True,
            "motivo": (
                f"No hay ninguna sesión de al menos {KM_MINIMO_REFERENCIA:.0f} km en el "
                "historial, así que no tengo de dónde extrapolar un tiempo."
            ),
            "metodo": None,
            "referencia": None,
            "factor": factor,
        }

    horas_base = base["minutos"] / 60
    horas_riegel = horas_base * (km_objetivo / base["km"]) ** EXPONENTE_RIEGEL
    sugerido = horas_riegel * factor

    return {
        "objetivo": objetivo,
        "etiqueta": OBJETIVOS[objetivo]["etiqueta"],
        "km_objetivo": round(float(km_objetivo), 2),
        "tiempo_objetivo_h": round(float(sugerido), 3),
        "ritmo_medio_min_km": round(float(sugerido * 60 / km_objetivo), 2),
        "editable": True,
        "motivo": None,
        "metodo": (
            f"Riegel (exponente {EXPONENTE_RIEGEL}) desde tu mejor esfuerzo reciente, "
            f"por el factor {factor:.2f} de «{OBJETIVOS[objetivo]['etiqueta']}». "
            "Es una calculadora sobre tu historial, no una predicción del modelo."
        ),
        "referencia": {
            "fecha": base["fecha"],
            "km": round(float(base["km"]), 2),
            "minutos": round(float(base["minutos"]), 1),
            "ritmo_min_km": round(float(base["ritmo"]), 2),
        },
        "factor": factor,
    }


def _mejor_esfuerzo(sesiones: pd.DataFrame) -> dict | None:
    """
    El esfuerzo de referencia: la sesión reciente más rápida de las largas.

    "Reciente" son las últimas `SESIONES_RECIENTES` por fecha, para que una
    marca de hace dos años no fije el objetivo de hoy.
    """
    if sesiones is None or len(sesiones) == 0:
        return None

    candidatas = sesiones[sesiones["km"] >= KM_MINIMO_REFERENCIA]
    if candidatas.empty:
        return None

    recientes = candidatas.sort_values("fecha").tail(SESIONES_RECIENTES)
    fila = recientes.loc[recientes["ritmo"].idxmin()]

    return {
        "fecha": str(fila["fecha"]),
        "km": float(fila["km"]),
        "minutos": float(fila["minutos"]),
        "ritmo": float(fila["ritmo"]),
    }


def opciones() -> list[dict]:
    """Las opciones del selector, para que la interfaz no las escriba a mano."""
    return [
        {
            "clave": clave,
            "etiqueta": datos["etiqueta"],
            "descripcion": datos["descripcion"],
            "factor": datos["factor"],
            "por_defecto": clave == OBJETIVO_POR_DEFECTO,
        }
        for clave, datos in OBJETIVOS.items()
    ]
