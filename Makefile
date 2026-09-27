.DEFAULT_GOAL := help
SHELL := /bin/bash

# Se ejecuta en Linux (WSL). El venv vive en ext4 y se enlaza desde aqui,
# porque /mnt/c va por 9p y es ~36x mas lento escribiendo archivos.
BACKEND  := backend
FRONTEND := frontend
CACHE    := $(HOME)/.stamina-cache
PY       := $(CACHE)/venv/bin/python

# Generador de tipos TS. Fijado aqui porque no vive en package.json (ver
# el objetivo `contracts`).
OPENAPI_TS := 7.13.0

# --- Node de Linux -----------------------------------------------------------
# El `node` que ve un shell NO interactivo en WSL es el de Windows
# (/mnt/c/Program Files/nodejs). Con ese, `ng` muere con
# "/usr/bin/env: 'node': No such file or directory", que no explica nada.
#
# Una terminal interactiva lo arregla sola, porque ~/.bashrc antepone el de
# Linux. Pero entonces `make dev` funciona o no segun como se haya abierto la
# terminal, y eso es una trampa y no una configuracion. Asi que se busca aqui:
# primero la instalacion local, y si no, el primer `node` del PATH que no venga
# de /mnt.
NODE_BIN := $(shell \
	for d in $(HOME)/.local/node/bin $(HOME)/.nvm/versions/node/*/bin \
		/usr/local/bin /usr/bin; do \
		if [ -x "$$d/node" ]; then echo "$$d"; break; fi; \
	done)

ifneq ($(NODE_BIN),)
export PATH := $(NODE_BIN):$(PATH)
endif

# Sin `~/.angular-config.json`, la primera orden `ng` de una maquina pregunta si
# quieres compartir estadisticas de uso, y esperando esa respuesta se queda
# colgada en cualquier terminal que no sea interactiva. La variable de entorno lo
# contesta de una vez para todos los objetivos; `ng serve --no-analytics` no vale,
# porque esa bandera no existe y la CLI muere con "Unknown argument: analytics".
export NG_CLI_ANALYTICS := false

.PHONY: help setup setup-backend setup-frontend dev dev-backend dev-frontend \
        test test-core test-api test-frontend build-frontend lint lint-backend \
        lint-frontend format contracts openapi marca modelo clean doctor

## help: lista los objetivos disponibles
help:
	@echo "Stamina.AI — objetivos disponibles:"
	@echo ""
	@grep -E '^## ' $(MAKEFILE_LIST) | sed 's/## /  /' | column -t -s ':'
	@echo ""

# --- Instalacion -------------------------------------------------------------

## setup: instala dependencias de backend y frontend
setup: setup-backend setup-frontend

## setup-backend: crea backend/.venv (en ext4) e instala dependencias
setup-backend:
	@mkdir -p $(CACHE)
	@test -d $(CACHE)/venv || python3.12 -m venv $(CACHE)/venv
	@ln -sfn $(CACHE)/venv $(BACKEND)/.venv
	$(PY) -m pip install --upgrade pip
	cd $(BACKEND) && $(PY) -m pip install -e ".[dev]"
	@echo "Listo. El venv real esta en $(CACHE)/venv"

## setup-frontend: instala dependencias npm (fase 3)
setup-frontend:
	@test -d $(FRONTEND) || { echo "Todavia no existe $(FRONTEND)/ (fase 3)"; exit 0; }
	@mkdir -p $(CACHE)/node_modules $(CACHE)/angular
	@ln -sfn $(CACHE)/node_modules $(FRONTEND)/node_modules
	@ln -sfn $(CACHE)/angular $(FRONTEND)/.angular
	cd $(FRONTEND) && npm install

## doctor: comprueba que el entorno de WSL esta como debe
doctor:
	@echo "python3.12: $$(command -v python3.12 || echo 'NO INSTALADO')"
	@echo "node:       $$(command -v node || echo 'NO INSTALADO')"
	@echo "npm:        $$(command -v npm || echo 'NO INSTALADO')"
	@if [ -n "$(NODE_BIN)" ]; then \
		echo "  Node de Linux en $(NODE_BIN), puesto por el Makefile."; \
		echo "  Por eso 'make dev' funciona igual en una terminal interactiva que"; \
		echo "  en 'wsl -e bash -lc ...' desde PowerShell."; \
	elif command -v node >/dev/null && [[ "$$(command -v node)" == /mnt/* ]]; then \
		echo "  AVISO: el unico node es el de Windows y no sirve para 'ng'"; \
		echo "         Instala Node en WSL con nvm."; \
	fi
	@be=$(BACKEND)/modelo/metadata.joblib; \
		if [ -f "$$be" ]; then \
			echo "artefacto:  $$be (el que validan los tests; la API lee reglas.json)"; \
		else \
			echo "artefacto:  NO ENCONTRADO en $$be"; \
		fi
	@test -x $(PY) && $(PY) -c "import pandas, sklearn; print('pandas', pandas.__version__, '· sklearn', sklearn.__version__)" \
		|| echo "backend/.venv no existe: corre 'make setup-backend'"

# --- Desarrollo --------------------------------------------------------------

## dev: arranca backend y frontend en paralelo
dev:
	@$(MAKE) -j2 dev-backend dev-frontend

## dev-backend: API en http://localhost:8000 (docs en /docs)
dev-backend:
	cd $(BACKEND) && $(PY) -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

## dev-frontend: UI en http://localhost:4200
# --poll no es opcional: el codigo vive en /mnt/c (9p) y el watcher de Angular
# no recibe eventos inotify de ahi, asi que sin esto no recompila nunca.
dev-frontend:
	cd $(FRONTEND) && node_modules/.bin/ng serve --poll 2000

# --- Contratos ---------------------------------------------------------------

## openapi: vuelca el esquema OpenAPI a frontend/openapi.json
openapi:
	cd $(BACKEND) && $(PY) scripts/dump_openapi.py ../$(FRONTEND)/openapi.json

## modelo: publica un artefacto nuevo (make modelo DESDE=ruta/metadata.joblib)
# backend/modelo/metadata.joblib es la copia canonica y va en el repositorio, asi
# que un clon limpio no necesita esto. Solo hace falta si se vuelve a ejecutar el
# notebook de investigacion, que vive fuera del repo y escribe su propia copia.
# Despues, 'make test' comprueba que el artefacto nuevo sigue dando los mismos
# ritmos.
modelo:
	@test -n "$(DESDE)" || { echo "Falta DESDE: make modelo DESDE=ruta/a/metadata.joblib"; exit 1; }
	@test -f "$(DESDE)" || { echo "No existe $(DESDE)"; exit 1; }
	@mkdir -p $(BACKEND)/modelo
	cp "$(DESDE)" $(BACKEND)/modelo/metadata.joblib
	cd $(BACKEND) && $(PY) scripts/extraer_reglas.py
	@echo "Publicado. La API lee modelo/reglas.json; los tests validan contra metadata.joblib."
	@md5sum "$(DESDE)" $(BACKEND)/modelo/metadata.joblib

## marca: regenera el logo y los favicon desde frontend/marca/logo-original.jpg
# Se corre a mano y sus salidas se versionan: el original pesa 2 MB y recortarlo
# en cada build no tendria sentido. Necesita pillow, que esta en el extra [dev].
marca:
	cd $(BACKEND) && $(PY) scripts/generar_marca.py

## contracts: openapi.json -> tipos TypeScript (openapi-typescript)
# Version fijada y via npx a proposito: openapi-typescript 7.13 declara
# `peer typescript@^5.x` y Angular 22 exige ~6.0, asi que instalarlo como
# dependencia obliga a --legacy-peer-deps. Es un generador de build; no necesita
# compartir el TypeScript del proyecto.
contracts: openapi
	cd $(FRONTEND) && npx --yes openapi-typescript@$(OPENAPI_TS) openapi.json -o src/app/core/api/schema.d.ts
	@echo "Contratos regenerados. Corre 'make lint-frontend' para ver si algo se desalineo."

# --- Calidad -----------------------------------------------------------------

## test: toda la bateria
test: test-core test-api test-frontend

## test-core: la prueba de persistencia contra lo que valido el notebook
test-core:
	cd $(BACKEND) && $(PY) -m pytest tests/test_persistencia.py tests/test_entrenamiento.py tests/test_lector_fit.py -v

## test-api: pruebas de humo de los endpoints (fase 2)
test-api:
	@test -f $(BACKEND)/tests/test_api.py \
		&& cd $(BACKEND) && $(PY) -m pytest tests/test_api.py -v \
		|| echo "Todavia no hay tests de API (fase 2)"

## test-frontend: vitest
test-frontend:
	cd $(FRONTEND) && node_modules/.bin/ng test --watch=false

## build-frontend: build de produccion
build-frontend:
	cd $(FRONTEND) && node_modules/.bin/ng build --configuration production

## lint: ruff en el backend, tsc en el frontend
lint: lint-backend lint-frontend

lint-backend:
	cd $(BACKEND) && $(PY) -m ruff check app stamina_core tests
	cd $(BACKEND) && $(PY) -m ruff format --check app stamina_core tests

lint-frontend:
	cd $(FRONTEND) && node_modules/.bin/tsc --noEmit -p tsconfig.app.json

## format: aplica formato automatico
format:
	cd $(BACKEND) && $(PY) -m ruff format app stamina_core tests
	cd $(BACKEND) && $(PY) -m ruff check --fix app stamina_core tests

# --- Limpieza ----------------------------------------------------------------

## clean: elimina artefactos de build y caches
clean:
	rm -rf $(FRONTEND)/dist
	find $(BACKEND) -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	find $(BACKEND) -type d -name .pytest_cache -prune -exec rm -rf {} + 2>/dev/null || true
	find $(BACKEND) -type d -name .ruff_cache -prune -exec rm -rf {} + 2>/dev/null || true
