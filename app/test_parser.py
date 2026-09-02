import sys
import email
import json

from monitor import get_email_text, parse_immoscout
from property_types import detect_property_type
from scoring import score_land


def main():

    if len(sys.argv) != 2:
        print(
            "Usage: python test_parser.py /path/to/mail.eml"
        )
        sys.exit(1)

    path = sys.argv[1]

    with open(path, "rb") as f:
        raw = f.read()

    message = email.message_from_bytes(raw)

    text = get_email_text(message)

    properties = parse_immoscout(text)

    print()
    print(f"Found {len(properties)} object(s)")
    print("=" * 70)

    for number, property_data in enumerate(
        properties,
        start=1
    ):

        property_type = detect_property_type(
            property_data
        )

        property_data["property_type"] = (
            property_type
        )

        print()
        print(f"OBJECT #{number}")
        print("-" * 70)

        print(
            f"Portal ID : "
            f"{property_data.get('portal_id')}"
        )

        print(
            f"Search ID : "
            f"{property_data.get('search_id')}"
        )

        print(
            f"Type      : "
            f"{property_type.upper()}"
        )

        print(
            f"Title     : "
            f"{property_data.get('title')}"
        )

        print(
            f"Location  : "
            f"{property_data.get('location')}"
        )

        print(
            f"Price     : "
            f"{property_data.get('price')}"
        )

        print(
            f"Plot      : "
            f"{property_data.get('plot_area')}"
        )

        print(
            f"Living    : "
            f"{property_data.get('living_area')}"
        )

        print(
            f"Rooms     : "
            f"{property_data.get('rooms')}"
        )

        print(
            f"URL       : "
            f"{property_data.get('url')}"
        )

        if property_type == "land":

            result = score_land(
                property_data
            )

            print()
            print("SCORING")
            print("-" * 70)

            print(
                f"Score     : "
                f"{result['score']}/100"
            )

            print(
                f"Rating    : "
                f"{result['rating']}"
            )

            print(
                f"KO        : "
                f"{result['ko']}"
            )

            if result["ko_reasons"]:

                print(
                    "KO reasons:"
                )

                for reason in result["ko_reasons"]:
                    print(
                        f"  - {reason}"
                    )

            if result["reasons"]:

                print(
                    "Score details:"
                )

                for reason in result["reasons"]:
                    print(
                        f"  - {reason}"
                    )

        print()
        print("=" * 70)


if __name__ == "__main__":
    main()
