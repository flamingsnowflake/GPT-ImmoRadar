#!/usr/bin/env python3

import json
import sqlite3

from monitor import DB_PATH
from scoring import score_house


TARGET_STATUSES = {
    "unknown",
    "not_required",
    "not_available_yet",
    "no_label",
}


def main():

    conn = sqlite3.connect(
        DB_PATH,
        timeout=30,
    )

    conn.row_factory = sqlite3.Row

    try:

        rows = conn.execute(
            """
            SELECT *
            FROM properties
            WHERE property_type IN ('house', 'farm')
              AND energy_updated_at IS NOT NULL
            ORDER BY id
            """
        ).fetchall()

        changed = 0
        skipped = 0

        for row in rows:

            p = dict(row)

            status = str(
                p.get(
                    "energy_certificate_status"
                )
                or "unknown"
            ).strip().lower()

            if status not in TARGET_STATUSES:
                skipped += 1
                continue

            result = score_house(
                p
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
                    p["id"],
                )
            )

            changed += 1

        conn.commit()

        print(
            f"✅ Energie-Rescore: {changed} geändert"
        )
        print(
            f"ℹ️ Andere Energiezustände: {skipped} übersprungen"
        )

    finally:
        conn.close()


if __name__ == "__main__":
    main()
