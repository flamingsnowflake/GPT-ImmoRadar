import math

from config_loader import CONFIG
from house_budget import house_costs
from geo_precision import (
    GEO_INCOMPLETE_REASONS,
    GEO_PRECISION_LOCALITY,
    GEO_PRECISION_MISSING,
    clear_geo_derived_data,
    effective_geo_precision,
)


SCORE_CEILING = 110


def price_points(price, config):

    if price is None:
        return 0

    for bracket in config["brackets"]:

        maximum = bracket.get("max")

        if maximum is None:
            return bracket["points"]

        if price <= maximum:
            return bracket["points"]

    return 0


def plot_points(plot_area, config):

    if plot_area is None:
        return 0

    for bracket in config["brackets"]:

        minimum = bracket.get("min")

        if plot_area >= minimum:
            return bracket["points"]

    return 0


def water_points(distance_km, config):

    if distance_km is None:
        return 0

    for bracket in config["brackets"]:

        maximum = bracket.get("max_km")

        if maximum is None:
            return bracket["points"]

        if distance_km <= maximum:
            return bracket["points"]

    return 0


def classify_score(score, thresholds):

    if score >= thresholds["dream"]:
        return "dream"

    if score >= thresholds["very_interesting"]:
        return "very_interesting"

    if score >= thresholds["interesting"]:
        return "interesting"

    if score >= thresholds["archive"]:
        return "archive"

    return "low"


def _round_score(value):

    return int(float(value) + 0.5)


def _distance_km(latitude, longitude, target_latitude, target_longitude):

    radius_km = 6371.0088
    latitude_1 = math.radians(float(latitude))
    latitude_2 = math.radians(float(target_latitude))
    latitude_delta = latitude_2 - latitude_1
    longitude_delta = math.radians(
        float(target_longitude) - float(longitude)
    )

    haversine = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(latitude_1)
        * math.cos(latitude_2)
        * math.sin(longitude_delta / 2) ** 2
    )

    return radius_km * 2 * math.atan2(
        math.sqrt(haversine),
        math.sqrt(max(0.0, 1.0 - haversine)),
    )


def location_weighting_details(base_score, property_data, config):

    if not config or not config.get("enabled"):
        return {
            "score": int(base_score),
            "base_score": int(base_score),
            "location_weighting_applied": False,
        }

    override = property_data.get(
        "_proximity_score_override"
    )

    latitude = property_data.get("manual_latitude")
    longitude = property_data.get("manual_longitude")

    if latitude is None or longitude is None:
        latitude = property_data.get("latitude")
        longitude = property_data.get("longitude")

    if override is None and (
        latitude is None or longitude is None
    ):
        return None

    reference_name = str(
        config.get("reference_name") or "Referenzort"
    )
    max_distance_km = float(
        config.get("max_distance_km", 100.0)
    )
    base_weight = float(
        config.get("existing_score_weight", 0.8)
    )
    proximity_weight = float(
        config.get("proximity_score_weight", 0.3)
    )
    if max_distance_km <= 0:
        raise ValueError(
            "max_distance_km must be positive"
        )

    if (
        base_weight < 0
        or proximity_weight < 0
    ):
        raise ValueError(
            "preference score values must not be negative"
        )

    if not math.isclose(
        base_weight + proximity_weight,
        1.0,
        abs_tol=1e-9,
    ):
        raise ValueError(
            "location weighting percentages must add up to 100"
        )

    if override is None:
        distance_km = _distance_km(
            latitude,
            longitude,
            config["latitude"],
            config["longitude"],
        )
        proximity_score = max(
            0.0,
            min(
                100.0,
                100.0
                * (1.0 - distance_km / max_distance_km),
            ),
        )
    else:
        distance_km = None
        proximity_score = max(
            0.0,
            min(100.0, float(override)),
        )

    score = _round_score(
        float(base_score) * base_weight
        + proximity_score * proximity_weight
    )

    return {
        "score": max(0, min(SCORE_CEILING, score)),
        "base_score": int(base_score),
        "location_weighting_applied": True,
        "location_reference": reference_name,
        "distance_to_reference_km": (
            None
            if distance_km is None
            else round(distance_km, 3)
        ),
        "proximity_score": round(proximity_score, 3),
        "existing_score_weight": base_weight,
        "proximity_score_weight": proximity_weight,
    }


def _location_reason(details):

    reference = details["location_reference"]
    distance = details["distance_to_reference_km"]
    proximity = details["proximity_score"]
    base_percent = details["existing_score_weight"] * 100
    proximity_percent = details["proximity_score_weight"] * 100

    if distance is None:
        return (
            f"Entfernung zu {reference}: "
            f"Nähe {proximity:.1f}/100 (vorläufig)"
        )

    return (
        f"Entfernung zu {reference}: {distance:.1f} km, "
        f"Nähe {proximity:.1f}/100; "
        f"Gewichteter {reference}-Score: "
        f"{base_percent:.0f} % × {details['base_score']} + "
        f"{proximity_percent:.0f} % × {proximity:.1f} "
        f"= {details['score']}"
    )


def _location_incomplete_reason(config):

    reference = str(
        (config or {}).get("reference_name")
        or "Referenzort"
    )
    return f"Entfernung zu {reference}"


OHNE_MAKLER_PRICE_DISCOUNT_PERCENT = 3.0
OHNE_MAKLER_MIN_SCORE_BONUS = 3


