import sqlite3
from datetime import datetime, timezone


TERMINAL_STATUSES = frozenset({
    "purged",
    "blacklisted",
})


def ensure_terminal_table(conn):

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS browser_terminal_events (
            portal TEXT NOT NULL,
            portal_id TEXT NOT NULL,
            status TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (portal, portal_id)
        )
        """
    )


def record_terminal_event(
    conn,
    portal,
    portal_id,
    status,
    *,
    updated_at=None,
):

    portal = str(
        portal or ""
    ).strip().lower()

    portal_id = str(
        portal_id or ""
    ).strip()

    status = str(
        status or ""
    ).strip().lower()

    if (
        not portal
        or not portal_id
        or status not in TERMINAL_STATUSES
    ):
        raise ValueError(
            "Ungültiger Browser-Terminalstatus"
        )

    ensure_terminal_table(
        conn
    )

    if updated_at is None:
        updated_at = datetime.now(
            timezone.utc
        ).isoformat()

    conn.execute(
        """
        INSERT INTO browser_terminal_events (
            portal,
            portal_id,
            status,
            updated_at
        )
        VALUES (?, ?, ?, ?)
        ON CONFLICT(portal, portal_id)
        DO UPDATE SET
            status = excluded.status,
            updated_at = excluded.updated_at
        """,
        (
            portal,
            portal_id,
            status,
            updated_at,
        )
    )


def clear_terminal_event(
    conn,
    portal,
    portal_id,
):

    if not _table_exists(
        conn,
        "browser_terminal_events",
    ):
        return

    conn.execute(
        """
        DELETE FROM browser_terminal_events
        WHERE portal = ?
          AND portal_id = ?
        """,
        (
            str(
                portal or ""
            ).strip().lower(),
            str(
                portal_id or ""
            ).strip(),
        )
    )


def get_terminal_event(
    db_path,
    portal,
    portal_id,
    *,
    since=None,
):

    portal = str(
        portal or ""
    ).strip().lower()

    portal_id = str(
        portal_id or ""
    ).strip()

    if (
        not portal
        or not portal_id
    ):
        return None

    conn = sqlite3.connect(
        db_path,
        timeout=5,
    )

    try:

        table = conn.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'browser_terminal_events'
            LIMIT 1
            """
        ).fetchone()

        if not table:
            return None

        row = conn.execute(
            """
            SELECT
                status,
                updated_at
            FROM browser_terminal_events
            WHERE portal = ?
              AND portal_id = ?
            LIMIT 1
            """,
            (
                portal,
                portal_id,
            )
        ).fetchone()

    finally:
        conn.close()

    if not row:
        return None

    status = str(
        row[0] or ""
    ).strip().lower()

    updated_at = str(
        row[1] or ""
    ).strip()

    if status not in TERMINAL_STATUSES:
        return None

    if (
        since
        and updated_at
        and updated_at < str(since)
    ):
        return None

    return {
        "status": status,
        "updated_at": updated_at,
    }


def page_is_unavailable(
    page_text,
    heading=None,
):

    text = " ".join(
        str(
            page_text or ""
        ).split()
    ).casefold()

    heading_text = " ".join(
        str(
            heading or ""
        ).split()
    ).casefold()

    markers = (
        "dieses angebot ist nicht mehr verfügbar",
        "dieses angebot ist leider nicht mehr verfügbar",
        "das angebot ist nicht mehr verfügbar",
        "dieses immobilienangebot ist nicht mehr verfügbar",
        "die von ihnen aufgerufene immobilie ist nicht mehr verfügbar",
        "dieses exposé ist nicht mehr verfügbar",
        "dieses expose ist nicht mehr verfügbar",
        "dieses objekt ist nicht mehr verfügbar",
        "diese immobilie ist nicht mehr verfügbar",
        "diese immobilie ist leider nicht mehr verfügbar",
        "das angebot wurde deaktiviert",
        "dieses angebot wurde deaktiviert",
        "das exposé wurde deaktiviert",
        "das expose wurde deaktiviert",
        "dieses angebot wurde gelöscht",
        "das angebot wurde gelöscht",
        "anzeige gelöscht",
        "diese anzeige wurde gelöscht",
        "diese anzeige wurde bereits gelöscht",
        "angebot nicht gefunden",
        "anzeige bereits gelöscht",
        "wurde die anzeige bereits gelöscht",
    )

    haystack = (
        heading_text
        + " "
        + text[:6000]
    )

    return any(
        marker in haystack
        for marker in markers
    )


def _table_exists(
    conn,
    table_name,
):

    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        LIMIT 1
        """,
        (
            table_name,
        )
    ).fetchone()

    return row is not None


def purge_property(
    conn,
    property_id,
    portal,
    portal_id,
):

    if _table_exists(
        conn,
        "property_searches",
    ):
        conn.execute(
            """
            DELETE FROM property_searches
            WHERE property_id = ?
            """,
            (
                property_id,
            )
        )

    if _table_exists(
        conn,
        "property_favorites",
    ):
        conn.execute(
            """
            DELETE FROM property_favorites
            WHERE portal_id = ?
            """,
            (
                portal_id,
            )
        )

    if _table_exists(
        conn,
        "property_user_status",
    ):
        conn.execute(
            """
            DELETE FROM property_user_status
            WHERE portal_id = ?
            """,
            (
                portal_id,
            )
        )

    conn.execute(
        """
        DELETE FROM properties
        WHERE id = ?
        """,
        (
            property_id,
        )
    )

    record_terminal_event(
        conn,
        portal,
        portal_id,
        "purged",
    )
