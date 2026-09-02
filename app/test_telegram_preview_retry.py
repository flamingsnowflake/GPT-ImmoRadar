import unittest

from telegram_preview import (
    _is_generic_immowelt_preview,
)


class TelegramPreviewRetryTest(unittest.TestCase):

    def test_generic_immowelt_title_retries(self):

        self.assertTrue(
            _is_generic_immowelt_preview(
                "https://www.immowelt.de/expose/test",
                "Immowelt",
                (
                    "Haus 150.69 m² 87900 € zum Kauf "
                    "Klostermansfeld (06308)"
                ),
                None,
            )
        )

    def test_final_auction_title_is_usable(self):

        self.assertFalse(
            _is_generic_immowelt_preview(
                "https://www.immowelt.de/expose/test",
                "Immowelt",
                (
                    "Haus 150.69 m² 87900 € "
                    "Zwangsversteigerungen "
                    "Klostermansfeld (06308)"
                ),
                None,
            )
        )

    def test_description_makes_preview_usable(self):

        self.assertFalse(
            _is_generic_immowelt_preview(
                "https://www.immowelt.de/expose/test",
                "Immowelt",
                "Haus 87900 € zum Kauf Klostermansfeld",
                "Zwangsversteigerung beim Amtsgericht",
            )
        )

    def test_non_immowelt_not_affected(self):

        self.assertFalse(
            _is_generic_immowelt_preview(
                "https://www.immobilienscout24.de/expose/123",
                "ImmobilienScout24",
                "Haus 87900 € zum Kauf Klostermansfeld",
                None,
            )
        )


if __name__ == "__main__":
    unittest.main()
