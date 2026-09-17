# Scoring, completeness and evidence states

Last updated: 2026-09-17

This document describes the **reference scoring model** shipped with this release. The implementation is `app/scoring.py` together with `config/score.yaml`.

## State first, score second

A numeric value and the completion state are separate concepts.

```text
None = not checked / unresolved
0    = checked and legitimately zero
```

That distinction is fundamental. A required category that has not been checked keeps a property `incomplete` and no final numeric total is published. A checked category may legitimately contribute zero points or a zero adjustment without making the property incomplete.

Examples:

```text
noise adjustment = 0   -> checked, no mapped/fallback penalty
water_score = 0        -> checked, no qualifying water found
energy class D = 0     -> known, neutral energy adjustment
```

Completeness is therefore determined by the relevant persisted evidence/state fields, not by testing whether a numeric score is non-zero.

The main result states are:

```text
incomplete   required evidence is still unresolved
provisional  locality is known, exact Geo evidence is not; a score range is shown
ko           a hard exclusion is known
normal score all required evidence for that scoring path is complete
```

A definitive KO may be returned before every other category has been completed.

Per-property user status (`active`, `offline`, `not_interested`) is separate from intrinsic scoring and controls visibility/work queues rather than rewriting the score.

## House / farm model

The reference house/farm hard filters include:

```text
purchase price + known necessary condition costs <= house.hard_filters.max_price
plot area >= house.hard_filters.min_plot_area
```

The hard budget uses the **advertised purchase price plus the configured necessary condition surcharge**. The limit is `house.hard_filters.max_price`. It also applies to chances; the Ohne-Makler scoring discount cannot bypass it. An unknown condition's estimated surcharge does not trigger a KO: the property remains incomplete pending review. A purchase price alone above the limit is still a KO.

The normal 100-point house base is currently:

```text
Price + condition   25
Plot                20
Neighbours          25
Quiet               15
Water               10
Living area          5
----------------------
Base               100
```

Energy is an adjustment on top of that base. Exceptional properties may therefore exceed 100, with a hard safety ceiling of 110. Broker-free offers can also receive a scoring advantage.

## Optional distance weighting

Distance weighting is currently disabled after the production search reset. When enabled with a deliberately chosen reference location, every completed house/farm or land score combines the existing score with proximity to that point:

```text
proximity score = max(0, 100 × (1 - distance_km / 100))
final score     = round(0.80 × existing score
                        + 0.20 × proximity score)
```

The proximity score is 100 at the configured reference point, falls linearly with distance, and is 0 at and beyond the configured maximum distance. With the current optional 80/20 model it contributes at most 20 final points. Freilage is already part of the neighbour component in the independent base score and receives no separate bonus in the location formula. Distance uses the property's exact or manually confirmed coordinates and a great-circle calculation. The result details retain the existing score, distance, proximity score, weights and final score so the calculation remains explainable.

The independent score and an enabled weighted score both have a safety ceiling of 110. With the current positive energy adjustments, a brokered house can reach 108. An otherwise perfect broker-free offer also receives its established transaction-cost bonus and reaches the 110 ceiling; at maximum reference-point proximity this produces a weighted score of 108. Scores above 100 deliberately mark an exceptional property rather than being silently clipped.

When exact coordinates are unresolved, the scorer does not publish a false exact total. Locality-only properties continue through the provisional range workflow, with the distance contribution bounded between 0 and 100 until the address or point is known.

### Price + condition

Condition is converted into an estimated surcharge before selecting the price bracket:

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

The current effective-price brackets are:

```text
<= 130,000   25
<= 160,000   22
<= 190,000   19
<= 220,000   16
<= 250,000   13
<= 275,000    9
<= 300,000    5
<= 310,000    0
<= 320,000   -5
<= 330,000  -15
<= 340,000  -25
<= 350,000  -35
>  350,000  -40
```

Both ranking and the hard budget include the configured condition surcharge once the condition is known. For example, 295,000 EUR plus 15,000 EUR is a budget KO at a 300,000 EUR limit, even if the other score components are good.

### Plot

Current house plot points:

```text
>= 5,000 m²   20
>= 3,000 m²   15
>= 2,000 m²   10
>= 1,500 m²    7
>= 1,000 m²    3
<  1,000 m²   KO
```

### Neighbours / isolation

Current house values:

```text
isolated             25
few_neighbours       20
loose_development    12
village_edge          7
village               3
dense                 0
```

`isolated` requires the nearest foreign building polygon to be at least 100 m away. `few_neighbours` requires no more than two foreign building polygons within 50 m. These classes receive their preference entirely within the ordinary neighbour component above; there is no additional Freilage category or bonus. Water and quiet remain unchanged, and an enabled reference-location model contributes its configured proximity share separately.

For houses/farms the category is unresolved if `neighbour_checked_at` is missing or the neighbour class is still unknown. A low numeric result is not the same thing as an untested result.

