# Scoring, completeness and evidence states

Last updated: 2026-09-02

This document describes the **private production scoring model**. The authoritative implementation is `app/scoring.py` together with `config/score.yaml`; the public repository may intentionally lag behind this state.

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

The current private house/farm hard filters include:

```text
real purchase price <= 300,000 EUR
plot area >= 500 m²
```

The price KO uses the **real advertised purchase price**. Condition surcharges and the Ohne-Makler scoring effect do not change that hard-filter value.

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

Energy is an adjustment on top of that base before the final score is clamped to the configured range. Broker-free offers can also receive a scoring advantage.

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

This is why a cheap ruin can rank below a more expensive house in good condition: the ranking price is purchase price plus the configured condition surcharge, while the hard budget still looks only at the real purchase price.

### Plot

Current house plot points:

```text
>= 5,000 m²   20
>= 3,000 m²   18
>= 2,000 m²   16
>= 1,500 m²   14
>= 1,000 m²   11
>=   750 m²    7
>=   500 m²    3
```

### Neighbours / isolation

Current house values:

```text
isolated             25
few_neighbours       23
loose_development    20
village_edge         17
village              12
dense                 7
```

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
Plot                25
Water               20
Neighbours          15
Primary residence    5
Buildability         5
----------------------
Base               100
```

The current hard policy also requires at least 500 m², forbids holiday-only areas, requires normal residential building permission, and treats severe noise as a hard exclusion.

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