def _is_ohne_makler_offer(property_data):

    portal = str(
        property_data.get("portal")
        or ""
    ).strip().casefold()

    normalized_portal = (
        portal
        .replace("_", "-")
        .replace(" ", "-")
    )

    url = str(
        property_data.get("url")
        or ""
    ).strip().casefold()

    return (
        normalized_portal in {
            "ohne-makler",
            "ohnemakler",
            "ohne-makler.net",
        }
        or "ohne-makler.net" in url
    )


def _ohne_makler_price_effect(
    property_data,
    purchase_price,
    price_config,
    surcharge=0,
):

    if (
        purchase_price is None
        or not _is_ohne_makler_offer(
            property_data
        )
    ):
        return {
            "applies": False,
            "discounted_purchase_price": purchase_price,
            "discounted_effective_price": (
                None
                if purchase_price is None
                else float(purchase_price) + float(surcharge)
            ),
            "bonus_points": 0,
            "bracket_gain": 0,
        }

    purchase_price = float(
        purchase_price
    )

    surcharge = float(
        surcharge
    )

    discounted_purchase_price = (
        purchase_price
        * (
            1.0
            - OHNE_MAKLER_PRICE_DISCOUNT_PERCENT
            / 100.0
        )
    )

    base_effective_price = (
        purchase_price
        + surcharge
    )

    discounted_effective_price = (
        discounted_purchase_price
        + surcharge
    )

    base_points = price_points(
        base_effective_price,
        price_config,
    )

    discounted_points = price_points(
        discounted_effective_price,
        price_config,
    )

    bracket_gain = max(
        0,
        int(discounted_points)
        - int(base_points),
    )

    bonus_points = max(
        OHNE_MAKLER_MIN_SCORE_BONUS,
        bracket_gain,
    )

    return {
        "applies": True,
        "discounted_purchase_price":
            discounted_purchase_price,
        "discounted_effective_price":
            discounted_effective_price,
        "bonus_points": bonus_points,
        "bracket_gain": bracket_gain,
    }


# ------------------------------------------------------------
# Traffic noise
#
# Lärm bleibt ein Bonus/Malus auf dem bestehenden
# 100-Punkte-Score.
#
# Grundstücke werden bewusst deutlich strenger bewertet als
# bestehende Häuser: Bei einem Neubau lässt sich ein schlechter
# Standort später nicht mehr korrigieren.
# ------------------------------------------------------------

NOISE_RULES = {

    "house": {

        "cap": -25,

        "rail": {
            "ko_lden": 75,
            "ko_lnight": 65,

            "lden": (
                (70, -14),
                (65, -9),
                (60, -5),
                (55, -2),
            ),

            "lnight": (
                (60, -14),
                (55, -9),
                (50, -5),
                (45, -2),
            ),
        },

        "road": {
            "ko_lden": 75,
            "ko_lnight": 65,

            "lden": (
                (70, -14),
                (65, -9),
                (60, -5),
                (55, -2),
            ),

            "lnight": (
                (60, -14),
                (55, -9),
                (50, -5),
            ),
        },

        "air": {
            "ko_lden": 65,
            "ko_lnight": 60,

            "lden": (
                (60, -16),
                (55, -10),
                (50, -5),
            ),

            "lnight": (
                (55, -17),
                (50, -11),
                (45, -6),
            ),
        },
    },

    "land": {

        "cap": -30,

        "rail": {
            "ko_lden": 70,
            "ko_lnight": 60,

            "lden": (
                (65, -18),
                (60, -10),
                (55, -5),
            ),

            "lnight": (
                (55, -18),
                (50, -11),
                (45, -6),
            ),
        },

        "road": {
            "ko_lden": 70,
            "ko_lnight": 60,

            "lden": (
                (65, -18),
                (60, -12),
                (55, -6),
            ),

            "lnight": (
                (55, -18),
                (50, -12),
            ),
        },

        "air": {
            "ko_lden": 60,
            "ko_lnight": 55,

            "lden": (
                (55, -20),
                (50, -10),
            ),

            "lnight": (
                (50, -22),
                (45, -12),
            ),
        },
    },
}


NOISE_SOURCE_LABELS = {
    "rail": "Schiene",
    "road": "Straße",
    "air": "Flug",
}


NOISE_KO_LABELS = {
    "rail": "Schienenlärm",
    "road": "Straßenlärm",
    "air": "Fluglärm",
}


def _noise_band(value, kind):

    if value is None:
        return None

    value = int(value)

    if kind == "lden" and value >= 75:
        return "≥75"

    if kind == "lnight" and value >= 70:
        return "≥70"

    return f"{value}-{value + 4}"


def _noise_penalty_for_value(
    value,
    brackets,
):

    if value is None:
        return 0

    value = float(value)

    for minimum, penalty in brackets:

        if value >= minimum:
            return penalty

    return 0


UNMAPPED_RAIL_REVIEW_DISTANCE_M = 500.0


def _unmapped_nearby_rail_reason(
    property_data,
):

    rail_distance = property_data.get(
        "rail_distance_m"
    )

    rail_lden = property_data.get(
        "rail_lden"
    )

    rail_lnight = property_data.get(
        "rail_lnight"
    )

    if rail_distance is None:
        return None

    try:
        rail_distance = float(
            rail_distance
        )
    except (TypeError, ValueError):
        return None

    # Es existiert eine Bahn in relevanter Nähe,
    # aber keine kartierte EBA-Isophone am Objekt.
    #
    # Das darf nicht als "ruhig" interpretiert werden.
    if (
        rail_distance
        <= UNMAPPED_RAIL_REVIEW_DISTANCE_M
        and rail_lden is None
        and rail_lnight is None
    ):

        annual_traffic = property_data.get(
            "rail_annual_traffic"
        )

        text = (
            "Bahn "
            f"{rail_distance:.0f} m entfernt, "
            "aber keine kartierte "
            "EBA-Lärmisophone"
        )

        if annual_traffic is not None:

            try:

                annual_traffic = float(
                    annual_traffic
                )

                trains_per_day = (
                    annual_traffic / 365.0
                )

                text += (
                    "; "
                    f"{annual_traffic:.0f} Züge/Jahr "
                    f"(~{trains_per_day:.1f}/Tag)"
                )

            except (TypeError, ValueError):
                pass

        return text

    return None


