import json
import sqlite3

from monitor import DB_PATH
from scoring import score_house


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
          AND rating = 'incomplete'
          AND energy_updated_at IS NOT NULL
          AND COALESCE(
                energy_certificate_status,
                'unknown'
              ) != 'not_available_yet'
        """
    ).fetchall()

    repaired = 0

    for row in rows:

        property_data = dict(row)

        try:
            old_details = json.loads(
                property_data.get(
                    "score_details"
                )
                or "{}"
            )
        except Exception:
            old_details = {}

        old_missing = old_details.get(
            "incomplete_reasons"
        )

        if not (
            isinstance(
                old_missing,
                list,
            )
            and "Energie" in old_missing
        ):
            continue

        result = score_house(
            property_data
        )

        db.execute(
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
                result.get("score"),
                result.get("rating"),
                int(
                    bool(
                        result.get("ko")
                    )
                ),
                json.dumps(
                    result,
                    ensure_ascii=False,
                ),
                property_data["id"],
            ),
        )

        print(
            "REPAIRED: "
            f"DB #{property_data['id']} | "
            f"{property_data.get('portal_id')} | "
            f"{old_missing} -> "
            f"{result.get('incomplete_reasons', [])}"
        )

        repaired += 1

    db.commit()
    db.close()

    print()
    print(
        f"✅ {repaired} stale "
        "Energie-Scoring-Snapshot(s) repariert"
    )


if __name__ == "__main__":
    main()
