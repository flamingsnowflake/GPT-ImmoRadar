import argparse
import collections
import json
import re
import sqlite3

from house_condition import classify_house_condition


CONDITION_LABELS = {
    "turnkey": "Bezugsfertig",
    "good": "Gut",
    "maintained": "Gepflegt",
    "cosmetic_renovation": "Teilrenovierung",
    "renovation_needed": "Renovierungsbedürftig",
    "major_renovation": "Sanierungsbedürftig",
    "dilapidated": "Baufällig/Abriss",
}


# Zusätzliche, absichtlich konservative Regeln.
#
# HIGH:
#   Formulierungen, die den Zustand unmittelbar beschreiben.
#
# REVIEW:
#   Nützliche Hinweise, die ohne menschlichen Blick noch nicht
#   automatisch gespeichert werden sollten.
HIGH_RULES = (
    (
        "dilapidated",
        re.compile(
            r"\b(?:"
            r"unbewohnbar|nicht\s+bewohnbar|"
            r"abriss(?:objekt|reif)?|abbruch(?:objekt|reif)?|"
            r"einsturzgefährdet|ruinös(?:er|e|en|em)?\s+zustand"
            r")\b",
            re.IGNORECASE,
        ),
    ),
    (
        "major_renovation",
        re.compile(
            r"\b(?:"
            r"kernsanierung\s+(?:ist\s+)?erforderlich|"
            r"komplett(?:e|er|en)?\s+sanierungsbedürftig|"
            r"vollständig(?:e|er|en)?\s+sanierungsbedürftig|"
            r"umfassend(?:e|er|en)?\s+sanierungsbedürftig|"
            r"stark(?:e|er|en)?\s+sanierungsbedürftig|"
            r"sanierungsobjekt|"
            r"erheblicher\s+sanierungsstau|"
            r"umfangreiche\s+sanierungsmaßnahmen\s+erforderlich"
            r")\b",
            re.IGNORECASE,
        ),
    ),
    (
        "renovation_needed",
        re.compile(
            r"\b(?:"
            r"renovierungsbedürftig(?:er|e|en|em)?\s+zustand|"
            r"sanierungsbedürftig(?:er|e|en|em)?\s+zustand|"
            r"modernisierungsbedürftig(?:er|e|en|em)?\s+zustand|"
            r"renovierungsstau|"
            r"modernisierungsstau|"
            r"renovierungsarbeiten\s+sind\s+erforderlich|"
            r"modernisierungsmaßnahmen\s+sind\s+erforderlich"
            r")\b",
            re.IGNORECASE,
        ),
    ),
    (
        "cosmetic_renovation",
        re.compile(
            r"\b(?:"
            r"kleinere\s+renovierungsarbeiten|"
            r"leichter\s+renovierungsbedarf|"
            r"teilweise\s+renovierungsbedürftig"
            r")\b",
            re.IGNORECASE,
        ),
    ),
    (
        "turnkey",
        re.compile(
            r"\b(?:"
            r"sofort\s+bezugsfertig|"
            r"direkt\s+bezugsfertig|"
            r"ohne\s+renovierung\s+beziehbar|"
            r"bezugsfertiger\s+zustand|"
            r"bezugsbereit(?:er|e|en|em)?\s+zustand"
            r")\b",
            re.IGNORECASE,
        ),
    ),
    (
        "good",
        re.compile(
            r"\b(?:"
            r"sehr\s+gut(?:er|e|en|em)?\s+zustand|"
            r"guter\s+erhaltungszustand|"
            r"hervorragender\s+zustand|"
            r"vollständig\s+kernsaniert"
            r")\b",
            re.IGNORECASE,
        ),
    ),
    (
        "maintained",
        re.compile(
            r"\b(?:"
            r"sehr\s+gepflegter\s+zustand|"
            r"gepflegter\s+erhaltungszustand|"
            r"ordentlicher\s+zustand|"
            r"solider\s+zustand|"
            r"laufend\s+instandgehalten"
            r")\b",
            re.IGNORECASE,
        ),
    ),
)


