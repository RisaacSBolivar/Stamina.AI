# Stamina.AI — backend

API REST sobre `stamina_core`, el pipeline extraído del notebook de investigación
(`notebook_StaminAI.ipynb`, que se entrega aparte y no vive en este repositorio).

- **`stamina_core/`** — el pipeline de investigación como módulo importable:
  ingeniería de variables, los cuatro modelos candidatos, la regla de capacidad
  y el compilador de entrenamiento estructurado. No se toca para "mejorar el
  modelo": cualquier cambio ahí invalida los números medidos.
- **`app/`** — la capa FastAPI (fase 2).
- **`tests/`** — incluye la prueba de persistencia que compara contra la última
  corrida del notebook.

Stack: Python 3.12, `pandas>=3.0`, `scikit-learn>=1.9`. Los dos pisos son
requisito de compatibilidad, no preferencia: el `metadata.joblib` entregado se
escribió con pandas 3.0.5 y con pandas 2.x no se puede leer.

Se ejecuta en Linux (WSL). La instalación y los comandos están en el
[README de la raíz](../README.md).
