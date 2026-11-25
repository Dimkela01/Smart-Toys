# Bruno MVP

Mobile-first web app that behaves like an AI learning toy for children aged 3–10. A child
holds a paw button, speaks, and an animated character answers by voice; parents control
topics and limits and read summaries.

The specification in [`docs/`](docs/) is the source of truth — start with
[`docs/CLAUDE.md`](docs/CLAUDE.md) and [`docs/SPEC.md`](docs/SPEC.md). Work follows the
milestone order in [`docs/MILESTONES.md`](docs/MILESTONES.md).

**Status: M1 "Skeleton" done, M2 "Voice loop" in progress.** Parent accounts, the parent
PIN, child profiles, child mode and the admin sign-in work end to end, with the web app on
top: landing, registration and consent, email verification, PIN, dashboard, add-child
wizard, the child picture picker and a placeholder toy screen. M2 adds the voice: the model
weights, an https front door so a phone may use its microphone, and the three local
inference services. See [`docs/reports/`](docs/reports/) for the milestone reports.

## Requirements

- Docker Desktop (the stack runs in containers)
- [uv](https://docs.astral.sh/uv/) for the backend, [pnpm](https://pnpm.io/) for the web app
- About 2 GB of disk for the model weights (`make models`), and no GPU: every model runs
  on the CPU. `make dev-lite` skips the inference services if you are only working on the
  parent or admin side.

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

### Testing on a real phone

- `make phone` — finds this machine's address and prints a plain-http URL for a phone on
  the same Wi-Fi.
- `make https` — the same, over https, through a Caddy front door with its own local
  certificate authority. **A microphone only works in a secure context**, so from M2
  onwards the paw cannot record over plain http. The target prints the one-time steps for
  trusting the certificate on the phone, and uses this machine's `.local` name, so it
  survives a change of IP address. `make https-stop` closes that door again.
- `make models` — downloads the model weights named in `models/registry.yaml` and checks
  each one against a recorded sha256. Weights are never committed. Gemma is gated by
  Google: accept the terms on its model page and `export HF_TOKEN` before running.

Set a real `JWT_SECRET` in `.env` before anything leaves your machine
(`python3 -c "import secrets; print(secrets.token_urlsafe(48))"`).

## What runs where

| Service | Purpose | Published as |
|---|---|---|
| `api` | FastAPI backend | `API_PORT`, `/docs` for the OpenAPI UI |
| `postgres` | Postgres 16 | `POSTGRES_PORT` |
| `redis` | login/PIN lockout counters, rate limits | `REDIS_PORT` |
| `mailpit` | catches verification, reset and alert email in development | `MAILPIT_UI_PORT` |
| `web` | Next.js app (parent, child, admin) | `WEB_PORT` |
| `llm` | llama.cpp serving the model the registry marks active | `LLM_PORT` |
| `stt` | faster-whisper, int8 on CPU | `STT_PORT` |
| `tts` | Kokoro (English) and a placeholder Piper voice (Serbian) | `TTS_PORT` |

The three inference services run locally via llama.cpp, faster-whisper, Kokoro and Piper.
**No external AI API is ever called** (`docs/CLAUDE.md` §2), and the images run with
`HF_HUB_OFFLINE=1` so a missing weight fails loudly instead of being fetched at runtime.
None of them has a model name in its Dockerfile or compose command: each resolves its own
weights through `models/registry.yaml`, so changing model is a registry edit and a restart.

The published `LLM_PORT`/`STT_PORT`/`TTS_PORT` are for smoke tests from the host only —
the app reaches these services inside the compose network.

**Serbian has no voice we can ship.** The only Serbian Piper voice is non-commercial and
mispronounces the language, so the registry marks it `internal_only` and `tts` refuses to
load it unless `TTS_ALLOW_INTERNAL_ONLY` is set. Speech *recognition* in Serbian is
unaffected. See `docs/reports/M2.md`.

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
