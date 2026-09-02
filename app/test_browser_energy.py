import unittest

from browser_energy import (
    energy_payload_from_browser,
    extract_energy_data,
)


class BrowserEnergyTests(unittest.TestCase):

    def test_extracts_energy_class(self):

        data = extract_energy_data(
            """
            Bausubstanz & Energieausweis
            Energieeffizienzklasse: E
            Heizungsart: Zentralheizung
            Wesentliche Energieträger: Gas
            Beschreibung
            """
        )

        self.assertEqual(
            data["energy_class"],
            "E",
        )
        self.assertEqual(
            data["energy_certificate_status"],
            "available",
        )

    def test_missing_energy_becomes_checked_unknown(self):

        result = energy_payload_from_browser(
            {
                "property_type": "house",
                "energy_updated_at": None,
                "energy_certificate_status": None,
            },
            "Schönes Haus mit großem Garten.",
        )

        self.assertIsNotNone(result)
        self.assertEqual(
            result["energy_certificate_status"],
            "unknown",
        )
        self.assertEqual(
            result["energy_data_source"],
            "browser_text_checked_no_energy",
        )

    def test_final_manual_energy_is_not_overwritten(self):

        result = energy_payload_from_browser(
            {
                "property_type": "house",
                "energy_updated_at": "2026-08-31T10:00:00+00:00",
                "energy_certificate_status": "available",
                "energy_data_source": "telegram_manual",
            },
            "Energieeffizienzklasse: H",
        )

        self.assertIsNone(result)

    def test_pending_without_new_decisive_data_stays_pending(self):

        result = energy_payload_from_browser(
            {
                "property_type": "house",
                "energy_updated_at": "2026-08-31T10:00:00+00:00",
                "energy_certificate_status": "not_available_yet",
            },
            "Heizungsart: Zentralheizung\nEnergieträger: Gas",
        )

        self.assertIsNone(result)

    def test_pending_can_be_replaced_by_real_energy_data(self):

        result = energy_payload_from_browser(
            {
                "property_type": "house",
                "energy_updated_at": "2026-08-31T10:00:00+00:00",
                "energy_certificate_status": "not_available_yet",
            },
            "Energieeffizienzklasse: B",
        )

        self.assertIsNotNone(result)
        self.assertEqual(
            result["energy_class"],
            "B",
        )
        self.assertEqual(
            result["energy_certificate_status"],
            "available",
        )

    def test_auto_unknown_can_be_upgraded_later(self):

        result = energy_payload_from_browser(
            {
                "property_type": "house",
                "energy_updated_at": "2026-08-31T10:00:00+00:00",
                "energy_certificate_status": "unknown",
                "energy_data_source": "browser_text_checked_no_energy",
            },
            "Energieeffizienzklasse: C",
        )

        self.assertIsNotNone(result)
        self.assertEqual(
            result["energy_class"],
            "C",
        )

    def test_auto_unknown_stays_unchanged_without_better_data(self):

        result = energy_payload_from_browser(
            {
                "property_type": "house",
                "energy_updated_at": "2026-08-31T10:00:00+00:00",
                "energy_certificate_status": "unknown",
                "energy_data_source": "browser_text_checked_no_energy",
            },
            "Schönes Haus mit großem Garten.",
        )

        self.assertIsNone(result)

    def test_land_is_ignored(self):

        result = energy_payload_from_browser(
            {
                "property_type": "land",
                "energy_updated_at": None,
                "energy_certificate_status": None,
            },
            "Energieeffizienzklasse: A",
        )

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
