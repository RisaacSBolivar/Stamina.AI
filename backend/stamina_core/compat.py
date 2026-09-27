"""
Puente para leer los artefactos que el notebook guardó desde `__main__`.

El problema, verificado: `joblib` (o mejor dicho `pickle`) guarda la **referencia**
a la clase, no su código. Las clases vivían en el notebook, así que dentro del
pickle de `metadata.joblib` que escribió el notebook el modelo entrenado está
anotado como `__main__.ModeloTabular`. Al cargarlo desde un módulo, pickle busca
ese atributo en el `__main__` del proceso —que en un backend es uvicorn— y falla:

    AttributeError: Can't get attribute 'ModeloTabular' on <module '__main__'>

Mover las clases a un módulo importable, que es lo que anotaba el notebook como
pendiente, es necesario pero no suficiente. Hay que además publicar los nombres
en `__main__` antes de deserializar. Eso es todo lo que hace este módulo, y por
eso `EstrategiaPipeline.cargar()` lo llama siempre.

El formato de `metadata.joblib` no cambia: esto solo afecta a cómo se lee.
"""

from __future__ import annotations

import sys

from .modelos import BaseFisica, ModeloTabular, RedTerreno, RitmoConstante

# Los nombres que el notebook pudo haber picklado dentro de `modelo_obj`, según
# qué modelo le asignara la regla de capacidad al corredor.
CLASES_PICKLEADAS = {
    "RitmoConstante": RitmoConstante,
    "BaseFisica": BaseFisica,
    "ModeloTabular": ModeloTabular,
    "RedTerreno": RedTerreno,
}


def registrar_alias_main() -> list[str]:
    """
    Publica las clases del pipeline en `__main__` para que pickle las resuelva.

    Solo rellena los nombres que falten: si esto corre dentro del propio
    notebook, `__main__` ya tiene las clases originales y no se pisan. Devuelve
    los nombres que hizo falta añadir, que es información útil para el log.
    """
    principal = sys.modules["__main__"]
    añadidos = []

    for nombre, clase in CLASES_PICKLEADAS.items():
        if not hasattr(principal, nombre):
            setattr(principal, nombre, clase)
            añadidos.append(nombre)

    # `EstrategiaPipeline` no se serializa dentro del artefacto actual, pero se
    # registra por si un artefacto futuro guardara el objeto completo. Import
    # diferido para no crear un ciclo con pipeline.py.
    if not hasattr(principal, "EstrategiaPipeline"):
        from .pipeline import EstrategiaPipeline  # noqa: PLC0415

        principal.EstrategiaPipeline = EstrategiaPipeline
        añadidos.append("EstrategiaPipeline")

    return añadidos
