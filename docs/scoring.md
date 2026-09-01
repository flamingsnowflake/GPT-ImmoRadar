# Reference Scoring Model

This document describes the reference scoring model shipped with GPT-ImmoRadar.

Canonical implementation:

```text
config/score.yaml
app/scoring.py
```

The model reflects one real rural house/land search. It is included as a working example, **not as a universal definition of a good property**. A fork is expected to change these rules for its own search; see `docs/customizing-your-search.md`.

## 1. Central rule: unknown is not zero

For houses/farms, missing required evidence does **not** mean zero points.

```text
unknown required evidence -> score=None, rating=incomplete
known bad evidence        -> zero or negative contribution is valid
hard exclusion            -> score=0, rating=ko immediately
```

A hard KO may be returned even while unrelated fields are still unresolved.

Land currently uses an older, less strict completeness model: missing non-KO inputs can contribute zero while a numeric total is still published. A fork may choose to adopt the stricter house/farm completeness model for land as well.

## 2. Rating thresholds

Both scoring families use:

| Score | Rating |
| ---: | --- |
| >= 90 | `dream` |
| >= 75 | `very_interesting` |
| >= 60 | `interesting` |
| >= 40 | `archive` |
| < 40 | `low` |

Special states:

```text
ko          hard exclusion, score=0
incomplete  house/farm requires more evidence, score=None
```

Final numeric scores are clamped to `0..100`.

# 3. House / farm scoring

## 3.1 Hard search filters

Reference limits:

```text
actual advertised purchase price <= 300,000 EUR
plot area                         >= 500 m²
```

The price KO uses the **actual purchase price only**. Condition/renovation surcharges do not trigger this hard filter.

`ignore_search_limits=True` can bypass these two search-limit KOs for internal/review calculations, while mapped-noise KOs still apply.

## 3.2 Completeness gate

A house/farm remains incomplete if any required category is unresolved:

| Category | Unresolved condition |
| --- | --- |
| Price/condition | price missing or condition unknown |
| Plot | plot area missing |
| Neighbours | not checked or class `unknown` |
| Noise | no completed noise check |
| Water | `water_score` missing |
| Living area | missing, except for `dilapidated` |
| Energy | never checked or status `not_available_yet` |

The application may calculate provisional category values internally, but the public result remains `score=None` / `rating=incomplete` until the required evidence is known.

## 3.3 Base category weights

| Category | Maximum |
| --- | ---: |
| Price + condition | 25 |
| Plot | 20 |
| Freestanding / neighbours | 25 |
| Quiet | 15 |
| Water | 10 |
| Living area | 5 |
| **Base** | **100** |

Energy and the broker-free rule are adjustments around this 100-point base. The final result is clamped to `0..100`.

## 3.4 Price + condition

The scoring price is an **effective price**:

```text
effective price = advertised purchase price + condition surcharge
```

Condition surcharges:

| Condition | Surcharge |
| --- | ---: |
| `turnkey` | 0 EUR |
| `good` | 0 EUR |
| `maintained` | 15,000 EUR |
| `cosmetic_renovation` | 40,000 EUR |
| `renovation_needed` | 80,000 EUR |
| `major_renovation` | 140,000 EUR |
| `dilapidated` | 220,000 EUR |
| `unknown` | 100,000 EUR |

Price brackets use that effective price:

| Effective price <= | Points |
| ---: | ---: |
| 130,000 | 25 |
| 160,000 | 22 |
| 190,000 | 19 |
| 220,000 | 16 |
| 250,000 | 13 |
| 275,000 | 9 |
| 300,000 | 5 |
| 310,000 | 0 |
| 320,000 | -5 |
| 330,000 | -15 |
| 340,000 | -25 |
| 350,000 | -35 |
| above | -40 |

This is intentionally separate from the actual-price KO. A house can cost less than 300,000 EUR to buy but receive a poor price/condition score because its likely renovation burden makes the effective cost much higher.

## 3.5 Plot

| Plot area >= | Points |
| ---: | ---: |
| 5,000 m² | 20 |
| 3,000 | 18 |
| 2,000 | 16 |
| 1,500 | 14 |
| 1,000 | 11 |
| 750 | 7 |
| 500 | 3 |

Below 500 m² is normally a hard search KO.

## 3.6 Freestanding / neighbours

| Class | Points |
| --- | ---: |
| `isolated` | 25 |
| `few_neighbours` | 22 |
| `loose_development` | 17 |
| `village_edge` | 12 |
| `village` | 6 |
| `dense` | 0 |

