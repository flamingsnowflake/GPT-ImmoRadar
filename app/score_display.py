import json


def _details_dict(value):

    if isinstance(value, dict):
        return value

    if not value:
        return {}

    try:
        result = json.loads(value)
    except Exception:
        return {}

    return result if isinstance(result, dict) else {}


def completed_score_lines(
    property_data,
    weighted_first=False,
):

    details = _details_dict(
        property_data.get("score_details")
    )

    score = property_data.get("score")

    if score is None:
        score = details.get("score")

    if score is None:
        return []

    base_score = property_data.get("base_score")

    if base_score is None:
        base_score = details.get("base_score")

    weighting_applied = property_data.get(
        "location_weighting_applied"
    )

    if weighting_applied is None:
        weighting_applied = details.get(
            "location_weighting_applied"
        )

    if weighting_applied and base_score is not None:

        reference = (
            property_data.get("location_reference")
            or details.get("location_reference")
            or "Referenzort"
        )

        base_line = (
            "⭐ Gesamtscore ohne "
            f"{reference}: "
            f"{int(base_score)}/100"
        )
        weighted_line = (
            "📍 Gewichteter "
            f"{reference}-Score: "
            f"{int(score)}/100"
        )

        if weighted_first:
            return [
                weighted_line,
                base_line,
            ]

        return [
            base_line,
            weighted_line,
        ]

    return [
        f"⭐ Gesamtscore: {int(score)}/100"
    ]
