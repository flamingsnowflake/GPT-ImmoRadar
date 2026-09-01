# Secrets

Real secrets do **not** belong in this repository.

Recommended server layout:

```text
/opt/immobilien-monitor/.env
/opt/immobilien-monitor/secrets/
```

Recommended permissions:

```bash
chmod 700 /opt/immobilien-monitor/secrets
chmod 600 /opt/immobilien-monitor/.env
chmod 600 /opt/immobilien-monitor/secrets/*
```

Examples of data that must remain outside Git:

- Telegram bot token
- IMAP password
- browser/enrichment API tokens
- private keys
- passwords
- bearer tokens
- signed/private URLs containing credentials

The repository may contain only the **names** of required secret variables, for example in `.env.example`.

For disaster recovery, keep an encrypted copy of secrets in a password manager or encrypted backup location. Do not rely on GitHub for secret storage.
