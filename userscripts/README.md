# Browser userscript

The browser component is a Tampermonkey userscript used on supported real-estate exposé pages.

Public exports place the installable source at:

```text
userscripts/immobilien-energy.user.js
```

## What it does

The current userscript:

- supports ImmoScout24 and Immowelt exposé routes;
- notices SPA route changes;
- waits for rendered page content;
- pauses on CAPTCHA/security pages instead of trying to defeat them;
- expands Immowelt “Mehr Infos” when browser-only energy information is needed;
- closes only an Immowelt detail dialog that the script itself opened;
- extracts DOM-only ImmoScout24 energy-class hints;
- sends browser evidence to `/browser-enrich`;
- shows enrichment status in a small in-page panel;
- retains a separate manual Energy fallback.

See `../docs/browser-enrichment.md`.

## Configure your endpoint

The public userscript intentionally uses an invalid example hostname such as:

```text
monitor.example.invalid
```

Before using it, replace/configure that endpoint for your own HTTPS reverse proxy and make the Tampermonkey `@connect` permission match your host.

Do not point a fork at another operator's server.

## Tokens

The source contains token **storage keys**, not token values.

Real Energy/browser-enrichment tokens are entered at runtime and stored by Tampermonkey. Do not hard-code them into the userscript or commit them to Git.

## Human-assisted enrichment

The userscript is intentionally part of a human-in-the-loop workflow. The user opens a listing in a normal browser; the script reads the page that the browser has already rendered and submits evidence to the self-hosted enrichment service.

It is not intended as a CAPTCHA bypass or an access-control circumvention mechanism.
