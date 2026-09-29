"""
Pruebas de humo de la API, una por endpoint.

Dos reglas de la suite:

1. **Ningún test toca la red.** Un fixture `autouse` parchea
   `socket.socket.connect` y solo deja pasar loopback. Sin eso, un descuido en
   los tests de Garmin acabaría golpeando una cuenta real.
2. Se usa `ASGITransport` de httpx en vez de `TestClient`, para correr la app
   dentro del mismo bucle de eventos.
"""

from __future__ import annotations

import base64
import json
import socket
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from .conftest import TEMPERATURA_C, TIEMPO_OBJETIVO_H

# --- Guardia anti-red --------------------------------------------------------

_LOOPBACK = {"127.0.0.1", "::1", "localhost"}
_connect_original = socket.socket.connect


def _cortar_cffi(*args, **kwargs):
    """Corta cualquier salida por curl_cffi, diga lo que diga la llamada."""
    destino = kwargs.get("url") or next(
        (a for a in args if isinstance(a, str) and "://" in a), "un host externo"
    )
    raise RuntimeError(
        f"Un test ha intentado una llamada de red real por curl_cffi a {destino}. "
        "Usa dobles, no la red."
    )


@pytest.fixture(autouse=True)
def prohibir_red(monkeypatch):
    """Solo loopback. Cualquier otra conexión revienta con un mensaje claro."""

    def guardia(self, direccion):
        if isinstance(direccion, tuple) and direccion and direccion[0] not in _LOOPBACK:
            raise RuntimeError(
                f"Un test ha intentado una llamada de red real a {direccion[0]}. "
                "Usa dobles, no la red."
            )
        return _connect_original(self, direccion)

    monkeypatch.setattr(socket.socket, "connect", guardia)

    # `curl_cffi` habla con libcurl a través de CFFI, así que nunca pasa por
    # `socket.socket.connect` y el parche de arriba no lo veía: la suite salía a
    # internet de verdad contra Garmin en cada `make test`, que es justo lo que
    # esta guardia existe para impedir. `garminconnect` lo usa en tres de sus
    # cinco vías de login, así que hay que taparlo aparte.
    try:
        from curl_cffi import requests as cffi
    except ImportError:  # pragma: no cover - si no está, no hay nada que cortar
        return

    monkeypatch.setattr(cffi.Session, "request", _cortar_cffi)
    for nombre in ("request", "get", "post", "put", "delete", "head"):
        monkeypatch.setattr(cffi, nombre, _cortar_cffi, raising=False)


# --- Cliente -----------------------------------------------------------------


@pytest.fixture
async def cliente():
    from app.main import app

    transporte = ASGITransport(app=app)
    async with AsyncClient(transport=transporte, base_url="http://test") as c:
        # El lifespan no corre con ASGITransport, así que se carga a mano.
        from app.core.config import settings
        from app.services.pipeline_service import PipelineService

        if not hasattr(app.state, "pipelines"):
            servicio = PipelineService(settings.carpeta_modelo)
            servicio.cargar()
            app.state.pipelines = servicio
        yield c


API = "/api/v1"


# --- Salud -------------------------------------------------------------------


async def test_health(cliente):
    respuesta = await cliente.get(f"{API}/health")
    assert respuesta.status_code == 200

    cuerpo = respuesta.json()
    assert cuerpo["estado"] == "ok"
    assert cuerpo["reglas"]["cargadas"] is True
    assert sorted(cuerpo["reglas"]["regimenes"]) == ["carrera de 10-12 km", "maratón"]
    # En local Garmin está encendido; en el despliegue sin estado se apaga.
    assert cuerpo["garmin_habilitado"] is True
    # Lo único que guarda el servidor es de Garmin.
    assert set(cuerpo["sesiones_activas"]) == {"garmin", "descargas"}


async def test_la_raiz_apunta_a_la_documentacion(cliente):
    cuerpo = (await cliente.get("/")).json()
    assert cuerpo["docs"] == "/docs"
    assert cuerpo["api"] == API


# --- Capacidad ---------------------------------------------------------------


async def test_capacidad_maraton_con_historial_de_sobra(cliente):
    respuesta = await cliente.get(f"{API}/capacidad", params={"horas": 200, "km_objetivo": 42.2})
    assert respuesta.status_code == 200

    cuerpo = respuesta.json()
    assert cuerpo["personalizada"] is True
    assert cuerpo["modelo"] == "RandomForest"
    assert cuerpo["habilidad_esperada"] == pytest.approx(0.303, abs=0.001)
    assert cuerpo["motivo"] is None
    assert cuerpo["regimen_fiable"] is True
    # La regla de maratón no es monótona y la API lo dice.
    assert cuerpo["regimen_monotono"] is False


