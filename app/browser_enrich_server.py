#!/usr/bin/env python3

import json
import os
import re
import sqlite3
import tempfile
import time

from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from config_loader import (
    CONFIG as SCORE_CONFIG,
)

from scoring import (
    score_house,
    score_land,
)

from buildability import (
    classify_buildability,
)

from browser_energy import (
    energy_payload_from_browser,
)
from browser_condition import (
    condition_payload_from_browser,
)
from energy_data import (
    update_property_energy,
)
from lab_terminal import (
    clear_terminal_event,
    page_is_unavailable,
    purge_property,
    record_terminal_event,
)


HOST = "127.0.0.1"
PORT = 8765

BASE_DIR = Path(
    os.environ.get(
        "IMMOBILIEN_MONITOR_ROOT",
        "/opt/immobilien-monitor",
    )
)

INBOX_DIR = (
    BASE_DIR
    / "browser-enrich-inbox"
)

TOKEN_FILE = (
    BASE_DIR
    / "config"
    / "browser_enrich_token"
)

BLACKLIST_FILE = (
    BASE_DIR
    / "config"
    / "blacklist.yaml"
)

DB_PATH = (
    BASE_DIR
    / "data"
    / "database.sqlite3"
)

MAX_BODY = 2 * 1024 * 1024


def load_token():

    return TOKEN_FILE.read_text(
        encoding="utf-8"
    ).strip()


def load_blacklist_terms():

    terms = []

    if not BLACKLIST_FILE.exists():
        return terms

    in_terms = False

    for raw_line in BLACKLIST_FILE.read_text(
        encoding="utf-8"
    ).splitlines():

        stripped = raw_line.strip()

        if not stripped:
            continue

        if stripped.startswith("#"):
            continue

        if stripped == "terms:":
            in_terms = True
            continue

        if not in_terms:
            continue

        if not stripped.startswith("-"):
            break

        term = (
            stripped[1:]
            .strip()
            .strip("'\"")
            .lower()
        )

        if term:
            terms.append(term)

    return terms


def find_blacklist_terms(*values):

    text = " ".join(
        str(value or "")
        for value in values
    ).lower()

    matches = []

    for term in load_blacklist_terms():

        if (
            term in text
            and term not in matches
        ):
            matches.append(term)

    # Überlappende Begriffe zusammenfassen.
    #
    # Beispiel:
    #   zwangsversteigerung
    #   zwangsversteigerungen
    #
    # In diesem Fall genügt der allgemeinere,
    # kürzere Begriff als Blacklist-Grund.

    canonical = []

    for term in sorted(
        matches,
        key=len
    ):

        if any(
            term.startswith(existing)
            for existing in canonical
        ):
            continue

        canonical.append(
            term
        )

    return canonical

def blacklist_relevant_page_text(
    page_text,
    browser_url
):

    text = str(
        page_text or ""
    )

    url = str(
        browser_url or ""
    ).casefold()

    # --------------------------------------------------------
    # ImmoScout24:
    #
    # Nach dem eigentlichen Exposé folgen Empfehlungen wie
    # "Weiteres vom Anbietenden".
    #
    # Diese fremden Inserate dürfen nicht in die Blacklist-
    # Prüfung des aktuellen Objekts geraten.
    # --------------------------------------------------------

    if "immobilienscout24." in url:

        cut_markers = (
            "weiteres vom anbietenden",
            "weiteres vom anbieter",
            "weitere ergebnisse für:",
        )

        text_lower = text.casefold()

        positions = [
            text_lower.find(marker)
            for marker in cut_markers
            if text_lower.find(marker) >= 0
        ]

        if positions:

            cut_at = min(
                positions
            )

            print(
                "BLACKLIST TEXT CUT: "
                f"immoscout24 | "
                f"{len(text)} -> {cut_at} chars",
                flush=True
            )

            text = text[:cut_at]

    return text.strip()

def is_immowelt_preview_title(
    title
):

    title = str(
        title or ""
    ).strip()

    # Telegram liefert bei Immowelt z.B.:
    #
    # Grundstück 18000 € zum Kauf
    # Genthin,Genthin (39307)
    #
    # Nur solche technischen Preview-Titel sollen durch
    # den tatsächlichen Browser-Titel ersetzt werden.

    return bool(
        re.search(
            r"\d"
            r"[\d.\s\u00a0]*"
            r"(?:,\d+)?"
            r"\s*€"
            r"\s+zum\s+"
            r"(?:kauf|miete)\b",
            title,
            re.I
        )
    )


