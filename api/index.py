"""
Entrada de Vercel: la API de `backend/` como una función Python.

Vercel sirve cada archivo de `api/` como una función y busca en él una variable
`app` con una aplicación ASGI. Aquí solo se añade `backend/` al path y se
importa la aplicación tal cual; `vercel.json` manda aquí todo lo que empiece
por `/api/`, y FastAPI ve la ruta original (`/api/v1/...`).

En local no se usa: `make dev` levanta la misma aplicación con uvicorn.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.main import app  # noqa: E402

__all__ = ["app"]
