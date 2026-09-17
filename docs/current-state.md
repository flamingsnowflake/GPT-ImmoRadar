# Current State

Last updated: 2026-09-17

## Production status

This release captures the reusable application baseline after a completed production search and operator reset. Runtime databases and prior search state are not part of the public distribution.

The Plötzkau location weighting is disabled for the new search. The configurable 80/20 location-weighting feature remains available, but a new reference location must be chosen deliberately before it is enabled again. Until then, ranking uses the independent score only.

The unified Telegram/browser workflow is live and has been tested end to end on both Immowelt and ImmoScout24.

The current working loop is:

```text
Telegram Labor item
    -> open exposé once
    -> Tampermonkey prepares and sends live browser evidence
    -> browser enrichment updates SQLite / rescoring / terminal status
    -> active Labor detects resolution
    -> same Telegram card advances automatically
```

This document describes the implementation state represented by this public release.

## `/incomplete` Labor

`/incomplete` is no longer a planned feature; it is the production workbench for unresolved property data.

Implemented specialist queues include Condition, Energy and Address/Geo-oriented review. Queues are re-evaluated from the database rather than treated as static snapshots. A separate optional `Lage präzisieren` queue handles locality-only provisional candidates.

Condition and Energy keep an active in-memory Labor session. While active, `telegram-commands` checks approximately every two seconds whether the displayed portal ID is still unresolved or has received a terminal event.

The Labor advances when, for example:

- browser enrichment resolves the required condition/energy information;
- the property is blacklisted;
- the user marks it offline/not interesting;
- the database row is removed;
- a portal explicitly reports the listing as removed and browser enrichment purges it;
- a manual Labor action completes the current item.

A restart of `telegram-commands` clears the active in-memory session; the persisted property decisions remain intact and the user simply reopens the relevant Labor queue.

For the full queue lifecycle see `docs/workflows.md`.

## Browser enrichment

The preferred browser path is the unified `/browser-enrich` endpoint backed by the host service `immobilien-browser-enrich.service`.

Current browser enrichment can:

- persist page text and browser metadata;
- normalize Immowelt title/location/plot/price facts where appropriate;
- scope blacklist checks so recommendation/navigation text does not create avoidable false positives;
- extract energy via the canonical Python parser plus DOM hints;
- extract explicit labelled condition fields;
- rescore affected properties;
- emit `blacklisted` terminal events;
- detect explicit removed-listing pages and purge the property;
- emit `purged` terminal events so Telegram advances even though the row was deleted.

Removed-listing detection is text-evidence based. It recognizes tested portal variants such as Immowelt's deleted-ad page and ImmoScout24's “offer not found / already deleted” page. A network error or arbitrary 404 is not by itself permission to purge.

## Tampermonkey production script

Production browser script:

```text
Immobilienmonitor – Browser & Energie
version 1.3.3
```

The exact generated production archive is stored under:

```text
userscripts/archive/Immobilienmonitor-Browser-Energie-1.3.3.zip
```

The archive contains the `.user.js` used in production. The previous `userscripts/immobilien-energy.user.js` v0.2.0 was obsolete and must not be treated as the canonical production userscript.

v1.3.3 includes SPA route handling, Immowelt detail expansion, ImmoScout24 DOM energy hints, automatic browser enrichment, manual Energy fallback, safe mobile placement above Immowelt's contact bar and the fix that closes only an Immowelt energy dialog opened by the script itself.

## Scoring completeness and zero values

The production scorer distinguishes a missing value from a legitimate zero:

```text
None = not checked / unresolved
0    = checked and genuinely zero
```

This applies to current workflows, not just presentation. Examples include:

```text
Lärm adjustment +0   -> completed result with no applicable penalty
water_score = 0      -> completed water search, no qualifying water found
Energy class D = 0   -> known neutral adjustment
```

A property remains `incomplete` only while a required category is genuinely unresolved according to its evidence/state fields. The final numeric total is withheld in that case. A hard KO may still surface earlier.

See `docs/scoring.md` for the detailed current model.

Completed properties currently rank by the independent scoring model because location weighting is disabled after the search reset. The optional location model can combine 80% of that independent score with 20% proximity to a configured reference point. Freilage is scored only inside the ordinary neighbour component: `isolated` requires at least 100 m to the nearest foreign building polygon, while `few_neighbours` permits at most two foreign building polygons within 50 m. House/farm and land candidates below 1,000 m² are hard exclusions; both models award plot points on the 3/7/10/15/20 scale for 1,000/1,500/2,000/3,000/5,000 m². The database stores the component values in `score_details`; locality-only candidates remain provisional until exact coordinates are known.

Positive house/farm energy labels contribute `C +1`, `B +3`, `A +5` and `A+ +8`. Both score paths permit exceptional results above 100 with a hard ceiling at 110. A perfect brokered house can reach 108 independently and 106 with maximum reference-point proximity; the existing Ohne-Makler bonus can raise those ceilings to 110 and 108 respectively.

When location weighting is enabled, Telegram displays the independent base score first and the weighted reference-location score directly below it. Freilage contributes through the regular neighbour component in the base score, which supplies 80% of the weighted score.

With location weighting disabled, `/top3house`, `/top10house` and their `_ohne` companions rank the same independent score. When a reference location is enabled, the regular commands use its weighted score and the `_ohne` commands keep the independent ranking. Chance cards include a direct, reversible `Lage angefragt` action that moves the property into the locality waitlist without replacing the card.

## Noise semantics and rail fallback

`noise_checked_at` is the main explicit completion marker for the noise check. A completed check is allowed to have a zero adjustment; `Lärm: +0` must never be rendered as “noch nicht geprüft”.

