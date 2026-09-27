"""
La prueba que cierra la fase 1: el módulo reproduce lo que validó el notebook.

Es la misma verificación que hace el notebook de investigación al final
de la sección 5.1 (guardar, recargar y comparar predicciones), pero cruzando la
frontera que importa: el artefacto lo escribió el notebook desde `__main__` y
aquí se lee desde `stamina_core`. Si esto falla, la app estaría sirviendo algo
distinto de lo que se midió en la investigación.
"""

from __future__ import annotations

import sys

import numpy as np
import pytest

from stamina_core import (
    EstrategiaPipeline,
    consultar_capacidad,
    elegir_modelo,
)
from stamina_core.reglas import REGIMEN_CORTO, REGIMEN_MARATON, RITMO_CONSTANTE

from .conftest import (
    FC_PRIMEROS_5_KM,
    HABILIDAD_ARTEFACTO,
    HORAS_ARTEFACTO,
    MODELO_ESPERADO,
    RITMO_PRIMEROS_5_KM,
    TEMPERATURA_C,
    TIEMPO_OBJETIVO_H,
    ZONA_PRIMEROS_5_KM,
)

# --- 1. El shim de __main__ --------------------------------------------------


def test_sin_shim_la_carga_falla(rutas):
    """
    Documenta el motivo de existir de `compat.py`.

    El pickle del notebook referencia `__main__.ModeloTabular`. Sin publicar ese
    nombre, pickle no lo encuentra y la carga muere. Este test deja constancia
    de que el puente no es decorativo.
    """
    import joblib

    principal = sys.modules["__main__"]
    guardados = {
        nombre: getattr(principal, nombre, None)
        for nombre in ("ModeloTabular", "BaseFisica", "RedTerreno", "RitmoConstante")
    }
    for nombre in guardados:
        if hasattr(principal, nombre):
            delattr(principal, nombre)

    try:
        with pytest.raises(AttributeError, match="ModeloTabular"):
            joblib.load(rutas.modelo / "metadata.joblib")
    finally:
        for nombre, valor in guardados.items():
            if valor is not None:
                setattr(principal, nombre, valor)


def test_cargar_desde_el_modulo(pipeline):
    """`EstrategiaPipeline.cargar()` funciona desde stamina_core, con el shim."""
    assert pipeline.modelo_nombre_ == MODELO_ESPERADO
    assert pipeline.horas_ == pytest.approx(HORAS_ARTEFACTO, abs=0.05)
    assert pipeline.habilidad_esperada_ == pytest.approx(HABILIDAD_ARTEFACTO, abs=0.001)
    assert pipeline.version_artefacto_ == "6.0"

    # El modelo deserializado es ahora una clase del módulo, no de __main__.
    assert type(pipeline.modelo_).__module__ == "stamina_core.modelos"

    # Y es el bosque que ganó la búsqueda de la sección 3.4.
    estimador = pipeline.modelo_.modelo_v
    assert estimador.n_estimators == 300
    assert estimador.min_samples_leaf == 25
    assert estimador.max_features == 0.5
    assert estimador.max_depth is None


# --- 2. Las predicciones ------------------------------------------------------


@pytest.fixture(scope="session")
def estrategia(pipeline, rutas):
    """La estrategia de Atenas, en las mismas condiciones que el notebook."""
    if not rutas.gpx_atenas.exists():
        pytest.skip(f"Falta el .GPX de referencia en {rutas.gpx_atenas}")
    return pipeline.predecir_ruta(rutas.gpx_atenas, TIEMPO_OBJETIVO_H, TEMPERATURA_C)


def test_la_ruta_mide_lo_mismo(estrategia):
    """423 tramos de 100 m, 42.3 km (sección 1.3 del notebook)."""
    assert len(estrategia) == 423
    assert estrategia["dist_km"].max() == pytest.approx(42.3, abs=0.01)


def test_el_anclaje_al_tiempo_objetivo_es_exacto(estrategia):
    """La suma de los tiempos por tramo tiene que dar el objetivo, no aproximarlo."""
    horas = estrategia["tiempo_split_min"].sum() / 60
    assert horas == pytest.approx(TIEMPO_OBJETIVO_H, abs=1e-6)


