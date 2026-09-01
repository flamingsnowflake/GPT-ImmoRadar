import argparse
import collections
import json
import re
import sqlite3

from energy_data import (
    update_property_energy,
)
from monitor import DB_PATH
from scoring import score_house


def clean(value):

    if value is None:
        return None

    text = (
        str(value)
        .replace("\u00a0", " ")
        .strip()
    )

    return text or None


def page_lines(text):

    result = []

    for line in (
        str(text or "")
        .replace("\r", "")
        .split("\n")
    ):

        value = clean(line)

        if value:
            result.append(value)

    return result


def normalize_energy_text(text):

    text = (
        str(text or "")
        .replace("\u00a0", " ")
    )

    replacements = (
        (
            r"Energie-\s*ausweistyp",
            "Energieausweistyp",
        ),
        (
            r"Endenergie-\s*bedarf",
            "Endenergiebedarf",
        ),
        (
            r"Endenergie-\s*verbrauch",
            "Endenergieverbrauch",
        ),
        (
            r"Energieeffizienz-\s*klasse",
            "Energieeffizienzklasse",
        ),
        (
            r"Wesentliche\s+Energieträger",
            "Wesentliche Energieträger",
        ),
        (
            r"Wesentlicher\s+Energieträger",
            "Wesentlicher Energieträger",
        ),
        (
            r"Baujahr laut\s+Energieausweis",
            "Baujahr laut Energieausweis",
        ),
    )

    for pattern, replacement in replacements:

        text = re.sub(
            pattern,
            replacement,
            text,
            flags=re.I,
        )

    return text


def extract_energy_section(lines):

    start_patterns = (
        re.compile(
            r"^Bausubstanz\s*&\s*Energieausweis$",
            re.I,
        ),
        re.compile(
            r"^Bausubstanz\s+und\s+Energie$",
            re.I,
        ),
    )

    end_patterns = (
        re.compile(r"^Beschreibung$", re.I),
        re.compile(r"^Preisdetails$", re.I),
        re.compile(r"^Lage$", re.I),
        re.compile(
            r"^Weitere Informationen$",
            re.I,
        ),
        re.compile(r"^Kosten$", re.I),
    )

    start = None

    for index, line in enumerate(lines):

        if any(
            pattern.search(line)
            for pattern in start_patterns
        ):
            start = index
            break

    if start is None:
        return []

    result = []

    for line in lines[
        start + 1:
        start + 61
    ]:

        if (
            result
            and any(
                pattern.search(line)
                for pattern in end_patterns
            )
        ):
            break

        result.append(line)

    return result


def value_after_label(
    lines,
    labels,
):

    normalized_labels = [
        label.lower()
        for label in labels
    ]

    for index, line in enumerate(lines):

        lower = line.lower()

        for label in normalized_labels:

            if lower == label:

                if index + 1 < len(lines):
                    return clean(
                        lines[index + 1]
                    )

            if lower.startswith(
                label + ":"
            ):
                return clean(
                    line[
                        len(label) + 1:
                    ]
                )

            if lower.startswith(
                label + " "
            ):
                return clean(
                    line[
                        len(label) + 1:
                    ]
                )

    return None


def first_regex(
    text,
    patterns,
):

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            flags=re.I,
        )

        if match:
            return clean(
                match.group(1)
            )

    return None


def normalize_number(value):

    if not value:
        return None

    normalized = re.sub(
        r"\s",
        "",
        str(value),
    )

    normalized = re.sub(
        r"\.(?=\d{3}(?:\D|$))",
        "",
        normalized,
    )

    normalized = normalized.replace(
        ",",
        ".",
    )

    try:
        return float(normalized)

    except ValueError:
        return None


