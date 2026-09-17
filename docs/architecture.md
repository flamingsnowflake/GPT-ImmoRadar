# Architecture

## Overview

GPT-ImmoRadar is a Python/SQLite real-estate decision-support system with four Docker services, one host-side browser enrichment service and a browser userscript.

The system intentionally separates automatic evidence collection from human decisions. Automatic parsers may fill fields only when the evidence is strong enough; unresolved items stay in Telegram Labor queues instead of being silently treated as zero.

The implementation distinguishes **evidence state** from **numeric value** throughout the pipeline. In particular, `None` can mean unresolved while `0` can be a fully checked result. See `docs/scoring.md`.

## Main data flow

```text
listing alert / pasted URL
        │
        ▼
     monitor
        │
        ├── portal parsing / normalization
        ├── property-type detection
        ├── geocoding + geo precision
        ├── water / neighbours / noise
        ├── buildability / condition hints
        └── score / provisional range / incomplete state
        │
        ▼
     SQLite
        ▲
        │
        ├──────── telegram-commands ◄──── Telegram user
        │                    │
        │                    ├── active Labor session (~2 s polling)
        │                    └── exact address/coordinate correction
        │                                  │
        │                                  └── invalidate Geo -> enrich -> rescore
        │
        └──────── browser_enrich_server.py
                              ▲
                              │ /browser-enrich
                              │
                    Tampermonkey userscript
                              ▲
                              │
                     live portal exposé
```

## Runtime components

### `monitor`

Compose service/container responsible for ingestion, normalization, automatic enrichment, scoring, persistence and initial Telegram notifications.

Primary modules include:

```text
app/monitor.py
app/scoring.py
app/enrichment.py
app/geo_precision.py
app/noise.py
app/noise_sources.py
app/buildability.py
app/house_condition.py
```

Duplicate alerts update ordinary listing facts while finalized browser/manual enrichment is preserved where required. In particular, completed energy data and explicit browser condition must not be lost merely because a later alert contains less information.

### `telegram-commands`

Compose service/container responsible for Telegram commands, callbacks, property cards, manual corrections and Labor workflows.

Relevant modules:

```text
app/telegram_commands.py
app/telegram_ui.py
app/incomplete_workflow.py
app/incomplete_energy.py
app/energy_lab_auto.py
app/manual_coordinates.py
app/user_status.py
```

`/incomplete` is the production workbench. Condition and Energy can keep active in-memory Labor sessions; Address/Geo resolves missing exact location; `Lage präzisieren` is a separate optional queue for locality-only provisional candidates.

The active Energy and Condition Labor sessions are kept in process memory. While a session is active, Telegram long-polling is shortened to roughly two seconds and the current queue is re-evaluated. A queue is dynamic, not a frozen list.

Changes to `telegram_commands.py` require restarting the `telegram-commands` Compose service.

See `docs/workflows.md` for queue semantics and auto-advance conditions.

### Manual location domain module

`app/manual_coordinates.py` owns the exact-address/coordinate correction logic instead of leaving it embedded in Telegram callbacks.

A manual exact location update:

```text
persist exact coordinate
    -> geo_precision = exact
    -> clear previous Water fields
    -> clear previous Neighbour/building fields
    -> clear previous Rail/Road/Air noise fields
    -> call normal enrichment
    -> rescore
    -> persist refreshed evidence
```

This is intentionally a rescan, not just a latitude/longitude overwrite. Once exact coordinates are known, a downstream service failure does not turn the property back into an address-entry task.

### `property-browser`

Compose service/container providing server-side browser rendering for workflows that need it. It is distinct from the browser enrichment service and does not normally need a restart for scoring-only changes.

### `energy-api`

Compose service/container for explicit/manual energy submissions. It remains a fallback even though the preferred path is now the unified browser enrichment flow.

Relevant modules:

```text
app/energy_api.py
app/energy_data.py
```

### Host browser enrichment service

`immobilien-browser-enrich.service` runs:

```text
app/browser_enrich_server.py
```

Reference bind address:

```text
127.0.0.1:8765
```

It receives authenticated browser payloads, stores browser evidence and can update/rescore the property immediately.

It coordinates:

```text
app/browser_energy.py
app/browser_condition.py
app/browser_condition_hints.py
app/lab_terminal.py
```