The high weight is deliberate for the reference rural search. An urban fork would likely replace or greatly reduce this category.

## 3.7 Noise -> Quiet

Mapped sources:

```text
rail
road
air
```

For each source, LDEN and Lnight are compared with thresholds. The worse day/night penalty is used for that source; source penalties are summed and capped at `-25` for houses.

House KO thresholds:

| Source | LDEN KO | Lnight KO |
| --- | ---: | ---: |
| Rail | >=75 dB | >=65 dB |
| Road | >=75 dB | >=65 dB |
| Air | >=65 dB | >=60 dB |

Non-KO penalties:

```text
Rail LDEN:   >=70 -14, >=65 -9, >=60 -5, >=55 -2
Rail night:  >=60 -14, >=55 -9, >=50 -5, >=45 -2
Road LDEN:   >=70 -14, >=65 -9, >=60 -5, >=55 -2
Road night:  >=60 -14, >=55 -9, >=50 -5
Air LDEN:    >=60 -16, >=55 -10, >=50 -5
Air night:   >=55 -17, >=50 -11, >=45 -6
```

The aggregate noise adjustment is translated into the 15-point Quiet category:

| Aggregate noise adjustment | Quiet points |
| --- | ---: |
| >= 0 | 15 |
| >= -2 | 12 |
| >= -5 | 9 |
| >= -9 | 6 |
| >= -14 | 3 |
| worse | 0 |

For houses the raw noise adjustment is **not subtracted a second time**.

## 3.8 Water

Geodata enrichment produces a raw `water_score` on a `0..20` scale. House scoring rescales it to `0..10`.

The enrichment is more than a nearest-distance check: where source data allows it, water type/significance or size class is used so a small stream need not be treated like a substantial river or other major water body.

## 3.9 Living area

| Living area >= | Points |
| ---: | ---: |
| 150 m² | 5 |
| 120 | 4 |
| 100 | 3 |
| 80 | 2 |
| >=0 | 1 |

For a `dilapidated` object the existing living area intentionally contributes `0`, and missing living area does not keep such an object incomplete.

## 3.10 Energy adjustment

Energy is an adjustment after the 100-point base:

| Effective class | Adjustment |
| --- | ---: |
| A+ | +3 |
| A | +2 |
| B | +1 |
| C | +1 |
| D | 0 |
| E | -1 |
| F | -3 |
| G | -5 |
| H | -8 |

Numeric kWh value maps to classes as follows:

```text
<30   A+
<50   A
<75   B
<100  C
<130  D
<160  E
<200  F
<=250 G
>250  H
```

If a portal-reported class and numeric value disagree, the **worse** class wins.

Special status policy:

```text
not_required       -> -7
no_label           -> H-equivalent (normally -8)
checked unknown    -> -7
not_available_yet  -> 0 provisionally, but remains incomplete
```

Certificate type (`demand` / `consumption`) is stored for explanation but currently does not change the adjustment.

## 3.11 Broker-free adjustment

Offers recognized as broker-free through the reference `ohne-makler.net` integration receive a fee-equivalence benefit.

Reference constants:

```text
assumed purchase-price advantage = 3%
minimum score bonus              = +3
```

For houses:

```text
discounted purchase price  = purchase price * 0.97
discounted effective price = discounted purchase price + condition surcharge
bracket gain               = discounted bracket points - normal bracket points
bonus                      = max(3, bracket gain)
```

The real advertised purchase price still controls the hard 300k search KO.

# 4. Building-land scoring

Planning/development status is relevant here because the object is **building land**. It is not a house-condition category.

The current code/config uses the internal name `buildability`; in user-facing terms this means **planning / development status**.

Land has a 100-point base before noise and broker-free adjustments:

| Category | Maximum |
| --- | ---: |
| Price | 30 |
| Plot | 25 |
| Water | 20 |
| Neighbours | 15 |
| Primary-residence usability | 5 |
| Planning / development status | 5 |
| **Base** | **100** |

## 4.1 Land hard KOs

Implemented reference hard exclusions include:

```text
plot < 500 m²
holiday_area == true
residential_building_allowed == false
severe_noise == true
mapped-noise KO thresholds reached
```

Text blacklist terms are primarily enforced in the ingestion/browser blacklist pipeline.

Important: the current `score_land` implementation has **no direct hard maximum-price KO**. Prices above the preferred range simply lose price points. A fork that wants `price > X` to be a true KO must implement that explicitly.

## 4.2 Land price

