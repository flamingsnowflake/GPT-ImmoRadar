import json
import sqlite3
import urllib.parse
import urllib.request
import urllib.error
import os
import yaml
import time
import re

from monitor import (
    DB_PATH,
    TELEGRAM_TOKEN,
    TELEGRAM_CHAT_ID,
    enrich_property,
)

from scoring import (
    score_land,
    score_house,
)
from config_loader import CONFIG
from property_types import (
    is_house_type,
    property_type_label,
)
from telegram_ui import (
    property_action_keyboard as _property_action_keyboard,
)
from energy_data import format_energy_summary
from geo_precision import (
    conservative_score,
    provisional_score_range,
)
from incomplete_workflow import (
    overview_text as incomplete_overview_text,
    overview_keyboard as incomplete_overview_keyboard,
    first_condition as incomplete_first_condition,
    condition_rows as incomplete_condition_rows,
    condition_text as incomplete_condition_text,
    condition_keyboard as incomplete_condition_keyboard,
    first_energy as incomplete_first_energy,
    energy_rows as incomplete_energy_rows,
    energy_text as incomplete_energy_text,
    energy_keyboard as incomplete_energy_keyboard,
    first_geo as incomplete_first_geo,
    geo_text as incomplete_geo_text,
    geo_keyboard as incomplete_geo_keyboard,
    first_locality as incomplete_first_locality,
    locality_text as incomplete_locality_text,
    locality_keyboard as incomplete_locality_keyboard,
    locality_rows as incomplete_locality_rows,
)
from incomplete_energy import (
    energy_choice_label,
    set_energy_choice,
    set_energy_value,
)
from energy_lab_auto import (
    next_energy_action,
)
from locality_lab import LocalityLab
from dog_tax_store import (
    database as dog_tax_database,
    load_stored_tariff,
    property_tax_text,
    research_queue as dog_tax_research_queue,
    save_assignment_and_tariff,
)
from lab_terminal import (
    get_terminal_event,
)
from user_status import (
    ensure_user_status_table,
    get_user_status,
    toggle_user_status,
)
from datetime import datetime, timezone, timedelta

BUILDABILITY_MAP = {
    "BUILDING_PERMIT": {
        "allowed": True,
        "class": "residential",
        "reason": "Baugenehmigung vorhanden",
    },

    "CONSTRUCTIONPLAN": {
        "allowed": True,
        "class": "residential",
        "reason": "Bebauungsplan",
    },

    "NEIGHBOURCONSTRUCTION": {
        "allowed": True,
        "class": "residential",
        "reason": "Nachbarbebauung / §34",
    },

    "EXTERNALAREA": {
        "allowed": False,
        "class": "ko",
        "reason": "Außenbereich / §35",
    },

    "NO_INFORMATION": {
        "allowed": None,
        "class": "unknown",
        "reason": None,
    },
}


# ------------------------------------------------------------
# Pending coordinate input
#
# Nur der Dialogzustand lebt im RAM.
# Die gesetzten Koordinaten selbst werden dauerhaft in SQLite
# gespeichert.
# ------------------------------------------------------------

PENDING_COORDINATES = {}
PENDING_ENERGY_VALUES = {}
PENDING_DOG_TAX = {}
LOCALITY_LAB = LocalityLab()
SKIPPED_LOCALITY_LAB = LOCALITY_LAB.skipped


def refresh_active_locality_lab(prefix=None, check_terminal=True):
    session = LOCALITY_LAB.session
    if not session:
        return False
    terminal = get_terminal_event(
        DB_PATH, session['portal'], session['portal_id'],
        since=session['started_at'],
    ) if check_terminal else None
    status = (terminal or {}).get('status')
    action, row, total = LOCALITY_LAB.next_action(
        incomplete_locality_rows(DB_PATH), status,
    )
    if action == 'wait':
        return False
    if prefix is None:
        prefix = {
            'purged': '🗑 Objekt auf dem Portal nicht mehr verfügbar – entfernt.\n\n',
            'blacklisted': '🚫 Objekt wurde blacklisted.\n\n',
        }.get(status, '➡️ Weiter zur nächsten offenen Lage.\n\n')
    if row is None:
        text = prefix + '✅ Keine weiteren Lagen in diesem Durchgang.\n\n' + incomplete_overview_text(DB_PATH)
        keyboard = incomplete_overview_keyboard(DB_PATH)
    else:
        text = prefix + incomplete_locality_text(row, 1, total)
        keyboard = incomplete_locality_keyboard(row)
    try:
        telegram_api('editMessageText', {
            'chat_id': TELEGRAM_CHAT_ID,
            'message_id': session['message_id'],
            'text': text,
            'disable_web_page_preview': 'true',
            'reply_markup': json.dumps(keyboard),
        })
    except Exception as exc:
        print(f'LOCALITY LAB AUTO ADVANCE ERROR: {exc}', flush=True)
        return False
    for chat_id, pending in list(PENDING_COORDINATES.items()):
        if pending.get('number') == 'iwl' and pending.get('portal_id') == session['portal_id']:
            PENDING_COORDINATES.pop(chat_id, None)
    LOCALITY_LAB.track(session['message_id'], row)
    print(f"LOCALITY LAB AUTO ADVANCE: {session['portal_id']} -> {(row or {}).get('portal_id', 'done')}", flush=True)
    return True

# Aktive Energie-Labor-Karte.
# Während sie aktiv ist, wird der Telegram-Long-Poll kurz
# gehalten. Nach jedem Poll prüfen wir, ob der Browser das
# aktuell angezeigte Energieobjekt inzwischen abgeschlossen
# hat.
ACTIVE_ENERGY_LAB = None


def set_active_energy_lab(
    message_id,
    row,
):

    global ACTIVE_ENERGY_LAB

    if (
        not message_id
        or row is None
    ):
        ACTIVE_ENERGY_LAB = None
        return

    ACTIVE_ENERGY_LAB = {
        "message_id": message_id,
        "portal": str(
            row.get("portal")
            or ""
        ).strip().lower(),
        "portal_id": str(
            row.get("portal_id")
            or ""
        ),
        "started_at": datetime.now(
            timezone.utc
        ).isoformat(),
    }


def refresh_active_energy_lab():

    global ACTIVE_ENERGY_LAB

    session = ACTIVE_ENERGY_LAB

    if not session:
        return False

    rows = incomplete_energy_rows(
        DB_PATH
    )

    terminal = get_terminal_event(
        DB_PATH,
        session.get("portal"),
        session.get("portal_id"),
        since=session.get("started_at"),
    )

    terminal_status = (
        terminal.get("status")
        if terminal
        else None
    )

    if terminal_status:
        rows = [
            row
            for row in rows
            if str(
                row.get("portal_id")
                or ""
            ) != str(
                session.get("portal_id")
                or ""
            )
        ]

    action, next_row = next_energy_action(
        session.get("portal_id"),
        rows,
    )

    if action == "wait":
        return False

    if terminal_status == "purged":
        advance_prefix = (
            "🗑 Objekt auf dem Portal nicht mehr verfügbar – entfernt.\n\n"
        )
    elif terminal_status == "blacklisted":
        advance_prefix = (
            "🚫 Objekt wurde blacklisted.\n\n"
        )
    else:
        advance_prefix = (
            "➡️ Weiter zum nächsten offenen Objekt.\n\n"
        )

    if action == "done":

        text = (
            advance_prefix
            + "🎉 Keine offenen Energiedaten mehr.\n\n"
            + incomplete_overview_text(
                DB_PATH
            )
        )

        keyboard = incomplete_overview_keyboard(
            DB_PATH
        )

    else:

        text = (
            advance_prefix
            + incomplete_energy_text(
                next_row,
                1,
                len(rows),
            )
        )

        keyboard = incomplete_energy_keyboard(
            next_row
        )

    try:

        telegram_api(
            "editMessageText",
            {
                "chat_id":
                    TELEGRAM_CHAT_ID,
                "message_id":
                    session["message_id"],
                "text": text,
                "disable_web_page_preview":
                    "true",
                "reply_markup":
                    json.dumps(
                        keyboard
                    ),
            }
        )

    except Exception as exc:

        print(
            "ENERGY LAB AUTO ADVANCE ERROR: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )

        return False

    if action == "done":
        ACTIVE_ENERGY_LAB = None

    else:
        ACTIVE_ENERGY_LAB = {
            "message_id": session[
                "message_id"
            ],
            "portal": str(
                next_row.get("portal")
                or ""
            ).strip().lower(),
            "portal_id": str(
                next_row.get("portal_id")
                or ""
            ),
            "started_at": datetime.now(
                timezone.utc
            ).isoformat(),
        }

    print(
        "ENERGY LAB AUTO ADVANCE: "
        f"{session.get('portal_id')} -> "
        + (
            "done"
            if action == "done"
            else str(
                next_row.get("portal_id")
                or ""
            )
        ),
        flush=True,
    )

    return True


# Aktive Zustands-Labor-Karte.
# Nach jedem kurzen Poll wird geprüft, ob das aktuell
# angezeigte Objekt noch in der Zustands-Queue steht.
ACTIVE_CONDITION_LAB = None


def set_active_condition_lab(
    message_id,
    row,
):

    global ACTIVE_CONDITION_LAB

    if (
        not message_id
        or row is None
    ):
        ACTIVE_CONDITION_LAB = None
        return

    ACTIVE_CONDITION_LAB = {
        "message_id": message_id,
        "portal": str(
            row.get("portal")
            or ""
        ).strip().lower(),
        "portal_id": str(
            row.get("portal_id")
            or ""
        ),
        "started_at": datetime.now(
            timezone.utc
        ).isoformat(),
    }


def refresh_active_condition_lab():

    global ACTIVE_CONDITION_LAB

    session = ACTIVE_CONDITION_LAB

    if not session:
        return False

    rows = incomplete_condition_rows(
        DB_PATH
    )

    terminal = get_terminal_event(
        DB_PATH,
        session.get("portal"),
        session.get("portal_id"),
        since=session.get("started_at"),
    )

    terminal_status = (
        terminal.get("status")
        if terminal
        else None
    )

    if terminal_status:
        rows = [
            row
            for row in rows
            if str(
                row.get("portal_id")
                or ""
            ) != str(
                session.get("portal_id")
                or ""
            )
        ]

    action, next_row = next_energy_action(
        session.get("portal_id"),
        rows,
    )

    if action == "wait":
        return False

    if terminal_status == "purged":
        advance_prefix = (
            "🗑 Objekt auf dem Portal nicht mehr verfügbar – entfernt.\n\n"
        )
    elif terminal_status == "blacklisted":
        advance_prefix = (
            "🚫 Objekt wurde blacklisted.\n\n"
        )
    else:
        advance_prefix = (
            "➡️ Weiter zum nächsten offenen Objekt.\n\n"
        )

    if action == "done":

        text = (
            advance_prefix
            + "🎉 Keine offenen Zustände mehr.\n\n"
            + incomplete_overview_text(
                DB_PATH
            )
        )

        keyboard = incomplete_overview_keyboard(
            DB_PATH
        )

    else:

        text = (
            advance_prefix
            + incomplete_condition_text(
                next_row,
                1,
                len(rows),
            )
        )

        keyboard = incomplete_condition_keyboard(
            next_row
        )

    try:

        telegram_api(
            "editMessageText",
            {
                "chat_id":
                    TELEGRAM_CHAT_ID,
                "message_id":
                    session["message_id"],
                "text": text,
                "disable_web_page_preview":
                    "true",
                "reply_markup":
                    json.dumps(
                        keyboard
                    ),
            }
        )

    except Exception as exc:

        print(
            "CONDITION LAB AUTO ADVANCE ERROR: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )

        return False

    old_portal_id = session.get(
        "portal_id"
    )

    if action == "done":
        ACTIVE_CONDITION_LAB = None
        target = "done"

    else:
        ACTIVE_CONDITION_LAB = {
            "message_id": session[
                "message_id"
            ],
            "portal": str(
                next_row.get("portal")
                or ""
            ).strip().lower(),
            "portal_id": str(
                next_row.get("portal_id")
                or ""
            ),
            "started_at": datetime.now(
                timezone.utc
            ).isoformat(),
        }

        target = ACTIVE_CONDITION_LAB[
            "portal_id"
        ]

    print(
        "CONDITION LAB AUTO ADVANCE: "
        f"{old_portal_id} -> {target}",
        flush=True,
    )

    return True


def telegram_api(method, data=None):

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/{method}"
    )

    encoded = None

    if data is not None:
        encoded = urllib.parse.urlencode(
            data
        ).encode()

    request = urllib.request.Request(
        url,
        data=encoded
    )

    with urllib.request.urlopen(
        request,
        timeout=40
    ) as response:

        return json.loads(
            response.read().decode()
        )


def send_message(text, reply_markup=None):

    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": "true",
    }

    if reply_markup is not None:
        data["reply_markup"] = json.dumps(
            reply_markup
        )

    return telegram_api(
        "sendMessage",
        data
    )

# ------------------------------------------------------------
# Personal favorites / Merkliste
# ------------------------------------------------------------

