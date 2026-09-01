from property_types import is_house_type



def property_action_keyboard(
    portal_id,
    property_type,
    number="new",
    favorite=False,
    user_status="active",
):

    rows = []

    # --------------------------------------------------------
    # Koordinaten
    #
    # Ersetzt den früheren großen ID-Button.
    # --------------------------------------------------------

    rows.append(
        [
            {
                "text": "📍 Koordinaten",
                "callback_data":
                    f"coords:{portal_id}:{property_type}:{number}"
            }
        ]
    )

    # --------------------------------------------------------
    # Details / Zustand
    # --------------------------------------------------------

    if is_house_type(property_type):

        rows.append(
            [
                {
                    "text": "🔎 Details",
                    "callback_data":
                        f"property:{portal_id}:{property_type}:{number}"
                },
                {
                    "text": "🔧 Zustand",
                    "callback_data":
                        f"inspect:{portal_id}:{property_type}:{number}"
                }
            ]
        )

    else:

        rows.append(
            [
                {
                    "text": "🔎 Details",
                    "callback_data":
                        f"property:{portal_id}:{property_type}:{number}"
                }
            ]
        )

    # --------------------------------------------------------
    # Persönliche Merkliste
    # --------------------------------------------------------

    rows.append(
        [
            {
                "text":
                    "⭐ Gemerkt"
                    if favorite
                    else "⭐ Merken",
                "callback_data":
                    f"favorite:{portal_id}:{property_type}:{number}"
            }
        ]
    )

    # --------------------------------------------------------
    # Persönlicher Objektstatus
    #
    # Offline und Kein Interesse sind gegenseitig
    # ausschließend und vollständig reversibel.
    # --------------------------------------------------------

    user_status = str(
        user_status
        or "active"
    ).strip().lower()

    if user_status == "offline":

        rows.append(
            [
                {
                    "text": "↩️ Wieder online",
                    "callback_data":
                        f"offline:{portal_id}:{property_type}:{number}"
                }
            ]
        )

    elif user_status == "not_interested":

        rows.append(
            [
                {
                    "text": "↩️ Wieder interessant",
                    "callback_data":
                        f"spam:{portal_id}:{property_type}:{number}"
                }
            ]
        )

    else:

        rows.append(
            [
                {
                    "text": "⛔ Offline",
                    "callback_data":
                        f"offline:{portal_id}:{property_type}:{number}"
                },
                {
                    "text": "🙈 Kein Interesse",
                    "callback_data":
                        f"spam:{portal_id}:{property_type}:{number}"
                }
            ]
        )

    return {
        "inline_keyboard": rows
    }
