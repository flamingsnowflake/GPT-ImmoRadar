import json
import sqlite3
from datetime import datetime, timezone


VALID_STATUSES = {
    "active",
    "offline",
    "not_interested",
}


# Schema-/Legacy-Migrationen sind Initialisierung, keine Leseoperation.
# Besonders das Energie-Labor pollt häufig; deshalb pro Prozess und DB
# nur einmal ausführen, statt bei jeder Abfrage Schreiblocks zu erzeugen.
_ENSURED_DATABASES = set()


def _score_details(value):

    if isinstance(value, dict):
        return value

    if not value:
        return {}

    try:
        data = json.loads(value)
    except Exception:
        return {}

    return data if isinstance(data, dict) else {}


def _restore_legacy_scoring(conn):

    rows = conn.execute(
        """
        SELECT
            id,
            portal_id,
            rating,
            score_details
        FROM properties
        WHERE rating IN (
            'offline',
            'not_interested'
        )
        """
    ).fetchall()

    now = datetime.now(
        timezone.utc
    ).isoformat()

    for row in rows:

        property_id = row[0]
        portal_id = row[1]
        legacy_rating = row[2]
        details = _score_details(
            row[3]
        )

        conn.execute(
            """
            INSERT INTO property_user_status (
                portal_id,
                status,
                updated_at
            )
            VALUES (?, ?, ?)
            ON CONFLICT(portal_id)
            DO UPDATE SET
                status = excluded.status,
                updated_at = excluded.updated_at
            """,
            (
                portal_id,
                legacy_rating,
                now,
            )
        )

        computed_rating = details.get(
            "rating"
        )

        if computed_rating is None:
            continue

        computed_score = details.get(
            "score"
        )

        computed_ko = int(
            bool(
                details.get(
                    "ko",
                    False,
                )
            )
        )

        conn.execute(
            """
            UPDATE properties
            SET
                score = ?,
                rating = ?,
                is_ko = ?
            WHERE id = ?
            """,
            (
                computed_score,
                computed_rating,
                computed_ko,
                property_id,
            )
        )


def _migrate_spam_objects(conn):

    table = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = 'spam_objects'
        LIMIT 1
        """
    ).fetchone()

    if not table:
        return

    now = datetime.now(
        timezone.utc
    ).isoformat()

    rows = conn.execute(
        """
        SELECT portal_id
        FROM spam_objects
        """
    ).fetchall()

    for row in rows:

        portal_id = row[0]

        existing = conn.execute(
            """
            SELECT status
            FROM property_user_status
            WHERE portal_id = ?
            LIMIT 1
            """,
            (
                portal_id,
            )
        ).fetchone()

        if existing:
            continue

        conn.execute(
            """
            INSERT INTO property_user_status (
                portal_id,
                status,
                updated_at
            )
            VALUES (?, 'not_interested', ?)
            """,
            (
                portal_id,
                now,
            )
        )


def ensure_user_status_table(db_path):

    database_key = str(db_path)

    if database_key in _ENSURED_DATABASES:
        return

    conn = sqlite3.connect(
        db_path,
        timeout=10,
    )

    try:

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS property_user_status (
                portal_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

        _restore_legacy_scoring(
            conn
        )

        _migrate_spam_objects(
            conn
        )

        conn.commit()

        _ENSURED_DATABASES.add(
            database_key
        )

    finally:
        conn.close()


def get_user_status(db_path, portal_id):

    ensure_user_status_table(
        db_path
    )

    conn = sqlite3.connect(
        db_path,
        timeout=10,
    )

    try:

        row = conn.execute(
            """
            SELECT status
            FROM property_user_status
            WHERE portal_id = ?
            LIMIT 1
            """,
            (
                portal_id,
            )
        ).fetchone()

    finally:
        conn.close()

    if not row:
        return "active"

    status = str(
        row[0]
        or "active"
    ).strip().lower()

    if status not in VALID_STATUSES:
        return "active"

    return status


def _ensure_spam_table(conn):

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS spam_objects (
            portal TEXT NOT NULL,
            portal_id TEXT NOT NULL,
            title TEXT,
            marked_at TEXT NOT NULL,
            UNIQUE(portal, portal_id)
        )
        """
    )


def set_user_status(
    db_path,
    portal_id,
    status,
):

    status = str(
        status
        or "active"
    ).strip().lower()

    if status not in VALID_STATUSES:
        raise ValueError(
            f"Unbekannter Benutzerstatus: {status}"
        )

    ensure_user_status_table(
        db_path
    )

    conn = sqlite3.connect(
        db_path,
        timeout=10,
    )

    conn.row_factory = sqlite3.Row

    try:

        row = conn.execute(
            """
            SELECT
                portal,
                portal_id,
                title,
                property_type
            FROM properties
            WHERE portal_id = ?
            ORDER BY
                last_seen DESC,
                id DESC
            LIMIT 1
            """,
            (
                portal_id,
            )
        ).fetchone()

        if not row:
            raise LookupError(
                f"Objekt {portal_id} nicht gefunden"
            )

        portal = row["portal"]
        title = row["title"]
        property_type = (
            row["property_type"]
            or "unknown"
        )

        _ensure_spam_table(
            conn
        )

        if status == "not_interested":

            conn.execute(
                """
                INSERT OR IGNORE INTO spam_objects (
                    portal,
                    portal_id,
                    title,
                    marked_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    portal,
                    portal_id,
                    title,
                    datetime.now(
                        timezone.utc
                    ).isoformat(),
                )
            )

        else:

            conn.execute(
                """
                DELETE FROM spam_objects
                WHERE portal = ?
                  AND portal_id = ?
                """,
                (
                    portal,
                    portal_id,
                )
            )

        if status == "active":

            conn.execute(
                """
                DELETE FROM property_user_status
                WHERE portal_id = ?
                """,
                (
                    portal_id,
                )
            )

        else:

            conn.execute(
                """
                INSERT INTO property_user_status (
                    portal_id,
                    status,
                    updated_at
                )
                VALUES (?, ?, ?)
                ON CONFLICT(portal_id)
                DO UPDATE SET
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (
                    portal_id,
                    status,
                    datetime.now(
                        timezone.utc
                    ).isoformat(),
                )
            )

        conn.commit()

        return {
            "portal_id": portal_id,
            "portal": portal,
            "title": title,
            "property_type": property_type,
            "status": status,
        }

    finally:
        conn.close()


def toggle_user_status(
    db_path,
    portal_id,
    target_status,
):

    target_status = str(
        target_status
        or ""
    ).strip().lower()

    if target_status not in (
        "offline",
        "not_interested",
    ):
        raise ValueError(
            "toggle_user_status erwartet offline "
            "oder not_interested"
        )

    current = get_user_status(
        db_path,
        portal_id,
    )

    new_status = (
        "active"
        if current == target_status
        else target_status
    )

    return set_user_status(
        db_path,
        portal_id,
        new_status,
    )