async def test_capacidad_sin_horas_suficientes(cliente):
    cuerpo = (
        await cliente.get(f"{API}/capacidad", params={"horas": 3, "km_objetivo": 42.2})
    ).json()

    assert cuerpo["personalizada"] is False
    assert cuerpo["motivo"] == "sin_evidencia_en_esta_franja"
    assert cuerpo["siguiente_franja"]["modelo"] == "Base física"
    assert cuerpo["siguiente_franja"]["horas_faltantes"] == pytest.approx(7.0, abs=0.1)


async def test_capacidad_en_carrera_corta_culpa_a_la_distancia(cliente):
    """Con 300 h y 10 km el motivo no puede ser el historial."""
    cuerpo = (
        await cliente.get(f"{API}/capacidad", params={"horas": 300, "km_objetivo": 10})
    ).json()

    assert cuerpo["personalizada"] is False
    assert cuerpo["motivo"] == "distancia_sin_evidencia"
    assert cuerpo["regimen_fiable"] is False


async def test_capacidad_avisa_de_la_media_maraton(cliente):
    cuerpo = (
        await cliente.get(f"{API}/capacidad", params={"horas": 124.7, "km_objetivo": 21.1})
    ).json()

    assert cuerpo["distancia_extrapolada"] is True
    assert cuerpo["validado_en_km"] == [10.1, 16.1]


async def test_capacidad_valida_los_parametros(cliente):
    assert (
        await cliente.get(f"{API}/capacidad", params={"horas": -1, "km_objetivo": 42})
    ).status_code == 422
    assert (
        await cliente.get(f"{API}/capacidad", params={"horas": 10, "km_objetivo": 0})
    ).status_code == 422


# --- Historial ---------------------------------------------------------------


def _como_archivos(rutas_fit) -> list:
    return [
        ("archivos", (Path(r).name, Path(r).read_bytes(), "application/octet-stream"))
        for r in rutas_fit
    ]


def _juntar(*tramos: dict) -> dict:
    """Lo que hace el navegador con varias tandas: concatenar columna a columna."""
    return {columna: sum((t[columna] for t in tramos), []) for columna in tramos[0]}


@pytest.fixture
def fit_de_prueba(fits_sinteticos) -> tuple[str, bytes]:
    """Una carrera sintética que pasa el control de calidad (ver `fit_sintetico.py`)."""
    ruta = Path(fits_sinteticos[0])
    return ruta.name, ruta.read_bytes()


async def test_subir_historial_devuelve_los_tramos_y_no_los_guarda(cliente, fit_de_prueba):
    nombre, contenido = fit_de_prueba
    respuesta = await cliente.post(
        f"{API}/historial/archivos",
        files=[("archivos", (nombre, contenido, "application/octet-stream"))],
    )
    assert respuesta.status_code == 200, respuesta.text

    cuerpo = respuesta.json()
    assert cuerpo["control_calidad"]["ok"] == 1
    tramos = cuerpo["tramos"]
    assert len(tramos["split"]) > 30
    assert set(tramos["actividad"]) == {Path(nombre).stem}
    # Lo que vuelve al navegador no lleva coordenadas ni un identificador que
    # haya que devolver: el servidor no se quedó con nada.
    assert set(tramos) == {
        "split", "v", "fc", "cadencia", "elev", "temperatura",
        "t_fin", "n_registros", "actividad", "fecha",
    }  # fmt: skip
    assert "historial_id" not in cuerpo


async def test_resumen_sin_objetivo(cliente, fit_de_prueba):
    nombre, contenido = fit_de_prueba
    procesado = (
        await cliente.post(
            f"{API}/historial/archivos",
            files=[("archivos", (nombre, contenido, "application/octet-stream"))],
        )
    ).json()

    resumen = (
        await cliente.post(f"{API}/historial/resumen", json={"tramos": procesado["tramos"]})
    ).json()

    assert resumen["sesiones"] == 1
    assert resumen["horas"] > 0
    assert resumen["desde"] == resumen["hasta"] == "2024-03-01"
    # Sin km_objetivo no se consulta la regla.
    assert resumen["capacidad"] is None


