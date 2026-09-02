#!/usr/bin/env python3

"""Create a history-free, privacy-sanitized public source snapshot.

Run this from a clean private production checkout. The destination is a new
ordinary directory; no .git history is copied. Review and scan the result
independently before publishing it.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

PUBLIC_TOP_LEVEL = {
    ".env.example",
    ".gitignore",
    "CONTRIBUTORS.md",
    "Dockerfile",
    "Dockerfile.browser",
    "LICENSE",
    "PROJECT.md",
    "README.md",
    "SECURITY.md",
    "docker-compose.yml",
    "requirements.txt",
}

PUBLIC_PREFIXES = (
    "app/",
    "config/",
    "deploy/",
    "docs/",
    "secrets/README.md",
    "tools/export_public_snapshot.py",
    "userscripts/",
)

EXCLUDE_PREFIXES = (
    "data/",
    "private/",
    "browser-enrich-inbox/",
    "backups/",
    "userscripts/archive/",
)

# Production search preferences remain private. Public example versions are
# copied into their canonical names after the tracked-source pass.
PRIVATE_CONFIG_PATHS = {
    "config/score.yaml",
    "config/blacklist.yaml",
}

TEXT_SUFFIXES = {
    ".css",
    ".env",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".py",
    ".service",
    ".sh",
    ".txt",
    ".yaml",
    ".yml",
}

EMAIL_RE = re.compile(
    r"(?<![A-Za-z0-9._%+-])"
    r"[A-Za-z0-9._%+-]+@"
    r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
)

SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{30,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\b"),
)

ASSIGNMENT_SECRET_RE = re.compile(
    r"(?im)^\s*"
    r"(?P<name>[A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|TOKEN|API_KEY)[A-Z0-9_]*)"
    r"\s*=\s*"
    r"(?P<value>[^#\r\n]+?)\s*$"
)


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def tracked_paths() -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
    )
    return [
        Path(item.decode("utf-8"))
        for item in output.split(b"\0")
        if item
    ]


def is_public_path(relative: Path) -> bool:
    value = relative.as_posix()

    if value in PRIVATE_CONFIG_PATHS:
        return False

    if any(
        value == prefix.rstrip("/")
        or value.startswith(prefix)
        for prefix in EXCLUDE_PREFIXES
    ):
        return False

    if value in PUBLIC_TOP_LEVEL:
        return True

    return any(
        value == prefix
        or value.startswith(prefix)
        for prefix in PUBLIC_PREFIXES
    )


def is_text(path: Path) -> bool:
    if path.name in {
        "Dockerfile",
        "Dockerfile.browser",
        ".gitignore",
        ".env.example",
    }:
        return True

    return path.suffix.lower() in TEXT_SUFFIXES


def sanitize_common_text(text: str) -> str:
    # Remove operator e-mail addresses from source/docs. Public examples get a
    # deliberately invalid RFC-reserved destination.
    text = EMAIL_RE.sub(
        "contact@example.invalid",
        text,
    )

    # Generic browser API endpoint rewrite; no private hostname is hard-coded
    # in this exporter.
    text = re.sub(
        r"https://[^\s\"']+/browser-enrich",
        "https://monitor.example.invalid/browser-enrich",
        text,
    )
    text = re.sub(
        r"https://[^\s\"']+/immobilien-energy/energy",
        "https://monitor.example.invalid/immobilien-energy/energy",
        text,
    )

    # Avoid publishing a personal Unix home name found in docs/scripts.
    text = re.sub(
        r"/home/[A-Za-z0-9._-]+",
        "/home/immomonitor",
        text,
    )

    return text


def sanitize_userscript(text: str) -> str:
    text = sanitize_common_text(text)

    text = re.sub(
        r"(?m)^// @namespace\s+\S+\s*$",
        "// @namespace    https://example.invalid/immoradar/",
        text,
    )
    text = re.sub(
        r"(?m)^// @connect\s+\S+\s*$",
        "// @connect      monitor.example.invalid",
        text,
    )

    return text


def sanitize_python(relative: Path, text: str) -> str:
    text = sanitize_common_text(text)

    if relative.as_posix() == "app/enrichment.py":
        if "import os\n" not in text:
            text = text.replace(
                "import math\n",
                "import math\nimport os\n",
                1,
            )

        text = re.sub(
            r"USER_AGENT\s*=\s*\(\s*"
            r"\"immobilien-monitor/1\.0 \"\s*"
            r"\"\([^\"]*\)\"\s*"
            r"\)",
            "USER_AGENT = os.environ.get(\n"
            "    \"NOMINATIM_USER_AGENT\",\n"
            "    \"immobilien-monitor/1.0 \"\n"
            "    \"(self-hosted; set NOMINATIM_USER_AGENT)\"\n"
            ")",
            text,
            count=1,
        )

    if relative.as_posix() == "app/browser_enrich_server.py":
        text = text.replace(
            'BASE_DIR = Path("/opt/immobilien-monitor")',
            'BASE_DIR = Path(\n'
            '    os.environ.get(\n'
            '        "IMMOBILIEN_MONITOR_ROOT",\n'
            '        "/opt/immobilien-monitor",\n'
            '    )\n'
            ')',
            1,
        )

    return text


def sanitize_text(relative: Path, text: str) -> str:
    if relative.suffix == ".py":
        return sanitize_python(
            relative,
            text,
        )

    if relative.suffix == ".js":
        return sanitize_userscript(text)

    return sanitize_common_text(text)


def copy_tracked_source(destination: Path) -> None:
    for relative in tracked_paths():
        if not is_public_path(relative):
            continue

        source = ROOT / relative
        target = destination / relative
        target.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        if is_text(relative):
            text = source.read_text(
                encoding="utf-8",
            )
            text = sanitize_text(
                relative,
                text,
            )
            target.write_text(
                text,
                encoding="utf-8",
            )
        else:
            shutil.copy2(
                source,
                target,
            )


def install_public_configs(destination: Path) -> None:
    mappings = {
        ROOT / "config" / "public" / "score.example.yaml":
            destination / "config" / "score.yaml",
        ROOT / "config" / "public" / "blacklist.example.yaml":
            destination / "config" / "blacklist.yaml",
    }

    for source, target in mappings.items():
        if not source.exists():
            raise RuntimeError(
                f"Public config example fehlt: {source}"
            )

        target.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        target.write_text(
            source.read_text(encoding="utf-8"),
            encoding="utf-8",
        )


def configured_private_strings() -> list[str]:
    raw = os.environ.get(
        "IMMORADAR_PRIVATE_STRINGS",
        "",
    )

    return [
        item.strip()
        for item in raw.split(",")
        if item.strip()
    ]


def assignment_looks_secret(name: str, value: str) -> bool:
    if name.endswith("_KEY"):
        return False

    cleaned = value.strip().strip("\"'")
    lower = cleaned.lower()

    safe_fragments = (
        "<set-on-server>",
        "example.invalid",
        "os.environ",
        "getenv(",
        "gm_getvalue",
        "energy_api_token",  # identifier/storage-key text is not a token value
        "browser_enrich_token",
    )

    if not cleaned:
        return False

    if any(
        fragment in lower
        for fragment in safe_fragments
    ):
        return False

    return len(cleaned) >= 8


def audit_text(relative: Path, text: str, failures: list[str]) -> None:
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            failures.append(
                f"{relative}: high-confidence secret pattern"
            )

    for match in ASSIGNMENT_SECRET_RE.finditer(text):
        if (
            relative.as_posix() == "tools/export_public_snapshot.py"
            and match.group("name") == "ASSIGNMENT_SECRET_RE"
        ):
            continue

        if assignment_looks_secret(
            match.group("name"),
            match.group("value"),
        ):
            failures.append(
                f"{relative}: possible secret assignment "
                f"({match.group('name')})"
            )

    for email in EMAIL_RE.findall(text):
        if email.lower() != "contact@example.invalid":
            failures.append(
                f"{relative}: unexpected e-mail address"
            )

    if re.search(
        r"/home/(?!immomonitor(?:/|\b))[A-Za-z0-9._-]+",
        text,
    ):
        failures.append(
            f"{relative}: personal /home path"
        )

    for private_value in configured_private_strings():
        if private_value.casefold() in text.casefold():
            failures.append(
                f"{relative}: configured private string remains"
            )


def audit_snapshot(destination: Path) -> None:
    failures: list[str] = []

    forbidden_suffixes = {
        ".db",
        ".db3",
        ".eml",
        ".pbf",
        ".session",
        ".sqlite",
        ".sqlite3",
    }

    for path in destination.rglob("*"):
        if not path.is_file():
            continue

        relative = path.relative_to(
            destination
        )

        if path.suffix.lower() in forbidden_suffixes:
            failures.append(
                f"{relative}: forbidden runtime/binary data type"
            )
            continue

        if not is_text(relative):
            continue

        try:
            text = path.read_text(
                encoding="utf-8",
            )
        except UnicodeDecodeError:
            failures.append(
                f"{relative}: unexpected non-UTF8 file"
            )
            continue

        audit_text(
            relative,
            text,
            failures,
        )

    if failures:
        message = "\n".join(
            f"  - {item}"
            for item in sorted(set(failures))
        )
        raise RuntimeError(
            "Public-Snapshot-Audit fehlgeschlagen:\n"
            + message
        )


def write_manifest(destination: Path) -> None:
    commit = git(
        "rev-parse",
        "HEAD",
    )

    now = datetime.now(
        timezone.utc
    ).isoformat()

    content = f"""# Public export manifest

