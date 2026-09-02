import argparse
import json
import os
import sqlite3
from collections import Counter
from datetime import datetime, timezone

from config_loader import CONFIG
from geo_precision import (
    GEO_DERIVED_FIELDS,
    GEO_PRECISION_EXACT,
    classify_geo_precision,
    clear_geo_derived_data,
)
from property_types import is_house_type
from scoring import score_house, score_land


DEFAULT_DB_PATH = os.environ.get(
    "DB_PATH",
    "/data/database.sqlite3",
)


def _score(property_data):

    property_type = property_data.get(
        "property_type"
    )

    if property_type == "land":
        return score_land(property_data)

    if is_house_type(property_type):
        return score_house(property_data)

    return None


def _prepare_row(row):

    before = dict(row)
    after = dict(row)

    precision = classify_geo_precision(
        after
    )

    after["geo_precision"] = precision

    removed_coordinates = False

    if precision != GEO_PRECISION_EXACT:
        removed_coordinates = (
            after.get("latitude") is not None
            or after.get("longitude") is not None
        )

        clear_geo_derived_data(after)

    score_result = _score(after)

    if score_result is not None:
        after["score"] = score_result.get("score")
        after["rating"] = score_result.get("rating")
        after["is_ko"] = int(
            bool(score_result.get("ko"))
        )
        after["score_details"] = json.dumps(
            score_result,
            ensure_ascii=False,
        )

    changed = any(
        before.get(field) != after.get(field)
        for field in (
            "geo_precision",
            "score",
            "rating",
            "is_ko",
            "score_details",
            *GEO_DERIVED_FIELDS,
        )
    )

    return after, changed, removed_coordinates


def _backup_database(conn, db_path):

    backup_dir = os.path.join(
        os.path.dirname(db_path),
        "backups",
    )

    os.makedirs(
        backup_dir,
        exist_ok=True,
    )

    timestamp = datetime.now(
        timezone.utc
    ).strftime("%Y%m%dT%H%M%SZ")

    backup_path = os.path.join(
        backup_dir,
        f"database.before-geo-precision.{timestamp}.sqlite3",
    )

    backup_conn = sqlite3.connect(
        backup_path
    )

    try:
        conn.backup(backup_conn)
    finally:
        backup_conn.close()

    return backup_path


def run(db_path, apply=False, sample_size=20):

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    columns = {
        row[1]
        for row in conn.execute(
            "PRAGMA table_info(properties)"
        )
    }

    has_geo_precision = (
        "geo_precision" in columns
    )

    rows = conn.execute(
        """
        SELECT *
        FROM properties
        ORDER BY id
        """
    ).fetchall()

    prepared = []
    precision_counts = Counter()
    changed_count = 0
    removed_coordinate_count = 0

    for row in rows:
        after, changed, removed = _prepare_row(row)
        prepared.append(after)
        precision_counts[
            after["geo_precision"]
        ] += 1
        changed_count += int(changed)
        removed_coordinate_count += int(removed)

    print(
        "GEO PRECISION DRY-RUN"
        if not apply
        else "GEO PRECISION APPLY",
        flush=True,
    )
    print(f"Database: {db_path}", flush=True)
    print(f"Objects: {len(rows)}", flush=True)
    print(
        "Precision: "
        f"exact={precision_counts['exact']} | "
        f"locality={precision_counts['locality']} | "
        f"missing={precision_counts['missing']}",
        flush=True,
    )
    print(
        f"Rows changed: {changed_count}",
        flush=True,
    )
    print(
        "Inexact coordinate sets to remove: "
        f"{removed_coordinate_count}",
        flush=True,
    )

    shown = 0

    for before, after in zip(rows, prepared):
        if shown >= sample_size:
            break

        if (
            before["score"] == after.get("score")
            and before["rating"] == after.get("rating")
            and (
                before["geo_precision"]
                if has_geo_precision
                else None
            ) == after.get("geo_precision")
        ):
            continue

        try:
            details = json.loads(
                after.get("score_details")
                or "{}"
            )
        except (
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ):
            details = {}

        if details.get("provisional"):
            score_text = (
                f"{details['score_min']}–"
                f"{details['score_max']}"
            )
        else:
            score_text = str(
                after.get("score")
            )

        print(
            f"{after.get('portal_id')} | "
            f"{after.get('geo_precision')} | "
            f"{before['score']} -> {score_text} | "
            f"{after.get('location') or '-'}",
            flush=True,
        )
        shown += 1

    if not apply:
        conn.close()
        print(
            "No database changes written. "
            "Use --apply only after reviewing this output.",
            flush=True,
        )
        return

    backup_path = _backup_database(
        conn,
        db_path,
    )

    if not has_geo_precision:
        conn.execute(
            """
            ALTER TABLE properties
            ADD COLUMN geo_precision TEXT
            """
        )

    update_fields = (
        "geo_precision",
        *GEO_DERIVED_FIELDS,
        "score",
        "rating",
        "is_ko",
        "score_details",
    )

    assignments = ", ".join(
        f"{field} = ?"
        for field in update_fields
    )

    with conn:
        for after in prepared:
            values = [
                after.get(field)
                for field in update_fields
            ]
            values.append(after["id"])

            conn.execute(
                f"""
                UPDATE properties
                SET {assignments}
                WHERE id = ?
                """,
                values,
            )

    conn.close()

    print(
        f"Backup: {backup_path}",
        flush=True,
    )
    print(
        "Geo precision backfill committed.",
        flush=True,
    )


def main():

    parser = argparse.ArgumentParser(
        description=(
            "Classify exact/locality/missing geo precision "
            "and rescore without using locality centroids."
        )
    )
    parser.add_argument(
        "--db",
        default=DEFAULT_DB_PATH,
    )
    parser.add_argument(
        "--config-dir",
        default="/config",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=20,
    )
    parser.add_argument(
        "--apply",
        action="store_true",
    )
    args = parser.parse_args()

    CONFIG.config_dir = args.config_dir

    run(
        args.db,
        apply=args.apply,
        sample_size=max(0, args.sample_size),
    )


if __name__ == "__main__":
    main()
