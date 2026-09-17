# Decisions

This file records decisions that should not be casually reopened in later sessions.

## Scoring completeness

Decision:

- Missing/unverified scoring categories do not silently count as zero.
- `None` means not tested/missing.
- `0` means tested and legitimately zero.
- No numeric overall score is shown while relevant categories are incomplete.
- A definitive KO can still be surfaced before every other category is complete.

Reason: a precise-looking total is misleading when an important category was never actually checked.

## Telegram UI and Labor

Decision:

Keep normal property cards/actions uncluttered. `/incomplete` is a dedicated Labor/workbench rather than another set of permanent buttons on every object.

Labor queues are dynamic. After every successful action or external browser resolution, re-query the database and advance to the next currently unresolved object.

Condition and Energy may keep only the lightweight active message/session identity in RAM. Property decisions themselves live in SQLite.

Normal detail actions should stay in the same Telegram message wherever practical, with a back/cancel route to the same property context.

## Browser-first review loop

Decision:

The preferred manual-review workflow is:

```text
Telegram property -> open portal once -> browser enrichment -> automatic rescore -> Labor advance
```

Do not require repetitive Details -> action -> Back -> Next interaction when browser evidence can resolve the task safely.

Tampermonkey is a first-class runtime component, not an ad-hoc debugging helper. Canonical domain parsing remains in Python where possible; the userscript primarily exposes browser-only evidence and DOM hints.

## Browser terminal states

Decision:

Use explicit terminal events for browser outcomes that remove an item from a Labor independently of normal enrichment:

```text
blacklisted
purged
```

A portal listing may be purged only when the rendered portal page contains explicit evidence that the listing was removed/unavailable. Network failures, CAPTCHA, timeouts or a generic transport error are not sufficient.

Purge removes the property and dependent per-property search/favorite/user-status references, then records a terminal event so an active Labor can advance even though the original row no longer exists.

## Blacklist evidence

Decision:

Blacklist matching must use text relevant to the current exposé. Portal navigation, recommendation cards and unrelated listings must not poison the current property's blacklist decision.

Browser-generated blacklist state stores enough previous scoring information to allow automatic restoration if a later browser check shows that the browser blacklist condition no longer applies.

## Manual address / Geo workflow

Decision:

Geo tasks in the Labor are deliberately conservative.

- Do not guess a more exact property address than the evidence provides.
- The user enters an exact address or coordinates only when actually known.
- A manual exact address/coordinate update invalidates the prior geo result and recalculates water, neighbours/freilage and noise together before rescoring.
- After successful recalculation, Labor advances to the next unresolved Geo object.
- Once verified coordinates exist, downstream technical failures in water, neighbour or noise services do not ask for the same address again. Those checks remain technically incomplete and may be retried separately.

Reason: a guessed address can produce a precise-looking but wrong environmental score.

Geo precision is persisted with three explicit states:

```text
exact     exact address or manually confirmed coordinates
locality  only locality/postcode is known
missing   no usable location evidence
```

`exact` keeps the existing water, neighbours and noise scoring. `locality` never uses a locality centroid for those categories; it receives a provisional score range from the worst and best possible Geo outcomes and remains eligible for Top lists. `missing` remains Geo-Labor work. A `locality` object must not enter the Geo Labor merely because its exact address is unavailable.

The Labor exposes locality-only objects in a separate optional `Lage präzisieren` queue. This queue is not an incomplete/error state. It is ordered by provisional upside and lets a verified address or coordinates replace the range with normal exact Geo scoring. Successful input advances to the next locality candidate.

## Legacy-data repair

Decision:

Before asking for manual review, automatically repair legacy incomplete data wherever existing evidence supports it, but do not invent missing evidence.

Examples include rerunning geo from valid stored coordinates, reclassifying explicit condition fields and parsing stored browser text for energy.

## Water semantics

Decision:

A successful water search that finds nothing qualifying inside the configured radius is a completed check with zero points, not an untested state.

```text
water_score = None -> not checked
water_score = 0    -> checked, no qualifying water found
```

## Noise semantics

Decision:

Noise completion and noise penalty are separate concepts.

```text
noise_checked_at = None -> noise not checked / unresolved
noise adjustment = 0    -> may be a completed check with no applicable penalty
```