def ensure_favorites_table():

    conn = sqlite3.connect(
        DB_PATH,
        timeout=10,
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS property_favorites (
            portal_id TEXT PRIMARY KEY,
            marked_at TEXT NOT NULL
        )
        """
    )

    conn.commit()
    conn.close()


def is_favorite(portal_id):

    ensure_favorites_table()

    conn = sqlite3.connect(
        DB_PATH,
        timeout=10,
    )

    row = conn.execute(
        """
        SELECT 1
        FROM property_favorites
        WHERE portal_id = ?
        LIMIT 1
        """,
        (
            portal_id,
        )
    ).fetchone()

    conn.close()

    return row is not None


def toggle_favorite(portal_id):

    ensure_favorites_table()

    conn = sqlite3.connect(
        DB_PATH,
        timeout=10,
    )

    row = conn.execute(
        """
        SELECT 1
        FROM property_favorites
        WHERE portal_id = ?
        LIMIT 1
        """,
        (
            portal_id,
        )
    ).fetchone()

    if row:

        conn.execute(
            """
            DELETE FROM property_favorites
            WHERE portal_id = ?
            """,
            (
                portal_id,
            )
        )

        favorite = False

    else:

        conn.execute(
            """
            INSERT INTO property_favorites (
                portal_id,
                marked_at
            )
            VALUES (?, ?)
            """,
            (
                portal_id,
                datetime.now(
                    timezone.utc
                ).isoformat(),
            )
        )

        favorite = True

    conn.commit()
    conn.close()

    return favorite


def get_favorite_rows():

    ensure_favorites_table()

    conn = sqlite3.connect(
        DB_PATH,
        timeout=10,
    )

    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        """
        SELECT
            p.*,
            f.marked_at AS favorite_marked_at
        FROM property_favorites AS f
        JOIN properties AS p
          ON p.id = (
              SELECT p2.id
              FROM properties AS p2
              WHERE p2.portal_id = f.portal_id
              ORDER BY
                  p2.last_seen DESC,
                  p2.id DESC
              LIMIT 1
          )
        ORDER BY f.marked_at DESC
        """
    ).fetchall()

    conn.close()

    return [
        dict(row)
        for row in rows
    ]


def property_action_keyboard(
    portal_id,
    property_type,
    number="new"
):

    keyboard = _property_action_keyboard(
        portal_id,
        property_type,
        number,
        favorite=is_favorite(
            portal_id
        ),
        user_status=get_user_status(
            DB_PATH,
            portal_id,
        ),
    )

    rows = keyboard.setdefault(
        "inline_keyboard",
        []
    )

    explanation_button = {
        "text": "🧮 Erklärung",
        "callback_data": (
            f"explain:{portal_id}:"
            f"{property_type}:{number}"
        ),
    }

    # Wenn die letzte Reihe noch Platz hat,
    # Erklärung daneben setzen.
    # Sonst eine neue Reihe beginnen.
    if (
        rows
        and len(rows[-1]) < 2
    ):
        rows[-1].append(
            explanation_button
        )

    else:
        rows.append(
            [
                explanation_button
            ]
        )

    return keyboard


def _score_details_dict(value):

    if isinstance(
        value,
        dict
    ):
        return value

    if not value:
        return {}

    try:
        result = json.loads(
            value
        )

    except Exception:
        return {}

    if isinstance(
        result,
        dict
    ):
        return result

    return {}


def _score_summary_lines(property_data):

    score_range = provisional_score_range(
        property_data
    )

    if score_range is not None:
        return [
            "Score: "
            f"{score_range[0]}–{score_range[1]} Punkte",
            "Status: vorläufig · "
            "Lage nur auf Ortsebene bekannt",
        ]

    score = property_data.get("score")
    rating = property_data.get("rating")

    return [
        (
            f"Score: {score}/100"
            if score is not None
            else "Score: noch offen"
        ),
        f"Status: {rating or '-'}",
    ]


def get_incomplete_rows():

    conn = sqlite3.connect(
        DB_PATH
    )

    conn.row_factory = (
        sqlite3.Row
    )

    try:

        rows = conn.execute(
            """
            SELECT p.*
            FROM properties AS p
            LEFT JOIN property_user_status AS us
              ON us.portal_id = p.portal_id
            WHERE p.rating = 'incomplete'
              AND COALESCE(
                    p.is_ko,
                    0
                  ) = 0
              AND COALESCE(
                    us.status,
                    'active'
                  ) = 'active'
              AND p.id = (
                  SELECT p2.id
                  FROM properties AS p2
                  WHERE p2.portal = p.portal
                    AND p2.portal_id = p.portal_id
                  ORDER BY
                      p2.last_seen DESC,
                      p2.id DESC
                  LIMIT 1
              )
            ORDER BY
                p.last_seen DESC,
                p.id DESC
            """
        ).fetchall()

    finally:
        conn.close()

    return [
        dict(row)
        for row in rows
    ]


def incomplete_reasons(
    property_data
):

    details = _score_details_dict(
        property_data.get(
            "score_details"
        )
    )

    reasons = details.get(
        "incomplete_reasons"
    )

    if not isinstance(
        reasons,
        list
    ):
        return []

    return [
        str(reason)
        for reason in reasons
        if reason
    ]


def format_incomplete_property(
    property_data,
    position,
    total
):

    title = (
        property_data.get(
            "title"
        )
        or "(ohne Titel)"
    )

    location = (
        property_data.get(
            "location"
        )
        or "(Ort unbekannt)"
    )

    price = property_data.get(
        "price"
    )

    living_area = (
        property_data.get(
            "living_area"
        )
    )

    plot_area = (
        property_data.get(
            "plot_area"
        )
    )

    url = (
        property_data.get(
            "url"
        )
        or ""
    )

    missing = incomplete_reasons(
        property_data
    )

    icons = {
        "Preis/Zustand": "💶",
        "Grundstück": "🌳",
        "Freilage/Nachbarn": "🏡",
        "Lärm": "🔇",
        "Wasser": "🌊",
        "Wohnfläche": "📐",
        "Energie": "⚡",
    }

    lines = [
        "⏳ UNVOLLSTÄNDIG "
        f"· {position}/{total}",
        "",
        title,
        location,
    ]

    facts = []

    if price is not None:
        facts.append(
            f"{price:,.0f} €"
            .replace(
                ",",
                "."
            )
        )

    if living_area is not None:
        facts.append(
            f"{living_area:.0f} m² Wohnfläche"
        )

    if plot_area is not None:
        facts.append(
            f"{plot_area:.0f} m² Grundstück"
        )

    if facts:
        lines.extend(
            [
                "",
                " · ".join(
                    facts
                ),
            ]
        )

    lines.extend(
        [
            "",
            "Fehlt:",
        ]
    )

    if missing:

        for reason in missing:

            lines.append(
                f"{icons.get(reason, '❓')} "
                f"{reason}"
            )

    else:

        lines.append(
            "❓ unbekannte Prüfung"
        )

    if url:

        lines.extend(
            [
                "",
                url,
            ]
        )

    return "\n".join(
        lines
    )


def incomplete_keyboard(
    property_data,
    has_next=True
):

    portal_id = str(
        property_data.get(
            "portal_id"
        )
        or ""
    )

    property_type = (
        property_data.get(
            "property_type"
        )
        or "house"
    )

    keyboard = (
        property_action_keyboard(
            portal_id,
            property_type,
            "incomplete",
        )
    )

    if has_next:

        keyboard[
            "inline_keyboard"
        ].append(
            [
                {
                    "text":
                        "➡️ Nächstes",
                    "callback_data":
                        f"inext:{portal_id}",
                }
            ]
        )

    return keyboard


def format_score_explanation(
    portal_id
):

    conn = sqlite3.connect(
        DB_PATH
    )

    conn.row_factory = (
        sqlite3.Row
    )

    try:

        row = conn.execute(
            """
            SELECT *
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

    finally:
        conn.close()

    if not row:

        return (
            "❌ Objekt nicht gefunden."
        )

    property_data = dict(
        row
    )

    details = _score_details_dict(
        property_data.get(
            "score_details"
        )
    )

    title = (
        property_data.get(
            "title"
        )
        or "(ohne Titel)"
    )

    location = (
        property_data.get(
            "location"
        )
        or "(Ort unbekannt)"
    )

    missing = details.get(
        "incomplete_reasons"
    )

    if not isinstance(
        missing,
        list
    ):
        missing = []

    icons = {
        "Preis/Zustand": "💶",
        "Grundstück": "🌳",
        "Freilage/Nachbarn": "🏡",
        "Ruhe": "🔇",
        "Wasser": "🌊",
        "Wohnfläche": "📐",
        "Energie": "⚡",
    }

    lines = [
        "🧮 SCORE-ERKLÄRUNG",
        "",
        title,
        location,
        "",
    ]

    for module, error in (details.get('geo_errors') or {}).items():
        lines.append(f'⚠️ {module}: {error}')

    shown_missing = set()

    for reason in details.get(
        "reasons",
        []
    ):

        reason = str(
            reason
        )

        if reason.startswith(
            "Unvollständig:"
        ):
            continue

        category = (
            reason.split(
                ":",
                1
            )[0]
            .strip()
        )

        if category in missing:

            if category not in shown_missing:

                lines.append(
                    "❓ "
                    f"{category}: "
                    "noch nicht geprüft"
                )

                shown_missing.add(
                    category
                )

            continue

        lines.append(
            f"{icons.get(category, '✅')} "
            f"{reason}"
        )

    # Falls eine fehlende Kategorie noch
    # gar keinen reasons-Eintrag hatte.
    for category in missing:

        if category in shown_missing:
            continue

        lines.append(
            "❓ "
            f"{category}: "
            "noch nicht geprüft"
        )

    lines.append(
        ""
    )

    if details.get(
        "ko"
    ):

        lines.append(
            "⛔ KO"
        )

        for reason in details.get(
            "ko_reasons",
            []
        ):
            lines.append(
                f"• {reason}"
            )

    elif details.get("provisional"):

        score_range = provisional_score_range(
            {
                "score_details": details
            }
        )

        if score_range is not None:
            lines.append(
                "⭐ "
                f"{score_range[0]}–{score_range[1]} Punkte"
            )

        lines.append(
            "📍 Lage nur auf Ortsebene bekannt"
        )

    elif (
        details.get(
            "rating"
        ) == "incomplete"
        or details.get(
            "score"
        ) is None
    ):

        lines.append(
            "⏳ Noch kein Gesamtscore"
        )

        if missing:

            lines.append(
                "Fehlt: "
                + ", ".join(
                    missing
                )
            )

    else:

        score = details.get(
            "score"
        )

        lines.append(
            f"⭐ {score} / 100"
        )

    return "\n".join(
        lines
    )


ensure_favorites_table()
ensure_user_status_table(
    DB_PATH
)


def buildability_keyboard(portal_id):

    return {
        "inline_keyboard": [
            [
                {
                    "text": "✅ Baugenehmigung",
                    "callback_data":
                        f"build:{portal_id}:BUILDING_PERMIT"
                },
            ],
            [
                {
                    "text": "🏗 Bebauungsplan",
                    "callback_data":
                        f"build:{portal_id}:CONSTRUCTIONPLAN"
                },
                {
                    "text": "🏘 §34 Nachbarn",
                    "callback_data":
                        f"build:{portal_id}:NEIGHBOURCONSTRUCTION"
                },
            ],
            [
                {
                    "text": "⛔ §35 Außenbereich",
                    "callback_data":
                        f"build:{portal_id}:EXTERNALAREA"
                },
                {
                    "text": "❔ Unbekannt",
                    "callback_data":
                        f"build:{portal_id}:NO_INFORMATION"
                },
            ],
        ]
    }


# ------------------------------------------------------------
# Manual coordinates
# ------------------------------------------------------------
#
# Domänenlogik liegt in manual_coordinates.py. Hier bleiben
# nur die Telegram-Dialoge und Callback-Routen.
# ------------------------------------------------------------

from manual_coordinates import (
    clear_manual_coordinates,
    coordinates_keyboard,
    get_coordinate_status,
    resolve_manual_location,
    set_manual_coordinates,
    rescan_geo,
)


def property_details_keyboard(
    portal_id,
    property_type,
    number
):

    rows = [
        [{"text": "🔄 Geo neu berechnen",
          "callback_data": f"geo_rescan:{portal_id}:{property_type}:{number}"}],
        [
            {
                "text": "⬅ Zurück",
                "callback_data":
                    f"back:{portal_id}:{property_type}:{number}"
            }
        ]
    ]

    if is_house_type(property_type):
        rows.insert(1, [{
            "text": "🐕 Hundesteuer prüfen",
            "callback_data": f"dt:start:{portal_id}",
        }])

    if property_type == "land":
        rows.extend(
            buildability_keyboard(
                portal_id
            )["inline_keyboard"]
        )

    return {
        "inline_keyboard": rows
    }


def set_buildability(
    portal_id,
    buildability
):

    buildability = (
        buildability
        .strip()
        .upper()
    )

    if buildability not in BUILDABILITY_MAP:

        return (
            "❌ Unbekannter Wert.\n\n"
            "Erlaubt:\n"
            "BUILDING_PERMIT\n"
            "CONSTRUCTIONPLAN\n"
            "NEIGHBOURCONSTRUCTION\n"
            "EXTERNALAREA\n"
            "NO_INFORMATION"
        )

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    row = conn.execute(
        """
        SELECT *
        FROM properties
        WHERE portal_id = ?
        ORDER BY last_seen DESC
        LIMIT 1
        """,
        (
            portal_id,
        )
    ).fetchone()

    if not row:

        conn.close()

        return (
            f"❌ Objekt {portal_id} "
            f"nicht gefunden."
        )

    property_data = dict(row)

    mapping = BUILDABILITY_MAP[
        buildability
    ]

    property_data["buildability"] = (
        buildability
    )

    property_data[
        "buildability_class"
    ] = mapping["class"]

    property_data[
        "buildability_reason"
    ] = mapping["reason"]

    property_data[
        "residential_building_allowed"
    ] = mapping["allowed"]

    score_result = score_land(
        property_data
    )

    allowed_db = (
        None
        if mapping["allowed"] is None
        else int(mapping["allowed"])
    )

    conn.execute(
        """
        UPDATE properties
        SET
            buildability = ?,
            buildability_class = ?,
            buildability_reason = ?,
            residential_building_allowed = ?,
            score = ?,
            rating = ?,
            is_ko = ?,
            score_details = ?
        WHERE portal_id = ?
        """,
        (
            buildability,
            mapping["class"],
            mapping["reason"],
            allowed_db,
            score_result["score"],
            score_result["rating"],
            int(score_result["ko"]),
            json.dumps(
                score_result,
                ensure_ascii=False
            ),
            portal_id,
        )
    )

    conn.commit()
    conn.close()

    title = (
        property_data.get("title")
        or portal_id
    )

    text = [
        f"🏠 {title}",
        "",
        f"ID: {portal_id}",
        f"Bebaubar nach: {mapping['reason'] or 'unbekannt'}",
    ]

    if mapping["allowed"] is True:
        text.append(
            "Wohnbaurecht: ✅ wahrscheinlich"
        )

    elif mapping["allowed"] is False:
        text.append(
            "Wohnbaurecht: ❌ nein"
        )

    else:
        text.append(
            "Wohnbaurecht: ❔ unbekannt"
        )

    text.extend(
        _score_summary_lines(
            {
                "score": score_result.get("score"),
                "rating": score_result.get("rating"),
                "score_details": score_result,
            }
        )
    )

    if score_result["ko"]:
        text.append("⛔ KO")

    return "\n".join(text)


def get_property_data(portal_id):

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    row = conn.execute(
        """
        SELECT *
        FROM properties
        WHERE portal_id = ?
        ORDER BY last_seen DESC
        LIMIT 1
        """,
        (
            portal_id,
        )
    ).fetchone()

    conn.close()

    return dict(row) if row else None


def get_property(portal_id):

    p = get_property_data(portal_id)

    if not p:
        return (
            f"❌ Objekt {portal_id} "
            f"nicht gefunden."
        )

    return format_property_card(
        p
    ) + '\n\n' + property_tax_text(DB_PATH, p)

    lines = [
        f"🏠 {p.get('title') or portal_id}",
        "",
        f"📍 {p.get('location') or '-'}",
    ]

    if p.get("price") is not None:

        lines.append(
            "💰 "
            + f"{p['price']:,.0f} €"
            .replace(",", ".")
        )

    if p.get("plot_area") is not None:

        lines.append(
            "🌳 "
            + f"{p['plot_area']:,.0f} m²"
            .replace(",", ".")
        )

    if p.get(
        "water_distance_km"
    ) is not None:

        lines.append(
            f"💧 Wasser: "
            f"{p['water_distance_km']:.2f} km"
        )

    if p.get("neighbour_class"):

        lines.append(
            f"🏘 Nachbarn: "
            f"{p['neighbour_class']}"
        )

    if p.get("buildability_reason"):

        lines.append(
            f"🏗 Bebaubar: "
            f"{p['buildability_reason']}"
        )

    else:

        lines.append(
            "🏗 Bebaubar: unbekannt"
        )

    lines.append("")

    lines.extend(
        _score_summary_lines(p)
    )

    if p.get("is_ko"):
        lines.append("⛔ KO")

    if p.get("url"):
        lines.append("")
        lines.append(p["url"])

    return "\n".join(lines)

BLACKLIST_PATH = "/config/blacklist.yaml"

def is_currently_blacklisted(property_data):

    text = " ".join(
        str(value or "")
        for value in (
            property_data.get("title"),
            property_data.get("location"),
            property_data.get("url"),
        )
    ).casefold()

    return any(
        term.casefold() in text
        for term in CONFIG.blacklist_terms()
    )

def add_blacklist_term(term):

    term = (
        (term or "")
        .strip()
        .casefold()
    )

    if not term:
        return (
            "❌ Kein Begriff angegeben.\n\n"
            "Beispiel:\n"
            "/blacklist Gartengrundstück"
        )

    try:

        with open(
            BLACKLIST_PATH,
            "r",
            encoding="utf-8"
        ) as f:
            config = yaml.safe_load(f) or {}

    except FileNotFoundError:

        return (
            f"❌ Blacklist nicht gefunden:\n"
            f"{BLACKLIST_PATH}"
        )

    # --------------------------------------------------------
    # Vorhandene Struktur automatisch finden.
    #
    # Unterstützt z.B.:
    #
    # blacklist:
    #   - ackerland
    #
    # oder:
    #
    # keywords:
    #   - ackerland
    # --------------------------------------------------------

    target_key = None

    for key in (
        "blacklist",
        "keywords",
        "terms"
    ):
        if isinstance(config.get(key), list):
            target_key = key
            break

    if target_key is None:
        return (
            "❌ Unbekannte blacklist.yaml-Struktur.\n"
            "Keine Liste unter blacklist, keywords "
            "oder terms gefunden."
        )

    terms = config[target_key]

    normalized = term.casefold()

    for existing in terms:

        if str(existing).strip().casefold() == normalized:

            return (
                "ℹ️ Bereits auf der Blacklist:\n\n"
                f"{term}"
            )

    terms.append(term)

    # Alphabetisch macht die Datei langfristig
    # deutlich angenehmer lesbar.
    terms.sort(
        key=lambda value:
            str(value).casefold()
    )

    temp_path = BLACKLIST_PATH + ".tmp"

    try:

        # Eigentümer und Dateirechte der bestehenden
        # blacklist.yaml merken.
        original_stat = os.stat(
            BLACKLIST_PATH
        )

        with open(
            temp_path,
            "w",
            encoding="utf-8"
        ) as f:

            yaml.safe_dump(
                config,
                f,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False
            )

        # Die temporäre Datei bekommt vor dem Austausch
        # dieselben Eigentümer und Rechte wie das Original.
        os.chown(
            temp_path,
            original_stat.st_uid,
            original_stat.st_gid
        )

        os.chmod(
            temp_path,
            original_stat.st_mode & 0o777
        )

        os.replace(
            temp_path,
            BLACKLIST_PATH
        )

    except Exception as exc:

        try:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        except Exception:
            pass

        return (
            "❌ Blacklist konnte nicht "
            "gespeichert werden:\n"
            f"{type(exc).__name__}: {exc}"
        )
    return (
        "✅ Blacklist ergänzt\n\n"
        f"{term}\n\n"
        f"Aktuell {len(terms)} Begriffe."
    )

def listing_status(url):

    if not url:
        return "unknown"

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "Chrome/151 Safari/537.36"
            )
        }
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=12
        ) as response:

            status = response.getcode()

            if status in (404, 410):
                return "offline"

            body = response.read().decode(
                "utf-8",
                errors="ignore"
            ).casefold()

            offline_terms = (
                "angebot wurde deaktiviert",
                "angebot ist nicht mehr verfügbar",
                "das angebot ist nicht mehr verfügbar",
                "objekt wurde deaktiviert",
                "inserat wurde deaktiviert",
                "nicht mehr verfügbar",
            )

            if any(
                term in body
                for term in offline_terms
            ):
                return "offline"

            return "live"

    except urllib.error.HTTPError as exc:

        # Eindeutig verschwunden
        if exc.code in (404, 410):
            return "offline"

        # ImmoScout/Immowelt blockieren Bots häufig
        # mit 401/403. Das bedeutet NICHT,
        # dass das Inserat verschwunden ist.
        if exc.code in (401, 403, 429):
            return "unknown"

        return "unknown"

    except Exception:

        return "unknown"


