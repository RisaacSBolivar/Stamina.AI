"""
Los cuatro candidatos de modelo, con la misma interfaz `fit` / `predecir`.

Estas clases son **exactamente** las que `joblib` referenció al guardar
`metadata.joblib`: el pickle apunta a `ModeloTabular` por nombre, no guarda su
código. Mover o renombrar cualquiera de ellas rompe la carga de artefactos ya
escritos. Ver `compat.py` para el puente con los artefactos que el notebook
guardó desde `__main__`.

Cada modelo devuelve dos salidas, ritmo y frecuencia cardíaca relativas
(`v_ratio`, `fc_ratio`), porque el nivel absoluto lo fija después el corredor
con su tiempo objetivo.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.base import clone

from .config import CANALES, ESCALARES, LIMITE_Z, SEMILLA, VENTANA, VENTANA_ADELANTE, VENTANA_ATRAS


def _keras():
    """
    Importa Keras solo cuando de verdad hace falta.

    TensorFlow tarda segundos en importarse y ocupa cientos de MB. Como el
    modelo elegido por la regla de capacidad nunca es la red con el historial
    actual, importar `stamina_core` no debe arrastrarlo: el backend arranca sin
    TensorFlow instalado y solo lo pide si tiene que cargar un `cnn.keras`.
    """
    try:
        from tensorflow import keras  # noqa: PLC0415
    except ImportError as error:  # pragma: no cover - depende del entorno
        raise ImportError(
            "Este artefacto usa la red convolucional y hace falta TensorFlow. "
            'Instálalo con: pip install -e ".[red]"'
        ) from error
    return keras


class RitmoConstante:
    """Lo que hace hoy el corredor: el mismo ritmo en todos los tramos."""

    nombre = "Ritmo constante"

    def fit(self, datos, datos_val=None):
        return self

    def predecir(self, datos):
        unos = np.ones(len(datos))
        return unos, unos


class BaseFisica:
    """
    Modelo de dos parámetros: v/v_media = costo_rel^(-alfa) * exp(-lambda * km).

    Tomando logaritmos queda lineal, así que se resuelve por mínimos cuadrados
    y no hay nada que sintonizar. Es el modelo que abre la puerta a las 10 horas
    de historial, con 0.221 de habilidad, por delante del bosque (0.137).
    """

    nombre = "Base física"

    def _matriz(self, datos):
        return np.c_[
            np.log(datos["costo_rel"].to_numpy()),
            datos["dist_km"].to_numpy(),
            np.ones(len(datos)),
        ]

    def fit(self, datos, datos_val=None):
        X = self._matriz(datos)
        self.coef_v = np.linalg.lstsq(X, np.log(datos["v_ratio"].to_numpy()), rcond=None)[0]
        self.coef_fc = np.linalg.lstsq(X, np.log(datos["fc_ratio"].to_numpy()), rcond=None)[0]
        return self

    def predecir(self, datos):
        X = self._matriz(datos)
        return np.exp(X @ self.coef_v), np.exp(X @ self.coef_fc)


class ModeloTabular:
    """Envuelve un regresor de sklearn para que dé las dos salidas (ritmo y FC)."""

    def __init__(self, estimador, nombre, variables):
        self.estimador = estimador
        self.nombre = nombre
        self.variables = variables

    def fit(self, datos, datos_val=None):
        self.modelo_v = clone(self.estimador).fit(datos[self.variables], datos["v_ratio"])
        self.modelo_fc = clone(self.estimador).fit(datos[self.variables], datos["fc_ratio"])
        return self

    def predecir(self, datos):
        return (
            self.modelo_v.predict(datos[self.variables]),
            self.modelo_fc.predict(datos[self.variables]),
        )


def ventanas_terreno(tabla: pd.DataFrame) -> np.ndarray:
    """Para cada tramo, la ventana de terreno centrada en él."""
    matriz = tabla[CANALES].to_numpy(dtype="float32")
    matriz = np.pad(matriz, ((VENTANA_ATRAS, VENTANA_ADELANTE), (0, 0)), mode="edge")
    ventanas = np.lib.stride_tricks.sliding_window_view(matriz, VENTANA, axis=0)
    return np.transpose(ventanas, (0, 2, 1)).copy()


class RedTerreno:
    """
    CNN 1-D sobre el perfil del terreno, con dos salidas (ritmo y FC relativos).

    Es híbrida: aprende el residuo logarítmico sobre la base física en lugar del
    objetivo directo.

    Con el historial de la investigación sale negativa en 4 de los 7
    presupuestos, y donde destaca (10 y 20 h) lo hace dentro del margen de ruido,
    así que la regla nunca la asigna. Se conserva porque forma parte de la curva
    medida y porque un artefacto futuro podría haberla elegido, no porque sea la
    recomendada.
    """

    nombre = "CNN-Híbrida"

    def __init__(
        self,
        unidades=48,
        dropout=0.2,
        lr=1e-3,
        filtros=32,
        epocas=80,
        lote=256,
        paciencia=8,
    ):
        self.config = {
            "unidades": unidades,
            "dropout": dropout,
            "lr": lr,
            "filtros": filtros,
            "epocas": epocas,
            "lote": lote,
            "paciencia": paciencia,
        }

    def _tensores(self, datos, con_objetivo=True):
        secuencias, contexto, objetivos, indices = [], [], [], []

        for _, actividad in datos.groupby("actividad", sort=False):
            actividad = actividad.sort_values("split")
            secuencias.append(ventanas_terreno(actividad))
            contexto.append(actividad[ESCALARES].to_numpy("float32"))
            indices.append(actividad.index.to_numpy())
            if con_objetivo:
                objetivos.append(actividad[["v_ratio", "fc_ratio"]].to_numpy("float32"))

        return (
            np.concatenate(secuencias),
            np.concatenate(contexto),
            np.concatenate(objetivos) if con_objetivo else None,
            np.concatenate(indices),
        )

    def _normalizar(self, secuencias, contexto):
        return (
            np.clip((secuencias - self.mu_s) / self.sd_s, -LIMITE_Z, LIMITE_Z),
            np.clip((contexto - self.mu_c) / self.sd_c, -LIMITE_Z, LIMITE_Z),
        )

    def _construir(self):
        keras = _keras()
        layers = keras.layers
        cfg = self.config

        entrada_terreno = keras.Input((VENTANA, len(CANALES)), name="terreno")
        entrada_contexto = keras.Input((len(ESCALARES),), name="contexto")

        x = layers.Conv1D(cfg["filtros"], 5, padding="same", activation="relu")(entrada_terreno)
        x = layers.Conv1D(cfg["filtros"], 5, padding="same", dilation_rate=2, activation="relu")(x)
        x = layers.GlobalAveragePooling1D()(x)

        h = layers.Concatenate()([x, entrada_contexto])
        h = layers.Dense(cfg["unidades"], activation="relu")(h)
        h = layers.Dropout(cfg["dropout"])(h)
        salida = layers.Dense(2, name="ritmo_y_fc")(h)

        red = keras.Model([entrada_terreno, entrada_contexto], salida)
        red.compile(
            optimizer=keras.optimizers.Adam(cfg["lr"]),
            loss="huber",  # huber para que las paradas no dominen
            metrics=["mae"],
        )
        return red

    def fit(self, datos, datos_val=None, verbose=0):
        keras = _keras()
        keras.utils.set_random_seed(SEMILLA)

        self.base = BaseFisica().fit(datos)

        secuencias, contexto, objetivo, indices = self._tensores(datos)
        v_fisica, fc_fisica = self.base.predecir(datos.loc[indices])
        residuo = (np.log(np.maximum(objetivo, 1e-3)) - np.log(np.c_[v_fisica, fc_fisica])).astype(
            "float32"
        )

        planas = secuencias.reshape(-1, len(CANALES))
        self.mu_s, self.sd_s = planas.mean(0), planas.std(0) + 1e-8
        self.mu_c, self.sd_c = contexto.mean(0), contexto.std(0) + 1e-8
        sec_norm, ctx_norm = self._normalizar(secuencias, contexto)

        self.red = self._construir()
        parada = keras.callbacks.EarlyStopping(
            monitor="val_loss",
            patience=self.config["paciencia"],
            restore_best_weights=True,
        )
        self.historia = self.red.fit(
            [sec_norm, ctx_norm],
            residuo,
            validation_split=0.15,
            epochs=self.config["epocas"],
            batch_size=self.config["lote"],
            verbose=verbose,
            callbacks=[parada],
        )

        self.val_loss = float(np.min(self.historia.history["val_loss"]))
        self.epocas_usadas = len(self.historia.history["loss"])
        return self

    def predecir(self, datos):
        secuencias, contexto, _, indices = self._tensores(datos, con_objetivo=False)
        prediccion = self.red.predict(list(self._normalizar(secuencias, contexto)), verbose=0)

        # _tensores reordena por actividad, así que hay que devolver las filas
        # al orden en que venían.
        orden = pd.Series(np.arange(len(indices)), index=indices).reindex(datos.index)
        prediccion = prediccion[orden.to_numpy()]

        v_fisica, fc_fisica = self.base.predecir(datos)
        return np.exp(prediccion[:, 0]) * v_fisica, np.exp(prediccion[:, 1]) * fc_fisica

    def estado(self):
        """Lo que hace falta para reconstruir el modelo, menos los pesos."""
        return {
            "config": self.config,
            "mu_s": self.mu_s,
            "sd_s": self.sd_s,
            "mu_c": self.mu_c,
            "sd_c": self.sd_c,
            "coef_v": self.base.coef_v,
            "coef_fc": self.base.coef_fc,
        }

    @classmethod
    def desde_estado(cls, estado, red):
        """Reconstruye el objeto a partir de estado() y una red ya cargada."""
        objeto = cls(**estado["config"])
        objeto.red = red
        objeto.base = BaseFisica()
        objeto.base.coef_v = estado["coef_v"]
        objeto.base.coef_fc = estado["coef_fc"]
        objeto.mu_s, objeto.sd_s = estado["mu_s"], estado["sd_s"]
        objeto.mu_c, objeto.sd_c = estado["mu_c"], estado["sd_c"]
        return objeto