| Price <= | Points |
| ---: | ---: |
| 30,000 EUR | 30 |
| 40,000 | 25 |
| 50,000 | 20 |
| 60,000 | 10 |
| above | 0 |

The broker-free adjustment also applies to land.

## 4.3 Land plot

| Plot >= | Points |
| ---: | ---: |
| 2,000 m² | 25 |
| 1,500 | 22 |
| 1,000 | 20 |
| 750 | 12 |
| 500 | 6 |

## 4.4 Land water

Preferred input is enriched `water_score` (`0..20`). Older rows can fall back to simple distance brackets:

| Distance <= | Points |
| --- | ---: |
| 0.5 km | 20 |
| 1.0 km | 18 |
| 2.0 km | 15 |
| 3.0 km | 10 |
| farther | 0 |

## 4.5 Land neighbours

| Class | Points |
| --- | ---: |
| `isolated` | 15 |
| `few_neighbours` | 12 |
| `loose_development` | 10 |
| `village_edge` | 8 |
| `village` | 4 |
| `dense` | 0 |

## 4.6 Primary-residence usability

| State | Points |
| --- | ---: |
| `confirmed` | 5 |
| `probable` | 3 |
| `unknown` | 2 |
| `forbidden` | 0 |

A separate `residential_building_allowed == false` flag is a hard KO.

## 4.7 Planning / development status

Internal field/category name: `buildability`.

| State | Points |
| --- | ---: |
| `BUILDING_PERMIT` | 5 |
| `PRELIMINARY_APPROVAL` | 4 |
| `CONSTRUCTIONPLAN` | 4 |
| `NEIGHBOURCONSTRUCTION` | 3 |
| `NO_INFORMATION` | 0 |

## 4.8 Land noise

Land is intentionally stricter than houses in the reference search because a poor site is difficult to correct after building.

KO thresholds:

| Source | LDEN KO | Lnight KO |
| --- | ---: | ---: |
| Rail | >=70 dB | >=60 dB |
| Road | >=70 dB | >=60 dB |
| Air | >=60 dB | >=55 dB |

Penalty tables:

```text
Rail LDEN:   >=65 -18, >=60 -10, >=55 -5
Rail night:  >=55 -18, >=50 -11, >=45 -6
Road LDEN:   >=65 -18, >=60 -12, >=55 -6
Road night:  >=55 -18, >=50 -12
Air LDEN:    >=55 -20, >=50 -10
Air night:   >=50 -22, >=45 -12
```

Source penalties sum with an aggregate cap of `-30`. Unlike houses, this aggregate penalty is applied directly to the land score.

# 5. Calculation order matters

House/farm:

```text
1. determine completeness flags
2. evaluate hard actual-price / minimum-plot filters
3. evaluate noise KOs
4. if KO -> return immediately
5. price + condition effective-cost score
6. broker-free bonus
7. plot
8. neighbours
9. Quiet derived from mapped noise
10. water
11. living area
12. energy adjustment
13. if incomplete -> publish no numeric total
14. clamp 0..100 and classify
```

Building land:

```text
1. evaluate hard land/noise filters
2. if KO -> return immediately
3. price
4. broker-free bonus
5. plot
6. water
7. neighbours
8. primary-residence usability
9. planning / development status
10. raw mapped-noise adjustment
11. clamp 0..100 and classify
```

# 6. Evidence precedence is part of scoring correctness

Changing mathematical weights alone is not enough. Scoring relies on upstream evidence rules:

- explicit manual condition should not be overwritten by weaker automatic evidence;
- decisive browser condition survives duplicate alerts;
- finalized energy survives duplicate alerts;
- if energy class and numeric value disagree, the worse class wins;
- `not_available_yet` means unresolved, not bad;
- checked `unknown` can be a finalized risk state;
- browser purge/blacklist removes an item from the review queue rather than inventing score points.

A fork should preserve these semantics unless it deliberately wants different evidence precedence.

# 7. Adapting the score

A different search can keep the workflow while changing the decision model.

Useful questions before changing the score:

```text
Which criteria are hard KOs?
Which criteria earn or lose points?
Which evidence must be known before a score is trustworthy?
Should Energy remain an adjustment or become a weighted category?
Should condition stay coupled to effective price?
Should land adopt strict incomplete semantics?
Which enrichment modules should be removed or added?
```

For an urban apartment search, for example, water and isolation could disappear entirely while public transport and commute time become major categories.

See `docs/customizing-your-search.md` for a concrete example.
