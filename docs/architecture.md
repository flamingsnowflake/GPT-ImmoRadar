# Architecture

## Overview

GPT-ImmoRadar is a Python/SQLite real-estate decision-support system with Docker services, a small host-side browser-enrichment service and a Tampermonkey userscript.

The architecture separates three concerns:

```text
collect evidence
      -> persist facts
      -> interpret those facts with a scoring model
```

That separation is important for forks. A different search can keep the ingestion, database, Telegram and browser workflow while replacing individual enrichment modules or scoring rules.

The system also separates automatic evidence from human decisions. Parsers fill fields only when the evidence is strong enough; unresolved items remain in Telegram review queues instead of silently becoming zero points.

## Main data flow

```text
listing alert / pasted URL
        |
        v
     monitor
        |
        +-- portal parsing / normalization
        +-- property-type detection
        +-- geocoding
        +-- water / neighbours / noise
        +-- house: condition / energy evidence
        +-- land: planning / development evidence
        +-- score or incomplete state
        |
        v
     SQLite
        ^
        |
        +-------- telegram-commands <---- Telegram user
        |                    |
        |                    +-- active Labor session
        |
        +-------- browser_enrich_server.py
                              ^
                              | /browser-enrich
                              |
                    Tampermonkey userscript
                              ^
                              |
                     live portal exposé
```

## Runtime components

### `monitor`

The main Compose service handles ingestion, normalization, automatic enrichment, scoring, persistence and initial Telegram notifications.

Important modules include:

```text
app/monitor.py
app/scoring.py
app/enrichment.py
app/noise_sources.py
app/buildability.py
app/house_condition.py
```

Duplicate alerts can refresh ordinary listing facts while stronger manual or browser-derived evidence is preserved where appropriate.

### `telegram-commands`

This Compose service handles Telegram commands, callbacks, property cards, manual corrections and guided review queues ("Labor").

Relevant modules include:

```text
app/telegram_commands.py
app/telegram_ui.py
app/incomplete_workflow.py
app/incomplete_energy.py
app/energy_lab_auto.py
app/user_status.py
```

The active queue is dynamic rather than a frozen list. When browser enrichment resolves, blacklists or purges the current property, Telegram can advance to the next unresolved item.

### `property-browser`

A separate Compose service provides server-side page rendering for workflows that need it. It is distinct from the human-assisted browser-enrichment path.

### `energy-api`

A Compose service for explicit/manual energy submissions. It remains a fallback even though the preferred flow can obtain energy evidence from the user's rendered browser page.

Relevant modules:

```text
app/energy_api.py
app/energy_data.py
```

### Host browser-enrichment service

The reference architecture runs:

```text
app/browser_enrich_server.py
```

through a small systemd service. Reference listener:

```text
127.0.0.1:8765
```

It receives authenticated browser evidence, stores normalized facts and can rescore the property immediately.

It coordinates modules such as:

```text
app/browser_energy.py
app/browser_condition.py
app/browser_condition_hints.py
app/lab_terminal.py
```

### Tampermonkey userscript

The userscript runs on supported listing pages that the user opens normally.

Its responsibilities include:

- detecting supported exposé routes, including SPA navigation;
- waiting for usable rendered content;
- pausing on CAPTCHA/security pages rather than treating them as listing data;
- opening portal UI details when required to expose energy information;
- extracting DOM-only energy hints;
- submitting rendered evidence to `/browser-enrich`;
- showing enrichment status in the page;
- retaining a manual Energy fallback.

The public source is generated with a neutral example endpoint. Each fork must configure its own server and Tampermonkey `@connect` permission.

## Property-type-specific evidence

Not every criterion applies to every property type.

For an **existing house/farm**, important property-specific evidence includes:

```text
building condition
energy performance / energy label
living area
```

For **building land**, the corresponding workflow instead cares about planning/development evidence such as whether residential construction is possible or a permit/preliminary approval is known.

The shared geo evidence — for example water, neighbours and mapped noise — can be reused by both scoring families.

## Browser terminal events

Browser enrichment can record explicit terminal events in SQLite:

```text
browser_terminal_events
    portal
    portal_id
    status       # purged | blacklisted
    updated_at
```

`purged` is only generated after explicit portal evidence that a listing was removed or is unavailable. A network failure, timeout or CAPTCHA is not sufficient evidence to delete a property.

This terminal-event mechanism lets an active Telegram Labor advance even after the underlying property row has been deleted.

## Condition pipeline

Automatic condition classification deliberately relies on explicit labelled portal fields rather than arbitrary marketing language.

Examples:

```text
Zustand der Immobilie
Objektzustand
```

Manual decisions have higher precedence than weaker automatic guesses.

## Energy pipeline

The canonical browser parser lives in `app/browser_energy.py`; persistence and normalization live in `app/energy_data.py`.

Energy states distinguish unresolved evidence from known-but-poor evidence. That distinction is required by the scoring contract: unknown is not automatically zero.

## Data storage

Runtime SQLite path inside the Compose services:

```text
/data/database.sqlite3
```

A typical host path is:

```text
/opt/immobilien-monitor/data/database.sqlite3
```

The database is private runtime data and is never part of the public source export.

## Scoring lifecycle

For required categories:

```text
None = not checked / unresolved
0    = checked and genuinely scored zero
```

A complete numeric house/farm score is withheld while required evidence is unresolved. A hard KO can still be returned immediately.

`score_details` stores the explanation of a scoring pass so presentation can show how the result was reached rather than inventing a second scoring model.

## Extension points

The existing geo modules are examples, not a fixed definition of what a good property is.

A fork can add a new enrichment module and then connect its persisted evidence to the scoring model. For example, an urban-apartment fork could replace rural water/isolation priorities with:

```text
public-transport stop distance
service frequency
commute time
schools / childcare
shops / daily services
parking / bike storage
```

A railway station could even produce two independent facts: a mobility benefit and a noise penalty. Keeping evidence separate from the score makes this possible without conflating the two.

See `docs/customizing-your-search.md` for a concrete public-transport example.

## Module direction

New domain workflows should live in dedicated modules where practical. Telegram code should orchestrate interaction; it should not become the only place where domain rules exist.