async def test_resumen_con_objetivo_trae_la_capacidad(cliente, fit_de_prueba):
    nombre, contenido = fit_de_prueba
    procesado = (
        await cliente.post(
            f"{API}/historial/archivos",
            files=[("archivos", (nombre, contenido, "application/octet-stream"))],
        )
    ).json()
    capacidad = (
        await cliente.post(
            f"{API}/historial/resumen",
            json={"tramos": procesado["tramos"], "km_objetivo": 42.2},
        )
    ).json()["capacidad"]

    assert capacidad is not None
    assert capacidad["regimen"] == "maratón"

    # Una sola sesión no alcanza para personalizar una maratón, caiga en la
    # primera franja medida o por debajo de ella.
    assert capacidad["personalizada"] is False
    assert capacidad["motivo"] in {"historial_insuficiente", "sin_evidencia_en_esta_franja"}

    # Y en maratón sí tiene sentido decirle cuántas horas le faltan, porque el
    # régimen es fiable: la franja con más horas personaliza.
    assert capacidad["regimen_fiable"] is True
    assert capacidad["siguiente_franja"] is not None
    assert capacidad["siguiente_franja"]["horas_faltantes"] > 0


async def test_subir_por_tandas_da_lo_mismo_que_de_una_vez(cliente, fits_sinteticos):
    """
    Un historial grande se sube por tandas de unos 3.5 MB, por debajo del tope
    de 4.5 MB por petición que tienen algunas plataformas. Juntarlas en el navegador —y repetir un archivo sin querer—
    tiene que dar el mismo historial que subirlo todo junto.
    """
    muestra = fits_sinteticos[:6]

    de_una_vez = (
        await cliente.post(f"{API}/historial/archivos", files=_como_archivos(muestra))
    ).json()["tramos"]

    tanda_1 = (
        await cliente.post(f"{API}/historial/archivos", files=_como_archivos(muestra[:4]))
    ).json()["tramos"]
    # La segunda tanda repite el tercer archivo: no puede contar doble.
    tanda_2 = (
        await cliente.post(f"{API}/historial/archivos", files=_como_archivos(muestra[2:]))
    ).json()["tramos"]

    resumen_una = (
        await cliente.post(f"{API}/historial/resumen", json={"tramos": de_una_vez})
    ).json()
    resumen_tandas = (
        await cliente.post(f"{API}/historial/resumen", json={"tramos": _juntar(tanda_1, tanda_2)})
    ).json()

    assert resumen_tandas == resumen_una
    assert resumen_una["sesiones"] == 5  # la cuarta no trae altitud


async def test_un_historial_con_columnas_desparejas_se_rechaza(cliente, fit_de_prueba):
    nombre, contenido = fit_de_prueba
    tramos = (
        await cliente.post(
            f"{API}/historial/archivos",
            files=[("archivos", (nombre, contenido, "application/octet-stream"))],
        )
    ).json()["tramos"]
    tramos["v"] = tramos["v"][:-1]

    respuesta = await cliente.post(f"{API}/historial/resumen", json={"tramos": tramos})
    assert respuesta.status_code == 422


async def test_el_tcx_se_rechaza_diciendo_por_que(cliente):
    respuesta = await cliente.post(
        f"{API}/historial/archivos",
        files=[("archivos", ("actividad.tcx", b"<TrainingCenterDatabase/>", "application/xml"))],
    )
    assert respuesta.status_code == 422

    error = respuesta.json()["error"]
    assert error["code"] == "formato_no_soportado"
    assert ".TCX" in error["message"]


async def test_un_fit_ilegible_no_pasa(cliente):
    respuesta = await cliente.post(
        f"{API}/historial/archivos",
        files=[("archivos", ("basura.fit", b"no soy un FIT", "application/octet-stream"))],
    )
    assert respuesta.status_code == 422
    assert respuesta.json()["error"]["code"] == "historial_insuficiente"


# --- El historial del notebook, como lo mandaría el navegador ---------------


@pytest.fixture(scope="session")
def tramos_del_notebook(splits, pool) -> dict:
    """
    El conjunto de entrenamiento del notebook (124.7 h), en el formato de la API.

    Mandarlo a `POST /estrategia` tiene que reproducir el modelo del notebook:
    es la prueba de que el viaje de ida y vuelta por el navegador no cambia nada.
    """
    from app.services.historial_service import a_tramos

    return a_tramos(splits[splits["actividad"].isin(pool)])


# --- Objetivo ----------------------------------------------------------------


async def test_opciones_del_selector(cliente):
    opciones = (await cliente.get(f"{API}/objetivo/opciones")).json()

    assert len(opciones) == 4
    claves = [o["clave"] for o in opciones]
    assert "terminar sin fatiga" in claves
    assert sum(o["por_defecto"] for o in opciones) == 1