def extract_immowelt_title(
    page_text
):

    lines = [
        line.strip()
        for line in str(
            page_text or ""
        ).splitlines()
    ]

    # Bei Immowelt folgt der eigentliche Titel derzeit
    # unmittelbar nach:
    #
    #   Berechne die Fahrtzeit
    #   Zur Arbeit, zur Schule
    #
    # Danach kommt ein eigener Absatz mit dem Exposé-Titel.

    marker_index = None

    for index, line in enumerate(
        lines
    ):

        if (
            line.casefold()
            == "zur arbeit, zur schule"
        ):
            marker_index = index
            break

    if marker_index is None:

        for index, line in enumerate(
            lines
        ):

            if (
                line.casefold()
                == "berechne die fahrtzeit"
            ):
                marker_index = index
                break

    if marker_index is None:
        return None

    index = marker_index + 1

    # Falls wir beim ersten Marker gelandet sind,
    # "Zur Arbeit, zur Schule" überspringen.

    while (
        index < len(lines)
        and (
            not lines[index]
            or lines[index].casefold()
            == "zur arbeit, zur schule"
        )
    ):
        index += 1

    title_lines = []

    stop_terms = {
        "mehr anzeigen",
        "merkmale",
        "preisdetails",
        "kaufpreis",
    }

    while (
        index < len(lines)
        and len(title_lines) < 3
    ):

        line = lines[index]

        if not line:
            break

        if (
            line.casefold()
            in stop_terms
        ):
            break

        title_lines.append(
            line
        )

        index += 1

    if not title_lines:
        return None

    title = " ".join(
        title_lines
    )

    title = re.sub(
        r"\s+",
        " ",
        title
    ).strip()

    if (
        len(title) < 10
        or len(title) > 400
    ):
        return None

    return title


def normalize_immowelt_location(
    location
):

    location = str(
        location or ""
    ).strip()

    if not location:
        return location

    # Beispiel:
    #
    # Genthin, Genthin (39307)
    #
    # wird:
    #
    # Genthin (39307)
    #
    # Es werden ausschließlich zwei wirklich identische
    # Ortsbestandteile zusammengefasst.

    postal = ""

    match = re.search(
        r"\s*(\(\d{5}\))\s*$",
        location
    )

    base = location

    if match:

        postal = match.group(1)

        base = location[
            :match.start()
        ].strip()

    parts = [
        part.strip()
        for part in base.split(
            ",",
            1
        )
    ]

    if (
        len(parts) == 2
        and parts[0]
        and parts[1]
        and parts[0].casefold()
        == parts[1].casefold()
    ):

        result = parts[0]

        if postal:
            result += f" {postal}"

        return result

    return location


def extract_immowelt_price(
    page_text
):

    text = str(
        page_text or ""
    ).replace(
        "\u00a0",
        " "
    )

    # Nur ausdrücklich als Kaufpreis bezeichnete Werte.
    #
    # Typische Immowelt-Varianten:
    #
    #   295.000 €
    #   Kaufpreis
    #
    #   295.000 €
    #   Kaufpreis 1.454 €/m²
    #
    #   Kaufpreis
    #   295.000 €
    #
    # Dadurch werden €/m², Provisionen und Monatsraten
    # nicht als Kaufpreis übernommen.

    amount = (
        r"(?P<price>"
        r"\d[\d.\s\u00a0]*"
        r"(?:,\d{1,2})?"
        r")"
    )

    patterns = (
        (
            amount
            + r"\s*€"
            + r"[ \t\r\n]{0,30}"
            + r"\bKaufpreis\b"
        ),
        (
            r"\bKaufpreis\b"
            + r"[ \t\r\n:\-–—]{0,30}"
            + amount
            + r"\s*€"
        ),
    )

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.I
        )

        if not match:
            continue

        raw = (
            match.group("price")
            .replace("\u00a0", "")
            .replace(" ", "")
            .replace(".", "")
            .replace(",", ".")
        )

        try:
            price = float(raw)
        except ValueError:
            continue

        if (
            price > 0
            and price <= 100000000
        ):
            return price

    return None