def format_property_card(
    p,
    number=None
):

    lines = []

    # --------------------------------------------------------
    # Titel
    # --------------------------------------------------------

    title = (
        p.get("title")
        or p.get("portal_id")
        or "Unbekanntes Objekt"
    )

    if number is not None:
        lines.append(
            f"#{number} 🏡 {title}"
        )
    else:
        lines.append(
            f"🏡 {title}"
        )
    lines.append("")

    # --------------------------------------------------------
    # Ort
    # --------------------------------------------------------

    lines.append(
        f"📍 {p.get('location') or '-'}"
    )

    lines.append(
        "🏷 Typ: "
        + property_type_label(
            p.get("property_type")
        )
    )

    # --------------------------------------------------------
    # Preis
    # --------------------------------------------------------

    if p.get("price") is not None:

        lines.append(
            "💰 "
            + f"{p['price']:,.0f} €"
            .replace(",", ".")
        )

    # --------------------------------------------------------
    # Grundstück
    # --------------------------------------------------------

    if p.get("plot_area") is not None:

        lines.append(
            "🌳 "
            + f"{p['plot_area']:,.0f} m² Grundstück"
            .replace(",", ".")
        )

    # --------------------------------------------------------
    # Wohnfläche
    # --------------------------------------------------------

    if (
        is_house_type(p.get("property_type"))
        and p.get("living_area") is not None
    ):

        lines.append(
            "🏠 "
            + f"{p['living_area']:,.0f} m² Wohnfläche"
            .replace(",", ".")
        )

    # --------------------------------------------------------
    # Wasser
    # --------------------------------------------------------

    if p.get("water_score") is not None:

        water_class = (
            p.get("water_class")
            or "unknown"
        )

        distance = p.get(
            "water_distance_km"
        )

        if distance is not None:

            lines.append(
                f"💧 {water_class} | "
                f"{distance:.2f} km | "
                f"{p['water_score']}/20"
            )

        else:

            lines.append(
                f"💧 {water_class} | "
                f"{p['water_score']}/20"
            )

    elif p.get("water_distance_km") is not None:

        lines.append(
            f"💧 Wasser: "
            f"{p['water_distance_km']:.2f} km"
        )

    # --------------------------------------------------------
    # Nachbarn
    # --------------------------------------------------------

    if p.get("neighbour_class"):

        lines.append(
            f"🏘 Nachbarn: "
            f"{p['neighbour_class']}"
        )

    # --------------------------------------------------------
    # Lärm
    #
    # noise_checked_at bedeutet: Prüfung wurde durchgeführt.
    # None bei den einzelnen Pegeln bedeutet dann nicht
    # "unbekannt", sondern "unter Kartierungsgrenze".
    # --------------------------------------------------------

    if p.get("noise_checked_at"):

        def noise_value(
            value,
            fallback,
        ):

            if value is None:
                return fallback

            return str(value)

        rail_day = noise_value(
            p.get("rail_lden"),
            "<55",
        )

        rail_night = noise_value(
            p.get("rail_lnight"),
            "<45",
        )

        road_day = noise_value(
            p.get("road_lden"),
            "<55",
        )

        road_night = noise_value(
            p.get("road_lnight"),
            "<50",
        )

        air_day = noise_value(
            p.get("air_lden"),
            "<55",
        )

        air_night = noise_value(
            p.get("air_lnight"),
            "<50",
        )

        lines.append(
            "🔇 Lärm: "
            f"Bahn {rail_day}/{rail_night} | "
            f"Straße {road_day}/{road_night} | "
            f"Flug {air_day}/{air_night}"
        )

    # --------------------------------------------------------
    # Bebaubarkeit
    # --------------------------------------------------------

    if p.get("property_type") == "land":

        buildability_class = (
            str(
                p.get(
                    "buildability_class"
                )
                or "unknown"
            )
            .strip()
            .lower()
        )

        buildability_reason = (
            p.get(
                "buildability_reason"
            )
        )

        residential_allowed = (
            p.get(
                "residential_building_allowed"
            )
        )

        # ----------------------------------------------------
        # Bestätigte Wohnbebauung
        # ----------------------------------------------------

        if (
            residential_allowed in (
                1,
                True,
            )
            or buildability_class
            == "residential"
        ):

            lines.append(
                "✅ Bebaubarkeit: Wohnbebauung"
            )

            if buildability_reason:
                lines.append(
                    f"   {buildability_reason}"
                )

        # ----------------------------------------------------
        # Kein normales Wohnbaurecht
        # ----------------------------------------------------

        elif (
            (
                residential_allowed
                is not None
            )
            and residential_allowed
            in (
                0,
                False,
            )
        ) or buildability_class == "ko":

            lines.append(
                "⛔ Bebaubarkeit: "
                "kein normales Wohnbaurecht"
            )

            if buildability_reason:
                lines.append(
                    f"   {buildability_reason}"
                )

        # ----------------------------------------------------
        # Hinweise vorhanden, aber rechtlich nicht geklärt
        # ----------------------------------------------------

        elif buildability_class == "uncertain":

            lines.append(
                "⚠️ Bebaubarkeit: unklar"
            )

            if buildability_reason:
                lines.append(
                    f"   {buildability_reason}"
                )

        # ----------------------------------------------------
        # Keine verwertbare Information
        # ----------------------------------------------------

        else:

            lines.append(
                "❔ Bebaubarkeit: unbekannt"
            )

    # --------------------------------------------------------
    # Zustand bei Häusern
    # --------------------------------------------------------

    if is_house_type(p.get("property_type")):

        condition_class = (
            p.get("condition_class")
            or "unknown"
        )

        condition_reason = p.get(
            "condition_reason"
        )

        if condition_reason:

            lines.append(
                f"🔧 {condition_class} "
                f"({condition_reason})"
            )

        else:

            lines.append(
                f"🔧 {condition_class}"
            )

        lines.append(
            "⚡ Energie: "
            + format_energy_summary(p)
        )

        heating_type = p.get(
            "heating_type"
        )

        energy_source = p.get(
            "energy_source"
        )

        if heating_type or energy_source:
            heating_parts = [
                value
                for value in (
                    heating_type,
                    energy_source,
                )
                if value
            ]

            lines.append(
                "🔥 Heizung: "
                + " | ".join(heating_parts)
            )

    # --------------------------------------------------------
    # Score
    # --------------------------------------------------------

    score_range = provisional_score_range(
        p
    )

    if score_range is not None:

        lines.append("")

        lines.append(
            "⭐ "
            f"{score_range[0]}–{score_range[1]} Punkte"
            " | 📍 Lage nur auf Ortsebene bekannt"
        )

    elif p.get("score") is not None:

        lines.append("")

        lines.append(
            f"⭐ Score: {p['score']}/100"
        )

        lines.append(
            f"📊 Status: "
            f"{p.get('rating') or '-'}"
        )

    # --------------------------------------------------------
    # ID
    # --------------------------------------------------------

    lines.append(
        f"🆔 {p.get('portal_id') or '-'}"
    )

    # --------------------------------------------------------
    # URL
    # --------------------------------------------------------

    if p.get("url"):

        lines.append(
            p["url"]
        )

    return "\n".join(lines)

def get_top_properties(property_type, limit=3):

    rows = get_top_property_rows(
        property_type,
        max(limit * 5, 15),
    )

    selected = []

    for row in rows:

        p = dict(row)

        if get_user_status(
            DB_PATH,
            p.get("portal_id"),
        ) != "active":
            continue

        status = listing_status(
            p.get("url")
        )

        if status == "offline":
            print(
                f"TOP LIST: offline | "
                f"{p['portal_id']} | "
                f"{p['title']}",
                flush=True
            )
            continue

        p["_live_status"] = status

        selected.append(p)

        if len(selected) >= limit:
            break

    if not selected:

        return (
            "Keine passenden aktiven "
            "Objekte gefunden."
        )

    label = (
        "GRUNDSTÜCKE"
        if property_type == "land"
        else "HÄUSER"
    )

    lines = [
        f"🏆 TOP {len(selected)} {label}",
        ""
    ]

    for number, p in enumerate(
        selected,
        1
    ):

        lines.append(
            format_property_card(
                p,
                number
            )
        )

        if p["_live_status"] == "unknown":
            lines.append(
                "🔎 Live-Status nicht eindeutig prüfbar"
            )

        lines.append("")

    return "\n".join(lines).strip()

def find_properties(query, limit=8, with_keyboard=False):

    query = (
        query
        or ""
    ).strip()

    if not query:

        text = (
            "Verwendung:\n"
            "/find <Suchtext>\n\n"
            "Beispiele:\n"
            "/find Köthen\n"
            "/find Dreiseitenhof\n"
            "/find 170130421"
        )
        return (text, None) if with_keyboard else text

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    pattern = (
        "%"
        + query.casefold()
        + "%"
    )

    rows = conn.execute(
        """
        SELECT
            portal,
            portal_id,
            property_type,
            title,
            location,
            price,
            plot_area,
            score,
            rating,
            is_ko,
            score_details,
            url
        FROM properties
        WHERE
            LOWER(COALESCE(portal_id, ''))
                LIKE ?
            OR LOWER(COALESCE(title, ''))
                LIKE ?
            OR LOWER(COALESCE(location, ''))
                LIKE ?
        ORDER BY
            is_ko ASC,
            score DESC,
            last_seen DESC
        LIMIT ?
        """,
        (
            pattern,
            pattern,
            pattern,
            limit,
        )
    ).fetchall()

    conn.close()

    if not rows:

        text = (
            "❌ Kein Objekt gefunden für:\n"
            f"{query}"
        )
        return (text, None) if with_keyboard else text

    lines = [
        f"🔎 Suche: {query}",
        ""
    ]

    for n, row in enumerate(rows, 1):

        p = dict(row)

        type_label = {
            "land": "🌳",
            "house": "🏠",
            "farm": "🚜",
        }.get(
            p["property_type"],
            "•"
        )

        lines.append(
            f"{n}. {type_label} "
            f"{p['title'] or '-'}"
        )

        lines.append(
            f"📍 {p['location'] or '-'}"
        )

        if p["price"] is not None:
            lines.append(
                "💰 "
                + f"{p['price']:,.0f} €"
                .replace(",", ".")
            )

        if p["plot_area"] is not None:
            lines.append(
                "🌳 "
                + f"{p['plot_area']:,.0f} m²"
                .replace(",", ".")
            )

        score_range = provisional_score_range(
            p
        )

        if score_range is not None:
            lines.append(
                "⭐ "
                f"{score_range[0]}–{score_range[1]} Punkte"
                " | 📍 Lage nur auf Ortsebene bekannt"
            )

        elif p["score"] is not None:
            lines.append(
                f"⭐ {p['score']}/100 | "
                f"{p['rating']}"
            )

        if p["is_ko"]:
            lines.append("⛔ KO")

        lines.append(
            f"🆔 {p['portal_id']} "
            f"({p['portal']})"
        )

        lines.append(
            f"/property {p['portal_id']}"
        )

        lines.append("")

    text = "\n".join(lines).strip()

    if not with_keyboard:
        return text

    keyboard = {
        "inline_keyboard": [
            [{
                "text": f"🏠 Details {number}",
                "callback_data": (
                    f"property:{row['portal_id']}:"
                    f"{row['property_type']}:find"
                ),
            }]
            for number, row in enumerate(rows, 1)
        ]
    }

    return text, keyboard