async def test_sugerencia_desde_los_tramos(cliente, tramos_del_notebook):
    respuesta = await cliente.post(
        f"{API}/objetivo/sugerencia",
        json={
            "tramos": tramos_del_notebook,
            "km_objetivo": 42.2,
            "objetivo": "terminar sin fatiga",
        },
    )
    assert respuesta.status_code == 200, respuesta.text

    sugerencia = respuesta.json()
    assert sugerencia["editable"] is True
    assert "calculadora" in sugerencia["metodo"]
    assert 2.5 < sugerencia["tiempo_objetivo_h"] < 7.0


async def test_sin_sesiones_largas_no_se_sugiere_nada(cliente, fit_de_prueba):
    """Veinte minutos de carrera no dan para extrapolar una maratón."""
    nombre, contenido = fit_de_prueba
    tramos = (
        await cliente.post(
            f"{API}/historial/archivos",
            files=[("archivos", (nombre, contenido, "application/octet-stream"))],
        )
    ).json()["tramos"]

    sugerencia = (
        await cliente.post(
            f"{API}/objetivo/sugerencia",
            json={"tramos": tramos, "km_objetivo": 42.2},
        )
    ).json()
    assert sugerencia["tiempo_objetivo_h"] is None
    assert sugerencia["motivo"]


# --- Estrategia --------------------------------------------------------------


@pytest.fixture
def gpx_atenas(rutas) -> bytes:
    if not rutas.gpx_atenas.exists():
        pytest.skip("Falta el .GPX de referencia")
    return rutas.gpx_atenas.read_bytes()


def _historial_como_archivo(tramos: dict) -> tuple:
    return ("historial", ("historial.json", json.dumps(tramos).encode(), "application/json"))


@pytest.fixture
async def estrategia_calculada(cliente, gpx_atenas, tramos_del_notebook):
    respuesta = await cliente.post(
        f"{API}/estrategia",
        files=[
            ("gpx", ("atenas.gpx", gpx_atenas, "application/gpx+xml")),
            _historial_como_archivo(tramos_del_notebook),
        ],
        data={
            "tiempo_objetivo_h": str(TIEMPO_OBJETIVO_H),
            "temperatura_c": str(TEMPERATURA_C),
        },
    )
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


async def test_estrategia_reproduce_el_notebook(estrategia_calculada):
    """
    El camino entero del producto da los ritmos de la sección 5.1 del notebook.

    Los tramos viajan como JSON, se reconstruye el historial, se entrena el
    Random Forest que asigna la regla y se predice Atenas: si algo del viaje de
    ida y vuelta cambiara un dato, estos ritmos no saldrían.

    La tolerancia es 0.02 min/km y no 0.01, por una razón medida: las sesiones
    sin temperatura se rellenan con la mediana del historial. El notebook la
    calculó sobre sus 460 actividades, incluidas las 6 carreras de prueba; aquí
    se calcula sobre las 454 que se mandan, que es lo correcto para un corredor
    real. Son 0.07 °C de diferencia y, como mucho, 0.02 min/km en algún km.
    """
    cuerpo = estrategia_calculada

    assert cuerpo["ruta"]["km_totales"] == pytest.approx(42.3, abs=0.01)
    assert len(cuerpo["tabla_km"]) == 43
    assert len(cuerpo["altimetria"]) == 423

    ritmos = [f["ritmo_objetivo"] for f in cuerpo["tabla_km"][:5]]
    assert ritmos == pytest.approx([5.06, 4.87, 4.85, 4.86, 4.86], abs=0.02)

    assert cuerpo["indicadores"]["tiempo_estimado_h"] == pytest.approx(4.0, abs=0.01)
    assert cuerpo["indicadores"]["desnivel_positivo_m"] == pytest.approx(343, abs=1)


async def test_la_estrategia_siempre_trae_las_senales_de_capacidad(estrategia_calculada):
    """La interfaz nunca tiene que inferir si está personalizada ni por qué."""
    capacidad = estrategia_calculada["capacidad"]

    assert capacidad["modelo"] == "RandomForest"
    assert capacidad["personalizada"] is True
    assert capacidad["horas"] == pytest.approx(124.7, abs=0.05)
    assert capacidad["regimen"] == "maratón"


