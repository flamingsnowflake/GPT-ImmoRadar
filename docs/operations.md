# Operations

## Browser-enrichment token rotation

### Applying a scoring update

Preview existing records with `python app/rescore_current.py --db PATH --config-dir config`.
This performs no network requests and writes no database rows. To apply the result,
add `--apply --backup NEW_BACKUP_PATH`; an existing backup path is rejected.
The command preserves blacklisted/deleted/offline/uninterested listings and updates
scores in one transaction. Restart all score-producing processes after shared scoring
changes, using the service matrix below. Test Telegram Top-3, details and lab callbacks
after restart. `/dogtax` describes the half-automatic municipal tax workflow.

Run isolated tests from the repository root with `python -m pytest -q app`.
Install `pytest` alongside `requirements.txt` in a separate test environment.
The three legacy live-check scripts are excluded from collection because they
require external mail/geo services or a command-line mail fixture.

`config/browser_enrich_token` is the only token source. The server reads it on
every request. `BROWSER_ENRICH_TOKEN` in `.env` or the process environment has no
effect and must be removed. This token is separate from the Energy API token.

To rotate, write a newly generated random token to a temporary file in `config/`,
give it the same owner/group and restrictive permissions as the current token,
then atomically rename it to `browser_enrich_token`. Update the userscript's token
to the same value. No Compose recreation or service restart is required.

If the userscript receives `403 invalid token`, compare its configured token with
the canonical file, not `.env`. Do not put token values in logs, issues, screenshots,
or shell arguments/history. A missing/unreadable token file is a server configuration
error, not a reason to fall back to another source.

## Reference project root

```text
/opt/immobilien-monitor
```

Docker Compose commands on the reference server require `sudo`.

## Runtime services

Docker Compose:

```text
monitor
telegram-commands
property-browser
energy-api
```

Host systemd:

```text
immobilien-browser-enrich.service
```

The host service runs `app/browser_enrich_server.py` and updates the same host SQLite database that is bind-mounted into the Compose services.

## Restart matrix

### Telegram command/callback/Labor-only change

```bash
cd /opt/immobilien-monitor
sudo docker compose restart telegram-commands
```

An active Labor session is in RAM and is lost on restart. Reopen `/incomplete`; persisted property decisions are unaffected.

### Main monitor ingestion change

```bash
cd /opt/immobilien-monitor
sudo docker compose restart monitor
```

### Browser enrichment parser/server change

```bash
cd /opt/immobilien-monitor
sudo systemctl restart immobilien-browser-enrich.service
```

### Energy API-only change

```bash
cd /opt/immobilien-monitor
sudo docker compose restart energy-api
```

### Scoring/shared domain logic change

Several long-running processes import scoring/domain modules at process start. A bind-mounted source edit does not reload already imported Python modules.

After changing shared scoring behavior, restart every score-producing process:

```bash
cd /opt/immobilien-monitor

sudo docker compose restart \
    monitor \
    telegram-commands \
    energy-api

sudo systemctl restart \
    immobilien-browser-enrich.service
```

`property-browser` renders/fetches pages and normally does not need a restart for scoring-only changes.

## Browser enrichment service

Reference health/log commands:

```bash
sudo systemctl status \
    immobilien-browser-enrich.service \
    --no-pager

sudo journalctl \
    -u immobilien-browser-enrich.service \
    -f
```

The service should bind locally; expose it to the browser only through a controlled reverse proxy/authenticated endpoint. The browser request also carries `X-Browser-Enrich-Token`.

Reference application port:

```text
127.0.0.1:8765
```

A generic unit template is stored at:

```text
deploy/systemd/immobilien-browser-enrich.service.example
```

## Telegram logs

```bash
cd /opt/immobilien-monitor

sudo docker compose logs \
    -f \
    telegram-commands
```

Useful successful Labor messages include:

```text
ENERGY LAB AUTO ADVANCE: <old> -> <new|done>
CONDITION LAB AUTO ADVANCE: <old> -> <new|done>
```

Browser terminal behavior is visible in the host service log, for example `BROWSER TERMINAL ... | purged`.

## Syntax/test baseline

A useful regression set for the current browser/Labor flow is:

```bash
cd /opt/immobilien-monitor

python3 -m py_compile \
    app/browser_enrich_server.py \
    app/lab_terminal.py \
    app/incomplete_workflow.py \
    app/monitor.py \
    app/telegram_commands.py

sudo docker compose exec -T telegram-commands \
python -m unittest \
    test_lab_terminal.py \
    test_lab_queue_resilience.py \
    test_energy_lab_auto.py \
    test_incomplete_energy.py \
    test_browser_condition.py \
    test_browser_condition_hints.py \
    test_energy_consistency_fix.py
```

Run the tests that are relevant to a change; do not assume an old successful run covers later edits.

## Geo-precision migration

The Geo backfill is dry-run by default. It classifies existing rows, reports score changes and identifies locality-centre coordinates that would be removed without writing to SQLite:

```bash
cd /opt/immobilien-monitor

sudo docker compose run --rm monitor \
python backfill_geo_precision.py \
    --db /data/database.sqlite3 \
    --config-dir /config
```

Review the complete output before applying. The apply mode creates a consistent SQLite backup under `/data/backups/` before changing rows:

```bash
cd /opt/immobilien-monitor

sudo docker compose run --rm monitor \
python backfill_geo_precision.py \
    --db /data/database.sqlite3 \
    --config-dir /config \
    --apply
```

Do not run `--apply` while the normal score-producing services are writing. Stop those services first and restart the shared scoring process set afterward.

## Git safety

Before any pull/rebase:

```bash
git status --short
```

Never blindly pull over an unexplained dirty production tree.

Before commit/push:

```bash
git diff --check
git status --short
```

Stage explicit paths where practical and inspect:

```bash
git diff --cached --check
git diff --cached --stat
```

GitHub is durable source history; temporary patch/install files belong in `/tmp`, not as long-lived `.bak` files beside source.

## Database backups

Do not copy a live SQLite file with ordinary file-copy semantics while it is actively being written. Use SQLite's online backup API.

Example:

```bash
cd /opt/immobilien-monitor

python3 - <<'PY'
import sqlite3
from pathlib import Path

source_path = Path("data/database.sqlite3")
target_path = Path("/safe/backup/database.sqlite3")

target_path.parent.mkdir(
    parents=True,
    exist_ok=True,
)

source = sqlite3.connect(
    source_path,
    timeout=30,
)
target = sqlite3.connect(
    target_path,
)

source.backup(target)

target.close()
source.close()

print(target_path)
PY
```

For milestone checkpoints also consider a Git bundle:

```bash
git bundle create /safe/backup/GPT-ImmoRadar.bundle --all
```

Backups themselves stay outside the repository.

## Tampermonkey

The exact production 1.3.3 build is archived under `userscripts/archive/`. Tampermonkey stores the real API tokens in its own userscript storage; real tokens must never be added to the source archive or Git.

The production build uses deployment-specific endpoints. A public release must replace these with user configuration; see `docs/public-release.md`.

## Configuration and secrets

Never commit:

- `.env` with real values;
- `config/browser_enrich_token`;
- Telegram sessions/credentials;
- SQLite databases/WAL/journals;
- archived e-mail;
- browser enrichment inbox payloads;
- private keys;
- personal reverse-proxy certificates/credentials;
- production backups.

`.env.example` contains names/placeholders only.

## Public-release procedure

The historical production repository is not the public artifact. Export a sanitized history-free tree and scan it before creating/pushing the public repository.

See:

```text
docs/public-release.md
tools/export_public_snapshot.py
SECURITY.md
```
