# Production workflows

Last updated: 2026-09-02

This document describes the workflows currently used in the **private production repository**. They are intentionally more detailed than the portable public snapshot.

## 1. Ingestion paths

Properties can enter the same SQLite-backed pipeline through more than one route.

### Alert e-mail

```text
property-alert e-mail
    -> IMAP monitor
    -> portal parsing / normalization
    -> type + geo enrichment
    -> scoring / incomplete state
    -> SQLite
    -> Telegram notification
```

Duplicate alerts update ordinary listing facts while stronger manually/browser-enriched fields are preserved where required.

### Manual URL import

A supported listing URL can be pasted directly into Telegram:

```text
pasted listing URL
    -> URL importer
    -> normalize / deduplicate
    -> enrich
    -> score
    -> SQLite
    -> normal Telegram property workflow
```

A manually found property therefore does not need an alert e-mail to become a first-class monitored object.

## 2. Telegram `/incomplete` Labor

`/incomplete` is the production workbench for unresolved evidence, not a static report.

It currently separates work into specialist paths including:

```text
Energy
Condition
Address / Geo
Lage präzisieren   (optional locality queue)
```

The overview also counts other incomplete facts such as price, living area and plot size. The specialist queues only expose actions that the current workflow can actually resolve.

Queue membership is re-read from SQLite. It is not frozen when the Labor is opened. Inactive objects, KOs and obsolete duplicate rows do not remain in the actionable queue.

### Active Labor sessions

Condition and Energy keep only lightweight session/message state in process memory. While a Labor session is active, `telegram-commands` checks the current item frequently and advances when the underlying database state changes.

Typical terminal reasons include:

- browser enrichment resolved the requested evidence;
- a browser blacklist result removed the object from consideration;
- the portal explicitly reported the listing as removed and the property was purged;
- the user marked the property offline or not interesting;
- the database row disappeared;
- a manual Labor choice completed the current category.

Restarting `telegram-commands` clears only this in-memory navigation state. Persisted property decisions remain in SQLite; reopen `/incomplete` to continue.

## 3. Condition workflow

Condition is relevant to houses/farms and feeds directly into the effective-price model.

Preferred path:

```text
Condition Labor card
    -> open exposé
    -> Tampermonkey sends rendered evidence
    -> browser enrichment reads explicit labelled condition fields
    -> persist condition
    -> rescore
    -> active Labor advances
```

Automatic classification uses explicit portal fields such as `Zustand der Immobilie` / `Objektzustand`. Marketing prose is not treated as reliable condition evidence.

When automatic evidence is insufficient, the manual buttons currently cover:

```text
Bezugsfertig
Gut
Gepflegt
Teilrenovierung
Renovierungsbedürftig
Sanierungsbedürftig
Baufällig
```

Modernization/sanitation years may be displayed as hints but do not prove a good condition by themselves.

Manual values have higher precedence than later weak automatic guesses. An explicit browser condition is also protected against being lost on a later duplicate alert.

## 4. Energy workflow

The preferred Energy flow is also browser-first:

```text
Energy Labor card
    -> open exposé
    -> Tampermonkey expands/reads relevant browser DOM where needed
    -> /browser-enrich
    -> canonical Python energy parser
    -> persist live Energy state
    -> rescore
    -> Labor advances
```

Manual A+..H and manual energy-value controls remain fallbacks.

Energy completion is based on live persisted fields, not on an old `score_details.incomplete_reasons` snapshot. In particular:

```text
untested              -> unresolved
not_available_yet     -> unresolved
checked unknown       -> completed with risk penalty
not_required          -> completed with risk penalty
no_label              -> completed with H-like risk penalty
class/value available -> completed
```

`not_available_yet` remains in the Energy queue but is sorted behind immediately actionable cases so a waiting certificate does not block the manual workbench.

If browser enrichment resolves an item while an older Labor card is still visible, the stale card must not overwrite the newer Energy result. The queue should advance instead.

## 5. Address / Geo workflow

The Geo workflow distinguishes a genuinely missing exact location from a downstream service problem.

### Missing exact location

When the property has no usable exact location, the Labor can accept either:

```text
latitude, longitude
```

or an exact German street address with house number.

An exact address is geocoded and then treated as confirmed exact Geo input. The system deliberately refuses to turn a locality-only string into a fake exact property location.

### What happens after manual coordinates/address

A manual exact location is not a cosmetic database edit. The previous derived Geo result is invalidated before recalculation.

