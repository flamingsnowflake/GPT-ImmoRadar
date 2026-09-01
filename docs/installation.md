# Installation

This document describes the reference self-hosted architecture. It is intentionally explicit about the moving parts so a fork can adapt them to a different server, reverse proxy or property-search workflow.

## Requirements

- Linux host (reference development environment: Ubuntu 24.04 LTS)
- Docker Engine + Docker Compose plugin
- Python 3 for the host browser-enrichment service
- SQLite
- a Telegram bot/chat
- an IMAP mailbox receiving property alerts
- optional HTTPS reverse proxy for browser enrichment and the Energy API
- Tampermonkey-compatible browser for browser-only enrichment

## Checkout

A convenient reference path is:

```bash
sudo mkdir -p /opt/immobilien-monitor
sudo chown "$USER":"$USER" /opt/immobilien-monitor
cd /opt/immobilien-monitor
```

Clone the public repository into that directory or adjust the paths in your deployment accordingly.

## Environment

Copy the example and fill only the local/private file:

```bash
cp .env.example .env
```

Never commit the filled `.env`.

At minimum, configure the Telegram bot and IMAP mailbox used by your installation.

## Browser enrichment token

Create a strong random token outside Git, for example:

```bash
mkdir -p config
umask 077
python3 - <<'PY' > config/browser_enrich_token
import secrets
print(secrets.token_urlsafe(48))
PY
```

The real token file is runtime secret material and should remain ignored by Git.

## Docker services

Build/start:

```bash
sudo docker compose up -d --build
```

Check:

```bash
sudo docker compose ps
```

Reference services:

```text
monitor
telegram-commands
property-browser
energy-api
```

## Host browser-enrichment service

Copy/customize the generic unit:

```bash
sudo cp \
    deploy/systemd/immobilien-browser-enrich.service.example \
    /etc/systemd/system/immobilien-browser-enrich.service
```

The example uses a dedicated `immomonitor` account. Either create that account and grant the project/data permissions it needs, or deliberately adjust `User`/`Group` for your deployment.

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now \
    immobilien-browser-enrich.service
```

Check:

```bash
sudo systemctl status \
    immobilien-browser-enrich.service \
    --no-pager
```

Keep the application listener on localhost or another trusted/private interface.

## Reverse proxy

For browser enrichment from another machine, put an HTTPS reverse proxy in front of the local application listener.

A generic Apache example is included at:

```text
deploy/apache/immoradar.example.conf
```

The important principles are:

- TLS for remote browser access;
- expose only the required routes;
- keep upstream services on localhost/private interfaces;
- retain application-token authentication;
- avoid logging sensitive request bodies.

See `docs/apache-reverse-proxy.md`.

## Tampermonkey

Install:

```text
userscripts/immobilien-energy.user.js
```

The public userscript deliberately points at an invalid example hostname. Configure your own HTTPS endpoint and matching `@connect` permission before use, then enter your Energy/browser tokens when prompted.

Token values are stored by Tampermonkey at runtime; do not hard-code them into the repository.

## Nominatim identification

Configure a meaningful Nominatim User-Agent/contact according to the service policy.

Example only:

```text
NOMINATIM_USER_AGENT=immobilien-monitor/1.0 (self-hosted; contact: contact@example.invalid)
```

Use your own contact identity rather than copying another operator's value.

## Data directories

SQLite/runtime data is expected under the project's `data/` directory and is bind-mounted into Compose containers.

Never commit populated databases, archived listing mail or browser payloads. Back them up separately; see `docs/operations.md`.

## Verify

After configuration:

```bash
sudo docker compose logs --tail=50 monitor
sudo docker compose logs --tail=50 telegram-commands
sudo journalctl \
    -u immobilien-browser-enrich.service \
    --since="5 minutes ago" \
    --no-pager
```

Then use the Telegram review workflow and open a test exposé in your configured browser to verify the browser-to-server flow.

## Adapt the search

The reference score reflects one rural house/land search. It is not intended as a universal property ranking.

Before using the score for your own search, read:

```text
docs/scoring.md
docs/customizing-your-search.md
```

For example, an urban fork may remove water/isolation priorities and instead add public-transport access, service frequency or commute time.

## Security before Internet exposure

Read:

```text
SECURITY.md
docs/public-release.md
```

A property-search database can reveal addresses, preferences and personal search history. Protect the database, logs, archived messages and browser payloads accordingly.
