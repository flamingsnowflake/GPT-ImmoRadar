import json
import re
import sqlite3
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from monitor import DB_PATH, enrich_property
from property_types import is_house_type
from scoring import score_house, score_land


def parse_coordinates(value):

    if not value:
        return None

    numbers = re.findall(
        r"[-+]?\d+(?:[.,]\d+)?",
        str(value),
    )

    if len(numbers) != 2:
        return None

    try:

        latitude = float(
            numbers[0].replace(",", ".")
        )

        longitude = float(
            numbers[1].replace(",", ".")
        )

    except ValueError:
        return None

    if not (
        -90.0 <= latitude <= 90.0
        and -180.0 <= longitude <= 180.0
    ):
        return None

    return (
        latitude,
        longitude,
    )


def geocode_manual_address(value):

    address = (
        str(value or "")
        .strip()
    )

    if not address:
        return None

    params = urllib.parse.urlencode(
        {
            "q": address,
            "format": "jsonv2",
            "limit": 1,
            "countrycodes": "de",
            "accept-language": "de",
        }
    )

    url = (
        "https://nominatim.openstreetmap.org/"
        f"search?{params}"
    )

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent":
                "immobilien-monitor/1.0 "
                "(manual address geocoding)",
            "Accept": "application/json",
        },
    )

    with urllib.request.urlopen(
        request,
        timeout=20,
    ) as response:

        data = json.loads(
            response.read().decode(
                "utf-8"
            )
        )

    if not data:
        return None

    result = data[0]

    try:

        latitude = float(
            result["lat"]
        )

        longitude = float(
            result["lon"]
        )

    except (
        KeyError,
        TypeError,
        ValueError,
    ):
        return None

    if not (
        -90.0 <= latitude <= 90.0
        and
        -180.0 <= longitude <= 180.0
    ):
        return None

    display_name = (
        result.get("display_name")
        or address
    ).strip()

    return (
        latitude,
        longitude,
        display_name,
    )


def resolve_manual_location(value):

    value = (
        str(value or "")
        .strip()
    )

    parsed = parse_coordinates(
        value
    )

    if parsed is not None:

        latitude, longitude = (
            parsed
        )

        return {
            "latitude": latitude,
            "longitude": longitude,
            "source": "telegram",
            "display_name": None,
        }

    geocoded = geocode_manual_address(
        value
    )

    if geocoded is None:
        return None

    (
        latitude,
        longitude,
        display_name,
    ) = geocoded

    return {
        "latitude": latitude,
        "longitude": longitude,
        "source": (
            "Adresse: "
            + value[:400]
        ),
        "display_name":
            display_name,
    }


def coordinates_keyboard(
    portal_id,
    property_type,
    number,
    manual=False,
):

    rows = [
        [
            {
                "text": "✏️ Manuell setzen",
                "callback_data":
                    f"coords_set:{portal_id}:"
                    f"{property_type}:{number}",
            }
        ]
    ]

    if manual:

        rows.append(
            [
                {
                    "text": "♻️ Automatik verwenden",
                    "callback_data":
                        f"coords_auto:{portal_id}:"
                        f"{property_type}:{number}",
                }
            ]
        )

    rows.append(
        [
            {
                "text": "⬅️ Zurück",
                "callback_data":
                    f"back:{portal_id}:"
                    f"{property_type}:{number}",
            }
        ]
    )

    return {
        "inline_keyboard": rows
    }


