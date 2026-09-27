"""
El otro lado de la fase 1: entrenar desde el historial y compilar el .FIT.

`cargar()` + `predecir_ruta()` cubre el camino de "ya hay un modelo". Aquí se
verifica el camino de "un usuario sube su historial", que es el que necesita los
hiperparámetros que **no** viajan dentro de `metadata.joblib`, y el compilador de
entrenamiento estructurado contra el archivo que el notebook ya dejó verificado.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from stamina_core import (
    EstrategiaPipeline,
    compilar_pasos,
    compilar_workout_fit,
    construir_dataset,
    listar_fit,
    perfil_temporal,
    procesar_fit,
    sugerir_tiempo_objetivo,
    verificar_workout_fit,
    workout_json,
)
from stamina_core.entrenamiento import ID_CONDICION_DISTANCIA
from stamina_core.hiperparametros import ALPHA_RIDGE, PARAMS_BOSQUE

from .conftest import (
    ACTIVIDADES_ESPERADAS,
    ARCHIVOS_FIT_ESPERADOS,
    DISTANCIAS_PASOS_M,
    HORAS_TOTALES_ESPERADAS,
    PASOS_ESPERADOS,
    SPLITS_ESPERADOS,
    TEMPERATURA_C,
    TIEMPO_OBJETIVO_H,
)

# --- 1. La caché procesada ---------------------------------------------------


def test_la_cache_trae_el_historial_del_notebook(splits, sesiones):
    """460 actividades, 15 959 tramos, 137.4 h (metadatos.json de la última corrida)."""
    assert splits["actividad"].nunique() == ACTIVIDADES_ESPERADAS
    assert len(splits) == SPLITS_ESPERADOS
    assert sesiones["minutos"].sum() / 60 == pytest.approx(HORAS_TOTALES_ESPERADAS, abs=0.05)


def test_construir_dataset_reproduce_el_parquet(rutas, splits):
    """
    `construir_dataset` da lo mismo que el `dataset.parquet` del notebook.

    Es la sección 2.1 completa: limpieza de tramos, variables de terreno por
    actividad y el objetivo winsorizado y suavizado.
    """
    if not rutas.dataset.exists():
        pytest.skip(
            "dataset.parquet no se versiona: solo viaja splits.parquet en tests/datos/. "
            "Esta comparación se hace con los datos completos del notebook."
        )

    esperado = pd.read_parquet(rutas.dataset)
    obtenido = construir_dataset(splits)

    assert len(obtenido) == len(esperado)
    assert obtenido["actividad"].nunique() == esperado["actividad"].nunique()

    # Se compara ordenando igual, porque el groupby no garantiza el mismo orden.
    clave = ["actividad", "split"]
    a = obtenido.sort_values(clave).reset_index(drop=True)
    b = esperado.sort_values(clave).reset_index(drop=True)

    for columna in ["pendiente", "costo_rel", "dist_km", "v_ratio", "fc_ratio", "temperatura"]:
        np.testing.assert_allclose(
            a[columna].to_numpy(), b[columna].to_numpy(), atol=1e-9, err_msg=columna
        )


# --- 2. Entrenar desde cero reproduce el artefacto ---------------------------


def test_el_pool_de_entrenamiento_es_el_del_notebook(sesiones, pool):
    """454 sesiones y 124.7 h (sección 1.4 del notebook)."""
    assert len(pool) == 454
    horas = sesiones.loc[sesiones["actividad"].isin(pool), "minutos"].sum() / 60
    assert horas == pytest.approx(124.7, abs=0.05)


def test_fit_desde_el_historial_reproduce_el_artefacto(rutas, splits, sesiones, pool, pipeline):
    """
    El test más fuerte de la fase: reentrenar da el mismo modelo y los mismos ritmos.

    Verifica de paso que los hiperparámetros de `hiperparametros.py` son los que
    usó la investigación: si `ALPHA_RIDGE` o `PARAMS_BOSQUE` estuvieran mal, el
    bosque saldría distinto y los ritmos no coincidirían.
    """
    dataset = construir_dataset(splits)
    entreno = dataset[dataset["actividad"].isin(pool)]
    sesiones_pool = sesiones[sesiones["actividad"].isin(pool)]

    nuevo = EstrategiaPipeline(pipeline.reglas, verboso=False)
    nuevo.fit(entreno, sesiones_pool, km_objetivo=42.2)

    assert nuevo.modelo_nombre_ == pipeline.modelo_nombre_ == "RandomForest"
    assert nuevo.horas_ == pytest.approx(pipeline.horas_, abs=0.05)
    assert nuevo.habilidad_esperada_ == pytest.approx(pipeline.habilidad_esperada_)
    assert nuevo.fc_referencia_ == pytest.approx(pipeline.fc_referencia_, abs=0.05)

    # Y los hiperparámetros que salieron de las celdas 40 y 42.
    assert nuevo.modelo_.modelo_v.n_estimators == PARAMS_BOSQUE["n_estimators"]
    assert nuevo.modelo_.modelo_v.min_samples_leaf == PARAMS_BOSQUE["min_samples_leaf"]
    assert ALPHA_RIDGE == 300.0

    # La prueba de verdad: la misma estrategia para la misma ruta.
    de_nuevo = nuevo.predecir_ruta(rutas.gpx_atenas, TIEMPO_OBJETIVO_H, TEMPERATURA_C)
    del_artefacto = pipeline.predecir_ruta(rutas.gpx_atenas, TIEMPO_OBJETIVO_H, TEMPERATURA_C)

    np.testing.assert_allclose(
        nuevo.tabla_km(de_nuevo)["ritmo_objetivo"].to_numpy(),
        pipeline.tabla_km(del_artefacto)["ritmo_objetivo"].to_numpy(),
        atol=0.01,
    )


# --- 3. El arreglo de la fecha (bug del flujo de subida) --------------------


@pytest.fixture(scope="session")
def fit_valido(fits_sinteticos) -> tuple[str, str]:
    """
    Un .FIT que pasa el control de calidad, con su fecha esperada.

    Es sintético (ver `fit_sintetico.py`) pero sigue la convención de nombre de
    los archivos del notebook, `AAAA-MM-DD_<id>.fit`.
    """
    ruta = fits_sinteticos[0]
    return ruta, pd.Timestamp(Path(ruta).stem[:10]).strftime("%Y-%m-%d")


def test_la_fecha_sale_del_nombre_cuando_sigue_la_convencion(fit_valido):
    """Los archivos del notebook se llaman AAAA-MM-DD_id.fit y de ahí sale la fecha."""
    ruta, fecha_esperada = fit_valido
    motivo, tramos = procesar_fit(ruta)

    assert motivo == "ok"
    assert tramos["fecha"].iat[0] == fecha_esperada


def test_la_fecha_sale_del_fit_cuando_el_nombre_no_dice_nada(fit_valido):
    """
    El caso del archivo subido por un usuario.

    Antes del arreglo, un `activity.fit` producía `fecha = 'activity.f'`, que
    rompe el orden cronológico del que dependen las horas acumuladas.
    """
    ruta, fecha_esperada = fit_valido
    motivo, tramos = procesar_fit(Path(ruta).read_bytes(), nombre="activity")

    assert motivo == "ok"
    fecha = tramos["fecha"].iat[0]

    # Lo importante: es una fecha de verdad, no un trozo del nombre.
    assert pd.Timestamp(fecha) is not None
    assert tramos["actividad"].iat[0] == "activity"
    # Y coincide con la del nombre, porque el .FIT lleva la misma fecha dentro.
    # Puede desviarse un día por zona horaria, de ahí la tolerancia.
    assert abs((pd.Timestamp(fecha) - pd.Timestamp(fecha_esperada)).days) <= 1


def test_perfil_temporal_ordena_por_fecha_real(fits_sinteticos):
    """
    Con fechas bien leídas, las horas acumuladas son monótonas.

    Es la consecuencia práctica del arreglo anterior: `perfil_temporal` ordena
    por `fecha`, y una fecha basura mandaría la sesión al principio o al final.
    """
    tablas = []
    # Al revés, para que el orden de llegada no coincida con el cronológico.
    for indice, ruta in enumerate(reversed(fits_sinteticos[:6])):
        motivo, tramos = procesar_fit(Path(ruta).read_bytes(), nombre=f"subida_{indice}")
        if motivo == "ok":
            tablas.append(tramos)

    sesiones = perfil_temporal(pd.concat(tablas, ignore_index=True))
    assert sesiones["horas_acum"].is_monotonic_increasing
    assert sesiones["fecha"].is_monotonic_increasing


# --- 4. El entrenamiento estructurado ---------------------------------------


@pytest.fixture(scope="session")
def pasos(pipeline, rutas):
    estrategia = pipeline.predecir_ruta(rutas.gpx_atenas, TIEMPO_OBJETIVO_H, TEMPERATURA_C)
    return compilar_pasos(pipeline.tabla_km(estrategia))


def test_la_estrategia_se_compila_en_siete_pasos(pasos):
    """Sección 7.1: 43 km quedan en 7 pasos de 12/4/3/5/4/3/12 km."""
    assert len(pasos) == PASOS_ESPERADOS
    np.testing.assert_allclose((pasos["km"] * 1000).to_numpy(), DISTANCIAS_PASOS_M, atol=1.0)


def test_el_fit_generado_se_relee_sin_errores(pasos):
    """
    Si el CRC o la estructura estuvieran mal, `fitparse` lanzaría aquí.

    Es la misma verificación que hace el notebook: formato correcto, aceptado por
    Garmin Connect y probado en un reloj físico.
    """
    contenido = compilar_workout_fit(pasos, "Atenas 4h")
    leido = verificar_workout_fit(contenido)

    assert leido["cabecera"]["num_valid_steps"] == PASOS_ESPERADOS
    assert leido["cabecera"]["sport"] == "running"
    assert leido["cabecera"]["wkt_name"] == "Atenas 4h"
    np.testing.assert_allclose(
        [p["distancia_m"] for p in leido["pasos"]], DISTANCIAS_PASOS_M, atol=1.0
    )


def test_coincide_con_el_fit_que_dejo_el_notebook(rutas, pasos):
    """
    La estructura del .FIT generado es la del archivo ya verificado en disco.

    No se comparan bytes: la cabecera lleva la fecha de creación, así que dos
    corridas nunca son idénticas byte a byte. Se compara lo que el reloj lee.
    """
    referencia = rutas.salidas / "entrenamiento_atenas.fit"
    if not referencia.exists():
        pytest.skip(f"Falta {referencia}")

    del_notebook = verificar_workout_fit(referencia.read_bytes())
    del_modulo = verificar_workout_fit(compilar_workout_fit(pasos, "Atenas 4h"))

    assert del_modulo["cabecera"]["num_valid_steps"] == del_notebook["cabecera"]["num_valid_steps"]
    assert del_modulo["bytes"] == del_notebook["bytes"]

    for a, b in zip(del_modulo["pasos"], del_notebook["pasos"], strict=True):
        assert a["paso"] == b["paso"]
        assert a["distancia_m"] == b["distancia_m"]
        assert a["ritmo_lento"] == pytest.approx(b["ritmo_lento"], abs=0.01)
        assert a["ritmo_rapido"] == pytest.approx(b["ritmo_rapido"], abs=0.01)


def test_el_json_de_garmin_usa_distancia_y_no_lap_button(pasos):
    """
    `conditionTypeId = 3`. El 1 es `lap.button`, y es el bug que ya se pagó.

    Con el 1, Garmin convirtió los pasos en "espera a que aprietes la vuelta" en
    vez de avanzar solos a los 12 km.
    """
    payload = workout_json(pasos, "Atenas 4h", 4 * 3600)
    pasos_json = payload["workoutSegments"][0]["workoutSteps"]

    assert ID_CONDICION_DISTANCIA == 3
    assert len(pasos_json) == PASOS_ESPERADOS
    for paso in pasos_json:
        assert paso["endCondition"]["conditionTypeId"] == 3
        assert paso["endCondition"]["conditionTypeKey"] == "distance"
        # targetValueOne es la velocidad lenta: tiene que ser <= la rápida.
        assert paso["targetValueOne"] <= paso["targetValueTwo"]

    np.testing.assert_allclose(
        [p["endConditionValue"] for p in pasos_json], DISTANCIAS_PASOS_M, atol=1.0
    )


def test_el_json_coincide_con_el_del_notebook(rutas, pasos):
    """Contra el `entrenamiento_atenas.json` que dejó el notebook, ya subido a Garmin."""
    import json

    referencia = rutas.salidas / "entrenamiento_atenas.json"
    if not referencia.exists():
        pytest.skip(f"Falta {referencia}")

    esperado = json.loads(referencia.read_text(encoding="utf-8"))
    obtenido = workout_json(pasos, esperado["workoutName"], esperado["estimatedDurationInSecs"])

    a = obtenido["workoutSegments"][0]["workoutSteps"]
    b = esperado["workoutSegments"][0]["workoutSteps"]
    assert len(a) == len(b)

    for paso_a, paso_b in zip(a, b, strict=True):
        assert paso_a["endConditionValue"] == paso_b["endConditionValue"]
        assert paso_a["targetValueOne"] == pytest.approx(paso_b["targetValueOne"], abs=0.001)
        assert paso_a["targetValueTwo"] == pytest.approx(paso_b["targetValueTwo"], abs=0.001)
        assert paso_a["description"] == paso_b["description"]


# --- 5. Reprocesado completo (solo con los .FIT en disco) -------------------


def test_reprocesar_los_fit_da_el_mismo_historial(rutas):
    """
    492 archivos -> 460 actividades / 15 959 tramos.

    Solo corre si `tests/datos/data/fit_files/` tiene los 492 archivos reales.
    No se versionan: son datos personales (GPS y frecuencia cardíaca) y viven
    con el notebook de investigación, fuera de este repositorio.
    """
    archivos = listar_fit(rutas)
    if len(archivos) < ARCHIVOS_FIT_ESPERADOS:
        pytest.skip(
            f"Los {ARCHIVOS_FIT_ESPERADOS} .FIT reales no viven en el repositorio "
            f"(datos personales); hay {len(archivos)} en {rutas.fit_files}."
        )

    from stamina_core.ingesta import parsear_todos

    splits, motivos = parsear_todos(archivos)

    assert splits["actividad"].nunique() == ACTIVIDADES_ESPERADAS
    assert len(splits) == SPLITS_ESPERADOS
    assert motivos["ok"] == ACTIVIDADES_ESPERADAS
    assert motivos.get("sin enhanced_altitude") == 31
    assert motivos.get("no es carrera continua") == 1


# --- 6. El selector de objetivo ---------------------------------------------


def test_sugerencia_de_tiempo_para_maraton(sesiones):
    """
    La sugerencia sale del propio historial, y es editable.

    No es una predicción del modelo y la respuesta lo dice explícitamente, para
    que la interfaz no pueda presentarla como tal.
    """
    sugerencia = sugerir_tiempo_objetivo(sesiones, 42.2, "terminar sin fatiga")

    assert sugerencia["editable"] is True
    assert "calculadora" in sugerencia["metodo"]
    assert sugerencia["referencia"]["km"] >= 5.0
    # Un maratón entre 2.5 y 7 h: no es un número fino, pero sí un rango sano.
    assert 2.5 < sugerencia["tiempo_objetivo_h"] < 7.0


def test_las_cuatro_opciones_estan_ordenadas(sesiones):
    """Conservador más lento que sin fatiga, y ese más lento que buscar marca."""
    tiempos = {
        clave: sugerir_tiempo_objetivo(sesiones, 42.2, clave)["tiempo_objetivo_h"]
        for clave in (
            "maximizar rendimiento",
            "mejor marca",
            "terminar sin fatiga",
            "ritmo conservador",
        )
    }

    assert (
        tiempos["maximizar rendimiento"]
        < tiempos["mejor marca"]
        < tiempos["terminar sin fatiga"]
        < tiempos["ritmo conservador"]
    )


def test_sin_historial_util_no_se_inventa_un_tiempo(sesiones):
    """Si no hay ninguna sesión larga, se dice y se deja que el usuario lo teclee."""
    cortas = sesiones[sesiones["km"] < 5.0]
    if cortas.empty:
        pytest.skip("El historial no tiene sesiones cortas para la prueba")

    sugerencia = sugerir_tiempo_objetivo(cortas, 42.2)

    assert sugerencia["tiempo_objetivo_h"] is None
    assert sugerencia["motivo"] is not None
    assert sugerencia["editable"] is True


# --- Parseo en paralelo ------------------------------------------------------


def test_parsear_en_paralelo_da_exactamente_lo_mismo_que_en_secuencial(fits_sinteticos):
    """
    La regresión que importa de paralelizar la subida de historial.

    Repartir el parseo entre procesos solo vale la pena si el resultado es
    idéntico: mismos motivos de control de calidad, en el mismo orden, y mismos
    tramos. Si esto falla, las horas que consulta la regla de capacidad cambian
    según cuántos archivos se suban a la vez, que sería lo peor posible.
    """
    from stamina_core.ingesta import MIN_ARCHIVOS_PARALELO, parsear_lote

    archivos = fits_sinteticos[: MIN_ARCHIVOS_PARALELO + 4]
    assert len(archivos) > MIN_ARCHIVOS_PARALELO, "el lote tiene que activar el paralelo"

    # Como tuplas (nombre, bytes): es la forma en que llegan por la API.
    lote = [(Path(a).name, Path(a).read_bytes()) for a in archivos]

    secuencial = parsear_lote(lote, n_jobs=1)
    paralelo = parsear_lote(lote)

    assert [motivo for motivo, _ in secuencial] == [motivo for motivo, _ in paralelo]
    for (_, esperado), (_, obtenido) in zip(secuencial, paralelo, strict=True):
        if esperado is None:
            assert obtenido is None
        else:
            assert obtenido is not None and esperado.equals(obtenido)


def test_el_lote_acepta_rutas_y_tuplas_por_igual(fits_sinteticos):
    """Un .FIT en disco y el mismo subido por multipart dan el mismo resultado."""
    from stamina_core.ingesta import parsear_lote

    archivos = fits_sinteticos[:2]

    por_ruta = parsear_lote(archivos, n_jobs=1)
    por_bytes = parsear_lote([(Path(a).name, Path(a).read_bytes()) for a in archivos], n_jobs=1)

    assert [m for m, _ in por_ruta] == [m for m, _ in por_bytes]
    for (_, a), (_, b) in zip(por_ruta, por_bytes, strict=True):
        assert (a is None and b is None) or a.equals(b)