REVIEW_RULES = (
    (
        "major_renovation",
        re.compile(
            r"\b(?:"
            r"entkernt|kernsanierung|sanierungsstau|"
            r"umfangreich\w*\s+sanier\w*"
            r")\b",
            re.IGNORECASE,
        ),
    ),
    (
        "renovation_needed",
        re.compile(
            r"\b(?:"
            r"in\s+die\s+jahre\s+gekommen|"
            r"renovierung(?:en)?\s+erforderlich|"
            r"modernisierung(?:en)?\s+erforderlich|"
            r"sanierung(?:en)?\s+erforderlich|"
            r"handwerker(?:haus|objekt)|"
            r"renovierungsbedarf|sanierungsbedarf|modernisierungsbedarf"
            r")\b",
            re.IGNORECASE,
        ),
    ),
    (
        "cosmetic_renovation",
        re.compile(
            r"\b(?:"
            r"renovierung\s+nach\s+geschmack|"
            r"kosmetische\s+renovierung|"
            r"auffrischungsarbeiten"
            r")\b",
            re.IGNORECASE,
        ),
    ),
    (
        "good",
        re.compile(
            r"\b(?:"
            r"kernsaniert|vollständig\s+saniert|"
            r"umfassend\s+modernisiert|"
            r"komplett\s+modernisiert"
            r")\b",
            re.IGNORECASE,
        ),
    ),
    (
        "maintained",
        re.compile(
            r"\b(?:"
            r"gepflegt|instandgehalten|"
            r"ordentlich(?:er|e|en|em)?\s+zustand|"
            r"solide(?:r|e|en|em)?\s+substanz"
            r")\b",
            re.IGNORECASE,
        ),
    ),
    (
        "turnkey",
        re.compile(
            r"\b(?:bezugsfertig|bezugsbereit|neuwertig)\b",
            re.IGNORECASE,
        ),
    ),
)


NEGATION_RE = re.compile(
    r"\b(?:nicht|kein(?:e|er|en|em)?|ohne)\b",
    re.IGNORECASE,
)


HISTORY_RE = re.compile(
    r"\b(?:19|20)\d{2}\b"
)


def _clean(value):

    if value is None:
        return ""

    return " ".join(
        str(value).split()
    ).strip()


def _excerpt(text, start, end, radius=95):

    left = max(0, start - radius)
    right = min(len(text), end + radius)

    result = text[left:right].strip()

    if left:
        result = "…" + result

    if right < len(text):
        result += "…"

    return result


def _unsafe_context(text, match):

    before = text[
        max(0, match.start() - 35):match.start()
    ]

    around = text[
        max(0, match.start() - 60):
        min(len(text), match.end() + 60)
    ]

    # "nicht saniert", "kein renovierungsbedarf" usw.
    if NEGATION_RE.search(before):
        return True

    # Aussagen über ein altes Sanierungs-/Modernisierungsjahr
    # sind kein sicherer Beleg für den heutigen Zustand.
    if HISTORY_RE.search(around) and re.search(
        r"sanier|modernisier|renovier",
        match.group(0),
        re.IGNORECASE,
    ):
        return True

    return False


def _match_rules(text, rules):

    matches = []

    for condition_class, pattern in rules:

        for match in pattern.finditer(text):

            matches.append(
                {
                    "condition_class": condition_class,
                    "phrase": match.group(0),
                    "excerpt": _excerpt(
                        text,
                        match.start(),
                        match.end(),
                    ),
                    "unsafe_context": _unsafe_context(
                        text,
                        match,
                    ),
                }
            )

    return matches


def _source_texts(row, columns):

    sources = []

    for key in (
        "condition",
        "title",
        "raw_text",
        "browser_text",
        "description",
    ):

        if key not in columns:
            continue

        value = _clean(
            row.get(key)
        )

        if value:
            sources.append(
                (key, value)
            )

    return sources


