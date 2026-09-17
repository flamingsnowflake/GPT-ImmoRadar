import os
import time
import ssl
import sqlite3
import hashlib
import imaplib
import email
import re
import html
import urllib.request
import urllib.parse
import json
import subprocess
from datetime import datetime, timezone
from email.header import decode_header
from email.utils import parsedate_to_datetime
from config_loader import CONFIG
from house_condition import classify_house_condition

from buildability import (
    classify_buildability as shared_classify_buildability,
)
from scoring import (
    score_land,
    score_house,
)
from property_types import (
    detect_property_type,
    is_house_type,
)
from enrichment import (
    geocode_address,
    find_nearest_water,
    find_best_water,
    find_neighbour_buildings
)
from telegram_preview import get_telegram_preview
from telegram_ui import (
    property_action_keyboard,
)
from energy_data import ENERGY_COLUMNS
from noise_sources import get_noise
from geo_precision import (
    GEO_PRECISION_EXACT,
    normalize_geo_precision,
    provisional_score_range,
)
from score_display import (
    completed_score_lines,
)
from neighbour_policy import classify_neighbours

IMAP_HOST = os.environ["IMAP_HOST"]
IMAP_PORT = int(os.environ.get("IMAP_PORT", "993"))
IMAP_USER = os.environ["IMAP_USER"]
IMAP_PASSWORD = os.environ["IMAP_PASSWORD"]
IMAP_MAILBOX = os.environ.get("IMAP_MAILBOX", "INBOX")

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

POLL_SECONDS = int(os.environ.get("POLL_SECONDS", "120"))

DB_PATH = "/data/database.sqlite3"
EMAIL_DIR = "/data/emails"

def is_spam_object(
    conn,
    portal,
    portal_id
):

    row = conn.execute(
        """
        SELECT 1
        FROM spam_objects
        WHERE portal = ?
          AND portal_id = ?
        LIMIT 1
        """,
        (
            portal,
            portal_id
        )
    ).fetchone()

    return row is not None

def is_blacklisted(*values, property_type=None):

    text = " ".join(
        str(value or "")
        for value in values
    ).lower()

    ignored_terms = set()

    # --------------------------------------------------------
    # Bei Grundstücken können Haustypen lediglich die
    # empfohlene / zulässige Bebauung beschreiben.
    #
    # Beispiel IS24 165639543:
    #   Empfohlene Nutzung:
    #   Doppelhaushälfte, Einfamilienhaus
    #
    # Das Grundstück ist deshalb natürlich keine
    # Doppelhaushälfte.
    # --------------------------------------------------------

    if property_type == "land":
        ignored_terms.add(
            "doppelhaushälfte"
        )

    # --------------------------------------------------------
    # Negierte Blacklist-Begriffe neutralisieren.
    #
    # Beispiel:
    #   "Aktuelle Nutzung: Nicht vermietet"
    #
    # Darf nicht wegen des Teilstrings "vermietet"
    # auf der Blacklist landen.
    # --------------------------------------------------------

    blacklist_text = text

    blacklist_text = re.sub(
        r"\bnicht\s+vermietet\b",
        " ",
        blacklist_text,
        flags=re.IGNORECASE,
    )

    return any(
        term in blacklist_text
        for term in CONFIG.blacklist_terms()
        if term not in ignored_terms
    )

# ------------------------------------------------------------
# Database
# ------------------------------------------------------------

