# Security and Privacy

GPT-ImmoRadar processes information that can become sensitive in a real deployment: e-mail credentials, Telegram credentials, viewed property pages, exact addresses/coordinates and a database that reflects a person's housing search.

Security and privacy are therefore deployment requirements, not optional cleanup.

## Never commit production secrets/data

Keep these outside Git:

```text
.env with real values
config/browser_enrich_token
private/
real secret files
Telegram *.session
SQLite databases and WAL/journal files
archived e-mail
browser-enrich-inbox payloads
private keys/certificates
production backups
```

The repository `.gitignore` is a safety net, not permission to stop checking staged changes.

## Browser enrichment

The reference browser enrichment service binds to localhost. If exposed to a browser over the network, place it behind the operator's controlled reverse proxy and require the browser-enrichment token.

The Tampermonkey userscript stores token values in its userscript storage; tokens are not supposed to be embedded in source.

A public userscript must never ship with the original operator's production endpoint as a usable default.

## Removed-listing safety

Automatic purge is intentionally conservative. A property is deleted only when the rendered portal page gives explicit evidence that the listing was removed/unavailable. Transport errors, CAPTCHA/security checks and timeouts do not authorize deletion.

## Public repository

The historical production Git repository should remain private. A public release should be a new, history-free sanitized snapshot; see `docs/public-release.md`.

Before first publication, rotate any credential that has appeared in terminal/debug output, even if an audit suggests it never entered Git history.

## Reporting a vulnerability

For a future public repository, avoid posting live credentials, private listing captures or personal data in public issues.

A maintainer should provide a private reporting route before enabling broad public use. Until such a route exists, disclose only the minimum non-sensitive reproduction information necessary to describe a problem.

## Dependency / operational notes

- Keep the host OS, Docker images and Python dependencies patched.
- Do not expose SQLite, Telegram sessions or internal service ports directly to the Internet.
- Treat reverse-proxy logs and browser-enrichment inbox captures as private runtime data.
- Back up the SQLite database using SQLite's backup API rather than copying an actively written DB file.
- Review portal terms and legal obligations for the deployment location.
