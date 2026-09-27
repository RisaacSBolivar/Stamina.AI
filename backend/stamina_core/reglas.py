"""
La regla de capacidad: qué modelo se le asigna a un corredor y por qué.

Secciones 4.3 y 4.4 del notebook. La tabla `reglas` es un **insumo fijo**: se
derivó una sola vez barriendo presupuestos de historial, viaja dentro de
`metadata.joblib` y la API la lee de `modelo/reglas.json`. Aquí solo se consulta; nunca se recalcula ni se replica el
umbral en ningún otro sitio del sistema.

Dos cosas que la interfaz necesita saber y que no son obvias en la tabla:

1. **La regla no es monótona.** En régimen maratón: 10 h asigna Base física
   (0.221), 19.9 h RandomForest (0.125), 39.4 h Base física otra vez (0.209),
   79.8 h RandomForest (0.217) y 124.7 h RandomForest (0.303). Como se toma la
   última franja aplicable, un corredor con 60 h recibe Base física y uno con
   30 h recibe RandomForest. Más horas no siempre significan mejor modelo.
2. **La capacidad depende también de la distancia objetivo.** En el régimen
   corto ningún modelo gana de forma consistente, con ningún volumen de datos.
   Decirle a ese usuario "te faltan horas" sería falso: el motivo es la
   distancia. De ahí `consultar_capacidad`, que devuelve el motivo real.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .config import SEMILLA, VARS_ACOTADAS, VARS_TABULARES
from .hiperparametros import ALPHA_RIDGE, CONFIG_CNN, PARAMS_BOSQUE
from .modelos import BaseFisica, ModeloTabular, RedTerreno, RitmoConstante

# --- Parámetros de la regla (sección 4.4) -----------------------------------

UMBRAL_HABILIDAD = 0.05  # por debajo de esto la ventaja no se distingue del ruido
MARGEN_RUIDO = 0.05  # dos modelos dentro de este margen empatan

# Nivel de capacidad = cuánta evidencia pide cada familia. Importa más el nivel
# que el nombre, porque Ridge y el bosque son intercambiables entre sí.
NIVEL_CAPACIDAD = {
    "Ritmo constante": 0,
    "Base física": 1,
    "Ridge": 2,
    "RandomForest": 2,
    "CNN-Híbrida": 3,
}

RITMO_CONSTANTE = "Ritmo constante"

# --- Regímenes ---------------------------------------------------------------
# Estas cadenas son parte del contrato del artefacto ya guardado: son las claves
# literales del diccionario `reglas` dentro de metadata.joblib. No se renombran
# sin regenerar el artefacto.

REGIMEN_MARATON = "maratón"
REGIMEN_CORTO = "carrera de 10-12 km"
KM_CORTE_REGIMEN = 40

# Distancias con las que se validó de verdad cada régimen. No están en el
# artefacto, pero salen de las carreras apartadas de la sección 1.4: dos
# maratones (43.0 y 42.9 km) y cuatro carreras de 10.1, 11.1, 12.1 y 16.1 km.
# Entre 16 y 42 km no hay nada medido, y la interfaz tiene que decirlo.
VALIDADO_EN_KM = {
    REGIMEN_MARATON: (42.9, 43.0),
    REGIMEN_CORTO: (10.1, 16.1),
}

# Motivos por los que el sistema devuelve ritmo constante.
MOTIVO_HISTORIAL_INSUFICIENTE = "historial_insuficiente"
MOTIVO_FRANJA_SIN_EVIDENCIA = "sin_evidencia_en_esta_franja"
MOTIVO_DISTANCIA_SIN_EVIDENCIA = "distancia_sin_evidencia"


def regimen_de(km_objetivo: float) -> str:
    """El régimen al que pertenece una distancia objetivo."""
    return REGIMEN_MARATON if km_objetivo > KM_CORTE_REGIMEN else REGIMEN_CORTO


# --- Construcción de los candidatos -----------------------------------------


def _nuevo_ridge() -> ModeloTabular:
    return ModeloTabular(
        make_pipeline(StandardScaler(), Ridge(alpha=ALPHA_RIDGE)), "Ridge", VARS_ACOTADAS
    )


def _nuevo_bosque() -> ModeloTabular:
    return ModeloTabular(
        RandomForestRegressor(random_state=SEMILLA, n_jobs=-1, **PARAMS_BOSQUE),
        "RandomForest",
        VARS_TABULARES,
    )


def _nueva_red() -> RedTerreno:
    return RedTerreno(**CONFIG_CNN)


def candidatos() -> dict:
    """
    Los constructores de modelo, por nombre.

    Sustituye al diccionario global `CANDIDATOS` del notebook. `EstrategiaPipeline.fit`
    lo consulta para instanciar únicamente el modelo que la regla le asigne al
    usuario: no se entrenan los cinco.
    """
    return {
        "Ritmo constante": RitmoConstante,
        "Base física": BaseFisica,
        "Ridge": _nuevo_ridge,
        "RandomForest": _nuevo_bosque,
        "CNN-Híbrida": _nueva_red,
    }


# --- Consulta (lo que usan el pipeline y la API) ----------------------------


def elegir_modelo(
    horas_disponibles: float, km_objetivo: float, tabla_reglas: dict[str, pd.DataFrame]
) -> tuple[str, float]:
    """
    Modelo recomendado y habilidad esperada.

    A diferencia del notebook, `tabla_reglas` es obligatoria: no hay una tabla
    global de la que tirar por defecto. Siempre se consulta la que viene dentro
    del artefacto cargado.
    """
    regla = tabla_reglas[regimen_de(km_objetivo)]

    aplicables = regla[regla["desde_horas"] <= horas_disponibles]
    if aplicables.empty:
        return RITMO_CONSTANTE, 0.0

    fila = aplicables.iloc[-1]
    return fila["modelo"], float(fila["habilidad"])


def consultar_capacidad(
    horas_disponibles: float, km_objetivo: float, tabla_reglas: dict[str, pd.DataFrame]
) -> dict:
    """
    Lo mismo que `elegir_modelo`, pero con todo lo que la interfaz necesita.

    Devuelve el modelo asignado y, cuando la respuesta es ritmo constante, **el
    motivo real**: si el historial todavía no llega al primer presupuesto
    medido, si esta franja concreta no mostró evidencia, o si es la distancia
    objetivo la que no tiene evidencia con ningún volumen de datos.

    La interfaz no debe inferir nada de esto por su cuenta ni escribir el umbral
    en ninguna parte: sale siempre de aquí.
    """
    regimen = regimen_de(km_objetivo)
    regla = tabla_reglas[regimen]

    personaliza = regla["modelo"] != RITMO_CONSTANTE
    aplicables = regla[regla["desde_horas"] <= horas_disponibles]

    # ¿Acumular historial lleva a algún sitio en este régimen? La prueba es si la
    # franja con más horas medidas personaliza. En maratón sí (RandomForest con
    # 0.303, el mejor número de toda la tabla). En el régimen corto no: la última
    # franja vuelve a ritmo constante, que es la forma medida de decir que ahí el
    # factor limitante es la distancia y no las horas.
    regimen_fiable = bool(personaliza.iloc[-1]) if len(regla) else False

    if aplicables.empty:
        modelo, habilidad, nivel = RITMO_CONSTANTE, 0.0, 0
        motivo = MOTIVO_HISTORIAL_INSUFICIENTE
    else:
        fila = aplicables.iloc[-1]
        modelo = str(fila["modelo"])
        habilidad = float(fila["habilidad"])
        nivel = int(fila["nivel"])
        if modelo != RITMO_CONSTANTE:
            motivo = None
        elif not regimen_fiable:
            # Ni con todo el historial medido personaliza este régimen: decirle
            # al usuario "te faltan horas" sería falso.
            motivo = MOTIVO_DISTANCIA_SIN_EVIDENCIA
        else:
            motivo = MOTIVO_FRANJA_SIN_EVIDENCIA

    # La primera franja por encima del historial actual que sí personaliza. Es
    # lo que permite decir "a las N horas la regla asignaría X" sin prometer que
    # la mejora sea monótona, porque no lo es.
    arriba = regla[(regla["desde_horas"] > horas_disponibles) & personaliza]
    siguiente = None
    if not arriba.empty:
        fila_sig = arriba.iloc[0]
        siguiente = {
            "desde_horas": float(fila_sig["desde_horas"]),
            "modelo": str(fila_sig["modelo"]),
            "habilidad": float(fila_sig["habilidad"]),
            "horas_faltantes": round(float(fila_sig["desde_horas"]) - horas_disponibles, 1),
        }

    validado_min, validado_max = VALIDADO_EN_KM[regimen]

    return {
        "horas": round(float(horas_disponibles), 2),
        "km_objetivo": round(float(km_objetivo), 2),
        "regimen": regimen,
        "modelo": modelo,
        "habilidad_esperada": round(habilidad, 3),
        "nivel_capacidad": nivel,
        "personalizada": modelo != RITMO_CONSTANTE,
        "motivo": motivo,
        "siguiente_franja": siguiente,
        # `regimen_fiable=False` significa que en este régimen acumular horas no
        # desbloquea nada: la interfaz no debe ofrecer "sigue entrenando y
        # vuelve" como salida, ni presentar una estrategia de aquí sin avisar.
        "regimen_fiable": regimen_fiable,
        "regimen_monotono": _es_monotona(regla),
        "validado_en_km": [validado_min, validado_max],
        # Entre 16 y 40 km la distancia cae en el régimen corto pero fuera de lo
        # que se validó. No es un error, es una extrapolación que hay que avisar.
        "distancia_extrapolada": bool(regimen == REGIMEN_CORTO and km_objetivo > validado_max),
        "franjas": [
            {
                "desde_horas": float(f["desde_horas"]),
                "sesiones": int(f["sesiones"]),
                "modelo": str(f["modelo"]),
                "habilidad": float(f["habilidad"]),
                "nivel": int(f["nivel"]),
            }
            for _, f in regla.iterrows()
        ],
    }


def _es_monotona(regla: pd.DataFrame) -> bool:
    """¿El nivel de capacidad asignado crece con las horas, sin bajar nunca?"""
    niveles = regla["modelo"].map(NIVEL_CAPACIDAD)
    return bool(niveles.diff().dropna().ge(0).all())


# --- La tabla como archivo ligero -------------------------------------------
#
# Para servir peticiones la API solo necesita `reglas`: cada corredor entrena su
# propio modelo. Leerla de `metadata.joblib` obligaba a cargar 24.5 MB con un
# Random Forest que nadie usaba, y a desplegar pyarrow (156 MB), porque el pickle
# guarda las columnas de texto de pandas 3 respaldadas por pyarrow. Con la tabla
# en JSON son unos KB y basta pandas. La escribe `scripts/extraer_reglas.py`
# desde el artefacto, y una prueba comprueba que las dos coinciden.

ARCHIVO_REGLAS = "reglas.json"


def guardar_reglas(reglas: dict[str, pd.DataFrame], ruta, **metadatos) -> None:
    """Escribe la tabla `reglas` en JSON, fila a fila, con metadatos de origen."""
    contenido = {
        **metadatos,
        "reglas": {nombre: tabla.to_dict(orient="records") for nombre, tabla in reglas.items()},
    }
    Path(ruta).write_text(
        json.dumps(contenido, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )


def cargar_reglas(ruta) -> tuple[dict[str, pd.DataFrame], dict]:
    """Lee `reglas.json`: devuelve la tabla por régimen y los metadatos de origen."""
    contenido = json.loads(Path(ruta).read_text(encoding="utf-8"))
    reglas = {
        nombre: pd.DataFrame.from_records(filas)
        for nombre, filas in contenido.pop("reglas").items()
    }
    return reglas, contenido