def extract_energy_data(text):

    lines = page_lines(text)

    full_text = "\n".join(
        lines
    )

    section = extract_energy_section(
        lines
    )

    section_text = "\n".join(
        section
    )

    preferred_text = normalize_energy_text(
        section_text or full_text
    )

    normalized_full_text = (
        normalize_energy_text(
            full_text
        )
    )

    # --------------------------------------------------------
    # Energieeffizienzklasse
    # --------------------------------------------------------

    energy_class = first_regex(
        normalized_full_text,
        (
            (
                r"Energieeffizienz"
                r"[\s\u00ad\u2010\u2011\u2012\u2013\u2014-]*"
                r"klasse\s*:?\s*"
                r"([A-H](?:\+)?)"
            ),
            (
                r"Energieausweis\s*"
                r"(?:/|\n|:)\s*"
                r"([A-H](?:\+)?)"
            ),
        ),
    )

    if (
        not energy_class
        and section
    ):

        energy_heading_index = None

        for index, line in enumerate(
            section
        ):

            if re.fullmatch(
                r"Energieausweis",
                line,
                flags=re.I,
            ):
                energy_heading_index = index
                break

        if energy_heading_index is not None:

            for line in section[
                energy_heading_index + 1:
                energy_heading_index + 6
            ]:

                match = re.fullmatch(
                    r"([A-H](?:\+)?)",
                    line,
                    flags=re.I,
                )

                if match:
                    energy_class = (
                        match.group(1)
                    )
                    break

    if energy_class:
        energy_class = (
            energy_class
            .strip()
            .upper()
        )

    # --------------------------------------------------------
    # Endenergiebedarf / Verbrauch
    # --------------------------------------------------------

    energy_value_text = first_regex(
        normalized_full_text,
        (
            (
                r"Endenergie"
                r"[\s\u00ad\u2010\u2011\u2012\u2013\u2014-]*"
                r"(?:bedarf|verbrauch)"
                r"\s*:?\s*"
                r"([0-9]{1,4}"
                r"(?:[.,][0-9]{1,2})?)"
            ),
            (
                r"Energieverbrauch"
                r"\s*:?\s*"
                r"([0-9]{1,4}"
                r"(?:[.,][0-9]{1,2})?)"
            ),
        ),
    )

    energy_value = normalize_number(
        energy_value_text
    )

    # --------------------------------------------------------
    # Energieausweistyp
    # --------------------------------------------------------

    certificate_type = "unknown"

    if (
        re.search(
            r"Energieausweistyp\s*:?\s*Bedarfsausweis",
            preferred_text,
            re.I,
        )
        or re.search(
            r"\bBedarfsausweis\b",
            preferred_text,
            re.I,
        )
    ):
        certificate_type = "demand"

    elif (
        re.search(
            r"Energieausweistyp\s*:?\s*Verbrauchsausweis",
            preferred_text,
            re.I,
        )
        or re.search(
            r"\bVerbrauchsausweis\b",
            preferred_text,
            re.I,
        )
    ):
        certificate_type = "consumption"

    elif re.search(
        r"\bBedarfsausweis\b",
        normalized_full_text,
        re.I,
    ):
        certificate_type = "demand"

    elif re.search(
        r"\bVerbrauchsausweis\b",
        normalized_full_text,
        re.I,
    ):
        certificate_type = "consumption"

    # --------------------------------------------------------
    # Energieausweis-Status
    # --------------------------------------------------------

    certificate_status = "unknown"

    if (
        re.search(
            (
                r"Energieausweis[\s\S]{0,120}"
                r"(?:laut Gesetz )?"
                r"nicht erforderlich"
            ),
            normalized_full_text,
            re.I,
        )
        or re.search(
            (
                r"(?:laut Gesetz )?"
                r"nicht erforderlich"
                r"[\s\S]{0,120}"
                r"Energieausweis"
            ),
            normalized_full_text,
            re.I,
        )
    ):
        certificate_status = (
            "not_required"
        )

    elif re.search(
        (
            r"Energieausweis[\s\S]{0,120}"
            r"(?:noch nicht|"
            r"nicht verfügbar|"
            r"nicht vorhanden)"
        ),
        normalized_full_text,
        re.I,
    ):
        certificate_status = (
            "not_available_yet"
        )

    elif (
        energy_class
        or energy_value is not None
        or certificate_type != "unknown"
        or re.search(
            r"Energieausweis\s*:?\s*liegt vor",
            normalized_full_text,
            re.I,
        )
    ):
        certificate_status = "available"

    # --------------------------------------------------------
    # Heizungsart
    # --------------------------------------------------------

    heating_type = first_regex(
        preferred_text,
        (
            r"Heizungsart\s*:?\s*([^\n]{1,120})",
        ),
    )

    if not heating_type:

        heating_type = value_after_label(
            section,
            (
                "Heizungsart",
            ),
        )

    if not heating_type:

        heating_type = first_regex(
            normalized_full_text,
            (
                r"Heizungsart\s*:?\s*([^\n]{1,120})",
            ),
        )

    # --------------------------------------------------------
    # Energieträger
    # --------------------------------------------------------

    energy_source = first_regex(
        preferred_text,
        (
            (
                r"(?:Wesentliche Energieträger|"
                r"Wesentlicher Energieträger|"
                r"Hauptenergieträger|"
                r"Energieträger)"
                r"\s*:?\s*"
                r"([^\n]{1,120})"
            ),
        ),
    )

    if not energy_source:

        energy_source = value_after_label(
            section,
            (
                "Energieträger",
                "Wesentliche Energieträger",
                "Wesentlicher Energieträger",
                "Hauptenergieträger",
            ),
        )

    if not energy_source:

        energy_source = first_regex(
            normalized_full_text,
            (
                (
                    r"(?:Wesentliche Energieträger|"
                    r"Wesentlicher Energieträger|"
                    r"Hauptenergieträger|"
                    r"Energieträger)"
                    r"\s*:?\s*"
                    r"([^\n]{1,120})"
                ),
            ),
        )

    # --------------------------------------------------------
    # Baujahr laut Energieausweis
    # --------------------------------------------------------

    year_text = first_regex(
        preferred_text,
        (
            (
                r"Baujahr laut Energieausweis"
                r"\s*:?\s*"
                r"((?:18|19|20)\d{2})"
            ),
            (
                r"Baujahr des Objekts lt\. "
                r"Energieausweis"
                r"(?: ist)?\s*:?\s*"
                r"((?:18|19|20)\d{2})"
            ),
        ),
    )

    if not year_text:

        year_text = value_after_label(
            section,
            (
                "Baujahr laut Energieausweis",
                "Baujahr Gebäude (Ursprung)",
                "Baujahr",
            ),
        )

    construction_year = None

    if year_text:

        match = re.search(
            r"\b(?:18|19|20)\d{2}\b",
            str(year_text),
        )

        if match:
            construction_year = int(
                match.group(0)
            )

    # --------------------------------------------------------
    # Sonderfall: Energieausweis nicht erforderlich
    # --------------------------------------------------------

    if certificate_status == "not_required":

        energy_class = None
        energy_value = None
        certificate_type = "unknown"

    # --------------------------------------------------------
    # Debug-Rohtext
    # --------------------------------------------------------

    raw_candidates = []

    if section:

        raw_candidates.append(
            "Bausubstanz/Energie:\n"
            + "\n".join(section)
        )

    relevant_lines = [
        line
        for line in lines
        if re.search(
            (
                r"energie|heizung|"
                r"energieträger|"
                r"hauptenergieträger|"
                r"baujahr"
            ),
            line,
            re.I,
        )
    ]

    if relevant_lines:

        raw_candidates.append(
            "Weitere Treffer:\n"
            + "\n".join(
                relevant_lines[:30]
            )
        )

    raw_text = clean(
        "\n\n".join(
            raw_candidates
        )
    )

    return {
        "energy_class":
            energy_class,

        "energy_value_kwh":
            energy_value,

        "energy_certificate_type":
            certificate_type,

        "energy_certificate_status":
            certificate_status,

        "heating_type":
            heating_type,

        "energy_source":
            energy_source,

        "energy_construction_year":
            construction_year,

        "energy_data_source":
            "browser_text_backfill",

        "energy_raw_text":
            raw_text[:5000]
            if raw_text
            else None,
    }


