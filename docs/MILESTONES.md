# Milestones and definition of done

Each milestone ends with a report: checklist status, assumptions made, drafts created, known issues.
The next milestone starts only after approval (see `CLAUDE.md`).

General done criteria for every milestone:
- [ ] `make dev`, `make test`, `make lint` pass from a clean checkout
- [ ] New migrations apply on an empty database
- [ ] No secrets, audio files or model weights committed
- [ ] Screens of this milestone work at 360×740 (Chrome) and on iOS Safari
- [ ] Milestone report written in `docs/reports/M<n>.md`

---

## M1 Skeleton

Scope: F-01, F-02, F-03, F-04, F-20 (registry file only); UC-01, UC-02, UC-03, UC-05, UC-21.

- [ ] Monorepo structure as in `ARCHITECTURE.md` §3; docker-compose with web, api, postgres, redis, mailpit
- [ ] Parent registration with 18+ and consent checkboxes; consent version stored
- [ ] Email verification and password reset via Mailpit; links expire (24 h / 1 h)
- [ ] Login lockout after 5 failed attempts; Argon2id hashing; access + refresh tokens
- [ ] Parent PIN set and verified; 5 wrong PINs → 5-minute lock
- [ ] Child profiles CRUD (max 5, nickname 1–20 chars, age 3–10, language, interests, avatar, character)
- [ ] Child mode: picture picker, placeholder toy screen, blocked back navigation and parent routes, 3-second corner press + PIN to exit
- [ ] Admin login with TOTP; empty `/admin` layout
- [ ] `models/registry.yaml` with the three models from `CLAUDE.md`
- [ ] i18n set up for `sr` and `en`
- [ ] Tests: auth flows, PIN lockout, child-mode token scope

## M2 Voice loop

Scope: F-05, F-06, F-07, F-21 (capture only), F-18 (LLM/STT/TTS languages); UC-11, UC-19, UC-22.

- [ ] Hold-to-talk paw (touch and space bar), AudioContext resumed on press (iOS)
- [ ] AudioWorklet capture → 16 kHz PCM16 → WebSocket frames; 15 s cap; < 0.4 s press handled
- [ ] STT service (faster-whisper base int8), language forced per child
- [ ] llama-server with the default model on CPU; streaming; Qwen thinking disabled; `<think>` stripped
- [ ] Sentence splitter; TTS per sentence (Kokoro EN, placeholder Piper SR); ordered playback
- [ ] Character states listening / thinking / speaking; mouth driven by output RMS; instant "hmm" on release
- [ ] Barge-in stops audio within 150 ms and cancels generation and TTS
- [ ] Fallback lines (not heard, error, timeout 8 s) played from local files; no technical text on the child screen
- [ ] Prompt builder with blocks 1–3 and 7–8 from `DATA_MODEL.md` §5 (others empty for now)
- [ ] `turn_metrics` filled for every turn (all fields in `EVALUATION.md` §4.1 that apply)
- [ ] Queue when both LLM slots are busy (max wait 10 s)
- [ ] Measured and reported: p50 / p95 first audio on the dev laptop for 20 test turns per language

## M3 Safety

Scope: F-09; UC-16, UC-17, UC-18; `SAFETY.md` §2–§9.

- [ ] Router pipeline in the order of `SAFETY.md` §4, Cyrillic transliteration, diacritics normalization
- [ ] Draft router lists for P1–P14 (both languages), marked draft
- [ ] Fixed responses copied exactly; audio pre-generated and cached per character and language
- [ ] Classifier step with constrained JSON output, used only on weak/ambiguous hits or long inputs
- [ ] System prompts v1 (sr, en) copied exactly; version + hash stored with each turn
- [ ] Output filter per `SAFETY.md` §6; `fallback_safe` on failure; event `output_filtered` logged
- [ ] Events stored for every router decision other than `allow`
- [ ] First-session `parents_can_see` line
- [ ] Draft test sets: redteam, benign_tricky, normal (≥ 30 items per set and language)
- [ ] CI job runs the safety sets against the default model; gate: 0 harmful (automatic checks), 100% urgent recall, ≤ 2% refusals on benign; report includes items needing human review

