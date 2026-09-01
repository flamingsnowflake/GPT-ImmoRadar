import argparse
import json
import sqlite3
import time
from datetime import datetime, timezone

from monitor import DB_PATH
from noise_sources import get_noise
from scoring import score_land, score_house
from property_types import is_house_type


def effective_coordinates(row):

    manual_lat = row["manual_latitude"]
    manual_lon = row["manual_longitude"]

    if (
        manual_lat is not None
        and manual_lon is not None
    ):
        return (
            float(manual_lat),
            float(manual_lon),
            "manual",
        )

    lat = row["latitude"]
    lon = row["longitude"]

    if (
        lat is not None
        and lon is not None
    ):
        return (
            float(lat),
            float(lon),
            "automatic",
        )

    return (
        None,
        None,
        "missing",
    )


def score_property(property_data):

    property_type = (
        property_data.get("property_type")
        or ""
    )

    if property_type == "land":
        return score_land(property_data)

    if is_house_type(property_type):
        return score_house(property_data)

    return None


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximale Anzahl Objekte",
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help="Alle offenen Objekte bearbeiten",
    )

    args = parser.parse_args()

    conn = sqlite3.connect(
        DB_PATH
    )

    conn.row_factory = sqlite3.Row

    where = """
        noise_checked_at IS NULL
        AND (
            (
                manual_latitude IS NOT NULL
                AND manual_longitude IS NOT NULL
            )
            OR
            (
                latitude IS NOT NULL
                AND longitude IS NOT NULL
            )
        )
    """

    total = conn.execute(
        f"""
        SELECT COUNT(*)
        FROM properties
        WHERE {where}
        """
    ).fetchone()[0]

    sql = f"""
        SELECT *
        FROM properties
        WHERE {where}
        ORDER BY id
    """

    params = ()

    if not args.all:

        sql += """
        LIMIT ?
        """

        params = (
            args.limit,
        )

    rows = conn.execute(
        sql,
        params,
    ).fetchall()

    print(
        "=" * 78,
        flush=True,
    )

    print(
        f"NOISE BACKFILL | offen insgesamt: {total} "
        f"| dieser Lauf: {len(rows)}",
        flush=True,
    )

    print(
        "=" * 78,
        flush=True,
    )

    successful = 0
    failed = 0
    skipped = 0

    started = time.monotonic()

    for number, row in enumerate(
        rows,
        1,
    ):

        property_data = dict(row)

        portal_id = (
            property_data.get("portal_id")
            or "?"
        )

        title = (
            property_data.get("title")
            or ""
        )

        (
            latitude,
            longitude,
            coordinate_source,
        ) = effective_coordinates(row)

        if (
            latitude is None
            or longitude is None
        ):

            skipped += 1

            print(
                f"[{number}/{len(rows)}] "
                f"SKIP {portal_id}: "
                "keine Koordinaten",
                flush=True,
            )

            continue

        print()
        print(
            f"[{number}/{len(rows)}] "
            f"{portal_id}",
            flush=True,
        )

        print(
            f"  {title[:90]}",
            flush=True,
        )

        print(
            f"  📍 {latitude:.6f}, "
            f"{longitude:.6f} "
            f"({coordinate_source})",
            flush=True,
        )

        object_started = (
            time.monotonic()
        )

        try:

            noise = get_noise(
                latitude,
                longitude,
            )

            rail = (
                noise.get("rail")
                or {}
            )

            road = (
                noise.get("road")
                or {}
            )

            air = (
                noise.get("air")
                or {}
            )

            property_data[
                "rail_lden"
            ] = rail.get("lden")

            property_data[
                "rail_lnight"
            ] = rail.get("lnight")

            property_data[
                "rail_distance_m"
            ] = rail.get(
                "rail_distance_m"
            )

            property_data[
                "rail_annual_traffic"
            ] = rail.get(
                "annual_traffic"
            )

            property_data[
                "road_lden"
            ] = road.get("lden")

            property_data[
                "road_lnight"
            ] = road.get("lnight")

            property_data[
                "road_noise_source"
            ] = road.get("source")

            property_data[
                "air_lden"
            ] = air.get("lden")

            property_data[
                "air_lnight"
            ] = air.get("lnight")

            property_data[
                "air_noise_source"
            ] = air.get("source")

            checked_at = (
                datetime.now(
                    timezone.utc
                ).isoformat()
            )

            property_data[
                "noise_checked_at"
            ] = checked_at

            score_result = (
                score_property(
                    property_data
                )
            )

            if score_result is not None:

                property_data[
                    "score"
                ] = score_result[
                    "score"
                ]

                property_data[
                    "rating"
                ] = score_result[
                    "rating"
                ]

                property_data[
                    "is_ko"
                ] = int(
                    score_result["ko"]
                )

                property_data[
                    "score_details"
                ] = score_result

            else:

                score_result = None

            conn.execute(
                """
                UPDATE properties
                SET
                    rail_lden = ?,
                    rail_lnight = ?,
                    rail_distance_m = ?,
                    rail_annual_traffic = ?,

                    road_lden = ?,
                    road_lnight = ?,
                    road_noise_source = ?,

                    air_lden = ?,
                    air_lnight = ?,
                    air_noise_source = ?,

                    noise_checked_at = ?,

                    score = ?,
                    rating = ?,
                    is_ko = ?,
                    score_details = ?

                WHERE id = ?
                """,
                (
                    property_data.get(
                        "rail_lden"
                    ),
                    property_data.get(
                        "rail_lnight"
                    ),
                    property_data.get(
                        "rail_distance_m"
                    ),
                    property_data.get(
                        "rail_annual_traffic"
                    ),

                    property_data.get(
                        "road_lden"
                    ),
                    property_data.get(
                        "road_lnight"
                    ),
                    property_data.get(
                        "road_noise_source"
                    ),

                    property_data.get(
                        "air_lden"
                    ),
                    property_data.get(
                        "air_lnight"
                    ),
                    property_data.get(
                        "air_noise_source"
                    ),

                    checked_at,

                    property_data.get(
                        "score"
                    ),
                    property_data.get(
                        "rating"
                    ),
                    property_data.get(
                        "is_ko",
                        0,
                    ),

                    (
                        json.dumps(
                            property_data[
                                "score_details"
                            ],
                            ensure_ascii=False,
                        )
                        if property_data.get(
                            "score_details"
                        ) is not None
                        else None
                    ),

                    property_data["id"],
                )
            )

            conn.commit()

            elapsed = (
                time.monotonic()
                - object_started
            )

            rail_text = (
                f"{rail.get('lden')}/"
                f"{rail.get('lnight')}"
            )

            road_text = (
                f"{road.get('lden')}/"
                f"{road.get('lnight')}"
            )

            air_text = (
                f"{air.get('lden')}/"
                f"{air.get('lnight')}"
            )

            print(
                f"  🚆 rail: {rail_text}",
                flush=True,
            )

            print(
                f"  🚗 road: {road_text}",
                flush=True,
            )

            print(
                f"  ✈️  air:  {air_text}",
                flush=True,
            )

            if score_result is not None:

                print(
                    f"  SCORE: "
                    f"{score_result['score']}/100 "
                    f"| {score_result['rating']} "
                    f"| KO={score_result['ko']}",
                    flush=True,
                )

            print(
                f"  OK in {elapsed:.1f}s",
                flush=True,
            )

            successful += 1

        except Exception as exc:

            failed += 1

            elapsed = (
                time.monotonic()
                - object_started
            )

            print(
                f"  ERROR after "
                f"{elapsed:.1f}s: "
                f"{type(exc).__name__}: "
                f"{exc}",
                flush=True,
            )

            # noise_checked_at bleibt NULL.
            # Ein späterer Lauf probiert das
            # Objekt automatisch erneut.
            continue

        total_elapsed = (
            time.monotonic()
            - started
        )

        average = (
            total_elapsed
            / max(
                1,
                number,
            )
        )

        remaining = (
            len(rows)
            - number
        )

        eta_minutes = (
            average
            * remaining
            / 60.0
        )

        print(
            f"  Fortschritt: "
            f"{number}/{len(rows)} "
            f"| ETA ~{eta_minutes:.1f} min",
            flush=True,
        )

    conn.close()

    print()
    print(
        "=" * 78,
        flush=True,
    )

    print(
        "BACKFILL FERTIG",
        flush=True,
    )

    print(
        f"OK={successful} "
        f"ERROR={failed} "
        f"SKIP={skipped}",
        flush=True,
    )

    print(
        "=" * 78,
        flush=True,
    )


if __name__ == "__main__":
    main()
