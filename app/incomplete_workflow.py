import json
import sqlite3

from user_status import (
    ensure_user_status_table,
)

from browser_condition_hints import (
    condition_lab_hints,
)
from geo_precision import (
    GEO_PRECISION_EXACT,
    GEO_PRECISION_LOCALITY,
    effective_geo_precision,
    provisional_score_range,
)
from lab_waitlist import (
    waiting_portal_ids,
)


CONDITION_BUTTONS = (
    (
        ("✅ Bezugsfertig", "t"),
        ("👍 Gut", "g"),
    ),
    (
        ("🧹 Gepflegt", "m"),
        ("🪛 Teilrenovierung", "c"),
    ),
    (
        ("🔧 Renovierungsbedürftig", "r"),
    ),
    (
        ("🏚 Sanierungsbedürftig", "s"),
        ("⛔ Baufällig", "d"),
    ),
)


ENERGY_BUTTONS = (
    (
        ("A+", "ap"),
        ("A", "a"),
        ("B", "b"),
    ),
    (
        ("C", "c"),
        ("D", "d"),
        ("E", "e"),
    ),
    (
        ("F", "f"),
        ("G", "g"),
        ("H", "h"),
    ),
)


GEO_REASONS = {
    "Freilage/Nachbarn",
    "Lärm",
    "Wasser",
}


GEO_LABELS = {
    "Freilage/Nachbarn": "🏡 Nachbarn/Freilage",
    "Lärm": "🔇 Lärm",
    "Wasser": "🌊 Wasser",
}


def _score_details(value):

    if isinstance(value, dict):
        return value

    if not value:
        return {}

    try:
        data = json.loads(value)
    except Exception:
        return {}

    return data if isinstance(data, dict) else {}


def _missing_reasons_base(row):

    details = _score_details(
        row.get("score_details")
    )

    reasons = details.get(
        "incomplete_reasons"
    )

    if not isinstance(reasons, list):
        return set()

    return {
        str(reason)
        for reason in reasons
        if reason
    }


def _row_value(
    row,
    key,
):

    if hasattr(
        row,
        "get",
    ):
        return row.get(
            key
        )

    try:
        return row[
            key
        ]

    except (
        KeyError,
        IndexError,
        TypeError,
    ):
        return None


def _rail_fallback_available(
    row,
):

    if not _row_value(
        row,
        "noise_checked_at",
    ):
        return False

    # Kartierte Werte:
    # kein Fallback notwendig.
    if (
        _row_value(
            row,
            "rail_lden",
        )
        is not None
        or _row_value(
            row,
            "rail_lnight",
        )
        is not None
    ):
        return False

    distance_value = _row_value(
        row,
        "rail_distance_m",
    )

    traffic_value = _row_value(
        row,
        "rail_annual_traffic",
    )

    if (
        distance_value is None
        or traffic_value is None
    ):
        return False

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
        return False

    return (
        0 <= distance <= 1000
        and annual_traffic >= 0
    )


def _missing_reasons(
    row,
):

    missing = set(
        _missing_reasons_base(
            row
        )
    )

    if _rail_fallback_available(
        row
    ):
        missing.discard(
            "Lärm"
        )

    return missing



def get_incomplete_rows(db_path):

    ensure_user_status_table(
        db_path
    )

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute(
            """
            SELECT p.*
            FROM properties AS p
            LEFT JOIN property_user_status AS us
              ON us.portal_id = p.portal_id
            WHERE p.rating = 'incomplete'
              AND COALESCE(p.is_ko, 0) = 0
              AND COALESCE(us.status, 'active') = 'active'
              AND p.id = (
                  SELECT p2.id
                  FROM properties AS p2
                  WHERE p2.portal = p.portal
                    AND p2.portal_id = p.portal_id
                  ORDER BY
                      p2.last_seen DESC,
                      p2.id DESC
                  LIMIT 1
              )
            ORDER BY
                p.last_seen DESC,
                p.id DESC
            """
        ).fetchall()

    finally:
        conn.close()

    return [dict(row) for row in rows]


