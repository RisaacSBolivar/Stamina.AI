# Frontend

La interfaz de Stamina.AI: **Angular 22** con signals, Tailwind 4 y ECharts para
las gráficas. Los cinco pasos del flujo viven en
`src/app/pages/estrategia/`, y el estado compartido en `src/app/core/estado.service.ts`.

## No se arranca desde aquí

Usa el `Makefile` de la raíz, no `ng serve` a pelo:

```bash
make dev             # levanta API y UI a la vez
make dev-frontend    # solo la UI, en :4200
```

`make dev-frontend` añade `--poll 2000`, y no es un capricho: el código vive en
`/mnt/c` bajo WSL, donde no llegan los eventos de `inotify`, así que sin el
sondeo la recarga automática no se entera de nada.

La instalación completa y los requisitos están en el
[README de la raíz](../README.md).

## Los tipos de la API no se escriben a mano

`src/app/core/api/schema.d.ts` es **generado**. Sale del OpenAPI del backend:

```bash
make contracts       # backend -> openapi.json -> schema.d.ts
```

Si el backend cambia un campo y aquí no se ajusta, `make lint-frontend`
(`tsc --noEmit`) lo caza antes de que llegue al navegador. Editar ese archivo a
mano es tirar el mecanismo.

## Comprobaciones

```bash
make test-frontend   # Vitest
make lint-frontend   # tsc --noEmit
```

## Las reglas que no se negocian

Están medidas y cubiertas por pruebas; el porqué de cada una está en
[`docs/METODOLOGIA.md`](../docs/METODOLOGIA.md).

- **Ningún umbral se escribe en el frontend.** Salen todos de `GET /capacidad`,
  porque el mínimo es de 10 h en maratón pero de 1.8 h en carrera corta: una
  cifra fija sería falsa.
- **El historial vive en el navegador, no en el servidor.** Los tramos
  procesados se guardan en `EstadoService` y viajan en cada petición; al salir
  se borran con la pestaña, y solo hay que cerrar la sesión de Garmin.
- **Lo visual va primero**: una frase y tres cifras, la gráfica, la carrera por
  capítulos y el medidor de evidencia. El detalle, plegado o en un ⓘ.
- **Garmin solo aparece si `GET /health` dice que está disponible.**
