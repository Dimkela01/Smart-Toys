# Instructions for the coding agent

You are implementing the Bruno MVP described in `docs/`. Read this file first, then
`docs/README.md`, `docs/SPEC.md` and `docs/MILESTONES.md`. Read other docs when the task needs them.

## 1. How to work

1. **Work one milestone at a time**, in the order of `docs/MILESTONES.md` (M1 → M7).
2. At the start of a milestone, write a short plan (files to create, open questions) and wait for approval.
3. At the end of a milestone, go through its checklist in `docs/MILESTONES.md`, report each item as done / not done, list anything you had to assume, and **stop**. Do not start the next milestone without explicit approval.
4. **Never modify existing code or documentation outside the current milestone without asking.** Never edit files in `docs/` unless asked; if the docs are wrong or contradictory, stop and ask.
5. **Do not add features that are not in the docs.** If something is unspecified, choose the simplest option that matches the docs and list it under "Assumptions" in your milestone report.
6. Reference requirement IDs (`F-…`, `NFR-…`, `UC-…`) in commit messages.
7. Small commits; each commit builds and passes tests.

## 2. Hard rules

- **No external AI APIs** (OpenAI, Anthropic, Google, etc.). All models run locally via llama.cpp, faster-whisper / whisper.cpp, Kokoro, Piper.
- **No analytics, ads or third-party tracking SDKs.** No third-party scripts in the frontend.
- **Never store audio.** Audio stays in memory only.
- **Never log transcript text** in application logs (IDs only).
- **Protected categories** in `docs/SAFETY.md` are always answered with fixed responses, never by the LLM.
- **Metrics, model names and latencies are admin-only.** Never show them in parent or child UI.
- **Secrets only in environment variables.** Commit `.env.example`, never `.env`.
- **Child UI must not show model text** (voice only).

## 3. Decisions for things the docs leave open

| Topic | Decision for now |
|---|---|
| Default LLM | `qwen3-1.7b` Q4_K_M GGUF, thinking disabled. Registry must also list `gemma3-1b` and `qwen3-0.6b`. Final choice comes from the benchmark; do not hard-code a model anywhere except the registry. |
| Speech-to-text | faster-whisper `base`, int8, CPU. |
| English voice | Kokoro-82M. |
| Serbian voice | Implement the TTS interface with a Piper voice as a **placeholder marked `internal_only: true`** in the character config. The UI shows nothing about it. Do not ship it to a public demo URL until the license is confirmed. |
| Characters, avatars, animations | Not available yet. Use simple placeholder assets: an SVG/CSS character with the 7 states from `docs/UI.md`, 12 placeholder avatar images (simple colored animals or shapes), and generated fallback audio via the TTS at build time. Keep all assets under `apps/web/public/characters/` and `apps/web/public/avatars/` with the final file names, so they can be swapped later. Rive integration is M7. |
| Email | SMTP via environment variables. In development, use a local mail catcher (Mailpit) in docker-compose and print links to the console. |
| Hosting | Develop and test with docker-compose on a laptop (amd64 and arm64). No cloud-specific services. |
| Database | Postgres in docker-compose; Alembic migrations from the first commit. |
| Package managers | Frontend: pnpm. Backend: uv (or pip with `requirements.txt` + lock). |
| Model weights | Downloaded by `scripts/download_models.py` into a volume, with SHA256 checks; never committed. |
| Languages | UI strings in i18n files (`sr`, `en`), Serbian Latin script. No hard-coded user-facing text in components. |

## 4. Content you must draft (and mark as draft)

These do not exist yet. Create them as **drafts** with `"status": "draft"` (JSON/YAML) or a
`DRAFT` header (text), and list them in every milestone report until a human marks them reviewed:

- Router keyword and phrase lists, `prompts/router/{sr,en}.yaml` (all categories P1–P14 in `docs/SAFETY.md`).
- Fixed responses, `prompts/fixed_responses/{sr,en}.yaml`: copy the texts from `docs/SAFETY.md` exactly; do not rewrite them.
- System prompts, `prompts/system_v1_{sr,en}.txt`: copy from `docs/SAFETY.md` exactly.
- Test sets in `services/eval/sets/`: start with at least 30 items per set and language, following the format in `docs/EVALUATION.md`; red-team items must cover every category.
- Lessons, word lists, story seeds, characters in `content/`: the examples from `docs/CONTENT.md`, plus 2 lessons per activity, 3 story seeds, 3 characters.

Safety content must never be "improved" silently: changes to router lists, fixed responses or
system prompts require a note in the milestone report.

## 5. Quality bar

- Backend: type hints, `ruff` + `mypy`, `pytest`; unit tests for router, output filter, lesson engine, prompt builder, number parsing, limits.
- Frontend: TypeScript strict, ESLint, Playwright test for: register → add child → child mode → hold paw (mocked audio) → hear answer → exit with PIN.
- Turn pipeline has an integration test with mocked STT/LLM/TTS (deterministic) and an optional test with real models (`pytest -m models`).
- `make dev`, `make test`, `make lint`, `make models` work from a clean checkout. README in the repo root explains setup in under 10 steps.
- Mobile check: every child and parent screen works at 360×740 in Chrome DevTools and iOS Safari.

## 6. When unsure

Stop and ask. A short question is always better than a guess that changes safety, privacy or scope.
