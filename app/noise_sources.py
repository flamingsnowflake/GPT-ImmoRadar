import json
import urllib.parse
import urllib.request

from noise import get_rail_noise


# ------------------------------------------------------------
# EEA – bundesweite strategische Lärmkartierung Deutschland
# ------------------------------------------------------------

EEA_BASE = (
    "https://noise.discomap.eea.europa.eu/"
    "arcgis/rest/services/Noise/"
    "Noise_Dyna_LAEA/MapServer"
)

EEA_LAYERS = {
    "road_lden": 269,
    "road_lnight": 270,
    "air_lden": 273,
    "air_lnight": 274,
}


# ------------------------------------------------------------
# Sachsen – detaillierter Fluglärm
#
# Enthält u.a. Flughafen Leipzig/Halle und beginnt niedriger
# als die normale EU-Ausgabe:
#
# LDEN:   ab 50 dB
# LNight: ab 45 dB
# ------------------------------------------------------------

SAXONY_NOISE_BASE = (
    "https://luis.sachsen.de/arcgis/rest/services/"
    "laerm/laermkartierung/FeatureServer"
)

SAXONY_AIR_LDEN = 37
SAXONY_AIR_LNIGHT = 36


def _get_json(url, params, timeout=20):
    full_url = (
        url
        + "?"
        + urllib.parse.urlencode(params)
    )

    req = urllib.request.Request(
        full_url,
        headers={
            "User-Agent": (
                "immobilien-monitor/1.0"
            ),
        },
    )

    with urllib.request.urlopen(
        req,
        timeout=timeout,
    ) as response:
        return json.loads(
            response.read().decode("utf-8")
        )


def _arcgis_point(
    base,
    layer_id,
    lat,
    lon,
    out_fields="*",
):
    data = _get_json(
        f"{base}/{layer_id}/query",
        {
            "f": "json",
            "geometry": f"{lon},{lat}",
            "geometryType": "esriGeometryPoint",
            "inSR": "4326",
            "spatialRel": (
                "esriSpatialRelIntersects"
            ),
            "outFields": out_fields,
            "returnGeometry": "false",
        },
    )

    if "error" in data:
        raise RuntimeError(
            data["error"]
        )

    return [
        feature.get(
            "attributes",
            {},
        )
        for feature in data.get(
            "features",
            [],
        )
    ]


def _eea_db(layer_id, lat, lon):
    # Wichtig:
    #
    # None darf hier ausschließlich bedeuten:
    # Die EEA-Abfrage war erfolgreich, aber am Punkt
    # liegt keine kartierte Lärmbelastung vor.
    #
    # Netzwerk-, Server- und API-Fehler müssen dagegen
    # nach oben durchgereicht werden. Der Aufrufer lässt
    # noise_checked_at dann auf None und der Score bleibt
    # incomplete statt fälschlich "ruhig".
    features = _arcgis_point(
        EEA_BASE,
        layer_id,
        lat,
        lon,
    )

    values = []

    for attrs in features:
        value = attrs.get("DB")

        try:
            if value is not None:
                values.append(
                    int(float(value))
                )
        except (TypeError, ValueError):
            continue

    if not values:
        return None

    return max(values)


def _parse_category(category):
    """
    Examples:

        Lden5054      -> 50
        Lden5559      -> 55
        Lden6569      -> 65
        Lden7074      -> 70
        LdenAb75      -> 75

        Lnight4549    -> 45
        Lnight5054    -> 50
        LnightAb70    -> 70
    """

    if not category:
        return None

    text = str(category)

    digits = "".join(
        char
        for char in text
        if char.isdigit()
    )

    if not digits:
        return None

    if "Ab" in text:
        try:
            return int(digits)
        except ValueError:
            return None

    if len(digits) >= 4:
        try:
            return int(digits[:2])
        except ValueError:
            return None

    return None


def _saxony_air(layer_id, lat, lon):
    try:
        features = _arcgis_point(
            SAXONY_NOISE_BASE,
            layer_id,
            lat,
            lon,
            out_fields="CATEGORY",
        )
    except Exception:
        return None

    values = []

    for attrs in features:
        value = _parse_category(
            attrs.get("CATEGORY")
        )

        if value is not None:
            values.append(value)

    if not values:
        return None

    return max(values)


def _band(value, kind, source=None):
    if value is None:
        return None

    value = int(value)

    if kind == "lden":
        if value >= 75:
            return ">=75"

    if kind == "lnight":
        if value >= 70:
            return ">=70"

    return f"{value}-{value + 4}"


