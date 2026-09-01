def classify_buildability(
    property_data
):

    # --------------------------------------------------------
    # Manuelle Entscheidung hat immer Vorrang.
    #
    # Dadurch können Browserdaten eine per Telegram gesetzte
    # Entscheidung NICHT wieder überschreiben.
    # --------------------------------------------------------

    explicit = str(
        property_data.get(
            "buildability"
        )
        or ""
    ).strip().upper()

    explicit_map = {
        "CONSTRUCTIONPLAN": {
            "residential_building_allowed": True,
            "buildability_class": "residential",
            "buildability_reason": "Bebauungsplan",
        },

        "PRELIMINARY_APPROVAL": {
            "residential_building_allowed": True,
            "buildability_class": "residential",
            "buildability_reason":
                "positiver Bauvorbescheid / positive Bauvoranfrage",
        },

        "NEIGHBOURCONSTRUCTION": {
            "residential_building_allowed": True,
            "buildability_class": "residential",
            "buildability_reason":
                "Nachbarbebauung / §34",
        },

        "EXTERNALAREA": {
            "residential_building_allowed": False,
            "buildability_class": "ko",
            "buildability_reason":
                "Außenbereich / §35",
        },

        "NO_INFORMATION": {
            "residential_building_allowed": None,
            "buildability_class": "unknown",
            "buildability_reason": None,
        },
    }

    if explicit in explicit_map:
        return dict(
            explicit_map[
                explicit
            ]
        )

    # --------------------------------------------------------
    # Automatische Textanalyse.
    #
    # browser_text ist hier bewusst enthalten.
    # --------------------------------------------------------

    text = " ".join(
        str(value or "")
        for value in (
            property_data.get("title"),
            property_data.get("raw_text"),
            property_data.get("browser_text"),
        )
    ).casefold()

    # --------------------------------------------------------
    # Eindeutige Ferien-/Wochenendhausgebiete
    # --------------------------------------------------------

    holiday_area_terms = (
        "wochenendhausgebiet",
        "ferienhausgebiet",
        "ferien-/wochenendhausgebiet",
        "sondergebiet wochenendhaus",
        "sondergebiet ferienhaus",
    )

    for term in holiday_area_terms:

        if term in text:

            return {
                "residential_building_allowed":
                    False,

                "holiday_area":
                    True,

                "buildability_class":
                    "ko",

                "buildability_reason":
                    term,
            }

    # --------------------------------------------------------
    # Eindeutiges KO
    # --------------------------------------------------------

    ko_terms = (
        "außenbereich",
        "aussenbereich",
        "außengebiet",
        "aussengebiet",
        "§ 35",
        "§35",
        "gewerbe- und industrieareal",
        "gewerbegebiet",
        "industriegebiet",
        "industrieareal",
        "gewerbeareal",

        # Nur eindeutige Aussagen zur Wohn-/Dauerbebauung.
        "wohnnutzung nicht zulässig",
        "wohnnutzung ausgeschlossen",
        "dauerhaftes wohnen nicht zulässig",
        "dauerhafte wohnnutzung nicht zulässig",
        "dauerhafte bebauung nicht möglich",
    )

    for term in ko_terms:

        if term in text:

            return {
                "residential_building_allowed":
                    False,

                "buildability_class":
                    "ko",

                "buildability_reason":
                    term,
            }

    # --------------------------------------------------------
    # Starke positive Aussagen
    # --------------------------------------------------------

    strong_good_terms = (
        (
            "positive bauvoranfrage liegt vor",
            "positive Bauvoranfrage"
        ),
        (
            "bauvoranfrage positiv beschieden",
            "positive Bauvoranfrage"
        ),
        (
            "positiver bauvorbescheid",
            "positiver Bauvorbescheid"
        ),
    )

    for term, reason in strong_good_terms:

        if term in text:

            return {
                "residential_building_allowed":
                    True,

                "buildability_class":
                    "residential",

                "buildability_reason":
                    reason,
            }

    # --------------------------------------------------------
    # Bisherige positive Regeln
    # --------------------------------------------------------

    good_terms = (
        "nachbarbebauung",
        "§ 34",
        "§34",
        "bebauungsplan",
        "potenzielles bauland",
        "als potenzielles bauland",
        "als bauland genutzt werden kann",
    )

    for term in good_terms:

        if term not in text:
            continue

        # "kein Bebauungsplan" darf natürlich nicht durch
        # das Wort "Bebauungsplan" positiv werden.
        if (
            term == "bebauungsplan"
            and (
                "kein bebauungsplan"
                in text
                or
                "keinen bebauungsplan"
                in text
            )
        ):
            continue

        return {
            "residential_building_allowed":
                True,

            "buildability_class":
                "residential",

            "buildability_reason":
                term,
        }

    # --------------------------------------------------------
    # Unklare / prüfbedürftige Fälle
    #
    # Diese sind ausdrücklich KEIN automatisches KO.
    # --------------------------------------------------------

    uncertain_terms = (
        (
            "nach positiver bauvoranfrage",
            "Bebauung nur nach positiver Bauvoranfrage"
        ),

        (
            "bauvoranfrage",
            "Bebaubarkeit muss per Bauvoranfrage geklärt werden"
        ),

        (
            "erholungsgrundstück",
            "Erholungsgrundstück"
        ),

        (
            "freizeitgrundstück",
            "Freizeitgrundstück"
        ),

        (
            "wochenendgrundstück",
            "Wochenendgrundstück"
        ),

        (
            "kein bebauungsplan",
            "kein Bebauungsplan"
        ),

        (
            "keinen bebauungsplan",
            "kein Bebauungsplan"
        ),
    )

    for term, reason in uncertain_terms:

        if term in text:

            return {
                "residential_building_allowed":
                    None,

                "buildability_class":
                    "uncertain",

                "buildability_reason":
                    reason,
            }

    # --------------------------------------------------------
    # Keine belastbare Information
    # --------------------------------------------------------

    return {
        "residential_building_allowed":
            None,

        "buildability_class":
            "unknown",

        "buildability_reason":
            None,
    }