def _rail_fallback_penalty(
    property_data,
    object_type,
):
    """
    Konservativer Ersatzwert für Bahnstrecken,
    wenn die EBA-Prüfung abgeschlossen ist,
    aber keine kartierte Isophone vorhanden ist.

    WICHTIG:
    - kartierte LDEN/LNight-Werte haben immer Vorrang
    - nur bei vorhandener Entfernung UND Zugzahl
    - Ersatzwert erzeugt niemals automatisch ein KO
    """

    if not property_data.get(
        "noise_checked_at"
    ):
        return None

    # Kartierte EBA-Werte haben immer Vorrang.
    if (
        property_data.get("rail_lden")
        is not None
        or property_data.get("rail_lnight")
        is not None
    ):
        return None

    distance_value = property_data.get(
        "rail_distance_m"
    )

    traffic_value = property_data.get(
        "rail_annual_traffic"
    )

    if (
        distance_value is None
        or traffic_value is None
    ):
        return None

    try:
        distance = float(
            distance_value
        )

        annual_traffic = float(
            traffic_value
        )

    except (
        TypeError,
        ValueError,
    ):
        return None

    if (
        distance < 0
        or distance > 1000
        or annual_traffic < 0
    ):
        return None

    # --------------------------------------------------------
    # Ersatzmatrix für bestehende Häuser
    #
    # Distanz ist die zweite Dimension innerhalb der
    # Verkehrsmenge.
    #
    # Wimmelburg:
    #   18.738 Züge/Jahr
    #   360 m
    #   => -5
    # --------------------------------------------------------

    if annual_traffic <= 0:

        bands = (
            (1000, 0),
        )

    elif annual_traffic < 1000:

        bands = (
            (50, -2),
            (100, -1),
            (1000, 0),
        )

    elif annual_traffic < 5000:

        bands = (
            (50, -5),
            (100, -4),
            (250, -2),
            (500, -1),
            (1000, 0),
        )

    elif annual_traffic < 15000:

        bands = (
            (50, -8),
            (100, -6),
            (250, -4),
            (500, -2),
            (1000, -1),
        )

    elif annual_traffic < 30000:

        bands = (
            (50, -11),
            (100, -9),
            (250, -7),
            (500, -5),
            (1000, -2),
        )

    else:

        bands = (
            (50, -14),
            (100, -11),
            (250, -9),
            (500, -7),
            (1000, -3),
        )

    house_penalty = 0

    for (
        maximum_distance,
        penalty,
    ) in bands:

        if distance <= maximum_distance:
            house_penalty = penalty
            break

    # Grundstücke werden wie bisher strenger bewertet.
    if object_type == "land":
        penalty = (
            house_penalty * 2
        )
    else:
        penalty = house_penalty

    penalty = max(
        NOISE_RULES[
            object_type
        ]["cap"],
        penalty,
    )

    return (
        int(penalty),
        distance,
        annual_traffic,
    )


def noise_effect(
    property_data,
    object_type,
):

    rules = NOISE_RULES[
        object_type
    ]

    total_penalty = 0
    details = []
    ko_reasons = []

    for source in (
        "rail",
        "road",
        "air",
    ):

        source_rules = rules[
            source
        ]

        lden = property_data.get(
            f"{source}_lden"
        )

        lnight = property_data.get(
            f"{source}_lnight"
        )

        # ----------------------------------------------------
        # Keine kartierten Pegel
        #
        # Nur bei Bahn darf hier der explizite Ersatzwert
        # greifen. Straße und Flug bleiben unverändert.
        # ----------------------------------------------------

        if (
            lden is None
            and lnight is None
        ):

            if source == "rail":

                fallback = (
                    _rail_fallback_penalty(
                        property_data,
                        object_type,
                    )
                )

                if fallback is not None:

                    (
                        source_penalty,
                        distance,
                        annual_traffic,
                    ) = fallback

                    total_penalty += (
                        source_penalty
                    )

                    traffic_text = (
                        f"{annual_traffic:,.0f}"
                        .replace(",", ".")
                    )

                    details.append(
                        "Schiene Ersatzwert "
                        f"{distance:.0f} m / "
                        f"{traffic_text} Züge/Jahr "
                        f"({source_penalty:+d}; "
                        "keine EBA-Isophone)"
                    )

            continue

        # ----------------------------------------------------
        # Kartierte Werte:
        # bestehende Logik unverändert
        # ----------------------------------------------------

        ko = False

        if (
            lden is not None
            and float(lden)
            >= source_rules["ko_lden"]
        ):
            ko = True

        if (
            lnight is not None
            and float(lnight)
            >= source_rules["ko_lnight"]
        ):
            ko = True

        if ko:

            parts = []

            if lden is not None:
                parts.append(
                    "LDEN "
                    f"{_noise_band(lden, 'lden')} dB"
                )

            if lnight is not None:
                parts.append(
                    "Nacht "
                    f"{_noise_band(lnight, 'lnight')} dB"
                )

            ko_reasons.append(
                f"{NOISE_KO_LABELS[source]}: "
                + " / ".join(parts)
            )

            continue

        lden_penalty = (
            _noise_penalty_for_value(
                lden,
                source_rules["lden"],
            )
        )

        lnight_penalty = (
            _noise_penalty_for_value(
                lnight,
                source_rules["lnight"],
            )
        )

        # Die jeweils schlechtere Bewertung gewinnt.
        source_penalty = min(
            lden_penalty,
            lnight_penalty,
        )

        total_penalty += (
            source_penalty
        )

        parts = []

        if lden is not None:
            parts.append(
                "LDEN "
                f"{_noise_band(lden, 'lden')}"
            )

        if lnight is not None:
            parts.append(
                "Nacht "
                f"{_noise_band(lnight, 'lnight')}"
            )

        if parts:

            details.append(
                f"{NOISE_SOURCE_LABELS[source]} "
                + "/".join(parts)
                + f" ({source_penalty:+d})"
            )

    # Mehrere Quellen dürfen sich summieren,
    # der Gesamtmalus bleibt aber gedeckelt.
    total_penalty = max(
        rules["cap"],
        total_penalty,
    )

    if details:

        reason = (
            f"Lärm: {total_penalty:+d} | "
            + " | ".join(details)
        )

    else:

        reason = (
            "Lärm: +0 "
            "(unter Kartierungsgrenzen "
            "bzw. keine kartierte Belastung)"
        )

    return (
        total_penalty,
        reason,
        ko_reasons,
    )