def get_road_noise(lat, lon):
    lden = _eea_db(
        EEA_LAYERS["road_lden"],
        lat,
        lon,
    )

    lnight = _eea_db(
        EEA_LAYERS["road_lnight"],
        lat,
        lon,
    )

    return {
        "source": "EEA_END_R4",
        "lden": lden,
        "lden_band": _band(
            lden,
            "lden",
        ),
        "lnight": lnight,
        "lnight_band": _band(
            lnight,
            "lnight",
        ),
        "mapping_floor_lden": 55,
        "mapping_floor_lnight": 50,
    }


def get_air_noise(lat, lon):
    # First use the more sensitive Saxon official layer.
    # This also contains the cross-border Leipzig/Halle
    # airport mapping where available.

    sax_lden = _saxony_air(
        SAXONY_AIR_LDEN,
        lat,
        lon,
    )

    sax_lnight = _saxony_air(
        SAXONY_AIR_LNIGHT,
        lat,
        lon,
    )

    if (
        sax_lden is not None
        or sax_lnight is not None
    ):
        return {
            "source": "LFULG_R4",
            "lden": sax_lden,
            "lden_band": _band(
                sax_lden,
                "lden",
            ),
            "lnight": sax_lnight,
            "lnight_band": _band(
                sax_lnight,
                "lnight",
            ),
            "mapping_floor_lden": 50,
            "mapping_floor_lnight": 45,
        }

    # Nationwide fallback.

    lden = _eea_db(
        EEA_LAYERS["air_lden"],
        lat,
        lon,
    )

    lnight = _eea_db(
        EEA_LAYERS["air_lnight"],
        lat,
        lon,
    )

    return {
        "source": "EEA_END_R4",
        "lden": lden,
        "lden_band": _band(
            lden,
            "lden",
        ),
        "lnight": lnight,
        "lnight_band": _band(
            lnight,
            "lnight",
        ),
        "mapping_floor_lden": 55,
        "mapping_floor_lnight": 50,
    }


def get_noise(lat, lon):
    result = {'lat': float(lat), 'lon': float(lon)}
    errors = []
    for name, lookup in [('rail', get_rail_noise), ('road', get_road_noise), ('air', get_air_noise)]:
        try:
            result[name] = lookup(lat, lon)
        except Exception as exc:
            errors.append(f'{name}: {type(exc).__name__}: {exc}')
    if errors:
        raise RuntimeError('; '.join(errors))
    return result


def _display_band(
    source,
    kind,
):
    value = source.get(
        f"{kind}_band"
    )

    if value is not None:
        return (
            value + " dB(A)"
        )

    floor = source.get(
        f"mapping_floor_{kind}"
    )

    if floor is None:
        return "nicht kartiert"

    return (
        f"<{floor} dB(A) / "
        "unter Kartierungsgrenze"
    )


def print_noise(result):
    print(
        "=" * 68
    )

    print(
        f'{result["lat"]:.6f}, '
        f'{result["lon"]:.6f}'
    )

    print(
        "=" * 68
    )

    rail = result["rail"]
    road = result["road"]
    air = result["air"]

    print()
    print("🚆 SCHIENE")

    print(
        "  LDEN:  ",
        rail["lden_band"],
        "dB(A)",
    )

    print(
        "  Nacht: ",
        rail["lnight_band"],
        "dB(A)",
    )

    print(
        "  Abstand:",
        (
            f'{rail["rail_distance_m"]:.0f} m'
            if rail.get(
                "rail_distance_m"
            ) is not None
            else "keine kartierte Bahn <=2 km"
        ),
    )

    if rail.get(
        "annual_traffic"
    ) is not None:
        print(
            "  Züge:",
            f'{rail["annual_traffic"]:,}'.replace(
                ",",
                ".",
            ),
            "/ Jahr",
        )

    print()
    print("🚗 STRASSE")

    print(
        "  LDEN:  ",
        _display_band(
            road,
            "lden",
        ),
    )

    print(
        "  Nacht: ",
        _display_band(
            road,
            "lnight",
        ),
    )

    print(
        "  Quelle:",
        road["source"],
    )

    print()
    print("✈️ FLUG")

    print(
        "  LDEN:  ",
        _display_band(
            air,
            "lden",
        ),
    )

    print(
        "  Nacht: ",
        _display_band(
            air,
            "lnight",
        ),
    )

    print(
        "  Quelle:",
        air["source"],
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "lat",
        type=float,
    )

    parser.add_argument(
        "lon",
        type=float,
    )

    args = parser.parse_args()

    print_noise(
        get_noise(
            args.lat,
            args.lon,
        )
    )
