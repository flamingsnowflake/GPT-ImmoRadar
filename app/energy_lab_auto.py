def next_energy_action(
    current_portal_id,
    rows,
):

    current_portal_id = str(
        current_portal_id
        or ""
    )

    rows = list(
        rows
        or []
    )

    # Solange das aktuell angezeigte Objekt noch in der
    # Energie-Warteschlange steht, darf Telegram nicht
    # vorspringen. Das ist insbesondere wichtig, wenn während
    # der Bearbeitung ein neueres Objekt hereinkommt und damit
    # an Position 1 der Warteschlange landet.
    for row in rows:

        portal_id = str(
            row.get("portal_id")
            or ""
        )

        if portal_id == current_portal_id:
            return "wait", None

    if not rows:
        return "done", None

    return "advance", rows[0]
