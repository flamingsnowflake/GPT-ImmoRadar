import sqlite3
from datetime import datetime, timezone

from monitor import (
    DB_PATH,
    classify_neighbours,
)

from enrichment import (
    find_neighbour_buildings,
)


def main():

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT
            id,
            portal,
            portal_id,
            title,
            location,
            latitude,
            longitude,
            neighbour_class,
            neighbour_checked_at
        FROM properties
        WHERE property_type = 'land'
          AND latitude IS NOT NULL
          AND longitude IS NOT NULL
          AND neighbour_checked_at IS NULL
        ORDER BY id
    """).fetchall()

    print(
        f"Found {len(rows)} LAND object(s) "
        f"without neighbour enrichment"
    )

    updated = 0
    failed = 0

    for row in rows:

        property_id = row["id"]
        portal_id = row["portal_id"]
        title = row["title"]
        latitude = row["latitude"]
        longitude = row["longitude"]

        print()
        print("=" * 70)
        print(
            f"{portal_id} | {title}"
        )
        print(
            f"{latitude:.6f}, {longitude:.6f}"
        )

        try:

            buildings = find_neighbour_buildings(
                latitude,
                longitude
            )

            neighbour_class = classify_neighbours(
                buildings
            )

            checked_at = datetime.now(
                timezone.utc
            ).isoformat()

            conn.execute(
                """
                UPDATE properties
                SET
                    nearest_building_m = ?,
                    buildings_100m = ?,
                    buildings_250m = ?,
                    buildings_500m = ?,
                    neighbour_class = ?,
                    neighbour_checked_at = ?
                WHERE id = ?
                """,
                (
                    buildings.get(
                        "nearest_building_m"
                    ),
                    buildings.get(
                        "buildings_100m"
                    ),
                    buildings.get(
                        "buildings_250m"
                    ),
                    buildings.get(
                        "buildings_500m"
                    ),
                    neighbour_class,
                    checked_at,
                    property_id
                )
            )

            conn.commit()

            print(
                f"CLASS: {neighbour_class}"
            )

            print(
                f"nearest: "
                f"{buildings.get('nearest_building_m')}"
            )

            print(
                f"100m={buildings.get('buildings_100m')} | "
                f"250m={buildings.get('buildings_250m')} | "
                f"500m={buildings.get('buildings_500m')}"
            )

            updated += 1

        except Exception as exc:

            print(
                f"ERROR: "
                f"{type(exc).__name__}: {exc}"
            )

            failed += 1

    print()
    print("=" * 70)
    print(
        f"Updated: {updated}"
    )
    print(
        f"Failed:  {failed}"
    )

    conn.close()


if __name__ == "__main__":
    main()
