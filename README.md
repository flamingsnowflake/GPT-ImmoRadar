# GPT-ImmoRadar

**A self-hosted property radar that turns listing alerts and manually found properties into an explainable, ranked shortlist.**<br>
**It combines automatic e-mail processing, geo data and human-assisted browser enrichment with a configurable scoring model.**<br>
**Keep the pipeline, change the search and scoring rules, and use it for your own house hunt.**

## What it does

### 1. Email processing

Property-alert e-mails are read via IMAP, parsed and normalized into a local SQLite database.

The monitor detects new and duplicate listings, extracts portal IDs and listing facts, and keeps one persistent record per property.

### 2. Telegram bot

Telegram is the main working interface.

It can:

- show new listings and scores;
- open the original portal page;
- search and rank stored properties;
- mark properties as interesting, offline or not interesting;
- correct incomplete data;
- run guided review queues ("Labor") for unresolved condition, energy and geo information;
- automatically advance to the next unresolved property when the current one is completed, blacklisted or removed.

### 3. Human-assisted browser enrichment

Some portal information is only available after the page is rendered in a normal browser.

Instead of trying to defeat CAPTCHAs or browser-security checks, the user opens the listing normally. A Tampermonkey userscript then reads the **already rendered page** and sends structured evidence back to the local enrichment service.

This allows the system to capture things such as:

- energy class and energy values;
- explicit property-condition fields;
- browser-only DOM information;
- portal messages that an advert has been deleted.

The human remains part of the loop where automation should not pretend to know more than it does.

### 4. Geo, water, neighbours and noise enrichment

Listings can be enriched with external geographic data, including:

- **nearby water, not just as a simple distance:** the system looks for nearby mapped water, records the distance and distinguishes the type / significance or size class of the water body where the source data allows it, so a small stream is not treated the same as a substantial river or other major body of water;
- surrounding building density and neighbour situation, including whether a property is isolated, loosely developed, on a village edge or in denser development;
- mapped road, rail and aircraft noise, including day/evening/night and night-time noise levels where available;
- **for building plots:** planning / development status — for example whether normal residential development is allowed, or whether a building permit, preliminary approval or other useful planning evidence is known.

For **existing houses**, planning/development status is not part of the house score. Instead, the important property-specific categories include the **condition of the building** and its **energy performance / energy label**.

These facts are stored separately from the score so the scoring model can be changed later without re-discovering the evidence.

### 5. Explainable scoring

The score is deliberately not a black box. Every category contributes visible points, penalties or KO reasons.

For example, a good house might score like this:

```text
Price + condition       19 / 25
Plot                    16 / 20
Neighbours              17 / 25
Quiet                   15 / 15
Water                    8 / 10
Living area              4 / 5
Energy label "A"         +2      <- bonus
--------------------------------
Total                    81 / 100  -> very interesting
```

Energy is deliberately shown as an adjustment rather than as a fixed category worth a certain number of points. A good label can add points; a poor label can subtract them.

A different house can look cheap at first but still rank much lower once condition and energy are taken into account:

```text
Purchase price          130,000 EUR
Condition surcharge     +140,000 EUR  (major renovation)
Effective price         270,000 EUR

Price + condition        9 / 25
Plot                    11 / 20
Neighbours               6 / 25
Quiet                   12 / 15
Water                    7 / 10
Living area              3 / 5
Energy label "H"         -8      <- penalty
--------------------------------
Total                    40 / 100  -> archive
```

In the current model, for example, energy label `A` gives **+2 points**, while label `H` deducts **8 points**. The detailed energy adjustments are configurable and documented with the rest of the scoring model.

Hard exclusions are handled separately. Missing required evidence is **not silently treated as zero**; houses can remain `incomplete` until the relevant category is actually known.

### 6. Pluggable for another person's search

The current scoring reflects one real-world search, but the system is intentionally configurable.

You can adapt it for yourself by changing things such as:

- price limits;
- plot-size preferences;
- neighbour / isolation importance;
- water importance;
- noise tolerance;
- energy penalties;
- condition / renovation assumptions;
- **public-transport access or commute time**;
- score thresholds;
- blacklist terms;
- search presets.

Those categories are not meant to be universal. For an **urban apartment search**, for example, a fork could drop water and isolation completely and instead enrich and score distance to tram, metro or railway stops, service frequency, commute time, schools, shops, parking or any other criterion that matters to that search.

The ingestion, database, Telegram workflow and browser enrichment can remain the same while the enrichment modules and scoring model change.

See `docs/customizing-your-search.md` for concrete adaptation ideas.

### 7. Manual property import

A property does not have to arrive through an alert e-mail.

A listing URL can be pasted directly into Telegram, imported, enriched and scored like any other object.

This is useful for listings found manually, recommendations from friends, or properties from sources that do not provide alert e-mails.

### 8. Queue resilience and deleted listings

The system detects when a portal explicitly says a listing has been removed and can purge it from the active queue.

Blacklist matches, deleted listings, manual status changes and completed browser enrichment all feed back into the Telegram Labor so the workflow does not get stuck on dead objects.

## Architecture in one picture

```text
alert e-mail / pasted URL
          |
          v
       monitor
          |
          v
       SQLite
          ^
          |
Telegram bot <------ human review
          ^
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
          +-- rescore
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

Detailed documentation lives under `docs/`, including:

- architecture;
- scoring rules;
- browser enrichment;
- installation and operations;
- adapting the enrichment/scoring model to a different search;
- safe public-release and security notes.

## Credits

Project idea, requirements, priorities and production validation: **Andreas / flamingsnowflake**.

The majority of the software architecture, implementation assistance, debugging, tests and technical documentation was developed collaboratively with **ChatGPT by OpenAI (GPT-5.6 Sol)**.

See `CONTRIBUTORS.md` for the longer development history.

## License

GNU Affero General Public License v3.0 or later (**AGPL-3.0-or-later**).

Commercial use is welcome. Fork it, adapt it, build on it, and make money with it. The copyleft terms are there so that improvements remain available to the people who receive or use modified versions, including over a network.

This project is not affiliated with ImmobilienScout24, Immowelt or other listing portals. Users are responsible for complying with portal terms, rate limits, data-protection rules and applicable law.
