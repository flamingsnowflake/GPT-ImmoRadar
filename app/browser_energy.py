import re


def clean(value):

    if value is None:
        return None

    text = (
        str(value)
        .replace("\u00a0", " ")
        .strip()
    )

    return text or None


def page_lines(text):

    result = []

    for line in (
        str(text or "")
        .replace("\r", "")
        .split("\n")
    ):

        value = clean(line)

        if value:
            result.append(value)

    return result


def normalize_energy_text(text):

    text = (
        str(text or "")
        .replace("\u00a0", " ")
    )

    replacements = (
        (
            r"Energie-\s*ausweistyp",
            "Energieausweistyp",
        ),
        (
            r"Endenergie-\s*bedarf",
            "Endenergiebedarf",
        ),
        (
            r"Endenergie-\s*verbrauch",
            "Endenergieverbrauch",
        ),
        (
            r"Energieeffizienz-\s*klasse",
            "Energieeffizienzklasse",
        ),
        (
            r"Wesentliche\s+Energieträger",
            "Wesentliche Energieträger",
        ),
        (
            r"Wesentlicher\s+Energieträger",
            "Wesentlicher Energieträger",
        ),
        (
            r"Baujahr laut\s+Energieausweis",
            "Baujahr laut Energieausweis",
        ),
    )

    for pattern, replacement in replacements:

        text = re.sub(
            pattern,
            replacement,
            text,
            flags=re.I,
        )

    return text


def extract_energy_section(lines):

    start_patterns = (
        re.compile(
            r"^Bausubstanz\s*&\s*Energieausweis$",
            re.I,
        ),
        re.compile(
            r"^Bausubstanz\s+und\s+Energie$",
            re.I,
        ),
    )

    end_patterns = (
        re.compile(r"^Beschreibung$", re.I),
        re.compile(r"^Preisdetails$", re.I),
        re.compile(r"^Lage$", re.I),
        re.compile(
            r"^Weitere Informationen$",
            re.I,
        ),
        re.compile(r"^Kosten$", re.I),
    )

    start = None

    for index, line in enumerate(lines):

        if any(
            pattern.search(line)
            for pattern in start_patterns
        ):
            start = index
            break

    if start is None:
        return []

    result = []

    for line in lines[
        start + 1:
        start + 61
    ]:

        if (
            result
            and any(
                pattern.search(line)
                for pattern in end_patterns
            )
        ):
            break

        result.append(line)

    return result


def value_after_label(
    lines,
    labels,
):

    normalized_labels = [
        label.lower()
        for label in labels
    ]

    for index, line in enumerate(lines):

        lower = line.lower()

        for label in normalized_labels:

            if lower == label:

                if index + 1 < len(lines):
                    return clean(
                        lines[index + 1]
                    )

            if lower.startswith(
                label + ":"
            ):
                return clean(
                    line[
                        len(label) + 1:
                    ]
                )

            if lower.startswith(
                label + " "
            ):
                return clean(
                    line[
                        len(label) + 1:
                    ]
                )

    return None


def first_regex(
    text,
    patterns,
):

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            flags=re.I,
        )

        if match:
            return clean(
                match.group(1)
            )

    return None


def normalize_number(value):

    if not value:
        return None

    normalized = re.sub(
        r"\s",
        "",
        str(value),
    )

    normalized = re.sub(
        r"\.(?=\d{3}(?:\D|$))",
        "",
        normalized,
    )

    normalized = normalized.replace(
        ",",
        ".",
    )

    try:
        return float(normalized)

    except ValueError:
        return None


