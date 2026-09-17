#!/usr/bin/env python3

"""Create a history-free, privacy-sanitized public source snapshot.

Run this from the private production checkout. Runtime-only paths may be dirty,
but publishable tracked source must be clean. The destination is a fresh ordinary
directory; no .git history is copied. Review and scan the result independently
before publishing it.
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

# These normal public-facing documents must read from the public distribution's
# point of view. docs/public-release.md is deliberately NOT listed: that file is
# allowed to explain that a private production repository is the source from
# which a sanitized public snapshot is created.
PUBLIC_PERSPECTIVE_PATHS = {
    "README.md",
    "PROJECT.md",
    "docs/architecture.md",
    "docs/browser-enrichment.md",
    "docs/current-state.md",
    "docs/decisions.md",
    "docs/installation.md",
    "docs/scoring.md",
    "docs/workflows.md",
}

PUBLIC_PERSPECTIVE_FORBIDDEN_RE = re.compile(
    r"(?i)(?:"
    r"private production|"
    r"private repository|"
    r"production source of truth|"
    r"current private|"
    r"public snapshot.{0,40}\blag|"
    r"private-production"
    r")"
)

PUBLIC_DOCUMENT_REPLACEMENTS: dict[str, tuple[tuple[str, str], ...]] = {
    "README.md": (
        (
            "> **Private production repository:** this repository is the source of truth "
            "for the currently deployed system. The public snapshot is intentionally "
            "sanitized and may lag behind production features and scoring semantics. "
            "For the exact current behavior, start with `docs/current-state.md`, "
            "`docs/scoring.md`, `docs/workflows.md` and the complete "
            "`docs/telegram.md` command reference.\n\n",
            "",
        ),
        (
            "For houses/farms, the current private base model is:",
            "For houses/farms, the reference base model is:",
        ),
        (
            "Current class adjustments are:",
            "Reference class adjustments are:",
        ),
        (
            "the production scorer can use",
            "the scorer can use",
        ),
        (
            "full current semantics and production values",
            "full reference semantics and values",
        ),
        (
            "The current private scoring reflects one real-world search",
            "The included reference scoring reflects one real-world search",
        ),
        (
            "For the current implementation, see `docs/scoring.md`",
            "For the reference implementation, see `docs/scoring.md`",
        ),
        (
            "The private production documentation lives under `docs/`:",
            "Documentation lives under `docs/`:",
        ),
    ),
    "PROJECT.md": (
        (
            "This repository is the durable source of truth for the private production "
            "history and current production behavior of GPT-ImmoRadar. The public "
            "repository is a sanitized distribution snapshot and may intentionally lag "
            "behind private scoring/workflow changes.",
            "This repository is the public distribution of GPT-ImmoRadar. It contains "
            "sanitized source code, reference configuration and documentation for "
            "self-hosting and adaptation.",
        ),
        (
            "## Public-release policy\n\n"
            "Do not make this historical production repository public in-place.\n\n"
            "A public release must be created from a newly generated, history-free "
            "snapshot after privacy and secret checks. Production endpoints, personal "
            "contact data and machine-specific details must be replaced with "
            "configuration/examples.\n\n"
            "See `docs/public-release.md`.",
            "## Release provenance\n\n"
            "This public repository is generated from a sanitized, history-free "
            "snapshot of the development and production source. Secrets, runtime data, "
            "production endpoints, personal contact data and machine-specific details "
            "are intentionally excluded or replaced with examples.\n\n"
            "See `docs/public-release.md` for the publication model.",
        ),
        (
            "- `README.md` — project overview and private-production entry point",
            "- `README.md` — project overview and getting-started entry point",
        ),
    ),
    "docs/installation.md": (
        (
            "The private production repo archives the exact tested 1.3.3 userscript. "
            "Public exports generate a sanitized copy.",
            "Production deployments may archive the exact tested userscript privately "
            "for reproducibility. The public distribution contains a sanitized, "
            "portable copy.",
        ),
    ),
    "docs/scoring.md": (
        (
            "This document describes the **private production scoring model**. The "
            "authoritative implementation is `app/scoring.py` together with "
            "`config/score.yaml`; the public repository may intentionally lag behind "
            "this state.",
            "This document describes the **reference scoring model** shipped with this "
            "release. The implementation is `app/scoring.py` together with "
            "`config/score.yaml`.",
        ),
        (
            "The current private house/farm hard filters include:",
            "The reference house/farm hard filters include:",
        ),
    ),
    "docs/browser-enrichment.md": (
        (
            "Canonical private-production archive:",
            "Canonical production archive:",
        ),
        (
            "- Public releases must not hardcode the private production endpoint.",
            "- Public releases must not hardcode an operator-specific production endpoint.",
        ),
        (
            "The exact 1.3.3 archive is retained in the private production repo for "
            "reproducibility. A public export should generate a portable userscript "
            "with configurable endpoint(s), so forks do not accidentally send their "
            "property pages to another operator's server.",
            "An operator may retain the exact tested userscript archive privately for "
            "reproducibility. The public distribution uses a portable userscript with "
            "configurable endpoint(s), so forks do not accidentally send their "
            "property pages to another operator's server.",
        ),
    ),
    "docs/architecture.md": (
        (
            "The private production repository distinguishes **evidence state** from "
            "**numeric value** throughout the pipeline.",
            "The implementation distinguishes **evidence state** from **numeric value** "
            "throughout the pipeline.",
        ),
        (
            "Public releases must use configurable endpoints instead of a private "
            "production hostname.",
            "Public releases must use configurable endpoints instead of an "
            "operator-specific production hostname.",
        ),
    ),
    "docs/current-state.md": (
        (
            "The private repository is the production source of truth. The sanitized "
            "public repository can lag behind this document, especially for scoring "
            "semantics, Geo precision and Labor workflows.",
            "This document describes the implementation state represented by this "
            "public release.",
        ),
        (
            "The previous search has ended without a move. Its runtime database was "
            "archived and the live database was reset on 2026-09-17 so the "
            "installation can begin a new search without carrying forward old "
            "candidates, queue state or decisions.",
            "This release captures the reusable application baseline after a completed "
            "production search and operator reset. Runtime databases and prior search "
            "state are not part of the public distribution.",
        ),
    ),
    "docs/workflows.md": (
        (
            "This document describes the workflows currently used in the **private "
            "production repository**. They are intentionally more detailed than the "
            "portable public snapshot.",
            "This document describes the workflows represented by this public release. "
            "Deployment-specific credentials, runtime data and private infrastructure "
            "details are intentionally omitted.",
        ),
    ),
    "docs/decisions.md": (
        (
            "The private repository remains the complete production archive. The public "
            "repository becomes a portable product/source distribution.",
            "Operational history remains private while the public repository provides "
            "a portable product/source distribution.",
        ),
        (
            "Keep the operator's reference point enabled only in the private "
            "production configuration. The public example exposes the feature with "
            "generic, disabled values.",
            "Keep an operator's reference point in local configuration only. The "
            "public example exposes the feature with generic, disabled values.",
        ),
        (
            "Disable the Plötzkau location weighting because the search it represented "
            "ended without a move.",
            "Keep reference-location weighting disabled in the public baseline until "
            "an operator deliberately configures a relevant reference point.",
        ),
    ),
}


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


def sanitize_public_document(relative: Path, text: str) -> str:
    for old, new in PUBLIC_DOCUMENT_REPLACEMENTS.get(
        relative.as_posix(),
        (),
    ):
        text = text.replace(old, new)

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

    text = sanitize_common_text(text)

    if relative.suffix.lower() == ".md":
        text = sanitize_public_document(
            relative,
            text,
        )

    return text


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
                newline="\n",
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
            newline="\n",
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

    # Plural token collections are ordinary parsing data (for example,
    # municipality-name word sets), not credential values.
    if name.lower().endswith("_tokens"):
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
        # The exporter is public and scans itself. Its own scanner definition is
        # code, not a credential. Keep this exemption exact and narrow.
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

    if (
        relative.as_posix() in PUBLIC_PERSPECTIVE_PATHS
        and PUBLIC_PERSPECTIVE_FORBIDDEN_RE.search(text)
    ):
        failures.append(
            f"{relative}: private-repository wording remains in public documentation"
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
        newline="\n",
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

    # A running production installation normally changes its database and other
    # excluded runtime artifacts. Those paths are never exported and therefore
    # must not block a release. Publishable tracked source must still be clean.
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
            "Publizierbares privates Working Tree ist nicht sauber; Export abgebrochen."
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
        "Public snapshot erstellt und Basis-Audit bestanden:"
    )
    print(destination)
    print()
    print(
        "Nächster Schritt: unabhängiger Secret-Scanner + manuelle Prüfung."
    )


if __name__ == "__main__":
    main()
