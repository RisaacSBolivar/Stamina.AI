"""
Integración con Garmin Connect: login, descarga de historial y subida.

**Lee esto antes de tocar nada.** Este módulo recibe usuario, contraseña y
código MFA de una cuenta real de terceros. Es una decisión del autor, tomada
sabiendo el riesgo. Las garantías que sí están implementadas:

1. **Nada se persiste.** No se llama a `login(tokenstore)`, que es lo que hace el
   notebook para reanudar sesión: eso escribiría el token en `~/.garminconnect`.
   Aquí el cliente autenticado vive en memoria, con caducidad corta.
2. **La contraseña se borra del cliente** en cuanto el login termina. La librería
   la guarda en `self.password`; no hay razón para que siga ahí.
3. **Nunca se escribe en los logs.** El logger redacta por nombre de clave
   (`app/core/logging.py`) y aquí solo se registra el correo enmascarado.
4. **El historial descargado no toca el disco.** Se parsea en memoria y se tira.
   Son datos de salud y de localización de otra persona.
5. **Ninguna operación es automática.** Descargar y subir exigen `confirmado=true`
   en cada petición.

Lo que sigue siendo cierto pese a todo lo anterior: un backend que recibe
credenciales de terceros por HTTP es una superficie de ataque que el notebook,
con `getpass` en local, no tenía. No se disimula en la interfaz.

La API de Garmin Connect que usa `garminconnect` **no es oficial** y puede
cambiar sin aviso.
"""

from __future__ import annotations

import contextlib
import io
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from app.core.errors import GarminAutenticacion, GarminError, GarminLimite
from app.core.logging import get_logger
from stamina_core import procesar_fit
from stamina_core.config import TIPOS_CARRERA

log = get_logger(__name__)


@dataclass
class SesionGarmin:
    """
    Una sesión autenticada, en memoria y con caducidad.

    `estado_mfa` solo está poblado mientras el login espera el código; se borra
    en cuanto se completa.
    """

    cliente: Any = None
    estado_mfa: dict[str, Any] | None = None
    correo_enmascarado: str = ""
    autenticada: bool = False
    creada: float = field(default_factory=time.time)


def _enmascarar(correo: str) -> str:
    """`isaac@gmail.com` -> `i***c@gmail.com`. Para poder rastrear sin exponer."""
    if "@" not in correo:
        return "***"
    usuario, dominio = correo.split("@", 1)
    if len(usuario) <= 2:
        return f"{usuario[:1]}***@{dominio}"
    return f"{usuario[0]}***{usuario[-1]}@{dominio}"


# La librería prueba varias vías de login y, si fallan todas, lanza el error de
# la ÚLTIMA. Eso engaña: lo habitual es que las primeras devuelvan 429 (la IP
# está limitada) y la última hable de Cloudflare, así que el usuario lee «bot
# challenge» cuando el problema real es el límite de peticiones.
MARCAS_LOGIN_AGOTADO = ("strategies exhausted", "bot challenge", "cloudflare")


def _traducir(error: Exception) -> GarminError:
    """Convierte los errores de la librería en errores de dominio."""
    import garminconnect

    texto = str(error)
    minusculas = texto.lower()

    if isinstance(error, garminconnect.GarminConnectTooManyRequestsError) or "429" in texto:
        return GarminLimite("Garmin está limitando las peticiones. Espera un minuto y reintenta.")

    if any(marca in minusculas for marca in MARCAS_LOGIN_AGOTADO):
        return GarminLimite(
            "Garmin no acepta ahora mismo el acceso automático desde esta red: rechazó la "
            "conexión antes de comprobar tus credenciales, así que no es tu contraseña. "
            "Suele ser el límite de peticiones por IP y se pasa solo al cabo de un rato. "
            "Mientras tanto puedes exportar tus actividades desde Garmin Connect y subir "
            "los .FIT a mano, que es el mismo flujo sin la cuenta.",
            details={"detalle_tecnico": texto},
        )

    if isinstance(error, garminconnect.GarminConnectAuthenticationError):
        return GarminAutenticacion("Garmin rechazó las credenciales.")

    return GarminError(f"Garmin Connect devolvió un error: {texto}")


def _olvidar_contrasena(cliente: Any) -> None:
    """Borra la contraseña del objeto cliente en cuanto deja de hacer falta."""
    for atributo in ("password", "_password"):
        if hasattr(cliente, atributo):
            # Si la librería protege el atributo, no se insiste: lo importante
            # es no dejarlo colgando cuando sí se puede borrar.
            with contextlib.suppress(Exception):
                setattr(cliente, atributo, None)