def extract_energy_data(
    text,
    energy_class_hint=None,
):

    lines = page_lines(text)

    full_text = "\n".join(
        lines
    )

    section = extract_energy_section(
        lines
    )

    section_text = "\n".join(
        section
    )

    preferred_text = normalize_energy_text(
        section_text or full_text
    )

    normalized_full_text = (
        normalize_energy_text(
            full_text
        )
    )

    energy_class = first_regex(
        normalized_full_text,
        (
            (
                r"Energieeffizienz"
                r"[\s\u00ad\u2010\u2011\u2012\u2013\u2014-]*"
                r"klasse\s*:?\s*"
                r"([A-H](?:\+)?)(?![A-Za-z])"
            ),
            (
                r"Energieausweis\s*"
                r"(?:/|\n|:)\s*"
                r"([A-H](?:\+)?)(?![A-Za-z])"
            ),
        ),
    )

    if (
        not energy_class
        and section
    ):

        energy_heading_index = None

        for index, line in enumerate(
            section
        ):

            if re.fullmatch(
                r"Energieausweis",
                line,
                flags=re.I,
            ):
                energy_heading_index = index
                break

        if energy_heading_index is not None:

            for line in section[
                energy_heading_index + 1:
                energy_heading_index + 6
            ]:

                match = re.fullmatch(
                    r"([A-H](?:\+)?)",
                    line,
                    flags=re.I,
                )

                if match:
                    energy_class = (
                        match.group(1)
                    )
                    break

    if not energy_class:

        hint = str(
            energy_class_hint
            or ""
        ).strip().upper()

        if re.fullmatch(
            r"[A-H](?:\+)?",
            hint,
        ):
            energy_class = hint

    if energy_class:
        energy_class = (
            energy_class
            .strip()
            .upper()
        )

    energy_value_text = first_regex(
        normalized_full_text,
        (
            (
                r"Endenergie"
                r"[\s\u00ad\u2010\u2011\u2012\u2013\u2014-]*"
                r"(?:bedarf|verbrauch)"
                r"\s*:?\s*"
                r"([0-9]{1,4}"
                r"(?:[.,][0-9]{1,2})?)"
            ),
            (
                r"Energieverbrauch"
                r"\s*:?\s*"
                r"([0-9]{1,4}"
                r"(?:[.,][0-9]{1,2})?)"
            ),
        ),
    )

    energy_value = normalize_number(
        energy_value_text
    )

    certificate_type = "unknown"

    if (
        re.search(
            r"Energieausweistyp\s*:?\s*Bedarfsausweis",
            preferred_text,
            re.I,
        )
        or re.search(
            r"\bBedarfsausweis\b",
            preferred_text,
            re.I,
        )
    ):
        certificate_type = "demand"

    elif (
        re.search(
            r"Energieausweistyp\s*:?\s*Verbrauchsausweis",
            preferred_text,
            re.I,
        )
        or re.search(
            r"\bVerbrauchsausweis\b",
            preferred_text,
            re.I,
        )
    ):
        certificate_type = "consumption"

    elif re.search(
        r"\bBedarfsausweis\b",
        normalized_full_text,
        re.I,
    ):
        certificate_type = "demand"

    elif re.search(
        r"\bVerbrauchsausweis\b",
        normalized_full_text,
        re.I,
    ):
        certificate_type = "consumption"

    certificate_status = "unknown"

    if (
        re.search(
            (
                r"Energieausweis[\s\S]{0,120}"
                r"(?:laut Gesetz )?"
                r"nicht erforderlich"
            ),
            normalized_full_text,
            re.I,
        )
        or re.search(
            (
                r"(?:laut Gesetz )?"
                r"nicht erforderlich"
                r"[\s\S]{0,120}"
                r"Energieausweis"
            ),
            normalized_full_text,
            re.I,
        )
    ):
        certificate_status = (
            "not_required"
        )

    elif re.search(
        (
            r"Energieausweis[\s\S]{0,120}"
            r"(?:noch nicht|"
            r"nicht verfügbar|"
            r"nicht vorhanden)"
        ),
        normalized_full_text,
        re.I,
    ):
        certificate_status = (
            "not_available_yet"
        )

    elif (
        energy_class
        or energy_value is not None
        or certificate_type != "unknown"
        or re.search(
            r"Energieausweis\s*:?\s*liegt vor",
            normalized_full_text,
            re.I,
        )
    ):
        certificate_status = "available"

    # Klasse/Wert schlagen einen widersprüchlichen Warte-Status.
    # Das schützt insbesondere IS24-Seiten, auf denen Textfragmente wie
    # "nicht vorhanden" außerhalb der eigentlichen Energiedaten vorkommen.
    if (
        certificate_status == "not_available_yet"
        and (
            energy_class
            or energy_value is not None
        )
    ):
        certificate_status = "available"

    heating_type = first_regex(
        preferred_text,
        (
            r"Heizungsart\s*:?\s*([^\n]{1,120})",
        ),
    )

    if not heating_type:
        heating_type = value_after_label(
            section,
            (
                "Heizungsart",
            ),
        )

    if not heating_type:
        heating_type = first_regex(
            normalized_full_text,
            (
                r"Heizungsart\s*:?\s*([^\n]{1,120})",
            ),
        )

    energy_source = first_regex(
        preferred_text,
        (
            (
                r"(?:Wesentliche Energieträger|"
                r"Wesentlicher Energieträger|"
                r"Hauptenergieträger|"
                r"Energieträger)"
                r"\s*:?\s*"
                r"([^\n]{1,120})"
            ),
        ),
    )

    if not energy_source:
        energy_source = value_after_label(
            section,
            (
                "Energieträger",
                "Wesentliche Energieträger",
                "Wesentlicher Energieträger",
                "Hauptenergieträger",
            ),
        )

    if not energy_source:
        energy_source = first_regex(
            normalized_full_text,
            (
                (
                    r"(?:Wesentliche Energieträger|"
                    r"Wesentlicher Energieträger|"
                    r"Hauptenergieträger|"
                    r"Energieträger)"
                    r"\s*:?\s*"
                    r"([^\n]{1,120})"
                ),
            ),
        )

    year_text = first_regex(
        preferred_text,
        (
            (
                r"Baujahr laut Energieausweis"
                r"\s*:?\s*"
                r"((?:18|19|20)\d{2})"
            ),
            (
                r"Baujahr des Objekts lt\. "
                r"Energieausweis"
                r"(?: ist)?\s*:?\s*"
                r"((?:18|19|20)\d{2})"
            ),
        ),
    )

    if not year_text:
        year_text = value_after_label(
            section,
            (
                "Baujahr laut Energieausweis",
                "Baujahr Gebäude (Ursprung)",
                "Baujahr",
            ),
        )

    construction_year = None

    if year_text:

        match = re.search(
            r"\b(?:18|19|20)\d{2}\b",
            str(year_text),
        )

        if match:
            construction_year = int(
                match.group(0)
            )

    if certificate_status == "not_required":
        energy_class = None
        energy_value = None
        certificate_type = "unknown"

    raw_candidates = []

    if section:
        raw_candidates.append(
            "Bausubstanz/Energie:\n"
            + "\n".join(section)
        )

    relevant_lines = [
        line
        for line in lines
        if re.search(
            (
                r"energie|heizung|"
                r"energieträger|"
                r"hauptenergieträger|"
                r"baujahr"
            ),
            line,
            re.I,
        )
    ]

    if relevant_lines:
        raw_candidates.append(
            "Weitere Treffer:\n"
            + "\n".join(
                relevant_lines[:30]
            )
        )

    raw_text = clean(
        "\n\n".join(
            raw_candidates
        )
    )

    return {
        "energy_class": energy_class,
        "energy_value_kwh": energy_value,
        "energy_certificate_type": certificate_type,
        "energy_certificate_status": certificate_status,
        "heating_type": heating_type,
        "energy_source": energy_source,
        "energy_construction_year": construction_year,
        "energy_data_source": "browser_text_auto",
        "energy_raw_text": (
            raw_text[:5000]
            if raw_text
            else None
        ),
    }