Generated from private production commit:

```text
{commit}
```

Generated at:

```text
{now}
```

This directory intentionally contains **no Git history** from the private production repository.

Production `score.yaml` and `blacklist.yaml` are not exported; generic public examples are installed instead.

Before publication, run an independent secret scanner and manual review as described in `docs/public-release.md`.
"""

    (destination / "PUBLIC_EXPORT_MANIFEST.md").write_text(
        content,
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "destination",
        type=Path,
        help="new/empty directory for sanitized public snapshot",
    )
    args = parser.parse_args()

    destination = args.destination.expanduser().resolve()

    if ROOT == destination or ROOT in destination.parents:
        raise SystemExit(
            "Destination darf nicht innerhalb des privaten Repositories liegen."
        )

    if destination.exists() and any(destination.iterdir()):
        raise SystemExit(
            f"Destination ist nicht leer: {destination}"
        )

    status = git(
        "status",
        "--porcelain",
        "--",
        ".",
        ":(exclude)data/**",
        ":(exclude)private/**",
        ":(exclude)browser-enrich-inbox/**",
        ":(exclude)backups/**",
        ":(exclude)userscripts/archive/**",
    )
    if status:
        raise SystemExit(
            "Privates Working Tree ist nicht sauber; Export abgebrochen."
        )

    destination.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:
        copy_tracked_source(destination)
        install_public_configs(destination)
        write_manifest(destination)
        audit_snapshot(destination)
    except Exception:
        shutil.rmtree(
            destination,
            ignore_errors=True,
        )
        raise

    print(
        "✅ Public snapshot erstellt und Basis-Audit bestanden:"
    )
    print(destination)
    print()
    print(
        "Nächster Schritt: unabhängiger Secret-Scanner + manuelle Prüfung."
    )


if __name__ == "__main__":
    main()