A completed `Lärm: +0` result is therefore valid evidence and must not be presented as “noch nicht geprüft”. For existing houses it maps to full Quiet points.

For rail, absence of an EBA isophone at the property point must not be converted into an invented low dB value. “No mapped isophone” means exactly that; it does not prove `<55 dB` or `<45 dB`.

For existing houses/farms, a conservative rail fallback may complete the noise category when:

- the noise check has completed;
- no mapped rail LDEN/LNight value exists at the property;
- rail distance is known and at most 1,000 m;
- annual train traffic is known.

Mapped EBA values always take precedence. The fallback uses distance plus annual traffic and may produce zero or a negative adjustment. It does not create an automatic KO by itself.

The land model remains deliberately stricter and should not inherit house/farm completion assumptions by accident.

Reason: an absent map polygon is not evidence of silence, but a known railway distance plus known traffic volume is still useful evidence and should not leave a house permanently incomplete when a conservative fallback can be applied.

## Condition semantics

Decision:

Automatic browser condition classification is based on explicit labelled portal fields (for example `Zustand der Immobilie` / `Objektzustand`), not arbitrary words in marketing prose.

Manual Telegram decisions have precedence. A decisive browser result uses `condition_source = browser_explicit` and is protected across later duplicate alert refreshes.

Modernization/sanitation year is contextual evidence only and never proves a good building condition by itself.

## Energy semantics

Decision:

Do not infer “energy checked” merely from the existence of browser text. Portal data may be hidden behind expanded UI or represented only in DOM/image metadata.

Supported explicit outcomes include:

```text
class A+..H
manual kWh/(m²·a) value
checked but no usable energy data stated
no energy label supplied
energy certificate not required
energy certificate not available yet
```

`not_available_yet` remains unresolved and does not permit an overall score.

Current risk treatment:

```text
untested                         -> incomplete
certificate not available yet    -> incomplete
checked but energy unknown       -> -7
energy certificate not required  -> -7
no energy label supplied         -> -8
A+ / A / B / C / D / E / F / G / H -> configured adjustment
```

When class and numeric value conflict, use the worse interpretation for purchase-risk scoring.

The Energy Labor queue must use live persisted Energy fields rather than stale `score_details.incomplete_reasons`.

If browser enrichment resolves Energy while an older Labor card is visible, that stale card must never overwrite the newer result; it should advance.

## Duplicate alerts

Decision:

A later duplicate alert may refresh ordinary portal facts while preserving finalized enrichment gathered through a stronger channel.

In particular:

- completed browser/manual Energy is merged into the fresh property before duplicate scoring;
- `browser_explicit` and manual condition are protected from weaker alert-text heuristics.

## Ohne-Makler scoring

Decision:

Offers identified as broker-free receive a transaction-cost advantage in scoring for houses/farms and land.

- Actual purchase price remains unchanged for hard budget/KO filters.
- For scoring, purchase price is treated as 3% lower.
- Score advantage is at least +3 points; a larger crossed-bracket gain may be used.
- Detection uses portal identity and URL so parser naming differences do not lose the effect.

## Runtime reload boundaries

Decision:

Treat every long-running process that imports scoring/domain modules as a separate runtime generation. A source edit on a bind mount does not reload already imported Python modules.

Restart the appropriate process set after changes; see `docs/operations.md`.

## Source history and backups

Decision:

- Git is the durable source-code history.
- Avoid project-local `.bak` proliferation.
- Use `/tmp` for transient patch files.
- Use SQLite's backup API for a consistent live DB snapshot.
- Production DB/credentials/runtime captures never belong in Git.

## Public/open-source release

Decision:

Do **not** change the historical production repository from private to public in-place.

Instead, generate a new sanitized snapshot with no previous Git history and publish that snapshot in a separate public repository.

Reasons:

- an old private commit may contain debug/personal infrastructure details even when the current tree is clean;
- production hostnames and contacts are deployment-specific;
- source releases should contain configuration examples, not the operator's runtime identity;
- a fresh initial commit gives a clear privacy boundary that can be audited.

Operational history remains private while the public repository provides a portable product/source distribution.

Before publication, rotate credentials that have ever been exposed in terminal/debug output as defense in depth, even if they were never committed.

## Code maintenance

