from config_loader import CONFIG


CONDITION_PRIORITY = (
    "dilapidated",
    "major_renovation",
    "renovation_needed",
    "cosmetic_renovation",
    "maintained",
    "good",
    "turnkey",
)


def classify_house_condition(property_data):

    config = CONFIG.house_condition_config()

    classes = config.get(
        "classes",
        {}
    )

    # --------------------------------------------------------
    # Textquellen
    #
    # Falls wir später ein explizites Portal-Zustandsfeld
    # parsen, kann es hier mit aufgenommen werden.
    # --------------------------------------------------------

    explicit_condition = (
        property_data.get("condition")
        or ""
    )

    title = (
        property_data.get("title")
        or ""
    )

    raw_text = (
        property_data.get("raw_text")
        or ""
    )

    # Explizites Zustandsfeld zuerst in den Text aufnehmen.
    # Die Priorität der Klassen selbst bleibt trotzdem
    # konservativ: schlechter Zustand gewinnt.
    text = " ".join([
        str(explicit_condition),
        str(title),
        str(raw_text),
    ]).casefold()

    # --------------------------------------------------------
    # Klassifizieren
    # --------------------------------------------------------

    for condition_class in CONDITION_PRIORITY:

        keywords = classes.get(
            condition_class,
            []
        )

        for keyword in keywords:

            normalized = (
                str(keyword)
                .strip()
                .casefold()
            )

            if not normalized:
                continue

            if normalized in text:

                source = "raw_text"

                explicit_lower = (
                    str(explicit_condition)
                    .casefold()
                )

                title_lower = (
                    str(title)
                    .casefold()
                )

                if normalized in explicit_lower:
                    source = "condition"

                elif normalized in title_lower:
                    source = "title"

                return {
                    "condition_class":
                        condition_class,

                    "condition_reason":
                        str(keyword),

                    "condition_source":
                        source,
                }

    return {
        "condition_class":
            "unknown",

        "condition_reason":
            None,

        "condition_source":
            None,
    }
