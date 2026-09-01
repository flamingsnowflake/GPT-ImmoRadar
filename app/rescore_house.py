import json
import os
import sqlite3

DB_PATH = os.environ.get(
    "DB_PATH",
    "/data/database.sqlite3",
)

from scoring import score_house


def main():

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        """
        SELECT *
        FROM properties
        WHERE property_type IN (
            'house',
            'farm'
        )
        ORDER BY id
        """
    ).fetchall()

    print(
        f"Found {len(rows)} HOUSE/FARM object(s)"
    )

    changed = 0

    for row in rows:
        property_data = dict(row)

        result = score_house(
            property_data
        )

        old_score = property_data.get(
            "score"
        )
        new_score = result["score"]

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
                new_score,
                result["rating"],
                int(result["ko"]),
                json.dumps(
                    result,
                    ensure_ascii=False,
                ),
                property_data["id"],
            ),
        )

        if old_score != new_score:
            changed += 1

            print(
                f"{property_data['portal_id']} | "
                f"{old_score} -> {new_score} | "
                f"{result['rating']}"
            )

    conn.commit()
    conn.close()

    print()
    print(
        f"Rescored: {len(rows)} | "
        f"Score changed: {changed}"
    )


if __name__ == "__main__":
    main()
