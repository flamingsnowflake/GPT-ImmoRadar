import json
import sqlite3
import sys

from monitor import DB_PATH
from scoring import score_land


BUILDABILITY_MAP = {
    "BUILDING_PERMIT": {
        "allowed": True,
        "class": "residential",
        "reason": "Baugenehmigung vorhanden",
    },

    "CONSTRUCTIONPLAN": {
        "allowed": True,
        "class": "residential",
        "reason": "Bebauungsplan",
    },

    "NEIGHBOURCONSTRUCTION": {
        "allowed": True,
        "class": "residential",
        "reason": "Nachbarbebauung / §34",
    },

    "EXTERNALAREA": {
        "allowed": False,
        "class": "ko",
        "reason": "Außenbereich / §35",
    },

    "NO_INFORMATION": {
        "allowed": None,
        "class": "unknown",
        "reason": None,
    },
}


def main():

    if len(sys.argv) != 3:
        print(
            "Usage: "
            "python set_buildability.py "
            "<portal_id> "
            "<BUILDING_PERMIT|CONSTRUCTIONPLAN|"
            "NEIGHBOURCONSTRUCTION|EXTERNALAREA|"
            "NO_INFORMATION>"
        )
        sys.exit(1)

    portal_id = sys.argv[1].strip()

    buildability = (
        sys.argv[2]
        .strip()
        .upper()
    )

    if buildability not in BUILDABILITY_MAP:

        print(
            f"Unknown buildability value: "
            f"{buildability}"
        )

        print()
        print("Allowed values:")

        for key in BUILDABILITY_MAP:
            print(f"  {key}")

        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    row = conn.execute(
        """
        SELECT *
        FROM properties
        WHERE portal = 'immoscout24'
          AND portal_id = ?
        """,
        (
            portal_id,
        )
    ).fetchone()

    if not row:

        print(
            f"Property not found: "
            f"{portal_id}"
        )

        conn.close()
        sys.exit(1)

    property_data = dict(row)

    mapping = BUILDABILITY_MAP[
        buildability
    ]

    property_data["buildability"] = (
        buildability
    )

    property_data[
        "buildability_class"
    ] = mapping["class"]

    property_data[
        "buildability_reason"
    ] = mapping["reason"]

    property_data[
        "residential_building_allowed"
    ] = mapping["allowed"]

    # --------------------------------------------------------
    # Score neu berechnen
    # --------------------------------------------------------

    score_result = score_land(
        property_data
    )

    score = score_result["score"]
    rating = score_result["rating"]
    is_ko = int(
        score_result["ko"]
    )

    score_details = json.dumps(
        score_result,
        ensure_ascii=False
    )

    allowed_db = (
        None
        if mapping["allowed"] is None
        else int(mapping["allowed"])
    )

    conn.execute(
        """
        UPDATE properties
        SET
            buildability = ?,
            buildability_class = ?,
            buildability_reason = ?,
            residential_building_allowed = ?,
            score = ?,
            rating = ?,
            is_ko = ?,
            score_details = ?
        WHERE portal = 'immoscout24'
          AND portal_id = ?
        """,
        (
            buildability,
            mapping["class"],
            mapping["reason"],
            allowed_db,
            score,
            rating,
            is_ko,
            score_details,
            portal_id,
        )
    )

    conn.commit()

    print()
    print("=" * 70)
    print(f"ID:          {portal_id}")
    print(
        f"Title:       "
        f"{property_data.get('title')}"
    )
    print(
        f"Location:    "
        f"{property_data.get('location')}"
    )
    print(
        f"Buildability:{buildability}"
    )
    print(
        f"Reason:      "
        f"{mapping['reason']}"
    )
    print(
        f"Residential: "
        f"{mapping['allowed']}"
    )
    print(
        f"Score:       "
        f"{score}/100"
    )
    print(
        f"Rating:      "
        f"{rating}"
    )
    print(
        f"KO:          "
        f"{bool(is_ko)}"
    )

    if score_result.get(
        "ko_reasons"
    ):

        print(
            "KO reasons:  "
            + "; ".join(
                score_result[
                    "ko_reasons"
                ]
            )
        )

    print("=" * 70)

    conn.close()


if __name__ == "__main__":
    main()
