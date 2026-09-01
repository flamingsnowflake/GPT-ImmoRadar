import json
import math
import os
import time
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET

from pyproj import Transformer
from shapely.geometry import LineString, MultiLineString, Point, Polygon
from datetime import datetime, timezone


NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URLS = [
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]
USER_AGENT = os.environ.get(
    "NOMINATIM_USER_AGENT",
    "immobilien-monitor/1.0 "
    "(self-hosted; set NOMINATIM_USER_AGENT)"
)

_last_nominatim_request = 0.0


def _rate_limit_nominatim():
    global _last_nominatim_request

    now = time.monotonic()
    elapsed = now - _last_nominatim_request

    # Deutlich konservativer als 1 req/s.
    if elapsed < 2.0:
        time.sleep(2.0 - elapsed)

    _last_nominatim_request = time.monotonic()


def geocode_address(location):

    if not location:
        return None

    original = location.strip()

    queries = []

    # 1. Original, nur "(Kreis)" entfernen
    cleaned = original.replace("(Kreis)", "").strip()
    cleaned = cleaned.replace("  ", " ")

    queries.append(cleaned)

    # 2. Straße + Ort, Landkreis abschneiden
    parts = [
        part.strip()
        for part in cleaned.split(",")
        if part.strip()
    ]

    if len(parts) >= 2:
        queries.append(
            f"{parts[0]}, {parts[1]}"
        )

    # Deutschland ergänzen
    queries = [
        q if "Deutschland" in q
        else f"{q}, Deutschland"
        for q in queries
    ]

    # Duplikate entfernen
    queries = list(dict.fromkeys(queries))

    for query in queries:

        params = urllib.parse.urlencode({
            "q": query,
            "format": "jsonv2",
            "limit": 1,
            "countrycodes": "de"
        })

        url = f"{NOMINATIM_URL}?{params}"

        _rate_limit_nominatim()

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json"
            }
        )

        with urllib.request.urlopen(
            request,
            timeout=15
        ) as response:

            data = json.loads(
                response.read().decode("utf-8")
            )

        if not data:
            continue

        result = data[0]

        return {
            "latitude": float(result["lat"]),
            "longitude": float(result["lon"]),
            "display_name": result.get("display_name"),
            "geocode_query": query,
            "geocoded_at": datetime.now(
                timezone.utc
            ).isoformat()
        }

    return None

def haversine_km(lat1, lon1, lat2, lon2):

    radius = 6371.0088

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)

    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2) ** 2
        +
        math.cos(phi1)
        * math.cos(phi2)
        * math.sin(d_lambda / 2) ** 2
    )

    return (
        2
        * radius
        * math.atan2(
            math.sqrt(a),
            math.sqrt(1 - a)
        )
    )

WFS_URL = (
    "https://geodatenportal.sachsen-anhalt.de/"
    "ows_INSPIRE_LVermGeo_ATKIS_HY-N_WFS"
)

WFS_TYPENAME = "hy-n:WatercourseLink"

_transform_to_25832 = Transformer.from_crs(
    "EPSG:4326",
    "EPSG:25832",
    always_xy=True
)


def _bbox_4326(latitude, longitude, radius_km):

    # Für die WFS-Abfrage reicht eine geografische Näherung.
    # 1° Breitengrad ≈ 111 km
    lat_delta = radius_km / 111.0

    # Längengrad hängt vom Breitengrad ab.
    lon_delta = radius_km / (
        111.0 * math.cos(math.radians(latitude))
    )

    min_lat = latitude - lat_delta
    max_lat = latitude + lat_delta
    min_lon = longitude - lon_delta
    max_lon = longitude + lon_delta

    return (
        min_lat,
        min_lon,
        max_lat,
        max_lon
    )


def _parse_gml_poslist(text):

    if not text:
        return []

    values = [
        float(value)
        for value in text.split()
    ]

    if len(values) < 4:
        return []

    if len(values) % 2 != 0:
        return []

    coords = []

    # WFS liefert EPSG:25832,
    # also X/Y = Easting/Northing.
    for index in range(
        0,
        len(values),
        2
    ):

        coords.append(
            (
                values[index],
                values[index + 1]
            )
        )

    return coords


