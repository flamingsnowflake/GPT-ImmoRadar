from datetime import datetime, timezone


ENERGY_COLUMNS = {
    "energy_class": "TEXT",
    "energy_value_kwh": "REAL",
    "energy_certificate_type": "TEXT",
    "energy_certificate_status": "TEXT",
    "heating_type": "TEXT",
    "energy_source": "TEXT",
    "energy_construction_year": "INTEGER",
    "energy_data_source": "TEXT",
    "energy_raw_text": "TEXT",
    "energy_updated_at": "TEXT",
}


ENERGY_CLASSES = frozenset({
    "A+",
    "A",
    "B",
    "C",
    "D",
    "E",
    "F",
    "G",
    "H",
})


CERTIFICATE_TYPES = frozenset({
    "demand",
    "consumption",
    "unknown",
})


CERTIFICATE_STATUSES = frozenset({
    "available",
    "not_required",
    "not_available_yet",
    "no_label",
    "unknown",
})


CERTIFICATE_TYPE_LABELS = {
    "demand": "Bedarf",
    "consumption": "Verbrauch",
    "unknown": "unbekannt",
}


def ensure_energy_columns(conn):

    existing_columns = {
        row[1]
        for row in conn.execute(
            "PRAGMA table_info(properties)"
        )
    }

    for column, definition in ENERGY_COLUMNS.items():

        if column in existing_columns:
            continue

        conn.execute(
            f"""
            ALTER TABLE properties
            ADD COLUMN {column} {definition}
            """
        )

    conn.commit()


def _clean_text(value, max_length=300):

    if value is None:
        return None

    text = str(value).strip()

    if not text:
        return None

    return text[:max_length]


def _normalize_energy_class(value):

    text = _clean_text(value, 10)

    if text is None:
        return None

    normalized = (
        text
        .upper()
        .replace(" ", "")
    )

    if normalized not in ENERGY_CLASSES:
        raise ValueError(
            f"Ungültige Energieklasse: {text}"
        )

    return normalized


def _normalize_float(value):

    if value is None or value == "":
        return None

    if isinstance(value, str):
        value = value.strip()

        if "," in value:
            value = (
                value
                .replace(".", "")
                .replace(",", ".")
            )

    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Ungültiger Energieverbrauch/-bedarf"
        ) from exc

    if not 0 < result <= 2000:
        raise ValueError(
            "Energiewert außerhalb des plausiblen Bereichs"
        )

    return result


def _normalize_year(value):

    if value is None or value == "":
        return None

    try:
        year = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Ungültiges Baujahr im Energieausweis"
        ) from exc

    if not 1800 <= year <= 2100:
        raise ValueError(
            "Baujahr im Energieausweis außerhalb des plausiblen Bereichs"
        )

    return year


def normalize_energy_data(data):

    if not isinstance(data, dict):
        raise ValueError(
            "Energiedaten müssen ein Objekt sein"
        )

    status = (
        _clean_text(
            data.get("energy_certificate_status"),
            40,
        )
        or "unknown"
    ).lower()

    certificate_type = (
        _clean_text(
            data.get("energy_certificate_type"),
            40,
        )
        or "unknown"
    ).lower()

    if status not in CERTIFICATE_STATUSES:
        raise ValueError(
            f"Ungültiger Energieausweis-Status: {status}"
        )

    if certificate_type not in CERTIFICATE_TYPES:
        raise ValueError(
            f"Ungültiger Energieausweistyp: {certificate_type}"
        )

    energy_class = _normalize_energy_class(
        data.get("energy_class")
    )

    energy_value_kwh = _normalize_float(
        data.get("energy_value_kwh")
    )

    # Eindeutige Energieklasse oder kWh-Wert beweisen verfügbare Energiedaten.
    # Ein Portal-/Userscript-Status "not_available_yet" darf niemals
    # gleichzeitig mit einer Klasse oder einem Verbrauch/Bedarf bestehen.
    if (
        energy_class is not None
        or energy_value_kwh is not None
    ):
        status = "available"

    elif (
        status == "unknown"
        and certificate_type != "unknown"
    ):
        status = "available"

    if status in {
        "not_required",
        "no_label",
    }:
        energy_class = None
        energy_value_kwh = None
        certificate_type = "unknown"

    raw_text = _clean_text(
        data.get("energy_raw_text"),
        5000,
    )

    return {
        "energy_class": energy_class,
        "energy_value_kwh": energy_value_kwh,
        "energy_certificate_type": certificate_type,
        "energy_certificate_status": status,
        "heating_type": _clean_text(
            data.get("heating_type")
        ),
        "energy_source": _clean_text(
            data.get("energy_source")
        ),
        "energy_construction_year": _normalize_year(
            data.get("energy_construction_year")
        ),
        "energy_data_source": _clean_text(
            data.get("energy_data_source"),
            80,
        ),
        "energy_raw_text": raw_text,
        "energy_updated_at": (
            datetime.now(timezone.utc).isoformat()
        ),
    }


def update_property_energy(
    conn,
    portal,
    portal_id,
    data,
):

    normalized = normalize_energy_data(data)

    row = conn.execute(
        """
        SELECT id, title, property_type
        FROM properties
        WHERE portal = ?
          AND portal_id = ?
        LIMIT 1
        """,
        (
            portal,
            portal_id,
        ),
    ).fetchone()

    if row is None:
        return None, normalized

    conn.execute(
        """
        UPDATE properties
        SET
            energy_class = :energy_class,
            energy_value_kwh = :energy_value_kwh,
            energy_certificate_type = :energy_certificate_type,
            energy_certificate_status = :energy_certificate_status,
            heating_type = :heating_type,
            energy_source = :energy_source,
            energy_construction_year = :energy_construction_year,
            energy_data_source = :energy_data_source,
            energy_raw_text = :energy_raw_text,
            energy_updated_at = :energy_updated_at
        WHERE portal = :portal
          AND portal_id = :portal_id
        """,
        {
            **normalized,
            "portal": portal,
            "portal_id": portal_id,
        },
    )

    return dict(row), normalized


def format_energy_summary(property_data):

    status = (
        property_data.get("energy_certificate_status")
        or "unknown"
    )

    if status == "not_required":
        return "Ausweis nicht erforderlich"

    if status == "not_available_yet":
        return "Ausweis noch nicht verfügbar"

    if status == "no_label":
        return "⚠️ Kein Energielabel · wie H gewertet"

    energy_class = property_data.get(
        "energy_class"
    )

    energy_value = property_data.get(
        "energy_value_kwh"
    )

    certificate_type = property_data.get(
        "energy_certificate_type"
    )

    parts = []

    if energy_class:
        parts.append(
            f"Klasse {energy_class}"
        )

    if energy_value is not None:
        value_text = (
            f"{energy_value:.1f}"
            .replace(".", ",")
        )

        parts.append(
            f"{value_text} kWh/(m²·a)"
        )

    if (
        certificate_type
        and certificate_type != "unknown"
    ):
        parts.append(
            CERTIFICATE_TYPE_LABELS.get(
                certificate_type,
                certificate_type,
            )
        )

    if parts:
        return " | ".join(parts)

    return "unbekannt"