def test_reproduce_la_tabla_km_del_notebook(pipeline, estrategia):
    """
    El corazón de la prueba: mismos ritmos, mismas FC y mismas zonas.

    Valores de la sección 5.1: 5.06 / 4.87 / 4.85 / 4.86 / 4.86 min/km y
    150.02 / 155.51 / 156.72 / 156.11 / 155.77 bpm.
    """
    tabla = pipeline.tabla_km(estrategia)

    assert len(tabla) == 43
    assert list(tabla["km"].head(5)) == [1, 2, 3, 4, 5]

    np.testing.assert_allclose(
        tabla["ritmo_objetivo"].head(5).to_numpy(), RITMO_PRIMEROS_5_KM, atol=0.005
    )
    np.testing.assert_allclose(
        tabla["fc_objetivo"].head(5).to_numpy(), FC_PRIMEROS_5_KM, atol=0.005
    )
    assert list(tabla["zona"].head(5)) == ZONA_PRIMEROS_5_KM


def test_indicadores_de_cabecera(pipeline, estrategia):
    """Los cinco números de la sección 7 del notebook."""
    ind = pipeline.indicadores(estrategia)

    assert ind["tiempo_estimado_h"] == pytest.approx(4.0, abs=0.01)
    assert ind["desnivel_positivo_m"] == pytest.approx(343, abs=1)
    assert ind["pendiente_maxima_pct"] == pytest.approx(8.0, abs=0.1)
    assert ind["pct_exigencia_alta"] == pytest.approx(55.8, abs=0.1)
    assert ind["fc_objetivo_media"] == pytest.approx(156, abs=1)


def test_guardar_y_recargar_no_cambia_nada(pipeline, estrategia, tmp_path):
    """
    La prueba de persistencia del notebook, ahora ida y vuelta por el módulo.

    Se guarda en un directorio temporal, se recarga y se comprueba que ritmos y
    zonas son idénticos. Esto valida además que `guardar()` sigue escribiendo el
    mismo formato.
    """
    carpeta = pipeline.guardar(tmp_path / "modelo")
    assert (carpeta / "metadata.joblib").exists()
    assert not (carpeta / "cnn.keras").exists()  # el modelo elegido no es la red

    recargado = EstrategiaPipeline.cargar(carpeta, verboso=False)
    bis = recargado.predecir_ruta(estrategia[["split", "elev"]], TIEMPO_OBJETIVO_H, TEMPERATURA_C)

    np.testing.assert_allclose(
        bis["ritmo_estrategia"].to_numpy(), estrategia["ritmo_estrategia"].to_numpy()
    )
    assert (bis["zona"].to_numpy() == estrategia["zona"].to_numpy()).all()


# --- 3. La regla de capacidad -------------------------------------------------


def test_las_claves_de_reglas_son_las_del_artefacto(pipeline):
    """Las cadenas del régimen son parte del contrato del artefacto."""
    assert set(pipeline.reglas) == {REGIMEN_MARATON, REGIMEN_CORTO}


def test_elegir_modelo_reproduce_la_tabla_de_la_celda_61(pipeline):
    """
    La tabla "qué usaría el sistema en cada caso" del notebook, punto por punto.

    Incluye los altibajos a propósito: la regla **no** es monótona y el test
    tiene que fallar si alguien la "arregla" sin volver a medir.
    """
    esperado = [
        # horas, objetivo 10 km, objetivo maratón
        (1, RITMO_CONSTANTE, RITMO_CONSTANTE),
        (3, "Ridge", RITMO_CONSTANTE),
        (8, "Base física", RITMO_CONSTANTE),
        (15, RITMO_CONSTANTE, "Base física"),
        (30, RITMO_CONSTANTE, "RandomForest"),
        (60, RITMO_CONSTANTE, "Base física"),
        (120, "Base física", "RandomForest"),
        (300, RITMO_CONSTANTE, "RandomForest"),
    ]

    for horas, corto, maraton in esperado:
        assert elegir_modelo(horas, 10, pipeline.reglas)[0] == corto, f"{horas} h / 10 km"
        assert elegir_modelo(horas, 42, pipeline.reglas)[0] == maraton, f"{horas} h / 42 km"


def test_el_umbral_de_entrada_son_10_horas(pipeline):
    """
    Por debajo de 10 h en maratón no hay personalización; a partir de ahí sí.

    El número no se escribe en ningún sitio del sistema: sale de consultar la
    tabla. Este test solo comprueba que la tabla sigue diciendo lo mismo.
    """
    assert elegir_modelo(9.9, 42.2, pipeline.reglas)[0] == RITMO_CONSTANTE
    assert elegir_modelo(10.0, 42.2, pipeline.reglas)[0] == "Base física"
    assert elegir_modelo(10.0, 42.2, pipeline.reglas)[1] == pytest.approx(0.221, abs=0.001)