def _condition_unknown(row):

    value = str(
        row.get("condition_class")
        or "unknown"
    ).strip().lower()

    return value == "unknown"


def _geo_missing(row):

    precision = effective_geo_precision(
        row
    )

    if precision == GEO_PRECISION_LOCALITY:
        return set()

    # Dieses Labor kann nur eine fehlende genaue Lage lösen.
    # Sind verifizierte Koordinaten vorhanden, darf ein
    # technischer Fehler bei Wasser, Nachbarn oder Lärm nicht
    # erneut zur Eingabe derselben Adresse auffordern.
    if (
        precision == GEO_PRECISION_EXACT
        and row.get("latitude") is not None
        and row.get("longitude") is not None
    ):
        return set()

    return _missing_reasons(
        row
    ).intersection(
        GEO_REASONS
    )


def _condition_rows_all(db_path):

    return [
        row
        for row in get_incomplete_rows(db_path)
        if (
            row.get("property_type")
            in ("house", "farm")
            and _condition_unknown(row)
        )
    ]


def condition_rows(db_path):

    waiting = waiting_portal_ids(
        db_path,
        "condition",
    )

    return [
        row
        for row in _condition_rows_all(db_path)
        if str(row.get("portal_id") or "") not in waiting
    ]


def waiting_condition_rows(db_path):

    waiting = waiting_portal_ids(
        db_path,
        "condition",
    )

    return [
        row
        for row in _condition_rows_all(db_path)
        if str(row.get("portal_id") or "") in waiting
    ]


def _energy_incomplete(row):

    status = str(
        row.get(
            "energy_certificate_status"
        )
        or "unknown"
    ).strip().lower()

    return (
        row.get(
            "energy_updated_at"
        ) is None
        or status == "not_available_yet"
    )


def energy_rows(db_path):

    rows = [
        row
        for row in get_incomplete_rows(db_path)
        if (
            row.get("property_type")
            in ("house", "farm")
            and _energy_incomplete(row)
        )
    ]

    # Ein bereits geprüfter, aber noch nicht verfügbarer
    # Energieausweis bleibt incomplete. Solche Wartefälle
    # sollen die manuell bearbeitbaren Fälle jedoch nicht
    # sofort blockieren, deshalb stabil nach hinten sortieren.
    rows.sort(
        key=lambda row: (
            str(
                row.get(
                    "energy_certificate_status"
                )
                or "unknown"
            ).strip().lower()
            == "not_available_yet"
        )
    )

    return rows


def geo_rows(db_path):

    return [
        row
        for row in get_incomplete_rows(db_path)
        if _geo_missing(row)
    ]


def _locality_rows_all(db_path):

    ensure_user_status_table(
        db_path
    )

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute(
            """
            SELECT p.*
            FROM properties AS p
            LEFT JOIN property_user_status AS us
              ON us.portal_id = p.portal_id
            WHERE p.geo_precision = 'locality'
              AND p.rating = 'provisional'
              AND COALESCE(p.is_ko, 0) = 0
              AND COALESCE(us.status, 'active') = 'active'
              AND p.id = (
                  SELECT p2.id
                  FROM properties AS p2
                  WHERE p2.portal = p.portal
                    AND p2.portal_id = p.portal_id
                  ORDER BY
                      p2.last_seen DESC,
                      p2.id DESC
                  LIMIT 1
              )
            ORDER BY
                p.last_seen DESC,
                p.id DESC
            """
        ).fetchall()

    finally:
        conn.close()

    result = [
        dict(row)
        for row in rows
    ]

    # Für das Nachfragen zuerst die Objekte mit dem größten
    # möglichen Nutzen einer genauen Adresse zeigen.
    result.sort(
        key=lambda row: (
            (
                provisional_score_range(row)
                or (-1, -1)
            )[1],
            (
                provisional_score_range(row)
                or (-1, -1)
            )[0],
        ),
        reverse=True,
    )

    return result