def analyze_row(row, columns):

    sources = _source_texts(
        row,
        columns,
    )

    combined = "\n\n".join(
        text
        for _, text in sources
    )

    result = {
        "portal_id": row.get("portal_id"),
        "title": row.get("title"),
        "location": row.get("location"),
        "sources": [
            source
            for source, _ in sources
        ],
        "text_length": len(combined),
        "status": "none",
        "candidate": None,
        "reason": None,
        "excerpt": None,
    }

    if not combined:
        result["status"] = "no_text"
        return result

    candidate_data = dict(row)

    if "browser_text" in columns:
        candidate_data["raw_text"] = "\n\n".join(
            value
            for key, value in sources
            if key in (
                "raw_text",
                "browser_text",
            )
        )

    existing = classify_house_condition(
        candidate_data
    )

    existing_class = str(
        existing.get("condition_class")
        or "unknown"
    ).strip().lower()

    high_matches = [
        item
        for item in _match_rules(
            combined,
            HIGH_RULES,
        )
        if not item["unsafe_context"]
    ]

    review_matches = _match_rules(
        combined,
        REVIEW_RULES,
    )

    # Eindeutige HIGH-Regel: alle sicheren Treffer zeigen
    # in dieselbe Zustandsklasse.
    high_classes = {
        item["condition_class"]
        for item in high_matches
    }

    if len(high_classes) == 1:

        candidate = next(
            iter(high_classes)
        )

        match = high_matches[0]

        # Falls der vorhandene Klassifikator ebenfalls eine
        # andere Klasse behauptet, nicht automatisch anfassen.
        if (
            existing_class not in (
                "",
                "unknown",
                candidate,
            )
        ):
            result["status"] = "review"
            result["candidate"] = candidate
            result["reason"] = (
                "Konflikt: konservative Regel = "
                f"{candidate}, bestehender Parser = "
                f"{existing_class}"
            )
            result["excerpt"] = match["excerpt"]
            return result

        result["status"] = "high"
        result["candidate"] = candidate
        result["reason"] = (
            "eindeutige Zustandsformulierung: "
            + match["phrase"]
        )
        result["excerpt"] = match["excerpt"]
        return result

    if len(high_classes) > 1:

        result["status"] = "review"
        result["reason"] = (
            "widersprüchliche sichere Hinweise: "
            + ", ".join(sorted(high_classes))
        )
        result["excerpt"] = high_matches[0]["excerpt"]
        return result

    # Der bestehende Parser bleibt als Review-Hinweis nützlich,
    # wenn die stärkeren Regeln nichts Eindeutiges ergeben.
    if existing_class not in (
        "",
        "unknown",
    ):

        reason = _clean(
            existing.get("condition_reason")
        )

        source = _clean(
            existing.get("condition_source")
        )

        result["status"] = "review"
        result["candidate"] = existing_class
        result["reason"] = (
            "bestehender Parser: "
            f"{reason or '-'}"
            + (
                f" ({source})"
                if source
                else ""
            )
        )

        needle = reason.casefold()
        haystack = combined.casefold()
        position = (
            haystack.find(needle)
            if needle
            else -1
        )

        if position >= 0:
            result["excerpt"] = _excerpt(
                combined,
                position,
                position + len(reason),
            )

        return result

    if review_matches:

        # Nur dann eine Kandidatenklasse zeigen, wenn alle
        # Review-Treffer auf dieselbe Klasse weisen.
        review_classes = {
            item["condition_class"]
            for item in review_matches
        }

        result["status"] = "review"

        if len(review_classes) == 1:
            result["candidate"] = next(
                iter(review_classes)
            )

        result["reason"] = (
            "Hinweis: "
            + review_matches[0]["phrase"]
        )
        result["excerpt"] = review_matches[0]["excerpt"]
        return result

    return result


def load_open_rows(db_path):

    conn = sqlite3.connect(
        db_path,
        timeout=30,
    )

    conn.row_factory = sqlite3.Row

    try:

        columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(properties)"
            )
        }

        rows = conn.execute(
            """
            SELECT p.*
            FROM properties AS p
            WHERE p.rating = 'incomplete'
              AND COALESCE(p.is_ko, 0) = 0
              AND p.property_type IN ('house', 'farm')
              AND LOWER(
                    COALESCE(
                        p.condition_class,
                        'unknown'
                    )
                  ) = 'unknown'
              AND p.id = (
                  SELECT p2.id
                  FROM properties AS p2
                  WHERE p2.portal = p.portal
                    AND p2.portal_id = p.portal_id
                  ORDER BY
                      p2.last_seen DESC,
                      p2.id DESC
                  LIMIT 1
              )
            ORDER BY
                p.last_seen DESC,
                p.id DESC
            """
        ).fetchall()

    finally:
        conn.close()

    return (
        [dict(row) for row in rows],
        columns,
    )


