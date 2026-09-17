# Telegram command and button reference

Telegram is the main user interface for reviewing, correcting and ranking
properties. Only the chat configured by `TELEGRAM_CHAT_ID` is accepted. `/help`
and `/start` show a compact German version of this reference in Telegram.

## Import

Send a supported Immowelt or ImmoScout24 listing URL as a normal Telegram
message. The bot imports the listing through the same normalization, enrichment,
scoring and persistence path as an e-mail alert. Sending a previously rejected
listing URL explicitly restores it from `Kein Interesse` before processing it.

## Search, display and saved properties

| Command | Function |
| --- | --- |
| `/find <text>` | Search title, location and portal ID. |
| `/search <text>` | Alias for `/find`. |
| `/property <ID>` | Show the latest complete property view and its actions. |
| `/inspect <ID>` | Open the manual house-condition choices. |
| `/merkliste` | Show all favorited properties. |
| `/favorites` | Alias for `/merkliste`. |

Selecting one of several search results opens its normal property card first.
`Details` then opens the deeper detail view, and `Zurück` returns to the same
property card. Multi-entry search and favorites output shows at most ten entries
and states how many of the total are shown when results are truncated. Only
active objects participate in ordinary rankings and queues.

## Rankings and chances

| Command | Ordering and scope |
| --- | --- |
| `/top3house` | Best three houses/farms by the active score (independent while location weighting is disabled). |
| `/top10house` | Best ten houses/farms by the active score (independent while location weighting is disabled). |
| `/top3house_ohne` | Best three houses/farms by independent base score. |
| `/top10house_ohne` | Best ten houses/farms by independent base score. |
| `/top3land` | Best three building plots. |

When reference-location weighting is enabled, house cards show both the independent score and the weighted score. The
`_ohne` commands change the ordering; they do not remove Freilage from the base
model.

Top-3 output may append up to three `Chancen`. A chance is incomplete but could
exceed the configured chance threshold if every still-open criterion receives
its best possible outcome. Hard KOs, the hard budget and the 1,000 m² minimum
still apply. Chance cards contain the direct, reversible `Lage angefragt`
action. It stores the property in the locality waitlist without replacing the
chance card; the button then becomes `Lage wieder offen`.

## Incomplete Labor and waitlists

`/incomplete` opens the dynamic workbench. It groups current tasks into:

- Condition;
- Energy;
- missing exact Address/Geo data;
- optional locality precision work;
- requested-condition and requested-location waitlists.

The queues are recalculated from current database state after every action.
Labor and waitlist screens show one object at a time together with its position
in the complete queue, so a long queue never produces a burst of cards.
`Information angefragt` moves a Condition or Locality task to its persistent
waitlist. `Wieder offen` returns it to the normal queue. `Überspringen` only
hides the current item for the current pass. `Kein Interesse` changes the
personal property status and removes it from active ranking and Labor work.

Condition and Energy sessions also observe browser-enrichment updates. If the
open browser page supplies decisive evidence, becomes blacklisted or is removed,
the active Telegram card advances automatically.

## Coordinates and Geo recalculation

| Command | Function |
| --- | --- |
| `/coords <ID>` | Show the current automatic/manual coordinate state. |
| `/coords <ID> <latitude> <longitude>` | Store exact coordinates and rerun Water, Neighbours and Noise. |
| `/coords <ID> <address>` | Geocode an exact address, store it and rerun dependent Geo checks. |
| `/coords-auto <ID>` | Remove the manual override, restore automatic geocoding and rerun dependent Geo checks. |

The Address/Geo and Locality Labor cards expose the same input as buttons.
A locality-only location is not silently accepted as an exact address.

## Manual condition and buildability

`/condition <ID> <value>` accepts:

```text
turnkey
good
maintained
cosmetic_renovation
renovation_needed
major_renovation
dilapidated
unknown
```

`/buildability <ID> <value>` accepts:

```text
BUILDING_PERMIT
CONSTRUCTIONPLAN
NEIGHBOURCONSTRUCTION
EXTERNALAREA
NO_INFORMATION
```

The normal UI exposes these decisions through the Condition and property-detail
buttons. Manual choices take precedence over weaker automatic evidence.

## Municipal dog tax

`/hundesteuer` and its alias `/dogtax` open the guided research queue for the
current Top-10 houses/farms plus favorites. The same wizard is available as
`Hundesteuer prüfen` in house details. Send an official HTTPS ordinance link or
upload its PDF; Telegram asks only for fields the document and municipality
lookup could not determine and shows a preview before saving.
The task selection lists at most ten already filtered and deduplicated tasks and
reports the full task count when more remain.

The expert correction commands remain available:

```text
/dogtax_link ID | municipality-code | municipality-name | https://official-source
/dogtax_set municipality-code | municipality-name | YYYY-MM-DD | staffel/alle | annual-rates | https://official-ordinance | ordinance-version
```

See [dog-tax.md](dog-tax.md) for data semantics, municipal-code verification and
the nine-dog calculation.

## Blacklist and cleanup

| Command | Function |
| --- | --- |
| `/blacklist <term>` | Add a persistent case-insensitive blacklist term after validation. |
| `/purge` | Preview removal of obsolete records using the default age. |
| `/purge <days>` | Preview removal using a chosen age. |

Purge never deletes immediately from the command alone. Telegram first shows a
preview and requires the confirmation button.

## Property-card actions

Depending on property type and context, cards provide:

- `Koordinaten` to inspect, set or restore automatic location data;
- `Details` to show all known property and enrichment facts;
- `Zustand` for house/farm condition;
- `Erklärung` for score components, KOs and unresolved criteria;
- `Merken` / `Gemerkt` for the favorites list;
- `Offline` and `Kein Interesse`, both reversible;
- `Hundesteuer prüfen` in house/farm details;
- `Lage angefragt` on chance cards.

## Help

`/help` and `/start` return the complete compact in-app overview. Keep
`HELP_TEXT` in `app/telegram_commands.py` and this document synchronized whenever
a user-facing command, alias or important card action changes.