def get_top_property_rows(
    property_type,
    limit=3
):

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    if is_house_type(property_type):

        rows = conn.execute(
            """
            SELECT *
            FROM properties
            WHERE property_type IN ('house', 'farm')
              AND is_ko = 0
              AND (
                    score IS NOT NULL
                    OR rating = 'provisional'
                  )
            """,
        ).fetchall()

    elif property_type == "land":

        rows = conn.execute(
            """
            SELECT *
            FROM properties
            WHERE property_type = 'land'
              AND is_ko = 0
              AND (
                    (
                        score IS NOT NULL
                        AND latitude IS NOT NULL
                        AND longitude IS NOT NULL
                        AND water_score IS NOT NULL
                        AND neighbour_class IS NOT NULL
                    )
                    OR rating = 'provisional'
                  )
            """,
        ).fetchall()

    else:
        rows = []

    conn.close()

    blacklist_terms = (
        CONFIG.blacklist_terms()
    )

    candidates = [
        dict(row)
        for row in rows
    ]

    candidates.sort(
        key=lambda p: (
            -conservative_score(p),
            -(p.get("plot_area") or 0),
            (
                p.get("price")
                if p.get("price") is not None
                else float("inf")
            ),
        )
    )

    selected = []
    seen_house_keys = set()

    for p in candidates:

        if get_user_status(
            DB_PATH,
            p.get("portal_id"),
        ) != "active":
            continue

        searchable_text = " ".join(
            str(value or "")
            for value in (
                p.get("title"),
                p.get("location"),
            )
        ).casefold()

        if any(
            term.casefold() in searchable_text
            for term in blacklist_terms
        ):

            print(
                f"TOP LIST: blacklist | "
                f"{p.get('portal_id')} | "
                f"{p.get('title')}",
                flush=True
            )

            continue

        # ----------------------------------------------------
        # Haus-Dubletten
        #
        # Gleicher Titel + Ort + gerundete Kerndaten:
        # nur einen Rang belegen.
        #
        # Beispiel:
        # 4160.04 m² und 4160.09 m² werden beide zu 4160.
        # ----------------------------------------------------

        if is_house_type(property_type):

            def dedupe_number(value):

                if value is None:
                    return None

                try:
                    return round(float(value))

                except (
                    TypeError,
                    ValueError,
                ):
                    return value


            dedupe_key = (
                " ".join(
                    str(
                        p.get("title")
                        or ""
                    )
                    .casefold()
                    .split()
                ),
                " ".join(
                    str(
                        p.get("location")
                        or ""
                    )
                    .casefold()
                    .split()
                ),
                dedupe_number(
                    p.get("price")
                ),
                dedupe_number(
                    p.get("plot_area")
                ),
                dedupe_number(
                    p.get("living_area")
                ),
            )


            if dedupe_key in seen_house_keys:

                print(
                    "TOP LIST: duplicate | "
                    f"{p.get('portal_id')} | "
                    f"{p.get('title')}",
                    flush=True,
                )

                continue


            seen_house_keys.add(
                dedupe_key
            )


        selected.append(p)

    return selected[:limit]


def get_chance_rows(property_type, limit=3, excluded_ids=()):
    from chances import max_reachable_score, CHANCE_THRESHOLD

    types = ('house', 'farm') if is_house_type(property_type) else ('land',)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM properties WHERE property_type IN ("
            + ','.join('?' for _ in types) + ") "
            "AND COALESCE(rating, '') NOT IN ('blacklisted', 'deleted')", types,
        ).fetchall()
    finally:
        conn.close()
    candidates = []
    seen = set(excluded_ids)
    for row in rows:
        p = dict(row)
        portal_id = p.get('portal_id')
        if portal_id in seen or get_user_status(DB_PATH, portal_id) != 'active':
            continue
        try:
            details = json.loads(p.get('score_details') or '{}')
        except (TypeError, ValueError):
            details = {}
        if details.get('blacklisted') or p.get('is_ko'):
            continue
        maximum = max_reachable_score(p)
        if maximum is None or maximum <= CHANCE_THRESHOLD:
            continue
        # Completed top-ranked listings already have ordinary ranking cards.
        if p.get('score') is not None and maximum <= p['score']:
            continue
        p['max_reachable_score'] = maximum
        candidates.append(p)
        seen.add(portal_id)
    candidates.sort(key=lambda p: (-p['max_reachable_score'], p.get('price') or 0, str(p.get('portal_id'))))
    return candidates[:limit]


def get_house_chance_rows(limit=3):
    return get_chance_rows('house', limit)


def send_chances(property_type, shown_rows):
    rows = get_chance_rows(property_type, 3, {p['portal_id'] for p in shown_rows})
    if not rows:
        return
    send_message('👀 CHANCEN · maximal erreichbar über 75/100\n'
                 'Nur offene Kriterien werden im besten Fall angenommen. Harte KO bleiben bestehen.')
    for number, p in enumerate(rows, 1):
        send_message(
            f"👀 CHANCE #{number} · Best Case: {p['max_reachable_score']}/100\n\n"
            + format_property_card(p),
            property_action_keyboard(p['portal_id'], p.get('property_type') or property_type, 'new'),
        )


CONDITION_MAP = {
    "turnkey": "Bezugsfertig",
    "good": "Gut",
    "maintained": "Gepflegt",
    "cosmetic_renovation": "Teilrenovierung",
    "renovation_needed": "Renovierungsbedürftig",
    "major_renovation": "Sanierungsbedürftig",
    "dilapidated": "Baufällig",
    "unknown": "Unbekannt",
}


def condition_keyboard(
    portal_id,
    property_type="house",
    number="new"
):

    return {
        "inline_keyboard": [
            [
                {
                    "text": "✅ Bezugsfertig",
                    "callback_data":
                        f"c:{portal_id}:t:{number}"
                },
                {
                    "text": "👍 Gut",
                    "callback_data":
                        f"c:{portal_id}:g:{number}"
                }
            ],
            [
                {
                    "text": "🧹 Gepflegt",
                    "callback_data":
                        f"c:{portal_id}:m:{number}"
                },
                {
                    "text": "🪛 Teilrenovierung",
                    "callback_data":
                        f"c:{portal_id}:c:{number}"
                }
            ],
            [
                {
                    "text": "🔧 Renovierungsbedürftig",
                    "callback_data":
                        f"c:{portal_id}:r:{number}"
                }
            ],
            [
                {
                    "text": "🏚 Sanierungsbedürftig",
                    "callback_data":
                        f"c:{portal_id}:s:{number}"
                },
                {
                    "text": "⛔ Baufällig",
                    "callback_data":
                        f"c:{portal_id}:d:{number}"
                }
            ],
            [
                {
                    "text": "❔ Unbekannt",
                    "callback_data":
                        f"c:{portal_id}:u:{number}"
                }
            ],
            [
                {
                    "text": "⬅️ Zurück",
                    "callback_data":
                        f"back:{portal_id}:{property_type}:{number}"
                }
            ]
        ]
    }

def set_house_condition(portal_id, condition_class):

    condition_class = (
        condition_class
        or ""
    ).strip().lower()

    if condition_class not in CONDITION_MAP:

        return (
            "❌ Unbekannter Zustand.\n\n"
            + "\n".join(
                CONDITION_MAP.keys()
            )
        )

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    row = conn.execute(
        """
        SELECT *
        FROM properties
        WHERE portal_id = ?
        ORDER BY last_seen DESC
        LIMIT 1
        """,
        (portal_id,)
    ).fetchone()

    if not row:

        conn.close()

        return (
            f"❌ Objekt {portal_id} "
            f"nicht gefunden."
        )

    p = dict(row)

    if not is_house_type(p.get("property_type")):

        conn.close()

        return (
            "❌ Zustand kann nur bei "
            "Häusern gesetzt werden."
        )

    p["condition_class"] = (
        condition_class
    )

    p["condition_reason"] = (
        "manuell gesetzt"
    )

    p["condition_source"] = (
        "telegram"
    )

    from scoring import score_house

    result = score_house(p)

    conn.execute(
        """
        UPDATE properties
        SET
            condition_class = ?,
            condition_reason = ?,
            condition_source = ?,
            score = ?,
            rating = ?,
            is_ko = ?,
            score_details = ?
        WHERE portal_id = ?
        """,
        (
            condition_class,
            "manuell gesetzt",
            "telegram",
            result["score"],
            result["rating"],
            int(result["ko"]),
            json.dumps(
                result,
                ensure_ascii=False
            ),
            portal_id,
        )
    )

    conn.commit()
    conn.close()

    return "\n".join(
        [
            "✅ Zustand gesetzt",
            "",
            CONDITION_MAP[condition_class],
            *_score_summary_lines(
                {
                    "score": result.get("score"),
                    "rating": result.get("rating"),
                    "score_details": result,
                }
            ),
        ]
    )


def inspect_property(portal_id):

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    row = conn.execute(
        """
        SELECT *
        FROM properties
        WHERE portal_id = ?
        ORDER BY last_seen DESC
        LIMIT 1
        """,
        (portal_id,)
    ).fetchone()

    conn.close()

    if not row:

        return (
            f"❌ Objekt {portal_id} "
            f"nicht gefunden."
        )

    p = dict(row)

    lines = [
        f"🔍 INSPECT {portal_id}",
        "",
        p.get("title") or "-",
        "",
        "🏷 Typ: "
        + property_type_label(
            p.get("property_type")
        ),
    ]

    if is_house_type(p.get("property_type")):

        condition = (
            p.get("condition_class")
            or "unknown"
        )

        lines.append(
            "🔧 Zustand: "
            f"{CONDITION_MAP.get(condition, condition)}"
        )

        lines.append(
            "⚡ Energie: "
            + format_energy_summary(p)
        )

        if p.get("heating_type"):
            lines.append(
                "🔥 Heizung: "
                f"{p['heating_type']}"
            )

        if p.get("energy_source"):
            lines.append(
                "🪵 Energieträger: "
                f"{p['energy_source']}"
            )

        if p.get("energy_construction_year"):
            lines.append(
                "📅 Baujahr Energieausweis: "
                f"{p['energy_construction_year']}"
            )

    lines.append(
        "📍 Geo: "
        + (
            "✅"
            if p.get("latitude") is not None
            else "❔"
        )
    )

    lines.append(
        "💧 Wasser: "
        + (
            "✅"
            if p.get("water_score") is not None
            else "❔"
        )
    )

    lines.append(
        "🏘 Nachbarn: "
        + (
            "✅"
            if p.get("neighbour_class")
            else "❔"
        )
    )

    lines.append(
        "⭐ Score: "
        f"{p.get('score')}"
    )

    return "\n".join(lines)

def get_purge_candidates(days=30):

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    cutoff = (
        datetime.now(timezone.utc)
        - timedelta(days=days)
    ).isoformat()

    rows = conn.execute(
        """
        SELECT
            p.*,
            COALESCE(
                us.status,
                'active'
            ) AS user_status
        FROM properties AS p
        LEFT JOIN property_user_status AS us
          ON us.portal_id = p.portal_id
        ORDER BY p.last_seen DESC
        """
    ).fetchall()

    conn.close()

    blacklist_terms = CONFIG.blacklist_terms()

    result = []

    for row in rows:

        p = dict(row)

        text = " ".join(
            str(value or "")
            for value in (
                p.get("title"),
                p.get("location"),
                p.get("url"),
            )
        ).casefold()

        reasons = []

        if any(
            term.casefold() in text
            for term in blacklist_terms
        ):
            reasons.append("blacklist")

        if p.get("user_status") == "offline":
            reasons.append("offline")

        last_seen = p.get("last_seen")

        if (
            last_seen
            and last_seen < cutoff
        ):
            reasons.append(
                f"älter als {days} Tage"
            )

        if reasons:

            p["_purge_reasons"] = reasons
            result.append(p)

    return result


def purge_preview(days=30):

    rows = get_purge_candidates(days)

    if not rows:

        return (
            "🧹 PURGE\n\n"
            "Keine löschbaren Objekte gefunden."
        )

    blacklist_count = 0
    offline_count = 0
    old_count = 0

    for p in rows:

        reasons = p["_purge_reasons"]

        if "blacklist" in reasons:
            blacklist_count += 1

        if "offline" in reasons:
            offline_count += 1

        if any(
            reason.startswith("älter als")
            for reason in reasons
        ):
            old_count += 1

    return (
        "🧹 PURGE\n\n"
        f"Blacklist-Treffer: {blacklist_count}\n"
        f"Offline markiert: {offline_count}\n"
        f"Älter als {days} Tage: {old_count}\n\n"
        f"Insgesamt zu löschen: {len(rows)}"
    )


def purge_keyboard(days=30):

    return {
        "inline_keyboard": [
            [
                {
                    "text": "✅ Löschen",
                    "callback_data":
                        f"purge_confirm:{days}"
                },
                {
                    "text": "❌ Abbrechen",
                    "callback_data":
                        "purge_cancel"
                }
            ]
        ]
    }


def execute_purge(days=30):

    rows = get_purge_candidates(days)

    if not rows:

        return 0

    ids = [
        p["id"]
        for p in rows
    ]

    conn = sqlite3.connect(DB_PATH)

    conn.executemany(
        """
        DELETE FROM properties
        WHERE id = ?
        """,
        [
            (property_id,)
            for property_id in ids
        ]
    )

    portal_ids = [
        p.get("portal_id")
        for p in rows
        if p.get("portal_id")
    ]

    conn.executemany(
        """
        DELETE FROM property_user_status
        WHERE portal_id = ?
        """,
        [
            (portal_id,)
            for portal_id in portal_ids
        ]
    )

    conn.commit()
    conn.close()

    return len(ids)

