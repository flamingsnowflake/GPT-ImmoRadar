import hashlib
import html
import json
import re
from urllib.parse import urlparse

from urllib.request import Request, urlopen

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0 Safari/537.36"
)


def detect_source(url):
    host = (
        urlparse(url)
        .netloc
        .lower()
        .split(":")[0]
    )

    if host.startswith("www."):
        host = host[4:]

    if (
        host == "immowelt.de"
        or host.endswith(".immowelt.de")
    ):
        return "immowelt"

    if (
        host == "immobilienscout24.de"
        or host.endswith(".immobilienscout24.de")
        or host == "is24.de"
        or host.endswith(".is24.de")
    ):
        return "immoscout24"

    # Bei Maklerseiten wird die Domain selbst zur Quelle.
    return host.replace(".", "_")


def detect_portal_id(url, source):
    if source == "immowelt":
        match = re.search(
            r"/expose/"
            r"([A-Za-z0-9-]+)",
            url
        )

        if match:
            return match.group(1)

    if source == "immoscout24":
        match = re.search(
            r"/expose/(\d+)",
            url
        )

        if match:
            return match.group(1)

    # Stabiler Fallback für beliebige Maklerseiten.
    normalized = url.split("#", 1)[0]

    return hashlib.sha256(
        normalized.encode("utf-8")
    ).hexdigest()[:24]


