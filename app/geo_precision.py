import json
import re


GEO_PRECISION_EXACT = "exact"
GEO_PRECISION_LOCALITY = "locality"
GEO_PRECISION_MISSING = "missing"

GEO_INCOMPLETE_REASONS = {
    "Freilage/Nachbarn",
    "Lärm",
    "Wasser",
}

GEO_DERIVED_FIELDS = (
    "latitude",
    "longitude",
    "geocode_query",
    "geocoded_at",
    "geocode_source_location",
    "water_distance_km",
    "water_class",
    "water_width_lower_m",
    "water_width_upper_m",
    "water_score",
    "neighbour_class",
    "nearest_building_m",
    "buildings_50m",
    "buildings_100m",
    "buildings_250m",
    "buildings_500m",
    "neighbour_checked_at",
    "rail_lden",
    "rail_lnight",
    "rail_distance_m",
    "rail_annual_traffic",
    "road_lden",
    "road_lnight",
    "road_noise_source",
    "air_lden",
    "air_lnight",
    "air_noise_source",
    "noise_checked_at",
)

_MISSING_LOCATION_VALUES = {
    "",
    "-",
    "--",
    "?",
    "unbekannt",
    "ort unbekannt",
    "keine angabe",
    "k. a.",
    "k.a.",
    "n/a",
}

_STREET_SUFFIX = (
    r"(?:straße|str\.?|weg|allee|platz|gasse|ring|damm|"
    r"ufer|chaussee|stieg|pfad|markt|graben|zeile)"
)

_STREET_WITH_NUMBER = re.compile(
    rf"\b[\wÄÖÜäöüß.'’ -]*{_STREET_SUFFIX}"
    r"\s+\d{1,4}[a-zA-Z]?"
    r"(?:\s*[-/]\s*\d{1,4}[a-zA-Z]?)?\b",
    re.IGNORECASE,
)

_NAMED_STREET_WITH_NUMBER = re.compile(
    r"\b(?:am|an\s+der|auf\s+dem|im|in\s+der)\s+"
    r"[\wÄÖÜäöüß.'’ -]{2,50}\s+"
    r"\d{1,4}[a-zA-Z]?\b",
    re.IGNORECASE,
)

_LEADING_ADDRESS_WITH_NUMBER = re.compile(
    r"^(?P<label>[^,\n]{2,80}?[A-Za-zÄÖÜäöüß])"
    r"\s+\d{1,4}\s*[a-zA-Z]?"
    r"(?:\s*[-/]\s*\d{1,4}\s*[a-zA-Z]?)?"
    r"(?=\s*(?:,|$))",
    re.IGNORECASE,
)

_NON_ADDRESS_LABELS = re.compile(
    r"^(?:flurstück|flurstueck|flur|gemarkung|parzelle|"
    r"grundstück|grundstueck|bauplatz|bauland|los|"
    r"postleitzahl|plz|ortsteil|ot)\b",
    re.IGNORECASE,
)


def has_manual_coordinates(property_data):

    return (
        property_data.get("manual_latitude") is not None
        and property_data.get("manual_longitude") is not None
    )


def location_has_exact_address(location):

    text = str(location or "").strip()

    if not text:
        return False

    leading_match = _LEADING_ADDRESS_WITH_NUMBER.search(
        text
    )

    if leading_match:
        leading_label = leading_match.group(
            "label"
        ).strip()

        if _NON_ADDRESS_LABELS.search(
            leading_label
        ):
            return False

    if (
        _STREET_WITH_NUMBER.search(text)
        or _NAMED_STREET_WITH_NUMBER.search(text)
    ):
        return True

    # Ländliche Adressen tragen oft keinen klassischen
    # Straßensuffix, z. B. "Tümplingsgrund 1" oder
    # "Altköpsen 17". Die Hausnummer muss im ersten
    # Adressbestandteil stehen; Flurstücks- und
    # Bauplatznummern gelten ausdrücklich nicht als Adresse.
    if not leading_match:
        return False

    return True


def location_has_usable_locality(location):

    text = " ".join(
        str(location or "").strip().casefold().split()
    )

    if text in _MISSING_LOCATION_VALUES:
        return False

    if re.search(r"\b\d{5}\b", text):
        return True

    return bool(
        re.search(
            r"[a-zäöüß]{2,}",
            text,
            re.IGNORECASE,
        )
    )


def classify_geo_precision(property_data):

    if has_manual_coordinates(property_data):
        return GEO_PRECISION_EXACT

    location = property_data.get("location")

    if location_has_exact_address(location):
        return GEO_PRECISION_EXACT

    if location_has_usable_locality(location):
        return GEO_PRECISION_LOCALITY

    return GEO_PRECISION_MISSING


def effective_geo_precision(property_data):

    explicit = str(
        property_data.get("geo_precision")
        or ""
    ).strip().lower()

    if explicit in {
        GEO_PRECISION_EXACT,
        GEO_PRECISION_LOCALITY,
        GEO_PRECISION_MISSING,
    }:
        return explicit

    if property_data.get("location") is not None:
        return classify_geo_precision(
            property_data
        )

    # Compatibility for focused scoring calls and legacy test
    # fixtures which contain verified coordinates but no copy
    # of the portal location. Persisted production rows are
    # classified from their location before scoring.
    if (
        property_data.get("latitude") is not None
        and property_data.get("longitude") is not None
    ):
        return GEO_PRECISION_EXACT

    return classify_geo_precision(
        property_data
    )


def clear_geo_derived_data(property_data):

    for field in GEO_DERIVED_FIELDS:
        property_data[field] = None

    return property_data


def normalize_geo_precision(property_data):

    precision = classify_geo_precision(
        property_data
    )

    property_data["geo_precision"] = precision

    if precision != GEO_PRECISION_EXACT:
        clear_geo_derived_data(
            property_data
        )

    return property_data


def score_details_dict(value):

    if isinstance(value, dict):
        return value

    if not value:
        return {}

    try:
        result = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}

    return result if isinstance(result, dict) else {}


def provisional_score_range(property_data):

    details = score_details_dict(
        property_data.get("score_details")
    )

    if not details.get("provisional"):
        return None

    minimum = details.get("score_min")
    maximum = details.get("score_max")

    if minimum is None or maximum is None:
        return None

    try:
        minimum = int(minimum)
        maximum = int(maximum)
    except (TypeError, ValueError):
        return None

    return min(minimum, maximum), max(minimum, maximum)


def conservative_score(property_data):

    score = property_data.get("score")

    if score is not None:
        try:
            return int(score)
        except (TypeError, ValueError):
            return -1

    score_range = provisional_score_range(
        property_data
    )

    if score_range is None:
        return -1

    return score_range[0]
