# Operations

This document describes the reference self-hosted runtime after a public installation. Adjust paths, service users and reverse-proxy details for your own host.

## Reference project root

```text
/opt/immobilien-monitor
```

## Runtime services

Docker Compose:

```text
monitor
telegram-commands
property-browser
energy-api
```

Host service:

```text
immobilien-browser-enrich.service
```

An HTTPS reverse proxy is recommended when browser enrichment is accessed from another machine. The application listeners themselves should remain on localhost or another trusted/private interface.

## Restart matrix

Telegram command/callback/Labor change:

```bash
cd /opt/immobilien-monitor
sudo docker compose restart telegram-commands
```

Main ingestion change:

```bash
cd /opt/immobilien-monitor
sudo docker compose restart monitor
```

Browser enrichment parser/server change:

```bash
sudo systemctl restart immobilien-browser-enrich.service
```

Energy API-only change:

```bash
cd /opt/immobilien-monitor
sudo docker compose restart energy-api
```

Scoring/shared domain logic is imported by several long-running processes. After changing shared scoring behavior, restart every score-producing process:

```bash
cd /opt/immobilien-monitor

sudo docker compose restart \
    monitor \
    telegram-commands \
    energy-api

sudo systemctl restart \
    immobilien-browser-enrich.service
```

`property-browser` normally does not need a restart for scoring-only changes.

## Browser enrichment service

Useful commands:

```bash
sudo systemctl status \
    immobilien-browser-enrich.service \
    --no-pager

sudo journalctl \
    -u immobilien-browser-enrich.service \
    -f
```

Reference application listener:

```text
127.0.0.1:8765
```

A generic systemd unit is provided under:

```text
deploy/systemd/immobilien-browser-enrich.service.example
```

## Browser-facing routes

The reference architecture uses two HTTPS routes:

```text
/browser-enrich
    -> http://127.0.0.1:8765/enrich

/immobilien-energy/energy
    -> http://127.0.0.1:8090/energy
```

Keep the upstream services private, use TLS for remote browser access, and do not expose unrelated application paths.

## Telegram logs

```bash
cd /opt/immobilien-monitor
sudo docker compose logs -f telegram-commands
```

## Basic syntax checks

```bash
cd /opt/immobilien-monitor

python3 -m py_compile \
    app/browser_enrich_server.py \
    app/lab_terminal.py \
    app/incomplete_workflow.py \
    app/monitor.py \
    app/telegram_commands.py
```

The private development history contains a larger production-derived regression suite. Public tests should use synthetic fixtures rather than publishing a user's real listing history.

## Git safety

Before pulling or rebasing a deployed checkout:

```bash
git status --short
```

Before committing:

```bash
git diff --check
git status --short
```

## Database backups

Do not copy an actively-written SQLite database with ordinary file-copy semantics. Use SQLite's online backup API.

Example:

```bash
cd /opt/immobilien-monitor

python3 - <<'PY'
import sqlite3
from pathlib import Path

source_path = Path("data/database.sqlite3")
target_path = Path("/safe/backup/database.sqlite3")

target_path.parent.mkdir(parents=True, exist_ok=True)

source = sqlite3.connect(source_path, timeout=30)
target = sqlite3.connect(target_path)
source.backup(target)
target.close()
source.close()

print(target_path)
PY
```

Backups belong outside the repository.

## Configuration and secrets

Never commit real values for:

- `.env`;
- `config/browser_enrich_token`;
- Telegram/Telethon sessions or credentials;
- SQLite databases/WAL/journals;
- archived property e-mail;
- browser-enrichment payloads;
- TLS or SSH private keys;
- production backups.

`.env.example` contains placeholders only.

See `SECURITY.md` and `docs/installation.md` before exposing any endpoint to the Internet.