## M4 Activities

Scope: F-08, F-19 (config only); UC-12, UC-13, UC-14, UC-15; `CONTENT.md`.

- [ ] Activity cards and voice intents; disabled activities hidden and declined
- [ ] Lesson engine: generators (count, add, subtract), number parsing SR/EN (unit-tested with ≥ 60 cases), hints, rounds, level-up
- [ ] English words: themes, fuzzy matching, picture cards, max 5 new words
- [ ] Story engine: seeds, state, two choices with pictures, facts update via constrained JSON, 4–6 parts, calm endings late in the day
- [ ] `ACTIVITY` prompt block; answer never revealed when the engine says so (filter check)
- [ ] `visual` WebSocket events rendered on the toy screen
- [ ] Activity state saved per child; switching activities keeps the session
- [ ] Draft content: 2 lessons per activity, 3 story seeds, 3 characters
- [ ] Scripted multi-turn tests for each activity pass

## M5 Parent

Scope: F-10–F-17; UC-04, UC-06–UC-10, UC-20; `DATA_MODEL.md` §3, §4, §6.

- [ ] Child settings screen: activity toggles, blocked topics (into router and prompt block 4), limit, hours, memory, transcripts, alerts
- [ ] Sessions: start/end rules; daily usage; 2-minute warning; goodbye and lock; PIN override
- [ ] Session-end job: summary + topic tags (protected turns excluded), bookmarks from activity states
- [ ] Memory block in prompts (profile, bookmarks, last summary ≤ 100 tokens) only when memory is on
- [ ] Dashboard: usage ring, last summary, topic tags, alert badge, "Give to child"
- [ ] Sessions list with summaries; transcripts only when enabled (403 otherwise, except urgent turns)
- [ ] "What Bruno remembers": edit, delete, forget everything
- [ ] Alerts: levels per `SAFETY.md` §7; urgent email within 1 minute (Mailpit in dev)
- [ ] Export JSON; delete child; delete account (password confirmation)
- [ ] Retention job: transcripts after 30 days, other values per `DATA_MODEL.md` §6 (configurable); tested with a fake clock

## M6 Evaluation

Scope: F-20–F-24; UC-23–UC-27; `EVALUATION.md`.

- [ ] Admin: models and prompt versions; active pair per environment, no redeploy needed
- [ ] Evaluation runner (CLI + admin page): models × prompt × sets × profile; stores env info and hashes; CSV export
- [ ] Automatic checks: sentence count, language, ends with question, length, refusals detection
- [ ] Blind rating queue with keyboard shortcuts; agreement stats when 2 raters exist
- [ ] Metrics dashboard: p50/p95 latency, tokens/s, memory peaks, error rates, router mix, per model and profile
- [ ] `device` profile: compose file for arm64, Cloudflare Tunnel config, profile switch per account, 3 s fallback to server
- [ ] `device/bench.sh` implementing `EVALUATION.md` §5, including the 20-minute thermal run
- [ ] Release-gate check command that prints pass/fail for every gate in `EVALUATION.md` §6

## M7 Demo polish

Scope: F-19, F-25, F-26, F-27.

- [ ] Character switch (3 characters) from config; voice and name per character
- [ ] Rive (or Lottie) integration replacing the placeholder character, with the same state names
- [ ] Demo mode: seeded parent, 3 child profiles, "Try to trick Bruno" card list (admin-enabled)
- [ ] Toy-speed simulation (cap tokens/s to the last device benchmark)
- [ ] PWA manifest, icons, full-screen install on Android and iOS
- [ ] Deployment guide for one always-on ARM host (Oracle Always Free or Hetzner ARM) with Caddy TLS
- [ ] End-to-end demo script (5 minutes) runs without errors on a phone over the public link
