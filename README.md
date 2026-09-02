# GPT-ImmoRadar

**A self-hosted property radar that turns listing alerts and manually found properties into an explainable, ranked shortlist.**<br>
**It combines automatic e-mail processing, geo data and human-assisted browser enrichment with a configurable scoring model.**<br>
**Keep the pipeline, change the search and scoring rules, and use it for your own house hunt.**

> **Private production repository:** this repository is the source of truth for the currently deployed system. The public snapshot is intentionally sanitized and may lag behind production features and scoring semantics. For the exact current behavior, start with `docs/current-state.md`, `docs/scoring.md` and `docs/workflows.md`.

## What it does

### 1. Email processing

Property-alert e-mails are read via IMAP, parsed and normalized into a local SQLite database.

The monitor detects new and duplicate listings, extracts portal IDs and listing facts, and keeps one persistent record per property. Duplicate refreshes may update ordinary portal facts while preserving stronger browser/manual enrichment such as finalized Energy and explicit condition evidence.

### 2. Telegram bot

Telegram is the main working interface.

It can:

- show new listings, provisional ranges and final scores;
- open the original portal page;
- search and rank stored properties;
- mark properties as interesting, offline or not interesting without rewriting their intrinsic score;
- correct incomplete data;
- import a supported listing by pasting its URL;
- show/set exact coordinates or an exact address and immediately rerun dependent Geo enrichment;
- run `/incomplete` as a guided workbench for unresolved Condition, Energy and Address/Geo evidence;
- offer an optional `Lage präzisieren` queue for promising locality-only properties;
- automatically advance active Labor sessions when the current item is resolved, blacklisted, removed or otherwise leaves the queue.

The Labor queues are dynamic: they are derived again from current SQLite state rather than treated as a frozen list.

### 3. Human-assisted browser enrichment

Some portal information is only available after the page is rendered in a normal browser.

Instead of trying to defeat CAPTCHAs or browser-security checks, the user opens the listing normally. A Tampermonkey userscript then reads the **already rendered page** and sends structured evidence back to the local enrichment service.

This allows the system to capture things such as:

- energy class and energy values;
- explicit property-condition fields;
- browser-only DOM information;
- portal messages that an advert has been deleted;
- current-exposé blacklist evidence without letting unrelated recommendation/navigation text poison the decision.

The production loop is intentionally browser-first where strong browser evidence is useful:

```text
Telegram Labor item
    -> open exposé once
    -> Tampermonkey sends rendered evidence
    -> browser enrichment updates SQLite / score / terminal state
    -> active Labor observes the change
    -> same workbench advances automatically
```

The human remains part of the loop where automation should not pretend to know more than it does.

### 4. Geo, water, neighbours and noise enrichment

Listings can be enriched with external geographic data, including:

- **nearby water, not just as a simple distance:** the system records distance and distinguishes water type/significance or size class where the source data allows it, so a small stream is not treated the same as a substantial river or other major body of water;
- surrounding building density and neighbour situation, including whether a property is isolated, loosely developed, on a village edge or in denser development;
- mapped road, rail and aircraft noise, including day/evening/night and night-time noise levels where available;
- **for building plots:** planning/development status — for example whether normal residential development is allowed, or whether a building permit, preliminary approval or other useful planning evidence is known.

Geo evidence has explicit precision states:

```text
exact     exact address or manually confirmed coordinates
locality  locality/postcode known, exact property location unknown
missing   no usable location evidence
```

A locality-only object is **not** scored using a town-centre coordinate as though it were the property. It receives a provisional worst/best Geo range and can optionally be processed through `Lage präzisieren` once an exact location becomes known.

Setting an exact address or manual coordinates invalidates the previous derived Geo result and reruns Water, Neighbours and Noise at the new coordinate before rescoring. If one downstream service is temporarily unavailable, the location remains solved; the system does not ask for the same exact address again.

For **existing houses**, planning/development status is not part of the house score. Instead, the important property-specific categories include the **condition of the building** and its **energy performance / energy label**.

These facts are stored separately from the score so the scoring model can be changed later without re-discovering the evidence.

### 5. Explainable scoring

The score is deliberately not a black box. Every category contributes visible points, penalties or KO reasons.

The most important state rule is:

```text
None = not checked / unresolved
0    = checked and legitimately zero
```

A zero is therefore **data**, not a synonym for missing. Examples include a completed `Lärm: +0` result, `water_score = 0` after a successful search that found no qualifying water, or the neutral Energy adjustment for class D.

A final numeric total is withheld only while required evidence is genuinely unresolved. A definitive hard KO can still be surfaced immediately.

For houses/farms, the current private base model is:

```text
Price + condition       25
Plot                    20
Neighbours              25
Quiet                   15
Water                   10
Living area              5
--------------------------
Base                   100
```

Energy is an adjustment rather than a fixed category. A good label can add points; a poor/uncertain result can subtract them. Current class adjustments are:

```text
A+  +3
A   +2
B   +1
C   +1
D    0
E   -1
F   -3
G   -5
H   -8
```

Additional Energy states distinguish a truly unresolved certificate (`untested`, `not_available_yet`) from a completed but risky/uncertain result (`checked unknown`, `not_required`, `no_label`).

#### Noise completion is not the same as a non-zero penalty

For noise, `noise_checked_at` is the important completion marker. If the check completed and no applicable source penalty exists, `Lärm: +0` is a valid result and an existing house receives full Quiet points.

Likewise, **no mapped EBA rail isophone does not mean an invented low dB value**. When a house/farm has a completed rail check but no EBA isophone at the property, the production scorer can use a conservative distance + annual-traffic fallback when both facts are known. Mapped EBA levels always take precedence; the fallback does not create an automatic KO by itself.

