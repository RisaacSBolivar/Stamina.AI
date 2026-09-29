"""
Almacén en memoria con caducidad, solo para Garmin.

La API no guarda el historial ni la estrategia de nadie: el historial procesado
vuelve al navegador y viaja en cada cálculo, así que ninguna petición depende de
que otra haya caído en el mismo proceso. Eso es lo que permite desplegarla sin
estado.

Lo único que vive aquí es Garmin, que no se puede hacer sin estado: la sesión
autenticada (login y MFA son dos peticiones) y la descarga en segundo plano.
Caducan solas y nada toca el disco: las credenciales de una cuenta de terceros
no se persisten en ningún sitio. Donde las peticiones de una persona no caigan
en el mismo proceso, `garmin_habilitado` lo apaga.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

from app.core.errors import RecursoNoEncontrado


@dataclass
class _Entrada[T]:
    valor: T
    expira_en: float


class AlmacenTTL[T]:
    """
    Diccionario con caducidad, seguro entre hilos.

    `uvicorn` puede atender peticiones desde varios hilos, así que el candado no
    es opcional. La purga es perezosa: se limpia al escribir, que es cuando
    importa que no crezca sin límite.
    """

    def __init__(self, ttl_segundos: int, nombre: str = "recurso") -> None:
        self.ttl = ttl_segundos
        self.nombre = nombre
        self._datos: dict[str, _Entrada[T]] = {}
        self._candado = threading.Lock()

    def guardar(self, valor: T, ttl: int | None = None) -> str:
        identificador = uuid.uuid4().hex[:16]
        with self._candado:
            self._purgar()
            self._datos[identificador] = _Entrada(
                valor=valor, expira_en=time.time() + (ttl or self.ttl)
            )
        return identificador

    def reemplazar(self, identificador: str, valor: T, ttl: int | None = None) -> None:
        """Actualiza una entrada existente conservando su identificador."""
        with self._candado:
            self._datos[identificador] = _Entrada(
                valor=valor, expira_en=time.time() + (ttl or self.ttl)
            )

    def obtener(self, identificador: str) -> T:
        with self._candado:
            entrada = self._datos.get(identificador)
            # El identificador va en `details` y no en el mensaje: el mensaje lo
            # lee una persona, y una cadena hexadecimal no le dice nada.
            if entrada is None:
                raise RecursoNoEncontrado(
                    f"No encuentro {self.nombre}: puede que haya caducado. Vuelve a empezar.",
                    details={"identificador": identificador},
                )
            if entrada.expira_en < time.time():
                del self._datos[identificador]
                raise RecursoNoEncontrado(
                    f"La sesión de {self.nombre} caducó. Vuelve a empezar.",
                    details={"identificador": identificador, "caducado": True},
                )
            return entrada.valor

    def borrar(self, identificador: str) -> None:
        with self._candado:
            self._datos.pop(identificador, None)

    def __len__(self) -> int:
        with self._candado:
            self._purgar()
            return len(self._datos)

    def _purgar(self) -> None:
        """Elimina lo caducado. Se llama con el candado ya tomado."""
        ahora = time.time()
        for clave in [k for k, v in self._datos.items() if v.expira_en < ahora]:
            del self._datos[clave]


# Instancias que usa la API. Se crean al importar y viven con el proceso.
sesiones_garmin: AlmacenTTL[Any] = AlmacenTTL(ttl_segundos=900, nombre="la sesión de Garmin")
# Una descarga de Garmin tarda minutos y el frontend la va consultando; el
# resultado tiene que sobrevivir a la espera con holgura.
tareas: AlmacenTTL[Any] = AlmacenTTL(ttl_segundos=3600, nombre="la descarga")


def configurar(ttl_garmin: int) -> None:
    """Ajusta el TTL de la sesión de Garmin desde la configuración, al arrancar."""
    sesiones_garmin.ttl = ttl_garmin
