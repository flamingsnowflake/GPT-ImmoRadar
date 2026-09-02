import unittest

from browser_energy import (
    energy_payload_from_browser,
    extract_energy_data,
)


class BrowserEnergyDomTests(unittest.TestCase):

    def test_dom_energy_class_is_used_when_text_has_none(self):

        data = extract_energy_data(
            "Schönes Haus mit großem Garten.",
            energy_class_hint="E",
        )

        self.assertEqual(
            data["energy_class"],
            "E",
        )

        self.assertEqual(
            data["energy_certificate_status"],
            "available",
        )

    def test_dom_hint_completes_unchecked_house(self):

        data = energy_payload_from_browser(
            {
                "property_type": "house",
                "energy_updated_at": None,
                "energy_certificate_status": None,
            },
            "Keine ausgeschriebene Energieklasse im Seitentext.",
            energy_class_hint="B",
        )

        self.assertIsNotNone(data)

        self.assertEqual(
            data["energy_class"],
            "B",
        )

        self.assertEqual(
            data["energy_certificate_status"],
            "available",
        )

    def test_invalid_dom_hint_is_ignored(self):

        data = extract_energy_data(
            "Keine Energiedaten.",
            energy_class_hint="XYZ",
        )

        self.assertIsNone(
            data["energy_class"]
        )


if __name__ == "__main__":
    unittest.main()