def _provisional_variants(
    property_data,
    object_type,
    neighbour_values,
):

    low = dict(property_data)
    high = dict(property_data)

    for candidate in (low, high):
        clear_geo_derived_data(candidate)
        candidate["geo_precision"] = "exact"
        candidate["_geo_precision_bypass"] = True
        candidate["noise_checked_at"] = "PROVISIONAL"
        candidate["rail_distance_m"] = None

    low["_proximity_score_override"] = 0
    high["_proximity_score_override"] = 100

    if neighbour_values:
        low["neighbour_class"] = min(
            neighbour_values,
            key=neighbour_values.get,
        )
        high["neighbour_class"] = max(
            neighbour_values,
            key=neighbour_values.get,
        )
    else:
        low["neighbour_class"] = "dense"
        high["neighbour_class"] = "isolated"

    low["neighbour_checked_at"] = "PROVISIONAL"
    high["neighbour_checked_at"] = "PROVISIONAL"

    low["water_score"] = 0
    high["water_score"] = 20

    if object_type == "land":
        low["rail_lden"] = 65
        low["road_lden"] = 65
    else:
        low["rail_lden"] = 70
        low["road_lden"] = 70

    return low, high


def _non_geo_reasons(reasons, object_type):

    prefixes = (
        (
            "Wasser:",
            "Nachbarn:",
            "Lärm:",
        )
        if object_type == "land"
        else (
            "Freilage/Nachbarn:",
            "Ruhe:",
            "Wasser:",
        )
    )

    prefixes = prefixes + (
        "Entfernung zu ",
    )

    return [
        reason
        for reason in reasons
        if not str(reason).startswith(prefixes)
    ]


def _provisional_result(
    low_result,
    high_result,
    object_type,
    thresholds,
):

    if low_result.get("ko"):
        return low_result

    if high_result.get("ko"):
        return high_result

    incomplete = sorted(
        {
            str(reason)
            for result in (
                low_result,
                high_result,
            )
            for reason in result.get(
                "incomplete_reasons",
                [],
            )
            if reason not in GEO_INCOMPLETE_REASONS
        }
    )

    reasons = _non_geo_reasons(
        low_result.get("reasons", []),
        object_type,
    )

    if incomplete:
        reasons.append(
            "Geo: Lage nur auf Ortsebene bekannt; "
            "Geo-Punkte werden nicht vergeben"
        )

        return {
            "ko": False,
            "score": None,
            "rating": "incomplete",
            "reasons": reasons,
            "ko_reasons": [],
            "incomplete_reasons": incomplete,
            "geo_precision": GEO_PRECISION_LOCALITY,
        }

    scores = (
        int(low_result["score"]),
        int(high_result["score"]),
    )

    score_min = min(scores)
    score_max = max(scores)

    reasons.append(
        "Geo: Lage nur auf Ortsebene bekannt; "
        f"vorläufig {score_min}–{score_max} Punkte"
    )

    return {
        "ko": False,
        "score": None,
        "rating": "provisional",
        "reasons": reasons,
        "ko_reasons": [],
        "incomplete_reasons": [],
        "provisional": True,
        "score_min": score_min,
        "score_max": score_max,
        "rating_min": classify_score(
            score_min,
            thresholds,
        ),
        "rating_max": classify_score(
            score_max,
            thresholds,
        ),
        "geo_precision": GEO_PRECISION_LOCALITY,
    }


