# Bruno MVP: documentation

Specification for the first, mobile-first web version of an AI learning toy for children aged 3–10.
The web app simulates the toy: a child holds a "paw" button, speaks, and an animated character
answers by voice. Parents control topics and limits and see summaries of conversations.

These documents are the source of truth for implementation. When code and docs disagree, fix one
of them in the same change.

## Files

| File | What it covers |
|---|---|
| [SPEC.md](SPEC.md) | Goals, scope, roles, feature list with priorities, non-functional requirements, decisions |
| [USE_CASES.md](USE_CASES.md) | All use cases with flows and acceptance criteria |
| [UI.md](UI.md) | Screens, navigation, child and parent design rules, copy |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Components, where everything runs, turn pipeline, APIs, WebSocket protocol, deployment |
| [DATA_MODEL.md](DATA_MODEL.md) | Database tables, memory design, prompt assembly, retention |
| [SAFETY.md](SAFETY.md) | Layered safety, protected categories, fixed responses, system prompt v1, parent controls, alerts, pre-pilot checklist |
| [CONTENT.md](CONTENT.md) | Activities, lesson and story formats, characters, intent detection |
| [EVALUATION.md](EVALUATION.md) | Model evaluation, metrics, device benchmarks, release gates (admin only, never shown to users) |

## How to use with Cursor

1. Copy the `docs/` folder into the repository root.
2. Ask Cursor to read `docs/README.md` and `docs/SPEC.md` first, then the file relevant to the task.
3. Build in the milestone order in [SPEC.md](SPEC.md#9-milestones).
4. Every requirement has an ID (`F-…`, `NFR-…`, `UC-…`, `S-…`, `E-…`). Reference IDs in commits and pull requests.

## Decision log

| # | Date | Decision |
|---|---|---|
| D1 | 2026-11-09 | Phase 1 is a hosted web app (PWA). The LLM, speech-to-text and text-to-speech run on our server, not on the user's device. Hardware comes after pricing and demand are confirmed. |
| D2 | 2026-11-09 | Build nearly all features now. Until consent forms and a light CRIA are done, the app is a **demo**: no real children's data, test profiles only. |
| D3 | 2026-11-09 | Parents see **summaries and topics by default**. Full transcripts only if the parent turns them on. |
| D4 | 2026-11-09 | Children sign in by **choosing their picture**. No passwords for children. |
| D5 | 2026-11-09 | Two inference profiles: `server` (low-cost EU CPU machine or a developer laptop, serves the app) and `device` (reference toy-class board and a mid-range phone, used for realistic metrics and live demos). Model and hardware decisions use `device` numbers only. |
| D6 | 2026-11-09 | Only small models that can fit the target hardware are used (4-bit, ~2 GB budget, 2,048-token context). No external AI APIs. |
| D7 | 2026-11-09 | **No GPU in the MVP.** Small 4-bit models run on CPU. Hosting target: €0–30 per month (laptop + tunnel, Oracle Always Free ARM, or Hetzner ARM). A GPU is added only if the pilot needs more concurrent children. |

## Glossary

| Term | Meaning |
|---|---|
| Bruno | Default character name. Characters are configurable. |
| Child mode | Locked state of the app where only the toy screen is reachable. Exit requires the parent PIN. |
| Turn | One child utterance and Bruno's spoken answer. |
| Session | Continuous use by one child; ends after 3 minutes of inactivity, exit, or the daily limit. |
| Router | Code (not the LLM) that classifies the child's input before it reaches the model. |
| Fixed response | Pre-written, reviewed answer used for protected categories. The LLM never writes these. |
| Bookmark | A whitelisted fact Bruno may remember across sessions (unfinished story, level, learned words). |
| Profile `server` / `device` | Where inference runs; see [ARCHITECTURE.md](ARCHITECTURE.md#4-inference-profiles). |
| CRIA | Child Rights Impact Assessment (UNICEF D-CRIA toolbox). Required before any pilot with real children. |