def handle_message(message):

    chat = message.get(
        "chat",
        {}
    )

    chat_id = str(
        chat.get("id")
    )

    # --------------------------------------------------------
    # Sicherheit:
    # nur dein konfigurierte Telegram-Chat darf Befehle geben
    # --------------------------------------------------------

    if chat_id != str(
        TELEGRAM_CHAT_ID
    ):
        return

    text = (
        message.get("text")
        or message.get("caption")
        or ""
    ).strip()

    pending_dog_tax = PENDING_DOG_TAX.get(chat_id)
    document = message.get("document")

    if pending_dog_tax and (document or (text and not text.startswith('/'))):
        try:
            from dog_tax_sources import (
                MAX_DOCUMENT_BYTES,
                extract_document_text,
                fetch_document,
                telegram_upload_reference,
            )
            from dog_tax_wizard import (
                accept_answer,
                apply_automatic_results,
                apply_document_results,
                extract_fields,
                next_prompt,
            )
            from municipality_lookup import lookup_municipality

            if pending_dog_tax.get('stage') == 'source':
                if document:
                    if int(document.get('file_size') or 0) > MAX_DOCUMENT_BYTES:
                        raise ValueError('Das Dokument ist größer als 12 MB.')
                    file_info = telegram_api('getFile', {'file_id': document['file_id']})['result']
                    file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_info['file_path']}"
                    with urllib.request.urlopen(file_url, timeout=30) as response:
                        content = response.read(MAX_DOCUMENT_BYTES + 1)
                    if len(content) > MAX_DOCUMENT_BYTES:
                        raise ValueError('Das Dokument ist größer als 12 MB.')
                    filename = document.get('file_name') or 'dokument.pdf'
                    source_reference = telegram_upload_reference(content, filename)
                    document_text = extract_document_text(content, 'application/pdf', filename)
                elif text.startswith('https://'):
                    source_reference, content, content_type = fetch_document(text)
                    document_text = extract_document_text(content, content_type, source_reference)
                else:
                    raise ValueError('Bitte den HTTPS-Link senden oder die PDF hochladen.')
                try:
                    municipality = lookup_municipality(pending_dog_tax['property'])
                except ValueError:
                    result = apply_document_results(pending_dog_tax, source_reference, document_text)
                else:
                    result = apply_automatic_results(pending_dog_tax, municipality, source_reference, document_text)
            else:
                result = accept_answer(pending_dog_tax, text)

            keyboard = dog_tax_prompt_keyboard(pending_dog_tax)
            if pending_dog_tax.get('stage') == 'preview':
                from dog_tax_wizard import note_existing_tariff
                with dog_tax_database(DB_PATH) as conn:
                    existing = load_stored_tariff(conn, pending_dog_tax['municipality_key'])
                result = note_existing_tariff(pending_dog_tax, existing)
            send_message(result, keyboard)
        except Exception as exc:
            print(f'DOG TAX INPUT ERROR: {type(exc).__name__}: {exc}', flush=True)
            prompt = ('Bitte den HTTPS-Link senden oder die PDF hochladen.'
                      if pending_dog_tax.get('stage') == 'source' else next_prompt(pending_dog_tax))
            send_message(f'⚠️ {exc}\n\nDie Aufgabe bleibt geöffnet.\n\n{prompt}',
                         dog_tax_prompt_keyboard(pending_dog_tax))
        return

    if not text:
        return

    if text.partition(' ')[0].split('@')[0].lower() in ('/dogtax', '/hundesteuer'):
        PENDING_DOG_TAX.pop(chat_id, None)
        tasks = dog_tax_research_queue(DB_PATH, get_top_property_rows('house', 10), get_favorite_rows())
        if not tasks:
            send_message('✅ Für Top-10-Häuser und Merkliste sind keine Hundesteuer-Angaben offen.')
            return
        lines = ['🐕 Hundesteuer · offene Aufgaben', '',
                 'Wähle ein Objekt. Danach reicht ein Satzungslink oder eine hochgeladene PDF.']
        buttons = []
        for number, task in enumerate(tasks, 1):
            if task['kind'] == 'municipality':
                p = task['property']
                lines.append(f"{number}. 📍 {p.get('location') or 'Ort unbekannt'} · Gemeinde/Satzung offen")
                portal_id = p['portal_id']
            else:
                lines.append(f"{number}. 📜 {task['municipality_name']} · Satzung offen")
                portal_id = task['portal_id']
            buttons.append([{'text': f'🐕 Aufgabe {number} öffnen', 'callback_data': f'dt:start:{portal_id}'}])
        send_message('\n'.join(lines), {'inline_keyboard': buttons})
        return

    if text.partition(' ')[0].split('@')[0].lower() in ('/dogtax_link', '/dogtax_set'):
        from dog_tax_workflow import handle_dog_tax_command
        result = handle_dog_tax_command(text, DB_PATH, get_top_property_rows('house', 10), get_favorite_rows())
        for start in range(0, len(result), 3800):
            send_message(result[start:start + 3800])
        return

    # --------------------------------------------------------
    # Manueller Immobilien-Linkimport
    # --------------------------------------------------------

    if (
        text.startswith("http://")
        or text.startswith("https://")
    ):
        try:
            from url_import import (
                import_property_url
            )

            from monitor import (
                format_property as monitor_format_property,
            )

            send_message(
                "🔎 Immobilie wird eingelesen …"
            )

            result = import_property_url(
                text
            )

            property_data = result[
                "property_data"
            ]

            # ------------------------------------------------
            # Manuelles erneutes Senden eines Links bedeutet:
            # "Kein Interesse" für dieses Objekt aufheben.
            #
            # Der automatische Mailimport bleibt weiterhin
            # durch spam_objects gesperrt, bis der Benutzer
            # den Link ausdrücklich erneut an Telegram sendet.
            # ------------------------------------------------

            restored_not_interested = False

            portal = str(
                property_data.get("portal")
                or ""
            ).strip().lower()

            portal_id = str(
                property_data.get("portal_id")
                or ""
            ).strip()

            if portal and portal_id:


                restore_conn = sqlite3.connect(
                    DB_PATH
                )

                restore_conn.row_factory = (
                    sqlite3.Row
                )

                try:

                    ignored = restore_conn.execute(
                        """
                        SELECT
                            portal,
                            portal_id,
                            title
                        FROM spam_objects
                        WHERE portal = ?
                          AND portal_id = ?
                        LIMIT 1
                        """,
                        (
                            portal,
                            portal_id,
                        )
                    ).fetchone()

                    if ignored:

                        # Die explizite manuelle Eingabe hebt
                        # "Kein Interesse" auf.
                        restore_conn.execute(
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

                        restore_conn.execute(
                            """
                            DELETE FROM property_user_status
                            WHERE portal_id = ?
                            """,
                            (
                                portal_id,
                            )
                        )

                        existing = (
                            restore_conn.execute(
                                """
                                SELECT
                                    id,
                                    rating,
                                    is_ko,
                                    score_details
                                FROM properties
                                WHERE portal = ?
                                  AND portal_id = ?
                                LIMIT 1
                                """,
                                (
                                    portal,
                                    portal_id,
                                )
                            ).fetchone()
                        )

                        if (
                            existing
                            and existing["rating"]
                            == "not_interested"
                        ):

                            restored_rating = None
                            restored_is_ko = 0

                            # "Kein Interesse" hat den
                            # eigentlichen Score nicht
                            # verändert. score_details enthält
                            # deshalb noch das ursprüngliche
                            # Scoring-Ergebnis.
                            try:
                                details = json.loads(
                                    existing[
                                        "score_details"
                                    ]
                                    or "{}"
                                )
                            except Exception:
                                details = {}

                            if isinstance(
                                details,
                                dict
                            ):
                                restored_rating = (
                                    details.get(
                                        "rating"
                                    )
                                )

                                restored_is_ko = int(
                                    bool(
                                        details.get(
                                            "ko",
                                            False
                                        )
                                    )
                                )

                            restore_conn.execute(
                                """
                                UPDATE properties
                                SET
                                    rating = ?,
                                    is_ko = ?
                                WHERE id = ?
                                """,
                                (
                                    restored_rating,
                                    restored_is_ko,
                                    existing["id"],
                                )
                            )

                            # Auch die bereits geladene
                            # property_data-Struktur korrigieren,
                            # damit Telegram sofort wieder den
                            # richtigen Zustand anzeigt.
                            property_data[
                                "rating"
                            ] = restored_rating

                            property_data[
                                "is_ko"
                            ] = restored_is_ko

                        restore_conn.commit()

                        restored_not_interested = (
                            True
                        )

                        print(
                            "NOT INTERESTED RESTORED: "
                            f"{portal} | "
                            f"{portal_id}",
                            flush=True
                        )

                finally:
                    restore_conn.close()

            property_type = property_data.get(
                "property_type"
            )

            if restored_not_interested:

                send_message(
                    "♻️ Objekt wieder aufgenommen\n\n"
                    + format_property(
                        property_data
                    ),
                    reply_markup=(
                        property_action_keyboard(
                            property_data[
                                "portal_id"
                            ],
                            property_type
                            or "unknown",
                            "new"
                        )
                    )
                )

                return

            if result.get("status") == "blacklisted":
                prefix = (
                    "⛔ Objekt steht auf der Blacklist.\n\n"
                )

            elif result["duplicate"]:
                prefix = (
                    "♻️ Objekt bereits vorhanden.\n\n"
                )

            else:
                prefix = (
                    "✅ Objekt manuell aufgenommen.\n\n"
                )

            send_message(
                prefix

                + monitor_format_property(
                    property_data
                ),

                property_action_keyboard(
                    property_data["portal_id"],
                    property_type,
                    "new"
                )
            )

        except Exception as exc:
            print(
                "URL IMPORT ERROR: "
                f"{type(exc).__name__}: "
                f"{exc}",
                flush=True
            )

            send_message(
                "❌ Link konnte nicht importiert "
                "werden.\n\n"
                f"{type(exc).__name__}: "
                f"{exc}"
            )
            time.sleep(5)
        return

    parts = text.split()

    command = (
        parts[0]
        .split("@")[0]
        .lower()
    )

    if command == "/condition":

        if len(parts) != 3:

            send_message(
                "Verwendung:\n"
                "/condition <ID> <WERT>"
            )

            return

        send_message(
            set_house_condition(
                parts[1],
                parts[2]
            )
        )

        return

    if command == "/inspect":

        portal_id = text.partition(" ")[2].strip()

        if not portal_id:

            send_message(
                "Verwendung:\n"
                "/inspect <ID>"
            )

            return

        conn = sqlite3.connect(DB_PATH)

        row = conn.execute(
            """
            SELECT property_type
            FROM properties
            WHERE portal_id = ?
            ORDER BY last_seen DESC
            LIMIT 1
            """,
            (portal_id,)
        ).fetchone()

        conn.close()

        property_type = (
            row[0]
            if row and row[0]
            else "unknown"
        )

        send_message(
            inspect_property(
                portal_id
            ),
            condition_keyboard(
                portal_id,
                property_type,
                "new"
            )
        )

        return

    # --------------------------------------------------------
    # Pending manual energy-value input
    # --------------------------------------------------------

    pending_energy = (
        PENDING_ENERGY_VALUES.get(
            chat_id
        )
    )

    if (
        pending_energy
        and not text.startswith("/")
    ):

        try:

            result = set_energy_value(
                DB_PATH,
                pending_energy[
                    "portal_id"
                ],
                text,
            )

        except Exception as exc:

            send_message(
                "❌ Energiewert nicht erkannt.\n\n"
                "Bitte nur eine Zahl senden, z. B.\n"
                "184,7\n\n"
                f"{type(exc).__name__}: {exc}"
            )

            return

        PENDING_ENERGY_VALUES.pop(
            chat_id,
            None,
        )

        if result.get(
            "status"
        ) == "already_complete":

            result_text = (
                "⚡ Energiedaten waren inzwischen "
                "bereits vorhanden."
            )

        else:

            result_text = (
                "✅ Energiewert gespeichert: "
                + str(
                    result.get("label")
                    or text
                )
            )

        old_message_id = pending_energy.get(
            "message_id"
        )

        if old_message_id:

            try:

                telegram_api(
                    "editMessageText",
                    {
                        "chat_id":
                            TELEGRAM_CHAT_ID,
                        "message_id":
                            old_message_id,
                        "text": result_text,
                        "disable_web_page_preview":
                            "true",
                    }
                )

            except Exception as exc:

                print(
                    "ENERGY VALUE RESULT EDIT ERROR: "
                    f"{exc}",
                    flush=True,
                )

        row, total = incomplete_first_energy(
            DB_PATH
        )

        if row is None:

            next_text = (
                result_text
                + "\n\n"
                + "🎉 Keine offenen Energiedaten mehr.\n\n"
                + incomplete_overview_text(
                    DB_PATH
                )
            )

            next_keyboard = incomplete_overview_keyboard(
                DB_PATH
            )

        else:

            next_text = incomplete_energy_text(
                row,
                1,
                total,
            )

            next_keyboard = incomplete_energy_keyboard(
                row
            )

        send_message(
            next_text,
            next_keyboard,
        )

        return


    # --------------------------------------------------------
    # Pending manual-coordinate input
    # --------------------------------------------------------

    chat_key = str(
        message.get(
            "chat",
            {},
        ).get(
            "id"
        )
    )

    pending_coords = (
        PENDING_COORDINATES.get(
            chat_key
        )
    )

    if (
        pending_coords
        and not text.startswith("/")
    ):

        try:

            resolved = (
                resolve_manual_location(
                    text
                )
            )

        except Exception as exc:

            print(
                "MANUAL GEOCODING ERROR: "
                f"{type(exc).__name__}: "
                f"{exc}",
                flush=True,
            )

            send_message(
                "❌ Die Adresse konnte wegen "
                "eines Geocoding-Fehlers nicht "
                "geprüft werden.\n\n"
                "Die Eingabe bleibt geöffnet."
            )

            return

        if resolved is None:

            send_message(
                "❌ Standort nicht erkannt.\n\n"
                "Bitte entweder Koordinaten senden:\n"
                "52.403560, 12.147920\n\n"
                "oder eine Anschrift, z. B.:\n"
                "Dorfstraße 17, 06909 Priesitz\n\n"
                "Auch Straße + Ort ist möglich.\n\n"
                "Die Eingabe bleibt geöffnet."
            )

            return

        latitude = resolved[
            "latitude"
        ]

        longitude = resolved[
            "longitude"
        ]

        source = resolved[
            "source"
        ]

        display_name = resolved[
            "display_name"
        ]

        PENDING_COORDINATES.pop(
            chat_key,
            None,
        )

        if display_name:

            progress_text = (
                "📍 Adresse gefunden:\n"
                f"{display_name}\n\n"
                f"{latitude:.6f}, "
                f"{longitude:.6f}\n\n"
                "🔄 Wasser, Nachbarn und Lärm "
                "werden neu berechnet …"
            )

        else:

            progress_text = (
                "🔄 Koordinaten werden gespeichert.\n"
                "Wasser, Nachbarn und Lärm "
                "werden neu berechnet …"
            )

        if (
            pending_coords.get("number") in ("iwg", "iwl")
            and pending_coords.get("message_id")
        ):

            telegram_api(
                "editMessageText",
                {
                    "chat_id":
                        TELEGRAM_CHAT_ID,
                    "message_id":
                        pending_coords[
                            "message_id"
                        ],
                    "text": progress_text,
                    "disable_web_page_preview":
                        "true",
                    "reply_markup":
                        json.dumps(
                            {
                                "inline_keyboard": []
                            }
                        ),
                }
            )

        else:

            send_message(
                progress_text
            )

        result = set_manual_coordinates(
            pending_coords["portal_id"],
            latitude,
            longitude,
            source=source,
        )

        if pending_coords.get(
            "number"
        ) in ("iwg", "iwl"):

            locality_workflow = (
                pending_coords.get("number") == "iwl"
            )

            if locality_workflow:
                rows = LOCALITY_LAB.rows(incomplete_locality_rows(DB_PATH))
                row, total = (rows[0] if rows else None), len(rows)
            else:
                row, total = incomplete_first_geo(
                    DB_PATH
                )

            if row is None:

                next_text = (
                    (
                        "✅ Alle provisorischen Lagen "
                        "bearbeitet.\n\n"
                        if locality_workflow
                        else "✅ Geo-Prüfung abgeschlossen.\n\n"
                    )
                    + incomplete_overview_text(
                        DB_PATH
                    )
                )

                next_keyboard = (
                    incomplete_overview_keyboard(
                        DB_PATH
                    )
                )

            else:

                if locality_workflow:
                    next_text = incomplete_locality_text(
                        row,
                        1,
                        total,
                    )
                    next_keyboard = incomplete_locality_keyboard(
                        row
                    )
                else:
                    next_text = incomplete_geo_text(
                        row,
                        1,
                        total,
                    )
                    next_keyboard = incomplete_geo_keyboard(
                        row
                    )

            message_id = pending_coords.get(
                "message_id"
            )

            if message_id:

                telegram_api(
                    "editMessageText",
                    {
                        "chat_id":
                            TELEGRAM_CHAT_ID,
                        "message_id":
                            message_id,
                        "text": result,
                        "disable_web_page_preview":
                            "true",
                        "reply_markup":
                            json.dumps(
                                {
                                    "inline_keyboard": []
                                }
                            ),
                    }
                )

            sent = send_message(
                next_text,
                next_keyboard,
            )

            if locality_workflow:
                LOCALITY_LAB.track((sent or {}).get('result', {}).get('message_id'), row)

            return

        send_message(
            result,
            property_action_keyboard(
                pending_coords[
                    "portal_id"
                ],
                pending_coords[
                    "property_type"
                ],
                pending_coords[
                    "number"
                ],
            ),
        )

        return


    # --------------------------------------------------------
    # /coords fallback
    #
    # /coords ID
    # /coords ID LAT LON
    # /coords-auto ID
    # --------------------------------------------------------

    if command == "/coords":

        if len(parts) == 2:

            portal_id = parts[1]

            status, manual = (
                get_coordinate_status(
                    portal_id
                )
            )

            conn = sqlite3.connect(
                DB_PATH
            )

            row = conn.execute(
                """
                SELECT property_type
                FROM properties
                WHERE portal_id = ?
                ORDER BY last_seen DESC
                LIMIT 1
                """,
                (
                    portal_id,
                )
            ).fetchone()

            conn.close()

            property_type = (
                row[0]
                if row and row[0]
                else "unknown"
            )

            send_message(
                status,
                coordinates_keyboard(
                    portal_id,
                    property_type,
                    "new",
                    manual,
                ),
            )

            return

        if len(parts) >= 3:

            portal_id = parts[1]

            value = " ".join(
                parts[2:]
            ).strip()

            try:

                resolved = (
                    resolve_manual_location(
                        value
                    )
                )

            except Exception as exc:

                print(
                    "MANUAL GEOCODING ERROR: "
                    f"{type(exc).__name__}: "
                    f"{exc}",
                    flush=True,
                )

                send_message(
                    "❌ Geocoding fehlgeschlagen.\n\n"
                    f"{type(exc).__name__}: "
                    f"{exc}"
                )

                return

            if resolved is None:

                send_message(
                    "Standort nicht gefunden.\n\n"
                    "Verwendung:\n"
                    "/coords <ID> <Breite> <Länge>\n"
                    "/coords <ID> <Adresse>\n\n"
                    "Beispiele:\n"
                    "/coords 165639543 "
                    "51.692836 12.820920\n\n"
                    "/coords 165639543 "
                    "Dorfstraße 17, 06909 Priesitz"
                )

                return

            latitude = resolved[
                "latitude"
            ]

            longitude = resolved[
                "longitude"
            ]

            source = resolved[
                "source"
            ]

            display_name = resolved[
                "display_name"
            ]

            if display_name:

                send_message(
                    "📍 Adresse gefunden:\n"
                    f"{display_name}\n\n"
                    f"{latitude:.6f}, "
                    f"{longitude:.6f}\n\n"
                    "🔄 Wasser, Nachbarn und Lärm "
                    "werden neu berechnet …"
                )

            else:

                send_message(
                    "🔄 Koordinaten werden gespeichert.\n"
                    "Wasser, Nachbarn und Lärm "
                    "werden neu berechnet …"
                )

            send_message(
                set_manual_coordinates(
                    portal_id,
                    latitude,
                    longitude,
                    source=source,
                )
            )

            return

        send_message(
            "Verwendung:\n"
            "/coords <ID>\n"
            "/coords <ID> <Breite> <Länge>"
        )

        return


    if command == "/coords-auto":

        if len(parts) != 2:

            send_message(
                "Verwendung:\n"
                "/coords-auto <ID>"
            )

            return

        send_message(
            "🔄 Manueller Override wird entfernt.\n"
            "Geocoding und Geodaten werden "
            "neu berechnet …"
        )

        send_message(
            clear_manual_coordinates(
                parts[1]
            )
        )

        return


    if command == "/purge":

        days = 30

        if len(parts) >= 2:

            try:
                days = int(parts[1])

            except ValueError:

                send_message(
                    "Verwendung:\n"
                    "/purge\n"
                    "/purge <Tage>"
                )

                return

        send_message(
            purge_preview(days),
            purge_keyboard(days)
        )

        return

    if command == "/blacklist":

        term = text.partition(" ")[2].strip()

        send_message(
            add_blacklist_term(term)
        )

        return

    if command in (
        "/find",
        "/search"
    ):

        query = text.partition(" ")[2].strip()

        result, keyboard = find_properties(
            query,
            with_keyboard=True,
        )

        send_message(
            result,
            keyboard,
        )

        return

    if command in (
        "/favorites",
        "/merkliste",
    ):

        rows = get_favorite_rows()

        if not rows:

            send_message(
                "⭐ Merkliste ist leer."
            )

            return

        send_message(
            f"⭐ MERKLISTE · {len(rows)} Objekt(e)"
        )

        for number, p in enumerate(
            rows,
            1,
        ):

            property_type = (
                p.get("property_type")
                or "house"
            )

            send_message(
                format_property_card(
                    p,
                    number,
                ),
                property_action_keyboard(
                    p["portal_id"],
                    property_type,
                    number,
                )
            )

        return


    if command == "/top3land":

        rows = get_top_property_rows(
            "land",
            3
        )

        send_message(
            f"🏆 TOP {len(rows)} GRUNDSTÜCKE"
        )

        for number, p in enumerate(
            rows,
            1
        ):

            send_message(
                format_property_card(
                    p,
                    number
                ),
                property_action_keyboard(
                    p["portal_id"],
                    "land",
                    number
                )
            )

        send_chances('land', rows)

        return

    if command == "/top3house":

        rows = get_top_property_rows(
            "house",
            3
        )

        send_message(
            f"🏆 TOP {len(rows)} HÄUSER / HÖFE"
        )


        for number, p in enumerate(
            rows,
            1
        ):

            send_message(
                format_property_card(
                    p,
                    number
                ),
                property_action_keyboard(
                    p["portal_id"],
                    "house",
                    number
                )
            )


        send_chances('house', rows)

        return


    if command == "/top10house":

        rows = get_top_property_rows(
            "house",
            10
        )

        send_message(
            f"🏆 TOP {len(rows)} HÄUSER / HÖFE"
        )


        for number, p in enumerate(
            rows,
            1
        ):

            send_message(
                format_property_card(
                    p,
                    number
                ),
                property_action_keyboard(
                    p["portal_id"],
                    "house",
                    "new"
                )
            )


        return


    if command == "/buildability":

        if len(parts) != 3:

            send_message(
                "Verwendung:\n"
                "/buildability "
                "<ID> <WERT>\n\n"
                "Beispiel:\n"
                "/buildability "
                "168620939 EXTERNALAREA"
            )

            return

        send_message(
            set_buildability(
                parts[1],
                parts[2]
            )
        )

        return

    if command == "/property":

        if len(parts) != 2:

            send_message(
                "Verwendung:\n"
                "/property <ID>"
            )

            return

        portal_id = parts[1]

        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            """
            SELECT property_type
            FROM properties
            WHERE portal_id = ?
            ORDER BY last_seen DESC
            LIMIT 1
            """,
            (portal_id,)
        ).fetchone()
        conn.close()

        property_type = (
            row[0]
            if row and row[0]
            else "unknown"
        )

        send_message(
            get_property(portal_id),
            property_action_keyboard(
                portal_id,
                property_type,
                "new"
            )
        )

        return

    if command == "/incomplete":

        LOCALITY_LAB.reset()

        send_message(
            incomplete_overview_text(
                DB_PATH
            ),
            incomplete_overview_keyboard(
                DB_PATH
            ),
        )

        return


    if command in (
        "/help",
        "/start"
    ):

        send_message(
            "🏠 Immobilien-Monitor\n\n"

            "🔎 Suchen & Anzeigen\n"
            "/find <Suchtext>\n"
            "/property <ID>\n"
            "/inspect <ID>\n"
            "/top3land\n"
            "/top3house\n"
            "/top10house\n"
            "/merkliste\n"
            "/incomplete\n\n"

            "🧮 Bewertung\n"
            "Ein Score wird erst angezeigt, wenn alle "
            "relevanten Prüfungen abgeschlossen sind.\n"
            "/incomplete zeigt Objekte mit noch "
            "fehlenden Prüfungen zur Abarbeitung.\n"
            "Der Button „🧮 Erklärung“ zeigt die "
            "Einzelbewertung bzw. fehlende Prüfungen.\n\n"

            "🚫 Blacklist & Aufräumen\n"
            "/blacklist <Begriff>\n"
            "/purge\n"
            "/purge <Tage>\n\n"

            "📍 Koordinaten\n"
            "/coords <ID>\n"
            "/coords <ID> <Breite> <Länge>\n"
            "/coords-auto <ID>\n\n"

            "🏗 Bebaubarkeit setzen\n"
            "/buildability <ID> <WERT>\n\n"
            "Werte:\n"
            "BUILDING_PERMIT\n"
            "CONSTRUCTIONPLAN\n"
            "NEIGHBOURCONSTRUCTION\n"
            "EXTERNALAREA\n"
            "NO_INFORMATION\n\n"

            "🔧 Hauszustand setzen\n"
            "/condition <ID> <WERT>\n\n"
            "Werte:\n"
            "turnkey\n"
            "good\n"
            "maintained\n"
            "cosmetic_renovation\n"
            "renovation_needed\n"
            "major_renovation\n"
            "dilapidated\n"
            "unknown\n\n"

            "ℹ️ Hinweise\n"
            "/purge zeigt zuerst eine Vorschau und "
            "löscht erst nach Bestätigung.\n"
            "Details, Zustand, Koordinaten, Merkliste "
            "und Offline können auch über die Buttons "
            "bedient werden."
        )

        return

