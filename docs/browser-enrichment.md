# Browser Enrichment

## Why it exists

Some useful real-estate data is only reliably visible after a listing page has been rendered in a normal browser. Server-side fetches may receive reduced markup, security/challenge pages, or text that omits DOM-only information such as an energy-efficiency class represented by an image or SVG.

GPT-ImmoRadar therefore uses the user's normal browser as an evidence source while keeping canonical parsing, persistence and scoring on the server.

The browser is not asked to decide the final score. It submits rendered evidence; Python modules normalize that evidence, protect higher-precedence manual values and rescore the property.

## End-to-end flow

```text
Telegram Labor/property card
        |
        | open normal portal link
        v
ImmoScout24 / Immowelt exposé
        |
        v
Tampermonkey userscript
        |
        +-- route / portal ID
        +-- rendered page text
        +-- heading / document title
        +-- JSON-LD
        +-- DOM-only energy hint
        |
        v
HTTPS POST /browser-enrich
X-Browser-Enrich-Token: ...
        |
        v
HTTPS reverse proxy
        |
        v
127.0.0.1:8765/enrich
        |
        v
app/browser_enrich_server.py
        |
        +-- blacklist-relevant text scope
        +-- portal fact normalization
        +-- app/browser_energy.py
        +-- app/browser_condition.py
        +-- app/lab_terminal.py
        +-- scoring
        |
        v
SQLite
        |
        v
Telegram active Labor notices resolution
```

## Browser behavior

The userscript:

1. identifies portal and portal ID from the exposé route;
2. handles SPA route changes so one property's content is not sent under another ID;
3. waits for sufficiently rendered page text;
4. pauses on CAPTCHA/security-check pages rather than treating them as listing content;
5. on Immowelt, opens “Mehr Infos” when needed so hidden energy fields become visible;
6. closes only a detail dialog that the script itself opened;
7. extracts DOM-only energy-class hints when present;
8. sends page evidence to `/browser-enrich`;
9. renders a small status panel in the page;
10. retains an explicit manual Energy fallback path.

The public userscript is stored at:

```text
userscripts/immobilien-energy.user.js
```

Its endpoint is intentionally neutralized in the public export. Configure your own HTTPS host and matching Tampermonkey `@connect` permission before use.

## Why Python remains canonical

The userscript deliberately does not become a second scoring implementation. Portal UI extraction can change; normalization and scoring rules should remain testable and explainable on the server.

Energy parsing lives primarily in:

```text
app/browser_energy.py
app/energy_data.py
```

Explicit condition parsing lives primarily in:

```text
app/browser_condition.py
app/browser_condition_hints.py
```

## Host service

The reference architecture runs:

```text
app/browser_enrich_server.py
```

through:

```text
immobilien-browser-enrich.service
```

Reference listener:

```text
127.0.0.1:8765
```

A reusable unit template is provided under:

```text
deploy/systemd/immobilien-browser-enrich.service.example
```

## HTTPS ingress

The browser should not connect directly to an unauthenticated Internet-facing port 8765.

Recommended external route:

```text
/browser-enrich
```

Recommended internal route:

```text
http://127.0.0.1:8765/enrich
```

The manual/fallback Energy API can be exposed separately:

```text
/immobilien-energy/energy
    -> http://127.0.0.1:8090/energy
```

See `docs/apache-reverse-proxy.md` for a generic Apache example and the security principles that apply to any reverse proxy.

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

The browser-enrichment route uses its own shared token.

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

The userscript treats the response as status/reporting information; SQLite remains authoritative.

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

When the rendered page was genuinely inspected but contains no usable energy information, the application may record a checked `unknown` outcome according to the configured policy. `not_available_yet` remains unresolved.

Manual/final Energy values are protected from weaker automatic updates.

## Condition

Only explicit labelled portal fields are automatically classified. This avoids turning marketing language into a false structural assessment.

Example evidence shapes:

```text
Objektzustand
Renovierungsbedürftig
```

or:

```text
Zustand der Immobilie: Gepflegt
```

If raw condition text cannot be mapped decisively, it can still be surfaced for human review.

## Blacklist and removed listings

Browser blacklist evaluation is useful because it sees the rendered listing, but rendered pages also contain navigation/recommendations. Portal-specific text scoping helps prevent unrelated UI text from becoming evidence.

`app/lab_terminal.py` also recognizes explicit portal language that a listing has been removed or is unavailable.

Safety rule:

```text
explicit portal removal evidence -> purge allowed
network error / timeout / CAPTCHA -> purge NOT allowed
```

A terminal event allows an active Telegram Labor to observe that a property disappeared after deletion and advance to the next item.

## Human-assisted, not access-control bypass

The intended flow is deliberately simple:

```text
user opens page normally
        -> browser renders what the user can access
        -> userscript extracts evidence from that rendered page
```

The project is not intended to defeat CAPTCHA, authentication or other access controls.

## Security model

- Browser-enrichment token values are not committed.
- Tampermonkey stores user-entered token values in userscript storage.
- The host service should bind locally/private by default.
- Remote browser traffic should use HTTPS.
- Browser captures and inbox payloads are private runtime data and belong outside Git.
- TLS private keys remain outside Git.