## Noise and quiet

Noise uses explicit check state plus source evidence. The important completion marker is:

```text
noise_checked_at = None  -> Lärm unresolved
noise_checked_at set     -> the noise check ran; evaluate its evidence/result
```

A completed check may legitimately produce:

```text
Lärm: +0
```

That means **checked with no applicable penalty**, not “not checked”. For houses, a non-negative noise adjustment gives the full quiet score:

```text
noise adjustment >=   0  -> Quiet 15/15
noise adjustment >=  -2  -> Quiet 12/15
noise adjustment >=  -5  -> Quiet  9/15
noise adjustment >=  -9  -> Quiet  6/15
noise adjustment >= -14  -> Quiet  3/15
worse                    -> Quiet  0/15
```

Rail, road and aircraft sources have separate penalty/KO thresholds. Land is intentionally evaluated more strictly than existing houses.

### No EBA isophone does not mean “quiet”

The EBA rail query deliberately keeps “no mapped isophone at the property point” separate from an actual low dB result. Absence of an EBA isophone must **not** be translated into an invented `<55 dB` or `<45 dB` value.

### Rail fallback for houses/farms

For an existing house/farm, a completed rail check can use a conservative fallback when all of the following are true:

- `noise_checked_at` is present;
- no mapped rail LDEN/LNight value exists at the property;
- distance to the railway is known;
- annual train traffic is known;
- the railway is no more than 1,000 m away.

Mapped EBA values always take precedence. The fallback uses distance plus annual traffic, produces a penalty or zero, and **never creates an automatic KO by itself**.

Example from the production regression case:

```text
18,738 trains/year
360 m distance
=> rail fallback -5
```

When that fallback is available, the house/farm noise category is considered completed even though no EBA isophone exists.

The land model remains deliberately conservative; do not assume every house/farm completion shortcut has identical land semantics.

## Water

Water has an explicit tested-zero state:

```text
water_score = None  -> water not checked / unresolved
water_score = 0     -> checked; no qualifying water found
```

The enrichment water score uses a 0..20 source scale. Houses/farms scale that value to the configured 0..10 category. A genuine source value of zero therefore remains a completed result.

## Energy

Current class adjustments:

```text
A+  +8
A   +5
B   +3
C   +1
D    0
E   -1
F   -3
G   -5
H   -8
```

Additional explicit states:

```text
checked unknown          -7
not_required             -7
no_label                 -8 (same risk as H)
not_available_yet        unresolved / no final total
untested                 unresolved / no final total
```

A zero energy adjustment alone does not prove completion. For example, `not_available_yet` returns a neutral internal adjustment but remains incomplete through its status. The live persisted Energy fields determine completion.

When both a portal class and a numeric value exist and conflict, the worse class is used for purchase-risk scoring.

Numeric fallback boundaries are:

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

## Ohne-Makler effect

### Best-case chances

The extra chances below both Top-3 lists require `max_reachable_score > 75`;
exactly 75 is excluded. Only unresolved components receive their possible maximum.
Known poor water/neighbour/energy/noise values stay unchanged. The regular scorer
calculates the result, including bonuses and hard KOs; assumptions are never saved
as property facts. Listings already displayed in the Top-3 are not repeated.

Recognized broker-free offers receive a transaction-cost scoring advantage:

- the real purchase price remains unchanged for hard filters;
- the purchase price is treated as 3% lower for scoring;
- the score advantage is at least +3 points;
- if that 3% shift crosses a larger price-bracket difference, the larger bracket gain may apply.

Detection uses portal identity and URL so parser naming variations do not silently remove the effect.

## Geo precision and provisional scoring

Geo evidence has three explicit precision states:

```text
exact     exact address or manually confirmed coordinates
locality  locality/postcode known, exact property location unknown
missing   no usable location evidence
```

`exact` uses normal water/neighbour/noise scoring.

`locality` does **not** score a town-centre geocode as if it were the property. Instead the scorer evaluates low/high Geo variants and exposes a provisional range (`score_min`..`score_max`). The property remains visible and may appear in Top lists, but no fake exact total is published.

`missing` remains an incomplete Geo task.

## Land model

Land has its own base model and stricter location/noise policy:

```text
Price               30
Plot                20
Water               20
Neighbours          20
Primary residence    5
Buildability         5
----------------------
Base               100
```

The current hard policy also requires at least 1,000 m², forbids holiday-only areas, requires normal residential building permission, and treats severe noise as a hard exclusion.

## Source of truth

When documentation and old screenshots disagree, check these files in this order:

```text
app/scoring.py
config/score.yaml
app/incomplete_workflow.py
app/noise.py
app/geo_precision.py
docs/decisions.md
docs/current-state.md
```

`score_details` is the persisted explanation of a scoring pass. Workflows that have stronger live state, especially Energy and active Labor queues, must use those live persisted fields rather than treating an old `score_details` snapshot as authoritative.
