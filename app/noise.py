import argparse
import json
import math
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


EBA_WFS = (
    "https://geoinformation.eisenbahn-bundesamt.de/"
    "wfs/eba/services/wfs"
)

EBA_CRS = "urn:ogc:def:crs:EPSG::3857"

# EBA Isophonenarten Runde 4:
#   5 = LDEN
#   6 = LNight
ISOPHONE_KIND = {
    5: "lden",
    6: "lnight",
}


def _localname(tag):
    return tag.split("}")[-1]


def _webmercator(lat, lon):
    """
    WGS84 -> EPSG:3857.
    """

    radius = 6378137.0

    x = radius * math.radians(lon)

    lat = max(
        min(lat, 85.05112878),
        -85.05112878,
    )

    y = radius * math.log(
        math.tan(
            math.pi / 4.0
            + math.radians(lat) / 2.0
        )
    )

    return x, y


def _fetch_wfs(layer, bbox, count=200, timeout=45):
    params = {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": layer,
        "SRSNAME": EBA_CRS,
        "BBOX": (
            f"{bbox[0]},"
            f"{bbox[1]},"
            f"{bbox[2]},"
            f"{bbox[3]},"
            f"{EBA_CRS}"
        ),
        "COUNT": str(count),
    }

    url = (
        EBA_WFS
        + "?"
        + urllib.parse.urlencode(params)
    )

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "immobilien-monitor/1.0",
        },
    )

    try:
        with urllib.request.urlopen(
            req,
            timeout=timeout,
        ) as response:
            return response.read()

    except Exception as exc:
        raise RuntimeError(
            f"EBA WFS {layer}: {exc}"
        ) from exc


def _extract_lines(geometry_element):
    """
    Extract line coordinates from GML geometries.

    Returns:
        [
            [(x1, y1), (x2, y2), ...],
            ...
        ]
    """

    lines = []

    for elem in geometry_element.iter():

        if _localname(elem.tag) != "posList":
            continue

        text = (elem.text or "").strip()

        if not text:
            continue

        try:
            values = [
                float(value)
                for value in text.split()
            ]
        except ValueError:
            continue

        dimension = 2

        try:
            dimension = int(
                elem.attrib.get(
                    "srsDimension",
                    "2",
                )
            )
        except ValueError:
            dimension = 2

        if dimension < 2:
            dimension = 2

        coordinates = []

        for index in range(
            0,
            len(values) - 1,
            dimension,
        ):
            coordinates.append(
                (
                    values[index],
                    values[index + 1],
                )
            )

        if len(coordinates) >= 2:
            lines.append(coordinates)

    return lines


def _parse_features(body):
    root = ET.fromstring(body)

    features = []

    for member in root.iter():

        if _localname(member.tag) != "member":
            continue

        children = list(member)

        if not children:
            continue

        feature_element = children[0]

        properties = {}
        lines = []

        for child in feature_element:

            name = _localname(child.tag)

            if name in (
                "geometrie_2d",
                "geometrie_multiline",
            ):
                lines.extend(
                    _extract_lines(child)
                )
                continue

            if len(list(child)) == 0:
                properties[name] = (
                    child.text or ""
                ).strip()

        features.append(
            {
                "properties": properties,
                "lines": lines,
            }
        )

    return features


def _parse_int(value):
    """
    Parse EBA traffic numbers.

    ATF is an integer annual train count.
    EBA currently returns values such as
    '26.197', i.e. German thousands notation.
    """

    if value is None:
        return None

    text = str(value).strip()

    if not text:
        return None

    # German thousands notation:
    # 26.197 -> 26197
    if re.fullmatch(
        r"[+-]?\d{1,3}(?:\.\d{3})+",
        text,
    ):
        return int(
            text.replace(".", "")
        )

    # Possible comma thousands notation.
    if re.fullmatch(
        r"[+-]?\d{1,3}(?:,\d{3})+",
        text,
    ):
        return int(
            text.replace(",", "")
        )

    try:
        return int(text)
    except ValueError:
        pass

    try:
        return int(
            round(
                float(
                    text.replace(",", ".")
                )
            )
        )
    except ValueError:
        return None


def _parse_float(value):
    if value is None:
        return None

    text = str(value).strip()

    if not text:
        return None

    try:
        return float(
            text.replace(",", ".")
        )
    except ValueError:
        return None