def dog_tax_prompt_keyboard(session):
    rows = []
    if session.get('stage') == 'model':
        rows.extend([
            [{'text': '📊 Staffel je Hund', 'callback_data': 'dt:model:staffel'}],
            [{'text': '👥 Satz für alle Hunde', 'callback_data': 'dt:model:alle'}],
        ])
    elif session.get('stage') == 'preview':
        rows.extend([
            [{'text': '✅ Bestätigen', 'callback_data': 'dt:confirm'}],
            [{'text': '✏️ Quelle korrigieren', 'callback_data': 'dt:correct'}],
        ])
    rows.append([{'text': '⏭ Für jetzt überspringen', 'callback_data': 'dt:skip'}])
    rows.append([{'text': '✖ Abbrechen', 'callback_data': 'dt:cancel'}])
    return {'inline_keyboard': rows}


def _edit_callback_message(callback, text, keyboard=None):
    message = callback.get('message', {})
    data = {
        'chat_id': TELEGRAM_CHAT_ID,
        'message_id': message['message_id'],
        'text': text,
        'disable_web_page_preview': 'true',
    }
    if keyboard is not None:
        data['reply_markup'] = json.dumps(keyboard)
    telegram_api('editMessageText', data)


def _ack_callback(callback):
    try:
        telegram_api('answerCallbackQuery', {'callback_query_id': callback['id']})
    except Exception as exc:
        print(f'DOG TAX CALLBACK ACK ERROR: {exc}', flush=True)