def get_coordinate_status(portal_id):

    conn = sqlite3.connect(
        DB_PATH
    )

    conn.row_factory = (
        sqlite3.Row
    )

    row = conn.execute(
        """
        SELECT
            title,
            property_type,
            latitude,
            longitude,
            manual_latitude,
            manual_longitude,
            manual_coordinates_set_at,
            manual_coordinates_source
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

        return (
            f"❌ Objekt {portal_id} "
            "nicht gefunden.",
            False,
        )

    manual = (
        row["manual_latitude"] is not None
        and row["manual_longitude"] is not None
    )

    if manual:

        latitude = (
            row["manual_latitude"]
        )

        longitude = (
            row["manual_longitude"]
        )

        source = "MANUELL"

        if row[
            "manual_coordinates_source"
        ]:
            source += (
                " / "
                + row[
                    "manual_coordinates_source"
                ]
            )

    else:

        latitude = row["latitude"]
        longitude = row["longitude"]

        source = "automatisch"

    lines = [
        "📍 Koordinaten",
        "",
        row["title"] or portal_id,
        f"ID: {portal_id}",
        "",
    ]

    if (
        latitude is not None
        and longitude is not None
    ):

        lines.append(
            f"{latitude:.6f}, "
            f"{longitude:.6f}"
        )

    else:

        lines.append(
            "keine Koordinaten vorhanden"
        )

    lines.extend(
        [
            f"Quelle: {source}",
        ]
    )

    if (
        manual
        and row[
            "manual_coordinates_set_at"
        ]
    ):

        lines.append(
            "Manuell gesetzt: "
            + row[
                "manual_coordinates_set_at"
            ]
        )

    return (
        "\n".join(lines),
        manual,
    )


def _coordinate_reset_sql():

    return """
        water_distance_km = NULL,
        water_class = NULL,
        water_width_lower_m = NULL,
        water_width_upper_m = NULL,
        water_score = NULL,

        neighbour_class = NULL,
        nearest_building_m = NULL,
        buildings_100m = NULL,
        buildings_250m = NULL,
        buildings_500m = NULL,
        neighbour_checked_at = NULL,

        rail_lden = NULL,
        rail_lnight = NULL,
        rail_distance_m = NULL,
        rail_annual_traffic = NULL,

        road_lden = NULL,
        road_lnight = NULL,
        road_noise_source = NULL,

        air_lden = NULL,
        air_lnight = NULL,
        air_noise_source = NULL,

        noise_checked_at = NULL
    """


def _recalculate_after_coordinate_change(
    conn,
    property_id,
):

    row = conn.execute(
        """
        SELECT *
        FROM properties
        WHERE id = ?
        """,
        (
            property_id,
        )
    ).fetchone()

    if not row:
        raise RuntimeError(
            "Objekt nach UPDATE nicht gefunden"
        )

    property_data = dict(row)

    property_data = enrich_property(
        conn,
        property_data,
    )

    property_type = (
        property_data.get(
            "property_type"
        )
        or "unknown"
    )

    if property_type == "land":

        score_result = score_land(
            property_data
        )

    elif is_house_type(
        property_type
    ):

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

    fields = {
        "latitude": property_data.get("latitude"),
        "longitude": property_data.get("longitude"),
        "geocode_query": property_data.get("geocode_query"),
        "geocoded_at": property_data.get("geocoded_at"),
        "geocode_source_location": property_data.get("geocode_source_location"),
        "water_distance_km": property_data.get("water_distance_km"),
        "water_class": property_data.get("water_class"),
        "water_width_lower_m": property_data.get("water_width_lower_m"),
        "water_width_upper_m": property_data.get("water_width_upper_m"),
        "water_score": property_data.get("water_score"),
        "neighbour_class": property_data.get("neighbour_class"),
        "nearest_building_m": property_data.get("nearest_building_m"),
        "buildings_100m": property_data.get("buildings_100m"),
        "buildings_250m": property_data.get("buildings_250m"),
        "buildings_500m": property_data.get("buildings_500m"),
        "neighbour_checked_at": property_data.get("neighbour_checked_at"),
        "rail_lden": property_data.get("rail_lden"),
        "rail_lnight": property_data.get("rail_lnight"),
        "rail_distance_m": property_data.get("rail_distance_m"),
        "rail_annual_traffic": property_data.get("rail_annual_traffic"),
        "road_lden": property_data.get("road_lden"),
        "road_lnight": property_data.get("road_lnight"),
        "road_noise_source": property_data.get("road_noise_source"),
        "air_lden": property_data.get("air_lden"),
        "air_lnight": property_data.get("air_lnight"),
        "air_noise_source": property_data.get("air_noise_source"),
        "noise_checked_at": property_data.get("noise_checked_at"),
        "score": property_data.get("score"),
        "rating": property_data.get("rating"),
        "is_ko": property_data.get("is_ko", 0),
        "score_details": (
            json.dumps(
                property_data["score_details"],
                ensure_ascii=False,
            )
            if property_data.get("score_details") is not None
            else None
        ),
    }

    assignments = ", ".join(
        f"{column} = ?"
        for column in fields
    )

    values = list(
        fields.values()
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

    return property_data


def set_manual_coordinates(
    portal_id,
    latitude,
    longitude,
    source="telegram",
):

    conn = sqlite3.connect(
        DB_PATH
    )

    conn.row_factory = (
        sqlite3.Row
    )

    row = conn.execute(
        """
        SELECT
            id,
            title
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
            "nicht gefunden."
        )

    now = datetime.now(
        timezone.utc
    ).isoformat()

    reset_sql = (
        _coordinate_reset_sql()
    )

    conn.execute(
        f"""
        UPDATE properties
        SET
            manual_latitude = ?,
            manual_longitude = ?,
            manual_coordinates_set_at = ?,
            manual_coordinates_source = ?,

            latitude = ?,
            longitude = ?,
            geocode_query = 'MANUAL',
            geocoded_at = ?,
            geocode_source_location = location,

            {reset_sql}
        WHERE id = ?
        """,
        (
            latitude,
            longitude,
            now,
            source,
            latitude,
            longitude,
            now,
            row["id"],
        )
    )

    conn.commit()

    try:

        p = _recalculate_after_coordinate_change(
            conn,
            row["id"],
        )

    except Exception as exc:

        conn.close()

        return (
            "⚠️ Koordinaten gespeichert, "
            "Neuberechnung fehlgeschlagen\n\n"
            f"{latitude:.6f}, "
            f"{longitude:.6f}\n\n"
            f"{type(exc).__name__}: {exc}"
        )

    conn.close()

    lines = [
        "✅ Manuelle Koordinaten gesetzt",
        "",
        row["title"] or portal_id,
        f"ID: {portal_id}",
        "",
        f"📍 {latitude:.6f}, "
        f"{longitude:.6f}",
        "",
        "Wasser, Nachbarn und Lärm "
        "wurden neu berechnet.",
    ]

    if p.get("score") is not None:

        lines.append(
            f"Score: {p['score']}/100"
        )

        lines.append(
            f"Status: {p.get('rating')}"
        )

    return "\n".join(lines)