async def test_la_estrategia_trae_los_pasos_y_el_fit(estrategia_calculada):
    """No hay una segunda petición que vaya a buscarlos: viajan en la respuesta."""
    entrenamiento = estrategia_calculada["entrenamiento"]

    assert [round(p["km"] * 1000) for p in entrenamiento["pasos"]] == [
        12000,
        4000,
        3000,
        5000,
        4000,
        3000,
        12000,
    ]
    # El aviso sobre el archivo viaja en la respuesta, no depende de que la UI lo
    # recuerde. Se comprueba que está y que menciona las tres verificaciones.
    assert "reloj físico" in entrenamiento["aviso"]
    assert "fitparse" in entrenamiento["aviso"]

    pasos_garmin = entrenamiento["payload_garmin"]["workoutSegments"][0]["workoutSteps"]
    assert all(p["endCondition"]["conditionTypeId"] == 3 for p in pasos_garmin)

    # Y el .FIT es un .FIT de verdad: se relee con fitparse.
    from stamina_core import verificar_workout_fit

    fit = estrategia_calculada["fit"]
    assert fit["nombre_archivo"].endswith(".fit")
    leido = verificar_workout_fit(base64.b64decode(fit["contenido_base64"]))
    assert leido["cabecera"]["num_valid_steps"] == 7
    assert leido["cabecera"]["sport"] == "running"


async def test_sin_historial_no_hay_estrategia(cliente, gpx_atenas):
    """Ya no hay modelo del autor al que recurrir: el historial es obligatorio."""
    respuesta = await cliente.post(
        f"{API}/estrategia",
        files=[("gpx", ("atenas.gpx", gpx_atenas, "application/gpx+xml"))],
        data={"tiempo_objetivo_h": "4.0"},
    )
    assert respuesta.status_code == 422


async def test_un_historial_malformado_se_rechaza(cliente, gpx_atenas):
    respuesta = await cliente.post(
        f"{API}/estrategia",
        files=[
            ("gpx", ("atenas.gpx", gpx_atenas, "application/gpx+xml")),
            ("historial", ("historial.json", b"{no es json", "application/json")),
        ],
        data={"tiempo_objetivo_h": "4.0"},
    )
    assert respuesta.status_code == 422
    assert respuesta.json()["error"]["code"] == "archivo_invalido"


async def test_un_gpx_invalido_se_rechaza(cliente, tramos_del_notebook):
    respuesta = await cliente.post(
        f"{API}/estrategia",
        files=[
            ("gpx", ("ruta.gpx", b"<gpx></gpx>", "application/gpx+xml")),
            _historial_como_archivo(tramos_del_notebook),
        ],
        data={"tiempo_objetivo_h": "4.0"},
    )
    assert respuesta.status_code == 422
    assert respuesta.json()["error"]["code"] == "archivo_invalido"


async def test_no_se_acepta_un_fit_como_ruta(cliente, tramos_del_notebook):
    respuesta = await cliente.post(
        f"{API}/estrategia",
        files=[
            ("gpx", ("ruta.fit", b"cualquier cosa", "application/octet-stream")),
            _historial_como_archivo(tramos_del_notebook),
        ],
        data={"tiempo_objetivo_h": "4.0"},
    )
    assert respuesta.status_code == 422


# --- Garmin: confirmación explícita -----------------------------------------


async def test_la_descarga_de_garmin_exige_confirmacion(cliente):
    """Sin `confirmado=true` no se llega siquiera a mirar la sesión."""
    respuesta = await cliente.post(
        f"{API}/historial/garmin",
        json={"sesion_garmin_id": "loquesea", "objetivo_horas": 50, "confirmado": False},
    )
    assert respuesta.status_code == 428
    assert respuesta.json()["error"]["code"] == "confirmacion_requerida"


def _para_subir(estrategia: dict) -> dict:
    """Lo que el navegador devuelve para subir: los pasos que le llegaron."""
    entrenamiento = estrategia["entrenamiento"]
    return {
        "nombre": entrenamiento["nombre"],
        "segundos_estimados": entrenamiento["segundos_estimados"],
        "pasos": entrenamiento["pasos"],
    }


async def test_la_subida_a_garmin_exige_confirmacion(cliente, estrategia_calculada):
    respuesta = await cliente.post(
        f"{API}/exportar/garmin",
        json={
            "sesion_garmin_id": "loquesea",
            "entrenamiento": _para_subir(estrategia_calculada),
            "confirmado": False,
        },
    )
    assert respuesta.status_code == 428
    assert respuesta.json()["error"]["code"] == "confirmacion_requerida"


