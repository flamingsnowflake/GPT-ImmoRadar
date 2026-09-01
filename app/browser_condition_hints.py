import re


CONDITION_LABELS = (
    "zustand der immobilie",
    "objektzustand",
)


CONDITION_CONTINUATION_PREFIXES = (
    "/",
    "und ",
)


def _clean(value):

    if value is None:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(value).replace("\u00a0", " "),
    ).strip()


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


def extract_condition_field(page_text):

    lines = _lines(page_text)

    for index, line in enumerate(lines):

        lower = line.casefold()

        for label in CONDITION_LABELS:

            portal_label = None
            value = ""

            if lower == label:

                portal_label = line

                if index + 1 < len(lines):
                    value = lines[index + 1]

            elif lower.startswith(
                label + ":"
            ):

                portal_label = line[:len(label)]
                value = _clean(
                    line[len(label) + 1:]
                )

                if (
                    not value
                    and index + 1 < len(lines)
                ):
                    value = lines[index + 1]

            else:
                continue

            if (
                value
                and index + 2 < len(lines)
            ):
                continuation = lines[index + 2]
                continuation_lower = (
                    continuation.casefold()
                )

                if continuation_lower.startswith(
                    CONDITION_CONTINUATION_PREFIXES
                ):
                    value = _clean(
                        f"{value} {continuation}"
                    )

            value = _clean(value)

            if not value:
                continue

            return {
                "label": portal_label,
                "value": value,
            }

    return None


def extract_modernization_hint(page_text):

    lines = _lines(page_text)

    for index, line in enumerate(lines):

        lower = line.casefold()

        if lower.startswith(
            "modernisierung/sanierung:"
        ):

            value = _clean(
                line.split(":", 1)[1]
            )

            if value:
                return value

            if index + 1 < len(lines):
                value = _clean(
                    lines[index + 1]
                )

                if value:
                    return value

        if lower.rstrip(":") == (
            "modernisierung/sanierung"
        ):

            if index + 1 < len(lines):
                value = _clean(
                    lines[index + 1]
                )

                if value:
                    return value

        if lower.rstrip(":") in {
            "modernisierung/",
            "modernisierung /",
        }:

            if index + 1 >= len(lines):
                continue

            next_lower = (
                lines[index + 1]
                .casefold()
                .rstrip(":")
            )

            if next_lower != "sanierung":
                continue

            if index + 2 < len(lines):
                value = _clean(
                    lines[index + 2]
                )

                if value:
                    return value

    return None


def condition_lab_hints(page_text):

    field = extract_condition_field(
        page_text
    )

    return {
        "portal_condition": (
            field.get("value")
            if field
            else None
        ),
        "portal_condition_label": (
            field.get("label")
            if field
            else None
        ),
        "modernization": (
            extract_modernization_hint(
                page_text
            )
        ),
    }