def clear_manual_coordinates(
    portal_id,
):

    conn = sqlite3.connect(
        DB_PATH
    )

    conn.row_factory = (
        sqlite3.Row
    )

    row = conn.execute(
        """
        SELECT
            id,
            title
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
            "nicht gefunden."
        )

    reset_sql = (
        _coordinate_reset_sql()
    )

    conn.execute(
        f"""
        UPDATE properties
        SET
            manual_latitude = NULL,
            manual_longitude = NULL,
            manual_coordinates_set_at = NULL,
            manual_coordinates_source = NULL,

            latitude = NULL,
            longitude = NULL,
            geocode_query = NULL,
            geocoded_at = NULL,
            geocode_source_location = NULL,

            {reset_sql}
        WHERE id = ?
        """,
        (
            row["id"],
        )
    )

    conn.commit()

    try:

        p = _recalculate_after_coordinate_change(
            conn,
            row["id"],
        )

    except Exception as exc:

        conn.close()

        return (
            "⚠️ Manueller Override entfernt, "
            "automatische Neuberechnung "
            "fehlgeschlagen\n\n"
            f"{type(exc).__name__}: {exc}"
        )

    conn.close()

    lines = [
        "♻️ Automatische Koordinaten aktiviert",
        "",
        row["title"] or portal_id,
        f"ID: {portal_id}",
    ]

    if (
        p.get("latitude") is not None
        and p.get("longitude") is not None
    ):

        lines.extend(
            [
                "",
                "📍 "
                f"{p['latitude']:.6f}, "
                f"{p['longitude']:.6f}",
            ]
        )

    lines.extend(
        [
            "",
            "Wasser, Nachbarn und Lärm "
            "wurden neu berechnet.",
        ]
    )

    if p.get("score") is not None:

        lines.append(
            f"Score: {p['score']}/100"
        )

        lines.append(
            f"Status: {p.get('rating')}"
        )

    return "\n".join(lines)