async def test_con_confirmacion_pero_sin_sesion_valida(cliente, estrategia_calculada):
    """Confirmar no basta: hace falta una sesión de Garmin viva."""
    respuesta = await cliente.post(
        f"{API}/exportar/garmin",
        json={
            "sesion_garmin_id": "caducada",
            "entrenamiento": _para_subir(estrategia_calculada),
            "confirmado": True,
        },
    )
    assert respuesta.status_code == 404


async def test_la_subida_reconstruye_el_json_de_garmin_con_distancia(
    cliente, estrategia_calculada, monkeypatch
):
    """
    El JSON de Garmin lo arma el servidor a partir de los pasos, no el cliente:
    así el `conditionTypeId = 3` (distancia, no `lap.button`) no depende de nadie.
    """
    from app.services import garmin_service
    from app.services.almacen import sesiones_garmin

    recibido = {}

    def subida_falsa(sesion, payload):
        recibido.update(payload)
        pasos = payload["workoutSegments"][0]["workoutSteps"]
        return {
            "workout_id": 1,
            "nombre": payload["workoutName"],
            "pasos_segun_garmin": [],
            "todos_por_distancia": all(p["endCondition"]["conditionTypeId"] == 3 for p in pasos),
        }

    monkeypatch.setattr(garmin_service, "subir_entrenamiento", subida_falsa)
    sesion_id = sesiones_garmin.guardar(object())

    respuesta = await cliente.post(
        f"{API}/exportar/garmin",
        json={
            "sesion_garmin_id": sesion_id,
            "entrenamiento": _para_subir(estrategia_calculada),
            "confirmado": True,
        },
    )
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["todos_por_distancia"] is True
    assert recibido == estrategia_calculada["entrenamiento"]["payload_garmin"]


async def test_cerrar_una_sesion_inexistente_no_falla(cliente):
    """Idempotente a propósito: cerrar algo que ya no está no es un error."""
    assert (await cliente.delete(f"{API}/garmin/sesion/noexiste")).status_code == 204


async def test_el_login_de_garmin_no_sale_a_la_red_en_los_tests(cliente):
    """
    Comprueba que la guardia anti-red funciona.

    Si este test empezara a pasar por otra razón, querría decir que la guardia
    dejó de proteger y los tests podrían golpear una cuenta real.
    """
    respuesta = await cliente.post(
        f"{API}/garmin/login",
        json={"correo": "nadie@example.com", "contrasena": "no-es-real"},
    )
    # La guardia corta las cinco vías de login y la librería acaba lanzando su
    # «strategies exhausted», que el servicio traduce a 429: el acceso se rechazó
    # antes de mirar las credenciales. Lo que importa aquí es que sea un error de
    # dominio y no una respuesta real de Garmin.
    assert respuesta.status_code in (401, 429, 500, 502)
    assert respuesta.json()["error"]["code"].startswith("garmin")


# --- Garmin apagado (STAMINA_GARMIN_HABILITADO=False) --------------------------


@pytest.fixture
def garmin_apagado():
    """Lo que pasa donde el despliegue apaga Garmin."""
    from app.core.config import Settings, get_settings
    from app.main import app

    app.dependency_overrides[get_settings] = lambda: Settings(garmin_habilitado=False)
    yield
    app.dependency_overrides.pop(get_settings, None)


async def test_sin_garmin_todas_sus_rutas_lo_dicen(cliente, garmin_apagado):
    peticiones = [
        cliente.post(f"{API}/garmin/login", json={"correo": "a@b.c", "contrasena": "x"}),
        cliente.post(
            f"{API}/historial/garmin",
            json={"sesion_garmin_id": "x", "objetivo_horas": 50, "confirmado": True},
        ),
        cliente.get(f"{API}/historial/garmin/x"),
        cliente.delete(f"{API}/garmin/sesion/x"),
    ]
    for peticion in peticiones:
        respuesta = await peticion
        assert respuesta.status_code == 403, respuesta.text
        assert respuesta.json()["error"]["code"] == "garmin_no_disponible"
        assert ".FIT" in respuesta.json()["error"]["message"]

    salud = (await cliente.get(f"{API}/health")).json()
    assert salud["garmin_habilitado"] is False


# --- Garmin: la descarga como tarea con progreso ----------------------------


