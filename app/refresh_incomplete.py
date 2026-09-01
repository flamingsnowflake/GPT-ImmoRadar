import argparse
import collections
import json
import sqlite3
import time

from house_condition import (
    classify_house_condition,
)
from monitor import (
    DB_PATH,
    enrich_property,
)
from property_types import (
    is_house_type,
)
from scoring import (
    score_house,
)


UPDATE_FIELDS = (
    "condition_class",
    "condition_reason",
    "condition_source",

    "latitude",
    "longitude",
    "geocode_query",
    "geocoded_at",
    "geocode_source_location",

    "water_distance_km",
    "water_class",
    "water_width_lower_m",
    "water_width_upper_m",
    "water_score",

    "neighbour_class",
    "nearest_building_m",
    "buildings_100m",
    "buildings_250m",
    "buildings_500m",
    "neighbour_checked_at",

    "rail_lden",
    "rail_lnight",
    "rail_distance_m",
    "rail_annual_traffic",

    "road_lden",
    "road_lnight",
    "road_noise_source",

    "air_lden",
    "air_lnight",
    "air_noise_source",

    "noise_checked_at",

    "score",
    "rating",
    "is_ko",
    "score_details",
)


def details_dict(value):

    if isinstance(
        value,
        dict
    ):
        return value

    if not value:
        return {}

    try:
        result = json.loads(
            value
        )

    except Exception:
        return {}

    if isinstance(
        result,
        dict
    ):
        return result

    return {}


def missing_reasons(value):

    details = details_dict(
        value
    )

    missing = details.get(
        "incomplete_reasons"
    )

    if not isinstance(
        missing,
        list
    ):
        return []

    return [
        str(item)
        for item in missing
        if item
    ]


def classify_missing_condition(
    property_data
):

    current = str(
        property_data.get(
            "condition_class"
        )
        or ""
    ).strip().lower()

    if current not in (
        "",
        "unknown",
    ):
        return False

    candidate_data = dict(
        property_data
    )

    texts = []

    for key in (
        "raw_text",
        "browser_text",
    ):

        value = property_data.get(
            key
        )

        if value:
            texts.append(
                str(value)
            )

    if texts:

        # Den vorhandenen Browsertext nur für die
        # Klassifikation zusätzlich verwenden.
        # raw_text in der DB wird NICHT verändert.
        candidate_data[
            "raw_text"
        ] = "\n\n".join(
            texts
        )

    result = classify_house_condition(
        candidate_data
    )

    candidate = str(
        result.get(
            "condition_class"
        )
        or ""
    ).strip().lower()

    if candidate in (
        "",
        "unknown",
    ):
        return False

    property_data[
        "condition_class"
    ] = result.get(
        "condition_class"
    )

    property_data[
        "condition_reason"
    ] = result.get(
        "condition_reason"
    )

    property_data[
        "condition_source"
    ] = result.get(
        "condition_source"
    )

    return True


