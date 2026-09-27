"""
Lectura de archivos crudos y construcción del dataset de modelado.

Secciones 0.3, 0.4, 1.2 y 2.1 del notebook. La rejilla es de tramos de 100 m y
el control de calidad descarta lo que no es una carrera continua; con los 492
archivos del autor sobrevivieron 460 actividades.
"""

from __future__ import annotations

import glob
import io
import json
import os
import re
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

from .config import (
    CAMPOS_FIT,
    CAMPOS_NECESARIOS,
    FC_MIN,
    LIMITES_FC_RATIO,
    LIMITES_V_RATIO,
    MIN_REGISTROS_SPLIT,
    SPLIT_M,
    SUAVIZADO_OBJETIVO,
    V_MAX,
    V_MIN,
    Rutas,
)
from .lector_fit import leer_records
from .variables import variables_terreno

# Los archivos que bajó el notebook se llaman AAAA-MM-DD_<id>.fit, y de ahí
# salía la fecha. Un archivo subido por un usuario no tiene por qué seguir esa
# convención, así que el patrón decide de dónde leerla.
PATRON_NOMBRE_FECHADO = re.compile(r"^\d{4}-\d{2}-\d{2}_")

# Cuántos procesos usa el parseo en paralelo, y a partir de cuántos archivos
# compensa arrancarlos. Los dos números están medidos, no elegidos: ver
# `parsear_lote`.
N_JOBS_PARSEO = 6
MIN_ARCHIVOS_PARALELO = 12


