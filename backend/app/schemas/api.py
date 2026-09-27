"""
Esquemas de la API.

De aquí sale el `openapi.json` y, con `make contracts`, los tipos TypeScript del
frontend. Los tipos de la interfaz **no se escriben a mano**: se generan desde
aquí, para que el contrato no se desincronice.

Regla de producto que se refleja en los tipos: toda respuesta que lleve una
estrategia lleva también su `Capacidad`, con el modelo asignado y el motivo si
la respuesta es ritmo constante. La interfaz nunca tiene que inferirlo.

Y una regla de arquitectura: **ninguna respuesta lleva un identificador que haya
que devolver después**, salvo las de Garmin. El historial procesado viaja entero
(`TramosHistorial`) y la estrategia trae consigo sus pasos y su `.FIT`, así que
ninguna petición depende de lo que haya guardado otra.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


class ModeloAPI(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# --- Salud -------------------------------------------------------------------


class InfoReglas(ModeloAPI):
    cargadas: bool
    carpeta: str
    motivo: str | None = Field(default=None, description="Por qué no cargó, si no cargó")
    version_artefacto: str | None = Field(
        default=None, description="Versión del artefacto del que se extrajo la regla"
    )
    creado: str | None = None
    regimenes: list[str] = Field(default_factory=list)


class Salud(ModeloAPI):
    estado: Literal["ok", "degradado"]
    app: str
    version: str
    entorno: str
    reglas: InfoReglas
    garmin_habilitado: bool = Field(
        description="Si la conexión con Garmin está disponible en este despliegue. "
        "Necesita estado en el servidor; `STAMINA_GARMIN_HABILITADO=False` la apaga."
    )
    dependencias: dict[str, str] = Field(description="Versiones de pandas y scikit-learn.")
    sesiones_activas: dict[str, int] = Field(
        description="Sesiones de Garmin y descargas vivas. Nada más se guarda en el servidor."
    )


# --- Capacidad ---------------------------------------------------------------


class Franja(ModeloAPI):
    desde_horas: float
    sesiones: int
    modelo: str
    habilidad: float
    nivel: int


class SiguienteFranja(ModeloAPI):
    desde_horas: float
    modelo: str
    habilidad: float
    horas_faltantes: float


class Capacidad(ModeloAPI):
    """
    Lo que la regla de capacidad responde para unas horas y una distancia.

    `motivo` solo viene cuando `personalizada` es falso:

    - `historial_insuficiente` — todavía no llega al primer presupuesto medido.
    - `sin_evidencia_en_esta_franja` — esta franja no superó al ritmo constante,
      pero otras con más horas sí lo hacen.
    - `distancia_sin_evidencia` — ni con todo el historial medido personaliza
      este régimen. El límite es la distancia, no las horas.
    """

    horas: float
    km_objetivo: float
    regimen: str
    modelo: str
    habilidad_esperada: float
    nivel_capacidad: int
    personalizada: bool
    motivo: (
        Literal[
            "historial_insuficiente",
            "sin_evidencia_en_esta_franja",
            "distancia_sin_evidencia",
        ]
        | None
    ) = None
    siguiente_franja: SiguienteFranja | None = None
    regimen_fiable: bool = Field(
        description="Si la franja con más horas de este régimen personaliza. "
        "Cuando es falso, acumular historial no desbloquea nada aquí."
    )
    regimen_monotono: bool = Field(
        description="Si el nivel de modelo crece con las horas sin bajar nunca. "
        "En maratón es falso: más horas no siempre significan mejor modelo."
    )
    validado_en_km: list[float] = Field(
        description="Rango de distancias con el que se validó este régimen."
    )
    distancia_extrapolada: bool = Field(
        description="La distancia objetivo cae fuera de lo validado (p. ej. una media maratón)."
    )
    franjas: list[Franja]


# --- Historial ---------------------------------------------------------------


class TramosHistorial(ModeloAPI):
    """
    El historial procesado: una fila por cada 100 m de cada sesión, en columnas.

    **Lo guarda el navegador, no el servidor.** Sale de `POST /historial/archivos`
    y vuelve en cada petición que lo necesita. No lleva coordenadas: solo lo que
    el pipeline usa para aprender cómo corre esta persona.
    """

    split: list[int] = Field(description="Número de tramo de 100 m dentro de la sesión")
    v: list[float] = Field(description="Velocidad media, m/s")
    fc: list[float] = Field(description="Frecuencia cardíaca media, bpm")
    cadencia: list[float]
    elev: list[float] = Field(description="Altitud al final del tramo, m")
    temperatura: list[float | None] = Field(description="°C; null si el reloj no la grabó")
    t_fin: list[float] = Field(description="Segundos desde el inicio de la sesión")
    n_registros: list[int]
    actividad: list[str] = Field(description="Identificador de la sesión (el nombre del .FIT)")
    fecha: list[str] = Field(description="AAAA-MM-DD")

    @model_validator(mode="after")
    def _mismo_largo(self) -> TramosHistorial:
        largos = {len(getattr(self, campo)) for campo in type(self).model_fields}
        if len(largos) != 1:
            raise ValueError("Todas las columnas de los tramos tienen que tener el mismo largo.")
        return self

    @property
    def n_tramos(self) -> int:
        return len(self.split)


class HistorialProcesado(ModeloAPI):
    tramos: TramosHistorial
    control_calidad: dict[str, int] = Field(
        description="Cuántos archivos se descartaron y por qué motivo."
    )


class PeticionResumen(ModeloAPI):
    tramos: TramosHistorial
    km_objetivo: float | None = Field(
        default=None, gt=0, le=500, description="Si se indica, se consulta la regla de capacidad"
    )


class ResumenHistorial(ModeloAPI):
    horas: float
    sesiones: int
    km_totales: float
    desde: str
    hasta: str
    capacidad: Capacidad | None = Field(
        default=None,
        description="Solo si se indicó km_objetivo.",
    )


# --- Objetivo de carrera -----------------------------------------------------


ClaveObjetivo = Literal[
    "maximizar rendimiento", "mejor marca", "terminar sin fatiga", "ritmo conservador"
]


class OpcionObjetivo(ModeloAPI):
    clave: ClaveObjetivo
    etiqueta: str
    descripcion: str
    factor: float
    por_defecto: bool


class ReferenciaEsfuerzo(ModeloAPI):
    fecha: str
    km: float
    minutos: float
    ritmo_min_km: float


class PeticionSugerencia(ModeloAPI):
    tramos: TramosHistorial
    km_objetivo: float = Field(gt=0, le=500)
    objetivo: ClaveObjetivo = "terminar sin fatiga"


class Sugerencia(ModeloAPI):
    """
    Un tiempo objetivo sugerido a partir del historial del propio corredor.

    **No es una predicción del modelo.** Es una extrapolación de Riegel sobre su
    mejor esfuerzo reciente, y por eso `editable` es siempre verdadero: es un
    punto de partida que el corredor puede cambiar.
    """

    objetivo: ClaveObjetivo
    etiqueta: str
    km_objetivo: float
    tiempo_objetivo_h: float | None
    ritmo_medio_min_km: float | None = None
    editable: bool
    motivo: str | None = Field(default=None, description="Por qué no se pudo sugerir nada")
    metodo: str | None = None
    referencia: ReferenciaEsfuerzo | None = None
    factor: float


# --- Estrategia --------------------------------------------------------------


class FilaKm(ModeloAPI):
    km: int
    ritmo_objetivo: float = Field(description="min/km")
    fc_objetivo: float = Field(description="bpm")
    pendiente: float = Field(description="%")
    elevacion: float = Field(description="msnm")
    zona: str
    tiempo_min: float
    tiempo_acum_min: float


class PuntoAltimetria(ModeloAPI):
    dist_km: float
    elevacion: float


class Indicadores(ModeloAPI):
    tiempo_estimado_h: float
    desnivel_positivo_m: float
    pendiente_maxima_pct: float
    pct_exigencia_alta: float
    fc_objetivo_media: float


class InfoRuta(ModeloAPI):
    nombre: str
    km_totales: float
    tramos: int


class EntradaEstrategia(ModeloAPI):
    tiempo_objetivo_h: float
    temperatura_c: float


# --- Exportación -------------------------------------------------------------


class PasoEntrenamiento(ModeloAPI):
    km_inicio: int
    km_fin: int
    km: float
    zona: str
    ritmo_min: float
    ritmo_max: float
    fc_min: float
    fc_max: float
    minutos: float
    nombre: str
    notas: str


class Entrenamiento(ModeloAPI):
    nombre: str
    pasos: list[PasoEntrenamiento]
    segundos_estimados: float
    payload_garmin: dict = Field(
        description="El mismo entrenamiento en el esquema JSON de Garmin Connect."
    )
    aviso: str


class ArchivoFit(ModeloAPI):
    nombre_archivo: str
    contenido_base64: str = Field(
        description="El .FIT del entrenamiento (unos cientos de bytes), listo para descargar."
    )


class Estrategia(ModeloAPI):
    ruta: InfoRuta
    entrada: EntradaEstrategia
    capacidad: Capacidad
    indicadores: Indicadores
    tabla_km: list[FilaKm]
    altimetria: list[PuntoAltimetria]
    reparto_zonas: dict[str, float]
    entrenamiento: Entrenamiento = Field(
        description="Los pasos para el reloj, ya compilados: no hay que pedirlos aparte."
    )
    fit: ArchivoFit


# --- Garmin ------------------------------------------------------------------


class PeticionLoginGarmin(ModeloAPI):
    """
    Credenciales de una cuenta real de Garmin Connect.

    No se guardan en ningún sitio: ni en disco, ni en base de datos, ni en los
    logs. La sesión vive en memoria y caduca a los 15 minutos.
    """

    correo: str = Field(min_length=3, max_length=254)
    contrasena: SecretStr = Field(min_length=1, max_length=256)


class PeticionMfaGarmin(ModeloAPI):
    sesion_garmin_id: str
    codigo: SecretStr = Field(min_length=4, max_length=16)


class SesionGarmin(ModeloAPI):
    sesion_garmin_id: str
    autenticada: bool
    requiere_mfa: bool
    correo: str = Field(description="Enmascarado a propósito")
    caduca_en_segundos: int
    aviso: str


class PeticionDescargaGarmin(ModeloAPI):
    sesion_garmin_id: str
    # 135 h es el default que justifica la curva de capacidad, no un número
    # redondo: la última franja medida empieza en 124.7 h, y como aquí se cuentan
    # horas **brutas** (las actividades que luego suspenden el control de calidad
    # ya van sumadas), hace falta ese margen para llegar. Quien quiera esperar
    # menos lo baja desde la interfaz. Ver docs/METODOLOGIA.md.
    objetivo_horas: float = Field(
        default=135.0,
        gt=0,
        le=300,
        description="Horas brutas de actividades a descargar; el control de calidad descarta algunas.",
    )
    confirmado: bool = Field(
        default=False,
        description="Tiene que ser true. La descarga nunca se dispara sola.",
    )


class EstadoDescarga(ModeloAPI):
    """
    El progreso de una descarga de Garmin.

    Se consulta cada pocos segundos mientras dura. El porcentaje es real: se
    calcula sobre las horas pedidas, que se conocen antes de empezar.
    """

    tarea_id: str
    estado: Literal["en_curso", "terminada", "fallida", "cancelada"]
    actividades: int = Field(description="Actividades descargadas hasta ahora.")
    horas: float
    objetivo_horas: float
    porcentaje: float
    segundos: float
    resultado: HistorialProcesado | None = Field(
        default=None, description="Solo cuando el estado es «terminada»."
    )
    error: str | None = None
    codigo_error: str | None = None


class EntrenamientoParaSubir(ModeloAPI):
    """Lo que devolvió `POST /estrategia` en `entrenamiento`, de vuelta para subirlo."""

    nombre: str = Field(min_length=1, max_length=64)
    segundos_estimados: float = Field(gt=0)
    pasos: list[PasoEntrenamiento] = Field(min_length=1, max_length=100)


class PeticionSubidaGarmin(ModeloAPI):
    sesion_garmin_id: str
    entrenamiento: EntrenamientoParaSubir
    confirmado: bool = Field(
        default=False,
        description="Tiene que ser true. La subida nunca se dispara sola.",
    )


class ResultadoSubida(ModeloAPI):
    workout_id: int | str | None
    nombre: str | None
    pasos_segun_garmin: list[dict]
    todos_por_distancia: bool = Field(
        description="Si algún paso saliera como lap.button, el reloj esperaría el "
        "botón de vuelta en vez de avanzar por distancia."
    )
    aviso: str


# --- Salir -------------------------------------------------------------------


class PeticionOlvidar(ModeloAPI):
    """
    Lo que el cliente dice tener vivo en el servidor.

    Solo puede ser de Garmin: el historial y la estrategia nunca se guardan allí.
    Todos opcionales: se borra lo que haya, sin informar de qué seguía vivo.
    """

    sesion_garmin_id: str | None = None
    tarea_id: str | None = Field(
        default=None, description="Una descarga de Garmin, que retiene el historial reunido"
    )


class ResultadoOlvidar(ModeloAPI):
    borrados: list[str] = Field(
        default_factory=list, description="Qué se soltó de memoria, para poder verlo en los tests."
    )


# --- Errores -----------------------------------------------------------------


class DetalleError(ModeloAPI):
    code: str
    message: str
    details: dict = Field(default_factory=dict)


class RespuestaError(ModeloAPI):
    error: DetalleError


# El manejador de `core.errors` serializa TODOS los StaminaError con esta
# forma. Declararlo aquí hace que baje al OpenAPI y de ahí a `schema.d.ts`,
# para que el cliente no tenga que volver a escribir el tipo a mano.
#
# El 422 no está en la lista a propósito: ahí conviven este sobre y el
# HTTPValidationError que pone FastAPI sola, y anunciar solo uno sería falso.
RESPUESTAS_ERROR: dict[int | str, dict] = {
    401: {"model": RespuestaError, "description": "Garmin rechazó las credenciales"},
    403: {"model": RespuestaError, "description": "Garmin no está disponible en este despliegue"},
    404: {"model": RespuestaError, "description": "El recurso no existe o ya caducó"},
    428: {"model": RespuestaError, "description": "Falta confirmación explícita"},
    429: {"model": RespuestaError, "description": "Garmin no deja pasar ahora"},
    500: {"model": RespuestaError, "description": "Error no previsto"},
    502: {"model": RespuestaError, "description": "Garmin no responde o responde mal"},
    503: {"model": RespuestaError, "description": "La regla de capacidad no está cargada"},
}
