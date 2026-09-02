# Installation (reference deployment)

This document describes the current reference architecture. A future public release should automate more of these steps, but keeping the dependencies explicit is useful for operators and contributors.

## Requirements

- Linux host (reference deployment: Ubuntu 24.04 LTS)
- Docker Engine + Docker Compose plugin
- Python 3 for the host browser-enrichment service
- SQLite
- a Telegram bot/chat
- an IMAP mailbox receiving property alerts
- optional reverse proxy/TLS endpoint for browser enrichment and Energy API
- Tampermonkey-compatible browser for browser-only enrichment

## Checkout

Recommended reference path:

```bash
sudo mkdir -p /opt/immobilien-monitor
sudo chown "$USER":"$USER" /opt/immobilien-monitor
cd /opt/immobilien-monitor
```

Clone/copy the source into that directory.

## Environment

Copy the example and fill only the local/private file:

```bash
cp .env.example .env
```

Never commit the filled `.env`.

At minimum the running stack needs the Telegram and IMAP configuration used by your deployment. Energy/browser tokens are separate secrets.

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

The token file is ignored by Git.

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

## Host browser enrichment service

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

The application binds to localhost on the reference port. Do not expose it directly without authentication/network controls.

## Reverse proxy

The production architecture maps an authenticated HTTPS route such as `/browser-enrich` to the localhost browser enrichment service.

Reverse-proxy implementation is intentionally not hard-coded in the project because hostnames/certificates/network topology are deployment-specific.

Keep these principles:

- TLS for remote browser access;
- only forward the required route;
- keep the upstream bound to localhost/private interface;
- require the browser-enrichment token at application level;
- avoid logging sensitive request bodies.

## Tampermonkey

Production deployments may archive the exact tested userscript privately for reproducibility. The public distribution contains a sanitized, portable copy.

Install the `.user.js` in Tampermonkey, configure your own endpoint(s), then enter the Energy/browser tokens when prompted. Token values are stored by Tampermonkey, not committed to source.

Do not use another operator's production endpoint.

## Nominatim identification

For a public/self-hosted deployment, configure a meaningful Nominatim User-Agent/contact according to the service policy. The public-export process converts the private hard-coded reference contact into `NOMINATIM_USER_AGENT` configuration.

Example:

```text
NOMINATIM_USER_AGENT=immobilien-monitor/1.0 (self-hosted; contact: contact@example.invalid)
```

Do not blindly copy someone else's contact identity.

## Data directories

SQLite/runtime data is expected under the project's `data/` directory and is bind-mounted into Compose containers.

Never commit `data/` or archived listing e-mail. Back it up separately using SQLite's backup API; see `operations.md`.

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

Then send/use `/incomplete` in Telegram and open a test exposé from the Labor to verify the browser-to-server flow.

## Security before Internet exposure

Read:

```text
SECURITY.md
docs/public-release.md
```

The project can reveal a great deal about a person's property search if deployed carelessly. Protect the database, logs, archived messages and browser payloads accordingly.