def _point_segment_distance(
    px,
    py,
    ax,
    ay,
    bx,
    by,
):
    dx = bx - ax
    dy = by - ay

    if dx == 0 and dy == 0:
        return math.hypot(
            px - ax,
            py - ay,
        )

    t = (
        (
            (px - ax) * dx
            + (py - ay) * dy
        )
        / (
            dx * dx
            + dy * dy
        )
    )

    t = max(
        0.0,
        min(1.0, t),
    )

    qx = ax + t * dx
    qy = ay + t * dy

    return math.hypot(
        px - qx,
        py - qy,
    )


def _feature_distance(feature, x, y):
    best = None

    for line in feature.get(
        "lines",
        [],
    ):
        for index in range(
            len(line) - 1
        ):
            ax, ay = line[index]
            bx, by = line[index + 1]

            distance = (
                _point_segment_distance(
                    x,
                    y,
                    ax,
                    ay,
                    bx,
                    by,
                )
            )

            if (
                best is None
                or distance < best
            ):
                best = distance

    return best


def _band_label(kind, lower):
    if lower is None:

        if kind == "lden":
            return "<55"

        if kind == "lnight":
            return "<45"

        return None

    lower = int(lower)

    if kind == "lden" and lower >= 75:
        return ">=75"

    if kind == "lnight" and lower >= 70:
        return ">=70"

    return f"{lower}-{lower + 4}"


def _query_isophones(lat, lon):
    x, y = _webmercator(
        lat,
        lon,
    )

    # Tiny BBOX around the actual object point.
    #
    # If the point happens to sit exactly on a band
    # boundary, we conservatively select the higher
    # returned noise level.
    epsilon = 0.25

    bbox = (
        x - epsilon,
        y - epsilon,
        x + epsilon,
        y + epsilon,
    )

    body = _fetch_wfs(
        "app:Isophonenbaender_EK",
        bbox,
        count=50,
    )

    features = _parse_features(body)

    values = {
        "lden": [],
        "lnight": [],
    }

    raw = []

    for feature in features:
        props = feature["properties"]

        art = _parse_int(
            props.get(
                "isophonenart_id"
            )
        )

        measure = _parse_float(
            props.get(
                "hh_measure"
            )
        )

        kind = ISOPHONE_KIND.get(art)

        if (
            kind is None
            or measure is None
        ):
            continue

        values[kind].append(
            measure
        )

        raw.append(
            {
                "kind": kind,
                "measure": measure,
                "class_id": _parse_int(
                    props.get(
                        "isophonenklasse_id"
                    )
                ),
            }
        )

    result = {}

    for kind in (
        "lden",
        "lnight",
    ):
        if values[kind]:
            lower = int(
                max(values[kind])
            )
        else:
            lower = None

        result[kind] = lower
        result[
            f"{kind}_band"
        ] = _band_label(
            kind,
            lower,
        )

    result["raw_isophones"] = raw

    return result


