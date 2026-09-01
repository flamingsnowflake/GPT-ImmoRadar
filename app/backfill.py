import os
import glob
import email
import sqlite3

from monitor import (
    DB_PATH,
    get_email_text,
    parse_immoscout,
    detect_property_type,
    enrich_property,
    save_property,
    score_land,
)


def main():

    conn = sqlite3.connect(DB_PATH)

    files = sorted(
        glob.glob(
            "/data/emails/**/*.eml",
            recursive=True
        )
    )

    print(f"Found {len(files)} archived mails")

    updated = 0

    for path in files:

        try:

            with open(path, "rb") as f:
                raw = f.read()

            message = email.message_from_bytes(raw)

            body = get_email_text(message)

            properties = parse_immoscout(body)

            for property_data in properties:

                property_type = detect_property_type(
                    property_data
                )

                property_data["property_type"] = (
                    property_type
                )

                # Erst einmal nur ImmoScout-LAND und
                # normale HOUSE/FARM-Daten korrigieren.
                # Externe Anreicherung nur für LAND.
                if property_type == "land":

                    property_data = enrich_property(
                        conn,
                        property_data
                    )

                    score_result = score_land(
                        property_data
                    )

                    property_data["score"] = (
                        score_result["score"]
                    )

                    property_data["rating"] = (
                        score_result["rating"]
                    )

                    property_data["is_ko"] = int(
                        score_result["ko"]
                    )

                    property_data["score_details"] = (
                        score_result
                    )

                else:

                    property_data["score"] = None
                    property_data["rating"] = None
                    property_data["is_ko"] = 0
                    property_data["score_details"] = None

                save_property(
                    conn,
                    property_data,
                    None
                )

                print(
                    f"{property_type.upper():8} "
                    f"{property_data.get('portal_id')} | "
                    f"{property_data.get('title')} | "
                    f"{property_data.get('location')}"
                )

                updated += 1

        except Exception as exc:

            print(
                f"ERROR {path}: "
                f"{type(exc).__name__}: {exc}"
            )

    conn.close()

    print()
    print(f"Processed {updated} property occurrence(s)")


if __name__ == "__main__":
    main()