def score_land(property_data):

    root_config = CONFIG.score_config()
    config = root_config.get("land", {})

    hard = config.get(
        "hard_filters",
        {}
    )

    scoring = config.get(
        "scoring",
        {}
    )

    if not property_data.get(
        "_geo_precision_bypass"
    ):
        geo_precision = (
            property_data.get("geo_precision")
            or effective_geo_precision(property_data)
        )

        if geo_precision == GEO_PRECISION_LOCALITY:
            low, high = _provisional_variants(
                property_data,
                "land",
                scoring.get(
                    "neighbours",
                    {},
                ).get("values", {}),
            )

            return _provisional_result(
                score_land(low),
                score_land(high),
                "land",
                config.get("thresholds", {}),
            )

        if geo_precision == GEO_PRECISION_MISSING:
            property_data = dict(property_data)
            clear_geo_derived_data(property_data)
            property_data[
                "_geo_precision_bypass"
            ] = True

    reasons = []
    ko_reasons = []
    incomplete_reasons = []

    plot_area = property_data.get(
        "plot_area"
    )

    price = property_data.get(
        "price"
    )

    (
        noise_adjustment,
        noise_reason,
        noise_ko_reasons,
    ) = noise_effect(
        property_data,
        "land",
    )

    # --------------------------------
    # KO FILTERS
    # --------------------------------

    minimum_plot = hard.get(
        "min_plot_area"
    )

    if (
        minimum_plot is not None
        and plot_area is not None
        and plot_area < minimum_plot
    ):

        ko_reasons.append(
            f"Grundstück nur {plot_area:.0f} m²"
        )

    if property_data.get(
        "holiday_area"
    ) is True:

        ko_reasons.append(
            "Ferien-/Wochenendhausgebiet"
        )

    if property_data.get(
        "residential_building_allowed"
    ) is False:

        ko_reasons.append(
            "kein normales Wohnbaurecht"
        )

    if property_data.get(
        "severe_noise"
    ) is True:

        ko_reasons.append(
            "starke Lärmquelle"
        )

    ko_reasons.extend(
        noise_ko_reasons
    )

    if ko_reasons:

        return {
            "ko": True,
            "score": 0,
            "rating": "ko",
            "reasons": reasons,
            "ko_reasons": ko_reasons
        }


    # --------------------------------
    # VOLLSTÄNDIGKEIT
    # --------------------------------

    if (
        property_data.get(
            "water_score"
        ) is None
        and property_data.get(
            "water_distance_km"
        ) is None
    ):
        incomplete_reasons.append(
            "Wasser"
        )

    neighbour_class_for_check = str(
        property_data.get(
            "neighbour_class"
        )
        or "unknown"
    ).strip().lower()

    if neighbour_class_for_check == "unknown":
        incomplete_reasons.append(
            "Freilage/Nachbarn"
        )

    if property_data.get(
        "noise_checked_at"
    ) is None:
        incomplete_reasons.append(
            "Lärm"
        )

    elif _unmapped_nearby_rail_reason(
        property_data
    ):
        incomplete_reasons.append(
            "Lärm"
        )

    if 'Lärm' in incomplete_reasons and _rail_fallback_penalty(property_data, 'land') is not None:
        incomplete_reasons.remove('Lärm')

    if incomplete_reasons:

        return {
            "ko": False,
            "score": None,
            "rating": "incomplete",
            "reasons": reasons,
            "ko_reasons": [],
            "incomplete_reasons":
                incomplete_reasons,
        }


    # --------------------------------
    # SCORE
    # --------------------------------

    score = 0

    # Preis

    p = price_points(
        price,
        scoring["price"]
    )

    score += p

    if price is not None:
        reasons.append(
            f"Preis: {p}/30"
        )

    no_broker = _ohne_makler_price_effect(
        property_data,
        price,
        scoring["price"],
    )

    if no_broker["applies"]:

        bonus = int(
            no_broker["bonus_points"]
        )

        score += bonus

        discounted = (
            no_broker[
                "discounted_purchase_price"
            ]
        )

        reasons.append(
            "Ohne-Makler-Bonus: "
            f"+{bonus} "
            "(Kaufpreis für Bewertung -3 %: "
            f"{discounted:.0f} €)"
        )


    # Grundstück

    p = plot_points(
        plot_area,
        scoring["plot_area"]
    )

    score += p

    if plot_area is not None:
        reasons.append(
            f"Grundstück: {p}/25"
        )

    # Wasser

    water_score = property_data.get(
        "water_score"
    )

    water_class = property_data.get(
        "water_class"
    )

    water_distance = property_data.get(
        "water_distance_km"
    )

    if water_score is not None:

        p = int(
            water_score
        )

        score += p

        if (
            water_class
            and water_distance is not None
        ):

            reasons.append(
                f"Wasser: {p}/20 "
                f"({water_class}, "
                f"{water_distance:.2f} km)"
            )

        else:

            reasons.append(
                f"Wasser: {p}/20"
            )

    elif water_distance is not None:

        # Fallback für alte DB-Einträge,
        # bis der Wasser-Backfill gelaufen ist.

        p = water_points(
            water_distance,
            scoring["water_distance"]
        )

        score += p

        reasons.append(
            f"Wasser: {p}/20 "
            f"(alte Distanzbewertung)"
        )

    # Nachbarn

    neighbour_class = property_data.get(
        "neighbour_class"
    )

    if neighbour_class:

        p = (
            scoring["neighbours"]
            ["values"]
            .get(
                neighbour_class,
                0
            )
        )

        score += p

        reasons.append(
            f"Nachbarn: {p}/15"
        )


    # Erstwohnsitz

    residence = property_data.get(
        "primary_residence",
        "unknown"
    )

    p = (
        scoring["primary_residence"]
        ["values"]
        .get(
            residence,
            0
        )
    )

    score += p

    reasons.append(
        f"Wohnnutzung: {p}/5"
    )


    # --------------------------------
    # Bebaubarkeit
    # --------------------------------

    buildability = (
        property_data.get(
            "buildability"
        )
        or "NO_INFORMATION"
    )

    buildability = str(
        buildability
    ).strip().upper()

    p = (
        scoring["buildability"]
        ["values"]
        .get(
            buildability,
            0
        )
    )

    score += p

    reasons.append(
        f"Bebaubarkeit: {p}/5 "
        f"({buildability})"
    )

    # --------------------------------
    # Lärm
    # --------------------------------

    score += noise_adjustment

    reasons.append(
        noise_reason
    )

    base_score = max(
        0,
        min(SCORE_CEILING, score),
    )

    location_config = root_config.get(
        "location_weighting", {}
    )
    location_details = location_weighting_details(
        base_score,
        property_data,
        location_config,
    )

    if location_details is None:
        incomplete_reasons.append(
            _location_incomplete_reason(location_config)
        )

    if incomplete_reasons:
        reasons.append(
            "Unvollständig: "
            + ", ".join(incomplete_reasons)
        )
        return {
            "ko": False,
            "score": None,
            "rating": "incomplete",
            "reasons": reasons,
            "ko_reasons": [],
            "incomplete_reasons": incomplete_reasons,
        }

    score = location_details["score"]

    if location_details["location_weighting_applied"]:
        reasons.append(
            _location_reason(location_details)
        )


    rating = classify_score(
        score,
        config["thresholds"]
    )


    return {

        "ko": False,

        "score": score,

        "rating": rating,

        "reasons": reasons,

        "ko_reasons": [],

        **location_details,
    }