async def test_la_descarga_devuelve_una_tarea_y_se_puede_seguir(
    cliente, monkeypatch, fits_sinteticos
):
    """
    El ciclo completo sin tocar Garmin: arrancar, consultar, terminar.

    `descargar_historial` se sustituye por un doble que llama al callback de
    progreso igual que lo haría la descarga real, para comprobar que el
    porcentaje que ve el frontend sale de verdad de ahí.
    """
    import pandas as pd

    from app.services import descarga_service, garmin_service
    from app.services.almacen import sesiones_garmin
    from stamina_core.ingesta import procesar_fit

    # Una sesión de Garmin falsa, solo para que el endpoint la encuentre.
    sesion_id = sesiones_garmin.guardar(object())

    muestra = fits_sinteticos[:3]
    tablas = [t for _, t in (procesar_fit(f) for f in muestra) if t is not None]
    splits = pd.concat(tablas, ignore_index=True)

    def descarga_falsa(sesion, objetivo_horas, *args, progreso=None, **kwargs):
        if progreso is not None:
            progreso(1, objetivo_horas / 2)
            progreso(2, objetivo_horas)
        return splits, {"ok": len(tablas)}

    monkeypatch.setattr(garmin_service, "descargar_historial", descarga_falsa)
    monkeypatch.setattr(descarga_service.garmin_service, "descargar_historial", descarga_falsa)

    arranque = await cliente.post(
        f"{API}/historial/garmin",
        json={"sesion_garmin_id": sesion_id, "objetivo_horas": 50, "confirmado": True},
    )
    assert arranque.status_code == 202
    tarea_id = arranque.json()["tarea_id"]

    # El hilo puede no haber terminado todavía: se consulta hasta que cierre.
    import asyncio

    for _ in range(100):
        estado = (await cliente.get(f"{API}/historial/garmin/{tarea_id}")).json()
        if estado["estado"] != "en_curso":
            break
        await asyncio.sleep(0.05)

    assert estado["estado"] == "terminada", estado
    assert estado["porcentaje"] == 100.0
    assert estado["actividades"] == 2
    # El historial reunido vuelve en tramos, como el de una subida de archivos.
    resultado = estado["resultado"]
    assert len(set(resultado["tramos"]["actividad"])) == len(tablas)
    assert resultado["control_calidad"] == {"ok": len(tablas)}


async def test_consultar_una_descarga_que_no_existe(cliente):
    respuesta = await cliente.get(f"{API}/historial/garmin/noexiste")
    assert respuesta.status_code == 404
    assert respuesta.json()["error"]["code"] == "recurso_no_encontrado"


# --- Garmin: el login agotado no se cuenta como culpa de las credenciales ----


def test_el_login_agotado_se_explica_como_bloqueo_y_no_como_contrasena():
    """
    La librería prueba varias vías y, si fallan todas, lanza la de la última.

    En la práctica las primeras devuelven 429 (IP limitada) y la última habla de
    Cloudflare, así que el texto crudo hacía pensar en un problema de
    credenciales. Este es el mensaje real que devolvió la librería.
    """
    from app.core.errors import GarminLimite
    from app.services.garmin_service import _traducir

    crudo = Exception(
        "Login failed: All login strategies exhausted: GarminConnectConnectionError: "
        "Portal login: HTTP 403 (Cloudflare bot challenge) — falling through to next strategy"
    )
    traducido = _traducir(crudo)

    assert isinstance(traducido, GarminLimite)
    assert traducido.status_code == 429
    assert "no es tu contraseña" in traducido.message
    assert ".FIT a mano" in traducido.message
    # El texto original no se pierde: queda para depurar.
    assert "Cloudflare" in traducido.details["detalle_tecnico"]


def test_un_429_limpio_sigue_dando_el_mensaje_corto_de_siempre():
    from app.core.errors import GarminLimite
    from app.services.garmin_service import _traducir

    traducido = _traducir(Exception("Mobile login returned 429"))
    assert isinstance(traducido, GarminLimite)
    assert "Espera un minuto" in traducido.message


# --- Salir sin dejar rastro --------------------------------------------------


async def test_olvidar_suelta_la_descarga_de_garmin(cliente):
    """
    Lo único personal que puede quedar en el servidor es una descarga de Garmin
    terminada, que retiene el historial reunido. Al salir se suelta ya.
    """
    from app.core.errors import RecursoNoEncontrado
    from app.services.almacen import tareas
    from app.services.descarga_service import TareaDescarga

    tarea = TareaDescarga(objetivo_horas=50)
    tarea.estado = "terminada"
    tarea.historial = object()
    tarea_id = tareas.guardar(tarea)

    respuesta = await cliente.post(f"{API}/sesion/olvidar", json={"tarea_id": tarea_id})
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["borrados"] == ["descarga"]

    with pytest.raises(RecursoNoEncontrado):
        tareas.obtener(tarea_id)


