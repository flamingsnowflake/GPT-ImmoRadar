# Browser userscript

The browser component is a Tampermonkey userscript used on supported real-estate exposé pages.

## Canonical private production build

```text
Immobilienmonitor – Browser & Energie
version 1.3.1
```

Readable source:

```text
immobilien-energy.user.js
```

Exact generated archive:

```text
archive/Immobilienmonitor-Browser-Energie-1.3.1.zip
```

The readable source and the `.user.js` inside the archive are byte-identical. Git blob SHA of the production source:

```text
8f579d64f18e0d01f7bf1d980aad359a570f5053
```

SHA-256 of the `.user.js`:

```text
3c4bb32f5b00229c12713ae8f51afd9684eb7fd3eea2749f8823f4e92dfd1b5c
```

The previous v0.2.0 file at this path predated the unified browser enrichment architecture and has been replaced by the exact production 1.3.1 source.

## What 1.3.1 does

- supports ImmoScout24 and Immowelt exposé routes;
- notices SPA route changes;
- waits for rendered page content;
- pauses on CAPTCHA/security pages;
- expands Immowelt “Mehr Infos” for browser-only energy information;
- closes only an Immowelt detail dialog that the script itself opened;
- extracts DOM-only ImmoScout24 energy-class hints;
- sends browser evidence to `/browser-enrich`;
- shows enrichment status in a small in-page panel;
- retains a separate manual Energy fallback.

See `../docs/browser-enrichment.md`.

## Tokens

The source contains token **storage keys**, not production token values. Real tokens are entered at runtime and held in Tampermonkey userscript storage.

## Public release

The exact private production build contains deployment-specific endpoint hostnames. Do not publish/use it as the default public installer without sanitizing/configuring those endpoints.

`tools/export_public_snapshot.py` generates the public snapshot from this canonical source and neutralizes the deployment endpoint. See `../docs/public-release.md`.
