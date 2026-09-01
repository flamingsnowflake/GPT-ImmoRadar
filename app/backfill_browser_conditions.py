import json
import os
import sqlite3

from browser_condition import (
    extract_explicit_condition,
)
from scoring import score_house


DB_PATH = os.environ.get(
    "DB_PATH",
    "/data/database.sqlite3",
)


MANUAL_SOURCES = {
    "telegram",
    "telegram_manual",
    "manual",
    "manuell",
    "manual_override",
}


def main():

    db = sqlite3.connect(
        DB_PATH,
        timeout=30,
    )
    db.row_factory = sqlite3.Row

    rows = db.execute(
        """
        SELECT *
        FROM properties
        WHERE property_type IN ('house', 'farm')
          AND browser_text IS NOT NULL
          AND COALESCE(rating, '') != 'blacklisted'
        ORDER BY id
        """
    ).fetchall()

    filled = 0
    normalized = 0
    skipped_manual = 0

    for row in rows:

        property_data = dict(row)

        current_source = str(
            property_data.get(
                "condition_source"
            )
            or ""
        ).strip().lower()

        if current_source in MANUAL_SOURCES:
            skipped_manual += 1
            continue

        current_class = str(
            property_data.get(
                "condition_class"
            )
            or "unknown"
        ).strip().lower()

        if current_class not in {
            "",
            "unknown",
        } and current_source != "browser_explicit":
            continue

        result = extract_explicit_condition(
            property_data.get(
                "browser_text"
            )
        )

        if not result:
            continue

        new_class = result.get(
            "condition_class"
        )
        new_reason = result.get(
            "condition_reason"
        )
        new_source = result.get(
            "condition_source"
        )

        if (
            property_data.get(
                "condition_class"
            ) == new_class
            and property_data.get(
                "condition_reason"
            ) == new_reason
            and property_data.get(
                "condition_source"
            ) == new_source
        ):
            continue

        was_unknown = current_class in {
            "",
            "unknown",
        }

        property_data[
            "condition_class"
        ] = new_class
        property_data[
            "condition_reason"
        ] = new_reason
        property_data[
            "condition_source"
        ] = new_source

        score_result = score_house(
            property_data
        )

        db.execute(
            """
            UPDATE properties
            SET
                condition_class = ?,
                condition_reason = ?,
                condition_source = ?,
                score = ?,
                rating = ?,
                is_ko = ?,
                score_details = ?
            WHERE id = ?
            """,
            (
                new_class,
                new_reason,
                new_source,
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

        if was_unknown:
            filled += 1
            action = "GEFÜLLT"
        else:
            normalized += 1
            action = "NORMALISIERT"

        print(
            f"{action}: DB #{property_data['id']} | "
            f"{property_data['portal_id']} | "
            f"{new_class} | {new_reason}"
        )

    db.commit()
    db.close()

    print()
    print(
        f"✅ Zustand aus Browserfeld gefüllt: {filled}"
    )
    print(
        f"✅ Browser-Zustandsgründe normalisiert: {normalized}"
    )
    print(
        f"ℹ️ Manuelle Zustände geschützt: {skipped_manual}"
    )


if __name__ == "__main__":
    main()