ENERGY_CLASS_ORDER = (
    "A+",
    "A",
    "B",
    "C",
    "D",
    "E",
    "F",
    "G",
    "H",
)


def energy_class_from_value(value):

    if value is None:
        return None

    try:
        value = float(value)
    except (TypeError, ValueError):
        return None

    if value < 30:
        return "A+"

    if value < 50:
        return "A"

    if value < 75:
        return "B"

    if value < 100:
        return "C"

    if value < 130:
        return "D"

    if value < 160:
        return "E"

    if value < 200:
        return "F"

    if value <= 250:
        return "G"

    return "H"


def energy_score_adjustment(
    property_data,
    config,
):

    status = (
        property_data.get(
            "energy_certificate_status"
        )
        or "unknown"
    )

    if status == "not_required":
        return -7, "Ausweis nicht erforderlich | Risiko -7"

    if status == "not_available_yet":
        return 0, "Ausweis noch nicht verfügbar | bleibt offen"

    if status == "no_label":

        adjustment = int(
            config.get(
                "class_adjustments",
                {}
            ).get(
                "H",
                -8,
            )
        )

        return (
            adjustment,
            "kein Energielabel | wie H gewertet",
        )

    reported_class = (
        property_data.get(
            "energy_class"
        )
        or ""
    ).strip().upper()

    if reported_class not in ENERGY_CLASS_ORDER:
        reported_class = None

    value = property_data.get(
        "energy_value_kwh"
    )

    value_class = energy_class_from_value(
        value
    )

    classes = [
        energy_class
        for energy_class in (
            reported_class,
            value_class,
        )
        if energy_class is not None
    ]

    if not classes:
        return -7, "Energie unbekannt | Risiko -7"

    # Falls Portal-Klasse und kWh-Wert widersprechen,
    # verwenden wir konservativ die schlechtere Klasse.
    effective_class = max(
        classes,
        key=ENERGY_CLASS_ORDER.index,
    )

    adjustment = int(
        config.get(
            "class_adjustments",
            {}
        ).get(
            effective_class,
            0
        )
    )

    details = [
        effective_class
    ]

    if value is not None:
        try:
            value_text = (
                f"{float(value):.1f}"
                .replace(".", ",")
            )

            details.append(
                f"{value_text} kWh/(m²·a)"
            )
        except (TypeError, ValueError):
            pass

    certificate_type = property_data.get(
        "energy_certificate_type"
    )

    if certificate_type == "demand":
        details.append("Bedarf")

    elif certificate_type == "consumption":
        details.append("Verbrauch")

    if (
        reported_class
        and value_class
        and reported_class != value_class
    ):
        details.append(
            "konservativ schlechtere Klasse"
        )

    return (
        adjustment,
        " | ".join(details),
    )


def _house_effective_price(
    price,
    condition_class,
    config,
):

    if price is None:
        return None, 0

    surcharges = config.get(
        "condition_surcharges",
        {},
    )

    surcharge = float(
        surcharges.get(
            condition_class,
            surcharges.get(
                "unknown",
                0,
            ),
        )
    )

    return (
        float(price) + surcharge,
        surcharge,
    )


def _house_noise_points(
    noise_adjustment,
    config,
):

    for bracket in config.get(
        "penalty_brackets",
        [],
    ):

        minimum = float(
            bracket.get(
                "min_adjustment",
                -999,
            )
        )

        if noise_adjustment >= minimum:
            return int(
                bracket.get(
                    "points",
                    0,
                )
            )

    return 0


def _house_water_points(
    water_score,
    config,
):

    if water_score is None:
        return 0

    target_max = int(
        config.get(
            "weight",
            10,
        )
    )

    source_max = float(
        config.get(
            "source_max",
            20,
        )
    )

    if source_max <= 0:
        return 0

    value = (
        float(water_score)
        * target_max
        / source_max
    )

    # klassisches Aufrunden ab .5
    points = int(
        value + 0.5
    )

    return max(
        0,
        min(
            target_max,
            points,
        ),
    )