def extract_immowelt_plot_area(
    page_text
):

    text = str(
        page_text or ""
    )

    # Typische Immowelt-Varianten:
    #
    #   4.580 m² Grundstück
    #   4580m2 Grundstück
    #   Grundstück 4580m2
    #   Grundstücksfläche 4.580 m²

    patterns = (
        (
            r"(?P<area>"
            r"\d[\d.\s\u00a0]*(?:,\d+)?"
            r")"
            r"\s*(?:m²|m2)"
            r"\s+grundstück\b"
        ),
        (
            r"\bgrundstück(?:sfläche)?\b"
            r"\s*[:\-]?\s*"
            r"(?P<area>"
            r"\d[\d.\s\u00a0]*(?:,\d+)?"
            r")"
            r"\s*(?:m²|m2)\b"
        ),
    )

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.I
        )

        if not match:
            continue

        raw = (
            match.group("area")
            .replace("\u00a0", "")
            .replace(" ", "")
            .replace(".", "")
            .replace(",", ".")
        )

        try:
            area = float(raw)
        except ValueError:
            continue

        # Plausibilitätsgrenzen verhindern,
        # dass irgendeine kleine m²-Angabe
        # versehentlich Grundstücksfläche wird.
        if (
            area >= 20
            and area <= 10000000
        ):
            return area

    return None


def safe_filename(value):

    return re.sub(
        r"[^a-zA-Z0-9_.-]+",
        "_",
        str(value)
    )


def ensure_database_columns():

    conn = sqlite3.connect(
        DB_PATH,
        timeout=10
    )

    try:

        columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(properties)"
            )
        }

        additions = {
            "browser_text":
                "TEXT",

            "browser_url":
                "TEXT",

            "browser_heading":
                "TEXT",

            "browser_enriched_at":
                "TEXT",
        }

        for name, column_type in additions.items():

            if name in columns:
                continue

            print(
                f"DB MIGRATION: adding {name}",
                flush=True
            )

            conn.execute(
                f"""
                ALTER TABLE properties
                ADD COLUMN {name} {column_type}
                """
            )

        conn.commit()

    finally:
        conn.close()


