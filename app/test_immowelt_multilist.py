import subprocess
import unittest
from unittest.mock import patch

from monitor import parse_immowelt


FIRST_TRACKING = (
    "https://click.by.immowelt.de/?qs=FIRST"
)

SECOND_TRACKING = (
    "https://click.by.immowelt.de/?qs=SECOND"
)


MAIL_TEXT = f"""
https://click.by.immowelt.de/?qs=OTHER-A
6 Zimmer . 98 m² . 3.636 m²
https://click.by.immowelt.de/?qs=OTHER-B
Kühren,
Aken (Elbe)
(06385)
{FIRST_TRACKING}
Mehr Informationen
https://click.by.immowelt.de/?qs=OTHER-C
129.000 € 1.075 €/m²
https://click.by.immowelt.de/?qs=OTHER-D
DENKMAL drüber nach!
https://click.by.immowelt.de/?qs=OTHER-E
5 Zimmer . 120 m² . 8.502 m²
https://click.by.immowelt.de/?qs=OTHER-F
Sachsendorf,
Barby
(39240)
{SECOND_TRACKING}
Mehr Informationen
""".strip()


def fake_run(args, **kwargs):

    tracking_url = args[-1]

    if tracking_url == FIRST_TRACKING:

        final_url = (
            "https://www.immowelt.de/expose/"
            "11111111-1111-1111-1111-111111111111"
        )

    elif tracking_url == SECOND_TRACKING:

        final_url = (
            "https://www.immowelt.de/expose/"
            "0121a332-02ba-4a91-a447-dcd8c247080c"
        )

    else:

        raise AssertionError(
            f"Unexpected tracking URL: "
            f"{tracking_url}"
        )

    return subprocess.CompletedProcess(
        args=args,
        returncode=0,
        stdout=final_url,
        stderr="",
    )


class ImmoweltMultiListingTest(
    unittest.TestCase
):

    @patch(
        "monitor.subprocess.run",
        side_effect=fake_run,
    )
    def test_second_listing_is_isolated(
        self,
        _mock_run,
    ):

        properties = parse_immowelt(
            MAIL_TEXT
        )

        by_id = {
            p["portal_id"]: p
            for p in properties
        }

        p = by_id[
            "0121a332-02ba-4a91-a447-dcd8c247080c"
        ]

        self.assertEqual(
            p["title"],
            "DENKMAL drüber nach!",
        )

        self.assertEqual(
            p["location"],
            "Sachsendorf, Barby (39240)",
        )

        self.assertEqual(
            p["price"],
            129000.0,
        )

        self.assertEqual(
            p["rooms"],
            5.0,
        )

        self.assertEqual(
            p["living_area"],
            120.0,
        )

        self.assertEqual(
            p["plot_area"],
            8502.0,
        )

        self.assertNotIn(
            "Kühren",
            p["raw_text"],
        )

        self.assertNotIn(
            "3.636 m²",
            p["raw_text"],
        )


if __name__ == "__main__":
    unittest.main()
