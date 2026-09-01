from house_condition import (
    classify_house_condition,
)


CONDITION_LABELS = (
    "zustand der immobilie",
    "objektzustand",
)


def _clean(value):

    if value is None:
        return ""

    return (
        str(value)
        .replace("\u00a0", " ")
        .strip()
    )


def _lines(text):

    return [
        cleaned
        for raw in str(text or "")
        .replace("\r", "")
        .split("\n")
        if (
            cleaned := _clean(raw)
        )
    ]


def extract_explicit_condition(
    page_text,
):

    lines = _lines(
        page_text
    )

    for index, line in enumerate(lines):

        lower = line.casefold()

        for label in CONDITION_LABELS:

            if lower == label:

                if index + 1 >= len(lines):
                    continue

                value = _clean(
                    lines[index + 1]
                )

            elif lower.startswith(
                label + ":"
            ):
                value = _clean(
                    line[
                        len(label) + 1:
                    ]
                )

                if (
                    not value
                    and index + 1 < len(lines)
                ):
                    value = _clean(
                        lines[index + 1]
                    )

            else:
                continue

            if (
                value
                and index + 2 < len(lines)
                and lines[index + 2].lstrip().startswith("/")
            ):
                value = _clean(
                    f"{value} {lines[index + 2]}"
                )

            if not value:
                continue

            result = (
                classify_house_condition(
                    {
                        "condition": value,
                        "title": "",
                        "raw_text": "",
                    }
                )
            )

            condition_class = str(
                result.get(
                    "condition_class"
                )
                or "unknown"
            ).strip().lower()

            if condition_class == "unknown":
                continue

            return {
                "condition_class": (
                    result.get(
                        "condition_class"
                    )
                ),
                "condition_reason": (
                    result.get(
                        "condition_reason"
                    )
                ),
                "condition_source": (
                    "browser_explicit"
                ),
                "condition_portal_label": (
                    line
                    if lower == label
                    else line[
                        :len(label)
                    ]
                ),
                "condition_portal_value": value,
            }

    return None


def condition_payload_from_browser(
    property_data,
    page_text,
):

    property_type = str(
        property_data.get(
            "property_type"
        )
        or ""
    ).strip().lower()

    if property_type not in {
        "house",
        "farm",
    }:
        return None

    current_class = str(
        property_data.get(
            "condition_class"
        )
        or "unknown"
    ).strip().lower()

    current_source = str(
        property_data.get(
            "condition_source"
        )
        or ""
    ).strip().lower()

    # Eine bewusste Telegram-Entscheidung ist stärker als
    # jede spätere Portalangabe und wird nie überschrieben.
    if current_source == "telegram":
        return None

    # Bestehende automatische/heuristische Zustände werden
    # vorerst ebenfalls nicht stillschweigend geändert.
    # Der Browser schließt gezielt nur echte Lücken.
    if current_class not in {
        "",
        "unknown",
    }:
        return None

    return extract_explicit_condition(
        page_text
    )