def handle_callback(callback):

    message = callback.get(
        "message",
        {}
    )

    chat = message.get(
        "chat",
        {}
    )

    chat_id = str(
        chat.get("id")
    )

    if chat_id != str(
        TELEGRAM_CHAT_ID
    ):
        return

    data = (
        callback.get("data")
        or ""
    )

    if data.startswith('dt:'):
        _ack_callback(callback)
        action = data.split(':', 2)

        if len(action) == 3 and action[1] == 'start':
            portal_id = action[2]
            property_data = get_property_data(portal_id)
            if not property_data or not is_house_type(property_data.get('property_type')):
                _edit_callback_message(callback, '❌ Haus nicht gefunden.')
                return
            from dog_tax_wizard import new_session
            session = new_session(property_data, property_data.get('property_type') or 'house', 'new')
            PENDING_DOG_TAX[chat_id] = session
            _edit_callback_message(
                callback,
                f"🐕 Hundesteuer für\n{property_data.get('title') or portal_id}\n"
                f"📍 {property_data.get('location') or 'Ort unbekannt'}\n\n"
                "Bitte jetzt den Link zur Hundesteuersatzung senden oder die PDF hochladen.\n\n"
                "Ich ordne das Objekt der Gemeinde zu, lese die Sätze und zeige vor dem Speichern eine Vorschau.",
                dog_tax_prompt_keyboard(session),
            )
            return

        session = PENDING_DOG_TAX.get(chat_id)
        if not session:
            _edit_callback_message(callback, 'ℹ️ Diese Hundesteuer-Aufgabe ist nicht mehr aktiv. Bitte /hundesteuer neu öffnen.')
            return

        if len(action) == 3 and action[1] == 'model':
            from dog_tax_wizard import choose_model, note_existing_tariff
            try:
                result = choose_model(session, action[2])
                if session.get('stage') == 'preview':
                    with dog_tax_database(DB_PATH) as conn:
                        existing = load_stored_tariff(conn, session['municipality_key'])
                    result = note_existing_tariff(session, existing)
            except ValueError as exc:
                result = f'⚠️ {exc}'
            _edit_callback_message(callback, result, dog_tax_prompt_keyboard(session))
            return

        command = action[1]
        if command in ('skip', 'cancel'):
            PENDING_DOG_TAX.pop(chat_id, None)
            label = '⏭ Für jetzt übersprungen.' if command == 'skip' else '✖ Hundesteuer-Eingabe abgebrochen.'
            _edit_callback_message(callback, label + '\n\n' + get_property(session['property']['portal_id']),
                                   property_details_keyboard(session['property']['portal_id'], session['property_type'], session['number']))
            return

        if command == 'correct':
            for field in ('source_reference', 'valid_from', 'model', 'rates', 'source_version',
                          'citation', 'document_municipality', 'document_warning'):
                session.pop(field, None)
            session['stage'] = 'source'
            _edit_callback_message(callback, '✏️ Bitte einen anderen Satzungslink senden oder eine andere PDF hochladen.',
                                   dog_tax_prompt_keyboard(session))
            return

        if command == 'confirm':
            if session.get('stage') != 'preview':
                _edit_callback_message(callback, '⚠️ Die Angaben sind noch nicht vollständig.', dog_tax_prompt_keyboard(session))
                return
            from dog_tax_wizard import tariff_from_session
            try:
                tariff = tariff_from_session(session)
                save_assignment_and_tariff(DB_PATH, session['property'], tariff, session['municipality_source'])
            except Exception as exc:
                _edit_callback_message(callback, f'⚠️ Speichern fehlgeschlagen: {exc}', dog_tax_prompt_keyboard(session))
                return
            PENDING_DOG_TAX.pop(chat_id, None)
            _edit_callback_message(callback, '✅ Hundesteuer gespeichert.\n\n' + get_property(session['property']['portal_id']),
                                   property_details_keyboard(session['property']['portal_id'], session['property_type'], session['number']))
            return

        return

    # --------------------------------------------------------
    # Incomplete workbench
    # --------------------------------------------------------

    if data in (
        "iw:menu",
        "iw:condition",
        "iw:energy",
        "iw:geo",
        "iw:locality",
    ):

        LOCALITY_LAB.reset()

        try:

            telegram_api(
                "answerCallbackQuery",
                {
                    "callback_query_id":
                        callback["id"],
                }
            )

        except Exception as exc:

            print(
                "INCOMPLETE WORKBENCH ACK ERROR: "
                f"{exc}",
                flush=True,
            )

        if data != "iw:energy":
            set_active_energy_lab(
                None,
                None,
            )

        if data != "iw:condition":
            set_active_condition_lab(
                None,
                None,
            )

        if data == "iw:menu":

            text = incomplete_overview_text(
                DB_PATH
            )

            keyboard = incomplete_overview_keyboard(
                DB_PATH
            )

        elif data == "iw:condition":

            row, total = incomplete_first_condition(
                DB_PATH
            )

            set_active_condition_lab(
                message.get("message_id"),
                row,
            )

            if row is None:

                text = (
                    "✅ Keine offenen Zustände mehr.\n\n"
                    + incomplete_overview_text(
                        DB_PATH
                    )
                )

                keyboard = incomplete_overview_keyboard(
                    DB_PATH
                )

            else:

                text = incomplete_condition_text(
                    row,
                    1,
                    total,
                )

                keyboard = incomplete_condition_keyboard(
                    row
                )

        elif data == "iw:geo":

            row, total = incomplete_first_geo(
                DB_PATH
            )

            if row is None:

                text = (
                    "✅ Keine offenen Geo-Prüfungen mehr.\n\n"
                    + incomplete_overview_text(
                        DB_PATH
                    )
                )

                keyboard = incomplete_overview_keyboard(
                    DB_PATH
                )

            else:

                text = incomplete_geo_text(
                    row,
                    1,
                    total,
                )

                keyboard = incomplete_geo_keyboard(
                    row
                )

        elif data == "iw:locality":

            SKIPPED_LOCALITY_LAB.clear()

            row, total = incomplete_first_locality(
                DB_PATH
            )

            LOCALITY_LAB.track(message.get('message_id'), row)

            if row is None:

                text = (
                    "✅ Keine provisorischen Lagen mehr.\n\n"
                    + incomplete_overview_text(
                        DB_PATH
                    )
                )

                keyboard = incomplete_overview_keyboard(
                    DB_PATH
                )

            else:

                text = incomplete_locality_text(
                    row,
                    1,
                    total,
                )

                keyboard = incomplete_locality_keyboard(
                    row
                )

        else:

            row, total = incomplete_first_energy(
                DB_PATH
            )

            set_active_energy_lab(
                message.get("message_id"),
                row,
            )

            if row is None:

                text = (
                    "✅ Keine offenen Energiedaten mehr.\n\n"
                    + incomplete_overview_text(
                        DB_PATH
                    )
                )

                keyboard = incomplete_overview_keyboard(
                    DB_PATH
                )

            else:

                text = incomplete_energy_text(
                    row,
                    1,
                    total,
                )

                keyboard = incomplete_energy_keyboard(
                    row
                )

        telegram_api(
            "editMessageText",
            {
                "chat_id":
                    TELEGRAM_CHAT_ID,
                "message_id":
                    message["message_id"],
                "text": text,
                "disable_web_page_preview":
                    "true",
                "reply_markup":
                    json.dumps(
                        keyboard
                    ),
            }
        )

        return


    # --------------------------------------------------------
    # Incomplete laboratory: Energie
    # --------------------------------------------------------

    if data.startswith("iwev:"):

        set_active_energy_lab(
            None,
            None,
        )

        try:

            _, portal_id = data.split(
                ":",
                1,
            )

        except ValueError:
            return

        chat_key = str(
            message.get(
                "chat",
                {},
            ).get(
                "id"
            )
        )

        PENDING_ENERGY_VALUES[
            chat_key
        ] = {
            "portal_id": portal_id,
            "message_id": message.get(
                "message_id"
            ),
        }

        try:

            telegram_api(
                "answerCallbackQuery",
                {
                    "callback_query_id":
                        callback["id"],
                    "text": "Energiewert eingeben",
                }
            )

        except Exception as exc:

            print(
                "ENERGY VALUE ACK ERROR: "
                f"{exc}",
                flush=True,
            )

        telegram_api(
            "editMessageText",
            {
                "chat_id":
                    TELEGRAM_CHAT_ID,
                "message_id":
                    message["message_id"],
                "text": (
                    "⚡ ENERGIEWERT MANUELL\n\n"
                    f"ID: {portal_id}\n\n"
                    "Bitte nur den Wert in kWh/(m²·a) senden.\n\n"
                    "Beispiele:\n"
                    "184,7\n"
                    "92"
                ),
                "disable_web_page_preview":
                    "true",
            }
        )

        return


    if data.startswith("iwe:"):

        try:

            (
                _,
                portal_id,
                energy_code,
            ) = data.split(
                ":",
                2,
            )

        except ValueError:
            return

        try:

            result = set_energy_choice(
                DB_PATH,
                portal_id,
                energy_code,
            )

            if result.get("status") == "already_complete":

                saved_text = (
                    "⚡ Energiedaten waren inzwischen "
                    "bereits vorhanden."
                )

            else:

                saved_text = (
                    "✅ "
                    + energy_choice_label(
                        energy_code
                    )
                    + " gespeichert"
                )

            try:

                telegram_api(
                    "answerCallbackQuery",
                    {
                        "callback_query_id":
                            callback["id"],
                        "text": saved_text,
                    }
                )

            except Exception as exc:

                print(
                    "ENERGY LAB ACK ERROR: "
                    f"{exc}",
                    flush=True,
                )

        except Exception as exc:

            print(
                "ENERGY LAB ERROR: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

            try:

                telegram_api(
                    "answerCallbackQuery",
                    {
                        "callback_query_id":
                            callback["id"],
                        "text": (
                            "❌ "
                            f"{type(exc).__name__}: {exc}"
                        ),
                        "show_alert": "true",
                    }
                )

            except Exception:
                pass

            return

        row, total = incomplete_first_energy(
            DB_PATH
        )

        set_active_energy_lab(
            message.get("message_id"),
            row,
        )

        if row is None:

            text = (
                saved_text
                + "\n\n"
                + "🎉 Keine offenen Energiedaten mehr.\n\n"
                + incomplete_overview_text(
                    DB_PATH
                )
            )

            keyboard = incomplete_overview_keyboard(
                DB_PATH
            )

        else:

            text = (
                saved_text
                + "\n\n"
                + incomplete_energy_text(
                    row,
                    1,
                    total,
                )
            )

            keyboard = incomplete_energy_keyboard(
                row
            )

        telegram_api(
            "editMessageText",
            {
                "chat_id":
                    TELEGRAM_CHAT_ID,
                "message_id":
                    message["message_id"],
                "text": text,
                "disable_web_page_preview":
                    "true",
                "reply_markup":
                    json.dumps(
                        keyboard
                    ),
            }
        )

        return


    # --------------------------------------------------------
    # Score erklären
    # --------------------------------------------------------

    if data.startswith(
        "explain:"
    ):

        parts = data.split(
            ":",
            3,
        )

        portal_id = (
            parts[1]
            if len(parts) >= 2
            else ""
        )

        if not portal_id:
            return

        if len(parts) == 4:

            property_type = parts[2]
            number = parts[3]

        else:

            conn = sqlite3.connect(
                DB_PATH
            )

            row = conn.execute(
                """
                SELECT property_type
                FROM properties
                WHERE portal_id = ?
                ORDER BY last_seen DESC
                LIMIT 1
                """,
                (
                    portal_id,
                )
            ).fetchone()

            conn.close()

            property_type = (
                row[0]
                if row and row[0]
                else "unknown"
            )

            number = "new"

        try:

            telegram_api(
                "answerCallbackQuery",
                {
                    "callback_query_id":
                        callback["id"],
                }
            )

        except Exception as exc:

            print(
                "EXPLAIN CALLBACK ACK ERROR: "
                f"{exc}",
                flush=True
            )

        telegram_api(
            "editMessageText",
            {
                "chat_id":
                    TELEGRAM_CHAT_ID,
                "message_id":
                    message["message_id"],
                "text":
                    format_score_explanation(
                        portal_id
                    ),
                "disable_web_page_preview":
                    "true",
                "reply_markup":
                    json.dumps(
                        {
                            "inline_keyboard": [
                                [
                                    {
                                        "text": "⬅️ Zurück",
                                        "callback_data": (
                                            f"back:{portal_id}:"
                                            f"{property_type}:{number}"
                                        ),
                                    }
                                ]
                            ]
                        }
                    ),
            }
        )

        return


    # --------------------------------------------------------
    # Unvollständige Objekte: nächstes
    # --------------------------------------------------------

    if data.startswith(
        "inext:"
    ):

        current_portal_id = (
            data.split(
                ":",
                1
            )[1]
        )

        try:

            telegram_api(
                "answerCallbackQuery",
                {
                    "callback_query_id":
                        callback["id"],
                }
            )

        except Exception as exc:

            print(
                "INCOMPLETE CALLBACK ACK ERROR: "
                f"{exc}",
                flush=True
            )

        rows = get_incomplete_rows()

        if not rows:

            telegram_api(
                "editMessageText",
                {
                    "chat_id":
                        TELEGRAM_CHAT_ID,
                    "message_id":
                        message[
                            "message_id"
                        ],
                    "text":
                        "✅ Keine unvollständigen "
                        "Objekte mehr.",
                }
            )

            return

        current_index = None

        for index, row in enumerate(
            rows
        ):

            if str(
                row.get(
                    "portal_id"
                )
            ) == str(
                current_portal_id
            ):

                current_index = (
                    index
                )

                break

        if current_index is None:

            next_index = 0

        else:

            next_index = (
                current_index + 1
            ) % len(rows)

        property_data = rows[
            next_index
        ]

        telegram_api(
            "editMessageText",
            {
                "chat_id":
                    TELEGRAM_CHAT_ID,
                "message_id":
                    message[
                        "message_id"
                    ],
                "text":
                    format_incomplete_property(
                        property_data,
                        next_index + 1,
                        len(rows),
                    ),
                "disable_web_page_preview":
                    "true",
                "reply_markup":
                    json.dumps(
                        incomplete_keyboard(
                            property_data,
                            has_next=(
                                len(rows) > 1
                            ),
                        )
                    ),
            }
        )

        return


    if data.startswith("property:"):

        try:

            (
                _,
                portal_id,
                property_type,
                number
            ) = data.split(
                ":",
                3
            )

        except ValueError:
            return

        try:

            telegram_api(
                "answerCallbackQuery",
                {
                    "callback_query_id":
                        callback["id"]
                }
            )

        except Exception as exc:

            print(
                f"CALLBACK ACK ERROR: {exc}",
                flush=True
            )

        telegram_api(
            "editMessageText",
            {
                "chat_id": TELEGRAM_CHAT_ID,
                "message_id": message["message_id"],
                "text": get_property(
                    portal_id
                ),
                "disable_web_page_preview": "true",
                "reply_markup": json.dumps(
                    property_details_keyboard(
                        portal_id,
                        property_type,
                        number
                    )
                )
            }
        )

    # --------------------------------------------------------
    # Favorite / Merkliste
    # --------------------------------------------------------

    if data.startswith("favorite:"):

        try:

            (
                _,
                portal_id,
                property_type,
                number,
            ) = data.split(
                ":",
                3,
            )

        except ValueError:
            return

        favorite = toggle_favorite(
            portal_id
        )

        try:

            telegram_api(
                "answerCallbackQuery",
                {
                    "callback_query_id":
                        callback["id"],
                    "text":
                        (
                            "⭐ Zur Merkliste hinzugefügt"
                            if favorite
                            else "Von Merkliste entfernt"
                        ),
                }
            )

        except Exception as exc:

            print(
                f"CALLBACK ACK ERROR: {exc}",
                flush=True,
            )

        telegram_api(
            "editMessageReplyMarkup",
            {
                "chat_id":
                    TELEGRAM_CHAT_ID,

                "message_id":
                    message[
                        "message_id"
                    ],

                "reply_markup":
                    json.dumps(
                        property_action_keyboard(
                            portal_id,
                            property_type,
                            number,
                        )
                    ),
            }
        )

        return

    if data.startswith("iwl_skip:"):

        try:
            (
                _,
                portal_id,
            ) = data.split(
                ":",
                1,
            )

        except ValueError:
            return

        try:

            telegram_api(
                "answerCallbackQuery",
                {
                    "callback_query_id":
                        callback["id"],
                }
            )

        except Exception as exc:

            print(
                "LOCALITY SKIP ACK ERROR: "
                f"{exc}",
                flush=True,
            )

        SKIPPED_LOCALITY_LAB.add(
            str(portal_id)
        )

        rows = [
            row
            for row in incomplete_locality_rows(
                DB_PATH
            )
            if str(
                row.get("portal_id")
                or ""
            ) not in SKIPPED_LOCALITY_LAB
        ]

        row = rows[0] if rows else None

        if not rows:

            text = (
                "⏭ Lage übersprungen.\n\n"
                "✅ Keine weiteren Lagen "
                "in diesem Durchgang.\n\n"
                + incomplete_overview_text(
                    DB_PATH
                )
            )

            keyboard = incomplete_overview_keyboard(
                DB_PATH
            )

        else:

            row = rows[0]

            text = (
                "⏭ Lage übersprungen.\n\n"
                + incomplete_locality_text(
                    row,
                    1,
                    len(rows),
                )
            )

            keyboard = incomplete_locality_keyboard(
                row
            )

        telegram_api(
            "editMessageText",
            {
                "chat_id":
                    TELEGRAM_CHAT_ID,
                "message_id":
                    message["message_id"],
                "text":
                    text,
                "disable_web_page_preview":
                    "true",
                "reply_markup":
                    json.dumps(
                        keyboard
                    ),
            }
        )

        LOCALITY_LAB.track(message['message_id'], row)
        return

    # --------------------------------------------------------
    # Coordinates
    # --------------------------------------------------------

    if data.startswith("coords_cancel:"):

        try:
            (
                _,
                portal_id,
                property_type,
                number,
            ) = data.split(
                ":",
                3,
            )

        except ValueError:
            return

        pending = PENDING_COORDINATES.get(
            chat_id
        )

        if (
            pending
            and str(
                pending.get("portal_id")
            ) == str(portal_id)
        ):
            PENDING_COORDINATES.pop(
                chat_id,
                None,
            )

        try:

            telegram_api(
                "answerCallbackQuery",
                {
                    "callback_query_id":
                        callback["id"],
                }
            )

        except Exception as exc:

            print(
                "COORD CANCEL ACK ERROR: "
                f"{exc}",
                flush=True,
            )

        conn = sqlite3.connect(
            DB_PATH
        )
        conn.row_factory = sqlite3.Row

        row = conn.execute(
            """
            SELECT *
            FROM properties
            WHERE portal_id = ?
            ORDER BY last_seen DESC
            LIMIT 1
            """,
            (
                portal_id,
            )
        ).fetchone()

        conn.close()

        if not row:
            return

        p = dict(row)

        telegram_api(
            "editMessageText",
            {
                "chat_id":
                    TELEGRAM_CHAT_ID,
                "message_id":
                    message["message_id"],
                "text":
                    format_property_card(
                        p
                    ),
                "disable_web_page_preview":
                    "true",
                "reply_markup":
                    json.dumps(
                        property_action_keyboard(
                            portal_id,
                            property_type,
                            number,
                        )
                    ),
            }
        )

        return


    if data.startswith("coords_set:"):

        try:
            (
                _,
                portal_id,
                property_type,
                number,
            ) = data.split(
                ":",
                3,
            )

        except ValueError:
            return

        try:

            telegram_api(
                "answerCallbackQuery",
                {
                    "callback_query_id":
                        callback["id"]
                }
            )

        except Exception as exc:

            print(
                f"CALLBACK ACK ERROR: {exc}",
                flush=True,
            )

        PENDING_COORDINATES[
            chat_id
        ] = {
            "portal_id": portal_id,
            "property_type":
                property_type,
            "number": number,
            "message_id": message.get(
                "message_id"
            ),
        }

        telegram_api(
            "editMessageText",
            {
                "chat_id":
                    TELEGRAM_CHAT_ID,
                "message_id":
                    message["message_id"],
                "text": (
                    "📍 Standort für "
                    f"{portal_id}\n\n"
                    "Bitte Koordinaten oder Anschrift senden.\n\n"
                    "Koordinaten:\n"
                    "52.403560, 12.147920\n\n"
                    "oder z. B.:\n"
                    "Dorfstraße 17, 06909 Priesitz\n\n"
                    "Auch Straße + Ort ist möglich."
                ),
                "disable_web_page_preview":
                    "true",
                "reply_markup":
                    json.dumps(
                        {
                            "inline_keyboard": [
                                [
                                    {
                                        "text": "⬅️ Abbrechen",
                                        "callback_data": (
                                            f"coords_cancel:{portal_id}:"
                                            f"{property_type}:{number}"
                                        ),
                                    }
                                ]
                            ]
                        }
                    ),
            }
        )
        return


    if data.startswith("geo_rescan:"):
        try:
            _, portal_id, property_type, number = data.split(":", 3)
        except ValueError:
            return
        try:
            telegram_api("answerCallbackQuery", {"callback_query_id": callback["id"]})
        except Exception as exc:
            print(f"CALLBACK ACK ERROR: {exc}", flush=True)
        send_message("🔄 Wasser, Nachbarn und Lärm/Bahn werden neu geprüft …")
        send_message(rescan_geo(portal_id), property_details_keyboard(portal_id, property_type, number))
        return

    if data.startswith("coords_auto:"):

        try:
            (
                _,
                portal_id,
                property_type,
                number,
            ) = data.split(
                ":",
                3,
            )

        except ValueError:
            return

        try:

            telegram_api(
                "answerCallbackQuery",
                {
                    "callback_query_id":
                        callback["id"]
                }
            )

        except Exception as exc:

            print(
                f"CALLBACK ACK ERROR: {exc}",
                flush=True,
            )

        send_message(
            "🔄 Automatische Koordinaten "
            "werden wiederhergestellt …"
        )

        result = (
            clear_manual_coordinates(
                portal_id
            )
        )

        send_message(
            result,
            property_action_keyboard(
                portal_id,
                property_type,
                number,
            ),
        )

        return


    if data.startswith("coords:"):

        try:
            (
                _,
                portal_id,
                property_type,
                number,
            ) = data.split(
                ":",
                3,
            )

        except ValueError:
            return

        try:

            telegram_api(
                "answerCallbackQuery",
                {
                    "callback_query_id":
                        callback["id"]
                }
            )

        except Exception as exc:

            print(
                f"CALLBACK ACK ERROR: {exc}",
                flush=True,
            )

        status, manual = (
            get_coordinate_status(
                portal_id
            )
        )

        telegram_api(
            "editMessageText",
            {
                "chat_id":
                    TELEGRAM_CHAT_ID,

                "message_id":
                    message[
                        "message_id"
                    ],

                "text":
                    status,

                "disable_web_page_preview":
                    "true",

                "reply_markup":
                    json.dumps(
                        coordinates_keyboard(
                            portal_id,
                            property_type,
                            number,
                            manual,
                        )
                    ),
            }
        )

        return


    if data.startswith("offline:"):

        parts = data.split(
            ":",
            3,
        )

        if len(parts) < 2:
            return

        portal_id = parts[1]

        property_type = (
            parts[2]
            if len(parts) >= 3
            else "unknown"
        )

        number = (
            parts[3]
            if len(parts) >= 4
            else "new"
        )

        try:

            result = toggle_user_status(
                DB_PATH,
                portal_id,
                "offline",
            )

        except Exception as exc:

            try:
                telegram_api(
                    "answerCallbackQuery",
                    {
                        "callback_query_id":
                            callback["id"],
                        "text": f"❌ {exc}",
                        "show_alert": "true",
                    }
                )
            except Exception:
                pass

            return

        property_type = (
            result.get("property_type")
            or property_type
            or "unknown"
        )

        status = result[
            "status"
        ]

        callback_text = (
            "↩️ Objekt wieder online"
            if status == "active"
            else "⛔ Objekt als offline markiert"
        )

        try:

            telegram_api(
                "answerCallbackQuery",
                {
                    "callback_query_id":
                        callback["id"],
                    "text": callback_text,
                }
            )

        except Exception as exc:

            print(
                f"CALLBACK ACK ERROR: {exc}",
                flush=True
            )

        telegram_api(
            "editMessageReplyMarkup",
            {
                "chat_id": TELEGRAM_CHAT_ID,
                "message_id": message["message_id"],
                "reply_markup": json.dumps(
                    property_action_keyboard(
                        portal_id,
                        property_type,
                        number,
                    )
                ),
            }
        )

        return

    if data.startswith("spam:"):

        parts = data.split(
            ":",
            3,
        )

        if len(parts) < 2:
            return

        portal_id = parts[1]

        property_type = (
            parts[2]
            if len(parts) >= 3
            else "unknown"
        )

        number = (
            parts[3]
            if len(parts) >= 4
            else "new"
        )

        try:

            result = toggle_user_status(
                DB_PATH,
                portal_id,
                "not_interested",
            )

        except Exception as exc:

            try:
                telegram_api(
                    "answerCallbackQuery",
                    {
                        "callback_query_id":
                            callback["id"],
                        "text": f"❌ {exc}",
                        "show_alert": "true",
                    }
                )
            except Exception:
                pass

            return

        property_type = (
            result.get("property_type")
            or property_type
            or "unknown"
        )

        status = result[
            "status"
        ]

        callback_text = (
            "↩️ Objekt wieder interessant"
            if status == "active"
            else "🙈 Kein Interesse"
        )

        try:

            telegram_api(
                "answerCallbackQuery",
                {
                    "callback_query_id":
                        callback["id"],
                    "text": callback_text,
                }
            )

        except Exception as exc:

            print(
                f"CALLBACK ACK ERROR: {exc}",
                flush=True
            )

        telegram_api(
            "editMessageReplyMarkup",
            {
                "chat_id": TELEGRAM_CHAT_ID,
                "message_id": message["message_id"],
                "reply_markup": json.dumps(
                    property_action_keyboard(
                        portal_id,
                        property_type,
                        number,
                    )
                ),
            }
        )

        return

    if data.startswith("back:"):

        try:

            (
                _,
                portal_id,
                property_type,
                number
            ) = data.split(
                ":",
                3
            )

        except ValueError:
            return

        try:

            telegram_api(
                "answerCallbackQuery",
                {
                    "callback_query_id":
                        callback["id"]
                }
            )

        except Exception as exc:

            print(
                f"CALLBACK ACK ERROR: {exc}",
                flush=True
            )

        # ----------------------------------------------------
        # Immer zum angeklickten Objekt zurückkehren.
        #
        # Die Top-3-Position ist nur Darstellungskontext.
        # Sie darf niemals benutzt werden, um das Objekt
        # erneut auszuwählen: Nach einem Rescore kann sich
        # die Reihenfolge geändert haben.
        # ----------------------------------------------------

        conn = sqlite3.connect(
            DB_PATH
        )

        conn.row_factory = (
            sqlite3.Row
        )

        row = conn.execute(
            """
            SELECT *
            FROM properties
            WHERE portal_id = ?
            ORDER BY last_seen DESC
            LIMIT 1
            """,
            (
                portal_id,
            )
        ).fetchone()

        conn.close()

        if not row:
            return

        p = dict(row)

        actual_property_type = (
            p.get("property_type")
            or property_type
        )

        display_number = None
        keyboard_number = "new"

        # Wenn das Objekt aus einer Top-3-Liste stammt,
        # seine AKTUELLE Position erneut bestimmen.
        # Ist es nach einem Rescore nicht mehr in den Top 3,
        # bleibt die Karte beim richtigen Objekt und verliert
        # lediglich die Rangnummer.
        if number != "new":

            rows = get_top_property_rows(
                property_type,
                3
            )

            for current_number, candidate in enumerate(
                rows,
                1
            ):

                if str(
                    candidate.get("portal_id")
                ) == str(portal_id):

                    display_number = current_number
                    keyboard_number = current_number
                    break

        telegram_api(
            "editMessageText",
            {
                "chat_id":
                    TELEGRAM_CHAT_ID,

                "message_id":
                    message["message_id"],

                "text":
                    format_property_card(
                        p,
                        display_number
                    ),

                "disable_web_page_preview":
                    "true",

                "reply_markup":
                    json.dumps(
                        property_action_keyboard(
                            p["portal_id"],
                            actual_property_type,
                            keyboard_number
                        )
                    )
            }
        )

        return

    if data.startswith("inspect:"):

        try:

            (
                _,
                portal_id,
                property_type,
                number
            ) = data.split(
                ":",
                3
            )

        except (ValueError, TypeError):
            return

        try:

            telegram_api(
                "answerCallbackQuery",
                {
                    "callback_query_id":
                        callback["id"]
                }
            )

        except Exception as exc:

            print(
                f"CALLBACK ACK ERROR: {exc}",
                flush=True
            )

        keyboard = {
            "inline_keyboard": []
        }

        # Bei Häusern Zustandsbuttons anzeigen
        if is_house_type(property_type):

            keyboard = condition_keyboard(
                portal_id,
                property_type,
                number
            )

        else:

            # Bei Grundstücken reicht Zurück
            keyboard = {
                "inline_keyboard": [
                    [
                        {
                            "text": "⬅️ Zurück",
                            "callback_data":
                                f"back:{portal_id}:{property_type}:{number}"
                        }
                    ]
                ]
            }

        telegram_api(
            "editMessageText",
            {
                "chat_id":
                    TELEGRAM_CHAT_ID,

                "message_id":
                    message["message_id"],

                "text":
                    inspect_property(
                        portal_id
                    ),

                "disable_web_page_preview":
                    "true",

                "reply_markup":
                    json.dumps(
                        keyboard
                    )
            }
        )

        return

    if data.startswith(("condition:", "c:")):

        try:

            if data.startswith("c:"):
                parts = data.split(":", 3)

                if len(parts) != 4:
                    return

                _, portal_id, condition_code, number = parts

                condition_codes = {
                    "t": "turnkey",
                    "g": "good",
                    "m": "maintained",
                    "c": "cosmetic_renovation",
                    "r": "renovation_needed",
                    "s": "major_renovation",
                    "d": "dilapidated",
                    "u": "unknown",
                }

                condition_class = condition_codes.get(
                    condition_code
                )

                if condition_class is None:
                    return

                property_type = "house"

            else:
                # Alte Buttons weiterhin unterstützen.
                parts = data.split(":", 4)

                if len(parts) == 5:
                    (
                        _,
                        portal_id,
                        condition_class,
                        property_type,
                        number
                    ) = parts

                elif len(parts) == 3:
                    (
                        _,
                        portal_id,
                        condition_class
                    ) = parts

                    property_type = "house"
                    number = "new"

                else:
                    return

        except ValueError:
            return

        try:

            telegram_api(
                "answerCallbackQuery",
                {
                    "callback_query_id":
                        callback["id"]
                }
            )

        except Exception as exc:

            print(
                f"CALLBACK ACK ERROR: {exc}",
                flush=True
            )

        result = set_house_condition(
            portal_id,
            condition_class
        )

        if number == "iwc":

            row, total = incomplete_first_condition(
                DB_PATH
            )

            set_active_condition_lab(
                message.get("message_id"),
                row,
            )

            if row is None:

                text = (
                    "✅ Zustand gespeichert.\n\n"
                    "🎉 Keine offenen Zustände mehr.\n\n"
                    + incomplete_overview_text(
                        DB_PATH
                    )
                )

                keyboard = incomplete_overview_keyboard(
                    DB_PATH
                )

            else:

                label = CONDITION_MAP.get(
                    condition_class,
                    condition_class,
                )

                text = (
                    f"✅ {label} gespeichert\n\n"
                    + incomplete_condition_text(
                        row,
                        1,
                        total,
                    )
                )

                keyboard = incomplete_condition_keyboard(
                    row
                )

            telegram_api(
                "editMessageText",
                {
                    "chat_id":
                        TELEGRAM_CHAT_ID,
                    "message_id":
                        message["message_id"],
                    "text": text,
                    "disable_web_page_preview":
                        "true",
                    "reply_markup":
                        json.dumps(
                            keyboard
                        ),
                }
            )

            return

        telegram_api(
            "editMessageText",
            {
                "chat_id":
                    TELEGRAM_CHAT_ID,

                "message_id":
                    message["message_id"],

                "text":
                    inspect_property(
                        portal_id
                    )
                    + "\n\n"
                    + result,

                "disable_web_page_preview":
                    "true"
,
                "reply_markup":
                    json.dumps(
                        condition_keyboard(
                            portal_id,
                            property_type,
                            number
                        )
                    )
            }
        )

        return

    if data.startswith("purge_confirm:"):

        try:

            _, days = data.split(
                ":",
                1
            )

            days = int(days)

        except ValueError:
            return

        try:

            telegram_api(
                "answerCallbackQuery",
                {
                    "callback_query_id":
                        callback["id"]
                }
            )

        except Exception as exc:

            print(
                f"PURGE CALLBACK ACK ERROR: {exc}",
                flush=True
            )

        try:

            deleted = execute_purge(
                days
            )

            telegram_api(
                "editMessageText",
                {
                    "chat_id":
                        TELEGRAM_CHAT_ID,

                    "message_id":
                        message["message_id"],

                    "text":
                        "🧹 Purge abgeschlossen\n\n"
                        f"{deleted} Objekt(e) gelöscht."
                }
            )

            print(
                f"PURGE: {deleted} object(s) deleted",
                flush=True
            )

        except Exception as exc:

            print(
                f"PURGE ERROR: "
                f"{type(exc).__name__}: {exc}",
                flush=True
            )

            send_message(
                "❌ Purge fehlgeschlagen\n\n"
                f"{type(exc).__name__}: {exc}"
            )

        return


    if data == "purge_cancel":

        try:

            telegram_api(
                "answerCallbackQuery",
                {
                    "callback_query_id":
                        callback["id"]
                }
            )

        except Exception as exc:

            print(
                f"PURGE CANCEL ACK ERROR: {exc}",
                flush=True
            )

        telegram_api(
            "editMessageText",
            {
                "chat_id":
                    TELEGRAM_CHAT_ID,

                "message_id":
                    message["message_id"],

                "text":
                    "❌ Purge abgebrochen."
            }
        )

        return

    if not data.startswith("build:"):
        return

    try:
        _, portal_id, buildability = (
            data.split(":", 2)
        )
    except ValueError:
        return

    # Telegram erwartet eine Bestätigung des Klicks.
    try:
        telegram_api(
            "answerCallbackQuery",
            {
                "callback_query_id":
                    callback["id"]
            }
        )
    except Exception as exc:
        print(
            f"CALLBACK ACK ERROR: {exc}",
            flush=True
        )

    result = set_buildability(
        portal_id,
        buildability
    )

    send_message(
        result
    )

def main():

    offset = None

    print(
        "Telegram command listener starting...",
        flush=True
    )

    while True:

        try:

            poll_timeout = (
                2
                if (
                    ACTIVE_ENERGY_LAB
                    or ACTIVE_CONDITION_LAB
                    or LOCALITY_LAB.session
                )
                else 30
            )

            data = {
                "timeout": poll_timeout,
                "allowed_updates":
                    json.dumps(
                        [
                             "message",
                             "callback_query"
                        ]
                    )
            }

            if offset is not None:
                data["offset"] = offset

            response = telegram_api(
                "getUpdates",
                data
            )

            for update in response.get(
                "result",
                []
            ):

                offset = (
                    update["update_id"]
                    + 1
                )

                message = update.get(
                    "message"
                )

                if message:
                    handle_message(
                        message
                    )

                callback = update.get(
                    "callback_query"
                )

                if callback:
                    handle_callback(
                        callback
                    )

            refresh_active_energy_lab()
            refresh_active_condition_lab()
            refresh_active_locality_lab()

        except Exception as exc:

            print(
                f"TELEGRAM COMMAND ERROR: "
                f"{type(exc).__name__}: {exc}",
                flush=True
            )


if __name__ == "__main__":
    main()