# --- Login -------------------------------------------------------------------


def iniciar_sesion(correo: str, contrasena: str) -> SesionGarmin:
    """
    Primer paso del login. Puede quedar pendiente de MFA.

    Nótese que `login()` se llama **sin** `tokenstore`: no se guarda ningún token
    en disco, a diferencia del notebook.
    """
    from garminconnect import Garmin

    sesion = SesionGarmin(correo_enmascarado=_enmascarar(correo))

    try:
        cliente = Garmin(correo, contrasena, return_on_mfa=True)
        resultado, estado = cliente.login()
    except Exception as error:
        log.warning(
            "Login de Garmin fallido",
            extra={"correo": sesion.correo_enmascarado, "tipo": type(error).__name__},
        )
        raise _traducir(error) from error

    sesion.cliente = cliente

    if resultado == "needs_mfa":
        sesion.estado_mfa = estado
        log.info("Garmin pide MFA", extra={"correo": sesion.correo_enmascarado})
        return sesion

    sesion.autenticada = True
    _olvidar_contrasena(cliente)
    log.info("Sesión de Garmin iniciada", extra={"correo": sesion.correo_enmascarado})
    return sesion


def completar_mfa(sesion: SesionGarmin, codigo: str) -> SesionGarmin:
    """Segundo paso: el código de verificación."""
    if sesion.estado_mfa is None:
        raise GarminAutenticacion("Esta sesión no está esperando un código MFA.")

    try:
        sesion.cliente.resume_login(sesion.estado_mfa, codigo)
    except Exception as error:
        log.warning(
            "Código MFA rechazado",
            extra={"correo": sesion.correo_enmascarado, "tipo": type(error).__name__},
        )
        raise _traducir(error) from error

    sesion.estado_mfa = None
    sesion.autenticada = True
    _olvidar_contrasena(sesion.cliente)
    log.info("MFA completado", extra={"correo": sesion.correo_enmascarado})
    return sesion


def exigir_autenticada(sesion: SesionGarmin) -> None:
    if not sesion.autenticada:
        raise GarminAutenticacion(
            "La sesión de Garmin no está completa. Falta el código MFA."
            if sesion.estado_mfa
            else "La sesión de Garmin no está autenticada."
        )


# --- Descarga del historial --------------------------------------------------


class DescargaCancelada(Exception):
    """
    La persona paró la descarga a mitad.

    No hereda de `StaminaError` a propósito: no es un fallo del sistema ni algo
    que haya que traducir a una respuesta HTTP. Es una salida ordenada, y quien
    la lanza y quien la recoge están en el mismo hilo.
    """


def descargar_historial(
    sesion: SesionGarmin,
    objetivo_horas: float,
    tam_pagina: int = 100,
    pausa: float = 0.6,
    max_reintentos: int = 4,
    progreso: Callable[[int, float], None] | None = None,
    cancelado: Callable[[], bool] | None = None,
) -> tuple[pd.DataFrame, dict]:
    """
    Baja actividades de carrera hasta juntar `objetivo_horas` y las parsea.

    A diferencia del notebook, **nada se escribe en disco**: cada archivo se
    descomprime, se parsea y se descarta. Son datos de salud y localización de
    otra persona, y el servidor no tiene por qué conservarlos.

    `progreso` se llama tras cada actividad con `(descargadas, horas)`. Esto
    tarda entre diez y veinte minutos —0.6 s de pausa obligatoria por actividad
    contra el límite de peticiones de Garmin, más la descarga—, así que quien
    llama necesita poder contarlo. Es opcional: sin él, todo sigue igual.

    `cancelado` se consulta antes de cada actividad y corta con
    `DescargaCancelada`. Es cooperativo porque no hay otra forma: a un hilo de
    Python no se le puede pedir que muera. Se mira **antes** de bajar el
    archivo y no después, para no gastar contra Garmin una petición que ya
    nadie quiere.
    """
    exigir_autenticada(sesion)
    cliente = sesion.cliente

    tablas: list[pd.DataFrame] = []
    motivos: dict[str, int] = {}
    horas = 0.0
    descargadas = 0
    desde = 0

    while horas < objetivo_horas:
        if cancelado is not None and cancelado():
            raise DescargaCancelada

        try:
            lote = cliente.get_activities(desde, tam_pagina)
        except Exception as error:
            raise _traducir(error) from error

        if not lote:
            break
        desde += len(lote)

        for actividad in lote:
            # En el lote pueden quedar cien actividades, a segundo y pico cada
            # una: sin este corte, cancelar tardaria minutos en notarse.
            if cancelado is not None and cancelado():
                raise DescargaCancelada

            if (actividad.get("activityType") or {}).get("typeKey") not in TIPOS_CARRERA:
                continue

            id_actividad = actividad.get("activityId")
            duracion_h = (actividad.get("duration") or 0) / 3600
            fecha = (actividad.get("startTimeLocal") or "sin_fecha")[:10]

            contenido = _descargar_fit(cliente, id_actividad, pausa, max_reintentos)
            if contenido is None:
                motivos["no se pudo descargar"] = motivos.get("no se pudo descargar", 0) + 1
                continue

            motivo, tramos = procesar_fit(contenido, nombre=f"{fecha}_{id_actividad}")
            motivos[motivo] = motivos.get(motivo, 0) + 1
            if motivo == "ok" and tramos is not None:
                tablas.append(tramos)

            horas += duracion_h
            descargadas += 1
            if progreso is not None:
                progreso(descargadas, horas)

            if horas >= objetivo_horas:
                break

    if not tablas:
        raise GarminError(
            "No se pudo reunir ninguna actividad de carrera utilizable de esa cuenta.",
            details={"control_calidad": motivos, "actividades_vistas": descargadas},
        )

    log.info(
        "Historial descargado de Garmin",
        extra={
            "correo": sesion.correo_enmascarado,
            "actividades": descargadas,
            "horas": round(horas, 1),
            "control_calidad": motivos,
        },
    )
    return pd.concat(tablas, ignore_index=True), motivos