def has_useful_data(data):

    return bool(
        data.get(
            "energy_class"
        )
        or data.get(
            "energy_value_kwh"
        ) is not None
        or data.get(
            "energy_certificate_type"
        ) != "unknown"
        or data.get(
            "energy_certificate_status"
        ) != "unknown"
        or data.get(
            "heating_type"
        )
        or data.get(
            "energy_source"
        )
        or data.get(
            "energy_construction_year"
        )
    )


def has_decisive_energy(data):

    status = str(
        data.get(
            "energy_certificate_status"
        )
        or "unknown"
    ).strip().lower()

    return bool(
        data.get("energy_class")
        or data.get("energy_value_kwh")
        is not None
        or data.get(
            "energy_certificate_type"
        ) != "unknown"
        or status in {
            "available",
            "not_required",
            "no_label",
        }
    )


def energy_payload_from_browser(
    property_data,
    page_text,
    energy_class_hint=None,
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

    existing_updated_at = (
        property_data.get(
            "energy_updated_at"
        )
    )

    existing_status = str(
        property_data.get(
            "energy_certificate_status"
        )
        or "unknown"
    ).strip().lower()

    existing_source = str(
        property_data.get(
            "energy_data_source"
        )
        or ""
    ).strip().lower()

    auto_unknown = (
        existing_updated_at is not None
        and existing_status == "unknown"
        and existing_source in {
            "browser_text_auto",
            "browser_text_backfill",
            "browser_text_checked_no_energy",
        }
    )

    if (
        existing_updated_at is not None
        and existing_status
        != "not_available_yet"
        and not auto_unknown
    ):
        return None

    energy = extract_energy_data(
        page_text,
        energy_class_hint=energy_class_hint,
    )

    if auto_unknown:

        if not has_decisive_energy(
            energy
        ):
            return None

        return energy

    if (
        existing_status
        == "not_available_yet"
    ):

        if (
            energy.get(
                "energy_certificate_status"
            )
            == "not_available_yet"
        ):
            return None

        if not has_decisive_energy(
            energy
        ):
            return None

        return energy

    if has_useful_data(
        energy
    ):
        return energy

    return {
        "energy_class": None,
        "energy_value_kwh": None,
        "energy_certificate_type": "unknown",
        "energy_certificate_status": "unknown",
        "heating_type": None,
        "energy_source": None,
        "energy_construction_year": None,
        "energy_data_source": (
            "browser_text_checked_no_energy"
        ),
        "energy_raw_text": None,
    }