def fetch_page(url):
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language":
                "de-DE,de;q=0.9,en;q=0.7",
            "Accept":
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,*/*;q=0.8",
        },
    )

    with urlopen(
        request,
        timeout=25,
    ) as response:
        final_url = response.geturl()

        charset = (
            response.headers.get_content_charset()
            or "utf-8"
        )

        source = response.read().decode(
            charset,
            errors="replace"
        )

    return (
        final_url,
        source,
    )


def parse_number(value):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    value = str(value)
    value = value.replace("\xa0", " ")

    match = re.search(
        r"[\d][\d.\s]*(?:,\d+)?",
        value
    )

    if not match:
        return None

    text = match.group(0)
    text = text.replace(" ", "")

    if "," in text:
        text = text.replace(".", "")
        text = text.replace(",", ".")
    else:
        # 160.000 -> 160000
        parts = text.split(".")

        if (
            len(parts) > 1
            and all(
                len(part) == 3
                for part in parts[1:]
            )
        ):
            text = "".join(parts)

    try:
        return float(text)
    except ValueError:
        return None


def _preview_blacklist_property_type(
    object_type,
):
    """
    Leitet nur den Typ ab, den die frühe Blacklist-Prüfung
    sicher kennen muss.

    Bei Grundstücken dürfen Haustyp-Begriffe wie
    "Doppelhaushälfte" in einer Nutzungsbeschreibung nicht
    als Blacklist-Treffer gelten. Andere Typen bleiben hier
    bewusst unbestimmt und werden später von der normalen
    Property-Type-Pipeline klassifiziert.
    """

    normalized = (
        str(object_type or "")
        .strip()
        .lower()
    )

    if (
        "grundstück" in normalized
        or "grundstueck" in normalized
    ):
        return "land"

    return None


def html_to_text(source):
    source = re.sub(
        r"(?is)<script\b.*?</script>",
        " ",
        source
    )

    source = re.sub(
        r"(?is)<style\b.*?</style>",
        " ",
        source
    )

    source = re.sub(
        r"(?s)<[^>]+>",
        " ",
        source
    )

    source = html.unescape(source)

    return re.sub(
        r"\s+",
        " ",
        source
    ).strip()


def extract_meta(source, key):
    patterns = [
        (
            r'<meta[^>]+property=["\']'
            + re.escape(key)
            + r'["\'][^>]+content=["\']'
            + r'(.*?)["\']'
        ),
        (
            r'<meta[^>]+content=["\']'
            + r'(.*?)["\'][^>]+property=["\']'
            + re.escape(key)
            + r'["\']'
        ),
        (
            r'<meta[^>]+name=["\']'
            + re.escape(key)
            + r'["\'][^>]+content=["\']'
            + r'(.*?)["\']'
        ),
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            source,
            re.I | re.S
        )

        if match:
            return html.unescape(
                match.group(1)
            ).strip()

    return None


def iter_jsonld(source):
    for match in re.finditer(
        r'<script[^>]+type=["\']'
        r'application/ld\+json'
        r'["\'][^>]*>(.*?)</script>',
        source,
        re.I | re.S
    ):
        raw = html.unescape(
            match.group(1)
        ).strip()

        try:
            data = json.loads(raw)
        except Exception:
            continue

        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    yield item

        elif isinstance(data, dict):
            graph = data.get("@graph")

            if isinstance(graph, list):
                for item in graph:
                    if isinstance(item, dict):
                        yield item

            yield data


def recursive_find(obj, keys):
    if isinstance(keys, str):
        keys = {keys}
    else:
        keys = set(keys)

    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in keys:
                if value not in (
                    None,
                    "",
                    [],
                    {}
                ):
                    return value

        for value in obj.values():
            result = recursive_find(
                value,
                keys
            )

            if result not in (
                None,
                "",
                [],
                {}
            ):
                return result

    elif isinstance(obj, list):
        for item in obj:
            result = recursive_find(
                item,
                keys
            )

            if result not in (
                None,
                "",
                [],
                {}
            ):
                return result

    return None


def value_from_schema(value):
    if isinstance(value, dict):
        for key in (
            "value",
            "amount",
            "price",
        ):
            if key in value:
                return value[key]

    return value


def address_from_schema(value):
    if isinstance(value, str):
        return value

    if not isinstance(value, dict):
        return None

    parts = [
        value.get("streetAddress"),
        value.get("postalCode"),
        value.get("addressLocality"),
        value.get("addressRegion"),
    ]

    return ", ".join(
        str(part).strip()
        for part in parts
        if part
    ) or None


def extract_jsonld_data(source):
    result = {}

    for item in iter_jsonld(source):
        if not result.get("title"):
            result["title"] = recursive_find(
                item,
                [
                    "name",
                    "headline",
                ]
            )

        if not result.get("description"):
            result["description"] = recursive_find(
                item,
                "description"
            )

        if result.get("price") is None:
            price = recursive_find(
                item,
                "price"
            )

            result["price"] = parse_number(
                value_from_schema(price)
            )

        if not result.get("location"):
            address = recursive_find(
                item,
                "address"
            )

            result["location"] = (
                address_from_schema(address)
            )

        if result.get("rooms") is None:
            rooms = recursive_find(
                item,
                [
                    "numberOfRooms",
                    "numberOfBedrooms",
                ]
            )

            result["rooms"] = parse_number(
                value_from_schema(rooms)
            )

        if result.get("living_area") is None:
            floor_size = recursive_find(
                item,
                "floorSize"
            )

            result["living_area"] = parse_number(
                value_from_schema(
                    floor_size
                )
            )

        if result.get("plot_area") is None:
            lot_size = recursive_find(
                item,
                [
                    "lotSize",
                    "landSize",
                ]
            )

            result["plot_area"] = parse_number(
                value_from_schema(
                    lot_size
                )
            )

    return result


def regex_area(text, labels):
    for label in labels:
        pattern = (
            re.escape(label)
            + r".{0,35}?"
            + r"([\d.\s]+(?:,\d+)?)"
            + r"\s*m(?:²|2)"
        )

        match = re.search(
            pattern,
            text,
            re.I
        )

        if match:
            return parse_number(
                match.group(1)
            )

    return None


def extract_fallback_data(source):
    text = html_to_text(source)

    title = (
        extract_meta(source, "og:title")
        or extract_meta(
            source,
            "twitter:title"
        )
    )

    if not title:
        match = re.search(
            r"<title[^>]*>(.*?)</title>",
            source,
            re.I | re.S
        )

        if match:
            title = html.unescape(
                re.sub(
                    r"\s+",
                    " ",
                    match.group(1)
                )
            ).strip()

    description = (
        extract_meta(
            source,
            "og:description"
        )
        or extract_meta(
            source,
            "description"
        )
    )

    price = None

    match = re.search(
        r"([\d.\s]+(?:,\d{1,2})?)"
        r"\s*(?:€|EUR)",
        text,
        re.I
    )

    if match:
        price = parse_number(
            match.group(1)
        )

    living_area = regex_area(
        text,
        [
            "Wohnfläche",
            "Wohnflaeche",
            "living area",
        ]
    )

    plot_area = regex_area(
        text,
        [
            "Grundstück",
            "Grundstücksfläche",
            "Grundstueck",
            "plot",
            "lot size",
        ]
    )

    rooms = None

    match = re.search(
        r"([\d.,]+)\s*Zimmer",
        text,
        re.I
    )

    if match:
        rooms = parse_number(
            match.group(1)
        )

    return {
        "title": title,
        "description": description,
        "price": price,
        "living_area": living_area,
        "plot_area": plot_area,
        "rooms": rooms,
        "raw_text": text,
    }


def merge_values(primary, fallback):
    result = dict(fallback)

    for key, value in primary.items():
        if value not in (
            None,
            "",
            [],
            {}
        ):
            result[key] = value

    return result


def parse_property_page(url):
    final_url, source = fetch_page(url)

    portal = detect_source(
        final_url
    )

    portal_id = detect_portal_id(
        final_url,
        portal
    )

    schema_data = extract_jsonld_data(
        source
    )

    fallback_data = extract_fallback_data(
        source
    )

    data = merge_values(
        schema_data,
        fallback_data
    )

    raw_text = (
        data.get("raw_text")
        or html_to_text(source)
    )

    property_data = {
        "portal": portal,
        "portal_id": portal_id,
        "url": final_url,
        "title": data.get("title"),
        "location": data.get("location"),
        "price": data.get("price"),
        "living_area": data.get(
            "living_area"
        ),
        "rooms": data.get("rooms"),
        "plot_area": data.get(
            "plot_area"
        ),
        "commission_free": False,
        "raw_text": raw_text,
    }

    return property_data


def get_existing_property(portal, portal_id):
    """
    Prüft, ob das Objekt bereits im Immobilien-Monitor
    vorhanden ist.
    """

    from monitor import get_db

    conn = get_db()

    try:
        cursor = conn.execute(
            """
            SELECT *
            FROM properties
            WHERE portal = ?
              AND portal_id = ?
            """,
            (
                portal,
                portal_id,
            )
        )

        row = cursor.fetchone()

        if row is None:
            return None

        columns = [
            column[0]
            for column in cursor.description
        ]

        return dict(
            zip(columns, row)
        )

    finally:
        conn.close()


def import_generic_property_url(url):
    """
    Importiert eine normale Immobilien-/Makler-Webseite,
    die direkt vom Monitor-Server abrufbar ist.
    """

    from monitor import (
        get_db,
        process_property,
    )

    property_data = parse_property_page(
        url
    )

    conn = get_db()

    try:
        result = process_property(
            conn,
            property_data,
            source_message_id=None,
            notify=False,

            # Manuell an Telegram geschickte Objekte
            # NICHT durch Blacklist/Spamfilter verwerfen.
            apply_filters=False,
        )

        conn.commit()

        return result

    finally:
        conn.close()


def import_immowelt_url(url):
    """
    Importiert Immowelt-Objekte über den Telegram-
    Webpage-Preview.

    Hintergrund:
    Direkte HTTP-Requests vom Monitor-Server werden
    von Immowelt häufig mit HTTP 403 blockiert.

    Telegram kann für dieselbe URL aber einen
    Webpage-Preview liefern. Dieser enthält derzeit
    typischerweise:

        Grundstück 18000 € zum Kauf
        Genthin,Genthin (39307)

    Daraus können wir mindestens Typ, Preis und Ort
    gewinnen und das Objekt anschließend durch die
    normale Monitor-Pipeline schicken.
    """

    portal_id = detect_portal_id(
        url,
        "immowelt"
    )

    if not portal_id:
        raise RuntimeError(
            "Keine Immowelt-Objekt-ID "
            "in der URL erkannt."
        )

    # --------------------------------------------------------
    # Bereits vorhandenes Objekt
    # --------------------------------------------------------

    existing = get_existing_property(
        "immowelt",
        portal_id
    )

    from monitor import (
        get_db,
        is_blacklisted,
        process_property,
    )

    from telegram_preview import (
        get_telegram_preview,
    )

    # --------------------------------------------------------
    # Telegram-Webpage-Preview holen
    # --------------------------------------------------------

    try:
        preview = get_telegram_preview(
            url
        )

    except Exception as exc:
        print(
            f"TELEGRAM PREVIEW ERROR: "
            f"{portal_id} | "
            f"{type(exc).__name__}: "
            f"{exc}",
            flush=True
        )

        preview = None

    # --------------------------------------------------------
    # Vorhandenes Objekt:
    # wie bisher zurückliefern, aber Preview weiterhin
    # für die Blacklist prüfen.
    # --------------------------------------------------------

    if existing is not None:

        if preview:

            preview_title = (
                preview.get("title")
                or ""
            )

            preview_description = (
                preview.get("description")
                or ""
            )

            print(
                f"TELEGRAM PREVIEW: "
                f"{portal_id} | "
                f"{preview_title}",
                flush=True
            )

            existing[
                "telegram_preview_title"
            ] = preview_title

            existing[
                "telegram_preview_description"
            ] = preview_description

            if is_blacklisted(
                preview_title,
                preview_description,
                property_type=existing.get(
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
                    "property_data": existing,
                    "property_id": existing.get(
                        "id"
                    ),
                    "duplicate": True,
                }

        return {
            "status": "existing",
            "property_data": existing,
            "property_id": existing.get("id"),
            "duplicate": True,
        }

    # --------------------------------------------------------
    # Neues Objekt:
    # ohne Telegram-Preview können wir nichts Sinnvolles
    # importieren.
    # --------------------------------------------------------

    if not preview:
        raise RuntimeError(
            "Immowelt blockiert den direkten "
            "Abruf und Telegram konnte keinen "
            "Webpage-Preview liefern."
        )

    preview_title = (
        preview.get("title")
        or ""
    ).strip()

    preview_description = (
        preview.get("description")
        or ""
    ).strip()

    print(
        f"TELEGRAM PREVIEW IMPORT: "
        f"{portal_id} | "
        f"{preview_title}",
        flush=True
    )

    if not preview_title:
        raise RuntimeError(
            "Telegram hat für das Immowelt-Objekt "
            "keinen Titel geliefert."
        )

    # --------------------------------------------------------
    # Typ / Preis / Ort aus dem Immowelt-Preview lesen.
    #
    # Beispiel:
    #
    # Grundstück 18000 € zum Kauf
    # Genthin,Genthin (39307)
    # --------------------------------------------------------

    match = re.match(
        r"^(?P<object_type>.+?)"
        r"\s+"
        r"(?P<price>[\d.\s]+(?:,\d{1,2})?)"
        r"\s*€"
        r"\s+zum\s+"
        r"(?:Kauf|Miete)"
        r"\s+"
        r"(?P<location>.+)$",
        preview_title,
        re.I
    )

    object_type = None
    price = None
    location = None

    if match:

        object_type = (
            match.group("object_type")
            or ""
        ).strip()

        price = parse_number(
            match.group("price")
        )

        location = (
            match.group("location")
            or ""
        ).strip()

        # Immowelt liefert z.B.
        #
        # Genthin,Genthin (39307)
        #
        # Für Geocoding und Anzeige etwas sauberer:
        location = re.sub(
            r",(?=\S)",
            ", ",
            location
        )

    else:

        print(
            f"IMMOWELT PREVIEW PARSE WARNING: "
            f"{portal_id} | "
            f"{preview_title}",
            flush=True
        )

    # --------------------------------------------------------
    # Ohne Ort ist die normale Geo-/Scoring-Pipeline
    # für unseren Monitor nicht sinnvoll.
    # --------------------------------------------------------

    if not location:
        raise RuntimeError(
            "Telegram konnte das Immowelt-Objekt "
            "lesen, aber der Ort konnte nicht aus "
            "dem Preview erkannt werden."
        )

    raw_text_parts = [
        preview_title,
        preview_description,
    ]

    raw_text = "\n".join(
        part
        for part in raw_text_parts
        if part
    )

    property_data = {
        "portal": "immowelt",
        "portal_id": portal_id,
        "title": preview_title,
        "url": url,
        "location": location,
        "price": price,
        "living_area": None,
        "rooms": None,
        "plot_area": None,
        "commission_free": 0,
        "raw_text": raw_text,
        "telegram_preview_title":
            preview_title,
        "telegram_preview_description":
            preview_description,
    }

    # --------------------------------------------------------
    # Blacklist prüfen.
    #
    # Manuell gesendete Objekte umgehen später innerhalb
    # process_property() die normalen Filter. Deshalb den
    # Telegram-Inhalt hier vorher explizit prüfen.
    # --------------------------------------------------------

    if is_blacklisted(
        preview_title,
        preview_description,
        property_type=(
            _preview_blacklist_property_type(
                object_type
            )
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

    # --------------------------------------------------------
    # Normale Monitor-Pipeline:
    #
    # - property_type
    # - Geo
    # - Wasser
    # - Nachbarn
    # - Bebaubarkeit
    # - Score
    # - Datenbank
    #
    # apply_filters=False:
    # manueller Telegram-Import soll nicht erneut durch
    # spam_objects / die allgemeinen Importfilter laufen.
    # Die Preview-Blacklist wurde oben bereits geprüft.
    # --------------------------------------------------------

    conn = get_db()

    try:

        result = process_property(
            conn,
            property_data,
            source_message_id=None,
            notify=False,
            apply_filters=False,
        )

        conn.commit()

        return result

    finally:
        conn.close()


def import_immoscout_url(url):
    """
    Importiert ImmoScout24-Objekte über den
    Telegram-Webpage-Preview.

    Direkte HTTP-Aufrufe werden von ImmoScout24
    häufig durch die Imperva-Robot-Prüfung blockiert.
    Telegram kann das Exposé dagegen als Preview lesen.
    """

    portal_id = detect_portal_id(
        url,
        "immoscout24"
    )

    if not portal_id:
        raise RuntimeError(
            "Keine ImmoScout24-Objekt-ID "
            "in der URL erkannt."
        )

    # --------------------------------------------------------
    # Bereits vorhandenes Objekt
    # --------------------------------------------------------

    existing = get_existing_property(
        "immoscout24",
        portal_id
    )

    from monitor import (
        get_db,
        is_blacklisted,
        process_property,
    )

    from telegram_preview import (
        get_telegram_preview,
    )

    # --------------------------------------------------------
    # Telegram-Webpage-Preview holen
    # --------------------------------------------------------

    try:
        preview = get_telegram_preview(
            url
        )

    except Exception as exc:
        print(
            f"TELEGRAM PREVIEW ERROR: "
            f"{portal_id} | "
            f"{type(exc).__name__}: "
            f"{exc}",
            flush=True
        )

        preview = None

    # --------------------------------------------------------
    # Bereits vorhandenes Objekt
    # --------------------------------------------------------

    if existing is not None:

        if preview:

            preview_title = (
                preview.get("title")
                or ""
            ).strip()

            preview_description = (
                preview.get("description")
                or ""
            ).strip()

            print(
                f"TELEGRAM PREVIEW IS24: "
                f"{portal_id} | "
                f"{preview_title}",
                flush=True
            )

            existing[
                "telegram_preview_title"
            ] = preview_title

            existing[
                "telegram_preview_description"
            ] = preview_description

            if is_blacklisted(
                preview_title,
                preview_description,
                property_type=existing.get(
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
                    "property_data": existing,
                    "property_id": existing.get(
                        "id"
                    ),
                    "duplicate": True,
                }

        return {
            "status": "existing",
            "property_data": existing,
            "property_id": existing.get("id"),
            "duplicate": True,
        }

    # --------------------------------------------------------
    # Neues Objekt
    # --------------------------------------------------------

    if not preview:
        raise RuntimeError(
            "ImmoScout24 blockiert den direkten "
            "Abruf und Telegram konnte keinen "
            "Webpage-Preview liefern."
        )

    preview_title = (
        preview.get("title")
        or ""
    ).strip()

    preview_description = (
        preview.get("description")
        or ""
    ).strip()

    print(
        f"TELEGRAM PREVIEW IS24 IMPORT: "
        f"{portal_id} | "
        f"{preview_title}",
        flush=True
    )

    if not preview_title:
        raise RuntimeError(
            "Telegram hat für das "
            "ImmoScout24-Objekt keinen Titel geliefert."
        )

    # --------------------------------------------------------
    # IS24-Preview auswerten.
    #
    # Beispiel:
    #
    # Villa zum Kauf (Haus/Kauf):
    # 9 Zimmer - 356 qm - Seevorstadt-Ost
    # bei ImmobilienScout24
    # (Scout-ID: 169517832)
    # --------------------------------------------------------

    object_type = None
    rooms = None
    living_area = None
    location = None

    match = re.match(
        r"^(?P<object_type>.+?)"
        r"\s+zum\s+(?:Kauf|Miete)"
        r"\s+\([^)]+\):\s*"
        r"(?P<rooms>[\d.,]+)\s+Zimmer"
        r"\s*-\s*"
        r"(?P<living_area>[\d.,]+)\s+qm"
        r"\s*-\s*"
        r"(?P<location>.+?)"
        r"\s+bei\s+ImmobilienScout24"
        r"(?:\s+\(Scout-ID:\s*\d+\))?"
        r"\s*$",
        preview_description,
        re.I
    )

    if match:

        object_type = (
            match.group("object_type")
            or ""
        ).strip()

        rooms = parse_number(
            match.group("rooms")
        )

        living_area = parse_number(
            match.group("living_area")
        )

        location = (
            match.group("location")
            or ""
        ).strip()

    else:

        print(
            f"IS24 PREVIEW PARSE WARNING: "
            f"{portal_id} | "
            f"{preview_description}",
            flush=True
        )

    if not location:
        raise RuntimeError(
            "Telegram konnte das ImmoScout24-Objekt "
            "lesen, aber der Ort konnte nicht aus "
            "dem Preview erkannt werden."
        )

    raw_text_parts = [
        preview_title,
        preview_description,
    ]

    raw_text = "\n".join(
        part
        for part in raw_text_parts
        if part
    )

    property_data = {
        "portal": "immoscout24",
        "portal_id": portal_id,
        "title": preview_title,
        "url": url,
        "location": location,

        # Im Telegram-Preview von IS24
        # derzeit nicht enthalten.
        "price": None,

        "living_area": living_area,
        "rooms": rooms,
        "plot_area": None,
        "commission_free": 0,
        "raw_text": raw_text,
        "telegram_preview_title":
            preview_title,
        "telegram_preview_description":
            preview_description,
    }

    # --------------------------------------------------------
    # Blacklist
    # --------------------------------------------------------

    if is_blacklisted(
        preview_title,
        preview_description,
        property_type=(
            _preview_blacklist_property_type(
                object_type
            )
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

    # --------------------------------------------------------
    # Normale Monitor-Pipeline
    # --------------------------------------------------------

    conn = get_db()

    try:

        result = process_property(
            conn,
            property_data,
            source_message_id=None,
            notify=False,
            apply_filters=False,
        )

        conn.commit()

        return result

    finally:
        conn.close()


def _normalize_ohne_makler_facts(
    property_data,
):
    """
    Überführt strukturierte Ohne-Makler-Fakten
    in die vorhandenen Monitor-Felder.

    Zusätzlich werden die Fakten an raw_text
    angehängt, damit die zentralen Klassifizierer
    für Zustand und Bebaubarkeit sie ebenfalls sehen.
    """

    from ohne_makler import parse_number

    facts = (
        property_data.get("source_facts")
        or {}
    )

    if not isinstance(facts, dict):
        return property_data

    # --------------------------------------------------------
    # Fakten für die zentrale Textanalyse erhalten
    # --------------------------------------------------------

    fact_lines = []

    for key, value in facts.items():

        if value in (
            None,
            "",
        ):
            continue

        fact_lines.append(
            f"{key}: {value}"
        )

    fact_text = "\n".join(
        fact_lines
    ).strip()

    raw_text = str(
        property_data.get("raw_text")
        or ""
    ).strip()

    if (
        fact_text
        and fact_text not in raw_text
    ):
        property_data["raw_text"] = (
            "\n".join(
                part
                for part in (
                    raw_text,
                    fact_text,
                )
                if part
            )
        )

    # --------------------------------------------------------
    # Energie
    # --------------------------------------------------------

    value = facts.get(
        "energieeffizienzklasse"
    )

    if value:
        property_data["energy_class"] = (
            str(value).strip().upper()
        )

    value = parse_number(
        facts.get(
            "endenergiebedarf"
        )
    )

    if value is not None:
        property_data[
            "energy_value_kwh"
        ] = value

    value = facts.get(
        "energieausweistyp"
    )

    if value:
        property_data[
            "energy_certificate_type"
        ] = str(value).strip()

    value = facts.get(
        "heizung"
    )

    if value:
        property_data[
            "heating_type"
        ] = str(value).strip()

    value = facts.get(
        "wesentlicher energieträger"
    )

    if value:
        property_data[
            "energy_source"
        ] = str(value).strip()

    value = parse_number(
        facts.get(
            "baujahr"
        )
    )

    if value is not None:
        property_data[
            "energy_construction_year"
        ] = int(value)

    energy_keys = (
        "energieeffizienzklasse",
        "energieausweistyp",
        "wesentlicher energieträger",
        "endenergiebedarf",
        "heizung",
        "baujahr",
    )

    energy_lines = [
        f"{key}: {facts[key]}"
        for key in energy_keys
        if facts.get(key)
    ]

    if energy_lines:
        property_data[
            "energy_data_source"
        ] = "ohne-makler"

        property_data[
            "energy_raw_text"
        ] = "\n".join(
            energy_lines
        )

    return property_data


def import_ohne_makler_url(url):
    """
    Importiert ein Ohne-Makler-Exposé über den
    spezialisierten HTML-Parser.
    """

    from monitor import (
        get_db,
        is_blacklisted,
        process_property,
    )

    from ohne_makler import (
        fetch_ohne_makler,
    )

    # --------------------------------------------------------
    # Objekt-ID aus der URL lesen.
    #
    # Beispiel:
    # https://www.ohne-makler.net/immobilie/485208/
    # --------------------------------------------------------

    match = re.search(
        r"/immobilie/(\d+)",
        url,
        re.I,
    )

    if not match:
        raise RuntimeError(
            "Keine Ohne-Makler-Objekt-ID "
            "in der URL erkannt."
        )

    portal_id = match.group(1)

    # --------------------------------------------------------
    # Bereits vorhanden?
    # --------------------------------------------------------

    existing = get_existing_property(
        "ohne-makler",
        portal_id,
    )

    if existing is not None:

        return {
            "status": "existing",
            "property_data": existing,
            "property_id": existing.get(
                "id"
            ),
            "duplicate": True,
        }

    # --------------------------------------------------------
    # Exposé laden und parsen
    # --------------------------------------------------------

    property_data = fetch_ohne_makler(
        url
    )

    property_data = (
        _normalize_ohne_makler_facts(
            property_data
        )
    )

    # Der Parser liefert zusätzlich Diagnosewerte.
    # process_property() bekommt nur die normalen
    # Immobilienfelder.
    property_data.pop(
        "source_object_class",
        None,
    )

    property_data.pop(
        "source_object_type",
        None,
    )

    property_data.pop(
        "source_facts",
        None,
    )

    title = (
        property_data.get("title")
        or ""
    )

    location = (
        property_data.get("location")
        or ""
    )

    raw_text = (
        property_data.get("raw_text")
        or ""
    )

    property_type = (
        property_data.get(
            "property_type"
        )
    )

    print(
        "OHNE-MAKLER IMPORT: "
        f"{portal_id} | "
        f"{property_type} | "
        f"{title}",
        flush=True,
    )

    # --------------------------------------------------------
    # Blacklist
    #
    # Der manuelle Telegram-Import läuft anschließend mit
    # apply_filters=False. Deshalb hier explizit prüfen.
    # --------------------------------------------------------

    if is_blacklisted(
        title,
        location,
        raw_text,
        property_type=property_type,
    ):

        print(
            "OHNE-MAKLER BLACKLIST: "
            f"{portal_id} | "
            f"{title}",
            flush=True,
        )

        return {
            "status": "blacklisted",
            "property_data":
                property_data,
            "property_id": None,
            "duplicate": False,
        }

    # --------------------------------------------------------
    # Normale zentrale Monitor-Pipeline
    #
    # - Geo
    # - Wasser
    # - Nachbarn
    # - Lärm
    # - Bebaubarkeit
    # - Score
    # - Datenbank
    # --------------------------------------------------------

    conn = get_db()

    try:

        result = process_property(
            conn,
            property_data,
            source_message_id=None,
            notify=False,
            apply_filters=False,
        )

        conn.commit()

        return result

    finally:

        conn.close()


def import_property_url(url):
    """
    Zentraler Router für manuell per Telegram
    übermittelte Immobilien-URLs.
    """

    url = url.strip()

    if not (
        url.startswith("http://")
        or url.startswith("https://")
    ):
        raise ValueError(
            "Keine gültige HTTP/HTTPS-URL."
        )

    # --------------------------------------------------------
    # Ohne-Makler
    # --------------------------------------------------------

    if re.search(
        r"^https?://(?:www\.)?"
        r"ohne-makler\.net/"
        r"immobilie/\d+",
        url,
        re.I,
    ):

        return import_ohne_makler_url(
            url
        )

    source = detect_source(
        url
    )

    # --------------------------------------------------------
    # Immowelt
    # --------------------------------------------------------

    if source == "immowelt":
        return import_immowelt_url(
            url
        )

    if source == "immoscout24":
        return import_immoscout_url(
            url
        )

    # --------------------------------------------------------
    # Alle anderen Anbieter zunächst über den
    # generischen Webseitenparser versuchen.
    #
    # Später können wir hier problemlos ergänzen:
    #
    # if source == "immoscout24":
    #     return import_immoscout_url(url)
    #
    # if source == "engelvoelkers_com":
    #     return import_engel_voelkers_url(url)
    #
    # --------------------------------------------------------

    return import_generic_property_url(
        url
    )