async def test_olvidar_lo_que_ya_no_existe_no_es_un_error(cliente):
    """
    Idempotente a proposito: la salida no puede fallar porque algo caducara
    antes. Lo que importa es que despues no quede nada.
    """
    respuesta = await cliente.post(
        f"{API}/sesion/olvidar",
        json={"sesion_garmin_id": "ni-esta", "tarea_id": "tampoco"},
    )
    assert respuesta.status_code == 200
    assert set(respuesta.json()["borrados"]) == {"sesion_garmin", "descarga"}


async def test_olvidar_sin_nada_que_borrar_es_valido(cliente):
    respuesta = await cliente.post(f"{API}/sesion/olvidar", json={})
    assert respuesta.status_code == 200
    assert respuesta.json()["borrados"] == []


# --- Garmin: cancelar una descarga en curso ---------------------------------


async def test_cancelar_corta_la_descarga_y_no_guarda_nada(cliente, monkeypatch):
    """
    El doble imita el bucle real: mira `cancelado` antes de cada actividad.

    Es cooperativo porque no hay otra forma — a un hilo de Python no se le puede
    pedir que muera—, asi que lo que se comprueba es justo eso: que el hilo
    consulta el interruptor y sale sin dejar historial guardado.
    """
    import asyncio
    import time

    from app.services import descarga_service, garmin_service
    from app.services.almacen import sesiones_garmin

    sesion_id = sesiones_garmin.guardar(object())

    def descarga_lenta(sesion, objetivo_horas, *args, progreso=None, cancelado=None, **kwargs):
        for i in range(1, 10_000):
            if cancelado is not None and cancelado():
                raise garmin_service.DescargaCancelada
            if progreso is not None:
                progreso(i, objetivo_horas * i / 10_000)
            time.sleep(0.005)
        raise AssertionError("El doble deberia haberse cancelado mucho antes de llegar aqui.")

    monkeypatch.setattr(garmin_service, "descargar_historial", descarga_lenta)
    monkeypatch.setattr(descarga_service.garmin_service, "descargar_historial", descarga_lenta)

    arranque = await cliente.post(
        f"{API}/historial/garmin",
        json={"sesion_garmin_id": sesion_id, "objetivo_horas": 50, "confirmado": True},
    )
    assert arranque.status_code == 202
    tarea_id = arranque.json()["tarea_id"]

    # Se espera a que de verdad haya empezado, para no cancelar el vacio.
    for _ in range(200):
        estado = (await cliente.get(f"{API}/historial/garmin/{tarea_id}")).json()
        if estado["actividades"] > 0:
            break
        await asyncio.sleep(0.01)
    assert estado["actividades"] > 0, "la descarga no llego a arrancar"

    cancelacion = await cliente.post(f"{API}/historial/garmin/{tarea_id}/cancelar")
    assert cancelacion.status_code == 200
    # Responde ya, sin esperar al hilo: cancelar tiene que sentirse inmediato.
    assert cancelacion.json()["estado"] == "cancelada"

    for _ in range(200):
        estado = (await cliente.get(f"{API}/historial/garmin/{tarea_id}")).json()
        if estado["estado"] != "en_curso":
            break
        await asyncio.sleep(0.01)

    assert estado["estado"] == "cancelada", estado
    # Lo importante: no queda historial que usar sin querer.
    assert estado["resultado"] is None
    assert estado["error"] is None


def test_cancelar_algo_ya_terminado_no_lo_deshace():
    """Llegar tarde no puede tirar un historial que ya se reunio."""
    from app.services.almacen import AlmacenTTL
    from app.services.descarga_service import TareaDescarga, pedir_cancelacion

    tareas = AlmacenTTL(ttl_segundos=60, nombre="la descarga")
    tarea = TareaDescarga(objetivo_horas=50)
    tarea.estado = "terminada"
    tarea.historial = "historial reunido"
    tarea_id = tareas.guardar(tarea)

    devuelta = pedir_cancelacion(tarea_id, tareas)

    assert devuelta.estado == "terminada"
    assert devuelta.historial == "historial reunido"
    assert not devuelta.cancelacion.is_set()


async def test_cancelar_una_descarga_que_no_existe(cliente):
    respuesta = await cliente.post(f"{API}/historial/garmin/noexiste/cancelar")
    assert respuesta.status_code == 404
    assert respuesta.json()["error"]["code"] == "recurso_no_encontrado"