The workflow does this as one logical operation:

```text
store manual exact location
    -> mark geo_precision = exact
    -> clear old water result
    -> clear old neighbour/building result
    -> clear old rail/road/air noise result
    -> rerun automatic enrichment at the new coordinate
    -> rescore
    -> persist new evidence + score
```

The Telegram response reports which of Water, Neighbours and Noise were recalculated successfully and which downstream checks are still technically open.

### Exact location known, service failed

Once verified coordinates exist, a temporary water/neighbour/noise service failure does **not** put the same property back into the “please enter the address” queue. The address problem is solved; the downstream evidence problem remains separate.

This avoids repeatedly asking the user for an exact location that is already known.

## 6. Locality-only / `Lage präzisieren`

A locality-only property is different from a missing-location property.

```text
geo_precision = locality
rating        = provisional
```

The scorer does not use the town centre for exact water/neighbour/noise points. Instead it exposes a worst/best provisional score range.

These properties remain visible and may still be useful candidates. They are **not** forced into the normal Geo error queue merely because the agent has not published the exact address.

`/incomplete` therefore exposes a separate optional `Lage präzisieren` queue. It is ordered by potential provisional upside so the most promising properties can be clarified first. Supplying verified coordinates/address converts the object to exact Geo scoring and advances to the next candidate.

## 7. Browser enrichment lifecycle

The current preferred human-assisted loop is:

```text
Telegram property/Labor item
    -> open portal page once
    -> Tampermonkey waits for usable rendered page
    -> send authenticated browser payload
    -> /browser-enrich
    -> canonical Python parsers / evidence policy
    -> SQLite update
    -> rescore or terminal event
    -> Telegram observes new state and advances
```

Current browser enrichment can contribute:

- rendered page text and metadata;
- explicit condition fields;
- Energy class/value/DOM hints;
- normalized portal facts where appropriate;
- blacklist evidence scoped to the current exposé;
- explicit removed-listing detection;
- immediate rescoring.

A CAPTCHA, timeout or arbitrary transport failure is not enough to purge a property.

### Terminal events

Two browser outcomes can remove an active item without a normal “completed category” result:

```text
blacklisted
purged
```

`purged` requires explicit rendered portal evidence that the listing itself has been removed/unavailable. The property and dependent per-property references are cleaned up and a terminal event remains long enough for the active Labor to know why it should advance.

## 8. Duplicate refresh workflow

A duplicate listing is not blindly rebuilt from the newest alert.

Ordinary portal facts such as price may refresh, but finalized evidence obtained through a stronger channel is merged/protected before rescoring. Important examples are:

- completed manual/browser Energy data;
- explicit browser condition;
- manual condition choices.

This prevents a sparse later e-mail from turning a completed property back into an unresolved one.

## 9. User status workflow

User disposition is persisted separately from score:

```text
active
offline
not_interested
```

Changing user status controls Top lists/work queues without changing the underlying environmental/property score. The decision can therefore be reversed without reconstructing the original score.

## 10. Noise workflow and checked zero

Noise completion must not be inferred from the adjustment value alone.

```text
noise_checked_at = None  -> not checked
noise adjustment = 0     -> can be a valid completed result
```

A completed result with no applicable penalty is shown as `Lärm: +0` and, for houses, yields full Quiet points.

For rail, “no EBA isophone at the property” is not automatically equivalent to a low dB band. Existing houses/farms may instead use the conservative distance + annual-traffic fallback when its evidence is available. See `docs/scoring.md` for the exact scoring semantics.

## 11. Runtime / restart boundaries

The workflows span multiple long-running processes. Editing a bind-mounted Python file does not reload already imported modules.

Use the restart matrix in `docs/operations.md`. In particular:

```text
Telegram command/callback/Labor change -> restart telegram-commands
monitor ingestion change               -> restart monitor
browser enrichment server/parser       -> restart host systemd service
shared scoring/domain change            -> restart all score-producing processes
```

`property-browser` normally does not need a restart for scoring-only changes.

## Relevant modules

```text
app/monitor.py
app/url_import.py
app/telegram_commands.py
app/incomplete_workflow.py
app/manual_coordinates.py
app/geo_precision.py
app/browser_enrich_server.py
app/browser_energy.py
app/browser_condition.py
app/lab_terminal.py
app/user_status.py
app/scoring.py
app/noise.py
```

For durable behavioral decisions also read `docs/decisions.md`; for the currently deployed feature set read `docs/current-state.md`.
