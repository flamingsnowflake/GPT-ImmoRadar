# Browser Enrichment

## Why it exists

Some useful real-estate data is only reliably visible in the rendered browser page. Server-side HTTP fetches may receive reduced markup, anti-bot responses, or text that omits DOM-only information such as an energy-efficiency class represented by an image/SVG.

GPT-ImmoRadar therefore uses the operator's normal browser as an evidence source while keeping canonical parsing and persistence on the server.

The browser is not asked to decide the final score. It sends the rendered evidence; Python modules normalize that evidence, protect higher-precedence manual data and rescore the property.

## End-to-end flow

```text
Telegram Labor/property card
        │
        │ open normal portal link
        ▼
ImmoScout24 / Immowelt exposé
        │
        ▼
Tampermonkey userscript
        │
        ├─ route/portal ID
        ├─ rendered page text
        ├─ H1/document title
        ├─ JSON-LD
        └─ DOM-only energy class hint
        │
        ▼
POST /browser-enrich
X-Browser-Enrich-Token: ...
        │
        ▼
reverse proxy / local service
        │
        ▼
app/browser_enrich_server.py
        │
        ├─ blacklist-relevant text scope
        ├─ portal fact normalization
        ├─ app/browser_energy.py
        ├─ app/browser_condition.py
        ├─ app/lab_terminal.py
        └─ scoring
        │
        ▼
SQLite
        │
        ▼
Telegram active Labor notices resolution
```

## Tampermonkey production build

Name:

```text
Immobilienmonitor – Browser & Energie
```

Production version:

```text
1.3.3
```

Canonical production archive:

```text
userscripts/archive/Immobilienmonitor-Browser-Energie-1.3.3.zip
```

The archive contains the exact `.user.js` that was tested in production. It contains deployment-specific endpoint hostnames but **no API token values**; tokens are requested at runtime and stored in Tampermonkey userscript storage.

### Browser behavior

The userscript:

1. identifies portal and portal ID from the exposé route;
2. handles SPA route changes so a previous property's content is not sent under a new ID;
3. waits for sufficiently rendered page text;
4. pauses on CAPTCHA/security-check pages rather than treating them as listing content;
5. on Immowelt, opens “Mehr Infos” when needed so hidden energy fields become visible;
6. records whether it opened that energy detail UI and in v1.3.1 closes only a dialog it opened itself;
7. extracts ImmoScout24's DOM-only energy-class hint when present;
8. sends page evidence to `/browser-enrich`;
9. renders a small status panel in the page;
10. retains an explicit “Energy fallback” path to the separate Energy API;
11. positions the panel above Immowelt's native contact bar on mobile viewports and includes the device safe area.

### Why Python remains canonical

The userscript deliberately does not become a second independent scoring implementation. Browser-specific extraction can change with portal UI; normalization and scoring rules should be testable in Python.

For Energy, the server uses:

```text
app/browser_energy.py
app/energy_data.py
```

For explicit Condition:

```text
app/browser_condition.py
app/browser_condition_hints.py
```

## Host service

The reference deployment runs `app/browser_enrich_server.py` through:

```text
immobilien-browser-enrich.service
```

Reference application bind:

```text
127.0.0.1:8765
```

The service expects a token file outside Git and updates the host database under the project data directory. A generic systemd template is provided under `deploy/systemd/`.

The externally visible `/browser-enrich` URL belongs to the operator's reverse-proxy configuration and is intentionally deployment-specific.

## Payload

The unified browser payload contains fields equivalent to:

```json
{
  "portal": "immoscout24 | immowelt",
  "portal_id": "...",
  "url": "...",
  "document_title": "...",
  "heading": "...",
  "page_text": "...",
  "energy_class_dom": "A+..H | null",
  "json_ld": ["..."],
  "browser_timestamp": "..."
}
```

The body is authenticated separately from the Energy fallback API.

## Database result statuses

Typical browser-enrichment result states include:

```text
enriched
rescored
blacklisted
unblacklisted
purged
not_found
```

The userscript should treat the response as status/reporting information; SQLite remains authoritative.

## Energy

Browser inspection can provide:

- efficiency class;
- numeric end-energy value;
- demand/consumption certificate type;
- certificate availability status;
- heating type;
- energy source;
- energy construction year;
- raw supporting text.

When the rendered page was genuinely inspected but contains no usable energy information, the application may record a checked `unknown` outcome according to the configured risk policy. `not_available_yet` is different: it stays unresolved.

Manual/final Energy values are protected from weaker automatic updates.

## Condition

Only explicit labelled portal fields are automatically classified. This avoids turning marketing phrases in a description into a false structural assessment.

Example evidence shapes:

```text
Objektzustand
Renovierungsbedürftig
```

or:

```text
Zustand der Immobilie: Gepflegt
```

If a portal exposes raw condition text that cannot be mapped decisively, the hint can still be shown in the Labor for human review.

## Blacklist

Browser blacklist evaluation is powerful because it sees the rendered listing, but the rendered page also contains navigation/recommendations. Portal-specific text scoping removes known unrelated sections before blacklist matching.

A browser blacklist event marks the property as blacklisted and records a terminal event for active Labor handling.

## Removed listings / purge

`app/lab_terminal.py` recognizes explicit portal language that a listing has been removed/unavailable.

Tested examples include the respective deleted-ad/not-found pages of Immowelt and ImmoScout24.

Safety rule:

```text
explicit portal removal evidence -> purge allowed
network error / timeout / CAPTCHA -> purge NOT allowed
```

Purge cleanup removes the property and associated local search/favorite/user-status references and then records `browser_terminal_events.status = purged`.

The terminal table exists specifically because after deletion there is no property row left for the active Telegram Labor to observe.

## Labor auto-advance

When Energy or Condition Labor is active, `telegram-commands` shortens its polling interval and re-queries the relevant queue. It also checks terminal events for the active portal ID.

That allows all of these to advance the same Telegram card:

```text
condition becomes known
energy becomes complete
blacklisted
offline / not interested
physical delete
browser purge
```

## Security model

- Browser-enrichment token is not committed.
- Tampermonkey stores token values in its own userscript storage.
- Host service binds locally in the reference deployment.
- Internet exposure should be through a controlled reverse proxy.
- Browser captures/inbox payloads are runtime data and ignored by Git.
- Public releases must not hardcode an operator-specific production endpoint.

## Public version

An operator may retain the exact tested userscript archive privately for reproducibility. The public distribution uses a portable userscript with configurable endpoint(s), so forks do not accidentally send their property pages to another operator's server.

See `docs/public-release.md`.