def _descargar_fit(cliente, id_actividad, pausa: float, max_reintentos: int) -> bytes | None:
    """Baja una actividad en formato original y saca el .FIT del zip."""
    for intento in range(max_reintentos):
        try:
            crudo = cliente.download_activity(
                id_actividad, dl_fmt=cliente.ActivityDownloadFormat.ORIGINAL
            )
            with zipfile.ZipFile(io.BytesIO(crudo)) as comprimido:
                for nombre in comprimido.namelist():
                    if nombre.lower().endswith(".fit"):
                        time.sleep(pausa)
                        return comprimido.read(nombre)
            return None
        except Exception as error:
            # El 429 es límite de peticiones: se espera más en cada intento.
            if "429" in str(error):
                time.sleep(20 * (intento + 1))
            else:
                log.debug(
                    "Actividad saltada",
                    extra={"actividad": id_actividad, "tipo": type(error).__name__},
                )
                return None
    return None


# --- Subida del entrenamiento ------------------------------------------------


def subir_entrenamiento(sesion: SesionGarmin, payload: dict) -> dict:
    """
    Sube el entrenamiento a la cuenta y comprueba qué interpretó Garmin.

    La comprobación no es opcional: Garmin reinterpreta los identificadores, y
    fue justo así como se descubrió que `conditionTypeId = 1` es `lap.button` y
    no distancia. Se devuelve lo que Garmin asignó a cada paso para poder verlo.
    """
    exigir_autenticada(sesion)

    try:
        respuesta = sesion.cliente.upload_workout(payload)
    except Exception as error:
        raise _traducir(error) from error

    pasos = []
    try:
        for paso in respuesta["workoutSegments"][0]["workoutSteps"]:
            pasos.append(
                {
                    "orden": paso["stepOrder"],
                    "condicion": paso["endCondition"]["conditionTypeKey"],
                    "valor": float(paso["endConditionValue"]),
                }
            )
    except (KeyError, IndexError, TypeError):
        # Si Garmin cambia la forma de la respuesta, no se pierde la subida.
        pasos = []

    id_entrenamiento = respuesta.get("workoutId")
    log.info(
        "Entrenamiento subido a Garmin",
        extra={
            "correo": sesion.correo_enmascarado,
            "workout_id": id_entrenamiento,
            "pasos": len(pasos),
        },
    )

    return {
        "workout_id": id_entrenamiento,
        "nombre": respuesta.get("workoutName"),
        "pasos_segun_garmin": pasos,
        # Si esto sale en `lap.button`, los pasos esperarían el botón de vuelta
        # en vez de avanzar por distancia.
        "todos_por_distancia": bool(pasos) and all(p["condicion"] == "distance" for p in pasos),
    }


def cerrar_sesion(sesion: SesionGarmin) -> None:
    """Suelta el cliente y lo que pudiera quedar colgando de él."""
    _olvidar_contrasena(sesion.cliente)
    sesion.estado_mfa = None
    sesion.cliente = None
    sesion.autenticada = False
