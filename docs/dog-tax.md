# Municipal dog tax

Dog tax is a supplemental annual/monthly cost indication for nine ordinary dogs.
It never changes the property score, budget KO, or ranking. No dangerous-dog
surcharge or exemption is assumed.

`/dogtax` (alias `/hundesteuer`) builds a research queue from the current Top-10
houses plus favorites. Properties are deduplicated across both lists and municipal
tariff research is deduplicated by the confirmed eight-digit municipality code.
Other properties do not open research tasks. Their details may show an already
stored tariff once their municipality is confirmed.

The normal Telegram path is guided. Open a house's details and select
`🐕 Hundesteuer prüfen`, or use `/hundesteuer` to see the open Top-10/favorite
queue. Send an official HTTPS ordinance link or upload its PDF. The bot resolves
the municipality from the property's coordinates, verifies the eight-digit code
against the official municipality directory, extracts readable rates and dates,
and asks one simple question for every field it could not determine. A district,
state, postcode, or similarly named village is not treated as a municipality.

Before writing anything, Telegram shows the municipality, code, tier model,
calculation for nine normal dogs, validity, document version, page/section hint,
and both sources. `Bestätigen` saves it, `Quelle korrigieren` reopens document
input, and `Für jetzt überspringen` closes the task without a database change.
An uploaded scan without usable text remains open and asks for a readable version.

## Expert fallback commands

The old commands remain available for corrections and diagnostics. They are not
required for the normal workflow.

```
/dogtax_link ID | municipality-code | municipality-name | https://official-source
/dogtax_set municipality-code | municipality-name | YYYY-MM-DD | staffel | 48;80;105 | https://official-ordinance | ordinance-version
```

The amounts above are illustrative annual euro rates, not a default tariff.
Use decimal commas for cents. The last rate repeats for all remaining dogs.
`staffel` applies each rate to its dog position; `alle` applies the rate selected
by total dog count to every dog. Those models differ materially, so confirm the
ordinance wording. A `?` validity date is displayed as not specified, never invented.
Future-dated tariffs do not apply early. The retrieval date is saved separately.

Confirmed assignments and tariffs live in separate SQLite tables. A tariff is
shared by all present and future properties assigned to that municipality.
Changes of property location/coordinates invalidate the assignment until reviewed.
Purging a property removes its assignment; the municipality tariff remains useful.
Unknown assignments/rates show `unbekannt`, never zero euros.

Details show the nine-dog annual total, rounded monthly amount, tier model/rates,
validity date, ordinance version, checked date, and source link.