def find_nearest_water(
    latitude,
    longitude,
    radius_m=5000
):

    radius_km = radius_m / 1000.0

    (
        min_lat,
        min_lon,
        max_lat,
        max_lon
    ) = _bbox_4326(
        latitude,
        longitude,
        radius_km
    )

    # --------------------------------------------------------
    # WFS-BBOX
    #
    # Wichtig:
    # Bei urn:ogc:def:crs:EPSG::4326 erwartet dieser
    # WFS die Achsenreihenfolge:
    #
    # latitude, longitude
    #
    # also:
    # minLat,minLon,maxLat,maxLon
    # --------------------------------------------------------

    bbox = (
        f"{min_lat},{min_lon},"
        f"{max_lat},{max_lon},"
        f"urn:ogc:def:crs:EPSG::4326"
    )

    params = urllib.parse.urlencode({
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": WFS_TYPENAME,

        # Geometrie direkt metrisch zurückgeben.
        "srsName": "urn:ogc:def:crs:EPSG::25832",

        "bbox": bbox,

        "outputFormat":
            "application/gml+xml; version=3.2"
    })

    url = f"{WFS_URL}?{params}"

    print(
        f"WFS WATER: querying {radius_km:.1f} km radius",
        flush=True
    )

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": (
                "application/gml+xml,"
                "application/xml,"
                "text/xml"
            )
        }
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=20
        ) as response:

            raw = response.read()

    except Exception as exc:

        raise RuntimeError(
            f"WFS request failed: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    # --------------------------------------------------------
    # XML parsen
    # --------------------------------------------------------

    try:

        root = ET.fromstring(raw)

    except ET.ParseError as exc:

        raise RuntimeError(
            f"WFS returned invalid XML: {exc}"
        ) from exc

    # --------------------------------------------------------
    # Prüfen, ob der Server einen OGC-Fehler geschickt hat
    # --------------------------------------------------------

    root_name = root.tag.lower()

    if (
        "exceptionreport" in root_name
        or "serviceexception" in root_name
    ):

        error_text = " ".join(
            text.strip()
            for text in root.itertext()
            if text.strip()
        )

        raise RuntimeError(
            f"WFS error: {error_text}"
        )

    # --------------------------------------------------------
    # Grundstückspunkt in EPSG:25832 transformieren
    # --------------------------------------------------------

    point_x, point_y = _transform_to_25832.transform(
        longitude,
        latitude
    )

    property_point = Point(
        point_x,
        point_y
    )

    # --------------------------------------------------------
    # GML-Geometrien auslesen
    # --------------------------------------------------------

    namespace = {
        "gml": "http://www.opengis.net/gml/3.2"
    }

    nearest_distance_m = None
    nearest_geometry = None

    feature_count = 0

    # Die Geometrien liegen typischerweise als
    # gml:posList vor.
    for poslist in root.findall(
        ".//gml:posList",
        namespace
    ):

        coords = _parse_gml_poslist(
            poslist.text
        )

        if len(coords) < 2:
            continue

        feature_count += 1

        try:

            line = LineString(
                coords
            )

        except Exception:
            continue

        distance_m = property_point.distance(
            line
        )

        if (
            nearest_distance_m is None
            or distance_m < nearest_distance_m
        ):

            nearest_distance_m = distance_m
            nearest_geometry = line

    print(
        f"WFS WATER: "
        f"{feature_count} line geometry/ies parsed",
        flush=True
    )

    if nearest_distance_m is None:

        return None

    # Sicherheitscheck:
    # Durch die rechteckige BBOX könnten theoretisch
    # Linien gefunden werden, die außerhalb des gewünschten
    # Kreisradius liegen.
    if nearest_distance_m > radius_m:

        return None

    return {
        "distance_km":
            nearest_distance_m / 1000.0,

        "name":
            None,

        "waterway":
            "watercourse",

        "source":
            "LVermGeo Sachsen-Anhalt ATKIS HY-N WFS",

        "feature_count":
            feature_count
    }
def find_best_water(
    latitude,
    longitude,
    radius_m=3000
):

    radius_km = radius_m / 1000.0

    (
        min_lat,
        min_lon,
        max_lat,
        max_lon
    ) = _bbox_4326(
        latitude,
        longitude,
        radius_km
    )

    bbox = (
        f"{min_lat},{min_lon},"
        f"{max_lat},{max_lon},"
        f"urn:ogc:def:crs:EPSG::4326"
    )

    wfs_url = (
        "https://geodatenportal.sachsen-anhalt.de/"
        "ows_INSPIRE_LVermGeo_ATKIS_HY-P_WFS"
    )

    params = urllib.parse.urlencode({
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": "hy-p:Watercourse",
        "srsName": "urn:ogc:def:crs:EPSG::25832",
        "bbox": bbox,
        "count": 2000,
        "outputFormat":
            "application/gml+xml; version=3.2"
    })

    url = f"{wfs_url}?{params}"

    print(
        f"WFS WATER QUALITY: querying "
        f"{radius_km:.1f} km radius",
        flush=True
    )

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": (
                "application/gml+xml,"
                "application/xml,"
                "text/xml"
            )
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=30
    ) as response:
        raw = response.read()

    root = ET.fromstring(raw)

    x, y = _transform_to_25832.transform(
        longitude,
        latitude
    )

    property_point = Point(
        x,
        y
    )

    candidates = []

    members = [
        elem
        for elem in root.iter()
        if elem.tag.endswith("member")
    ]

    for member in members:

        feature = next(
            iter(member),
            None
        )

        if feature is None:
            continue

        lower = None
        upper = None
        local_id = None
        origin = None

        for elem in feature.iter():

            tag = elem.tag.split("}")[-1]

            text = (
                elem.text.strip()
                if elem.text
                and elem.text.strip()
                else None
            )

            if not text:
                continue

            if tag == "lower":
                try:
                    lower = float(text)
                except ValueError:
                    pass

            elif tag == "upper":
                try:
                    upper = float(text)
                except ValueError:
                    pass

            elif tag == "localId":
                # Es können mehrere localId vorkommen.
                # Wir behalten die letzte konkrete Feature-ID.
                local_id = text

            elif tag == "origin":
                origin = text

        best_feature_distance = None

        for poslist in feature.iter():

            if not poslist.tag.endswith(
                "posList"
            ):
                continue

            coords = _parse_gml_poslist(
                poslist.text
            )

            if len(coords) < 2:
                continue

            geom = None
            geometry_type = None

            # Geschlossene Koordinatenfolge zuerst als Polygon versuchen.
            if (
                len(coords) >= 4
                and coords[0] == coords[-1]
            ):
                try:
                    geom = Polygon(
                        coords
                    )
                    geometry_type = "polygon"
                except Exception:
                    pass

            if geom is None:
                try:
                    geom = LineString(
                        coords
                    )
                    geometry_type = "line"
                except Exception:
                    continue

            distance_m = (
                property_point.distance(
                    geom
                )
            )

            if (
                best_feature_distance is None
                or distance_m
                < best_feature_distance
            ):
                best_feature_distance = (
                    distance_m
                )

        if best_feature_distance is None:
            continue

        if best_feature_distance > radius_m:
            continue

        distance_km = (
            best_feature_distance / 1000.0
        )

        # ----------------------------------------------------
        # Gewässerklasse aus Breitenklasse
        # ----------------------------------------------------

        if geometry_type == "polygon":

            # Ein Wasserlauf, der flächenhaft modelliert wird,
            # ist deutlich breiter als ein einfacher Bachlauf.
            water_class = "major_river"
            type_points = 12

        elif upper is None:

            water_class = "unknown"
            type_points = 4

        elif upper <= 3:

            water_class = "stream"
            type_points = 6

        elif upper <= 6:

            water_class = "small_river"
            type_points = 9

        elif upper <= 12:

            water_class = "river"
            type_points = 11

        else:

            water_class = "major_river"
            type_points = 12

        # ----------------------------------------------------
        # Distanzpunkte
        # ----------------------------------------------------

        if distance_km <= 0.5:
            distance_points = 8

        elif distance_km <= 1.0:
            distance_points = 7

        elif distance_km <= 2.0:
            distance_points = 5

        elif distance_km <= 3.0:
            distance_points = 3

        else:
            distance_points = 0

        water_score = (
            type_points
            + distance_points
        )

        candidates.append({
            "distance_km":
                distance_km,

            "water_class":
                water_class,

            "width_lower_m":
                lower,

            "width_upper_m":
                upper,

            "geometry_type":
                geometry_type,

            "type_points":
                type_points,

            "distance_points":
                distance_points,

            "water_score":
                water_score,

            "osm_type":
                None,

            "osm_id":
                local_id,

            "name":
                None,

            "waterway":
                water_class,

            "origin":
                origin,

            "source":
                "LVermGeo Sachsen-Anhalt "
                "ATKIS HY-P WFS"
        })

    if not candidates:
        return None

    # Höchster Wasserwert gewinnt.
    # Bei Gleichstand gewinnt das nähere Gewässer.
    candidates.sort(
        key=lambda item: (
            -item["water_score"],
            item["distance_km"]
        )
    )

    best = candidates[0]

    print(
        f"WATER BEST: "
        f"{best['water_class']} | "
        f"{best['distance_km']:.2f} km | "
        f"{best['water_score']}/20",
        flush=True
    )

    return best


