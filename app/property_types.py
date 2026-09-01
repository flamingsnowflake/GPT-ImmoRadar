from config_loader import CONFIG


HOUSE_TYPES = frozenset({
    "house",
    "farm",
})


PROPERTY_TYPE_LABELS = {
    "house": "Haus",
    "farm": "Hof",
    "land": "Grundstück",
    "unknown": "Unbekannt",
}


def property_type_label(property_type):
    normalized = (
        str(property_type or "unknown")
        .strip()
        .lower()
    )

    return PROPERTY_TYPE_LABELS.get(
        normalized,
        normalized or "Unbekannt",
    )


def is_house_type(property_type):
    return (
        str(property_type or "")
        .strip()
        .lower()
        in HOUSE_TYPES
    )


def detect_property_type(property_data):

    config = CONFIG.property_types_config()

    searches = config.get(
        "searches",
        {}
    )

    keywords = config.get(
        "keywords",
        {}
    )

    search_id = str(
        property_data.get("search_id") or ""
    )

    # --------------------------------------------------------
    # 1. Expliziter Suchauftrag
    # --------------------------------------------------------

    if search_id in searches:
        return searches[search_id]

    # --------------------------------------------------------
    # 2. Strukturierte Immobiliendaten
    # --------------------------------------------------------
    #
    # Eine echte Wohnfläche oder Zimmerzahl ist ein sehr
    # starkes Signal für ein Haus.
    #
    # Das muss VOR "land" geprüft werden, weil Hausanzeigen
    # praktisch immer Wörter wie "Grundstück",
    # "Grundstücksfläche" usw. enthalten.
    #
    # FARM behandeln wir separat weiter unten.

    living_area = property_data.get(
        "living_area"
    )

    rooms = property_data.get(
        "rooms"
    )

    text = " ".join([
        str(
            property_data.get("title")
            or ""
        ),
        str(
            property_data.get("raw_text")
            or ""
        ),
        str(
            property_data.get(
                "telegram_preview_title"
            )
            or ""
        ),
        str(
            property_data.get(
                "telegram_preview_description"
            )
            or ""
        ),
    ]).lower()

    # Farm hat weiterhin Vorrang vor normalem Haus.
    for keyword in keywords.get(
        "farm",
        []
    ):
        if keyword.lower() in text:
            return "farm"

    if (
        living_area is not None
        or rooms is not None
    ):
        return "house"

    # --------------------------------------------------------
    # 3. Text-Fallback
    # --------------------------------------------------------

    for property_type in (
        "house",
        "land"
    ):

        for keyword in keywords.get(
            property_type,
            []
        ):

            if keyword.lower() in text:
                return property_type

    return "unknown"
