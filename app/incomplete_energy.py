import json
import sqlite3

from energy_data import (
    ensure_energy_columns,
    update_property_energy,
)
from property_types import is_house_type
from scoring import score_house


ENERGY_CHOICE_LABELS = {
    "ap": "Klasse A+",
    "a": "Klasse A",
    "b": "Klasse B",
    "c": "Klasse C",
    "d": "Klasse D",
    "e": "Klasse E",
    "f": "Klasse F",
    "g": "Klasse G",
    "h": "Klasse H",
    "nl": "Kein Energielabel · wie H gewertet",
    "none": "Keine Energieangabe im Exposé",
    "nr": "Energieausweis nicht erforderlich",
    "ny": "Energieausweis noch nicht verfügbar",
}


ENERGY_CLASS_CODES = {
    "ap": "A+",
    "a": "A",
    "b": "B",
    "c": "C",
    "d": "D",
    "e": "E",
    "f": "F",
    "g": "G",
    "h": "H",
}


def energy_choice_payload(code):

    code = str(
        code
        or ""
    ).strip().lower()

    if code in ENERGY_CLASS_CODES:

        energy_class = (
            ENERGY_CLASS_CODES[code]
        )

        return {
            "energy_class": energy_class,
            "energy_certificate_status": "available",
            "energy_certificate_type": "unknown",
            "energy_data_source": "telegram_manual",
            "energy_raw_text": (
                "Manuell im Labor gesetzt: "
                f"Energieklasse {energy_class}"
            ),
        }

    if code == "nl":

        return {
            "energy_certificate_status": "no_label",
            "energy_certificate_type": "unknown",
            "energy_data_source": "telegram_manual",
            "energy_raw_text": (
                "Manuell geprüft: kein Energielabel vorhanden; "
                "für das Scoring wie Klasse H behandeln"
            ),
        }

    if code == "none":

        return {
            "energy_certificate_status": "unknown",
            "energy_certificate_type": "unknown",
            "energy_data_source": "telegram_manual",
            "energy_raw_text": (
                "Manuell geprüft: Im Exposé ist keine "
                "Energieangabe vorhanden"
            ),
        }

    if code == "nr":

        return {
            "energy_certificate_status": "not_required",
            "energy_certificate_type": "unknown",
            "energy_data_source": "telegram_manual",
            "energy_raw_text": (
                "Manuell geprüft: Energieausweis nicht erforderlich"
            ),
        }

    if code == "ny":

        return {
            "energy_certificate_status": "not_available_yet",
            "energy_certificate_type": "unknown",
            "energy_data_source": "telegram_manual",
            "energy_raw_text": (
                "Manuell geprüft: Energieausweis noch nicht verfügbar"
            ),
        }

    raise ValueError(
        f"Unbekannte Energieauswahl: {code}"
    )


def energy_choice_label(code):

    code = str(
        code
        or ""
    ).strip().lower()

    return ENERGY_CHOICE_LABELS.get(
        code,
        code,
    )


def _energy_data_is_final(
    property_data,
):

    if property_data.get(
        "energy_updated_at"
    ) is None:
        return False

    status = str(
        property_data.get(
            "energy_certificate_status"
        )
        or "unknown"
    ).strip().lower()

    # "Noch nicht verfügbar" ist absichtlich ein offener
    # Wartezustand. Er darf später durch Klasse, kWh-Wert oder
    # einen anderen endgültigen manuellen Befund ersetzt werden.
    return status != "not_available_yet"


def _set_energy_payload(
    db_path,
    portal_id,
    payload,
    label,
):

    conn = sqlite3.connect(
        db_path,
        timeout=20,
    )

    conn.row_factory = sqlite3.Row

    try:

        ensure_energy_columns(
            conn
        )

        row = conn.execute(
            """
            SELECT *
            FROM properties
            WHERE portal_id = ?
            ORDER BY
                last_seen DESC,
                id DESC
            LIMIT 1
            """,
            (
                portal_id,
            )
        ).fetchone()

        if row is None:
            raise LookupError(
                f"Objekt {portal_id} nicht gefunden"
            )

        property_data = dict(
            row
        )

        if not is_house_type(
            property_data.get(
                "property_type"
            )
        ):
            raise ValueError(
                "Energiedaten sind nur für Häuser/Höfe vorgesehen"
            )

        # Falls Browser/Userscript die Energiedaten inzwischen
        # bereits endgültig geliefert hat, niemals mit einem
        # veralteten Labor-Dialog darüber schreiben.
        #
        # Ausnahme: not_available_yet bleibt bewusst offen und
        # darf später durch echte Energiedaten ersetzt werden.
        if _energy_data_is_final(
            property_data
        ):

            return {
                "status": "already_complete",
                "portal_id": portal_id,
                "label": "Energiedaten bereits vorhanden",
                "score": property_data.get("score"),
                "rating": property_data.get("rating"),
            }

        portal = str(
            property_data.get("portal")
            or ""
        ).strip().lower()

        if not portal:
            raise ValueError(
                "Portal fehlt"
            )

        _, normalized = update_property_energy(
            conn,
            portal,
            portal_id,
            payload,
        )

        scored_property = dict(
            property_data
        )

        scored_property.update(
            normalized
        )

        score_result = score_house(
            scored_property
        )

        conn.execute(
            """
            UPDATE properties
            SET
                score = ?,
                rating = ?,
                is_ko = ?,
                score_details = ?
            WHERE portal = ?
              AND portal_id = ?
            """,
            (
                score_result.get("score"),
                score_result.get("rating"),
                int(
                    bool(
                        score_result.get("ko")
                    )
                ),
                json.dumps(
                    score_result,
                    ensure_ascii=False,
                ),
                portal,
                portal_id,
            )
        )

        conn.commit()

        return {
            "status": "updated",
            "portal_id": portal_id,
            "label": label,
            "energy": normalized,
            "score": score_result.get("score"),
            "rating": score_result.get("rating"),
            "score_result": score_result,
        }

    finally:
        conn.close()


def set_energy_choice(
    db_path,
    portal_id,
    code,
):

    payload = energy_choice_payload(
        code
    )

    return _set_energy_payload(
        db_path,
        portal_id,
        payload,
        energy_choice_label(code),
    )


def set_energy_value(
    db_path,
    portal_id,
    value,
):

    text = str(
        value
        or ""
    ).strip()

    if not text:
        raise ValueError(
            "Energiewert fehlt"
        )

    payload = {
        "energy_value_kwh": text,
        "energy_certificate_status": "available",
        "energy_certificate_type": "unknown",
        "energy_data_source": "telegram_manual",
        "energy_raw_text": (
            "Manuell im Labor gesetzter Energiewert: "
            f"{text} kWh/(m²·a)"
        ),
    }

    result = _set_energy_payload(
        db_path,
        portal_id,
        payload,
        "Energiewert manuell gesetzt",
    )

    if result.get("status") == "updated":

        normalized_value = (
            result
            .get("energy", {})
            .get("energy_value_kwh")
        )

        if normalized_value is not None:
            result["label"] = (
                f"{float(normalized_value):.1f} "
                "kWh/(m²·a)"
            ).replace(
                ".",
                ",",
            )

    return result