def persist(
    conn,
    property_data,
    columns,
):

    values = dict(
        property_data
    )

    values["is_ko"] = int(
        bool(
            property_data.get(
                "is_ko"
            )
        )
    )

    score_details = (
        property_data.get(
            "score_details"
        )
    )

    if isinstance(
        score_details,
        dict
    ):

        values["score_details"] = (
            json.dumps(
                score_details,
                ensure_ascii=False,
            )
        )

    fields = [
        field
        for field in UPDATE_FIELDS
        if field in columns
    ]

    assignments = ", ".join(
        f"{field} = :{field}"
        for field in fields
    )

    values[
        "property_id"
    ] = property_data[
        "id"
    ]

    conn.execute(
        f"""
        UPDATE properties
        SET {assignments}
        WHERE id = :property_id
        """,
        values,
    )


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help=(
            "Nur die ersten N Objekte "
            "bearbeiten; 0 = alle"
        ),
    )

    parser.add_argument(
        "--sleep",
        type=float,
        default=0.10,
        help=(
            "Pause zwischen Objekten "
            "in Sekunden"
        ),
    )

    args = parser.parse_args()

    conn = sqlite3.connect(
        DB_PATH,
        timeout=30,
    )

    conn.row_factory = (
        sqlite3.Row
    )

    columns = {
        row[1]
        for row in conn.execute(
            "PRAGMA table_info(properties)"
        )
    }

    rows = conn.execute(
        """
        SELECT *
        FROM properties
        WHERE rating = 'incomplete'
          AND COALESCE(
                is_ko,
                0
              ) = 0
          AND property_type IN (
                'house',
                'farm'
              )
        ORDER BY
            last_seen DESC,
            id DESC
        """
    ).fetchall()

    if args.limit > 0:
        rows = rows[
            :args.limit
        ]

    total = len(
        rows
    )

    print(
        "========================================"
    )
    print(
        "INCOMPLETE AUTO-REFRESH"
    )
    print(
        "========================================"
    )
    print(
        f"Objekte: {total}"
    )
    print()

    completed = 0
    still_incomplete = 0
    became_ko = 0

    condition_detected = 0

    before_reasons = (
        collections.Counter()
    )

    after_reasons = (
        collections.Counter()
    )

    for number, row in enumerate(
        rows,
        1,
    ):

        property_data = dict(
            row
        )

        if not is_house_type(
            property_data.get(
                "property_type"
            )
        ):
            continue

        before_missing = (
            missing_reasons(
                property_data.get(
                    "score_details"
                )
            )
        )

        before_reasons.update(
            before_missing
        )

        before_snapshot = {
            field:
                property_data.get(
                    field
                )
            for field in UPDATE_FIELDS
            if field
            not in (
                "score",
                "rating",
                "is_ko",
                "score_details",
            )
        }

        try:

            if classify_missing_condition(
                property_data
            ):
                condition_detected += 1

            property_data = (
                enrich_property(
                    conn,
                    property_data,
                )
            )

            result = score_house(
                property_data
            )

            property_data[
                "score"
            ] = result.get(
                "score"
            )

            property_data[
                "rating"
            ] = result.get(
                "rating"
            )

            property_data[
                "is_ko"
            ] = int(
                bool(
                    result.get(
                        "ko"
                    )
                )
            )

            property_data[
                "score_details"
            ] = result

            persist(
                conn,
                property_data,
                columns,
            )

            conn.commit()

            after_missing = (
                result.get(
                    "incomplete_reasons"
                )
                or []
            )

            after_reasons.update(
                after_missing
            )

            changed = []

            for field, before in (
                before_snapshot.items()
            ):

                after = (
                    property_data.get(
                        field
                    )
                )

                if before != after:
                    changed.append(
                        field
                    )

            if result.get(
                "ko"
            ):

                became_ko += 1

                state = "KO"

            elif result.get(
                "rating"
            ) == "incomplete":

                still_incomplete += 1

                state = (
                    "OFFEN: "
                    + ", ".join(
                        after_missing
                    )
                )

            else:

                completed += 1

                state = (
                    "FERTIG: "
                    f"{result.get('score')}/100"
                )

            changed_text = (
                ", ".join(
                    changed
                )
                if changed
                else "-"
            )

            print(
                f"[{number:03d}/{total:03d}] "
                f"{property_data.get('portal_id')} "
                f"| geändert: {changed_text} "
                f"| {state}",
                flush=True,
            )

        except Exception as exc:

            conn.rollback()

            still_incomplete += 1

            print(
                f"[{number:03d}/{total:03d}] "
                f"{property_data.get('portal_id')} "
                f"| FEHLER: "
                f"{type(exc).__name__}: "
                f"{exc}",
                flush=True,
            )

        if args.sleep > 0:
            time.sleep(
                args.sleep
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
        f"Bearbeitet:          {total}"
    )
    print(
        f"Vollständig:         {completed}"
    )
    print(
        f"Jetzt KO:            {became_ko}"
    )
    print(
        f"Weiter unvollständig:{still_incomplete}"
    )
    print(
        f"Zustand erkannt:     {condition_detected}"
    )

    print()
    print(
        "FEHLGRÜNDE VORHER:"
    )

    for reason, count in (
        before_reasons.most_common()
    ):

        print(
            f"{count:4d}  {reason}"
        )

    print()
    print(
        "FEHLGRÜNDE NACHHER:"
    )

    for reason, count in (
        after_reasons.most_common()
    ):

        print(
            f"{count:4d}  {reason}"
        )

    # --------------------------------------------------------
    # Gesamtbestand nach dem Lauf
    # --------------------------------------------------------

    remaining = conn.execute(
        """
        SELECT *
        FROM properties
        WHERE rating = 'incomplete'
          AND COALESCE(
                is_ko,
                0
              ) = 0
          AND property_type IN (
                'house',
                'farm'
              )
        """
    ).fetchall()

    remaining_reasons = (
        collections.Counter()
    )

    browser_text_count = 0
    browser_energy_open = 0

    for row in remaining:

        item = dict(
            row
        )

        reasons = missing_reasons(
            item.get(
                "score_details"
            )
        )

        remaining_reasons.update(
            reasons
        )

        if item.get(
            "browser_text"
        ):
            browser_text_count += 1

            if "Energie" in reasons:
                browser_energy_open += 1

    print()
    print(
        "========================================"
    )
    print(
        "GESAMT NOCH OFFEN"
    )
    print(
        "========================================"
    )

    print(
        f"Objekte: {len(remaining)}"
    )

    for reason, count in (
        remaining_reasons.most_common()
    ):

        print(
            f"{count:4d}  {reason}"
        )

    print()
    print(
        "Davon mit gespeichertem "
        f"Browsertext: {browser_text_count}"
    )

    print(
        "Davon Energie offen + "
        "Browsertext vorhanden: "
        f"{browser_energy_open}"
    )

    conn.close()


if __name__ == "__main__":
    main()
