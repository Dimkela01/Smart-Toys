# Bruno MVP

Mobile-first web app that behaves like an AI learning toy for children aged 3–10. A child
holds a paw button, speaks, and an animated character answers by voice; parents control
topics and limits and read summaries.

The specification in [`docs/`](docs/) is the source of truth — start with
[`docs/CLAUDE.md`](docs/CLAUDE.md) and [`docs/SPEC.md`](docs/SPEC.md). Work follows the
milestone order in [`docs/MILESTONES.md`](docs/MILESTONES.md).

**Status: M1 "Skeleton" nearly complete.** Parent accounts, the parent PIN, child profiles,
child mode and the admin sign-in work end to end, with the web app on top: landing,
registration and consent, email verification, PIN, dashboard, add-child wizard, the child
picture picker and a placeholder toy screen. There is no voice yet — that is M2.

## Requirements

- Docker Desktop (the stack runs in containers)
- [uv](https://docs.astral.sh/uv/) for the backend, [pnpm](https://pnpm.io/) for the web app
- No GPU and no model weights are needed for M1

## Setup

1. `cp .env.example .env` — or just run `make dev`, which creates it on first use.
2. **Check the ports in `.env`.** `POSTGRES_PORT`, `API_PORT`, `WEB_PORT`,
   `MAILPIT_UI_PORT` and `REDIS_PORT` are what gets published on your machine; change them
   if another project already uses those ports. Keep the port in `TEST_DATABASE_URL` equal
   to `POSTGRES_PORT`.
3. `make dev` — builds and starts the stack, then applies migrations. It prints the ports.
4. `make install` — installs the local (non-container) dev environment used by tests and linters.
5. `make test` — backend tests, plus the Playwright run-through once the web app exists.
6. `make lint` — ruff, mypy, and eslint/tsc once the web app exists.
7. `make down` — stop everything. `make clean` also deletes the database volume.

Set a real `JWT_SECRET` in `.env` before anything leaves your machine
(`python3 -c "import secrets; print(secrets.token_urlsafe(48))"`).

## What runs where

| Service | Purpose | Published as |
|---|---|---|
| `api` | FastAPI backend | `API_PORT`, `/docs` for the OpenAPI UI |
| `postgres` | Postgres 16 | `POSTGRES_PORT` |
| `redis` | login/PIN lockout counters, rate limits | `REDIS_PORT` |
| `mailpit` | catches verification, reset and alert email in development | `MAILPIT_UI_PORT` |
| `web` | Next.js app (parent, child, admin) — arrives in a later M1 step | `WEB_PORT` |

The LLM, speech-to-text and text-to-speech services join the stack in M2; they run locally
via llama.cpp, faster-whisper, Kokoro and Piper. **No external AI API is ever called**
(`docs/CLAUDE.md` §2).

## Checks that matter

- `make test-api` recreates the test database from scratch, so it also proves migrations
  apply to an empty database.
- `tests/test_schema.py` fails if `app/models/` and `app/migrations/` drift apart.
- Model weights, `.env` and audio are never committed. Audio is never stored at all.

## Repository layout

```
apps/web/        Next.js app (parent, child, admin UI)
services/api/    FastAPI backend: auth, REST, child mode, admin; Alembic migrations
content/         lessons, stories, word lists, characters (drafts until reviewed)
models/          model registry (registry.yaml); weights are never committed
prompts/         system prompts, router lists, fixed responses (from M3)
infra/           docker-compose and deployment configuration
scripts/         model download and maintenance scripts
docs/            the specification; docs/reports/ holds milestone reports
```
