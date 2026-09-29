# Metodología

Cómo decide Stamina.AI, qué se midió para sostenerlo y qué no está comprobado.
Esto es el respaldo del producto: el [README](../README.md) cuenta qué hace, y
aquí está por qué se puede afirmar.

La investigación completa se hizo en un notebook (`notebook_StaminAI.ipynb`)
que se entrega aparte y no vive en este repositorio. De él salen el modelo
entrenado de `backend/modelo/`, los hiperparámetros y la tabla de la regla de
capacidad; las cifras de esta página son las de su última corrida.

## Índice

- [La regla de capacidad](#la-regla-de-capacidad)
- [Cuántas horas descargar de Garmin](#cuántas-horas-descargar-de-garmin)
- [La API](#la-api)
- [Qué está verificado y qué no](#qué-está-verificado-y-qué-no)
- [Límites del modelo](#límites-del-modelo)
- [Rendimiento del parseo](#rendimiento-del-parseo)
- [Referencias](#referencias)

## La regla de capacidad

El sistema decide solo qué modelo usar según lo que el corredor tenga
registrado, en vez de exigirle un mínimo para funcionar. La tabla se derivó una
sola vez; la API la lee de `backend/modelo/reglas.json`, extraída del artefacto,
y **nunca la recalcula**.

Con el historial de la investigación, en régimen de maratón:

| Historial | Modelo asignado | Habilidad |
|---|---|---|
| 1.8 h | Ritmo constante | 0.000 |
| 5.0 h | Ritmo constante | 0.000 |
| **10.0 h** | **Base física** | **0.221** |
| 19.9 h | RandomForest | 0.125 |
| 39.4 h | Base física | 0.209 |
| 79.8 h | RandomForest | 0.217 |
| 124.7 h | RandomForest | 0.303 |

La **habilidad** es qué fracción del error elimina la estrategia frente a salir
a ritmo fijo. En 0 no aporta nada; en 1 acertaría perfecto. Por debajo de 0.05
la ventaja no se distingue del ruido, y entonces el sistema devuelve ritmo
constante en vez de fingir.

Tres cosas que conviene leer bien:

- **El umbral de entrada son 10 horas.** Para el autor fueron 36 sesiones y 62
  días. Por debajo, ritmo constante con el motivo explicado.
- **La curva no es monótona.** Más horas no siempre significan mejor modelo. Un
  corredor con 60 h recibe Base física y uno con 30 h recibe RandomForest.
  Cada punto se apoya en solo dos maratones apartadas, así que las diferencias
  de un par de centésimas entre franjas son ruido, no señal.
- **La capacidad depende también de la distancia.** En carreras cortas ningún
  modelo gana de forma consistente, con ningún volumen de datos. A ese usuario
  decirle «te faltan horas» sería falso, y la API distingue los dos motivos.

El umbral **no está escrito en ninguna parte del código**, ni del backend ni del
frontend: sale de consultar `GET /capacidad`, porque depende de las horas y de
la distancia, y porque la tabla cambiaría si se volviera a correr el notebook.
Consultando con `horas=0` se obtiene el umbral de entrada del régimen — 10 h en
maratón, 1.8 h en carrera corta— y de ahí sale el mensaje que ve el usuario
antes de subir nada.

## Cuántas horas descargar de Garmin

La interfaz ofrece cuatro topes, y por defecto propone el más rápido: **lo justo
para personalizar**. Es el umbral que da la regla para la distancia (10 h en
maratón, 1.8 h en carrera corta) por 1.3, redondeado hacia arriba —13 h en
maratón—, porque se cuentan horas brutas y el control de calidad descarta
algunas. Los otros tres son 50, 100 y 135 h. El 135 no es redondo por casualidad:

- La última franja medida, la que da la mejor habilidad (0.303), empieza en
  **124.7 h**.
- `objetivo_horas` cuenta horas **brutas**: las actividades que luego suspenden
  el control de calidad ya van sumadas. De los 492 archivos del autor pasaron
  460, así que el descarte ronda el 7 %.
- 135 h brutas dejan unas 125 h netas: lo justo para alcanzar esa franja.

La descarga se puede **cancelar a mitad**, y es cooperativo por obligación:
a un hilo de Python no se le puede pedir que muera, así que el bucle mira un
interruptor antes de cada actividad. Se mira antes de bajar el archivo y no
después, para no gastar contra Garmin una petición que ya nadie quiere; el
corte se nota como mucho una actividad más tarde. Lo ya reunido **no se
guarda**: para quedarse con menos horas está el selector, que para eso ofrece
cuatro topes.

Bajar el tope no es gratis: con 13 h se personaliza con la base física
(habilidad esperada 0.221); con 100 h se acaba en la franja de 79.8 h, con el
Random Forest (0.217), y con 135 h, en la última (0.303). A cambio,
la espera es proporcional a las actividades: cada una cuesta su descarga y 0.6 s
de pausa obligatoria contra el límite de peticiones de Garmin. Por eso lo elige
la persona y no el programa.

**Leer cada `.FIT` ya no es lo que tarda.** `fitparse` decodificaba el archivo
entero y era el 92 % del tiempo de procesarlo; en un servidor con una fracción
de CPU, eso eran minutos por historial. `stamina_core/lector_fit.py` es unas
diez veces más rápido con la misma salida: comparado registro a registro con
fitparse en 686 archivos (los 492 del autor, los de la demo y los sintéticos), y
el reprocesado de los 492 da el mismo `splits.parquet` que el notebook. El
detalle está en [«Rendimiento del parseo»](#rendimiento-del-parseo).

## La API

Prefijo `/api/v1`. Documentación interactiva en `/docs`.

| Método y ruta | Qué hace |
|---|---|
| `GET /health` | Estado del servicio y de la regla, si Garmin está disponible y las versiones de pandas y scikit-learn |
| `POST /historial/archivos` | Procesa `.FIT` y devuelve los tramos de 100 m y el control de calidad, **sin guardarlos** |
| `POST /historial/resumen` | Horas, sesiones y capacidad de unos tramos |
| `GET /capacidad` | Qué modelo asigna la regla, y el motivo si es ritmo constante |
| `GET /objetivo/opciones` | Las cuatro opciones del selector |
| `POST /objetivo/sugerencia` | Sugiere un tiempo objetivo a partir de los tramos |
| `POST /estrategia` | GPX + tramos + objetivo → la estrategia, sus pasos para el reloj y el `.FIT` |
| `POST /exportar/garmin` | Sube el entrenamiento a la cuenta (solo con Garmin encendido) |
| `POST /historial/garmin`, `GET …/{tarea_id}`, `POST …/cancelar` | Descarga desde Garmin Connect con progreso (solo con Garmin encendido) |
| `POST /garmin/login`, `/garmin/mfa`, `DELETE /garmin/sesion/{id}` | Sesión con Garmin (solo con Garmin encendido) |
| `POST /sesion/olvidar` | Suelta la sesión y la descarga de Garmin al salir |

**La API no tiene estado.** Ninguna respuesta lleva un identificador que haya
que devolver después, salvo las de Garmin: el historial procesado vuelve al
navegador y viaja en cada petición, y la estrategia trae consigo sus pasos y su
`.FIT`. Así da igual en qué proceso caiga cada petición. Garmin es la
excepción: la sesión y la descarga tienen que seguir vivas entre peticiones, y
por eso la API se despliega como un servicio con un solo proceso (Render) y no
como funciones sin servidor, donde se probó y la descarga no llegaba a su fin.
`STAMINA_GARMIN_HABILITADO=False` apaga Garmin.

Ejemplo — la consulta que produce el disclaimer:

```bash
curl -s "http://localhost:8000/api/v1/capacidad?horas=6&km_objetivo=42.2"
```

```json
{
  "modelo": "Ritmo constante",
  "personalizada": false,
  "motivo": "sin_evidencia_en_esta_franja",
  "siguiente_franja": { "desde_horas": 10.0, "modelo": "Base física", "horas_faltantes": 4.0 },
  "regimen_fiable": true
}
```

### Salir y no dejar rastro

El historial y la estrategia nunca se guardan en el servidor: viven en la
pestaña y se van con ella. Al volver a la portada solo queda cerrar lo de Garmin
—la sesión y, si la hubo, una descarga que retiene el historial reunido—, y la
interfaz lo pide con `POST /sesion/olvidar`. En cuanto el navegador recoge una
descarga terminada, además, la suelta sin esperar a salir.

### Credenciales de Garmin

El login pide correo, contraseña y código MFA de una cuenta real. **No se
guardan en ningún sitio**: ni en disco, ni en base de datos, ni en los registros
(el logger redacta por nombre de clave). La sesión vive en memoria y caduca a los
15 minutos, y ninguna descarga ni subida ocurre sin `confirmado=true`.

Aun así, un backend que recibe credenciales de terceros por HTTP es una
superficie de ataque que el notebook, con `getpass` en local, no tenía. Es una
decisión del autor, tomada sabiendo el riesgo.

Ningún test toca la red: un guardia sobre `socket.socket.connect` solo deja pasar
loopback, para que un descuido en los tests de Garmin no golpee una cuenta real.

## Qué está verificado y qué no

**Verificado.** El módulo reproduce la estrategia del notebook al centésimo
(km 1–5 a 5.06 / 4.87 / 4.85 / 4.86 / 4.86 min/km). Reentrenar desde cero da el
mismo modelo. El `.FIT` generado se relee con `fitparse`, Garmin Connect aceptó
la subida por API asignándole identificador, y el entrenamiento **se probó en un
reloj físico**, que era lo último que quedaba por comprobar de la cadena de
exportación.

**Lo que sigue sin medirse** no es la cadena técnica, sino el alcance de lo
medido: está en «Límites del modelo», justo debajo.

## Límites del modelo

Tal como los dejó escritos el notebook en su sección 6.3:

- **Describe, no prescribe.** La métrica premia parecerse a lo que el corredor
  hizo, y lo que hizo fue salir fuerte y pagarlo en la segunda mitad. Como
  diagnóstico de en qué kilómetros se pierde tiempo funciona; como recomendación
  de cómo se debería correr, todavía no.
- **Un solo corredor.** Toda la curva sale del historial del autor. Que el
  umbral esté donde está para él no garantiza que esté ahí para otra persona.
- **Dos maratones de prueba.** El escalón general se lee, pero los altibajos
  entre franjas contiguas son ruido.
- **El hueco de 16 a 42 km.** No hay ninguna carrera medida en ese rango, que es
  justo donde cae una media maratón. La API lo marca como
  `distancia_extrapolada` y la interfaz lo avisa.
- **Un solo reloj.** El entrenamiento se probó en el reloj del autor. Los
  campos del FIT son estándar, pero cada fabricante y cada versión de firmware
  interpretan los entrenamientos estructurados a su manera.

## Rendimiento del parseo

Leer los `.FIT` es lo único del producto que crece con el historial, así que se
midió aparte.

**El lector.** Al principio los leía `fitparse`, que decodifica el archivo
entero: con los 47 `.FIT` de 12 h y un núcleo, 9.5 s, de ellos 6.8 dentro de
`fitparse`. `stamina_core/lector_fit.py` lee solo los mensajes `record` y los
campos que se usan, con la misma salida —comparada registro a registro en 686
archivos—, y sigue comprobando el CRC, porque son datos que sube el usuario y un
archivo corrupto se tiene que detectar. Las mismas 12 h, subidas por la API con
un núcleo, tardan ahora **1.2 s**. Si un archivo trae algo que el lector no
replica —campos de desarrollador de Connect IQ— o no lo puede leer,
`procesar_fit` se lo pasa a `fitparse`: el resultado nunca cambia; como mucho,
tarda lo de antes.

**En paralelo.** Los `.FIT` que se suben a mano se reparten entre procesos. Se
midió con `fitparse`, en la máquina de desarrollo (12 núcleos, 48 archivos, pool
ya caliente):

| Modo | Tiempo | Ganancia |
|---|---|---|
| Secuencial | 11.75 s (245 ms/archivo) | — |
| 4 procesos | 5.60 s | ×2.10 |
| 6 procesos | 5.32 s | ×2.21 |
| 12 procesos | 6.27 s | ×1.87 |
| 8 hilos | 13.27 s | ×0.89 |

De ahí salen las dos constantes de `stamina_core/ingesta.py`: seis procesos en
vez de «todos los que haya», porque a partir de ahí la sobresuscripción pesa más
que el reparto; y un mínimo de archivos por debajo del cual se queda secuencial,
porque arrancar el pool cuesta unos segundos (con 3 archivos: 3.3 s en paralelo
contra 0.87 s secuencial). Con hilos es más lento que no paralelizar: la lectura
es Python puro y el GIL no deja. En el servidor publicado, que tiene una
fracción de núcleo, se fija `STAMINA_PROCESOS_PARSEO=1`: ahí repartir solo
añadiría el coste de arrancar los procesos.

### Lo que cuesta una estrategia

Medido con `backend/scripts/medir_rendimiento.py`, que reproduce el camino
caliente de la API (mediana de 5 repeticiones, misma máquina):

| Operación | Tiempo |
|---|---|
| Cargar `reglas.json` (3 KB) | unos ms, **una sola vez** al arrancar |
| `predecir_ruta`: del `.GPX` a los 43 km | 135 ms |
| `tabla_km`: de tramos de 100 m a una fila por km | 11 ms |
| `compilar_pasos`: de 43 km a los bloques del reloj | 4.8 ms |
| `compilar_workout_fit`: de bloques a bytes `.FIT` | 0.7 ms |

O sea que **predecir la estrategia entera cuesta unos 150 ms**. Lo que pesa es
lo que depende del historial: leerlo (unos 25 ms por `.FIT` con un núcleo) y
entrenar el modelo de esa persona, que se mide justo debajo. Por eso la barra de
progreso está en la subida y no en el cálculo.

En la descarga de Garmin **no** se paraleliza, y es deliberado: ahí cada
actividad cuesta la descarga más 0.6 s de pausa obligatoria contra el límite de
peticiones, y con el lector nuevo leer el archivo es una parte pequeña de eso.
Repartirlo apenas acortaría la espera, y a cambio complicaría el código que habla
con una cuenta real.

### Sin demostración: la API solo carga la regla

Hubo una demostración que calculaba con el modelo del autor sin subir nada. Se
quitó el 2026-09-26, porque obligaba a cargar al arrancar el artefacto completo
(24.5 MB, con los 300 árboles del Random Forest) y a desplegar pyarrow (156 MB):
el pickle guarda las columnas de texto de pandas 3 respaldadas por pyarrow y sin
él no se lee. Lo único que la API necesita de verdad es la tabla `reglas`, y
ahora la lee de `backend/modelo/reglas.json`, extraída del artefacto por
`scripts/extraer_reglas.py`. Una prueba comprueba que las dos coinciden.
El artefacto sigue en el repositorio para las pruebas de reproducción.

### El modelo del usuario se entrena en cada cálculo

Subir historial propio entrena un pipeline con **esos** datos: el modelo del
artefacto esta ajustado al autor y sus parametros son su forma de fatigarse,
asi que no se puede reusar para otra persona. Lo que si se hereda del
notebook, y es lo valioso, es la investigacion: las variables, los
hiperparametros y la tabla `reglas`.

Hasta el 2026-09-26 ese ajuste se cacheaba junto al historial en el servidor.
Con la API sin estado no hay dónde guardarlo, así que se entrena en cada
petición a `POST /estrategia`. Es asumible porque es barato: medido con 1 núcleo,
0.6 s con la base física (12 h de historial) y 12.7 s en el peor caso, el Random
Forest con el historial completo del autor.

Un detalle medido al pasar a este flujo: las sesiones sin temperatura se
rellenan con la mediana del historial que llega. El notebook la calculó sobre
sus 460 actividades, incluidas las 6 carreras de prueba; con las 454 de
entrenamiento cambia 0.07 °C y mueve algún kilómetro 0.02 min/km como mucho.

## Referencias

- Minetti, A. E., et al. (2002). Energy cost of walking and running at extreme
  uphill and downhill slopes. *Journal of Applied Physiology, 93*(3), 1039-1046.
- Riegel, P. S. (1981). Athletic records and human endurance. *American
  Scientist, 69*(3), 285-290.
- Pedregosa, F., et al. (2011). Scikit-learn. *JMLR, 12*, 2825-2830.