See `docs/scoring.md` for the full current semantics and production values.

### 6. Condition-aware price scoring

The house price score is based on an effective price:

```text
real purchase price + configured condition surcharge
```

The hard purchase-price limit still uses the **real purchase price only**.

For example, the current production model treats `good` and `maintained` as a +15,000 EUR allowance, renovation-needed as +80,000 EUR and major renovation as +140,000 EUR. This makes a cheap ruin comparable with a more expensive house that needs little work instead of rewarding asking price in isolation.

Broker-free offers recognized as Ohne-Makler receive a transaction-cost scoring advantage: the real purchase price remains unchanged for hard filters, while scoring treats it as 3% lower and grants at least a +3-point benefit.

### 7. Pluggable for another person's search

The current private scoring reflects one real-world search, but the system is intentionally configurable.

You can adapt it by changing things such as:

- price limits;
- plot-size preferences;
- neighbour/isolation importance;
- water importance;
- noise tolerance;
- energy penalties;
- condition/renovation assumptions;
- public-transport access or commute time;
- score thresholds;
- blacklist terms;
- search presets.

Those categories are not meant to be universal. For an **urban apartment search**, for example, a fork could drop water and isolation completely and instead enrich and score distance to tram, metro or railway stops, service frequency, commute time, schools, shops, parking or any other criterion that matters to that search.

The ingestion, database, Telegram workflow and browser enrichment can remain the same while the enrichment modules and scoring model change.

For the current implementation, see `docs/scoring.md`; portable example configuration lives under `config/public/`.

### 8. Manual property import

A property does not have to arrive through an alert e-mail.

A listing URL can be pasted directly into Telegram, imported, enriched and scored like any other object.

This is useful for listings found manually, recommendations from friends, or properties from sources that do not provide alert e-mails.

### 9. Queue resilience and deleted listings

The system detects when a rendered portal page explicitly says a listing has been removed and can purge it from the active property set. A network error, CAPTCHA or arbitrary transport failure is not enough to authorize a purge.

Blacklist matches, deleted listings, manual status changes and completed browser enrichment all feed back into the Telegram Labor so the workflow does not get stuck on dead objects.

Browser terminal events distinguish at least:

```text
blacklisted
purged
```

See `docs/workflows.md` for the end-to-end queue behavior.

## Architecture in one picture

```text
alert e-mail / pasted URL
          |
          v
       monitor
          |
          +---- automatic parsing / geo enrichment
          |
          v
       SQLite
          ^
          |
Telegram bot <------ human review / /incomplete Labor
          ^                         |
          |                         +---- exact address/coordinates
          |                                      |
          |                                      v
          |                                geo re-enrich + rescore
          |
Browser + Tampermonkey
          |
          v
HTTPS reverse proxy
          |
          v
browser enrichment service
          |
          +-- energy
          +-- condition
          +-- blacklist
          +-- deleted listing detection
          +-- rescore / terminal events
```

## Why AI matters here

This project is also a practical demonstration of **AI as an engineering multiplier**.

A large part of the architecture, implementation, debugging, regression testing and documentation was produced with **ChatGPT / OpenAI GPT-5.6 Sol**, while the project itself grew out of a real house search and continuous production use.

The development loop looked much more like engineering collaboration than automatic code generation:

- define a real problem and acceptance criteria;
- inspect a real listing or failure case;
- design and implement a solution;
- deploy it on the actual server;
- test it in the real Telegram/browser workflow;
- keep what works, change what does not;
- add regression tests and documentation so the result survives the next iteration.

That combination made it possible for one technically curious person, working with AI, to build and operate a system that would otherwise require substantially more development time.

> **The human defined the problem, priorities and acceptance criteria. AI accelerated the engineering work. The working system came from the feedback loop between both.**

The point is not that engineering became unnecessary. The point is that **engineering gained a very powerful new tool**.

## Self-hosted

The reference setup uses:

- Python
- SQLite
- Docker Compose
- Telegram
- Tampermonkey
- an HTTPS reverse proxy
- a small systemd browser-enrichment service

No cloud AI service is required at runtime for scoring or normal operation.

## Documentation

The private production documentation lives under `docs/`:

- `docs/current-state.md` — what is currently implemented/deployed;
- `docs/scoring.md` — exact scoring, completion and `None`/`0` semantics;
- `docs/workflows.md` — e-mail/import, Labor, browser, Energy, Condition and Geo workflows;
- `docs/architecture.md` — component and data-flow architecture;
- `docs/browser-enrichment.md` — Tampermonkey/browser enrichment pipeline;
- `docs/decisions.md` — durable behavioral decisions that should not be casually reopened;
- `docs/operations.md` — restart matrix, tests, migrations and backups;
- `docs/installation.md` — reference installation;
- `docs/public-release.md` — safe sanitized public-export process.

`PROJECT.md` is the continuity entry point for future development sessions.

## Credits

Project idea, requirements, priorities and production validation: **Andreas / flamingsnowflake**.

The majority of the software architecture, implementation assistance, debugging, tests and technical documentation was developed collaboratively with **ChatGPT by OpenAI (GPT-5.6 Sol)**.

See `CONTRIBUTORS.md` for the longer development history.

## License

GNU Affero General Public License v3.0 or later (**AGPL-3.0-or-later**).

Commercial use is welcome. Fork it, adapt it, build on it, and make money with it. The copyleft terms are there so that improvements remain available to the people who receive or use modified versions, including over a network.

This project is not affiliated with ImmobilienScout24, Immowelt or other listing portals. Users are responsible for complying with portal terms, rate limits, data-protection rules and applicable law.
