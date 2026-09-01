import html
import re
from html.parser import HTMLParser
from urllib.parse import urlparse

import urllib.request


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0 Safari/537.36"
)


def _clean_text(value):

    value = html.unescape(
        str(value or "")
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


def _normalize_key(value):

    value = _clean_text(
        value
    ).lower()

    value = value.rstrip(
        ":"
    )

    return value.strip()


def parse_number(value):

    value = _clean_text(
        value
    )

    if not value:
        return None

    # Nur Zahl, Dezimal- und Tausenderzeichen behalten.
    match = re.search(
        r"-?\d[\d.\s]*(?:,\d+)?",
        value,
    )

    if not match:
        return None

    number = (
        match.group(0)
        .replace("\xa0", "")
        .replace(" ", "")
    )

    # Deutsch:
    #
    # 94.000       -> 94000
    # 1.485,00     -> 1485.00
    # 3,50         -> 3.50
    #
    if "," in number:

        number = (
            number
            .replace(".", "")
            .replace(",", ".")
        )

    elif re.fullmatch(
        r"-?\d{1,3}(?:\.\d{3})+",
        number,
    ):

        number = number.replace(
            ".",
            "",
        )

    try:
        return float(
            number
        )

    except ValueError:
        return None


class OhneMaklerHTMLParser(
    HTMLParser
):

    def __init__(self):

        super().__init__(
            convert_charrefs=True
        )

        self.skip_depth = 0

        self.in_td = False
        self.in_th = False
        self.current_cell = []
        self.current_row = []
        self.rows = []

        self.in_h1 = False
        self.current_h1 = []
        self.h1_values = []

        self.main_depth = 0
        self.main_chunks = []

        self.visible_chunks = []

        self.h1_end_index = None

        self.og_title = None
        self.meta_description = None

    def handle_starttag(
        self,
        tag,
        attrs,
    ):

        tag = tag.lower()

        attrs = dict(
            attrs
        )

        if tag in (
            "script",
            "style",
            "noscript",
        ):

            self.skip_depth += 1
            return

        if self.skip_depth:
            return

        if tag == "main":
            self.main_depth += 1

        if tag == "tr":

            self.current_row = []

        elif tag in (
            "td",
            "th",
        ):

            self.current_cell = []

            if tag == "td":
                self.in_td = True
            else:
                self.in_th = True

        elif tag == "h1":

            self.in_h1 = True
            self.current_h1 = []

        elif tag == "meta":

            prop = (
                attrs.get("property")
                or ""
            ).lower()

            name = (
                attrs.get("name")
                or ""
            ).lower()

            content = _clean_text(
                attrs.get("content")
            )

            if (
                prop == "og:title"
                and content
            ):

                self.og_title = content

            if (
                name == "description"
                and content
            ):

                self.meta_description = (
                    content
                )

    def handle_endtag(
        self,
        tag,
    ):

        tag = tag.lower()

        if tag in (
            "script",
            "style",
            "noscript",
        ):

            if self.skip_depth:
                self.skip_depth -= 1

            return

        if self.skip_depth:
            return

        if tag == "td":

            value = _clean_text(
                " ".join(
                    self.current_cell
                )
            )

            self.current_row.append(
                value
            )

            self.current_cell = []
            self.in_td = False

        elif tag == "th":

            value = _clean_text(
                " ".join(
                    self.current_cell
                )
            )

            self.current_row.append(
                value
            )

            self.current_cell = []
            self.in_th = False

        elif tag == "tr":

            cells = [
                _clean_text(cell)
                for cell in self.current_row
                if _clean_text(cell)
            ]

            if cells:
                self.rows.append(
                    cells
                )

            self.current_row = []

        elif tag == "h1":

            value = _clean_text(
                " ".join(
                    self.current_h1
                )
            )

            if value:
                self.h1_values.append(
                    value
                )

            self.current_h1 = []
            self.in_h1 = False

            self.h1_end_index = len(
                self.visible_chunks
            )

        elif tag == "main":

            if self.main_depth:
                self.main_depth -= 1

    def handle_data(
        self,
        data,
    ):

        if self.skip_depth:
            return

        value = _clean_text(
            data
        )

        if not value:
            return

        self.visible_chunks.append(
            value
        )

        if self.main_depth:
            self.main_chunks.append(
                value
            )

        if (
            self.in_td
            or self.in_th
        ):
            self.current_cell.append(
                value
            )

        if self.in_h1:
            self.current_h1.append(
                value
            )


def _rows_to_facts(rows):

    facts = {}

    for row in rows:

        # Ohne-Makler verwendet überwiegend:
        #
        # KEY | VALUE
        #
        # Einige Tabellen können aber auch enthalten:
        #
        # KEY | VALUE | KEY | VALUE
        #
        for index in range(
            0,
            len(row) - 1,
            2,
        ):

            key = _normalize_key(
                row[index]
            )

            value = _clean_text(
                row[index + 1]
            )

            if (
                key
                and value
                and key not in facts
            ):

                facts[key] = value

    return facts


def _fact(
    facts,
    *names,
):

    for name in names:

        key = _normalize_key(
            name
        )

        if key in facts:
            return facts[key]

    return None

def _find_summary_metric_html(
    page_html,
    label,
    unit=None,
):

    matches = list(
        re.finditer(
            re.escape(label),
            page_html,
            re.I,
        )
    )

    for match in matches:

        start = max(
            0,
            match.start() - 1800,
        )

        fragment = page_html[
            start:match.start()
        ]

        # Die großen Kennzahlen bei Ohne-Makler
        # stehen in Spans wie:
        #
        # <span class="block text-lg ...">
        #     68 m²
        # </span>
        #
        # bzw.
        #
        # <span class="block text-lg ...">
        #     3
        # </span>

        values = re.findall(
            r'<span\b'
            r'[^>]*'
            r'class=["\']'
            r'(?=[^"\']*\bblock\b)'
            r'(?=[^"\']*\btext-lg\b)'
            r'[^"\']*'
            r'["\']'
            r'[^>]*>'
            r'\s*([^<]+?)\s*'
            r'</span>',
            fragment,
            re.I | re.S,
        )

        for candidate in reversed(
            values
        ):

            candidate = _clean_text(
                candidate
            )

            number = parse_number(
                candidate
            )

            if number is None:
                continue

            if unit == "m2":

                if "m²" in candidate:
                    return candidate

                continue

            if unit == "rooms":

                if (
                    "m²" not in candidate
                    and "€" not in candidate
                    and 0 < number <= 50
                ):
                    return candidate

            else:

                return candidate

    return None

def _find_location(parser):

    chunks = parser.visible_chunks

    start = (
        parser.h1_end_index
        if parser.h1_end_index is not None
        else 0
    )

    # Objektlage steht auf Ohne-Makler unmittelbar im
    # oberen Exposé-Bereich. Nur dort suchen, damit wir
    # nicht versehentlich die Adresse des Anbieters oder
    # des Portalbetreibers erwischen.
    candidates = chunks[
        start:start + 80
    ]

    for index, value in enumerate(
        candidates
    ):

        if not re.search(
            r"\b\d{5}\b",
            value,
        ):
            continue

        # Reine Preis-/Zahlzeilen ausschließen.
        if "€" in value:
            continue

        location = value

        # Falls Straße und PLZ/Ort auf zwei HTML-Blöcke
        # verteilt sind, vorherigen Text mitnehmen.
        if index > 0:

            previous = candidates[
                index - 1
            ]

            if (
                not re.search(
                    r"€|m²|\bZimmer\b",
                    previous,
                    re.I,
                )
                and len(previous) <= 120
                and not re.fullmatch(
                    r"\d+(?:[.,]\d+)?",
                    previous,
                )
            ):

                # Nur mitnehmen, wenn der vorige Block
                # wie Straße/Ortsteil aussieht.
                if re.search(
                    r"[A-Za-zÄÖÜäöüß]",
                    previous,
                ):

                    location = (
                        previous
                        + ", "
                        + value
                    )

        return _clean_text(
            location
        )

    return None


def _detect_property_type(
    object_class,
    object_type,
    title,
):

    object_class_l = (
        object_class
        or ""
    ).lower()

    object_type_l = (
        object_type
        or ""
    ).lower()

    title_l = (
        title
        or ""
    ).lower()

    if "grundstück" in object_class_l:
        return "land"

    if object_class_l == "haus":
        return "house"

    # Fallback, falls Ohne-Makler die Bezeichnung einmal
    # anders liefert.
    if "grundstück" in title_l:
        return "land"

    house_terms = (
        "einfamilienhaus",
        "zweifamilienhaus",
        "mehrfamilienhaus",
        "bauernhaus",
        "bungalow",
        "villa",
        "doppelhaushälfte",
        "reihenhaus",
        "reihenendhaus",
        "haus",
    )

    if any(
        term in object_type_l
        for term in house_terms
    ):
        return "house"

    return None


def parse_ohne_makler_html(
    page_html,
    url,
):

    parser = OhneMaklerHTMLParser()

    parser.feed(
        page_html
    )

    facts = _rows_to_facts(
        parser.rows
    )

    match = re.search(
        r"/immobilie/(\d+)",
        url,
        re.I,
    )

    if not match:
        raise ValueError(
            "Keine Ohne-Makler Objekt-ID "
            "in URL gefunden"
        )

    portal_id = match.group(1)

    title = (
        parser.h1_values[0]
        if parser.h1_values
        else parser.og_title
    )

    title = _clean_text(
        title
    )

    object_class = _fact(
        facts,
        "Objektart",
    )

    object_type = _fact(
        facts,
        "Objekttyp",
    )

    property_type = (
        _detect_property_type(
            object_class,
            object_type,
            title,
        )
    )

    price = parse_number(
        _fact(
            facts,
            "Kaufpreis",
        )
    )
    living_area_raw = (
        _fact(
            facts,
            "Wohnfläche",
        )
        or
        _find_summary_metric_html(
            page_html,
            "Wohnfläche",
            unit="m2",
        )
    )

    plot_area_raw = (
        _fact(
            facts,
            "Grundstücksfläche",
        )
        or
        _find_summary_metric_html(
            page_html,
            "Grundstücksfläche",
            unit="m2",
        )
    )

    rooms_raw = (
        _fact(
            facts,
            "Zimmer",
        )
        or
        _find_summary_metric_html(
            page_html,
            "Zimmer",
            unit="rooms",
        )
    )

    living_area = parse_number(
        living_area_raw
    )

    plot_area = parse_number(
        plot_area_raw
    )

    rooms = parse_number(
        rooms_raw
    )

    location = _find_location(
        parser
    )

    raw_chunks = (
        parser.main_chunks
        or parser.visible_chunks
    )

    # --------------------------------------------------------
    # Nur den eigentlichen Exposé-Inhalt übernehmen.
    #
    # Ohne-Makler hängt innerhalb von <main> noch Bereiche
    # wie "Ähnliche Immobilien" an. Dort können Begriffe
    # vorkommen, die mit dem aktuellen Objekt nichts zu tun
    # haben und sonst unsere Blacklist auslösen.
    #
    # Beispiel 485208:
    #
    #   Ähnliche Immobilien
    #   Land- / forstwirtschaftliches Objekt ...
    #
    # Das aktuelle Objekt selbst ist aber ein normales
    # Wohngrundstück.
    # --------------------------------------------------------

    clean_chunks = []

    stop_markers = (
        "ähnliche immobilien",
        "nachricht direkt an den verkäufer senden",
    )

    for chunk in raw_chunks:

        normalized = (
            _clean_text(
                chunk
            )
            .lower()
        )

        if any(
            marker in normalized
            for marker in stop_markers
        ):
            break

        clean_chunks.append(
            chunk
        )

    raw_text = "\n".join(
        clean_chunks
    )
    # Plausibilitätsprüfungen: lieber laut scheitern,
    # als ein halb kaputtes Objekt in die DB schreiben.

    if not title:
        raise RuntimeError(
            "Ohne-Makler: Titel nicht gefunden"
        )

    if property_type is None:
        raise RuntimeError(
            "Ohne-Makler: Objektart nicht erkannt "
            f"(Objektart={object_class!r}, "
            f"Objekttyp={object_type!r})"
        )

    if price is None:
        raise RuntimeError(
            "Ohne-Makler: Kaufpreis nicht gefunden"
        )

    if not location:
        raise RuntimeError(
            "Ohne-Makler: Objektlage nicht gefunden"
        )

    return {
        "portal": "ohne-makler",
        "portal_id": portal_id,
        "property_type": property_type,
        "title": title,
        "url": url,
        "location": location,
        "price": price,
        "living_area": living_area,
        "rooms": rooms,
        "plot_area": plot_area,

        # Ohne-Makler ist ein provisionsfreies Portal.
        "commission_free": 1,

        "raw_text": raw_text,

        # Nur zur Diagnose / späteren Erweiterung.
        "source_object_class":
            object_class,
        "source_object_type":
            object_type,
        "source_facts":
            facts,
    }


def fetch_ohne_makler(
    url,
):

    parsed_url = urlparse(
        url
    )

    host = (
        parsed_url.hostname
        or ""
    ).lower()

    if host not in (
        "ohne-makler.net",
        "www.ohne-makler.net",
    ):

        raise ValueError(
            "Keine ohne-makler.net URL"
        )

    if not re.search(
        r"/immobilie/\d+",
        parsed_url.path,
        re.I,
    ):

        raise ValueError(
            "Keine gültige Ohne-Makler "
            "Immobilien-URL"
        )

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language":
                "de-DE,de;q=0.9,en;q=0.7",
        },
    )

    with urllib.request.urlopen(
        request,
        timeout=30,
    ) as response:

        page_html = response.read().decode(
            "utf-8",
            errors="replace",
        )

        final_url = response.geturl()

    return parse_ohne_makler_html(
        page_html,
        final_url,
    )

if __name__ == "__main__":

    import json
    import sys

    if len(sys.argv) != 2:

        print(
            "Verwendung:"
        )

        print(
            "python ohne_makler.py "
            "https://www.ohne-makler.net/"
            "immobilie/123456/"
        )

        raise SystemExit(2)

    result = fetch_ohne_makler(
        sys.argv[1]
    )

    # raw_text/source_facts hier nicht komplett ausgeben,
    # damit der Test lesbar bleibt.
    preview = dict(
        result
    )

    preview["raw_text"] = (
        f"<{len(result['raw_text'])} Zeichen>"
    )

    print(
        json.dumps(
            preview,
            indent=2,
            ensure_ascii=False,
        )
    )
