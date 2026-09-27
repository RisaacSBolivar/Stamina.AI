"""
Logging sin dependencias externas, con redacción de credenciales.

Lo segundo no es adorno. El backend recibe usuario, contraseña y código MFA de
una cuenta real de Garmin, y la promesa es que **no
se persisten en ningún sitio, tampoco en los logs**. Un `extra` con una clave
sensible, o un `repr` de un objeto que la contenga, es la forma más fácil de
romper esa promesa sin darse cuenta. Aquí se corta por lo bajo.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

# Claves cuyo valor nunca se escribe. Se comparan en minúsculas y por subcadena,
# para que `garmin_password` o `mfaCode` caigan igual.
CLAVES_SENSIBLES = (
    "password",
    "contrasena",
    "contraseña",
    "passwd",
    "secret",
    "token",
    "mfa",
    "codigo",
    "credencial",
    "authorization",
    "cookie",
)

REDACTADO = "[redactado]"

# Atributos que `LogRecord` ya usa. Un `extra` con uno de estos nombres revienta
# con KeyError, así que se renombran a `ctx_*`.
_RESERVADAS = frozenset(
    {
        "args", "asctime", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "module", "msecs",
        "message", "msg", "name", "pathname", "process", "processName",
        "relativeCreated", "stack_info", "thread", "threadName", "taskName",
    }
)  # fmt: skip


def _es_sensible(clave: str) -> bool:
    minuscula = clave.lower()
    return any(marca in minuscula for marca in CLAVES_SENSIBLES)


def _redactar(valor: Any) -> Any:
    """Recorre estructuras anidadas tapando lo que no debe salir."""
    if isinstance(valor, dict):
        return {k: (REDACTADO if _es_sensible(str(k)) else _redactar(v)) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_redactar(v) for v in valor]
    return valor


class LoggerSeguro(logging.Logger):
    """
    Renombra los `extra` que chocan con atributos de `LogRecord` y redacta.

    Sin el renombrado, pasar `extra={"module": ...}` revienta con KeyError, y
    justo en la rama de error, que es cuando más falta hace el log.
    """

    def makeRecord(
        self, name, level, fn, lno, msg, args, exc_info, func=None, extra=None, sinfo=None
    ):  # noqa: E501
        if extra:
            limpio = {}
            for clave, valor in extra.items():
                destino = f"ctx_{clave}" if clave in _RESERVADAS else clave
                limpio[destino] = REDACTADO if _es_sensible(clave) else _redactar(valor)
            extra = limpio
        return super().makeRecord(name, level, fn, lno, msg, args, exc_info, func, extra, sinfo)


logging.setLoggerClass(LoggerSeguro)


class FormatoJson(logging.Formatter):
    """Una línea JSON por registro, con los `extra` incorporados."""

    def format(self, record: logging.LogRecord) -> str:
        carga: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        for clave, valor in record.__dict__.items():
            if clave in _RESERVADAS or clave in carga or clave.startswith("_"):
                continue
            try:
                json.dumps(valor)
                carga[clave] = valor
            except (TypeError, ValueError):
                carga[clave] = repr(valor)

        if record.exc_info:
            carga["exception"] = self.formatException(record.exc_info)

        return json.dumps(carga, ensure_ascii=False)


def setup_logging(nivel: str = "INFO", *, json_output: bool = False) -> None:
    raiz = logging.getLogger()
    raiz.handlers.clear()

    manejador = logging.StreamHandler(sys.stdout)
    if json_output:
        manejador.setFormatter(FormatoJson())
    else:
        manejador.setFormatter(logging.Formatter("%(levelname)-8s %(name)-26s %(message)s"))

    raiz.addHandler(manejador)
    raiz.setLevel(nivel)

    # Estas dos son ruidosas y, en el caso de garth/garminconnect, pueden llegar
    # a escribir cabeceras de autenticación en DEBUG.
    for ruidoso in ("httpx", "httpcore", "garth", "garminconnect", "urllib3"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)


def get_logger(nombre: str) -> logging.Logger:
    return logging.getLogger(nombre)