def locality_rows(db_path):

    waiting = waiting_portal_ids(
        db_path,
        "locality",
    )

    return [
        row
        for row in _locality_rows_all(db_path)
        if str(row.get("portal_id") or "") not in waiting
    ]


def waiting_locality_rows(db_path):

    waiting = waiting_portal_ids(
        db_path,
        "locality",
    )

    return [
        row
        for row in _locality_rows_all(db_path)
        if str(row.get("portal_id") or "") in waiting
    ]


def stats(db_path):

    rows = get_incomplete_rows(db_path)

    result = {
        "Objekte": len(rows),
        "Energie": 0,
        "Zustand": len(
            condition_rows(db_path)
        ),
        "Preis": 0,
        "Wohnfläche": 0,
        "Grundstück": 0,
        "Geo": 0,
        "Lage präzisieren": len(
            locality_rows(db_path)
        ),
        "Zustand angefragt": len(
            waiting_condition_rows(db_path)
        ),
        "Lage angefragt": len(
            waiting_locality_rows(db_path)
        ),
    }

    for row in rows:

        missing = _missing_reasons(row)

        if (
            row.get("property_type")
            in ("house", "farm")
            and _energy_incomplete(row)
        ):
            result["Energie"] += 1

        if row.get("price") is None:
            result["Preis"] += 1

        if "Wohnfläche" in missing:
            result["Wohnfläche"] += 1

        if "Grundstück" in missing:
            result["Grundstück"] += 1

        if _geo_missing(row):
            result["Geo"] += 1

    return result


def overview_text(db_path):

    current = stats(db_path)

    if (
        current["Objekte"] == 0
        and current["Lage präzisieren"] == 0
        and current["Zustand angefragt"] == 0
        and current["Lage angefragt"] == 0
    ):
        return (
            "✅ Keine unvollständigen "
            "Objekte mehr."
        )

    lines = [
        "🧪 LABOR · OFFENE PRÜFUNGEN",
        "",
        f"Objekte: {current['Objekte']}",
        "",
        f"⚡ Energie: {current['Energie']}",
        f"🔧 Zustand: {current['Zustand']}",
        f"💶 Preis: {current['Preis']}",
        f"📐 Wohnfläche: {current['Wohnfläche']}",
        f"🌳 Grundstück: {current['Grundstück']}",
        f"📍 Adresse/Geo: {current['Geo']}",
        "",
        "Das Labor zeigt nur Aufgaben, "
        "die wirklich noch offen sind.",
        "",
        "Optional:",
        "📌 Lage präzisieren: "
        f"{current['Lage präzisieren']}",
    ]

    if (
        current["Zustand angefragt"]
        or current["Lage angefragt"]
    ):
        lines.extend(
            [
                "",
                "Warteliste:",
                "📨 Zustand: "
                f"{current['Zustand angefragt']}",
                "📨 Lage: "
                f"{current['Lage angefragt']}",
            ]
        )

    return "\n".join(lines)


def overview_keyboard(db_path):

    current = stats(db_path)

    rows = []

    if current["Energie"]:
        rows.append(
            [
                {
                    "text": (
                        "⚡ Energie abarbeiten "
                        f"({current['Energie']})"
                    ),
                    "callback_data": "iw:energy",
                }
            ]
        )

    if current["Zustand"]:
        rows.append(
            [
                {
                    "text": (
                        "🔧 Zustand abarbeiten "
                        f"({current['Zustand']})"
                    ),
                    "callback_data": "iw:condition",
                }
            ]
        )

    if current["Geo"]:
        rows.append(
            [
                {
                    "text": (
                        "📍 Adresse/Geo nachtragen "
                        f"({current['Geo']})"
                    ),
                    "callback_data": "iw:geo",
                }
            ]
        )

    if current["Lage präzisieren"]:
        rows.append(
            [
                {
                    "text": (
                        "📌 Lage präzisieren "
                        f"({current['Lage präzisieren']})"
                    ),
                    "callback_data": "iw:locality",
                }
            ]
        )

    if current["Zustand angefragt"]:
        rows.append(
            [
                {
                    "text": (
                        "📨 Zustand-Warteliste "
                        f"({current['Zustand angefragt']})"
                    ),
                    "callback_data": "iw:wait_condition",
                }
            ]
        )

    if current["Lage angefragt"]:
        rows.append(
            [
                {
                    "text": (
                        "📨 Lage-Warteliste "
                        f"({current['Lage angefragt']})"
                    ),
                    "callback_data": "iw:wait_locality",
                }
            ]
        )

    return {
        "inline_keyboard": rows
    }