def update_database(data):

    portal = str(
        data.get("portal") or ""
    ).strip().lower()

    portal_id = str(
        data.get("portal_id") or ""
    ).strip()

    page_text = str(
        data.get("page_text") or ""
    )

    browser_url = str(
        data.get("url") or ""
    )

    browser_heading = str(
        data.get("heading") or ""
    )

    enriched_at = (
        datetime.now(
            timezone.utc
        ).isoformat()
    )

    conn = sqlite3.connect(
        DB_PATH,
        timeout=10
    )

    conn.row_factory = sqlite3.Row

    try:

        row = conn.execute(
            """
            SELECT *
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

        if not row:

            return {
                "database_status": "not_found",
                "duplicate": False,
                "blacklisted": False,
                "blacklist_terms": [],
            }

        property_data = dict(row)

        # ----------------------------------------------------
        # Terminaler Portalzustand.
        #
        # Nur eine ausdrücklich als nicht mehr verfügbar /
        # deaktiviert / gelöscht erkannte Portalseite führt
        # zum Purge. HTTP-Fehler oder leere Seiten allein
        # reichen ausdrücklich nicht.
        # ----------------------------------------------------

        if page_is_unavailable(
            page_text,
            browser_heading,
        ):

            purge_property(
                conn,
                property_data["id"],
                portal,
                portal_id,
            )

            conn.commit()

            print(
                "BROWSER TERMINAL: "
                f"{portal} {portal_id} | purged",
                flush=True,
            )

            return {
                "database_status": "purged",
                "property_id": property_data["id"],
                "duplicate": True,
                "blacklisted": False,
                "blacklist_terms": [],
            }

        # Ein normal erreichbares Exposé hebt einen eventuell
        # alten Browser-Terminalevent für dieselbe ID wieder auf.
        clear_terminal_event(
            conn,
            portal,
            portal_id,
        )

        # ----------------------------------------------------
        # Immowelt:
        # generischen Telegram-Titel durch den echten
        # Exposé-Titel ersetzen und doppelte Ortsnamen
        # bereinigen.
        # ----------------------------------------------------

        title_changed = False
        location_changed = False

        if portal == "immowelt":

            old_title = str(
                property_data.get(
                    "title"
                )
                or ""
            ).strip()

            browser_title = (
                extract_immowelt_title(
                    page_text
                )
            )

            if (
                browser_title
                and browser_title
                != old_title
                and is_immowelt_preview_title(
                    old_title
                )
            ):

                property_data[
                    "title"
                ] = browser_title

                title_changed = True

            old_location = str(
                property_data.get(
                    "location"
                )
                or ""
            ).strip()

            clean_location = (
                normalize_immowelt_location(
                    old_location
                )
            )

            if (
                clean_location
                and clean_location
                != old_location
            ):

                property_data[
                    "location"
                ] = clean_location

                location_changed = True

        plot_area_from_browser = None
        plot_area_changed = False

        if portal == "immowelt":

            plot_area_from_browser = (
                extract_immowelt_plot_area(
                    page_text
                )
            )

            if (
                plot_area_from_browser
                is not None
            ):

                old_plot_area = (
                    property_data.get(
                        "plot_area"
                    )
                )

                try:
                    old_plot_area = (
                        float(old_plot_area)
                        if old_plot_area is not None
                        else None
                    )
                except (
                    TypeError,
                    ValueError
                ):
                    old_plot_area = None

                plot_area_changed = (
                    old_plot_area is None
                    or abs(
                        old_plot_area
                        - plot_area_from_browser
                    ) > 0.01
                )

                property_data[
                    "plot_area"
                ] = plot_area_from_browser

        price_from_browser = None
        price_changed = False

        if portal in (
            "immowelt",
            "immoscout24",
        ):

            price_from_browser = (
                extract_immowelt_price(
                    page_text
                )
            )

            if (
                price_from_browser
                is not None
            ):

                old_price = (
                    property_data.get(
                        "price"
                    )
                )

                try:
                    old_price = (
                        float(old_price)
                        if old_price is not None
                        else None
                    )
                except (
                    TypeError,
                    ValueError
                ):
                    old_price = None

                price_changed = (
                    old_price is None
                    or abs(
                        old_price
                        - price_from_browser
                    ) > 0.01
                )

                property_data[
                    "price"
                ] = price_from_browser

        blacklist_page_text = (
            blacklist_relevant_page_text(
                page_text,
                browser_url
            )
        )

        matches = find_blacklist_terms(
            property_data.get("title"),
            property_data.get("location"),
            property_data.get("url"),
            property_data.get("raw_text"),
            blacklist_page_text,
            browser_heading,
            browser_url,
        )

        conn.execute(
            """
            UPDATE properties
            SET
                browser_text = ?,
                browser_url = ?,
                browser_heading = ?,
                browser_enriched_at = ?
            WHERE id = ?
            """,
            (
                page_text,
                browser_url,
                browser_heading,
                enriched_at,
                property_data["id"],
            )
        )
        if title_changed:

            conn.execute(
                """
                UPDATE properties
                SET title = ?
                WHERE id = ?
                """,
                (
                    property_data["title"],
                    property_data["id"],
                )
            )

            print(
                "BROWSER TITLE: "
                f"{portal} "
                f"{portal_id} | "
                f"{old_title!r} -> "
                f"{property_data['title']!r}",
                flush=True
            )

        if location_changed:

            conn.execute(
                """
                UPDATE properties
                SET location = ?
                WHERE id = ?
                """,
                (
                    property_data["location"],
                    property_data["id"],
                )
            )

            print(
                "BROWSER LOCATION: "
                f"{portal} "
                f"{portal_id} | "
                f"{old_location!r} -> "
                f"{property_data['location']!r}",
                flush=True
            )

        if (
            plot_area_from_browser
            is not None
        ):

            conn.execute(
                """
                UPDATE properties
                SET plot_area = ?
                WHERE id = ?
                """,
                (
                    plot_area_from_browser,
                    property_data["id"],
                )
            )

            if plot_area_changed:

                print(
                    "BROWSER PLOT AREA: "
                    f"{portal} "
                    f"{portal_id} | "
                    f"{old_plot_area} -> "
                    f"{plot_area_from_browser:.0f} m²",
                    flush=True
                )

        if (
            price_from_browser
            is not None
        ):

            conn.execute(
                """
                UPDATE properties
                SET price = ?
                WHERE id = ?
                """,
                (
                    price_from_browser,
                    property_data["id"],
                )
            )

            if price_changed:

                print(
                    "BROWSER PRICE: "
                    f"{portal} "
                    f"{portal_id} | "
                    f"{old_price} -> "
                    f"{price_from_browser:.0f} €",
                    flush=True
                )

        if matches:

            record_terminal_event(
                conn,
                portal,
                portal_id,
                "blacklisted",
            )

            previous_score = property_data.get(
                "score"
            )

            previous_rating = property_data.get(
                "rating"
            )

            previous_is_ko = property_data.get(
                "is_ko"
            )

            previous_score_details = (
                property_data.get(
                    "score_details"
                )
            )

            # Wenn das Objekt bereits durch den Browser
            # geblacklistet war, den ursprünglichen Zustand
            # nicht mit dem Blacklist-Zustand überschreiben.
            try:
                current_details = json.loads(
                    previous_score_details
                    or "{}"
                )
            except Exception:
                current_details = {}

            if (
                previous_rating == "blacklisted"
                and current_details.get(
                    "source"
                ) == "browser"
            ):
                previous_score = (
                    current_details.get(
                        "previous_score"
                    )
                )

                previous_rating = (
                    current_details.get(
                        "previous_rating"
                    )
                )

                previous_is_ko = (
                    current_details.get(
                        "previous_is_ko",
                        0
                    )
                )

                previous_score_details = (
                    current_details.get(
                        "previous_score_details"
                    )
                )

            score_details = {
                "ko": True,
                "blacklisted": True,
                "source": "browser",
                "blacklist_terms": matches,
                "ko_reasons": [
                    f"Blacklist: {term}"
                    for term in matches
                ],

                # Zustand vor dem Browser-Blacklist-Treffer
                # sichern, damit er später automatisch
                # wiederhergestellt werden kann.
                "previous_score":
                    previous_score,

                "previous_rating":
                    previous_rating,

                "previous_is_ko":
                    previous_is_ko,

                "previous_score_details":
                    previous_score_details,
            }

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
                        score_details,
                        ensure_ascii=False
                    ),
                    property_data["id"],
                )
            )

            database_status = (
                "blacklisted"
            )

        else:

            restored = False

            # Nur automatisch freigeben, wenn die
            # Blacklist ursprünglich vom Browser kam.
            if (
                property_data.get("rating")
                == "blacklisted"
            ):
                try:
                    old_details = json.loads(
                        property_data.get(
                            "score_details"
                        )
                        or "{}"
                    )
                except Exception:
                    old_details = {}

                if (
                    old_details.get("source")
                    == "browser"
                ):
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
                            old_details.get(
                                "previous_score"
                            ),
                            old_details.get(
                                "previous_rating"
                            ),
                            old_details.get(
                                "previous_is_ko",
                                0
                            ),
                            old_details.get(
                                "previous_score_details"
                            ),
                            property_data["id"],
                        )
                    )

                    restored = True

            if restored:
                database_status = (
                    "unblacklisted"
                )
            else:
                database_status = (
                    "enriched"
                )

            # ------------------------------------------------
            # Immowelt-Bebaubarkeit aus Browsertext.
            #
            # Manuelle Entscheidungen bleiben erhalten,
            # weil classify_buildability() einen gesetzten
            # buildability-Wert zuerst auswertet.
            # ------------------------------------------------

            buildability_changed = False

            if (
                portal == "immowelt"
                and property_data.get(
                    "property_type"
                ) == "land"
            ):

                buildability_input = dict(
                    property_data
                )

                buildability_input[
                    "browser_text"
                ] = page_text

                buildability_result = (
                    classify_buildability(
                        buildability_input
                    )
                )

                old_class = (
                    property_data.get(
                        "buildability_class"
                    )
                )

                old_reason = (
                    property_data.get(
                        "buildability_reason"
                    )
                )

                old_allowed_raw = (
                    property_data.get(
                        "residential_building_allowed"
                    )
                )

                old_holiday_raw = (
                    property_data.get(
                        "holiday_area"
                    )
                )

                old_allowed = (
                    None
                    if old_allowed_raw is None
                    else bool(old_allowed_raw)
                )

                old_holiday = (
                    None
                    if old_holiday_raw is None
                    else bool(old_holiday_raw)
                )

                new_class = (
                    buildability_result.get(
                        "buildability_class"
                    )
                )

                new_reason = (
                    buildability_result.get(
                        "buildability_reason"
                    )
                )

                new_allowed = (
                    buildability_result.get(
                        "residential_building_allowed"
                    )
                )

                new_holiday = (
                    buildability_result.get(
                        "holiday_area",
                        old_holiday
                    )
                )

                buildability_changed = (
                    old_class != new_class
                    or old_reason != new_reason
                    or old_allowed != new_allowed
                    or old_holiday != new_holiday
                )

                property_data[
                    "buildability_class"
                ] = new_class

                property_data[
                    "buildability_reason"
                ] = new_reason

                property_data[
                    "residential_building_allowed"
                ] = new_allowed

                property_data[
                    "holiday_area"
                ] = new_holiday

                allowed_db = (
                    None
                    if new_allowed is None
                    else int(new_allowed)
                )

                holiday_db = (
                    None
                    if new_holiday is None
                    else int(new_holiday)
                )

                conn.execute(
                    """
                    UPDATE properties
                    SET
                        buildability_class = ?,
                        buildability_reason = ?,
                        residential_building_allowed = ?,
                        holiday_area = ?
                    WHERE id = ?
                    """,
                    (
                        new_class,
                        new_reason,
                        allowed_db,
                        holiday_db,
                        property_data["id"],
                    )
                )

                if buildability_changed:

                    print(
                        "BROWSER BUILDABILITY: "
                        f"{portal} "
                        f"{portal_id} | "
                        f"{old_class} -> "
                        f"{new_class} | "
                        f"{new_reason}",
                        flush=True
                    )

            # ------------------------------------------------
            # Energie aus dem einmal geöffneten Browser-Exposé.
            #
            # Finale/manuelle Werte bleiben erhalten. Ein offener
            # not_available_yet-Status darf später durch echte
            # Browserdaten ersetzt werden. Wenn bei einem bislang
            # ungeprüften Objekt gar nichts gefunden wird, gilt die
            # Energieprüfung als durchgeführt und wird als unknown
            # gespeichert (-7 im Scoring).
            # ------------------------------------------------

            energy_changed = False

            if property_data.get(
                "property_type"
            ) in (
                "house",
                "farm",
            ):

                energy_payload = (
                    energy_payload_from_browser(
                        property_data,
                        page_text,
                        energy_class_hint=data.get(
                            "energy_class_dom"
                        ),
                    )
                )

                if energy_payload is not None:

                    _, normalized_energy = (
                        update_property_energy(
                            conn,
                            portal,
                            portal_id,
                            energy_payload,
                        )
                    )

                    property_data.update(
                        normalized_energy
                    )

                    energy_changed = True

                    print(
                        "BROWSER ENERGY: "
                        f"{portal} "
                        f"{portal_id} | "
                        f"status="
                        f"{normalized_energy.get('energy_certificate_status')} | "
                        f"class="
                        f"{normalized_energy.get('energy_class')} | "
                        f"value="
                        f"{normalized_energy.get('energy_value_kwh')} | "
                        f"source="
                        f"{normalized_energy.get('energy_data_source')}",
                        flush=True
                    )

            # ------------------------------------------------
            # Explizites Portal-Zustandsfeld aus dem geöffneten
            # Browser-Exposé übernehmen.
            #
            # Beispiel Immowelt:
            #   Zustand der Immobilie
            #   gepflegt
            #
            # Es wird bewusst nur ein beschriftetes Portal-Feld
            # ausgewertet, nicht ein zufälliges Wort im freien
            # Beschreibungstext. Telegram-Manuellwerte sowie bereits
            # bekannte Zustände bleiben unangetastet.
            # ------------------------------------------------

            condition_changed = False

            if property_data.get(
                "property_type"
            ) in (
                "house",
                "farm",
            ):

                condition_payload = (
                    condition_payload_from_browser(
                        property_data,
                        page_text,
                    )
                )

                if condition_payload is not None:

                    property_data.update(
                        condition_payload
                    )

                    conn.execute(
                        """
                        UPDATE properties
                        SET
                            condition_class = ?,
                            condition_reason = ?,
                            condition_source = ?
                        WHERE id = ?
                        """,
                        (
                            condition_payload.get(
                                "condition_class"
                            ),
                            condition_payload.get(
                                "condition_reason"
                            ),
                            condition_payload.get(
                                "condition_source"
                            ),
                            property_data["id"],
                        )
                    )

                    condition_changed = True

                    print(
                        "BROWSER CONDITION: "
                        f"{portal} "
                        f"{portal_id} | "
                        f"class="
                        f"{condition_payload.get('condition_class')} | "
                        f"reason="
                        f"{condition_payload.get('condition_reason')} | "
                        f"source="
                        f"{condition_payload.get('condition_source')}",
                        flush=True
                    )

            effective_rating = (
                property_data.get(
                    "rating"
                )
            )

            if restored:
                effective_rating = (
                    old_details.get(
                        "previous_rating"
                    )
                )

            if (
                (
                    plot_area_changed
                    or buildability_changed
                )
                and property_data.get(
                    "property_type"
                ) == "land"
                and effective_rating
                not in (
                    "blacklisted",
                    "not_interested",
                )
            ):

                score_input = dict(
                    property_data
                )

                if (
                    plot_area_from_browser
                    is not None
                ):
                    score_input[
                        "plot_area"
                    ] = plot_area_from_browser

                try:

                    score_result = (
                        score_land(
                            score_input
                        )
                    )

                except Exception as exc:

                    print(
                        "BROWSER RESCORE ERROR: "
                        f"{portal} "
                        f"{portal_id} | "
                        f"{type(exc).__name__}: "
                        f"{exc}",
                        flush=True
                    )

                else:

                    old_score = (
                        property_data.get(
                            "score"
                        )
                    )

                    if restored:
                        old_score = (
                            old_details.get(
                                "previous_score"
                            )
                        )

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
                            score_result[
                                "score"
                            ],
                            score_result[
                                "rating"
                            ],
                            int(
                                score_result[
                                    "ko"
                                ]
                            ),
                            json.dumps(
                                score_result,
                                ensure_ascii=False
                            ),
                            property_data["id"],
                        )
                    )

                    print(
                        "BROWSER RESCORE: "
                        f"{portal} "
                        f"{portal_id} | "
                        f"{old_score} -> "
                        f"{score_result['score']} | "
                        f"{score_result['rating']}",
                        flush=True
                    )

                    if restored:
                        database_status = (
                            "unblacklisted_rescored"
                        )
                    else:
                        database_status = (
                            "rescored"
                        )

            if (
                (
                    price_changed
                    or plot_area_changed
                    or energy_changed
                    or condition_changed
                )
                and property_data.get(
                    "property_type"
                )
                in (
                    "house",
                    "farm",
                )
                and effective_rating
                not in (
                    "blacklisted",
                    "not_interested",
                    "offline",
                )
            ):

                score_input = dict(
                    property_data
                )

                if (
                    price_from_browser
                    is not None
                ):
                    score_input[
                        "price"
                    ] = price_from_browser

                if (
                    plot_area_from_browser
                    is not None
                ):
                    score_input[
                        "plot_area"
                    ] = plot_area_from_browser

                try:

                    score_result = (
                        score_house(
                            score_input
                        )
                    )

                except Exception as exc:

                    print(
                        "BROWSER HOUSE RESCORE ERROR: "
                        f"{portal} "
                        f"{portal_id} | "
                        f"{type(exc).__name__}: "
                        f"{exc}",
                        flush=True
                    )

                else:

                    old_score = (
                        property_data.get(
                            "score"
                        )
                    )

                    if restored:
                        old_score = (
                            old_details.get(
                                "previous_score"
                            )
                        )

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
                            score_result[
                                "score"
                            ],
                            score_result[
                                "rating"
                            ],
                            int(
                                score_result[
                                    "ko"
                                ]
                            ),
                            json.dumps(
                                score_result,
                                ensure_ascii=False
                            ),
                            property_data["id"],
                        )
                    )

                    print(
                        "BROWSER HOUSE RESCORE: "
                        f"{portal} "
                        f"{portal_id} | "
                        f"{old_score} -> "
                        f"{score_result['score']} | "
                        f"{score_result['rating']}",
                        flush=True
                    )

                    if restored:
                        database_status = (
                            "unblacklisted_rescored"
                        )
                    else:
                        database_status = (
                            "rescored"
                        )

        conn.commit()

        return {
            "database_status":
                database_status,

            "property_id":
                property_data["id"],

            "duplicate":
                True,

            "blacklisted":
                bool(matches),

            "blacklist_terms":
                matches,
        }

    finally:
        conn.close()


def update_database_with_retry(
    data,
    attempts=3,
    delay=0.75,
):

    attempts = max(
        1,
        int(attempts),
    )

    for attempt in range(
        1,
        attempts + 1,
    ):

        try:
            return update_database(
                data
            )

        except sqlite3.OperationalError as exc:

            locked = (
                "locked"
                in str(exc).casefold()
            )

            if (
                not locked
                or attempt >= attempts
            ):
                raise

            wait_seconds = (
                float(delay)
                * attempt
            )

            print(
                "DATABASE LOCK: retry "
                f"{attempt + 1}/{attempts} "
                f"in {wait_seconds:.2f}s",
                flush=True
            )

            time.sleep(
                wait_seconds
            )


class Handler(BaseHTTPRequestHandler):

    def send_json(
        self,
        status,
        data
    ):

        body = json.dumps(
            data,
            ensure_ascii=False
        ).encode("utf-8")

        self.send_response(
            status
        )

        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8"
        )

        self.send_header(
            "Content-Length",
            str(len(body))
        )

        self.send_header(
            "Access-Control-Allow-Origin",
            "*"
        )

        self.send_header(
            "Access-Control-Allow-Headers",
            (
                "Content-Type, "
                "X-Browser-Enrich-Token"
            )
        )

        self.end_headers()

        self.wfile.write(
            body
        )


    def do_OPTIONS(self):

        self.send_response(
            204
        )

        self.send_header(
            "Access-Control-Allow-Origin",
            "*"
        )

        self.send_header(
            "Access-Control-Allow-Methods",
            "POST, GET, OPTIONS"
        )

        self.send_header(
            "Access-Control-Allow-Headers",
            (
                "Content-Type, "
                "X-Browser-Enrich-Token"
            )
        )

        self.end_headers()


    def do_GET(self):

        if self.path == "/health":

            self.send_json(
                200,
                {
                    "ok": True,
                    "service":
                        "browser-enrich",
                }
            )

            return

        self.send_json(
            404,
            {
                "ok": False
            }
        )


    def do_POST(self):

        if self.path != "/enrich":

            self.send_json(
                404,
                {
                    "ok": False
                }
            )

            return

        expected_token = (
            load_token()
        )

        supplied_token = (
            self.headers.get(
                "X-Browser-Enrich-Token",
                ""
            )
        )

        if (
            not expected_token
            or supplied_token
            != expected_token
        ):

            self.send_json(
                403,
                {
                    "ok": False,
                    "error":
                        "invalid token",
                }
            )

            return

        try:

            content_length = int(
                self.headers.get(
                    "Content-Length",
                    "0"
                )
            )

        except ValueError:

            content_length = 0

        if (
            content_length <= 0
            or content_length > MAX_BODY
        ):

            self.send_json(
                413,
                {
                    "ok": False,
                    "error":
                        "invalid body size",
                }
            )

            return

        try:

            raw = self.rfile.read(
                content_length
            )

            data = json.loads(
                raw.decode(
                    "utf-8"
                )
            )

        except Exception as exc:

            self.send_json(
                400,
                {
                    "ok": False,
                    "error":
                        f"invalid json: {exc}",
                }
            )

            return

        portal = str(
            data.get("portal") or ""
        ).strip().lower()

        portal_id = str(
            data.get("portal_id") or ""
        ).strip()

        if portal not in (
            "immowelt",
            "immoscout24",
        ):

            self.send_json(
                400,
                {
                    "ok": False,
                    "error":
                        "unsupported portal",
                }
            )

            return

        if not portal_id:

            self.send_json(
                400,
                {
                    "ok": False,
                    "error":
                        "portal_id missing",
                }
            )

            return

        data["received_at"] = (
            datetime.now(
                timezone.utc
            ).isoformat()
        )

        INBOX_DIR.mkdir(
            parents=True,
            exist_ok=True
        )

        filename = (
            f"{safe_filename(portal)}-"
            f"{safe_filename(portal_id)}"
            f".json"
        )

        target = (
            INBOX_DIR
            / filename
        )

        fd, tmpname = (
            tempfile.mkstemp(
                prefix=
                    ".browser-enrich-",
                dir=INBOX_DIR,
            )
        )

        try:

            with os.fdopen(
                fd,
                "w",
                encoding="utf-8"
            ) as handle:

                json.dump(
                    data,
                    handle,
                    ensure_ascii=False,
                    indent=2
                )

                handle.write(
                    "\n"
                )

            os.replace(
                tmpname,
                target
            )

        finally:

            if os.path.exists(
                tmpname
            ):
                os.unlink(
                    tmpname
                )

        try:

            database_result = (
                update_database_with_retry(
                    data
                )
            )

        except Exception as exc:

            print(
                "DATABASE ERROR:",
                type(exc).__name__,
                str(exc),
                flush=True
            )

            self.send_json(
                500,
                {
                    "ok": False,
                    "error":
                        "database update failed",
                }
            )

            return

        print(
            "BROWSER ENRICH:",
            portal,
            portal_id,
            "|",
            len(
                data.get(
                    "page_text"
                ) or ""
            ),
            "chars",
            "|",
            database_result[
                "database_status"
            ],
            "|",
            ",".join(
                database_result.get(
                    "blacklist_terms",
                    []
                )
            ),
            flush=True
        )

        response = {
            "ok": True,
            "portal": portal,
            "portal_id": portal_id,
            "stored": filename,
        }

        response.update(
            database_result
        )

        self.send_json(
            200,
            response
        )


    def log_message(
        self,
        format,
        *args
    ):

        print(
            f"{self.client_address[0]} "
            f"{format % args}",
            flush=True
        )


if __name__ == "__main__":

    # Der Host-Dienst läuft außerhalb der Docker-Container und
    # verwendet deshalb den Projektpfad unter /opt. Diese globale
    # Config-Umschaltung darf erst beim echten Prozessstart passieren.
    # Beim bloßen Import (z. B. in Docker-Tests) muss /config erhalten
    # bleiben, sonst beeinflusst browser_enrich_server andere Module.
    SCORE_CONFIG.config_dir = str(
        BASE_DIR / "config"
    )

    if not TOKEN_FILE.exists():

        raise SystemExit(
            "Token file missing: "
            f"{TOKEN_FILE}"
        )

    if not DB_PATH.exists():

        raise SystemExit(
            "Database missing: "
            f"{DB_PATH}"
        )

    INBOX_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    ensure_database_columns()

    server = ThreadingHTTPServer(
        (
            HOST,
            PORT
        ),
        Handler
    )

    print(
        "browser-enrich listening on "
        f"{HOST}:{PORT}",
        flush=True
    )

    server.serve_forever()
