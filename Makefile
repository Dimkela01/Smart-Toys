#
# Bruno MVP — developer entry points (docs/CLAUDE.md §5)
#
#
SHELL := /bin/bash
COMPOSE := docker compose -f infra/docker-compose.yml --project-directory .
# the end-to-end suite needs room inside the auth rate limit; see infra/docker-compose.test.yml
COMPOSE_TEST := docker compose -f infra/docker-compose.yml -f infra/docker-compose.test.yml --project-directory .
API := $(COMPOSE) exec -T api
API_RUN := $(COMPOSE) run --rm -T api

.PHONY: help install dev up down logs ps migrate revision seed test test-api test-e2e lint fmt models clean

help: ## show this help
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

.env: ## create .env from the example on first run
	@test -f .env || (cp .env.example .env && echo "created .env from .env.example — review it")

install: .env ## install local (non-docker) dev dependencies
	cd services/api && uv sync
	@if [ -f apps/web/package.json ]; then cd apps/web && pnpm install; else echo "skip: apps/web not set up yet"; fi

dev: .env ## start the stack (web, api, postgres, redis, mailpit) and apply migrations
	@if [ -f apps/web/Dockerfile ]; then $(COMPOSE) up --build -d --wait; else echo "note: apps/web does not exist yet (M1 step 3); starting backend services only"; $(COMPOSE) up --build -d --wait postgres redis mailpit api; fi
	$(MAKE) migrate
	@echo
	@echo "  ports are set in .env (API_PORT, WEB_PORT, MAILPIT_UI_PORT):"
	@grep -E '^(API_PORT|WEB_PORT|MAILPIT_UI_PORT|POSTGRES_PORT)=' .env | sed 's/^/    /'
	@echo

up: dev ## alias for dev

phone: .env ## open the app on a phone on the same network (detects this machine's address)
	@ip=$$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || hostname -I 2>/dev/null | awk '{print $$1}'); \
	if [ -z "$$ip" ]; then echo "could not find a LAN address; are you on Wi-Fi?"; exit 1; fi; \
	web=$$(grep '^WEB_PORT=' .env | cut -d= -f2); mail=$$(grep '^MAILPIT_UI_PORT=' .env | cut -d= -f2); \
	tmp=$$(mktemp); \
	sed -e "s|^PUBLIC_WEB_URL=.*|PUBLIC_WEB_URL=http://$$ip:$$web|" \
	    -e "s|^DEV_ALLOWED_ORIGINS=.*|DEV_ALLOWED_ORIGINS=$$ip|" .env > $$tmp && mv $$tmp .env; \
	grep -q '^DEV_ALLOWED_ORIGINS=' .env || echo "DEV_ALLOWED_ORIGINS=$$ip" >> .env; \
	$(COMPOSE) up -d --force-recreate --wait api web >/dev/null; \
	echo; \
	echo "  On the phone (same Wi-Fi), open:   http://$$ip:$$web"; \
	echo "  Verification emails land here:     http://$$ip:$$mail"; \
	echo; \
	echo "  Run this again whenever the machine changes network."

down: ## stop the stack
	$(COMPOSE) down

clean: ## stop the stack and delete volumes (destroys the dev database)
	$(COMPOSE) down -v

logs: ## follow logs
	$(COMPOSE) logs -f --tail=100

ps: ## show container status
	$(COMPOSE) ps

migrate: ## apply database migrations
	$(API) alembic upgrade head

revision: ## create a new migration: make revision m="message"
	$(API) alembic revision --autogenerate -m "$(m)"

seed: ## create the first admin account and print its TOTP provisioning URI
	$(API) python -m app.cli seed-admin

test: test-api test-e2e ## run all tests

test-api: ## backend tests (pytest); applies migrations to an empty test database
	$(COMPOSE) up -d --wait postgres redis
	cd services/api && uv run pytest

test-e2e: .env ## Playwright end-to-end run-through (starts the stack with test limits)
	@if [ ! -f apps/web/package.json ]; then echo "skip: apps/web not set up yet"; exit 0; fi; \
	cd apps/web && pnpm install --prefer-offline --silent && pnpm exec playwright install chromium
	$(COMPOSE_TEST) up -d --wait postgres redis mailpit api web
	$(COMPOSE_TEST) exec -T api alembic upgrade head
	@set -a; . ./.env; set +a; cd apps/web && pnpm exec playwright test

lint: ## ruff + mypy + eslint + tsc
	cd services/api && uv run ruff check . && uv run ruff format --check . && uv run mypy .
	@if [ -f apps/web/package.json ]; then cd apps/web && pnpm install --prefer-offline --silent && pnpm run lint && pnpm exec tsc --noEmit; else echo "skip: apps/web not set up yet"; fi

fmt: ## format backend and frontend
	cd services/api && uv run ruff format . && uv run ruff check --fix .
	@if [ -f apps/web/package.json ]; then cd apps/web && pnpm exec prettier --write .; else echo "skip: apps/web not set up yet"; fi

models: .env ## download model weights listed in models/registry.yaml (not needed for M1)
	cd services/api && uv run python ../../scripts/download_models.py \
		--registry ../../models/registry.yaml --dest ../../models/weights