For EBA rail data, absence of a mapped isophone at the property point does not imply an invented low dB band. The rail query intentionally leaves LDEN/LNight unset when no mapped band exists.

For existing houses/farms, the scorer now has a conservative fallback when the EBA check ran but no mapped rail LDEN/LNight exists and both railway distance plus annual traffic are known within the supported distance. Mapped EBA values take precedence. The fallback may produce zero or a penalty and never creates an automatic KO by itself.

The production regression case for Wimmelburg is approximately:

```text
18,738 trains/year
360 m railway distance
=> rail fallback -5
```

When this fallback is available, house/farm `Lärm` is treated as resolved even without a mapped EBA isophone. The land model remains intentionally stricter.

## Condition semantics

Browser auto-condition uses explicit labelled portal fields only. `browser_explicit` condition is protected against duplicate alert refreshes; Telegram/manual condition values remain higher-precedence.

Raw portal condition and modernization/sanitation hints can be shown in the Labor when a decisive classification is not possible. A modernization year alone never implies a good condition.

Current house condition surcharges used for price scoring include:

```text
turnkey                  +0 EUR
good                +15,000 EUR
maintained          +15,000 EUR
cosmetic renovation +40,000 EUR
renovation needed   +80,000 EUR
major renovation   +140,000 EUR
dilapidated        +220,000 EUR
unknown            +100,000 EUR
```

The hard house budget uses purchase price plus known condition surcharges. Unknown condition estimates remain open until review, unless the purchase price alone already exceeds the budget. Bonuses and the chances list cannot bypass that limit.

## Energy semantics

Energy score adjustments currently are:

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

Additional outcomes:

```text
checked unknown          -7
not_required             -7
no_label                 -8
not_available_yet        unresolved / no total
untested                 unresolved / no total
```

Value-to-class boundaries used for consistency/fallback interpretation:

```text
< 30       A+
< 50       A
< 75       B
< 100      C
< 130      D
< 160      E
< 200      F
<= 250     G
> 250      H
```

If a class and numeric value contradict, the worse energy outcome wins for purchase-risk scoring.

The Energy queue uses live `energy_certificate_status` / `energy_updated_at` state, not a possibly stale `score_details.incomplete_reasons` snapshot.

## Duplicate refresh resilience

A repeated alert for the same `(portal, portal_id)` may update normal listing facts such as current price while retaining finalized enrichment that was obtained separately in the browser or Labor.

Completed Energy and explicit browser condition are therefore merged/protected before duplicate rescoring.

## User status

Per-property user status is stored separately from scoring (`active`, `offline`, `not_interested`). It controls visibility/queues without rewriting the property's intrinsic score.

The status-table initialization has a once-per-process fast path so active Labor polling does not perform unnecessary SQLite schema writes every two seconds.

## Geographic coverage and precision

Geo evidence distinguishes `exact`, `locality` and `missing`.

Exact addresses and manually confirmed coordinates use normal water/neighbour/noise scoring. Locality-only objects do not receive points from a geocoded town centre; they remain visible with a provisional score range. The normal Address/Geo Labor only asks for a usable exact location when the location itself is unresolved.

`/incomplete` also has an optional `Lage präzisieren` queue for active provisional locality candidates. Its cards display the current score range and provide the existing address/coordinate dialog. Locality objects remain provisional and visible even when the user does not process this optional queue.

### Manual exact location recalculation

Setting manual coordinates or a verified exact address now triggers a real Geo rescan rather than merely storing latitude/longitude.

The workflow:

```text
store exact manual location
    -> clear old Water result
    -> clear old Neighbour/building result
    -> clear old Rail/Road/Air noise result
    -> rerun enrichment at the exact coordinate
    -> rescore
    -> persist new Geo evidence + score
```

The Telegram result explicitly reports which checks were recalculated and which remain technically open. Once exact coordinates are known, a downstream service failure does not put the property back into the Address/Geo queue and ask for the same address again.

### Regional data coverage

The high-quality water and neighbour/building enrichment paths use official state geodata services for Sachsen-Anhalt, Niedersachsen and Brandenburg. Brandenburg uses the GeoBasis-DE/LGB ATKIS physical-water WFS and ALKIS 2D-building WFS. All three adapters feed the same water scoring and neighbour classification. Noise enrichment remains based on nationwide/federal/EEA sources (with a more sensitive Saxony air-noise layer where available). Unsupported states remain explicitly unknown rather than being mistaken for empty water or building coverage.

Niedersachsen rollout was tracked in private issue #1.

## Ohne-Makler scoring

Recognized broker-free offers receive a transaction-cost scoring advantage without changing the hard-filter purchase price:

```text
real purchase price       unchanged for KO/budget
scoring purchase price    -3%
minimum scoring advantage +3 points
```

A larger price-bracket gain may apply when the 3% scoring adjustment crosses a bracket boundary.

## Regression coverage

Current regression coverage includes browser condition parsing/hints, energy consistency, Energy auto-advance, live incomplete-energy semantics, Geo precision, manual coordinates, queue disappearance after blacklist/delete, terminal event storage/purge cleanup, scoring policy extensions and the rail-noise fallback behavior.

The final Labor/browser checkpoint was tested successfully before being committed as the production baseline; later scoring/Geo changes have their own targeted regression tests and should not be assumed covered by an older checkpoint.

## Public-release work

The production repository remains private while a sanitized, history-free public export is maintained separately.

The public release must not expose production tokens, databases, e-mails, browser captures, Telegram sessions, personal contact strings or private hostnames. See `docs/public-release.md`.