def get_db():
    conn = sqlite3.connect(DB_PATH)

    # --------------------------------------------------------
    # Messages
    # --------------------------------------------------------

    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_hash TEXT UNIQUE NOT NULL,
            imap_uid TEXT,
            sender TEXT,
            subject TEXT,
            date TEXT,
            received_at TEXT NOT NULL,
            archive_path TEXT NOT NULL
        )
    """)

    # --------------------------------------------------------
    # Properties
    # --------------------------------------------------------

    conn.execute("""
        CREATE TABLE IF NOT EXISTS properties (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            portal TEXT NOT NULL,
            portal_id TEXT NOT NULL,
            title TEXT,
            url TEXT,
            location TEXT,
            price REAL,
            living_area REAL,
            rooms REAL,
            plot_area REAL,
            commission_free INTEGER,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            source_message_id INTEGER,
            UNIQUE(portal, portal_id)
        )
    """)

    # --------------------------------------------------------
    # Spam objects
    # --------------------------------------------------------

    conn.execute("""
        CREATE TABLE IF NOT EXISTS spam_objects (
            portal TEXT NOT NULL,
            portal_id TEXT NOT NULL,
            title TEXT,
            marked_at TEXT NOT NULL,
            UNIQUE(portal, portal_id)
        )
    """)

    # --------------------------------------------------------
    # Database migration:
    # Add new scoring columns to an existing database.
    # --------------------------------------------------------

    existing_columns = {
        row[1]
        for row in conn.execute(
            "PRAGMA table_info(properties)"
        )
    }

    new_columns = {
        "property_type": "TEXT",
        "raw_text": "TEXT",
        "score": "INTEGER",
        "rating": "TEXT",
        "condition_class": "TEXT",
        "condition_reason": "TEXT",
        "condition_source": "TEXT",
        "is_ko": "INTEGER DEFAULT 0",
        "score_details": "TEXT",
        "water_distance_km": "REAL",
        "water_class": "TEXT",
        "water_width_lower_m": "REAL",
        "water_width_upper_m": "REAL",
        "water_score": "INTEGER",
        "neighbour_class": "TEXT",
        "nearest_building_m": "REAL",
        "buildings_50m": "INTEGER",
        "buildings_100m": "INTEGER",
        "buildings_250m": "INTEGER",
        "buildings_500m": "INTEGER",
        "neighbour_checked_at": "TEXT",
        "buildability": "TEXT",
        "buildability_class": "TEXT",
        "buildability_reason": "TEXT",
        "primary_residence": "TEXT",
        "residential_building_allowed": "INTEGER",
        "holiday_area": "INTEGER",
        "severe_noise": "INTEGER",
        "latitude": "REAL",
        "longitude": "REAL",
        "geocode_query": "TEXT",
        "geocoded_at": "TEXT",
        "geocode_source_location": "TEXT",
        "geo_precision": "TEXT",
        "rail_lden": "REAL",
        "rail_lnight": "REAL",
        "rail_distance_m": "REAL",
        "rail_annual_traffic": "INTEGER",
        "road_lden": "REAL",
        "road_lnight": "REAL",
        "road_noise_source": "TEXT",
        "air_lden": "REAL",
        "air_lnight": "REAL",
        "air_noise_source": "TEXT",
        "noise_checked_at": "TEXT",
        "manual_latitude": "REAL",
        "manual_longitude": "REAL",
        "manual_coordinates_set_at": "TEXT",
        "manual_coordinates_source": "TEXT"
   }

    new_columns.update(
        ENERGY_COLUMNS
    )

    for column, definition in new_columns.items():
        if column not in existing_columns:
            print(
                f"Adding database column: {column}",
                flush=True
            )

            conn.execute(
                f"""
                ALTER TABLE properties
                ADD COLUMN {column} {definition}
                """
            )

    # --------------------------------------------------------
    # Search -> Property relationship
    # --------------------------------------------------------

    conn.execute("""
        CREATE TABLE IF NOT EXISTS property_searches (
            property_id INTEGER NOT NULL,
            search_id TEXT NOT NULL,
            first_seen TEXT NOT NULL,
            UNIQUE(property_id, search_id)
        )
    """)

    conn.commit()
    return conn

# ------------------------------------------------------------
# Text helpers
# ------------------------------------------------------------

def decode_text(value):
    if not value:
        return ""

    result = ""

    for part, encoding in decode_header(value):
        if isinstance(part, bytes):
            result += part.decode(
                encoding or "utf-8",
                errors="replace"
            )
        else:
            result += part

    return result.strip()


def clean_text(value):
    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def number_from_german(value):
    if not value:
        return None

    value = value.replace("\xa0", " ")
    value = value.replace("€", "")
    value = value.strip()

    # 2.819,01 -> 2819.01
    value = value.replace(".", "")
    value = value.replace(",", ".")

    match = re.search(r"\d+(?:\.\d+)?", value)

    if not match:
        return None

    try:
        return float(match.group())
    except ValueError:
        return None


# ------------------------------------------------------------
# Email body extraction
# ------------------------------------------------------------

def normalize_multiline(text):

    text = html.unescape(text)

    text = text.replace(
        "\r\n",
        "\n"
    ).replace(
        "\r",
        "\n"
    )

    lines = []

    for line in text.split("\n"):

        line = re.sub(
            r"[ \t]+",
            " ",
            line
        ).strip()

        lines.append(line)

    return "\n".join(lines)


def get_email_text(message):

    plain_parts = []
    html_parts = []

    if message.is_multipart():

        for part in message.walk():

            content_type = part.get_content_type()

            disposition = str(
                part.get(
                    "Content-Disposition",
                    ""
                )
            )

            if "attachment" in disposition.lower():
                continue

            try:

                payload = part.get_payload(
                    decode=True
                )

                if not payload:
                    continue

                charset = (
                    part.get_content_charset()
                    or "utf-8"
                )

                text = payload.decode(
                    charset,
                    errors="replace"
                )

            except Exception:
                continue

            if content_type == "text/plain":
                plain_parts.append(text)

            elif content_type == "text/html":
                html_parts.append(text)

    else:

        payload = message.get_payload(
            decode=True
        )

        if payload:

            charset = (
                message.get_content_charset()
                or "utf-8"
            )

            text = payload.decode(
                charset,
                errors="replace"
            )

            if message.get_content_type() == "text/html":
                html_parts.append(text)

            else:
                plain_parts.append(text)

    # Plaintext bevorzugen
    if plain_parts:

        return normalize_multiline(
            "\n".join(plain_parts)
        )

    # HTML-Fallback
    html_text = "\n".join(
        html_parts
    )

    html_text = re.sub(
        r"<br\s*/?>",
        "\n",
        html_text,
        flags=re.I
    )

    html_text = re.sub(
        r"</(?:p|div|tr|td)>",
        "\n",
        html_text,
        flags=re.I
    )

    html_text = re.sub(
        r"<[^>]+>",
        " ",
        html_text
    )

    return normalize_multiline(
        html_text
    )


# ------------------------------------------------------------
# parse HTML mails, too
# ------------------------------------------------------------

def get_email_html(message):

    html_parts = []

    if message.is_multipart():

        for part in message.walk():

            if part.get_content_type() != "text/html":
                continue

            disposition = str(
                part.get(
                    "Content-Disposition",
                    ""
                )
            )

            if "attachment" in disposition.lower():
                continue

            try:

                payload = part.get_payload(
                    decode=True
                )

                if not payload:
                    continue

                charset = (
                    part.get_content_charset()
                    or "utf-8"
                )

                html_parts.append(
                    payload.decode(
                        charset,
                        errors="replace"
                    )
                )

            except Exception:
                continue

    elif message.get_content_type() == "text/html":

        payload = message.get_payload(
            decode=True
        )

        if payload:

            charset = (
                message.get_content_charset()
                or "utf-8"
            )

            html_parts.append(
                payload.decode(
                    charset,
                    errors="replace"
                )
            )

    return "\n".join(html_parts)



def get_immoscout_html_block(html_text, portal_id):

    if not html_text or not portal_id:
        return ""

    marker = f"/expose/{portal_id}"

    start = html_text.find(marker)

    if start < 0:
        return ""

    # Etwas vor dem Link mitnehmen
    start = max(
        0,
        start - 2000
    )

    # Bis zum nächsten Scout-Expose
    next_match = re.search(
        r"/expose/\d+",
        html_text[start + 2000:]
    )

    if next_match:

        end = (
            start
            + 2000
            + next_match.start()
        )

    else:

        # Anbieter liegt bei Scout einige KB
        # hinter dem Expose-Link.
        end = min(
            len(html_text),
            start + 12000
        )

    return html_text[start:end]


def get_email_html(message):

    html_parts = []

    if message.is_multipart():

        for part in message.walk():

            if part.get_content_type() != "text/html":
                continue

            disposition = str(
                part.get("Content-Disposition", "")
            )

            if "attachment" in disposition.lower():
                continue

            try:

                payload = part.get_payload(
                    decode=True
                )

                if not payload:
                    continue

                charset = (
                    part.get_content_charset()
                    or "utf-8"
                )

                html_parts.append(
                    payload.decode(
                        charset,
                        errors="replace"
                    )
                )

            except Exception:
                continue

    elif message.get_content_type() == "text/html":

        payload = message.get_payload(
            decode=True
        )

        if payload:

            charset = (
                message.get_content_charset()
                or "utf-8"
            )

            html_parts.append(
                payload.decode(
                    charset,
                    errors="replace"
                )
            )

    return "\n".join(
        html_parts
    )


def get_immoscout_html_block(
    html_text,
    portal_id
):

    if not html_text or not portal_id:
        return ""

    matches = list(
        re.finditer(
            r"/(?:email/)?expose/(\d+)",
            html_text,
            re.I
        )
    )

    for index, match in enumerate(matches):

        if match.group(1) != str(portal_id):
            continue

        start = max(
            0,
            match.start() - 1000
        )

        end = min(
            len(html_text),
            match.end() + 15000
        )

        # Bis zum nächsten ANDEREN Objekt.
        # Weitere Links zur gleichen Expose-ID
        # gehören weiterhin zu diesem Objekt.
        for later in matches[index + 1:]:

            if later.group(1) != str(portal_id):
                end = later.start()
                break

        return html_text[start:end]

    return ""

# ------------------------------------------------------------
# ImmoScout24 parser
# ------------------------------------------------------------

def parse_immoscout(text):

    lines = text.splitlines()

    url_pattern = re.compile(
        r"https?://push\.search\.is24\.de/"
        r"email/expose/(\d+)[^\s<>\)]*",
        re.I
    )

    # ========================================================
    # Helper
    # ========================================================

    def extract_search_id(url):

        match = re.search(
            r"savedSearchId=(\d+)",
            url or ""
        )

        return (
            match.group(1)
            if match
            else None
        )


    def extract_url(block_lines):

        for candidate in block_lines:

            match = url_pattern.search(
                candidate
            )

            if match:

                return (
                    match.group(0)
                    .rstrip(".,);>")
                )

        return None


    def parse_classic_block(block_lines):

        block = "\n".join(
            block_lines
        )

        url = extract_url(
            block_lines
        )

        if not url:
            return None

        id_match = url_pattern.search(
            url
        )

        if not id_match:
            return None

        portal_id = id_match.group(1)

        search_id = extract_search_id(
            url
        )

        title = ""
        location = ""
        price = None
        plot_area = None
        living_area = None
        rooms = None
        buildability = None
        property_type = "unknown"

        for candidate in block_lines:

            stripped = candidate.strip()

            # ----------------------------
            # Title
            # ----------------------------

            if stripped.lower().startswith(
                "titel:"
            ):

                title = clean_text(
                    stripped.split(
                        ":",
                        1
                    )[1]
                )

                continue

            # ----------------------------
            # Address
            # ----------------------------

            if stripped.lower().startswith(
                "adresse:"
            ):

                location = clean_text(
                    stripped.split(
                        ":",
                        1
                    )[1]
                )

                continue

            # ----------------------------
            #  Bebaubarkeit
            # ----------------------------

            if stripped.lower().startswith(
                "bebaubar nach:"
            ):

                buildability = clean_text(
                    stripped.split(
                        ":",
                        1
                    )[1]
                )

                continue

            # ----------------------------
            # Price
            # ----------------------------

            match = re.search(
                r"Kaufpreis:\s*"
                r"([\d\.,]+)\s*€",
                stripped,
                re.I
            )

            if match:

                price = number_from_german(
                    match.group(1)
                )

                continue

            # ----------------------------
            # Plot
            # ----------------------------

            match = re.search(
                r"(?:Grundstücksfläche|Grundstück):"
                r"\s*([\d\.,]+)\s*m²",
                stripped,
                re.I
            )

            if match:

                plot_area = number_from_german(
                    match.group(1)
                )

                if property_type == "unknown":
                    property_type = "land"

                continue

            # ----------------------------
            # Living area
            # ----------------------------

            match = re.search(
                r"Wohnfläche:\s*"
                r"([\d\.,]+)\s*m²",
                stripped,
                re.I
            )

            if match:

                living_area = number_from_german(
                    match.group(1)
                )

                continue

            # ----------------------------
            # Rooms
            # ----------------------------

            match = re.search(
                r"Zimmer:\s*([\d\.,]+)",
                stripped,
                re.I
            )

            if match:

                rooms = number_from_german(
                    match.group(1)
                )

        commission_free = bool(
            re.search(
                r"provisionsfrei",
                block,
                re.I
            )
        )

        return {
            "portal": "immoscout24",
            "portal_id": portal_id,
            "title": title,
            "url": url,
            "location": location,
            "price": price,
            "living_area": living_area,
            "rooms": rooms,
            "plot_area": plot_area,
            "commission_free": commission_free,
            "search_id": search_id,
            "buildability": buildability,
            "raw_text": block
        }


    def parse_compact():

        properties = []

        anchors = []

        for line_index, line in enumerate(
            lines
        ):

            match = url_pattern.search(
                line
            )

            if not match:
                continue

            anchors.append({
                "line_index": line_index,
                "portal_id": match.group(1),
                "url": (
                    match.group(0)
                    .rstrip(".,);>")
                )
            })

        if not anchors:
            return properties

        # Same ID may appear twice directly after each other
        # in one compact mail.
        groups = []

        for anchor in anchors:

            if (
                groups
                and groups[-1]["portal_id"]
                == anchor["portal_id"]
                and anchor["line_index"]
                <= groups[-1]["last_line"] + 4
            ):

                groups[-1]["anchors"].append(
                    anchor
                )

                groups[-1]["last_line"] = (
                    anchor["line_index"]
                )

            else:

                groups.append({
                    "portal_id":
                        anchor["portal_id"],

                    "anchors": [
                        anchor
                    ],

                    "first_line":
                        anchor["line_index"],

                    "last_line":
                        anchor["line_index"]
                })

        seen_ids = set()

        for group_index, group in enumerate(
            groups
        ):

            portal_id = group[
                "portal_id"
            ]

            if portal_id in seen_ids:
                continue

            seen_ids.add(
                portal_id
            )

            first_line = group[
                "first_line"
            ]

            last_line = group[
                "last_line"
            ]

            # --------------------------------------------
            # Compact object boundaries
            # --------------------------------------------

            if group_index == 0:

                block_start = max(
                    0,
                    first_line - 3
                )

            else:

                block_start = (
                    groups[
                        group_index - 1
                    ]["last_line"] + 1
                )

            if (
                group_index + 1
                < len(groups)
            ):

                block_end = groups[
                    group_index + 1
                ]["first_line"]

            else:

                block_end = min(
                    len(lines),
                    last_line + 15
                )

            block_lines = lines[
                block_start:block_end
            ]

            block = "\n".join(
                block_lines
            )

            url = group[
                "anchors"
            ][0]["url"]

            search_id = extract_search_id(
                url
            )

            # --------------------------------------------
            # Title
            # --------------------------------------------

            title = ""

            for anchor in group[
                "anchors"
            ]:

                candidate = lines[
                    anchor["line_index"]
                ]

                candidate_title = (
                    url_pattern.sub(
                        "",
                        candidate
                    )
                )

                candidate_title = (
                    candidate_title
                    .replace("()", "")
                    .rstrip(" (")
                    .strip()
                )

                candidate_title = re.sub(
                    r"^Link:\s*",
                    "",
                    candidate_title,
                    flags=re.I
                )

                if candidate_title:

                    title = clean_text(
                        candidate_title
                    )

                    break

            # --------------------------------------------
            # Price
            # --------------------------------------------

            price = None

            for candidate in block_lines:

                stripped = (
                    candidate.strip()
                )

                match = re.fullmatch(
                    r"([\d\.,]+)\s*€",
                    stripped
                )

                if match:

                    price = number_from_german(
                        match.group(1)
                    )

                    break

            # --------------------------------------------
            # Plot
            # --------------------------------------------

            plot_area = None

            if search_id in (
                "201749106",
                "201749120"
            ):

                for candidate in block_lines:

                    stripped = (
                        candidate.strip()
                    )

                    match = re.fullmatch(
                        r"([\d\.,]+)\s*m²",
                        stripped
                    )

                    if match:

                        plot_area = (
                            number_from_german(
                                match.group(1)
                            )
                        )

                        break

            # --------------------------------------------
            # Living area
            # --------------------------------------------

            living_area = None

            for candidate in block_lines:

                match = re.search(
                    r"Wohnfläche:\s*"
                    r"([\d\.,]+)\s*m²",
                    candidate,
                    re.I
                )

                if match:

                    living_area = (
                        number_from_german(
                            match.group(1)
                        )
                    )

                    break

            # --------------------------------------------
            # Rooms
            # --------------------------------------------

            rooms = None

            for candidate in block_lines:

                match = re.search(
                    r"Zimmer:\s*"
                    r"([\d\.,]+)",
                    candidate,
                    re.I
                )

                if match:

                    rooms = (
                        number_from_german(
                            match.group(1)
                        )
                    )

                    break

            # --------------------------------------------
            # Location
            # --------------------------------------------

            location = ""

            area_seen = False

            for candidate in block_lines:

                stripped = (
                    candidate.strip()
                )

                if not stripped:
                    continue

                # Explicit address, if present
                if stripped.lower().startswith(
                    "adresse:"
                ):

                    location = clean_text(
                        stripped.split(
                            ":",
                            1
                        )[1]
                    )

                    break

                # Ignore price
                if re.fullmatch(
                    r"[\d\.,]+\s*€",
                    stripped
                ):
                    continue

                # After area comes address in compact format
                if re.fullmatch(
                    r"[\d\.,]+\s*m²",
                    stripped
                ):

                    area_seen = True
                    continue

                if not area_seen:
                    continue

                lower = (
                    stripped.lower()
                )

                if (
                    "http://" in lower
                    or "https://" in lower
                    or "alle angebote" in lower
                    or "gespeicherte suche" in lower
                    or "suchauftrag" in lower
                    or "passe deine" in lower
                ):
                    continue

                # Address/location lines normally contain
                # at least one comma.
                if "," in stripped:

                    location = clean_text(
                        stripped
                    )

                    break

            commission_free = bool(
                re.search(
                    r"provisionsfrei",
                    block,
                    re.I
                )
            )

            properties.append({
                "portal":
                    "immoscout24",

                "portal_id":
                    portal_id,

                "title":
                    title,

                "url":
                    url,

                "location":
                    location,

                "price":
                    price,

                "living_area":
                    living_area,

                "rooms":
                    rooms,

                "plot_area":
                    plot_area,

                "commission_free":
                    commission_free,

                "search_id":
                    search_id,

                "raw_text":
                    block
            })

        return properties


    # ========================================================
    # CLASSIC FORMAT
    #
    # Every property begins with:
    #
    # Titel: ...
    #
    # ========================================================

    title_indexes = []

    for index, line in enumerate(
        lines
    ):

        if line.strip().lower().startswith(
            "titel:"
        ):

            title_indexes.append(
                index
            )

    if title_indexes:

        properties = []

        for position, start in enumerate(
            title_indexes
        ):

            if (
                position + 1
                < len(title_indexes)
            ):

                end = title_indexes[
                    position + 1
                ]

            else:

                end = len(lines)

            block_lines = lines[
                start:end
            ]

            property_data = (
                parse_classic_block(
                    block_lines
                )
            )

            if property_data:

                properties.append(
                    property_data
                )

        return properties

    # ========================================================
    # COMPACT FORMAT FALLBACK
    # ========================================================

    return parse_compact()



# ------------------------------------------------------------
# IMMOWELT PARSER
# ------------------------------------------------------------

def parse_immowelt(text):

    properties = []

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    tracking_pattern = re.compile(
        r"https://click\.by\.immowelt\.de/\?qs=[^\s)]+",
        re.I
    )

    for index, line in enumerate(lines):

        if not line.lower().startswith(
            "mehr informationen"
        ):
            continue

        # Der Immowelt-Tracking-Link steht in den
        # aktuellen Mails in der Zeile VOR
        # "Mehr Informationen".
        tracking_match = None

        for previous_index in range(
            index - 1,
            max(-1, index - 5),
            -1
        ):
            tracking_match = tracking_pattern.search(
                lines[previous_index]
            )

            if tracking_match:
                break

        if not tracking_match:
            print(
                "IMMOWELT: no tracking link before "
                "'Mehr Informationen'",
                flush=True
            )
            continue

        tracking_url = tracking_match.group(0)

        # Eine Immowelt-Mail kann mehrere Angebote enthalten.
        #
        # Der vorige "Mehr Informationen"-Marker trennt
        # die einzelnen Angebotskarten voneinander.
        # Dadurch dürfen Daten eines vorherigen Objekts
        # nicht in den aktuellen Block geraten.
        previous_marker = None

        for previous_index in range(
            index - 1,
            -1,
            -1
        ):

            if lines[
                previous_index
            ].lower().startswith(
                "mehr informationen"
            ):
                previous_marker = previous_index
                break

        block_start = (
            previous_marker + 1
            if previous_marker is not None
            else 0
        )

        block_lines = lines[
            block_start:index + 1
        ]

        # --------------------------------------------
        # Immowelt Tracking-Link auflösen
        # --------------------------------------------

        final_url = None

        try:

            result = subprocess.run(
                [
                    "curl",
                    "-sS",
                    "-L",
                    "--max-time",
                    "20",
                    "-o",
                    "/dev/null",
                    "-w",
                    "%{url_effective}",
                    tracking_url,
                ],
                capture_output=True,
                text=True,
                timeout=25,
            )

            if result.returncode != 0:

                raise RuntimeError(
                    result.stderr.strip()
                    or f"curl exit {result.returncode}"
                )

            final_url = result.stdout.strip()

            if not final_url:

                raise RuntimeError(
                    "empty redirect URL"
                )

            print(
                f"IMMOWELT REDIRECT: {final_url}",
                flush=True
            )

        except Exception as exc:

            print(
                f"IMMOWELT REDIRECT ERROR: "
                f"{type(exc).__name__}: {exc}",
                flush=True
            )

            continue
        # --------------------------------------------
        # Portal-ID aus Ziel-URL
        # --------------------------------------------

        expose_match = re.search(
            r"/expose/"
            r"([0-9a-fA-F-]{36})",
            final_url
        )

        if not expose_match:

            print(
                f"IMMOWELT: no expose ID | "
                f"{final_url}",
                flush=True
            )

            continue

        portal_id = (
            expose_match
            .group(1)
            .lower()
        )

        canonical_url = (
            "https://www.immowelt.de/"
            f"expose/{portal_id}"
        )

        # --------------------------------------------
        # Preis
        # --------------------------------------------

        price = None

        for candidate in block_lines:

            match = re.match(
                r"^([\d\.\,]+)\s*€",
                candidate
            )

            if match:

                price = number_from_german(
                    match.group(1)
                )

                break

        # --------------------------------------------
        # Zimmer / Wohnfläche / Grundstück
        # --------------------------------------------

        rooms = None
        living_area = None
        plot_area = None
        property_type = "unknown"

        for candidate in block_lines:

            # Haus:
            # 4 Zimmer · 75 m² · 915 m²

            match = re.match(
                r"^([\d\.,]+)\s+Zimmer"
                r"\s*[·.]\s*"
                r"([\d\.,]+)\s*m²"
                r"\s*[·.]\s*"
                r"([\d\.,]+)\s*m²",
                candidate,
                re.I
            )

            if match:

                rooms = number_from_german(
                    match.group(1)
                )

                living_area = number_from_german(
                    match.group(2)
                )

                plot_area = number_from_german(
                    match.group(3)
                )

                property_type = "house"

                break

            # Grundstück:
            # 722 m²

            match = re.fullmatch(
                r"([\d\.,]+)\s*m²"
                r"(?:\s*\([^)]*\))?",
                candidate
            )

            if match:

                plot_area = number_from_german(
                    match.group(1)
                )

        # --------------------------------------------
        # Ort
        # --------------------------------------------
        location = ""

        # Aktuelle Immowelt-Mails liefern z.B.:
        #
        # Gröbzig,
        # Südliches Anhalt
        # (06388)
        #
        # also PLZ und Ortsangaben auf getrennten Zeilen.

        for pos, candidate in enumerate(block_lines):

            zip_match = re.fullmatch(
                r"\((\d{5})\)",
                candidate.strip()
            )

            if not zip_match:
                continue

            postal_code = zip_match.group(1)

            previous = []

            for prev in reversed(block_lines[:pos]):

                prev = tracking_pattern.sub(
                    "",
                    prev
                ).strip().rstrip(",")

                if not prev:
                    continue

                previous.append(prev)

                if len(previous) == 2:
                    break

            if len(previous) >= 2:

                city = previous[1]
                municipality = previous[0]

                location = (
                    f"{city}, {municipality} "
                    f"({postal_code})"
                )

            elif previous:

                location = (
                    f"{previous[0]} "
                    f"({postal_code})"
                )

            break
        # --------------------------------------------
        # Titel
        # --------------------------------------------

        title = ""

        # Immowelt-Aufbau:
        # Preis
        # Tracking-Link
        # Titel
        # Tracking-Link
        # Eckdaten

        price_index = None

        for pos, candidate in enumerate(block_lines):

            if re.match(
                r"^[\d\.\,]+\s*€",
                candidate
            ):
                price_index = pos
                break

        if price_index is not None:

            for candidate in block_lines[
                price_index + 1:
            ]:

                if tracking_pattern.fullmatch(
                    candidate
                ):
                    continue

                if not candidate:
                    continue

                # Eckdaten nicht als Titel verwenden
                if re.match(
                    r"^[\d\.,]+\s+zimmer",
                    candidate,
                    re.I
                ):
                    continue

                if re.fullmatch(
                    r"[\d\.,]+\s*m²"
                    r"(?:\s*\([^)]*\))?",
                    candidate
                ):
                    continue

                title = clean_text(
                    candidate
                )

                break

        if not title:
            title = "Immowelt Angebot"

        properties.append({
            "portal": "immowelt",
            "portal_id": portal_id,
            "title": title,
            "url": canonical_url,
            "location": location,
            "price": price,
            "living_area": living_area,
            "rooms": rooms,
            "plot_area": plot_area,
            "property_type": property_type,
            "commission_free": False,
            "search_id": None,
            "raw_text": "\n".join(
                block_lines
            )
        })

    return properties

# ------------------------------------------------------------
# Telegram
# ------------------------------------------------------------

def telegram(message, reply_markup=None):

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": "false"
    }

    if reply_markup is not None:
        payload["reply_markup"] = json.dumps(
            reply_markup
        )

    data = urllib.parse.urlencode(
        payload
    ).encode()

    request = urllib.request.Request(
        url,
        data=data
    )

    with urllib.request.urlopen(
        request,
        timeout=30
    ) as response:

        return response.read()

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

def format_property(p, duplicate=False):

    lines = []

    if duplicate:
        lines.append("🔁 BEKANNTES OBJEKT – weiterer Suchauftrag")
    else:
        lines.append("🏠 NEUES OBJEKT")

    lines.append("")

    if p["title"]:
        lines.append(f"**{p['title']}**")

    if p["location"]:
        lines.append(f"📍 {p['location']}")

    if p["price"] is not None:
        lines.append(
            f"💰 {p['price']:,.0f} €".replace(",", ".")
        )

    if p["plot_area"] is not None:
        lines.append(
            f"🌳 Grundstück: "
            f"{p['plot_area']:,.0f} m²".replace(",", ".")
        )

    if p["living_area"] is not None:
        lines.append(
            f"🏡 Wohnfläche: "
            f"{p['living_area']:,.0f} m²".replace(",", ".")
        )

    if p["rooms"] is not None:
        lines.append(
            f"🚪 Zimmer: "
            f"{p['rooms']:g}"
        )

    if p["commission_free"]:
        lines.append("✅ provisionsfrei")

    # --------------------------------------------------------
    # Bewertung
    # --------------------------------------------------------

    score_details = (
        p.get(
            "score_details"
        )
        or {}
    )

    if isinstance(
        score_details,
        str
    ):

        try:

            score_details = json.loads(
                score_details
            )

        except Exception:

            score_details = {}

    if not isinstance(
        score_details,
        dict
    ):
        score_details = {}

    if p.get("is_ko"):

        lines.append("")
        lines.append(
            "⛔ KO"
        )

    elif p.get("rating") == "incomplete":

        lines.append("")
        lines.append(
            "⏳ Bewertung unvollständig"
        )

        missing = score_details.get(
            "incomplete_reasons"
        )

        if isinstance(
            missing,
            list
        ) and missing:

            lines.append(
                "Fehlt: "
                + ", ".join(
                    str(value)
                    for value in missing
                )
            )

    elif p.get("rating") == "provisional":

        score_range = provisional_score_range(
            p
        )

        lines.append("")

        if score_range is not None:
            lines.append(
                "⭐ "
                f"{score_range[0]}–{score_range[1]} Punkte"
                " | 📍 Lage nur auf Ortsebene bekannt"
            )
        else:
            lines.append(
                "⭐ Vorläufige Bewertung"
            )

            lines.append(
                "📍 Lage nur auf Ortsebene bekannt"
            )

    elif p.get("score") is not None:

        lines.append("")

        lines.extend(
            completed_score_lines(p)
        )

        if p.get("rating"):

            lines.append(
                f"📊 Rating: {p['rating']}"
            )

    elif p.get("rating"):

        lines.append("")

        lines.append(
            f"📊 Rating: {p['rating']}"
        )

    lines.append("")
    lines.append(f"🔗 {p['url']}")

    return "\n".join(lines)

#
# geo enrichment
#
def load_existing_enrichment(conn, property_data):

    existing = conn.execute(
        """
        SELECT
            latitude,
            longitude,
            geocode_query,
            geocode_source_location,
            geocoded_at,
            water_distance_km,
            water_class,
            water_width_lower_m,
            water_width_upper_m,
            water_score,
            neighbour_class,
            nearest_building_m,
            buildings_50m,
            buildings_100m,
            buildings_250m,
            buildings_500m,
            neighbour_checked_at,
            primary_residence,
            residential_building_allowed,
            holiday_area,
            severe_noise,
            manual_latitude,
            manual_longitude,
            manual_coordinates_set_at,
            manual_coordinates_source,
            rail_lden,
            rail_lnight,
            rail_distance_m,
            rail_annual_traffic,
            road_lden,
            road_lnight,
            road_noise_source,
            air_lden,
            air_lnight,
            air_noise_source,
            noise_checked_at
        FROM properties
        WHERE portal = ?
          AND portal_id = ?
        """,
        (
            property_data["portal"],
            property_data["portal_id"]
        )
    ).fetchone()

    if not existing:
        return property_data

    (
        latitude,
        longitude,
        geocode_query,
        geocode_source_location,
        geocoded_at,
        water_distance_km,
        water_class,
        water_width_lower_m,
        water_width_upper_m,
        water_score,
        neighbour_class,
        nearest_building_m,
        buildings_50m,
        buildings_100m,
        buildings_250m,
        buildings_500m,
        neighbour_checked_at,
        primary_residence,
        residential_building_allowed,
        holiday_area,
        severe_noise,
        manual_latitude,
        manual_longitude,
        manual_coordinates_set_at,
        manual_coordinates_source,
        rail_lden,
        rail_lnight,
        rail_distance_m,
        rail_annual_traffic,
        road_lden,
        road_lnight,
        road_noise_source,
        air_lden,
        air_lnight,
        air_noise_source,
        noise_checked_at
    ) = existing

    current_location = (
        property_data.get("location") or ""
    ).strip()

    cached_location = (
        geocode_source_location or ""
    ).strip()

    # --------------------------------------------------------
    # Manuelle Koordinaten sind ein permanenter Override.
    #
    # Priorität:
    #
    #   MANUELL > gespeicherter Geo-Cache > Geocoding
    #
    # Eine Änderung der Inserats-Location darf manuelle
    # Koordinaten niemals ungültig machen.
    # --------------------------------------------------------

    manual_override = (
        manual_latitude is not None
        and manual_longitude is not None
    )

    if manual_override:

        latitude = manual_latitude
        longitude = manual_longitude

        geocode_query = "MANUAL"

        geocode_source_location = (
            current_location
            or cached_location
            or "MANUAL"
        )

        if manual_coordinates_set_at:
            geocoded_at = manual_coordinates_set_at

        property_data["manual_latitude"] = (
            manual_latitude
        )

        property_data["manual_longitude"] = (
            manual_longitude
        )

        property_data["manual_coordinates_set_at"] = (
            manual_coordinates_set_at
        )

        property_data["manual_coordinates_source"] = (
            manual_coordinates_source
        )

    # Automatische Geodaten nur wiederverwenden, wenn sie
    # tatsächlich für dieselbe Inseratsadresse erzeugt wurden.
    #
    # Bei MANUAL ist diese Prüfung absichtlich irrelevant.
    geo_cache_valid = (
        manual_override
        or (
            current_location
            and cached_location
            and current_location == cached_location
        )
    )

    if geo_cache_valid:

        if latitude is not None:
            property_data["latitude"] = latitude

        if longitude is not None:
            property_data["longitude"] = longitude

        if geocode_query is not None:
            property_data["geocode_query"] = geocode_query

        property_data["geocode_source_location"] = (
            geocode_source_location
        )

        if geocoded_at is not None:
            property_data["geocoded_at"] = geocoded_at

        if water_distance_km is not None:
            property_data["water_distance_km"] = (
                water_distance_km
         )

        if water_class is not None:
            property_data["water_class"] = (
                water_class
            )

        if water_width_lower_m is not None:
            property_data["water_width_lower_m"] = (
                water_width_lower_m
            )

        if water_width_upper_m is not None:
            property_data["water_width_upper_m"] = (
                water_width_upper_m
            )

        if water_score is not None:
            property_data["water_score"] = (
                water_score
            )

        # Gebäudedaten hängen ebenfalls von
        # den gecachten Koordinaten ab.

        if neighbour_class is not None:
            property_data["neighbour_class"] = (
                neighbour_class
            )

        if nearest_building_m is not None:
            property_data["nearest_building_m"] = (
                nearest_building_m
            )

        if buildings_50m is not None:
            property_data["buildings_50m"] = (
                buildings_50m
            )

        if buildings_100m is not None:
            property_data["buildings_100m"] = (
                buildings_100m
            )

        if buildings_250m is not None:
            property_data["buildings_250m"] = (
                buildings_250m
            )

        if buildings_500m is not None:
            property_data["buildings_500m"] = (
                buildings_500m
            )

        if neighbour_checked_at is not None:
            property_data["neighbour_checked_at"] = (
                neighbour_checked_at
            )

        # Lärmdaten hängen ebenfalls von den Koordinaten ab.
        #
        # noise_checked_at ist dabei das Cache-Kennzeichen.
        # Die einzelnen Pegel dürfen absichtlich None sein:
        # das bedeutet "unter Kartierungsgrenze".
        if noise_checked_at is not None:

            property_data["rail_lden"] = rail_lden
            property_data["rail_lnight"] = rail_lnight

            property_data["rail_distance_m"] = (
                rail_distance_m
            )

            property_data["rail_annual_traffic"] = (
                rail_annual_traffic
            )

            property_data["road_lden"] = road_lden
            property_data["road_lnight"] = road_lnight

            property_data["road_noise_source"] = (
                road_noise_source
            )

            property_data["air_lden"] = air_lden
            property_data["air_lnight"] = air_lnight

            property_data["air_noise_source"] = (
                air_noise_source
            )

            property_data["noise_checked_at"] = (
                noise_checked_at
            )

    elif latitude is not None or longitude is not None:

        print(
            f"GEO CACHE INVALIDATED: "
            f"{property_data.get('portal_id')} | "
            f"cached='{cached_location}' | "
            f"current='{current_location}'",
            flush=True
        )

    # --------------------------------------------------------
    # Diese Werte hängen NICHT von den Koordinaten ab
    # --------------------------------------------------------

    if primary_residence is not None:
        property_data["primary_residence"] = primary_residence

    if residential_building_allowed is not None:
        property_data["residential_building_allowed"] = (
            bool(residential_building_allowed)
        )

    if holiday_area is not None:
        property_data["holiday_area"] = bool(holiday_area)

    if severe_noise is not None:
        property_data["severe_noise"] = bool(severe_noise)

    return property_data

def classify_buildability(property_data):

    return shared_classify_buildability(
        property_data
    )

def _geocode_location_with_fallback(
    location,
):

    location = str(
        location or ""
    ).strip()

    if not location:
        return None

    queries = []

    def add_query(value):

        value = str(
            value or ""
        ).strip()

        if (
            value
            and value not in queries
        ):
            queries.append(
                value
            )

    # --------------------------------------------------------
    # 1. Original immer zuerst.
    # --------------------------------------------------------

    add_query(
        location
    )

    # --------------------------------------------------------
    # Bundesland hinter Gedankenstrich entfernen.
    #
    # Beispiel:
    #
    # ... Hecklingen (...) – Sachsen-Anhalt
    # --------------------------------------------------------

    compact = re.sub(
        r"\s+[–—]\s+[^,]+$",
        "",
        location,
    ).strip()

    # --------------------------------------------------------
    # Deutsche Adresse mit PLZ erkennen.
    #
    # Beispiel:
    #
    # Obere Kirchstr 18,
    # Rüsternberg,
    # 39444 Hecklingen (Groß Börnecke)
    #
    # Daraus bevorzugt:
    #
    # Obere Kirchstr 18, 39444 Groß Börnecke
    #
    # danach:
    #
    # Obere Kirchstr 18, 39444 Hecklingen
    # --------------------------------------------------------

    match = re.match(
        r"^(?P<street>[^,]+),"
        r".*?"
        r"\b(?P<postal>\d{5})\s+"
        r"(?P<town>[^,(–—]+?)"
        r"(?:\s*\((?P<district>[^)]+)\))?"
        r"\s*$",
        compact,
        re.I,
    )

    if match:

        street = (
            match.group("street")
            or ""
        ).strip()

        postal = (
            match.group("postal")
            or ""
        ).strip()

        town = (
            match.group("town")
            or ""
        ).strip()

        district = (
            match.group("district")
            or ""
        ).strip()

        # Ortsteil zuerst, weil er bei solchen
        # Eingemeindungen die präzisere Angabe ist.
        if (
            street
            and postal
            and district
        ):

            add_query(
                f"{street}, "
                f"{postal} {district}"
            )

        if (
            street
            and postal
            and town
        ):

            add_query(
                f"{street}, "
                f"{postal} {town}"
            )

    # Variante ohne Bundesland ebenfalls versuchen.
    add_query(
        compact
    )

    # --------------------------------------------------------
    # Bewusst KEIN Fallback nur auf PLZ/Ort.
    #
    # Das wäre für Wasser-, Nachbarschafts- und
    # Lärmbewertung zu ungenau.
    # --------------------------------------------------------

    for query in queries:

        geo = geocode_address(
            query
        )

        if not geo:
            continue

        if query != location:

            print(
                "GEO FALLBACK: "
                f"{location} "
                "-> "
                f"{query}",
                flush=True,
            )

        return geo

    return None


def enrich_property(conn, property_data):

    property_data["_geo_errors"] = {}

    # --------------------------------------------------------
    # Existing enrichment data from SQLite
    # --------------------------------------------------------

    property_data = load_existing_enrichment(
        conn,
        property_data
    )

    property_data = normalize_geo_precision(
        property_data
    )

    if property_data["geo_precision"] != GEO_PRECISION_EXACT:
        print(
            "GEO PRECISION: "
            f"{property_data['geo_precision']} | "
            f"{property_data.get('location') or '-'}",
            flush=True,
        )

    # --------------------------------------------------------
    # Geocoding
    # --------------------------------------------------------

    if (
        property_data.get("geo_precision")
        == GEO_PRECISION_EXACT
        and (
            property_data.get("latitude") is None
            or property_data.get("longitude") is None
        )
    ):

        location = property_data.get("location")

        if location:

            try:

                geo = (
                    _geocode_location_with_fallback(
                        location
                    )
                )

                if geo:

                    property_data["latitude"] = (
                        geo["latitude"]
                    )

                    property_data["longitude"] = (
                        geo["longitude"]
                    )

                    property_data["geocode_query"] = (
                        geo["geocode_query"]
                    )

                    property_data["geocoded_at"] = (
                        geo["geocoded_at"]
                    )
                    property_data["geocode_source_location"] = (
                        location
                    )

                    print(
                        f"GEO: "
                        f"{geo['latitude']:.6f}, "
                        f"{geo['longitude']:.6f}",
                        flush=True
                    )

                else:

                    print(
                        f"GEO: not found | "
                        f"{location}",
                        flush=True
                    )

            except Exception as exc:

                print(
                    f"GEO ERROR: "
                    f"{type(exc).__name__}: {exc}",
                    flush=True
                )

    elif (
        property_data.get("latitude") is not None
        and property_data.get("longitude") is not None
    ):

        print(
            f"GEO: cached | "
            f"{property_data['latitude']:.6f}, "
            f"{property_data['longitude']:.6f}",
            flush=True
        )

    # --------------------------------------------------------
    # Water distance
    # --------------------------------------------------------

    if (
        property_data.get("latitude") is not None
        and property_data.get("longitude") is not None
        and property_data.get("water_score") is None
    ):

        try:

            water = find_best_water(
                property_data["latitude"],
                property_data["longitude"]
            )

            if water:

                property_data["water_distance_km"] = (
                    water["distance_km"]
                )

                property_data["water_class"] = (
                    water.get("water_class")
                )

                property_data["water_width_lower_m"] = (
                    water.get("width_lower_m")
                )

                property_data["water_width_upper_m"] = (
                    water.get("width_upper_m")
                )

                property_data["water_score"] = (
                    water.get("water_score")
                )

                property_data["water_name"] = (
                    water.get("name")
                )

                property_data["water_type"] = (
                    water.get("waterway")
                )

                property_data["water_osm_type"] = (
                    water.get("osm_type")
                )

                property_data["water_osm_id"] = (
                    water.get("osm_id")
                )

                print(
                    f"WATER: "
                    f"{water.get('water_class') or 'unknown'} | "
                    f"{water['distance_km']:.2f} km | "
                    f"{water.get('water_score', 0)}/20",
                    flush=True
                )

            else:

                # Prüfung erfolgreich, aber innerhalb des
                # Suchradius wurde kein geeignetes Wasser
                # gefunden.
                #
                # 0 = geprüft und keine Punkte
                # None = noch nicht geprüft
                property_data["water_distance_km"] = None
                property_data["water_class"] = (
                    "none_nearby"
                )
                property_data["water_width_lower_m"] = None
                property_data["water_width_upper_m"] = None
                property_data["water_score"] = 0

                print(
                    "WATER: none within search radius | "
                    "0/20",
                    flush=True
                )

        except Exception as exc:

            property_data["_geo_errors"]["Wasser"] = f"{type(exc).__name__}: {exc}"[:350]
            print(
                f"WATER ERROR: "
                f"{type(exc).__name__}: {exc}",
                flush=True
            )

    elif property_data.get("water_score") is not None:

        if property_data.get(
            "water_distance_km"
        ) is not None:

            print(
                f"WATER: cached | "
                f"{property_data['water_distance_km']:.2f} km | "
                f"{property_data['water_score']}/20",
                flush=True
            )

        else:

            print(
                "WATER: cached | "
                f"{property_data.get('water_class') or 'none_nearby'} | "
                f"{property_data['water_score']}/20",
                flush=True
            )
    # --------------------------------------------------------
    # Neighbour buildings
    # --------------------------------------------------------

    if (
        property_data.get("latitude") is not None
        and property_data.get("longitude") is not None
        and property_data.get(
            "neighbour_checked_at"
        ) is None
    ):
        try:

            buildings = find_neighbour_buildings(
                property_data["latitude"],
                property_data["longitude"]
            )

            property_data["nearest_building_m"] = (
                buildings.get("nearest_building_m")
            )

            property_data["buildings_50m"] = (
                buildings.get("buildings_50m")
            )

            property_data["buildings_100m"] = (
                buildings.get("buildings_100m")
            )

            property_data["buildings_250m"] = (
                buildings.get("buildings_250m")
            )

            property_data["buildings_500m"] = (
                buildings.get("buildings_500m")
            )

            property_data["neighbour_class"] = (
                classify_neighbours(buildings)
            )

            property_data["neighbour_checked_at"] = (
                datetime.now(timezone.utc).isoformat()
            )

            nearest = property_data.get(
                "nearest_building_m"
            )

            nearest_text = (
                f"{nearest:.0f} m"
                if nearest is not None
                else "none"
            )

            print(
                f"NEIGHBOURS: "
                f"{property_data['neighbour_class']} | "
                f"nearest={nearest_text} | "
                f"50m={property_data.get('buildings_50m')} | "
                f"100m={property_data.get('buildings_100m')} | "
                f"250m={property_data.get('buildings_250m')} | "
                f"500m={property_data.get('buildings_500m')}",
                flush=True
            )

        except Exception as exc:

            property_data["_geo_errors"]["Nachbarn"] = f"{type(exc).__name__}: {exc}"[:350]
            print(
                f"NEIGHBOUR ERROR: "
                f"{type(exc).__name__}: {exc}",
                flush=True
            )

    elif property_data.get(
        "neighbour_checked_at"
    ) is not None:

        nearest = property_data.get(
            "nearest_building_m"
        )

        nearest_text = (
            f"{nearest:.0f} m"
            if nearest is not None
            else "none"
        )

        print(
            f"NEIGHBOURS: cached | "
            f"{property_data.get('neighbour_class')} | "
            f"nearest={nearest_text} | "
            f"50m={property_data.get('buildings_50m')} | "
            f"100m={property_data.get('buildings_100m')} | "
            f"250m={property_data.get('buildings_250m')} | "
            f"500m={property_data.get('buildings_500m')}",
            flush=True
        )

    # --------------------------------------------------------
    # Traffic noise
    # --------------------------------------------------------

    if (
        property_data.get("latitude") is not None
        and property_data.get("longitude") is not None
        and property_data.get("noise_checked_at") is None
    ):

        try:

            noise = get_noise(
                property_data["latitude"],
                property_data["longitude"],
            )

            rail = noise.get("rail", {})
            road = noise.get("road", {})
            air = noise.get("air", {})

            property_data["rail_lden"] = rail.get(
                "lden"
            )

            property_data["rail_lnight"] = rail.get(
                "lnight"
            )

            property_data["rail_distance_m"] = rail.get(
                "rail_distance_m"
            )

            property_data["rail_annual_traffic"] = rail.get(
                "annual_traffic"
            )

            property_data["road_lden"] = road.get(
                "lden"
            )

            property_data["road_lnight"] = road.get(
                "lnight"
            )

            property_data["road_noise_source"] = road.get(
                "source"
            )

            property_data["air_lden"] = air.get(
                "lden"
            )

            property_data["air_lnight"] = air.get(
                "lnight"
            )

            property_data["air_noise_source"] = air.get(
                "source"
            )

            property_data["noise_checked_at"] = (
                datetime.now(timezone.utc).isoformat()
            )

            print(
                "NOISE: "
                f"rail="
                f"{rail.get('lden_band')}/"
                f"{rail.get('lnight_band')} | "
                f"road="
                f"{road.get('lden_band') or '<55'}/"
                f"{road.get('lnight_band') or '<50'} | "
                f"air="
                f"{air.get('lden_band') or '<55'}/"
                f"{air.get('lnight_band') or '<50'}",
                flush=True,
            )

        except Exception as exc:

            property_data["_geo_errors"]["Lärm/Bahn"] = f"{type(exc).__name__}: {exc}"[:350]
            print(
                f"NOISE ERROR: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

    elif property_data.get("noise_checked_at") is not None:

        print(
            "NOISE: cached | "
            f"rail={property_data.get('rail_lden')}/"
            f"{property_data.get('rail_lnight')} | "
            f"road={property_data.get('road_lden')}/"
            f"{property_data.get('road_lnight')} | "
            f"air={property_data.get('air_lden')}/"
            f"{property_data.get('air_lnight')}",
            flush=True,
        )

    return property_data
# ------------------------------------------------------------
# Property storage
# ------------------------------------------------------------
def save_property(conn, property_data, source_message_id):

    now = datetime.now(timezone.utc).isoformat()

    score_details_json = None

    if property_data.get("score_details") is not None:
        score_details_json = json.dumps(
            property_data["score_details"],
            ensure_ascii=False
        )

    params = {
        "portal": property_data["portal"],
        "portal_id": property_data["portal_id"],
        "raw_text": property_data.get(
            "raw_text"
        ),
        "title": property_data.get("title"),
        "url": property_data.get("url"),
        "location": property_data.get("location"),
        "price": property_data.get("price"),
        "living_area": property_data.get("living_area"),
        "rooms": property_data.get("rooms"),
        "plot_area": property_data.get("plot_area"),
        "commission_free": int(
            property_data.get("commission_free", False)
        ),
        "property_type": property_data.get("property_type"),
        "condition_class": property_data.get(
            "condition_class"
        ),
        "condition_reason": property_data.get(
            "condition_reason"
        ),
        "condition_source": property_data.get(
            "condition_source"
        ),
        "score": property_data.get("score"),
        "rating": property_data.get("rating"),
        "is_ko": property_data.get("is_ko", 0),
        "score_details": score_details_json,
        "water_distance_km": property_data.get(
            "water_distance_km"
        ),
        "water_class": property_data.get(
            "water_class"
        ),

        "water_width_lower_m": property_data.get(
            "water_width_lower_m"
        ),

        "water_width_upper_m": property_data.get(
            "water_width_upper_m"
        ),

        "water_score": property_data.get(
            "water_score"
        ),
        "neighbour_class": property_data.get(
            "neighbour_class"
        ),
        "nearest_building_m": property_data.get(
            "nearest_building_m"
        ),
        "buildings_50m": property_data.get(
            "buildings_50m"
        ),
        "buildings_100m": property_data.get(
            "buildings_100m"
         ),
        "buildings_250m": property_data.get(
            "buildings_250m"
        ),
        "buildings_500m": property_data.get(
            "buildings_500m"
        ),
        "neighbour_checked_at": property_data.get(
            "neighbour_checked_at"
        ),
        "buildability": property_data.get(
            "buildability"
        ),
        "buildability_class": property_data.get(
            "buildability_class"
        ),
        "buildability_reason": property_data.get(
             "buildability_reason"
        ),
        "primary_residence": property_data.get(
            "primary_residence"
        ),
        "residential_building_allowed": (
            None
            if property_data.get(
                "residential_building_allowed"
            ) is None
            else int(
                property_data[
                    "residential_building_allowed"
                ]
            )
        ),
        "holiday_area": (
            None
            if property_data.get("holiday_area") is None
            else int(property_data["holiday_area"])
        ),
        "severe_noise": (
            None
            if property_data.get("severe_noise") is None
            else int(property_data["severe_noise"])
        ),
        "rail_lden": property_data.get(
            "rail_lden"
        ),
        "rail_lnight": property_data.get(
            "rail_lnight"
        ),
        "rail_distance_m": property_data.get(
            "rail_distance_m"
        ),
        "rail_annual_traffic": property_data.get(
            "rail_annual_traffic"
        ),
        "road_lden": property_data.get(
            "road_lden"
        ),
        "road_lnight": property_data.get(
            "road_lnight"
        ),
        "road_noise_source": property_data.get(
            "road_noise_source"
        ),
        "air_lden": property_data.get(
            "air_lden"
        ),
        "air_lnight": property_data.get(
            "air_lnight"
        ),
        "air_noise_source": property_data.get(
            "air_noise_source"
        ),
        "noise_checked_at": property_data.get(
            "noise_checked_at"
        ),
        "latitude": property_data.get("latitude"),
        "longitude": property_data.get("longitude"),
        "geocode_query": property_data.get(
            "geocode_query"
        ),
        "geocoded_at": property_data.get(
            "geocoded_at"
        ),
        "geocode_source_location": property_data.get(
            "geocode_source_location"
        ),
        "geo_precision": property_data.get(
            "geo_precision"
        ),
        "source_message_id": source_message_id,
        "now": now,
    }

    existing = conn.execute(
        """
        SELECT id
        FROM properties
        WHERE portal = :portal
          AND portal_id = :portal_id
        """,
        params
    ).fetchone()

    if existing:

        property_id = existing[0]
        params["property_id"] = property_id

        conn.execute(
            """
            UPDATE properties
            SET
                title = :title,
                url = :url,
                raw_text = :raw_text,
                location = :location,
                price = :price,
                living_area = :living_area,
                rooms = :rooms,
                plot_area = :plot_area,
                commission_free = :commission_free,
                property_type = :property_type,
                condition_class = :condition_class,
                condition_reason = :condition_reason,
                condition_source = :condition_source,
                score = :score,
                rating = :rating,
                is_ko = :is_ko,
                score_details = :score_details,
                water_distance_km = :water_distance_km,
                water_class = :water_class,
                water_width_lower_m = :water_width_lower_m,
                water_width_upper_m = :water_width_upper_m,
                water_score = :water_score,
                neighbour_class = :neighbour_class,
                nearest_building_m = :nearest_building_m,
                buildings_50m = :buildings_50m,
                buildings_100m = :buildings_100m,
                buildings_250m = :buildings_250m,
                buildings_500m = :buildings_500m,
                neighbour_checked_at = :neighbour_checked_at,
                buildability = :buildability,
                buildability_class = :buildability_class,
                buildability_reason = :buildability_reason,
                primary_residence = :primary_residence,
                residential_building_allowed =
                    :residential_building_allowed,
                holiday_area = :holiday_area,
                severe_noise = :severe_noise,
                rail_lden = :rail_lden,
                rail_lnight = :rail_lnight,
                rail_distance_m = :rail_distance_m,
                rail_annual_traffic = :rail_annual_traffic,
                road_lden = :road_lden,
                road_lnight = :road_lnight,
                road_noise_source = :road_noise_source,
                air_lden = :air_lden,
                air_lnight = :air_lnight,
                air_noise_source = :air_noise_source,
                noise_checked_at = :noise_checked_at,
                latitude = :latitude,
                longitude = :longitude,
                geocode_query = :geocode_query,
                geocoded_at = :geocoded_at,
                geocode_source_location = :geocode_source_location,
                geo_precision = :geo_precision,
                last_seen = :now
            WHERE id = :property_id
            """,
            params
        )

        duplicate = True

    else:

        cursor = conn.execute(
            """
            INSERT INTO properties (
                portal,
                portal_id,
                title,
                url,
                raw_text,
                location,
                price,
                living_area,
                rooms,
                plot_area,
                commission_free,
                property_type,
                condition_class,
                condition_reason,
                condition_source,
                score,
                rating,
                is_ko,
                score_details,
                water_distance_km,
                water_class,
                water_width_lower_m,
                water_width_upper_m,
                water_score,
                neighbour_class,
                nearest_building_m,
                buildings_50m,
                buildings_100m,
                buildings_250m,
                buildings_500m,
                neighbour_checked_at,
                buildability,
                buildability_class,
                buildability_reason,
                primary_residence,
                residential_building_allowed,
                holiday_area,
                severe_noise,
                rail_lden,
                rail_lnight,
                rail_distance_m,
                rail_annual_traffic,
                road_lden,
                road_lnight,
                road_noise_source,
                air_lden,
                air_lnight,
                air_noise_source,
                noise_checked_at,
                latitude,
                longitude,
                geocode_query,
                geocoded_at,
                geocode_source_location,
                geo_precision,
                first_seen,
                last_seen,
                source_message_id
            )
            VALUES (
                :portal,
                :portal_id,
                :title,
                :url,
                :raw_text,
                :location,
                :price,
                :living_area,
                :rooms,
                :plot_area,
                :commission_free,
                :property_type,
                :condition_class,
                :condition_reason,
                :condition_source,
                :score,
                :rating,
                :is_ko,
                :score_details,
                :water_distance_km,
                :water_class,
                :water_width_lower_m,
                :water_width_upper_m,
                :water_score,
                :neighbour_class,
                :nearest_building_m,
                :buildings_50m,
                :buildings_100m,
                :buildings_250m,
                :buildings_500m,
                :neighbour_checked_at,
                :buildability,
                :buildability_class,
                :buildability_reason,
                :primary_residence,
                :residential_building_allowed,
                :holiday_area,
                :severe_noise,
                :rail_lden,
                :rail_lnight,
                :rail_distance_m,
                :rail_annual_traffic,
                :road_lden,
                :road_lnight,
                :road_noise_source,
                :air_lden,
                :air_lnight,
                :air_noise_source,
                :noise_checked_at,
                :latitude,
                :longitude,
                :geocode_query,
                :geocoded_at,
                :geocode_source_location,
                :geo_precision,
                :now,
                :now,
                :source_message_id
            )
            """,
            params
        )

        property_id = cursor.lastrowid
        duplicate = False

    search_id = property_data.get("search_id")

    if search_id:

        conn.execute(
            """
            INSERT OR IGNORE INTO property_searches (
                property_id,
                search_id,
                first_seen
            )
            VALUES (?, ?, ?)
            """,
            (
                property_id,
                search_id,
                now
            )
        )

    conn.commit()

    return duplicate, property_id

def load_existing_energy_for_refresh(
    conn,
    property_data,
):

    columns = tuple(
        ENERGY_COLUMNS.keys()
    )

    select_columns = ", ".join(
        columns
    )

    existing = conn.execute(
        f"""
        SELECT {select_columns}
        FROM properties
        WHERE portal = ?
          AND portal_id = ?
        LIMIT 1
        """,
        (
            property_data.get("portal"),
            property_data.get("portal_id"),
        ),
    ).fetchone()

    if not existing:
        return property_data

    stored = dict(
        zip(
            columns,
            existing,
        )
    )

    status = str(
        stored.get(
            "energy_certificate_status"
        )
        or "unknown"
    ).strip().lower()

    if (
        stored.get(
            "energy_updated_at"
        ) is None
        or status == "not_available_yet"
    ):
        return property_data

    for key in columns:
        property_data[key] = stored.get(
            key
        )

    property_data[
        "_preserved_energy_from_db"
    ] = True

    return property_data


def process_property(
    conn,
    property_data,
    source_message_id=None,
    *,
    notify=False,
    apply_filters=True,
    immoscout_html_block="",
):
    """
    Gemeinsame Verarbeitung eines bereits geparsten Immobilienobjekts.

    Verwendbar für:
    - Mail-Import
    - Telegram-Linkimport
    - spätere Makler-/Website-Scanner
    """

    portal = property_data.get("portal")
    portal_id = property_data.get("portal_id")

    if not portal or not portal_id:
        raise ValueError(
            "property_data benötigt portal und portal_id"
        )

    if apply_filters:
        if is_spam_object(
            conn,
            portal,
            portal_id
        ):
            return {
                "status": "spam",
                "property_data": property_data,
                "property_id": None,
                "duplicate": False,
            }

        if is_blacklisted(
            property_data.get("title"),
            property_data.get("location"),
            property_data.get("url"),
            property_data.get("raw_text"),
            immoscout_html_block,
            property_type=property_data.get(
                "property_type"
            ),
        ):
            return {
                "status": "blacklisted",
                "property_data": property_data,
                "property_id": None,
                "duplicate": False,
            }

        # ----------------------------------------------------
        # Immowelt: Telegram-Webpage-Preview als zusätzliche
        # Quelle verwenden.
        #
        # Die Immowelt-Mail enthält z.B. den Hinweis
        # "Zwangsversteigerungen" häufig nicht. Telegram sieht
        # ihn jedoch bereits in der Webpage-Preview.
        #
        # Fehler beim Preview-Abruf sind absichtlich nicht
        # fatal: In diesem Fall wird das Objekt normal weiter
        # verarbeitet.
        # ----------------------------------------------------

        if (
            portal == "immowelt"
            and property_data.get("url")
        ):
            try:
                telegram_preview = (
                    get_telegram_preview(
                        property_data["url"]
                    )
                )
                print(
                    f"TELEGRAM PREVIEW: "
                    f"{portal_id} | "
                    f"{telegram_preview!r}",
                    flush=True
                )
            except Exception as exc:
                print(
                    f"TELEGRAM PREVIEW ERROR: "
                    f"{portal_id} | "
                    f"{type(exc).__name__}: "
                    f"{exc}",
                    flush=True
                )

                telegram_preview = None

            if telegram_preview:
                preview_title = (
                    telegram_preview.get("title")
                    or ""
                )

                preview_description = (
                    telegram_preview.get(
                        "description"
                    )
                    or ""
                )

                property_data[
                    "telegram_preview_title"
                ] = preview_title

                property_data[
                    "telegram_preview_description"
                ] = preview_description

                if is_blacklisted(
                    preview_title,
                    preview_description,
                    property_type=property_data.get(
                        "property_type"
                    ),
                ):
                    print(
                        f"TELEGRAM PREVIEW BLACKLIST: "
                        f"{portal_id} | "
                        f"{preview_title}",
                        flush=True
                    )

                    return {
                        "status": "blacklisted",
                        "property_data": property_data,
                        "property_id": None,
                        "duplicate": False,
                    }

    property_data = load_existing_energy_for_refresh(
        conn,
        property_data,
    )

    property_type = detect_property_type(
        property_data
    )

    property_data["property_type"] = property_type

    if is_house_type(property_type):

        # ----------------------------------------------------
        # Manuell gesetzter Hauszustand hat Vorrang.
        #
        # Der neue Parser-/Browserinhalt darf eine bereits
        # vom Benutzer gesetzte Entscheidung nicht wieder
        # automatisch überschreiben.
        # ----------------------------------------------------

        existing_condition = conn.execute(
            """
            SELECT
                condition_class,
                condition_reason,
                condition_source
            FROM properties
            WHERE portal = ?
              AND portal_id = ?
            LIMIT 1
            """,
            (
                portal,
                portal_id,
            ),
        ).fetchone()

        manual_condition = False

        if existing_condition:

            existing_class = (
                existing_condition[0]
            )

            existing_reason = (
                existing_condition[1]
            )

            existing_source = (
                existing_condition[2]
            )

            reason_text = str(
                existing_reason or ""
            ).strip().casefold()

            source_text = str(
                existing_source or ""
            ).strip().casefold()

            manual_condition = bool(
                existing_class
                and (
                    reason_text
                    == "manuell gesetzt"
                    or source_text in (
                        "manual",
                        "manuell",
                        "manual_override",
                        "telegram_manual",
                        "browser_explicit",
                    )
                )
            )

            if manual_condition:

                property_data[
                    "condition_class"
                ] = existing_class

                property_data[
                    "condition_reason"
                ] = existing_reason

                property_data[
                    "condition_source"
                ] = existing_source

                print(
                    "CONDITION: manual override | "
                    f"{portal_id} | "
                    f"{existing_class}",
                    flush=True,
                )

        if not manual_condition:

            condition_result = (
                classify_house_condition(
                    property_data
                )
            )

            property_data.update(
                condition_result
            )

    property_data = enrich_property(
        conn,
        property_data
    )

    if property_type == "land":
        buildability_result = classify_buildability(
            property_data
        )

        property_data.update(
            buildability_result
        )

        # ----------------------------------------------------
        # Automatische Bebaubarkeitsklassifizierung in den
        # kanonischen Scoring-Wert überführen.
        #
        # Manuell gesetztes "buildability" hat weiterhin
        # Vorrang und wird niemals überschrieben.
        # ----------------------------------------------------

        if not property_data.get(
            "buildability"
        ):

            reason = str(
                property_data.get(
                    "buildability_reason"
                )
                or ""
            ).casefold()

            if (
                "positive bauvoranfrage"
                in reason
                or "bauvorbescheid"
                in reason
            ):

                property_data[
                    "buildability"
                ] = (
                    "PRELIMINARY_APPROVAL"
                )

            elif "bebauungsplan" in reason:

                property_data[
                    "buildability"
                ] = "CONSTRUCTIONPLAN"

            elif (
                "nachbarbebauung" in reason
                or "§34" in reason
                or "§ 34" in reason
            ):

                property_data[
                    "buildability"
                ] = (
                    "NEIGHBOURCONSTRUCTION"
                )

            elif (
                "außenbereich" in reason
                or "aussenbereich" in reason
                or "§35" in reason
                or "§ 35" in reason
            ):

                property_data[
                    "buildability"
                ] = "EXTERNALAREA"

        score_result = score_land(
            property_data
        )

    elif is_house_type(property_type):
        score_result = score_house(
            property_data
        )

    else:
        score_result = None

    if score_result is not None:
        property_data["score"] = (
            score_result["score"]
        )

        property_data["rating"] = (
            score_result["rating"]
        )

        property_data["is_ko"] = int(
            score_result["ko"]
        )

        property_data["score_details"] = (
            score_result
        )

    else:
        property_data["score"] = None
        property_data["rating"] = None
        property_data["is_ko"] = 0
        property_data["score_details"] = None

    duplicate, property_id = save_property(
        conn,
        property_data,
        source_message_id
    )

    # --------------------------------------------------------
    # Energiedaten
    #
    # save_property() speichert derzeit nicht alle optionalen
    # Energiefelder. Bereits vom Parser / Browser gelieferte
    # Daten deshalb nach dem normalen Property-Save zentral
    # persistieren.
    #
    # Nur tatsächlich vorhandene Werte schreiben, damit
    # bestehende Daten nicht durch None überschrieben werden.
    # --------------------------------------------------------

    energy_fields = (
        "energy_class",
        "energy_value_kwh",
        "energy_certificate_type",
        "energy_certificate_status",
        "heating_type",
        "energy_source",
        "energy_construction_year",
        "energy_data_source",
        "energy_raw_text",
    )

    preserved_energy = bool(
        property_data.pop(
            "_preserved_energy_from_db",
            False,
        )
    )

    energy_updates = (
        {}
        if preserved_energy
        else {
            key: property_data.get(key)
            for key in energy_fields
            if property_data.get(key) is not None
        }
    )

    if energy_updates:

        energy_updated_at = (
            datetime.now(
                timezone.utc
            ).isoformat()
        )

        energy_updates[
            "energy_updated_at"
        ] = energy_updated_at

        assignments = ", ".join(
            f"{key} = ?"
            for key in energy_updates
        )

        values = list(
            energy_updates.values()
        )

        values.append(
            property_id
        )

        conn.execute(
            f"""
            UPDATE properties
            SET {assignments}
            WHERE id = ?
            """,
            values,
        )

        conn.commit()

        property_data[
            "energy_updated_at"
        ] = energy_updated_at

    # --------------------------------------------------------
    # Finale Bewertung
    # --------------------------------------------------------
    #
    # Die erste Bewertung findet bereits vor dem optionalen
    # Energie-Enrichment statt.
    #
    # Deshalb unmittelbar vor der Telegram-Nachricht noch
    # einmal mit dem endgültigen Datenstand bewerten.
    #
    # Wichtig:
    #   None = Bewertung noch unvollständig
    #   0    = echte 0 Punkte / KO
    # --------------------------------------------------------

    if not duplicate:

        if property_type == "land":

            final_score_result = score_land(
                property_data
            )

        elif is_house_type(
            property_type
        ):

            final_score_result = score_house(
                property_data
            )

        else:

            final_score_result = None

        if final_score_result is not None:

            property_data["score"] = (
                final_score_result[
                    "score"
                ]
            )

            property_data["rating"] = (
                final_score_result[
                    "rating"
                ]
            )

            property_data["is_ko"] = int(
                final_score_result[
                    "ko"
                ]
            )

            property_data[
                "score_details"
            ] = final_score_result

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
                    final_score_result[
                        "score"
                    ],
                    final_score_result[
                        "rating"
                    ],
                    int(
                        final_score_result[
                            "ko"
                        ]
                    ),
                    json.dumps(
                        final_score_result,
                        ensure_ascii=False,
                    ),
                    property_id,
                )
            )

            conn.commit()

    if notify and not duplicate:
        telegram(
            format_property(
                property_data
            ),
            reply_markup=property_action_keyboard(
                property_data["portal_id"],
                property_type,
                "new"
            )
        )

    return {
        "status": (
            "updated"
            if duplicate
            else "created"
        ),
        "property_data": property_data,
        "property_id": property_id,
        "duplicate": duplicate,
    }

# ------------------------------------------------------------
# Ohne-Makler Mail parser
# ------------------------------------------------------------

def parse_ohne_makler_mail(
    text,
    html_text="",
):
    """
    Ohne-Makler-Mails werden nicht selbst als Exposé geparst.

    Stattdessen:
    - Objekt-IDs aus Plaintext / HTML sammeln
    - kanonische Exposé-URL bilden
    - normalen Ohne-Makler-Webparser verwenden

    Dadurch verwenden Telegram-Linkimport und Mailimport
    dieselbe Datenquelle und dieselbe Parserlogik.
    """

    from ohne_makler import (
        fetch_ohne_makler,
    )

    from url_import import (
        _normalize_ohne_makler_facts,
    )

    source = "\n".join(
        (
            text or "",
            html_text or "",
        )
    )

    matches = re.findall(
        r"(?:https?://"
        r"(?:www\.)?"
        r"ohne-makler\.net)?"
        r"/immobilie/(\d+)"
        r"/?",
        source,
        re.I,
    )

    portal_ids = []

    for portal_id in matches:

        if portal_id not in portal_ids:
            portal_ids.append(
                portal_id
            )

    properties = []

    for portal_id in portal_ids:

        url = (
            "https://www.ohne-makler.net/"
            f"immobilie/{portal_id}/"
        )

        try:

            property_data = (
                fetch_ohne_makler(
                    url
                )
            )

            property_data = (
                _normalize_ohne_makler_facts(
                    property_data
                )
            )

            # Parser-interne Felder nicht in die
            # zentrale Property-Struktur übernehmen.
            for key in (
                "source_object_class",
                "source_object_type",
                "source_facts",
            ):
                property_data.pop(
                    key,
                    None,
                )

            properties.append(
                property_data
            )

            print(
                "OHNE-MAKLER MAIL: "
                f"{portal_id} | "
                f"{property_data.get('property_type')} | "
                f"{property_data.get('title')}",
                flush=True,
            )

        except Exception as exc:

            print(
                "OHNE-MAKLER MAIL ERROR: "
                f"{portal_id} | "
                f"{type(exc).__name__}: "
                f"{exc}",
                flush=True,
            )

    return properties


# ------------------------------------------------------------
# Mail processing
# ------------------------------------------------------------

def archive_message(raw_message, message_hash):

    now = datetime.now(timezone.utc)

    directory = os.path.join(
        EMAIL_DIR,
        now.strftime("%Y"),
        now.strftime("%m"),
        now.strftime("%d")
    )

    os.makedirs(
        directory,
        exist_ok=True
    )

    path = os.path.join(
        directory,
        f"{message_hash}.eml"
    )

    with open(path, "wb") as f:
        f.write(raw_message)

    return path


def process_mailbox():

    print(
        "Checking mailbox...",
        flush=True
    )

    context = ssl.create_default_context()

    with imaplib.IMAP4_SSL(
        IMAP_HOST,
        IMAP_PORT,
        ssl_context=context
    ) as imap:

        imap.login(
            IMAP_USER,
            IMAP_PASSWORD
        )

        status, _ = imap.select(
            IMAP_MAILBOX
        )

        if status != "OK":
            raise RuntimeError(
                "Could not select mailbox"
            )

        status, data = imap.search(
            None,
            "UNSEEN"
        )

        if status != "OK":
            raise RuntimeError(
                "Could not search mailbox"
            )

        message_ids = data[0].split()

        if not message_ids:

            print(
                "No new messages.",
                flush=True
            )

            return

        conn = get_db()

        for message_id in message_ids:

            status, message_data = imap.fetch(
                message_id,
                "(RFC822)"
            )

            if status != "OK":
                continue

            raw_message = message_data[0][1]

            message_hash = hashlib.sha256(
                raw_message
            ).hexdigest()

            message = email.message_from_bytes(
                raw_message
            )

            sender = decode_text(
                message.get("From")
            )

            subject = decode_text(
                message.get("Subject")
            )

            date = message.get("Date")

            received_at = datetime.now(
                timezone.utc
            ).isoformat()

            # Bereits bekannte Mail?
            already = conn.execute(
                """
                SELECT id
                FROM messages
                WHERE message_hash = ?
                """,
                (message_hash,)
            ).fetchone()

            if already:
                continue

            archive_path = archive_message(
                raw_message,
                message_hash
            )

            cursor = conn.execute(
                """
                INSERT INTO messages
                (
                    message_hash,
                    imap_uid,
                    sender,
                    subject,
                    date,
                    received_at,
                    archive_path
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_hash,
                    message_id.decode(),
                    sender,
                    subject,
                    date,
                    received_at,
                    archive_path
                )
            )

            message_db_id = cursor.lastrowid

            body = get_email_text(message)
            html_body = get_email_html(message)

            # ImmoScout24 erkennen

            # ------------------------------------------------
            # Portal erkennen und parsen
            # ------------------------------------------------

            body_lower = body.lower()

            is_is24 = (
                "immobilienscout24" in body_lower
                or "is24" in body_lower
                or "push.search.is24.de" in body_lower
            )

            is_immowelt = (
                "immowelt" in body_lower
                or "click.by.immowelt.de" in body_lower
            )

            mail_lower = "\n".join(
                (
                    sender or "",
                    subject or "",
                    body or "",
                    html_body or "",
                )
            ).lower()

            is_ohne_makler = (
                "ohne-makler.net"
                in mail_lower
                or "ohne-makler"
                in mail_lower
            )

            if is_is24:

                properties = parse_immoscout(
                    body
                )

                portal_name = "ImmoScout24"

            elif is_immowelt:

                properties = parse_immowelt(
                    body
                )

                portal_name = "Immowelt"

            elif is_ohne_makler:

                properties = (
                    parse_ohne_makler_mail(
                        body,
                        html_body,
                    )
                )

                portal_name = "Ohne-Makler"

                # Eine erkannte Ohne-Makler-Mail ohne
                # Exposé-Link soll nicht lautlos verschwinden.
                if not properties:
                    properties = None

            else:

                properties = None
                portal_name = None

            # ------------------------------------------------
            # Erkannte Portal-Mail verarbeiten
            # ------------------------------------------------

            if properties is not None:

                print(
                    f"{portal_name}: "
                    f"{len(properties)} object(s)",
                    flush=True
                )

                for property_data in properties:

                    immoscout_html_block = ""

                    if (
                        property_data.get("portal")
                        == "immoscout24"
                    ):
                        immoscout_html_block = (
                            get_immoscout_html_block(
                                html_body,
                                property_data.get(
                                    "portal_id"
                                )
                            )
                        )

                    result = process_property(
                        conn,
                        property_data,
                        source_message_id=message_db_id,
                        notify=True,
                        apply_filters=True,
                        immoscout_html_block=immoscout_html_block,
                    )

                    status = result.get(
                        "status"
                    )

                    if status == "spam":
                        print(
                            f"SPAM BLOCKED: "
                            f"{property_data.get('portal_id')} | "
                            f"{property_data.get('title')}",
                            flush=True
                        )
                        continue

                    if status == "blacklisted":
                        print(
                            f"BLACKLISTED: "
                            f"{property_data.get('title')}",
                            flush=True
                        )
                        continue

                    processed = result[
                        "property_data"
                    ]

                    property_type = (
                        processed.get(
                            "property_type"
                        )
                        or "unknown"
                    )

                    print(
                        f"TYPE: "
                        f"{property_type.upper()} | "
                        f"{processed.get('portal_id')} | "
                        f"{processed.get('title')}",
                        flush=True
                    )

                    if (
                        processed.get("score")
                        is not None
                    ):
                        print(
                            f"SCORE: "
                            f"{processed.get('score')}/100 | "
                            f"{processed.get('rating')} | "
                            f"KO="
                            f"{bool(processed.get('is_ko'))}",
                            flush=True
                        )

            else:

                print(
                    f"Unknown portal/mail format: "
                    f"{subject}",
                    flush=True
                )

                telegram(
                    "🏠 Immobilien-Monitor\n\n"
                    "Neue Immobilien-Mail "
                    "erhalten.\n\n"
                    f"{subject}\n\n"
                    "⚠️ Portal/Format noch nicht "
                    "automatisch erkannt."
                )

            conn.commit()

            # Als gelesen markieren.
            imap.store(
                message_id,
                "+FLAGS",
                "\\Seen"
            )

        conn.close()

# ------------------------------------------------------------
# Main loop
# ------------------------------------------------------------

def main():

    print(
        "Immobilien Monitor starting...",
        flush=True
    )

    get_db().close()

    while True:

        try:

            process_mailbox()

        except Exception as exc:

            import traceback

            print(
                f"ERROR: "
                f"{type(exc).__name__}: {exc}",
                flush=True
            )

            traceback.print_exc()

        time.sleep(
            POLL_SECONDS
        )


if __name__ == "__main__":
    main()