def condition_text(
    row,
    position,
    total,
    waiting=False,
):

    title = (
        row.get("title")
        or row.get("portal_id")
        or "(ohne Titel)"
    )

    location = (
        row.get("location")
        or "(Ort unbekannt)"
    )

    lines = [
        (
            "📨 ZUSTAND-WARTELISTE"
            if waiting
            else "🔧 ZUSTAND"
        )
        + f" · {position}/{total}",
        "",
        title,
        f"📍 {location}",
    ]

    facts = []

    price = row.get("price")
    plot_area = row.get("plot_area")
    living_area = row.get("living_area")

    if price is not None:
        facts.append(
            f"{float(price):,.0f} €".replace(",", ".")
        )

    if plot_area is not None:
        facts.append(
            f"{float(plot_area):,.0f} m² Grundstück"
            .replace(",", ".")
        )

    if living_area is not None:
        facts.append(
            f"{float(living_area):,.0f} m² Wohnfläche"
            .replace(",", ".")
        )

    if facts:
        lines.extend(
            [
                "",
                " · ".join(facts),
            ]
        )

    hints = condition_lab_hints(
        row.get("browser_text")
    )

    portal_condition = hints.get(
        "portal_condition"
    )
    modernization = hints.get(
        "modernization"
    )

    if (
        portal_condition
        or modernization
    ):
        lines.extend(
            [
                "",
                "Portalangaben:",
            ]
        )

        if portal_condition:
            lines.append(
                "🏷 Zustand: "
                f"{portal_condition}"
            )

        if modernization:
            lines.append(
                "🛠 Modernisierung/Sanierung: "
                f"{modernization} "
                "(nur Hinweis)"
            )

    if row.get("url"):
        lines.extend(
            [
                "",
                row["url"],
            ]
        )

    lines.extend(
        [
            "",
            "Zustand auswählen:",
        ]
    )

    return "\n".join(lines)


def condition_keyboard(
    row,
    waiting=False,
):

    portal_id = str(
        row.get("portal_id")
        or ""
    )

    rows = []

    for button_row in CONDITION_BUTTONS:

        rows.append(
            [
                {
                    "text": label,
                    "callback_data": (
                        f"c:{portal_id}:{code}:"
                        + (
                            "iwcw"
                            if waiting
                            else "iwc"
                        )
                    ),
                }
                for label, code in button_row
            ]
        )

    rows.append(
        [
            {
                "text": "🙈 Kein Interesse",
                "callback_data": (
                    "iw_nope:"
                    + (
                        "cw"
                        if waiting
                        else "ca"
                    )
                    + f":{portal_id}"
                ),
            },
            {
                "text": (
                    "↩️ Wieder offen"
                    if waiting
                    else "📩 Information angefragt"
                ),
                "callback_data": (
                    "iwq:"
                    + (
                        "open:c"
                        if waiting
                        else "add:c"
                    )
                    + f":{portal_id}"
                ),
            },
        ]
    )

    if waiting:
        rows.append(
            [
                {
                    "text": "⏭ Nächster Wartelistenfall",
                    "callback_data": f"iwq:skip:c:{portal_id}",
                }
            ]
        )

    rows.append(
        [
            {
                "text": "⬅️ Labor",
                "callback_data": "iw:menu",
            }
        ]
    )

    return {
        "inline_keyboard": rows
    }


