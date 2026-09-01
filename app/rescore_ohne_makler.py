#!/usr/bin/env python3

import json
import os
import sqlite3

from property_types import is_house_type
from scoring import (
    score_house,
    score_land,
)


DB_PATH = os.environ.get(
    "DB_PATH",
    "/data/database.sqlite3",
)


def main():

    conn = sqlite3.connect(
        DB_PATH,
        timeout=30,
    )

    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        """
        SELECT *
        FROM properties
        WHERE
            LOWER(COALESCE(url, ''))
                LIKE '%ohne-makler.net%'
            OR REPLACE(
                REPLACE(
                    LOWER(COALESCE(portal, '')),
                    '_',
                    '-'
                ),
                ' ',
                '-'
            ) IN (
                'ohne-makler',
                'ohnemakler',
                'ohne-makler.net'
            )
        ORDER BY id
        """
    ).fetchall()

    updated = 0
    skipped = 0

    for row in rows:

        property_data = dict(
            row
        )

        property_type = (
            property_data.get(
                "property_type"
            )
            or "unknown"
        )

        if is_house_type(
            property_type
        ):

            result = score_house(
                property_data
            )

        elif property_type == "land":

            result = score_land(
                property_data
            )

        else:

            skipped += 1
            continue

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
                property_data["id"],
            )
        )

        updated += 1

        print(
            "RESCORE OHNE-MAKLER: "
            f"{property_data.get('portal_id')} | "
            f"score={result.get('score')} | "
            f"rating={result.get('rating')}",
            flush=True,
        )

    conn.commit()
    conn.close()

    print()
    print(
        f"Aktualisiert: {updated}"
    )
    print(
        f"Übersprungen: {skipped}"
    )


if __name__ == "__main__":
    main()
