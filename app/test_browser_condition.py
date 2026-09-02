import unittest

from browser_condition import (
    condition_payload_from_browser,
    extract_explicit_condition,
)


class BrowserConditionTests(unittest.TestCase):

    def test_immowelt_maintained_field(self):

        result = extract_explicit_condition(
            """
            Bausubstanz und Energie
            Zustand der Immobilie
            gepflegt
            Energieträger
            Öl
            """
        )

        self.assertIsNotNone(result)
        self.assertEqual(
            result["condition_class"],
            "maintained",
        )
        self.assertEqual(
            result["condition_reason"],
            "gepflegt",
        )
        self.assertEqual(
            result["condition_source"],
            "browser_explicit",
        )

    def test_inline_condition_field(self):

        result = extract_explicit_condition(
            "Objektzustand: renovierungsbedürftig"
        )

        self.assertIsNotNone(result)
        self.assertEqual(
            result["condition_class"],
            "renovation_needed",
        )

    def test_free_description_is_not_used_as_explicit_field(self):

        result = extract_explicit_condition(
            "Das Haus wurde stets gepflegt und bietet viel Platz."
        )

        self.assertIsNone(result)

    def test_manual_condition_is_protected(self):

        result = condition_payload_from_browser(
            {
                "property_type": "house",
                "condition_class": "good",
                "condition_source": "telegram",
            },
            "Zustand der Immobilie\ngepflegt",
        )

        self.assertIsNone(result)

    def test_unknown_condition_is_filled(self):

        result = condition_payload_from_browser(
            {
                "property_type": "house",
                "condition_class": "unknown",
                "condition_source": None,
            },
            "Zustand der Immobilie\ngepflegt",
        )

        self.assertIsNotNone(result)
        self.assertEqual(
            result["condition_class"],
            "maintained",
        )

    def test_existing_auto_condition_is_not_overwritten(self):

        result = condition_payload_from_browser(
            {
                "property_type": "house",
                "condition_class": "renovation_needed",
                "condition_source": "raw_text",
            },
            "Zustand der Immobilie\ngepflegt",
        )

        self.assertIsNone(result)

    def test_land_is_ignored(self):

        result = condition_payload_from_browser(
            {
                "property_type": "land",
                "condition_class": "unknown",
                "condition_source": None,
            },
            "Zustand der Immobilie\ngepflegt",
        )

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
