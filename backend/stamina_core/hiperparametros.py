"""
Hiperparámetros ya ajustados en la investigación.

Estos valores **no viajan dentro de `metadata.joblib`**: el notebook los derivaba
en tiempo de ejecución y los usaba para construir el diccionario `CANDIDATOS`.
Un pipeline cargado desde disco no los necesita (trae el modelo ya entrenado),
pero `EstrategiaPipeline.fit()` sí, porque tiene que construir el modelo que la
regla de capacidad le asigne al usuario. Sin ellos, el flujo "sube tu historial
y entreno para ti" no existe.

No se reafinan en esta fase. Ajustarlos invalida la curva de aprendizaje y la
tabla `reglas`, que se midieron con exactamente estos valores.
"""

from __future__ import annotations

# Barrido de la sección 3.3 del notebook: 11 valores en escala logarítmica.
# Ganó 300 con 0.0558 de habilidad en el régimen largo; entre el peor y el mejor
# alpha hay 0.042, así que la elección importa.
ALPHA_RIDGE = 300.0

# RandomizedSearchCV de la sección 3.4 (10 candidatos, GroupKFold de 3).
# MAE de 0.03788 en validación cruzada.
PARAMS_BOSQUE = {
    "n_estimators": 300,
    "min_samples_leaf": 25,
    "max_features": 0.5,
    "max_depth": None,
}

# Sección 4.1: tres configuraciones probadas. Empatan en habilidad en maratón
# dentro del margen de ruido (0.05), así que gana la más pequeña (0.2117). Elegir
# por la milésima hacía que la configuración cambiara según la máquina. Aun con
# ella la regla de capacidad nunca asigna la red: cuando destaca (10 y 20 h) lo
# hace dentro del margen de ruido, y el desempate favorece al modelo más simple.
CONFIG_CNN = {"unidades": 32, "dropout": 0.3, "lr": 5e-4}
