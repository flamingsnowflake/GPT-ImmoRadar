import json
import sqlite3

from monitor import (
    DB_PATH,
    is_blacklisted,
)

from scoring import (
    score_land,
)


def main():

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT *
        FROM properties
        WHERE property_type = 'land'
        ORDER BY id
    """).fetchall()

    print(f"Found {len(rows)} LAND object(s)")

    rescored = 0
    blacklisted = 0
    failed = 0

    for row in rows:

        property_data = dict(row)

        portal_id = property_data.get("portal_id")
        title = property_data.get("title")
        location = property_data.get("location")
        url = property_data.get("url")

        print()
        print("=" * 80)
        print(f"{portal_id} | {title}")

        try:

            # ------------------------------------------------
            # Blacklist
            # ------------------------------------------------

            if is_blacklisted(
                title,
                location,
                url,
                title,
                property_type="land",
            ):

                print("BLACKLISTED")

                conn.execute(
                    """
                    UPDATE properties
                    SET
                        score = NULL,
                        rating = 'blacklisted',
                        is_ko = 1,
                        score_details = ?
                    WHERE id = ?
                    """,
                    (
                        json.dumps(
                            {
                                "blacklisted": True
                            },
                            ensure_ascii=False
                        ),
                        property_data["id"]
                    )
                )

                conn.commit()

                blacklisted += 1
                continue

            # ------------------------------------------------
            # Score neu berechnen
            # ------------------------------------------------

            result = score_land(
                property_data
            )

            score = result["score"]
            rating = result["rating"]
            is_ko = int(result["ko"])

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
                    score,
                    rating,
                    is_ko,
                    json.dumps(
                        result,
                        ensure_ascii=False
                    ),
                    property_data["id"]
                )
            )

            conn.commit()

            print(
                f"SCORE: "
                f"{score}/100 | "
                f"{rating} | "
                f"KO={bool(is_ko)}"
            )

            neighbour_class = property_data.get(
                "neighbour_class"
            )

            water = property_data.get(
                "water_distance_km"
            )

            print(
                f"NEIGHBOURS: {neighbour_class} | "
                f"WATER: {water}"
            )

            rescored += 1

        except Exception as exc:

            print(
                f"ERROR: "
                f"{type(exc).__name__}: {exc}"
            )

            failed += 1

    print()
    print("=" * 80)
    print(f"Rescored:    {rescored}")
    print(f"Blacklisted: {blacklisted}")
    print(f"Failed:      {failed}")

    conn.close()


if __name__ == "__main__":
    main()
