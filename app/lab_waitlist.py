import sqlite3
from datetime import datetime, timezone


VALID_LAB_KINDS = {
    "condition",
    "locality",
}


def _validate_kind(kind):

    value = str(
        kind
        or ""
    ).strip().lower()

    if value not in VALID_LAB_KINDS:
        raise ValueError(
            f"Unbekannte Labor-Warteliste: {value}"
        )

    return value


def ensure_lab_waitlist_table(db_path):

    conn = sqlite3.connect(
        db_path,
        timeout=10,
    )

    try:

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS lab_information_requests (
                portal_id TEXT NOT NULL,
                lab_kind TEXT NOT NULL,
                requested_at TEXT NOT NULL,
                PRIMARY KEY (portal_id, lab_kind)
            )
            """
        )

        conn.commit()

    finally:
        conn.close()


def mark_information_requested(
    db_path,
    portal_id,
    kind,
):

    kind = _validate_kind(kind)

    ensure_lab_waitlist_table(
        db_path
    )

    conn = sqlite3.connect(
        db_path,
        timeout=10,
    )

    try:

        conn.execute(
            """
            INSERT INTO lab_information_requests (
                portal_id,
                lab_kind,
                requested_at
            )
            VALUES (?, ?, ?)
            ON CONFLICT(portal_id, lab_kind)
            DO UPDATE SET
                requested_at = excluded.requested_at
            """,
            (
                str(portal_id),
                kind,
                datetime.now(
                    timezone.utc
                ).isoformat(),
            ),
        )

        conn.commit()

    finally:
        conn.close()


def clear_information_requested(
    db_path,
    portal_id,
    kind=None,
):

    ensure_lab_waitlist_table(
        db_path
    )

    conn = sqlite3.connect(
        db_path,
        timeout=10,
    )

    try:

        if kind is None:

            conn.execute(
                """
                DELETE FROM lab_information_requests
                WHERE portal_id = ?
                """,
                (
                    str(portal_id),
                ),
            )

        else:

            conn.execute(
                """
                DELETE FROM lab_information_requests
                WHERE portal_id = ?
                  AND lab_kind = ?
                """,
                (
                    str(portal_id),
                    _validate_kind(kind),
                ),
            )

        conn.commit()

    finally:
        conn.close()


def waiting_portal_ids(
    db_path,
    kind,
):

    kind = _validate_kind(kind)

    ensure_lab_waitlist_table(
        db_path
    )

    conn = sqlite3.connect(
        db_path,
        timeout=10,
    )

    try:

        rows = conn.execute(
            """
            SELECT portal_id
            FROM lab_information_requests
            WHERE lab_kind = ?
            ORDER BY requested_at ASC
            """,
            (
                kind,
            ),
        ).fetchall()

    finally:
        conn.close()

    return {
        str(row[0])
        for row in rows
    }