def test_la_regla_de_maraton_no_es_monotona(pipeline):
    """Si esto pasa a ser monótono, alguien cambió la investigación."""
    capacidad = consultar_capacidad(124.7, 42.2, pipeline.reglas)
    assert capacidad["regimen_monotono"] is False


def test_motivo_por_falta_de_horas(pipeline):
    """Con 3 h y objetivo de maratón, el motivo es el historial."""
    capacidad = consultar_capacidad(3.0, 42.2, pipeline.reglas)

    assert capacidad["personalizada"] is False
    assert capacidad["modelo"] == RITMO_CONSTANTE
    assert capacidad["motivo"] == "sin_evidencia_en_esta_franja"
    # Y se puede decir a partir de cuándo sí, sin prometer monotonía.
    assert capacidad["siguiente_franja"]["modelo"] == "Base física"
    assert capacidad["siguiente_franja"]["desde_horas"] == pytest.approx(10.0, abs=0.01)


def test_motivo_por_distancia_no_por_horas(pipeline):
    """
    Con historial de sobra pero objetivo corto, el motivo NO puede ser "te faltan horas".

    Es el caso que el diseño de solución describía mal. Con 300 h registradas y
    objetivo de 10 km la regla devuelve ritmo constante, y no hay ninguna
    cantidad de horas que lo cambie: la última franja medida del régimen corto
    también es ritmo constante.
    """
    capacidad = consultar_capacidad(300.0, 10.0, pipeline.reglas)

    assert capacidad["regimen"] == REGIMEN_CORTO
    assert capacidad["personalizada"] is False
    assert capacidad["motivo"] == "distancia_sin_evidencia"
    assert capacidad["regimen_fiable"] is False
    assert capacidad["siguiente_franja"] is None  # no hay más horas que sirvan


def test_el_regimen_corto_es_poco_fiable_aunque_asigne_modelo(pipeline):
    """
    El caso incómodo: a 124.7 h y 10 km la regla *sí* asigna Base física.

    Cae en la franja de 79.8 h, donde la habilidad es 0.007 — indistinguible de
    cero. Que la regla asigne algo no significa que sirva, y por eso la consulta
    devuelve `regimen_fiable=False` incluso cuando `personalizada=True`.
    """
    capacidad = consultar_capacidad(124.7, 10.0, pipeline.reglas)

    assert capacidad["personalizada"] is True
    assert capacidad["modelo"] == "Base física"
    assert capacidad["habilidad_esperada"] == pytest.approx(0.007, abs=0.001)
    assert capacidad["regimen_fiable"] is False


def test_el_regimen_de_maraton_si_es_fiable(pipeline):
    """En maratón la franja con más horas es la que mejor puntúa: 0.303."""
    capacidad = consultar_capacidad(200.0, 42.2, pipeline.reglas)

    assert capacidad["regimen_fiable"] is True
    assert capacidad["modelo"] == "RandomForest"
    assert capacidad["habilidad_esperada"] == pytest.approx(0.303, abs=0.001)


def test_una_media_maraton_queda_marcada_como_extrapolacion(pipeline):
    """
    21 km cae en el régimen corto, validado solo hasta 16.1 km.

    La interfaz tiene que avisar: entre 16 y 42 km no hay nada medido.
    """
    capacidad = consultar_capacidad(124.7, 21.1, pipeline.reglas)

    assert capacidad["regimen"] == REGIMEN_CORTO
    assert capacidad["distancia_extrapolada"] is True
    assert capacidad["validado_en_km"] == [10.1, 16.1]

    # Un maratón, en cambio, está dentro de lo validado.
    assert consultar_capacidad(124.7, 42.2, pipeline.reglas)["distancia_extrapolada"] is False


# --- La regla ligera que carga la API ----------------------------------------


def test_reglas_json_coincide_con_el_artefacto(pipeline, rutas):
    """
    La API ya no carga `metadata.joblib`: lee `modelo/reglas.json`.

    Si alguien publica un artefacto nuevo y olvida `make modelo` (que vuelve a
    extraer la regla), la API serviría una regla distinta de la del modelo
    validado. Esta prueba lo detecta: mismas tablas, mismos tipos, mismos valores.
    """
    import pandas as pd

    from stamina_core import ARCHIVO_REGLAS, cargar_reglas

    reglas, metadatos = cargar_reglas(rutas.modelo / ARCHIVO_REGLAS)

    assert sorted(reglas) == sorted(pipeline.reglas)
    for regimen, tabla in pipeline.reglas.items():
        pd.testing.assert_frame_equal(reglas[regimen], tabla)
    assert metadatos["version"] == pipeline.version_artefacto_
    assert metadatos["creado"] == pipeline.creado_