def score_house(property_data, ignore_search_limits=False):

    root_config = CONFIG.score_config()
    config = root_config.get("house", {})

    hard = config.get(
        "hard_filters",
        {},
    )

    scoring = config.get(
        "scoring",
        {},
    )

    if not property_data.get(
        "_geo_precision_bypass"
    ):
        geo_precision = (
            property_data.get("geo_precision")
            or effective_geo_precision(property_data)
        )

        if geo_precision == GEO_PRECISION_LOCALITY:
            low, high = _provisional_variants(
                property_data,
                "house",
                scoring.get(
                    "neighbours",
                    {},
                ).get("values", {}),
            )

            return _provisional_result(
                score_house(
                    low,
                    ignore_search_limits=
                        ignore_search_limits,
                ),
                score_house(
                    high,
                    ignore_search_limits=
                        ignore_search_limits,
                ),
                "house",
                config.get("thresholds", {}),
            )

        if geo_precision == GEO_PRECISION_MISSING:
            property_data = dict(property_data)
            clear_geo_derived_data(property_data)
            property_data[
                "_geo_precision_bypass"
            ] = True

    reasons = []
    ko_reasons = []
    incomplete_reasons = []

    price = property_data.get(
        "price"
    )

    plot_area = property_data.get(
        "plot_area"
    )

    living_area = property_data.get(
        "living_area"
    )

    condition_class = (
        property_data.get(
            "condition_class"
        )
        or "unknown"
    )

    # ========================================================
    # VOLLSTÄNDIGKEIT
    # ========================================================
    #
    # Ein fehlender Wert darf NICHT als 0 Punkte gewertet
    # werden.
    #
    # Solange eine relevante Kategorie noch nicht geprüft
    # bzw. unbekannt ist, wird am Ende KEIN Gesamtscore
    # veröffentlicht.
    #
    # KO-Kriterien dürfen trotzdem sofort greifen.
    # ========================================================

    if (
        price is None
        or condition_class == "unknown"
    ):
        incomplete_reasons.append(
            "Preis/Zustand"
        )

    if plot_area is None:
        incomplete_reasons.append(
            "Grundstück"
        )

    neighbour_class_for_check = str(
        property_data.get(
            "neighbour_class"
        )
        or "unknown"
    ).strip().lower()

    if (
        property_data.get(
            "neighbour_checked_at"
        ) is None
        or neighbour_class_for_check == "unknown"
    ):
        incomplete_reasons.append(
            "Freilage/Nachbarn"
        )

    if property_data.get(
        "noise_checked_at"
    ) is None:
        incomplete_reasons.append(
            "Lärm"
        )

    elif _unmapped_nearby_rail_reason(
        property_data
    ):
        incomplete_reasons.append(
            "Lärm"
        )

    if property_data.get(
        "water_score"
    ) is None:
        incomplete_reasons.append(
            "Wasser"
        )

    if (
        condition_class != "dilapidated"
        and living_area is None
    ):
        incomplete_reasons.append(
            "Wohnfläche"
        )

    energy_status_for_check = str(
        property_data.get(
            "energy_certificate_status"
        )
        or "unknown"
    ).strip().lower()

    if (
        property_data.get(
            "energy_updated_at"
        ) is None
        or energy_status_for_check
        == "not_available_yet"
    ):
        incomplete_reasons.append(
            "Energie"
        )

    # ========================================================
    # HARTE FILTER
    # ========================================================
    #
    # WICHTIG:
    #
    # Das harte Budget umfasst Kaufpreis und bekannte Zustandskosten.
    # Eine unbekannte Zustandsschätzung löst kein Budget-KO aus.
    #
    # Fehlende Werte sind NICHT automatisch KO.
    # ========================================================

    costs = house_costs(price, condition_class, config)
    if costs['ko_reason']:
        ko_reasons.append(costs['ko_reason'])


    minimum_plot = hard.get(
        "min_plot_area"
    )

    if (
        not ignore_search_limits
        and minimum_plot is not None
        and plot_area is not None
        and plot_area < minimum_plot
    ):

        ko_reasons.append(
            "Grundstück nur "
            + f"{plot_area:,.0f} m²".replace(",", ".")
            + " (< "
            + f"{minimum_plot:,.0f} m²".replace(",", ".")
            + ")"
        )


    # ========================================================
    # LÄRM
    # ========================================================

    (
        noise_adjustment,
        noise_reason,
        noise_ko_reasons,
    ) = noise_effect(
        property_data,
        "house",
    )

    ko_reasons.extend(
        noise_ko_reasons
    )


    if ko_reasons:

        return {
            "ko": True,
            "score": 0,
            "rating": "ko",
            "reasons": reasons,
            "ko_reasons": ko_reasons,
        }


    score = 0


    # ========================================================
    # PREIS + ZUSTAND
    # ========================================================

    price_config = scoring.get(
        "price",
        {},
    )

    condition_surcharge = costs['surcharge']

    effective_price = None

    if price is not None:

        effective_price = (
            price
            + condition_surcharge
        )

        price_score = price_points(
            effective_price,
            price_config,
        )

    else:

        price_score = 0


    score += price_score


    if price is not None:

        reasons.append(
            "Preis/Zustand: "
            f"{price_score}/25 "
            f"({price:.0f} € + "
            f"{condition_surcharge:.0f} € = "
            f"{effective_price:.0f} €; "
            f"{condition_class})"
        )

    else:

        reasons.append(
            "Preis/Zustand: 0/25 "
            f"(Preis unbekannt; "
            f"{condition_class})"
        )

    no_broker = _ohne_makler_price_effect(
        property_data,
        price,
        price_config,
        surcharge=condition_surcharge,
    )

    if no_broker["applies"]:

        bonus = int(
            no_broker["bonus_points"]
        )

        score += bonus

        discounted_purchase = (
            no_broker[
                "discounted_purchase_price"
            ]
        )

        discounted_effective = (
            no_broker[
                "discounted_effective_price"
            ]
        )

        reasons.append(
            "Ohne-Makler-Bonus: "
            f"+{bonus} "
            "(Kaufpreis für Bewertung -3 %: "
            f"{discounted_purchase:.0f} €; "
            "mit Zustand: "
            f"{discounted_effective:.0f} €)"
        )


    # ========================================================
    # GRUNDSTÜCK
    # ========================================================

    plot_config = scoring.get(
        "plot_area",
        {},
    )

    plot_score = plot_points(
        plot_area,
        plot_config,
    )

    score += plot_score


    if plot_area is not None:

        reasons.append(
            "Grundstück: "
            f"{plot_score}/20 "
            f"({plot_area:.0f} m²)"
        )

    else:

        reasons.append(
            "Grundstück: 0/20 "
            "(unbekannt)"
        )


    # ========================================================
    # FREILAGE / NACHBARN
    # ========================================================

    neighbour_class = (
        property_data.get(
            "neighbour_class"
        )
        or "unknown"
    )

    neighbour_score = (
        scoring
        .get(
            "neighbours",
            {},
        )
        .get(
            "values",
            {},
        )
        .get(
            neighbour_class,
            0,
        )
    )

    score += neighbour_score

    reasons.append(
        "Freilage/Nachbarn: "
        f"{neighbour_score}/25 "
        f"({neighbour_class})"
    )


    # ========================================================
    # RUHE
    # ========================================================

    if noise_adjustment >= 0:
        quiet_score = 15

    elif noise_adjustment >= -2:
        quiet_score = 12

    elif noise_adjustment >= -5:
        quiet_score = 9

    elif noise_adjustment >= -9:
        quiet_score = 6

    elif noise_adjustment >= -14:
        quiet_score = 3

    else:
        quiet_score = 0


    score += quiet_score

    reasons.append(
        "Ruhe: "
        f"{quiet_score}/15 | "
        f"{noise_reason}"
    )


    # ========================================================
    # WASSER
    # ========================================================

    water_score_raw = property_data.get(
        "water_score"
    )

    water_class = property_data.get(
        "water_class"
    )

    water_distance = property_data.get(
        "water_distance_km"
    )


    if water_score_raw is None:

        water_score = 0

        reasons.append(
            "Wasser: 0/10 "
            "(unbekannt)"
        )

    else:

        # Die vorhandene Wasserbewertung hat 0..20 Punkte.
        # Für Häuser wird sie auf 0..10 skaliert.
        water_score = min(
            10,
            max(
                0,
                int(
                    (
                        float(
                            water_score_raw
                        )
                        + 1
                    )
                    // 2
                ),
            ),
        )

        if (
            water_class
            and water_distance is not None
        ):

            reasons.append(
                "Wasser: "
                f"{water_score}/10 "
                f"({water_class}, "
                f"{water_distance:.2f} km)"
            )

        else:

            reasons.append(
                "Wasser: "
                f"{water_score}/10"
            )


    score += water_score


    # ========================================================
    # WOHNFLÄCHE
    # ========================================================
    #
    # Bei Abriss / dilapidated zählt die vorhandene
    # Wohnfläche bewusst nicht als Vorteil.
    # ========================================================

    if condition_class == "dilapidated":

        living_score = 0

        reasons.append(
            "Wohnfläche: 0/5 "
            "(Abrissobjekt)"
        )

    else:

        living_score = plot_points(
            living_area,
            scoring.get(
                "living_area",
                {},
            ),
        )

        score += living_score

        if living_area is not None:

            reasons.append(
                "Wohnfläche: "
                f"{living_score}/5 "
                f"({living_area:.0f} m²)"
            )

        else:

            reasons.append(
                "Wohnfläche: 0/5 "
                "(unbekannt)"
            )


    # Bei dilapidated wurde living_score oben bewusst
    # nicht addiert.
    if condition_class == "dilapidated":
        pass


    # ========================================================
    # ENERGIE
    # ========================================================

    (
        energy_adjustment,
        energy_reason,
    ) = energy_score_adjustment(
        property_data,
        scoring.get(
            "energy",
            {},
        ),
    )

    score += energy_adjustment

    reasons.append(
        "Energie: "
        f"{energy_adjustment:+d} "
        f"({energy_reason})"
    )


    # ========================================================
    # ABSCHLUSS
    # ========================================================

    # Rail-Fallback gilt als abgeschlossene Lärmprüfung.
    # EBA-Isophonen haben weiterhin Vorrang; der Helper
    # liefert nur dann einen Ersatzwert, wenn keine
    # kartierten Bahnpegel vorhanden sind und Entfernung
    # plus Jahresverkehr bekannt sind.
    if (
        "Lärm" in incomplete_reasons
        and _rail_fallback_penalty(
            property_data,
            "house",
        ) is not None
    ):
        incomplete_reasons.remove(
            "Lärm"
        )

    base_score = max(
        0,
        min(
            SCORE_CEILING,
            int(score),
        ),
    )

    location_config = root_config.get(
        "location_weighting", {}
    )
    location_details = location_weighting_details(
        base_score,
        property_data,
        location_config,
    )

    if location_details is None:
        incomplete_reasons.append(
            _location_incomplete_reason(location_config)
        )

    if incomplete_reasons:

        reasons.append(
            "Unvollständig: "
            + ", ".join(
                incomplete_reasons
            )
        )

        return {
            "ko": False,
            "score": None,
            "rating": "incomplete",
            "reasons": reasons,
            "ko_reasons": [],
            "incomplete_reasons":
                incomplete_reasons,
        }

    score = location_details["score"]

    if location_details["location_weighting_applied"]:
        reasons.append(
            _location_reason(location_details)
        )

    rating = classify_score(
        score,
        config.get(
            "thresholds",
            {},
        ),
    )

    return {
        "ko": False,
        "score": score,
        "rating": rating,
        "reasons": reasons,
        "ko_reasons": [],
        "incomplete_reasons": [],
        **location_details,
    }