def has_useful_data(data):

    return bool(
        data.get(
            "energy_class"
        )
        or data.get(
            "energy_value_kwh"
        ) is not None
        or data.get(
            "energy_certificate_type"
        ) != "unknown"
        or data.get(
            "energy_certificate_status"
        ) != "unknown"
        or data.get(
            "heating_type"
        )
        or data.get(
            "energy_source"
        )
        or data.get(
            "energy_construction_year"
        )
    )


def missing_reasons(value):

    try:
        details = json.loads(
            value or "{}"
        )

    except Exception:
        return []

    if not isinstance(
        details,
        dict
    ):
        return []

    reasons = details.get(
        "incomplete_reasons"
    )

    if not isinstance(
        reasons,
        list
    ):
        return []

    return [
        str(reason)
        for reason in reasons
        if reason
    ]


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--dry-run",
        action="store_true",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=0,
    )

    args = parser.parse_args()

    conn = sqlite3.connect(
        DB_PATH,
        timeout=30,
    )

    conn.row_factory = (
        sqlite3.Row
    )

    rows = conn.execute(
        """
        SELECT *
        FROM properties
        WHERE rating = 'incomplete'
          AND COALESCE(is_ko, 0) = 0
          AND property_type IN (
              'house',
              'farm'
          )
          AND energy_updated_at IS NULL
          AND browser_text IS NOT NULL
          AND TRIM(browser_text) != ''
        ORDER BY
            last_seen DESC,
            id DESC
        """
    ).fetchall()

    if args.limit > 0:
        rows = rows[
            :args.limit
        ]

    found = 0
    no_data = 0
    completed = 0
    still_incomplete = 0
    became_ko = 0
    errors = 0

    print(
        "========================================"
    )
    print(
        "ENERGY FROM STORED BROWSER TEXT"
    )
    print(
        "========================================"
    )
    print(
        f"Kandidaten: {len(rows)}"
    )
    print(
        f"Dry run:    {args.dry_run}"
    )
    print()

    for number, row in enumerate(
        rows,
        1,
    ):

        property_data = dict(
            row
        )

        try:

            energy = extract_energy_data(
                property_data.get(
                    "browser_text"
                )
            )

            if not has_useful_data(
                energy
            ):

                no_data += 1

                print(
                    f"[{number:02d}/{len(rows):02d}] "
                    f"{property_data['portal_id']} "
                    "| keine Energiedaten erkannt",
                    flush=True,
                )

                continue

            found += 1

            summary_parts = []

            if energy.get(
                "energy_class"
            ):
                summary_parts.append(
                    "Klasse "
                    + str(
                        energy[
                            "energy_class"
                        ]
                    )
                )

            if energy.get(
                "energy_value_kwh"
            ) is not None:
                summary_parts.append(
                    "Wert "
                    + str(
                        energy[
                            "energy_value_kwh"
                        ]
                    )
                )

            if (
                energy.get(
                    "energy_certificate_type"
                )
                != "unknown"
            ):
                summary_parts.append(
                    str(
                        energy[
                            "energy_certificate_type"
                        ]
                    )
                )

            if (
                energy.get(
                    "energy_certificate_status"
                )
                != "unknown"
            ):
                summary_parts.append(
                    str(
                        energy[
                            "energy_certificate_status"
                        ]
                    )
                )

            if energy.get(
                "heating_type"
            ):
                summary_parts.append(
                    "Heizung "
                    + str(
                        energy[
                            "heating_type"
                        ]
                    )
                )

            if energy.get(
                "energy_source"
            ):
                summary_parts.append(
                    "Träger "
                    + str(
                        energy[
                            "energy_source"
                        ]
                    )
                )

            print(
                f"[{number:02d}/{len(rows):02d}] "
                f"{property_data['portal_id']} "
                "| "
                + (
                    " | ".join(
                        summary_parts
                    )
                    or "verwertbare Daten"
                ),
                flush=True,
            )

            if args.dry_run:
                continue

            update_property_energy(
                conn,
                property_data["portal"],
                property_data["portal_id"],
                energy,
            )

            fresh = conn.execute(
                """
                SELECT *
                FROM properties
                WHERE id = ?
                """,
                (
                    property_data["id"],
                ),
            ).fetchone()

            if fresh is None:
                raise RuntimeError(
                    "Objekt nach Energie-Update "
                    "nicht mehr gefunden"
                )

            fresh_data = dict(
                fresh
            )

            score_result = score_house(
                fresh_data
            )

            conn.execute(
                """
                UPDATE properties
                SET
                    score = ?,
                    rating = ?,
                    is_ko = ?,
                    score_details = ?
                WHERE id = ?
                """,
                (
                    score_result.get(
                        "score"
                    ),
                    score_result.get(
                        "rating"
                    ),
                    int(
                        bool(
                            score_result.get(
                                "ko"
                            )
                        )
                    ),
                    json.dumps(
                        score_result,
                        ensure_ascii=False,
                    ),
                    property_data["id"],
                ),
            )

            conn.commit()

            if score_result.get(
                "ko"
            ):

                became_ko += 1

            elif (
                score_result.get(
                    "rating"
                )
                == "incomplete"
            ):

                still_incomplete += 1

            else:

                completed += 1

        except Exception as exc:

            conn.rollback()

            errors += 1

            print(
                f"    FEHLER: "
                f"{type(exc).__name__}: "
                f"{exc}",
                flush=True,
            )

    print()
    print(
        "========================================"
    )
    print(
        "ERGEBNIS"
    )
    print(
        "========================================"
    )

    print(
        f"Energie erkannt:      {found}"
    )
    print(
        f"Keine Daten erkannt:  {no_data}"
    )

    if not args.dry_run:

        print(
            f"Jetzt vollständig:    {completed}"
        )
        print(
            f"Weiter unvollständig: {still_incomplete}"
        )
        print(
            f"Jetzt KO:             {became_ko}"
        )

    print(
        f"Fehler:               {errors}"
    )

    if not args.dry_run:

        remaining = conn.execute(
            """
            SELECT score_details
            FROM properties
            WHERE rating = 'incomplete'
              AND COALESCE(is_ko, 0) = 0
              AND property_type IN (
                  'house',
                  'farm'
              )
            """
        ).fetchall()

        counts = collections.Counter()

        for row in remaining:

            counts.update(
                missing_reasons(
                    row[
                        "score_details"
                    ]
                )
            )

        print()
        print(
            "NOCH OFFEN:"
        )

        print(
            f"Objekte: {len(remaining)}"
        )

        for reason, count in (
            counts.most_common()
        ):

            print(
                f"{count:4d}  {reason}"
            )

    conn.close()


if __name__ == "__main__":
    main()