def analyze(db_path):

    rows, columns = load_open_rows(
        db_path
    )

    return [
        analyze_row(
            row,
            columns,
        )
        for row in rows
    ]


def _print_samples(
    title,
    rows,
    limit,
):

    print()
    print(title)
    print("-" * len(title))

    if not rows:
        print("keine")
        return

    for number, item in enumerate(
        rows[:limit],
        1,
    ):

        candidate = item.get(
            "candidate"
        )

        label = (
            CONDITION_LABELS.get(
                candidate,
                candidate,
            )
            if candidate
            else "?"
        )

        print(
            f"{number:02d}. "
            f"{item.get('portal_id')} | "
            f"{label} | "
            f"{item.get('title') or '-'}"
        )

        print(
            "    "
            + str(
                item.get("reason")
                or "-"
            )
        )

        if item.get("excerpt"):
            print(
                "    "
                + item["excerpt"]
            )


def main():

    parser = argparse.ArgumentParser(
        description=(
            "Read-only Analyse offener Hauszustände. "
            "Keine Netzwerkzugriffe, keine DB-Änderungen."
        )
    )

    parser.add_argument(
        "--db",
        default="/data/database.sqlite3",
    )

    parser.add_argument(
        "--samples",
        type=int,
        default=20,
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Komplettes Ergebnis als JSON ausgeben",
    )

    args = parser.parse_args()

    results = analyze(
        args.db
    )

    if args.json:
        print(
            json.dumps(
                results,
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    counts = collections.Counter(
        item["status"]
        for item in results
    )

    class_counts = collections.Counter(
        item["candidate"]
        for item in results
        if (
            item["status"] == "high"
            and item.get("candidate")
        )
    )

    with_browser = sum(
        "browser_text" in item["sources"]
        for item in results
    )

    with_raw = sum(
        "raw_text" in item["sources"]
        for item in results
    )

    useful_text = sum(
        item["text_length"] >= 120
        for item in results
    )

    print(
        "========================================"
    )
    print(
        "ZUSTANDS-LABOR · DRY RUN"
    )
    print(
        "========================================"
    )
    print()
    print(
        "Nur lokale SQLite-Texte."
    )
    print(
        "Netzwerkzugriffe: 0"
    )
    print(
        "DB-Änderungen:    0"
    )
    print()
    print(
        f"Offene Zustände:             {len(results)}"
    )
    print(
        f"Sicher automatisch:          {counts['high']}"
    )
    print(
        f"Prüfenswert:                 {counts['review']}"
    )
    print(
        f"Text, aber kein Hinweis:     {counts['none']}"
    )
    print(
        f"Keine gespeicherten Texte:   {counts['no_text']}"
    )
    print()
    print(
        f"Mit raw_text:                {with_raw}"
    )
    print(
        f"Mit browser_text:            {with_browser}"
    )
    print(
        f"Mit >=120 Zeichen Text:      {useful_text}"
    )

    if class_counts:
        print()
        print("SICHERE TREFFER NACH KLASSE")
        print("---------------------------")

        for condition_class, count in (
            class_counts.most_common()
        ):
            print(
                f"{count:4d}  "
                + CONDITION_LABELS.get(
                    condition_class,
                    condition_class,
                )
            )

    high = [
        item
        for item in results
        if item["status"] == "high"
    ]

    review = [
        item
        for item in results
        if item["status"] == "review"
    ]

    _print_samples(
        "SICHER AUTOMATISCH · STICHPROBE",
        high,
        args.samples,
    )

    _print_samples(
        "PRÜFENSWERT · STICHPROBE",
        review,
        args.samples,
    )

    print()
    print(
        "========================================"
    )
    print(
        "✅ DRY RUN — NICHTS VERÄNDERT"
    )
    print(
        "========================================"
    )


if __name__ == "__main__":
    main()
