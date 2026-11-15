#
# Bruno MVP — developer entry points (docs/CLAUDE.md §5)
#
#
SHELL := /bin/bash
COMPOSE := docker compose -f infra/docker-compose.yml --project-directory .
API := $(COMPOSE) exec -T api
API_RUN := $(COMPOSE) run --rm -T api

.PHONY: help install dev up down logs ps migrate revision seed test test-api test-e2e lint fmt models clean

help: ## show this help
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

.env: ## create .env from the example on first run
	@test -f .env || (cp .env.example .env && echo "created .env from .env.example — review it")

install: .env ## install local (non-docker) dev dependencies
	cd services/api && uv sync --all-extras
	cd apps/web && pnpm install

dev: .env ## start the full stack (web, api, postgres, redis, mailpit)
	$(COMPOSE) up --build -d
	@echo
	@echo "  web      http://localhost:3000"
	@echo "  api      http://localhost:8000/docs"
	@echo "  mailpit  http://localhost:8025"
	@echo
	$(MAKE) migrate

up: dev ## alias for dev

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
	$(COMPOSE) up -d postgres redis
	cd services/api && uv run pytest -q

test-e2e: ## Playwright end-to-end test (needs the stack running: make dev)
	cd apps/web && pnpm exec playwright test

lint: ## ruff + mypy + eslint + tsc
	cd services/api && uv run ruff check . && uv run ruff format --check . && uv run mypy .
	cd apps/web && pnpm run lint && pnpm exec tsc --noEmit

fmt: ## format backend and frontend
	cd services/api && uv run ruff format . && uv run ruff check --fix .
	cd apps/web && pnpm exec prettier --write .

models: .env ## download model weights listed in models/registry.yaml (not needed for M1)
	cd services/api && uv run python ../../scripts/download_models.py \
		--registry ../../models/registry.yaml --dest ../../models/weights
