# Customizing GPT-ImmoRadar for a different property search

GPT-ImmoRadar was built for one real search, but the useful part is the pipeline rather than the original preferences.

The project separates as much **evidence** as possible from the **score** that interprets that evidence. A fork can therefore keep the e-mail ingestion, database, Telegram workflow, manual URL import and browser-enrichment loop while changing what is measured and what is important.

## The reference search

The current reference configuration strongly values things such as:

- purchase price and building condition;
- plot size;
- few or distant neighbours;
- quiet surroundings;
- nearby water, including water type / significance rather than distance alone;
- living area;
- energy performance;
- for building plots, planning/development evidence.

That makes sense for a rural house search. It is not intended as a universal definition of a good property.

## Example: urban apartment search

A city-apartment fork could keep the same ingestion and review workflow but replace rural criteria with urban ones.

For example:

```text
Price / monthly cost          25
Public transport              25
Commute time                  15
Energy performance            10
Noise                         10
Shops / daily services         5
Schools / childcare            5
Parking / bike storage         5
                              ---
                              100
```

A public-transport enrichment module could evaluate more than straight-line distance. Depending on available data, it could consider:

- distance to the nearest tram, metro, bus or railway stop;
- mode of transport;
- service frequency;
- number of useful lines;
- walking time to the stop;
- travel time to a workplace or city centre;
- evening/weekend service;
- whether a nearby railway line is useful transport, unwanted noise, or both.

The same fact can also affect more than one decision. A railway station may be a strong mobility bonus while a railway line immediately behind the building may incur a noise penalty.

## Other possible forks

The same pattern can support very different searches. Examples include:

- families: schools, childcare, playgrounds, traffic safety;
- commuters: motorway access, station access, door-to-door travel time;
- accessibility: step-free access, lift, floor, medical services;
- resilience: flood zones, wildfire risk, heat exposure;
- energy-focused searches: roof orientation, solar potential, heating type, efficiency;
- car-light households: public transport, cycling infrastructure, daily services within walking distance;
- renovation projects: condition evidence, estimated work, heritage restrictions, usable outbuildings.

## Where to change things

The current reference scoring contract is documented in `docs/scoring.md`.

The main implementation lives in:

```text
config/score.yaml
app/scoring.py
```

Existing geographic enrichment lives primarily in the `app/` modules used by the monitor. A new criterion normally needs three pieces:

```text
1. evidence acquisition / enrichment
2. persisted field or derived value
3. scoring rule + explanation
```

Keeping these concepts separate is important. It allows a score to be changed later without having to re-fetch every fact, and it keeps the final ranking explainable.

## Recommended fork workflow

Start by writing down your own decision model before editing code:

```text
What is a hard KO?
What earns points?
What loses points?
Which facts are required before a score is trustworthy?
Which facts can be gathered automatically?
Which facts require human review?
```

Then modify one category at a time and test it against real examples from your own search.

That is the intended use of this project: **keep the pipeline, change the evidence and scoring rules, and make the system solve your property search rather than the original author's.**
