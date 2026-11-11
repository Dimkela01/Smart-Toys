# Product specification: Bruno MVP (web)

## 1. Purpose

Build a mobile-first web app that behaves like the future toy, in order to:

1. **Demo** the concept to toy companies, mentors and investors.
2. **Pilot** with 10–20 families (only after the pre-pilot checklist in [SAFETY.md](SAFETY.md#10-pre-pilot-checklist) is complete).
3. **Choose the model** and pipeline that will later run on toy-class hardware, using realistic measurements.

## 2. Product in one paragraph

A child opens the app on a parent's phone, picks their picture and sees an animated plush character.
They hold a big paw button, ask a question or pick an activity (questions, stories, numbers, English
words), release the paw, and the character answers by voice in 1–3 short sentences. The character is
warm, honest that it is a toy, never gives advice on risky topics, and sends the child back to
parents and friends. Parents set what the toy may talk about and for how long, see daily summaries,
and get alerts when something sensitive comes up.

## 3. Roles

| Role | Sign-in | Can |
|---|---|---|
| Parent | email + password, email verification; 4-digit PIN for child-mode exit | manage child profiles, topics, limits, memory; read summaries and (optionally) transcripts; export or delete data |
| Child | picks own picture inside a parent account; no credentials | talk to the toy, choose activities |
| Admin (team) | email + password + TOTP 2FA | model and prompt registry, evaluation runs, metrics, review of flagged turns (only where the parent consented) |

## 4. Scope

### 4.1 In scope (MVP)

Priorities: **P0** must exist for the first demo, **P1** needed before the pilot, **P2** nice to have.

| ID | Feature | Priority |
|---|---|---|
| F-01 | Parent registration, email verification, login, password reset | P0 |
| F-02 | Consent and privacy screen at registration (what is stored, for how long, who sees it) | P0 |
| F-03 | Child profiles (nickname, age, language, interests, avatar, character) | P0 |
| F-04 | Child mode with picture selection; exit only with parent PIN | P0 |
| F-05 | Toy screen: animated character, hold-to-talk paw, activity cards, states (sleeping, listening, thinking, speaking) | P0 |
| F-06 | Voice turn pipeline: speech-to-text → router → LLM → output filter → text-to-speech, streamed by sentence | P0 |
| F-07 | Barge-in: pressing the paw while Bruno speaks stops audio and cancels generation | P0 |
| F-08 | Activities: "Why?" questions, choose-your-story, numbers game, English words | P0 |
| F-09 | Layered safety: router, system prompt, output filter, fixed responses | P0 |
| F-10 | Parent topic controls: activity toggles and custom blocked topics | P0 |
| F-11 | Daily time limit and allowed hours; goodbye and lock | P0 |
| F-12 | Session summaries and bookmarks (memory across sessions) | P0 |
| F-13 | Parent dashboard: today's usage, topics, alerts, session list with summaries | P0 |
| F-14 | Full transcripts view (off by default, parent opt-in) | P1 |
| F-15 | "What Bruno remembers" screen with edit and delete | P1 |
| F-16 | Alerts: sensitive-topic events and urgent safeguarding events | P1 |
| F-17 | Data export and account deletion | P1 |
| F-18 | Languages: Serbian (Latin script) and English, chosen per child | P0 for UI and LLM; TTS per [ARCHITECTURE.md](ARCHITECTURE.md#64-text-to-speech) |
| F-19 | 2–3 characters (bear, bunny, robot) with name, personality and voice from a config file | P1 |
| F-20 | Admin: model and prompt registry, switch active model per environment | P0 |
| F-21 | Admin: per-turn metrics capture and metrics dashboard | P0 |
| F-22 | Admin: evaluation runner on fixed test sets, report export | P0 |
| F-23 | Admin: human rating screen for sampled turns | P1 |
| F-24 | Inference profile switch `server` / `device` (live demo on reference board) | P1 |
| F-25 | Demo mode: seeded parent account and child profiles, "Try to trick Bruno" card list for presentations | P1 |
| F-26 | Toy-speed simulation for demos (cap tokens/s to device numbers) | P2 |
| F-27 | PWA install (home-screen icon, full-screen) | P1 |

### 4.2 Out of scope (MVP)

Physical toy, Bluetooth, on-device inference in the browser, payments and subscriptions, app-store
apps, more than two languages, fine-tuned or custom-trained models, social features, any external
AI API (OpenAI, Anthropic, Google cloud AI), advertising or analytics SDKs.

## 5. Key decisions

See [README.md](README.md#decision-log). The ones that shape the code most:

- Inference is server-side in phase 1 (D1), but only with small 4-bit models and toy limits (D6).
- Children have no credentials (D4). Child mode is a lock on a parent's session.
- Transcripts are hidden by default (D3); summaries are the parent's main view.
- Safety does not rely on the system prompt alone ([SAFETY.md](SAFETY.md)).
- All metrics are admin-only (F-21). No metric, model name or latency is shown to parents or children.

## 6. Non-functional requirements

| ID | Requirement |
|---|---|
| NFR-01 | **Mobile first.** Primary targets: Android Chrome and iOS Safari on phones from the last 4 years. Layouts from 360 px width. Desktop works but is secondary. |
| NFR-02 | **Latency** (server profile on CPU, p50): end of speech → first audio ≤ 4 s; p95 ≤ 6 s. Targets are revised after the first CPU measurements. Play an instant "thinking" sound at release. |
| NFR-03 | **Answer length:** 1–3 sentences, max 150 generated tokens. |
| NFR-04 | **Context limit:** 2,048 tokens total prompt + answer, to match toy hardware. |
| NFR-05 | **Privacy:** all servers and databases in the EU. No audio stored. Transcripts deleted after 30 days. No third-party trackers. TLS everywhere. |
| NFR-06 | **Security:** passwords hashed with Argon2id; short-lived access tokens; rate limits on auth and turn endpoints; admin 2FA; secrets only in environment variables. |
| NFR-07 | **Child UI:** no reading required to use the toy screen; touch targets ≥ 64 px; no scrolling, links, ads or external navigation. |
| NFR-08 | **Accessibility (parent UI):** WCAG 2.1 AA contrast, screen-reader labels, works at 200% text size. |
| NFR-09 | **Reliability:** any failure in the turn pipeline ends in a spoken fallback line from Bruno, never a technical error on the child screen. |
| NFR-10 | **Observability:** every turn records model ID, prompt version, router decision and metrics ([EVALUATION.md](EVALUATION.md)). |
| NFR-11 | **Reproducibility:** prompts, fixed responses, lessons and character configs are versioned files in the repo. |
| NFR-12 | **Cost:** hosting €0–30 per month, no GPU (D7). Must serve 1–2 concurrent children with NFR-02 met; further requests wait in a queue and Bruno plays a short "thinking" line. |

## 7. Success criteria for the MVP

- Demo: a stranger can complete a 5-minute session (question, story, numbers) without help.
- Safety: 0 harmful answers on the red-team set; ≤ 2 unnecessary refusals per 100 benign questions.
- Latency: NFR-02 met on the server profile; device-profile numbers recorded for the chosen model.
- Pilot (later): ≥ 50% of children use it again on day 7; children speak more words than Bruno (hypotheses H13, H14).

## 8. Assumptions and risks

| Risk | Mitigation |
|---|---|
| Small models answer poorly or unsafely in Serbian | Evaluation gate before model choice ([EVALUATION.md](EVALUATION.md)); router and fixed responses for protected topics |
| Whisper misrecognizes children's Serbian speech | Measure on child recordings early; force language per child; ask to repeat when confidence is low |
| No commercially licensed Serbian TTS voice | Use the best available voice for internal demos only; plan to record and train our own voice |
| iOS Safari audio restrictions (autoplay, background) | Start audio only after a user gesture (the paw press); keep the app in the foreground |
| Server latency not representative of the toy | Device profile and device benchmarks (D5) |
| CPU hosting too slow or too few concurrent users | Smaller model, prompt caching, queue; move to pay-per-use GPU (Modal) or a GPU server only when needed |
| Child data legal risk | Demo-only until the pre-pilot checklist is done |

## 9. Milestones

| # | Milestone | Contents |
|---|---|---|
| M1 | Skeleton | Repo, auth, parent and child profiles, child mode with PIN, database, admin login |
| M2 | Voice loop | Hold-to-talk, WebSocket, STT, LLM, TTS, streaming by sentence, barge-in, metrics capture |
| M3 | Safety | Router, protected categories, fixed responses, system prompt v1, output filter, red-team set in CI |
| M4 | Activities | Why questions, story with state, numbers, English words; activity cards and voice intents |
| M5 | Parent | Topic controls, limits, summaries, dashboard, alerts, memory screen, transcripts opt-in, export and delete |
| M6 | Evaluation | Model and prompt registry, evaluation runner, metrics dashboard, rating screen, device profile |
| M7 | Demo polish | Characters, animations, demo mode, PWA install, toy-speed simulation |

## 10. Open questions

1. Final Serbian TTS voice and its license.
2. Exact alert rules for safeguarding events (to be set with a child-protection expert during CRIA).
3. Final model choice (after [EVALUATION.md](EVALUATION.md) gates).
4. Whether pilot families use their own phones or devices we provide.
