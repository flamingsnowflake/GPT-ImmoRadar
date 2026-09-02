import json
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, "/app")

from noise import get_rail_noise


EEA_BASE = (
    "https://noise.discomap.eea.europa.eu/"
    "arcgis/rest/services/Noise/"
    "Noise_Dyna_LAEA/MapServer"
)

# Deutschland – offizielle EU-Lärmkartierung
EEA_LAYERS = {
    "road_lden": 269,
    "road_lnight": 270,
    "air_lden": 273,
    "air_lnight": 274,
}


POINTS = [
    (
        "Genthin Grundstück",
        52.40356,
        12.14792,
    ),
    (
        "Plötzkau – Schloßstraße 22",
        51.7455795,
        11.6848349,
    ),
]


def query_eea(layer_id, lat, lon):
    url = (
        f"{EEA_BASE}/{layer_id}/query"
    )

    params = {
        "f": "json",
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "false",
    }

    req = urllib.request.Request(
        url
        + "?"
        + urllib.parse.urlencode(params),
        headers={
            "User-Agent": (
                "immobilien-monitor/1.0"
            ),
        },
    )

    with urllib.request.urlopen(
        req,
        timeout=30,
    ) as response:
        data = json.loads(
            response.read().decode("utf-8")
        )

    if "error" in data:
        raise RuntimeError(
            data["error"]
        )

    features = data.get(
        "features",
        [],
    )

    values = []

    for feature in features:
        attrs = feature.get(
            "attributes",
            {},
        )

        value = attrs.get("DB")

        try:
            if value is not None:
                values.append(
                    float(value)
                )
        except (TypeError, ValueError):
            pass

    if not values:
        return None

    return int(max(values))


def band(value, kind):
    if value is None:
        if kind == "lden":
            return "<55 / nicht kartiert"

        return "<50 / nicht kartiert"

    if kind == "lden":
        if value >= 75:
            return ">=75"

    if kind == "lnight":
        if value >= 70:
            return ">=70"

    return f"{value}-{value + 4}"


for name, lat, lon in POINTS:

    print()
    print("=" * 72)
    print(name)
    print(f"{lat:.6f}, {lon:.6f}")
    print("=" * 72)

    # --------------------------------------------------------
    # SCHIENE
    # --------------------------------------------------------

    rail = get_rail_noise(
        lat,
        lon,
    )

    print()
    print("🚆 SCHIENE")

    print(
        "  LDEN:   ",
        rail["lden_band"],
        "dB(A)",
    )

    print(
        "  LNight: ",
        rail["lnight_band"],
        "dB(A)",
    )

    print(
        "  Abstand:",
        rail.get("rail_distance_m"),
        "m",
    )

    print(
        "  Züge/Jahr:",
        rail.get("annual_traffic"),
    )

    # --------------------------------------------------------
    # STRASSE
    # --------------------------------------------------------

    road_lden = query_eea(
        EEA_LAYERS["road_lden"],
        lat,
        lon,
    )

    road_lnight = query_eea(
        EEA_LAYERS["road_lnight"],
        lat,
        lon,
    )

    print()
    print("🚗 STRASSE")

    print(
        "  LDEN:   ",
        band(
            road_lden,
            "lden",
        ),
        "dB(A)",
    )

    print(
        "  LNight: ",
        band(
            road_lnight,
            "lnight",
        ),
        "dB(A)",
    )

    # --------------------------------------------------------
    # FLUG
    # --------------------------------------------------------

    air_lden = query_eea(
        EEA_LAYERS["air_lden"],
        lat,
        lon,
    )

    air_lnight = query_eea(
        EEA_LAYERS["air_lnight"],
        lat,
        lon,
    )

    print()
    print("✈️ FLUG")

    print(
        "  LDEN:   ",
        band(
            air_lden,
            "lden",
        ),
        "dB(A)",
    )

    print(
        "  LNight: ",
        band(
            air_lnight,
            "lnight",
        ),
        "dB(A)",
    )

    if (
        air_lden is None
        and air_lnight is None
    ):
        print(
            "  Hinweis: unter EU-Kartierungsgrenze;"
        )
        print(
            "           NICHT automatisch 'kein Fluglärm'"
        )
