"""
Cronometra el camino caliente de la API, para no optimizar a ciegas.

La regla del proyecto es que mandan los números medidos: ya pasó con el
paralelismo del parseo, donde lo esperado era x12 y lo real x2.1. Este script
mide lo que de verdad paga un usuario, cada cosa por separado, y se ejecuta
igual antes y después de tocar nada.

    cd backend && python scripts/medir_rendimiento.py
    cd backend && python scripts/medir_rendimiento.py --fit-dir ~/mis-fit --gpx ruta.gpx

Por defecto usa el `.GPX` de Atenas de `tests/datos/`. Los `.FIT` no viven en el
repositorio (son datos personales), así que el parseo solo se mide si se le
indica una carpeta con `--fit-dir`.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stamina_core import EstrategiaPipeline  # noqa: E402
from stamina_core.config import MODELO_PUBLICADO  # noqa: E402

REPETICIONES = 5
GPX_POR_DEFECTO = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "datos"
    / "data"
    / "rutas"
    / "athens_marathon_the_authentic.gpx"
)


def cronometrar(etiqueta: str, funcion, repeticiones: int = REPETICIONES) -> float:
    """Corre `funcion` varias veces y reporta la mediana, que es robusta al ruido."""
    tiempos = []
    for _ in range(repeticiones):
        t0 = time.perf_counter()
        funcion()
        tiempos.append(time.perf_counter() - t0)
    mediana = statistics.median(tiempos)
    print(
        f"  {etiqueta:<44} {mediana * 1000:8.1f} ms"
        f"   (min {min(tiempos) * 1000:.1f}, max {max(tiempos) * 1000:.1f})"
    )
    return mediana


def main() -> None:
    argumentos = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    argumentos.add_argument("--gpx", type=Path, default=GPX_POR_DEFECTO)
    argumentos.add_argument("--fit-dir", type=Path, default=None)
    opciones = argumentos.parse_args()

    # --- Arranque en frío: solo pasa una vez, al levantar la API ------------
    print("Arranque (una sola vez, al levantar la API)")
    t0 = time.perf_counter()
    pipeline = EstrategiaPipeline.cargar(MODELO_PUBLICADO, verboso=False)
    print(f"  {'cargar metadata.joblib ':<44} {(time.perf_counter() - t0) * 1000:8.1f} ms")

    # --- Lo que paga cada petición -----------------------------------------
    print("\nPor petición")

    gpx = opciones.gpx
    if not gpx.exists():
        print(f"  (falta el .GPX en {gpx}, se omite la predicción)")
        return

    cronometrar(
        "predecir_ruta: .GPX -> estrategia de 43 km",
        lambda: pipeline.predecir_ruta(gpx, tiempo_objetivo_h=4.0, temperatura_c=18.0),
    )

    ruta = pipeline.predecir_ruta(gpx, tiempo_objetivo_h=4.0, temperatura_c=18.0)

    cronometrar(
        "tabla_km: tramos de 100 m -> una fila por km",
        lambda: pipeline.tabla_km(ruta),
    )
    tabla = pipeline.tabla_km(ruta)

    from stamina_core import compilar_pasos, compilar_workout_fit  # noqa: PLC0415

    cronometrar(
        "compilar_pasos: 43 km -> bloques del reloj",
        lambda: compilar_pasos(tabla),
    )

    pasos = compilar_pasos(tabla)
    cronometrar(
        "compilar_workout_fit: bloques -> bytes .FIT",
        lambda: compilar_workout_fit(pasos, "Atenas"),
    )

    # --- La subida de historial, que es el paso lento del flujo -------------
    fits = sorted(opciones.fit_dir.glob("*.fit")) if opciones.fit_dir else []
    if not fits:
        print("\n  (sin --fit-dir con archivos .FIT, se omite el parseo)")
        return

    from stamina_core import parsear_lote  # noqa: PLC0415

    muestra = fits[:24]
    print(f"\nParseo de historial ({len(muestra)} archivos .FIT)")
    t0 = time.perf_counter()
    resultados = parsear_lote(muestra)
    dt = time.perf_counter() - t0
    buenos = sum(1 for _, tabla in resultados if tabla is not None)
    print(
        f"  {'parsear_lote (paralelo)':<44} {dt * 1000:8.1f} ms"
        f"   ({dt / len(muestra) * 1000:.0f} ms/archivo, {buenos}/{len(muestra)} ok)"
    )


if __name__ == "__main__":
    main()
