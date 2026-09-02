# Immobilien Monitor — Project Continuity

This repository is the durable source of truth for the private production history and current production behavior of GPT-ImmoRadar. The public repository is a sanitized distribution snapshot and may intentionally lag behind private scoring/workflow changes.

## Purpose

The project monitors real-estate listings, enriches them with geo/noise/water/browser information, scores them, stores them in SQLite and exposes review/correction workflows through Telegram.

The core goal is not generic scraping. It is a decision-support loop that combines automatic evidence with explicit human review for questions that should not be guessed.

## Working agreement

- Prefer small, modular changes over further growth of monolithic files.
- Python indentation must be exact and copy/paste-safe.
- Avoid project-local `.bak` files; use Git for history and `/tmp` for temporary work.
- Every non-trivial change should include syntax checks and, where practical, automated regression tests.
- Never commit real secrets, `.env`, SQLite databases, archived mail, Telegram sessions, browser-enrichment inbox payloads or private keys.
- Before changing established behavior, read `docs/decisions.md`, `docs/current-state.md`, `docs/scoring.md` and `docs/workflows.md`.
- Before `git pull`, always inspect `git status --short`.
- **Interactive SSH safety:** never prefix copy/paste commands intended for the operator's live SSH shell with `set -e`, `set -euo pipefail` or equivalent shell-exit behavior. A normal command failure must not terminate the operator's SSH shell. If strict shell mode is useful, put it inside a disposable script/subshell instead of changing the interactive shell state.
- **Public-export self-audit:** `tools/export_public_snapshot.py` is itself part of the public snapshot and is scanned by its own assignment-secret detector. The scanner definition `ASSIGNMENT_SECRET_RE = ...` is a known self-match and must be exempted only for that exact variable in that exact exporter file. Do not broadly suppress `SECRET`, `TOKEN`, `PASSWORD`, `API_KEY`, etc. checks. The independent Gitleaks scan remains part of the public-release workflow.

## Reference runtime

Project root:

```text
/opt/immobilien-monitor
```

Docker Compose services:

```text
monitor            main ingestion/enrichment/scoring process
telegram-commands  Telegram commands, callbacks and Labor sessions
property-browser   server-side page rendering helper
energy-api         explicit/manual energy API
```

Host service:

```text
immobilien-browser-enrich.service
    -> app/browser_enrich_server.py
```

Browser runtime:

```text
Tampermonkey: Immobilienmonitor – Browser & Energie
production archive: userscripts/archive/Immobilienmonitor-Browser-Energie-1.3.1.zip
```

The browser userscript, host enrichment service and Telegram Labor form one asynchronous workflow. Opening an exposé can resolve energy/condition, blacklist it, or identify it as removed; Telegram notices the queue/terminal-state change and advances automatically.

## Scoring semantics

For production scoring:

```text
None = category not yet tested / unresolved
0    = category was tested and legitimately scored zero
```

This is not merely a UI convention. Completion is determined by explicit evidence/state fields. Examples of valid zero outcomes include `Lärm: +0`, `water_score = 0`, and the class-D Energy adjustment.

A numeric total is shown only when all required categories for that scoring path are complete. A definitive KO may be surfaced earlier.

Locality-only Geo is handled separately:

```text
geo_precision = locality
-> provisional score range, not a fake exact total
```

Public score states include:

```text
⏳ UNVOLLSTÄNDIG
📍 VORLÄUFIG <min>–<max>
⛔ KO
⭐ <score> / 100
```

`score_details` explains a scoring pass, but queue decisions that have a dedicated live state — notably Energy and active Labor semantics — must use the live persisted fields rather than trusting an old score snapshot.

Detailed current behavior lives in `docs/scoring.md`.

## Browser-first completion loop

The preferred path is:

```text
Telegram property
    -> open portal once
    -> Tampermonkey prepares/reads the live DOM
    -> /browser-enrich
    -> canonical Python parsers
    -> SQLite + rescore/terminal event
    -> Telegram auto-advance
```

Manual Energy/Condition controls remain fallbacks. Explicit manual values have precedence over later automatic guesses.

For missing exact Geo, verified address/coordinate input triggers a full Water + Neighbours + Noise recalculation and rescore rather than merely overwriting latitude/longitude.

See `docs/workflows.md` for the end-to-end production workflows.

## Public-release policy

Do not make this historical production repository public in-place.

A public release must be created from a newly generated, history-free snapshot after privacy and secret checks. Production endpoints, personal contact data and machine-specific details must be replaced with configuration/examples.

See `docs/public-release.md`.

## Documentation map

- `README.md` — project overview and private-production entry point
- `docs/current-state.md` — current implemented/deployed state
- `docs/scoring.md` — current scoring, completion, zero-value and Geo-provisional semantics
- `docs/workflows.md` — ingestion, `/incomplete`, browser, Energy, Condition and Geo workflows
- `docs/architecture.md` — component/data-flow architecture
- `docs/browser-enrichment.md` — browser/Tampermonkey enrichment pipeline
- `docs/decisions.md` — decisions that should not be casually reopened
- `docs/operations.md` — operational commands/restart matrix/backups
- `docs/installation.md` — installation reference
- `docs/public-release.md` — safe open-source publication plan
- `SECURITY.md` — secret and vulnerability handling
- `CONTRIBUTORS.md` — project and AI-assisted development credit
