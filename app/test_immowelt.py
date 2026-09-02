import sys
from email import policy
from email.parser import BytesParser

from monitor import (
    get_email_text,
    parse_immowelt,
    detect_property_type,
)


def load(path):

    with open(path, "rb") as f:
        msg = BytesParser(
            policy=policy.default
        ).parse(f)

    text = get_email_text(msg)

    return parse_immowelt(text)


def show(p):

    print("=" * 80)
    print("Portal ID :", p.get("portal_id"))
    print("Type      :", detect_property_type(p).upper())
    print("Title     :", p.get("title"))
    print("Location  :", p.get("location"))
    print("Price     :", p.get("price"))
    print("Plot      :", p.get("plot_area"))
    print("Living    :", p.get("living_area"))
    print("Rooms     :", p.get("rooms"))
    print("URL       :", p.get("url"))


path = sys.argv[1]

properties = load(path)

print(f"Found {len(properties)} object(s)")

for p in properties:
    show(p)
