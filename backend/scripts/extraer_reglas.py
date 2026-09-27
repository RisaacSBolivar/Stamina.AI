"""
Extrae la tabla `reglas` de `modelo/metadata.joblib` a `modelo/reglas.json`.

Es lo único del artefacto que la API necesita para servir peticiones (ver
`stamina_core/reglas.py`, al final). Se corre desde `make modelo` cada vez que
se publica un artefacto nuevo, y la prueba `test_reglas_json_coincide_con_el_artefacto`
avisa si alguien se olvida.

    cd backend && python scripts/extraer_reglas.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import joblib  # noqa: E402

from stamina_core import ARCHIVO_REGLAS, compat, guardar_reglas  # noqa: E402
from stamina_core.config import MODELO_PUBLICADO  # noqa: E402


def main() -> None:
    compat.registrar_alias_main()
    metadatos = joblib.load(MODELO_PUBLICADO / "metadata.joblib")
    destino = MODELO_PUBLICADO / ARCHIVO_REGLAS
    guardar_reglas(
        metadatos["reglas"],
        destino,
        version=metadatos.get("version"),
        creado=metadatos.get("creado"),
        origen="metadata.joblib",
    )
    print(f"Escrito {destino} ({destino.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