It can produce normal enrichment results, browser blacklist results and terminal `purged` results for explicitly removed portal listings.

### Tampermonkey userscript

The production userscript is `Immobilienmonitor – Browser & Energie` v1.3.3.

Its responsibilities include:

- detecting ImmoScout24 and Immowelt exposé routes, including SPA navigation;
- waiting for a usable page instead of transmitting a half-rendered route;
- avoiding CAPTCHA pages;
- automatically opening Immowelt “Mehr Infos” when needed for energy details;
- closing only an energy dialog that the script itself opened;
- extracting DOM-only energy-class hints from ImmoScout24;
- sending page text, URL, heading, JSON-LD and DOM hints to `/browser-enrich`;
- displaying browser enrichment status;
- retaining an explicit manual Energy fallback.

The exact production build is archived under `userscripts/archive/`. Public releases must use configurable endpoints instead of an operator-specific production hostname.

## Browser terminal events

Browser enrichment can record explicit terminal events in SQLite:

```text
browser_terminal_events
    portal
    portal_id
    status       # purged | blacklisted
    updated_at
```

`purged` is only generated after a portal page explicitly indicates that the listing was removed/unavailable. A generic HTTP/network failure is not enough to delete a property.

Purge cleanup removes the property and associated per-property search/favorite/user-status references before recording the terminal event. This gives the active Telegram Labor an unambiguous reason to advance even though the property row itself no longer exists.

## Condition pipeline

Automatic browser condition classification deliberately reads explicit labelled portal fields such as:

```text
Zustand der Immobilie
Objektzustand
```

It does not classify a house from arbitrary positive/negative words in free-form marketing text.

`condition_source = browser_explicit` is preserved across duplicate alerts. Manual Telegram decisions have higher precedence.

Modernization/sanitation years are context for the Labor UI, not proof that the building is in good condition.

## Energy pipeline

The canonical browser parser lives in `app/browser_energy.py`; persistence/normalization lives in `app/energy_data.py`.

The live Energy queue is derived from current energy fields rather than stale `score_details`. Finalized energy survives later duplicate-alert refreshes.

Energy states distinguish:

```text
untested                  -> incomplete
not_available_yet         -> incomplete
checked but unknown       -> complete with uncertainty penalty
not_required              -> complete with uncertainty penalty
no_label                  -> complete with stronger penalty
available class/value     -> complete
```

## Geo precision pipeline

Geo precision is persisted explicitly:

```text
exact
locality
missing
```

`exact` permits normal Water/Neighbours/Noise scoring.

`locality` deliberately avoids a town-centre pseudo-coordinate. `app/scoring.py` creates worst/best Geo variants and stores a provisional score range instead of an exact total. These candidates remain visible and can be processed through the optional `Lage präzisieren` queue.

`missing` remains an Address/Geo Labor task until a trustworthy exact location is known.

## Noise evidence pipeline

Noise data keeps check state separate from mapped values.

```text
noise_checked_at = None -> unresolved
noise_checked_at set    -> check executed; evaluate returned evidence
```

A completed check can therefore yield a legitimate `0` adjustment.

For EBA rail data, no isophone at the point does not imply a fabricated low band. For existing houses/farms, `app/scoring.py` can use a conservative rail distance + annual-traffic fallback when the check is complete, mapped rail levels are absent and the required fallback evidence is available. Mapped EBA levels always win; the fallback itself does not create a KO.

## Data storage

Runtime SQLite path inside Compose containers:

```text
/data/database.sqlite3
```

Reference host path:

```text
/opt/immobilien-monitor/data/database.sqlite3
```

The database is runtime/private data and must not be part of a public source snapshot.

## Scoring lifecycle

For required categories:

```text
None = not checked / unresolved
0    = checked and genuinely zero
```

A complete numeric total is withheld while required categories remain unresolved. A hard KO can still be returned immediately.

Locality-only Geo is a third presentation state: it can produce a provisional range without pretending the property has exact environmental evidence.

`score_details` is the persisted explanation of a scoring pass. Presentation should reuse it rather than independently constructing a second scoring model. Workflows with dedicated live completion state, especially Energy, must use the live fields for queue membership.

For the exact production scoring rules see `docs/scoring.md`.

## Module direction

New domain workflows should continue to move into dedicated modules. `telegram_commands.py` should primarily orchestrate Telegram interaction rather than become the home for all domain logic.