def energy_text(row, position, total):

    title = (
        row.get("title")
        or row.get("portal_id")
        or "(ohne Titel)"
    )

    location = (
        row.get("location")
        or "(Ort unbekannt)"
    )

    lines = [
        f"⚡ ENERGIE · {position}/{total}",
        "",
        title,
        f"📍 {location}",
    ]

    if row.get("url"):
        lines.extend(
            [
                "",
                row["url"],
            ]
        )

    lines.extend(
        [
            "",
            "Exposé öffnen: Die Browserprüfung übernimmt "
            "Energiedaten automatisch und springt diese Karte automatisch "
            "zum nächsten offenen Objekt.",
            "",
            "Die manuellen Buttons sind nur nötig, wenn die "
            "Browserprüfung den Fall nicht abschließen kann.",
        ]
    )

    return "\n".join(lines)


def energy_keyboard(row):

    portal_id = str(
        row.get("portal_id")
        or ""
    )

    rows = []

    for button_row in ENERGY_BUTTONS:

        rows.append(
            [
                {
                    "text": label,
                    "callback_data": (
                        f"iwe:{portal_id}:{code}"
                    ),
                }
                for label, code in button_row
            ]
        )

    rows.extend(
        [
            [
                {
                    "text": "✏️ kWh-Wert eingeben",
                    "callback_data": (
                        f"iwev:{portal_id}"
                    ),
                }
            ],
            [
                {
                    "text": "⚠️ Kein Label · wie H",
                    "callback_data": (
                        f"iwe:{portal_id}:nl"
                    ),
                }
            ],
            [
                {
                    "text": "❔ Keine Angabe",
                    "callback_data": (
                        f"iwe:{portal_id}:none"
                    ),
                }
            ],
            [
                {
                    "text": "📄 Nicht erforderlich",
                    "callback_data": (
                        f"iwe:{portal_id}:nr"
                    ),
                },
                {
                    "text": "⏳ Noch nicht verfügbar",
                    "callback_data": (
                        f"iwe:{portal_id}:ny"
                    ),
                },
            ],
            [
                {
                    "text": "⬅️ Labor",
                    "callback_data": "iw:menu",
                }
            ],
        ]
    )

    return {
        "inline_keyboard": rows
    }


def geo_text(row, position, total):

    title = (
        row.get("title")
        or row.get("portal_id")
        or "(ohne Titel)"
    )

    location = (
        row.get("location")
        or "(Ort unbekannt)"
    )

    missing = _geo_missing(
        row
    )

    lines = [
        f"📍 ADRESSE / GEO · {position}/{total}",
        "",
        title,
        f"📍 Portal-Ort: {location}",
    ]

    latitude = row.get(
        "latitude"
    )

    longitude = row.get(
        "longitude"
    )

    if (
        latitude is not None
        and longitude is not None
    ):
        lines.append(
            "🧭 Aktuell: "
            f"{float(latitude):.6f}, "
            f"{float(longitude):.6f}"
        )

    if row.get(
        "manual_coordinates_set_at"
    ):
        lines.append(
            "✅ Manuelle Adresse/Koordinaten "
            "sind bereits gesetzt"
        )

    lines.extend(
        [
            "",
            "Noch offen:",
        ]
    )

    for reason in (
        "Wasser",
        "Freilage/Nachbarn",
        "Lärm",
    ):
        if reason in missing:
            lines.append(
                GEO_LABELS[reason]
            )

    if row.get("url"):
        lines.extend(
            [
                "",
                row["url"],
            ]
        )

    lines.extend(
        [
            "",
            "Hier wird keine genaue Adresse "
            "automatisch geraten.",
            "Trage Adresse oder Koordinaten erst ein, "
            "wenn du sie sicher kennst.",
            "Danach werden Wasser, Nachbarn und Lärm "
            "komplett neu berechnet.",
        ]
    )

    return "\n".join(lines)