def _query_traffic(lat, lon):
    x, y = _webmercator(
        lat,
        lon,
    )

    # EPSG:3857 map distances are enlarged by
    # approximately 1/cos(latitude).
    cos_lat = math.cos(
        math.radians(lat)
    )

    if cos_lat < 0.1:
        cos_lat = 0.1

    search_ground_m = 2000.0

    search_map_m = (
        search_ground_m
        / cos_lat
    )

    bbox = (
        x - search_map_m,
        y - search_map_m,
        x + search_map_m,
        y + search_map_m,
    )

    candidates = []

    for layer, layer_type in (
        (
            "app:Verkehrsweg",
            "ULR",
        ),
        (
            "app:Verkehrsweg_EK",
            "EK",
        ),
    ):
        try:
            body = _fetch_wfs(
                layer,
                bbox,
                count=200,
            )

            features = (
                _parse_features(body)
            )

        except Exception:
            continue

        for feature in features:
            map_distance = (
                _feature_distance(
                    feature,
                    x,
                    y,
                )
            )

            if map_distance is None:
                continue

            ground_distance = (
                map_distance
                * cos_lat
            )

            if (
                ground_distance
                > search_ground_m
            ):
                continue

            candidates.append(
                {
                    "layer": layer_type,
                    "distance_m": (
                        ground_distance
                    ),
                    "feature": feature,
                }
            )

    if not candidates:
        return {
            "rail_distance_m": None,
            "traffic_layer": None,
            "annual_traffic": None,
            "trains_per_day": None,
            "traffic_day": None,
            "traffic_evening": None,
            "traffic_night": None,
            "traffic_total": None,
            "unique_rail_id": None,
        }

    candidates.sort(
        key=lambda item: (
            item["distance_m"],
            0
            if item["layer"] == "ULR"
            else 1,
        )
    )

    nearest = candidates[0]

    props = nearest[
        "feature"
    ]["properties"]

    annual_traffic = None

    if nearest["layer"] == "EK":
        annual_traffic = _parse_int(
            props.get("atf")
        )

    traffic_total = _parse_int(
        props.get("summe_gesamt")
    )

    # For ULR the detailed day/evening/night
    # values are retained separately. We do not
    # yet interpret their temporal unit until the
    # EBA data model has been checked explicitly.
    result = {
        "rail_distance_m": round(
            nearest["distance_m"],
            1,
        ),
        "traffic_layer": nearest["layer"],
        "annual_traffic": annual_traffic,
        "trains_per_day": (
            round(
                annual_traffic / 365.0,
                1,
            )
            if annual_traffic is not None
            else None
        ),
        "traffic_day": _parse_int(
            props.get("summe_tag")
        ),
        "traffic_evening": _parse_int(
            props.get("summe_abend")
        ),
        "traffic_night": _parse_int(
            props.get("summe_nacht")
        ),
        "traffic_total": traffic_total,
        "unique_rail_id": (
            props.get("uniquerail_id")
        ),
    }

    return result


def get_rail_noise(lat, lon):
    """
    Query EBA nationwide rail-noise mapping.

    Returns LDEN and LNight bands plus nearest
    federal railway traffic information.
    """

    lat = float(lat)
    lon = float(lon)

    isophones = _query_isophones(
        lat,
        lon,
    )

    traffic = _query_traffic(
        lat,
        lon,
    )

    result = {
        "source": "EBA_R4",
        "lat": lat,
        "lon": lon,
    }

    result.update(isophones)
    result.update(traffic)

    return result


def print_rail_noise(result):
    print(
        "EBA SCHIENENLÄRM"
    )
    print(
        "=" * 50
    )

    print(
        "Koordinate:",
        f'{result["lat"]:.6f},',
        f'{result["lon"]:.6f}',
    )

    print()

    print(
        "LDEN:   ",
        result["lden_band"],
        "dB(A)",
    )

    print(
        "LNight: ",
        result["lnight_band"],
        "dB(A)",
    )

    print()

    distance = result.get(
        "rail_distance_m"
    )

    if distance is not None:
        print(
            "Nächster EBA-Schienenweg:",
            f"{distance:.0f} m",
        )
    else:
        print(
            "Nächster EBA-Schienenweg:",
            "> 2 km / nicht gefunden",
        )

    print(
        "Verkehrslayer:",
        result.get(
            "traffic_layer"
        ),
    )

    annual = result.get(
        "annual_traffic"
    )

    if annual is not None:
        print(
            "Zugpassagen/Jahr:",
            f"{annual:,}".replace(
                ",",
                ".",
            ),
        )

        print(
            "Ø Zugpassagen/Tag:",
            result.get(
                "trains_per_day"
            ),
        )

    if result.get(
        "traffic_layer"
    ) == "ULR":

        print(
            "EBA summe_tag:",
            result.get(
                "traffic_day"
            ),
        )

        print(
            "EBA summe_abend:",
            result.get(
                "traffic_evening"
            ),
        )

        print(
            "EBA summe_nacht:",
            result.get(
                "traffic_night"
            ),
        )

        print(
            "EBA summe_gesamt:",
            result.get(
                "traffic_total"
            ),
        )

    if result.get(
        "unique_rail_id"
    ):
        print(
            "Rail-ID:",
            result[
                "unique_rail_id"
            ],
        )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Query EBA rail noise at a coordinate."
        )
    )

    parser.add_argument(
        "lat",
        type=float,
    )

    parser.add_argument(
        "lon",
        type=float,
    )

    parser.add_argument(
        "--json",
        action="store_true",
    )

    args = parser.parse_args()

    result = get_rail_noise(
        args.lat,
        args.lon,
    )

    if args.json:
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print_rail_noise(result)


if __name__ == "__main__":
    main()