def procesar_fit(
    archivo,
    split_m: int = SPLIT_M,
    min_registros: int = MIN_REGISTROS_SPLIT,
    nombre: str | None = None,
) -> tuple[str, pd.DataFrame | None]:
    """
    Lee un .FIT y lo agrega a tramos de `split_m` metros.

    Devuelve una tupla (motivo, tabla). Si el archivo no pasa el control de
    calidad, `motivo` explica por qué y `tabla` es None. Se guarda el motivo
    para poder contar después cuántos archivos se cayeron y por qué.

    `archivo` puede ser una ruta o bytes (subida por la API). Con bytes hay que
    pasar `nombre`, porque de él sale el identificador de la actividad.
    """
    if isinstance(archivo, (bytes, bytearray)):
        if nombre is None:
            raise ValueError("Al pasar el .FIT como bytes hace falta `nombre`.")
    else:
        nombre = nombre if nombre is not None else Path(archivo).stem

    try:
        # Leer la ruta dentro del try, como antes: un archivo que no se puede
        # abrir cuenta como ilegible y no tumba el lote entero.
        if isinstance(archivo, (bytes, bytearray)):
            datos = bytes(archivo)
        else:
            datos = Path(archivo).read_bytes()
        registros = leer_registros(datos)
    except Exception:
        return ("archivo ilegible", None)

    df = pd.DataFrame(registros)
    if df.empty:
        return ("sin registros", None)

    faltantes = [c for c in CAMPOS_NECESARIOS if c not in df.columns]
    if faltantes:
        return ("sin " + ", ".join(faltantes), None)

    # La temperatura es opcional: hay relojes (y actividades) que no la graban.
    # Sin esta línea el groupby de abajo truena con KeyError.
    if "temperature" not in df.columns:
        df["temperature"] = np.nan

    df = df.dropna(subset=CAMPOS_NECESARIOS)
    if len(df) < 60:
        return ("sesión demasiado corta", None)
    if df["enhanced_speed"].median() < 1.5 or df["cadence"].median() < 50:
        return ("no es carrera continua", None)

    df = df.sort_values("timestamp")
    df["t_s"] = (df["timestamp"] - df["timestamp"].min()).dt.total_seconds()
    df["split"] = (df["distance"] // split_m).astype(int)

    tramos = (
        df.groupby("split")
        .agg(
            v=("enhanced_speed", "mean"),
            fc=("heart_rate", "mean"),
            cadencia=("cadence", "mean"),
            elev=("enhanced_altitude", "last"),
            temperatura=("temperature", "mean"),
            t_fin=("t_s", "last"),
            n_registros=("t_s", "size"),
        )
        .reset_index()
    )

    tramos = tramos[tramos["n_registros"] >= min_registros]
    if tramos.empty:
        return ("sin splits válidos", None)

    tramos["actividad"] = nombre
    tramos["fecha"] = _fecha_de(nombre, df)
    return ("ok", tramos)


def leer_registros(datos: bytes) -> list[dict]:
    """
    Los mensajes `record` de un .FIT, con los campos de `CAMPOS_FIT`.

    Primero con el lector propio (`lector_fit`), que es unas diez veces más
    rápido. Si no puede —campos de desarrollador, o un archivo que no entiende—
    lo lee fitparse, que es lo que se usaba antes: así un archivo nunca da un
    resultado distinto del de siempre, a lo sumo tarda lo de siempre.
    """
    try:
        return leer_records(datos)
    except Exception:
        import fitparse  # noqa: PLC0415

        mensajes = fitparse.FitFile(io.BytesIO(datos)).get_messages("record")
        return [
            {campo.name: campo.value for campo in fila if campo.name in CAMPOS_FIT}
            for fila in mensajes
        ]


def _fecha_de(nombre: str, df: pd.DataFrame) -> str:
    """
    La fecha de la actividad, en AAAA-MM-DD.

    Si el nombre sigue la convención del notebook se usa, para que reprocesar el
    historial del autor dé exactamente el mismo parquet que antes. Si no —caso
    de un archivo subido como `activity.fit`— se lee del propio .FIT. Sin este
    arreglo la fecha saldría troceada del nombre (`'activity.f'`) y rompería el
    orden cronológico del que dependen las horas acumuladas.
    """
    if PATRON_NOMBRE_FECHADO.match(nombre):
        return nombre[:10]
    return str(pd.Timestamp(df["timestamp"].min()).date())


def procesar_gpx(ruta_archivo, split_m: int = SPLIT_M) -> pd.DataFrame:
    """Lee un .GPX de ruta y lo lleva a la misma rejilla de tramos."""
    import gpxpy  # noqa: PLC0415
    from haversine import Unit, haversine  # noqa: PLC0415

    if isinstance(ruta_archivo, (bytes, bytearray)):
        gpx = gpxpy.parse(io.StringIO(ruta_archivo.decode("utf-8", errors="replace")))
    else:
        with open(ruta_archivo) as archivo:
            gpx = gpxpy.parse(archivo)

    puntos = []
    distancia = 0.0
    anterior = None

    for track in gpx.tracks:
        for segmento in track.segments:
            for punto in segmento.points:
                if anterior is not None:
                    distancia += haversine(
                        (anterior.latitude, anterior.longitude),
                        (punto.latitude, punto.longitude),
                        unit=Unit.METERS,
                    )
                puntos.append({"elevacion_msnm": punto.elevation, "distancia_acum_m": distancia})
                anterior = punto

    if not puntos:
        raise ValueError("El .GPX no tiene puntos de track legibles.")

    crudo = pd.DataFrame(puntos)
    crudo["elevacion_msnm"] = crudo["elevacion_msnm"].interpolate(limit_direction="both")
    crudo["split"] = (crudo["distancia_acum_m"] // split_m).astype(int)

    return crudo.groupby("split").agg(elev=("elevacion_msnm", "last")).reset_index()


def perfil_temporal(splits: pd.DataFrame, split_m: int = SPLIT_M) -> pd.DataFrame:
    """Una fila por sesión, ordenadas por fecha y con el tiempo acumulado."""
    sesiones = (
        splits.groupby("actividad")
        .agg(
            fecha=("fecha", "first"),
            segundos=("t_fin", "max"),
            km=("split", lambda s: (s.max() + 1) * split_m / 1000),
            v_media=("v", "mean"),
            fc_media=("fc", "mean"),
            dpos=("elev", lambda s: s.diff().clip(lower=0).sum()),
            n_splits=("v", "size"),
        )
        .reset_index()
    )

    sesiones["minutos"] = sesiones["segundos"] / 60
    sesiones["ritmo"] = 1000 / 60 / sesiones["v_media"]
    sesiones = sesiones.sort_values("fecha").reset_index(drop=True)
    sesiones["horas_acum"] = sesiones["minutos"].cumsum() / 60
    sesiones["sesiones_acum"] = np.arange(1, len(sesiones) + 1)
    return sesiones


def construir_dataset(splits: pd.DataFrame) -> pd.DataFrame:
    """
    Del historial en rejilla al dataset de modelado.

    Reproduce la sección 2.1 del notebook: limpieza de tramos, variables de
    terreno por actividad, y el objetivo relativo winsorizado y suavizado a
    500 m. Ese tratamiento del objetivo movió la habilidad de -0.004 a 0.052,
    así que no es cosmético.
    """
    base = splits[splits["v"].between(V_MIN, V_MAX) & (splits["fc"] > FC_MIN)]
    if base.empty:
        raise ValueError(
            "Ningún tramo pasó la limpieza (velocidad 1-7 m/s y FC > 60). "
            "¿Seguro que son sesiones de carrera?"
        )

    dataset = pd.concat(
        [variables_terreno(t) for _, t in base.groupby("actividad")], ignore_index=True
    )
    dataset["temperatura"] = dataset["temperatura"].fillna(dataset["temperatura"].median())
    # Si ninguna actividad traía temperatura la mediana es NaN y el modelo
    # recibiría nulos. 18 grados es el mismo default que usa predecir_ruta.
    dataset["temperatura"] = dataset["temperatura"].fillna(18.0)

    dataset["v_crudo"] = dataset["v"] / dataset.groupby("actividad")["v"].transform("mean")
    dataset["fc_crudo"] = dataset["fc"] / dataset.groupby("actividad")["fc"].transform("mean")
    dataset["v_ratio"] = dataset["v_crudo"].clip(*LIMITES_V_RATIO)
    dataset["fc_ratio"] = dataset["fc_crudo"].clip(*LIMITES_FC_RATIO)

    for columna in ["v_ratio", "fc_ratio"]:
        dataset[columna] = dataset.groupby("actividad")[columna].transform(
            lambda s: s.rolling(SUAVIZADO_OBJETIVO, center=True, min_periods=1).mean()
        )

    return dataset


# --- Carga desde disco -------------------------------------------------------


def listar_fit(rutas: Rutas, extra: list[Path] | None = None) -> list[str]:
    """Todos los .FIT que haya en las carpetas conocidas, sin repetir."""
    carpetas = [rutas.fit_files, *(extra or [])]
    encontrados: list[str] = []
    for carpeta in carpetas:
        encontrados += glob.glob(str(Path(carpeta) / "*.fit"))
    return sorted(set(encontrados))


def _parsear_uno(entrada):
    """
    Parsea una entrada, venga como ruta o como `(nombre, bytes)`.

    La segunda forma es la de la API: los archivos llegan por multipart y nunca
    tocan el disco. `procesar_fit` exige el nombre cuando recibe bytes, porque de
    ahí sale la fecha (ver `_fecha_de`).
    """
    if isinstance(entrada, tuple):
        nombre, contenido = entrada
        return procesar_fit(contenido, nombre=Path(nombre).stem)
    return procesar_fit(entrada)


def _nucleos_disponibles() -> int:
    """Los núcleos que puede usar este proceso (respeta `taskset` y cgroups de afinidad)."""
    if hasattr(os, "sched_getaffinity"):
        return max(1, len(os.sched_getaffinity(0)))
    return os.cpu_count() or 1


def parsear_lote(archivos, n_jobs: int | None = None) -> list[tuple[str, pd.DataFrame | None]]:
    """
    Parsea un lote y devuelve el resultado crudo, sin decidir qué es un error.

    Quien llama se queda con el recuento de motivos y con qué hacer si no
    sobrevive nada: la API lo cuenta como control de calidad y el notebook lo
    trata como fallo. Por eso aquí no se lanza nada.

    Medido en esta máquina (12 núcleos, 48 archivos, pool caliente): secuencial
    11.75 s, con 4 procesos 5.60 s, con 6 procesos 5.32 s, con 12 procesos
    6.27 s. Con hilos son 13.27 s, peor que secuencial: `fitparse` es Python
    puro y el GIL no deja. De ahí `N_JOBS_PARSEO = 6` en vez de `-1`.

    Y el pool frío cuesta unos segundos: con 3 archivos, 3.3 s en paralelo contra
    0.87 s secuencial. Por debajo de `MIN_ARCHIVOS_PARALELO` no compensa.

    Con un solo núcleo el paralelo es peor que no hacer nada: 47 archivos tardan
    15.6 s en secuencial y 32.8 s repartidos en 6 procesos que se pelean por la
    misma CPU (medido el 2026-09-26, pensando en una función de 1 vCPU). Por eso
    nunca se piden más procesos que núcleos tiene asignados este proceso.
    """
    entradas = list(archivos)
    trabajos = n_jobs if n_jobs is not None else N_JOBS_PARSEO
    if trabajos > 0:
        trabajos = min(trabajos, _nucleos_disponibles())

    if len(entradas) < MIN_ARCHIVOS_PARALELO or trabajos == 1:
        return [_parsear_uno(entrada) for entrada in entradas]

    return list(Parallel(n_jobs=trabajos)(delayed(_parsear_uno)(e) for e in entradas))


def parsear_todos(archivos, n_jobs: int = -1) -> tuple[pd.DataFrame, dict]:
    """Parsea en paralelo y devuelve (tabla de splits, conteo de motivos)."""
    resultados = parsear_lote(archivos, n_jobs=n_jobs)

    buenos = [tabla for motivo, tabla in resultados if motivo == "ok"]
    if not buenos:
        raise RuntimeError("Ningún archivo pasó el control de calidad.")

    splits = pd.concat(buenos, ignore_index=True)
    motivos = pd.Series([motivo for motivo, _ in resultados]).value_counts().to_dict()
    return splits, motivos


def cargar_splits(
    rutas: Rutas, usar_cache: bool = True, escribir: bool = False
) -> tuple[pd.DataFrame, dict]:
    """
    Carga el historial ya en rejilla de tramos.

    Prioridad: artefacto procesado > .FIT crudos > error explicando qué falta.
    Si aparecieron .FIT nuevos desde la última vez, reprocesa.

    En un clon del repositorio los .FIT no están (son datos personales y no se
    versionan), así que la comparación de conteos deja pasar el parquet y todo
    funciona igual. `escribir=False` por defecto: el backend no reescribe la
    caché de la investigación.
    """
    archivos = listar_fit(rutas)
    metadatos: dict = {}

    if usar_cache and rutas.splits.exists():
        if rutas.metadatos.exists():
            metadatos = json.loads(rutas.metadatos.read_text(encoding="utf-8"))

        usados = metadatos.get("archivos_fit", 0)
        if len(archivos) > usados:
            metadatos["aviso"] = (
                f"Hay {len(archivos)} archivos .FIT en disco y el artefacto se "
                f"construyó con {usados}. Reprocesando."
            )
        else:
            metadatos["origen"] = "artefacto procesado"
            return pd.read_parquet(rutas.splits), metadatos

    if not archivos:
        raise FileNotFoundError(
            "No encuentro datos.\n"
            f"  - No está el artefacto: {rutas.splits}\n"
            f"  - Ni hay .FIT en: {rutas.fit_files}\n\n"
            "El repositorio versiona la caché procesada; si falta, vuelve a "
            "correr el notebook o copia data/procesado/."
        )

    splits, motivos = parsear_todos(archivos)

    metadatos = {
        "generado": datetime.now().isoformat(timespec="seconds"),
        "split_m": SPLIT_M,
        "min_registros_split": MIN_REGISTROS_SPLIT,
        "archivos_fit": len(archivos),
        "actividades": int(splits["actividad"].nunique()),
        "splits": int(len(splits)),
        "control_calidad": motivos,
        "rango_fechas": [splits["fecha"].min(), splits["fecha"].max()],
        "origen": f"{len(archivos)} archivos .FIT parseados",
    }

    if escribir:
        rutas.procesado.mkdir(parents=True, exist_ok=True)
        splits.to_parquet(rutas.splits, index=False)
        rutas.metadatos.write_text(
            json.dumps(metadatos, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    return splits, metadatos


def cargar_ruta_objetivo(rutas: Rutas) -> tuple[pd.DataFrame, str]:
    """El perfil de la ruta de referencia: del .GPX si se puede, y si no del parquet."""
    if rutas.gpx_atenas.exists():
        return procesar_gpx(rutas.gpx_atenas), "GPX"
    if rutas.atenas.exists():
        return pd.read_parquet(rutas.atenas), "parquet"
    raise FileNotFoundError(f"Falta la ruta objetivo: ni {rutas.gpx_atenas} ni {rutas.atenas}.")


__all__ = [
    "cargar_ruta_objetivo",
    "cargar_splits",
    "construir_dataset",
    "listar_fit",
    "parsear_todos",
    "perfil_temporal",
    "procesar_fit",
    "procesar_gpx",
]
