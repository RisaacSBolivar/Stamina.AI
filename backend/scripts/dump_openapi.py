"""
Vuelca el esquema OpenAPI a un archivo.

Importa la app y serializa `app.openapi()` en vez de hacer curl contra un
servidor vivo: no depende de puertos ni de tiempos de arranque, y funciona igual
en cualquier máquina.

Uso:
    python scripts/dump_openapi.py ../frontend/openapi.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app  # noqa: E402

DESTINO_POR_DEFECTO = Path("openapi.json")


def main() -> int:
    destino = Path(sys.argv[1]) if len(sys.argv) > 1 else DESTINO_POR_DEFECTO
    destino.parent.mkdir(parents=True, exist_ok=True)

    esquema = app.openapi()
    destino.write_text(json.dumps(esquema, indent=2, ensure_ascii=False), encoding="utf-8")

    rutas = len(esquema.get("paths", {}))
    modelos = len(esquema.get("components", {}).get("schemas", {}))
    print(f"Escrito {destino} · {rutas} rutas · {modelos} modelos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