#
# BUILDINGS
#

BUILDING_WFS_URL = (
    "https://geodatenportal.sachsen-anhalt.de/"
    "ows_INSPIRE_LVermGeo_ALKIS_BU_WFS"
)

BUILDING_TYPENAME = "bu-core2d:Building"


def _parse_gml_polygon(poslist_text):

    if not poslist_text:
        return None

    try:

        values = [
            float(value)
            for value in poslist_text.split()
        ]

    except ValueError:
        return None

    if len(values) < 6:
        return None

    if len(values) % 2 != 0:
        return None

    coords = []

    for index in range(
        0,
        len(values),
        2
    ):

        coords.append(
            (
                values[index],
                values[index + 1]
            )
        )

    try:

        polygon = Polygon(coords)

    except Exception:
        return None

    if polygon.is_empty:
        return None

    if not polygon.is_valid:
        polygon = polygon.buffer(0)

    if polygon.is_empty:
        return None

    return polygon


def find_neighbour_buildings(
    latitude,
    longitude,
    radius_m=500,
    ignore_within_m=20
):

    # --------------------------------------------------------
    # Grundstückspunkt in EPSG:25832
    # --------------------------------------------------------

    point_x, point_y = _transform_to_25832.transform(
        longitude,
        latitude
    )

    property_point = Point(
        point_x,
        point_y
    )

    # --------------------------------------------------------
    # Bounding Box erzeugen
    # --------------------------------------------------------

    radius_km = radius_m / 1000.0

    (
        min_lat,
        min_lon,
        max_lat,
        max_lon
    ) = _bbox_4326(
        latitude,
        longitude,
        radius_km
    )

    # ACHTUNG:
    # EPSG:4326 beim WFS hier in lat,lon-Reihenfolge.
    bbox = (
        f"{min_lat},{min_lon},"
        f"{max_lat},{max_lon},"
        f"urn:ogc:def:crs:EPSG::4326"
    )

    params = urllib.parse.urlencode({
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": BUILDING_TYPENAME,
        "srsName": "urn:ogc:def:crs:EPSG::25832",
        "bbox": bbox,
        "outputFormat":
            "application/gml+xml; version=3.2"
    })

    url = (
        f"{BUILDING_WFS_URL}?{params}"
    )

    print(
        f"WFS BUILDINGS: querying "
        f"{radius_m} m radius",
        flush=True
    )

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": (
                "application/gml+xml,"
                "application/xml,"
                "text/xml"
            )
        }
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=20
        ) as response:

            raw = response.read()

    except Exception as exc:

        raise RuntimeError(
            f"Building WFS request failed: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    # --------------------------------------------------------
    # XML
    # --------------------------------------------------------

    try:

        root = ET.fromstring(raw)

    except ET.ParseError as exc:

        raise RuntimeError(
            f"Building WFS returned invalid XML: {exc}"
        ) from exc

    if "exceptionreport" in root.tag.lower():

        error_text = " ".join(
            text.strip()
            for text in root.itertext()
            if text.strip()
        )

        raise RuntimeError(
            f"Building WFS error: {error_text}"
        )

    namespace = {
        "gml": "http://www.opengis.net/gml/3.2"
    }

    distances = []

    polygon_count = 0

    # --------------------------------------------------------
    # Gebäudegeometrien parsen
    # --------------------------------------------------------

    for poslist in root.findall(
        ".//gml:posList",
        namespace
    ):

        polygon = _parse_gml_polygon(
            poslist.text
        )

        if polygon is None:
            continue

        polygon_count += 1

        distance_m = property_point.distance(
            polygon
        )

        # Vermutlich eigenes Gebäude / Gebäude
        # direkt auf dem Grundstück.
        if distance_m < ignore_within_m:
            continue

        # Rechteckige WFS-BBOX kann Gebäude etwas
        # außerhalb des gewünschten Radius enthalten.
        if distance_m > radius_m:
            continue

        distances.append(
            distance_m
        )

    # --------------------------------------------------------
    # Ergebnis
    # --------------------------------------------------------

    distances.sort()

    nearest = (
        distances[0]
        if distances
        else None
    )

    result = {
        "nearest_building_m": nearest,

        "buildings_100m": sum(
            1
            for distance in distances
            if distance <= 100
        ),

        "buildings_250m": sum(
            1
            for distance in distances
            if distance <= 250
        ),

        "buildings_500m": sum(
            1
            for distance in distances
            if distance <= 500
        ),

        "feature_count":
            polygon_count
    }

    print(
        f"WFS BUILDINGS: "
        f"{polygon_count} polygon(s) parsed | "
        f"100m={result['buildings_100m']} | "
        f"250m={result['buildings_250m']} | "
        f"500m={result['buildings_500m']}",
        flush=True
    )

    return result