Decision:

- Prefer dedicated modules for substantial domain workflows.
- Keep orchestration and domain logic separate where practical.
- Changes should be copy/paste-safe and include syntax/tests where practical.
- Security/privacy checks are part of the release process, not an afterthought.

## Plötzkau distance weighting

Superseded for the production weights and isolation thresholds by **Strong isolation preference** below; retained as history.

Decision:

- Keep the established property score as the explainable base score.
- Rank completed candidates with 70% base score, 20% proximity to Plötzkau and an isolation preference worth up to 10 final points.
- Define proximity as a linear score from 100 at Plötzkau to 0 at and beyond 100 km.
- Add 10 final points for `isolated` and 8 for `few_neighbours`; keep all other neighbour classes at zero extra preference points.
- Exclude plots below 1,000 m² and apply a stronger plot-point reduction below 2,000 m².
- Require exact coordinates for a definitive combined score; preserve a provisional range for locality-only candidates.
- Keep an operator's reference point in local configuration only. The public example exposes the feature with generic, disabled values.

## Regional geo coverage

Decision:

The original geo enrichment was built around Sachsen-Anhalt official WFS services because that was the initial search region. The active search area now also includes Niedersachsen and Brandenburg.

- Keep the existing Sachsen-Anhalt ATKIS/ALKIS WFS sources.
- Use the official Niedersachsen LGLN INSPIRE WFS sources for physical water and 2D buildings.
- Use the official Brandenburg GeoBasis-DE/LGB INSPIRE WFS sources for ATKIS physical water and ALKIS 2D buildings.
- Preserve the existing water scoring model and neighbour classification semantics across all supported states.
- Noise enrichment remains based on nationwide/federal/EEA sources as already implemented.
- Never treat an out-of-coverage state service returning no features as evidence for `none_nearby` or `isolated`.

Regression targets include Niedersachsen properties in Hitzacker and Osterode/Lerbach, including Ohne-Makler object `OM-469963`, plus production object `933` for Brandenburg.

## Strong isolation preference

Superseded by **Single neighbour component and 80/20 Plötzkau weighting** below; retained as history.

Decision:

- Keep proximity to Plötzkau at 20% of the final score.
- Use 60% of the independent base score and reserve up to 20 final points for the isolation preference.
- Award the final preference as 20 points for `isolated` and 15 for `few_neighbours`.
- Classify `isolated` only when the nearest foreign building polygon is at least 200 m away.
- Classify `few_neighbours` only when no more than two foreign building polygons are within 50 m.
- Persist the new 50 m building count; do not infer it from the older 100 m count.
- Apply the plot scale 3/7/10/15/20 at 1,000/1,500/2,000/3,000/5,000 m² to both house/farm and land.

## Single neighbour component and 80/20 Plötzkau weighting

Decision:

- Keep Freilage and neighbour density exclusively in the existing base-score neighbour component; do not add a separate preference bonus.
- Calculate the Plötzkau score as 80% of the independent base score plus 20% of the linear proximity score.
- Classify `isolated` when the nearest foreign building polygon is at least 100 m away, or when a completed search finds no foreign building in its search radius.
- Keep `few_neighbours` for properties with no more than two foreign building polygons within 50 m that do not qualify as `isolated`.
- Reclassify stored completed neighbour checks from their persisted measurements when current scores are recalculated.

## Strong positive energy labels

Decision:

- Reward documented investment in efficiency, insulation and sustainability more strongly in the house/farm base score.
- Apply `C +1`, `B +3`, `A +5` and `A+ +8`.
- Keep the existing neutral value for `D` and the existing penalties and unresolved-state rules for weaker, missing or unavailable energy evidence.
- Permit exceptional scores above 100 and cap both independent and weighted results at 110 instead of discarding the positive energy investment at the old ceiling.

## Search reset and neutral location ranking

Decision:

- Archive the completed search database outside the live runtime and start the production database empty.
- Keep reference-location weighting disabled in the public baseline until an operator deliberately configures a relevant reference point.
- Retain the configurable 80/20 reference-location feature for a future search, but require a deliberate new reference point before enabling it.
- Keep the scoring, enrichment, Telegram and Labor functionality as the final reusable product baseline and publish one final sanitized public snapshot from that state.