def geo_keyboard(row):

    portal_id = str(
        row.get("portal_id")
        or ""
    )

    property_type = str(
        row.get("property_type")
        or "unknown"
    )

    return {
        "inline_keyboard": [
            [
                {
                    "text": "📍 Adresse/Koordinaten setzen",
                    "callback_data": (
                        f"coords_set:{portal_id}:"
                        f"{property_type}:iwg"
                    ),
                }
            ],
            [
                {
                    "text": "⬅️ Labor",
                    "callback_data": "iw:menu",
                }
            ],
        ]
    }


def locality_text(
    row,
    position,
    total,
    waiting=False,
):

    title = (
        row.get("title")
        or row.get("portal_id")
        or "(ohne Titel)"
    )

    location = (
        row.get("location")
        or "(Ort unbekannt)"
    )

    score_range = provisional_score_range(
        row
    )

    lines = [
        (
            "📨 LAGE-WARTELISTE"
            if waiting
            else "📌 LAGE PRÄZISIEREN"
        )
        + f" · {position}/{total}",
        "",
        title,
        f"📍 Portal-Ort: {location}",
    ]

    if score_range is not None:
        lines.extend(
            [
                "⭐ Vorläufig: "
                f"{score_range[0]}–{score_range[1]} Punkte",
            ]
        )

    if row.get("url"):
        lines.extend(
            [
                "",
                row["url"],
            ]
        )

    lines.extend(
        [
            "",
            "Die genaue Lage ist noch unbekannt. Der Bereich "
            "zeigt den schlechtesten und besten möglichen "
            "Ausgang für Wasser, Nachbarn und Lärm.",
            "",
            "Wenn du die Adresse sicher erfahren hast, kannst "
            "du sie hier eintragen und erhältst den exakten "
            "Geo-Score.",
        ]
    )

    return "\n".join(lines)

def locality_keyboard(
    row,
    waiting=False,
):

    portal_id = str(
        row.get("portal_id")
        or ""
    )

    property_type = str(
        row.get("property_type")
        or "unknown"
    )

    return {
        "inline_keyboard": [
            [
                {
                    "text": "📍 Adresse/Koordinaten setzen",
                    "callback_data": (
                        f"coords_set:{portal_id}:"
                        f"{property_type}:"
                        + (
                            "iwlw"
                            if waiting
                            else "iwl"
                        )
                    ),
                }
            ],
            [
                {
                    "text": "🙈 Kein Interesse",
                    "callback_data": (
                        "iw_nope:"
                        + (
                            "lw"
                            if waiting
                            else "la"
                        )
                        + f":{portal_id}"
                    ),
                },
                {
                    "text": (
                        "↩️ Wieder offen"
                        if waiting
                        else "📩 Information angefragt"
                    ),
                    "callback_data": (
                        "iwq:"
                        + (
                            "open:l"
                            if waiting
                            else "add:l"
                        )
                        + f":{portal_id}"
                    ),
                },
            ],
            [
                {
                    "text": (
                        "⏭ Nächster Wartelistenfall"
                        if waiting
                        else "⏭ Überspringen"
                    ),
                    "callback_data": (
                        f"iwq:skip:l:{portal_id}"
                        if waiting
                        else f"iwl_skip:{portal_id}"
                    ),
                },
            ],
            [
                {
                    "text": "⬅️ Labor",
                    "callback_data": "iw:menu",
                }
            ],
        ]
    }

def first_condition(db_path):

    rows = condition_rows(db_path)

    if not rows:
        return None, 0

    return rows[0], len(rows)


def first_energy(db_path):

    rows = energy_rows(db_path)

    if not rows:
        return None, 0

    return rows[0], len(rows)


def first_geo(db_path):

    rows = geo_rows(db_path)

    if not rows:
        return None, 0

    return rows[0], len(rows)


def first_locality(db_path):

    rows = locality_rows(db_path)

    if not rows:
        return None, 0

    return rows[0], len(rows)
