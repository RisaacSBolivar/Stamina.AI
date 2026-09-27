"""
`EstrategiaPipeline`: de historial de un corredor + una ruta a una estrategia.

Sección 5 del notebook, sin cambios de comportamiento. Las dos llamadas que usa
el backend son `cargar(carpeta)` y `predecir_ruta(gpx, tiempo, temperatura)`.

La regla de capacidad se le pasa ya derivada: es un insumo fijo, no algo que el
pipeline recalcule.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

from .config import K_ZONAS, SEMILLA, SPLIT_M, VARS_MODELO, VARS_ZONA
from .ingesta import procesar_gpx
from .modelos import RedTerreno
from .reglas import candidatos, elegir_modelo
from .variables import a_ritmo, variables_terreno
from .zonas import ordenar_zonas


class EstrategiaPipeline:
    """
    De historial de un corredor + una ruta a una estrategia de ritmo.

    La regla de capacidad se le pasa ya derivada: es un insumo fijo, no algo
    que el pipeline recalcule.
    """

    VERSION = "6.0"
    SUAVIZADO_ESTRATEGIA = 20  # 20 tramos = 2 km, ver predecir_ruta()

    def __init__(self, reglas, k_zonas=K_ZONAS, semilla=SEMILLA, verboso=True):
        self.reglas = {nombre: tabla.copy() for nombre, tabla in reglas.items()}
        self.k_zonas = k_zonas
        self.semilla = semilla
        self.verboso = verboso
        self.registro = []

    def _anotar(self, mensaje):
        self.registro.append(mensaje)
        if self.verboso:
            print(mensaje)

    def fit(self, dataset_usuario, sesiones_usuario, km_objetivo=42.2):
        """
        Entrena con el historial de UN usuario.

        Consulta la regla con sus horas acumuladas y entrena únicamente el
        modelo que le toca. El km objetivo hace falta porque la regla depende
        del régimen; por defecto asumo maratón.
        """
        t0 = time.perf_counter()

        self.horas_ = float(sesiones_usuario["minutos"].sum() / 60)
        self.km_objetivo_ = float(km_objetivo)
        self.modelo_nombre_, self.habilidad_esperada_ = elegir_modelo(
            self.horas_, km_objetivo, self.reglas
        )

        self._anotar(
            f"[fit] {self.horas_:.1f} h en {len(sesiones_usuario)} sesiones, "
            f"objetivo {km_objetivo:.1f} km"
        )
        self._anotar(
            f"[fit] la regla dice: {self.modelo_nombre_} "
            f"(habilidad esperada {self.habilidad_esperada_:.2f})"
        )

        self.modelo_ = candidatos()[self.modelo_nombre_]().fit(dataset_usuario)

        # Zonas y límites de entrada, con los datos de este usuario
        self.escalador_zonas_ = StandardScaler().fit(dataset_usuario[VARS_ZONA])
        self.kmeans_ = KMeans(n_clusters=self.k_zonas, n_init=10, random_state=self.semilla).fit(
            self.escalador_zonas_.transform(dataset_usuario[VARS_ZONA])
        )
        self.mapa_zona_, _ = ordenar_zonas(dataset_usuario, self.kmeans_, self.escalador_zonas_)
        self.limites_ = dataset_usuario[VARS_MODELO].agg(["min", "max"])

        # La FC de referencia la saco de sus carreras largas si las tiene
        largas = dataset_usuario[dataset_usuario["distancia_total_km"] > 10]
        base_fc = largas if len(largas) else dataset_usuario
        self.fc_referencia_ = float(base_fc["fc"].mean())

        self.segundos_fit_ = time.perf_counter() - t0
        self._anotar(
            f"[fit] entrenado en {self.segundos_fit_:.1f} s, "
            f"FC de referencia {self.fc_referencia_:.0f} bpm"
        )
        return self

    def _perfil_ruta(self, ruta_gpx, temperatura_c):
        """Acepta un .GPX (ruta o bytes) o una tabla de tramos con `split` y `elev`."""
        if isinstance(ruta_gpx, (str, Path, bytes, bytearray)):
            perfil = procesar_gpx(ruta_gpx)
        else:
            perfil = ruta_gpx.copy()

        perfil = variables_terreno(perfil)
        perfil["actividad"] = "objetivo"
        perfil["temperatura"] = float(temperatura_c)
        return perfil

    def predecir_ruta(self, ruta_gpx, tiempo_objetivo_h, temperatura_c=18.0):
        """
        Estrategia de ritmo y FC para una ruta, tramo a tramo.

        Pasos: variables de terreno, recorte al rango entrenado, predicción,
        suavizado, anclaje al tiempo objetivo y asignación de zona.

        El suavizado a 2 km no es cosmético. Un bosque parte por umbrales y
        produce saltos de decenas de segundos por kilómetro entre tramos
        contiguos; como forma de la curva están bien, pero nadie puede correr
        eso. La media móvil conserva la tendencia y la vuelve ejecutable.
        """
        ruta = self._perfil_ruta(ruta_gpx, temperatura_c)
        km_ruta = ruta["dist_km"].max()

        if (km_ruta > 40) != (self.km_objetivo_ > 40):
            self._anotar(
                f"[aviso] la ruta mide {km_ruta:.1f} km y entrené para "
                f"{self.km_objetivo_:.1f} km. Conviene volver a llamar a "
                f"fit() con km_objetivo={km_ruta:.0f}"
            )

        entrada = ruta.copy()
        for variable in VARS_MODELO:
            entrada[variable] = entrada[variable].clip(
                self.limites_.loc["min", variable],
                self.limites_.loc["max", variable],
            )

        v_ratio, fc_ratio = self.modelo_.predecir(entrada)

        def suavizar(prediccion):
            return (
                pd.Series(prediccion, index=ruta.index)
                .rolling(self.SUAVIZADO_ESTRATEGIA, center=True, min_periods=1)
                .mean()
                .to_numpy()
            )

        v_ratio, fc_ratio = suavizar(v_ratio), suavizar(fc_ratio)

        # Anclaje al tiempo objetivo. Ojo: el tiempo total es la suma de los
        # tiempos de cada tramo, no el promedio de las velocidades.
        v_objetivo = km_ruta * 1000 / (tiempo_objetivo_h * 3600)
        ruta["v_ratio"] = v_ratio / v_ratio.mean()
        ruta["v_estrategia"] = ruta["v_ratio"] * v_objetivo
        ruta["v_estrategia"] *= (SPLIT_M / ruta["v_estrategia"]).sum() / (tiempo_objetivo_h * 3600)
        ruta["ritmo_estrategia"] = a_ritmo(ruta["v_estrategia"])

        ruta["fc_ratio"] = fc_ratio / fc_ratio.mean()
        ruta["fc_objetivo"] = ruta["fc_ratio"] * self.fc_referencia_

        etiquetas = self.kmeans_.predict(self.escalador_zonas_.transform(ruta[VARS_ZONA]))
        ruta["zona"] = pd.Series(etiquetas, index=ruta.index).map(self.mapa_zona_)

        ruta["km"] = np.ceil(ruta["dist_km"]).astype(int)
        ruta["tiempo_split_min"] = ruta["ritmo_estrategia"] * SPLIT_M / 1000
        return ruta

    @staticmethod
    def tabla_km(ruta: pd.DataFrame) -> pd.DataFrame:
        """Resumen por kilómetro: lo que el corredor se lleva al reloj."""
        tabla = (
            ruta.groupby("km")
            .agg(
                ritmo_objetivo=("ritmo_estrategia", "mean"),
                fc_objetivo=("fc_objetivo", "mean"),
                pendiente=("pendiente", "mean"),
                elevacion=("elev", "last"),
                zona=("zona", lambda s: s.mode().iat[0]),
                tiempo_min=("tiempo_split_min", "sum"),
            )
            .reset_index()
            .round(2)
        )
        tabla["tiempo_acum_min"] = tabla["tiempo_min"].cumsum().round(1)
        return tabla

    @staticmethod
    def indicadores(ruta: pd.DataFrame) -> dict:
        """
        Los cinco números de cabecera de la estrategia (sección 7.1).

        Se calculan aquí y no en la interfaz para que backend y notebook
        reporten exactamente lo mismo.
        """
        return {
            "tiempo_estimado_h": round(ruta["tiempo_split_min"].sum() / 60, 2),
            "desnivel_positivo_m": round(float(ruta["elev"].diff().clip(lower=0).sum())),
            "pendiente_maxima_pct": round(float(ruta["pendiente"].max()), 1),
            "pct_exigencia_alta": round(
                100 * float(ruta["zona"].isin(["Exigencia alta", "Exigencia crítica"]).mean()),
                1,
            ),
            "fc_objetivo_media": round(float(ruta["fc_objetivo"].mean())),
        }

    def guardar(self, carpeta):
        """
        Escribe una carpeta portable.

        Siempre un metadata.joblib, y un cnn.keras aparte solo si el modelo
        elegido fue la red. Una red neuronal no se guarda con joblib.
        """
        carpeta = Path(carpeta)
        carpeta.mkdir(parents=True, exist_ok=True)

        metadatos = {
            "version": self.VERSION,
            "creado": datetime.now().isoformat(timespec="seconds"),
            "reglas": self.reglas,
            "modelo": self.modelo_nombre_,
            "horas_historial": self.horas_,
            "km_objetivo": self.km_objetivo_,
            "habilidad_esperada": self.habilidad_esperada_,
            "fc_referencia": self.fc_referencia_,
            "limites": self.limites_,
            "escalador_zonas": self.escalador_zonas_,
            "kmeans": self.kmeans_,
            "mapa_zona": self.mapa_zona_,
            "k_zonas": self.k_zonas,
            "semilla": self.semilla,
            "registro": self.registro,
        }

        if isinstance(self.modelo_, RedTerreno):
            self.modelo_.red.save(str(carpeta / "cnn.keras"))
            metadatos["modelo_obj"] = None
            metadatos["cnn"] = self.modelo_.estado()
        else:
            metadatos["modelo_obj"] = self.modelo_
            metadatos["coef_fisica"] = getattr(self.modelo_, "coef_v", None)

        joblib.dump(metadatos, carpeta / "metadata.joblib")

        archivos = {p.name: p.stat().st_size / 1024 for p in sorted(carpeta.iterdir())}
        self._anotar(
            "[guardar] "
            + carpeta.name
            + "/: "
            + ", ".join(f"{n} ({kb:.0f} KB)" for n, kb in archivos.items())
        )
        return carpeta

    @classmethod
    def cargar(cls, carpeta, verboso=True):
        """
        Reconstruye un pipeline guardado.

        Antes de deserializar publica las clases del pipeline en `__main__`: los
        artefactos que escribió el notebook referencian `__main__.ModeloTabular`
        y sin ese puente la carga falla con AttributeError. Ver `compat.py`.
        """
        from .compat import registrar_alias_main  # noqa: PLC0415

        registrar_alias_main()

        carpeta = Path(carpeta)
        metadatos = joblib.load(carpeta / "metadata.joblib")

        pipeline = cls(
            metadatos["reglas"],
            k_zonas=metadatos["k_zonas"],
            semilla=metadatos["semilla"],
            verboso=verboso,
        )

        if metadatos["modelo_obj"] is None:
            from .modelos import _keras  # noqa: PLC0415

            red = _keras().models.load_model(str(carpeta / "cnn.keras"))
            pipeline.modelo_ = RedTerreno.desde_estado(metadatos["cnn"], red)
        else:
            pipeline.modelo_ = metadatos["modelo_obj"]

        pipeline.modelo_nombre_ = metadatos["modelo"]
        pipeline.horas_ = metadatos["horas_historial"]
        pipeline.km_objetivo_ = metadatos["km_objetivo"]
        pipeline.habilidad_esperada_ = metadatos["habilidad_esperada"]
        pipeline.fc_referencia_ = metadatos["fc_referencia"]
        pipeline.limites_ = metadatos["limites"]
        pipeline.escalador_zonas_ = metadatos["escalador_zonas"]
        pipeline.kmeans_ = metadatos["kmeans"]
        pipeline.mapa_zona_ = metadatos["mapa_zona"]
        pipeline.registro = list(metadatos["registro"])
        pipeline.creado_ = metadatos.get("creado")
        pipeline.version_artefacto_ = metadatos.get("version")

        pipeline._anotar(
            f"[cargar] {pipeline.modelo_nombre_}, entrenado con "
            f"{pipeline.horas_:.1f} h, versión {metadatos['version']}"
        )
        return pipeline
