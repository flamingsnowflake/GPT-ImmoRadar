import unittest

from browser_condition import (
    extract_explicit_condition,
)
from browser_condition_hints import (
    condition_lab_hints,
    extract_condition_field,
    extract_modernization_hint,
)


class BrowserConditionHintTests(unittest.TestCase):

    def test_composite_condition_uses_real_condition_term(self):

        result = extract_explicit_condition(
            """
            Zustand der Immobilie
            Massivhaus, renovierungsbedürftig
            / sanierungsbedürftig
            Energieträger
            Elektro
            """
        )

        self.assertIsNotNone(result)
        self.assertEqual(
            result["condition_class"],
            "renovation_needed",
        )
        self.assertEqual(
            result["condition_reason"],
            "sanierungsbedürftig",
        )
        self.assertIn(
            "Massivhaus",
            result["condition_portal_value"],
        )

    def test_massivhaus_alone_stays_unknown_but_is_visible(self):

        result = extract_explicit_condition(
            "Zustand der Immobilie\nMassivhaus"
        )

        self.assertIsNone(result)

        hints = condition_lab_hints(
            "Zustand der Immobilie\nMassivhaus"
        )

        self.assertEqual(
            hints["portal_condition"],
            "Massivhaus",
        )

    def test_abrissobjekt_is_dilapidated(self):

        result = extract_explicit_condition(
            "Zustand der Immobilie\nAbrissobjekt"
        )

        self.assertIsNotNone(result)
        self.assertEqual(
            result["condition_class"],
            "dilapidated",
        )

    def test_gepflegt_is_maintained(self):

        result = extract_explicit_condition(
            "Zustand der Immobilie\nGepflegt"
        )

        self.assertIsNotNone(result)
        self.assertEqual(
            result["condition_class"],
            "maintained",
        )

    def test_saniert_is_good(self):

        result = extract_explicit_condition(
            "Objektzustand:\nSaniert"
        )

        self.assertIsNotNone(result)
        self.assertEqual(
            result["condition_class"],
            "good",
        )

    def test_split_modernization_label(self):

        value = extract_modernization_hint(
            """
            Baujahr:
            1953
            Modernisierung/
            Sanierung:
            zuletzt 2025
            Objektzustand:
            Renovierungsbedürftig
            """
        )

        self.assertEqual(
            value,
            "zuletzt 2025",
        )

    def test_modernization_is_hint_only(self):

        result = extract_explicit_condition(
            """
            Modernisierung/Sanierung:
            zuletzt 2020
            """
        )

        self.assertIsNone(result)

    def test_condition_field_keeps_portal_wording(self):

        field = extract_condition_field(
            """
            Zustand der Immobilie
            Massivhaus, renovierungsbedürftig
            / sanierungsbedürftig
            """
        )

        self.assertEqual(
            field["value"],
            "Massivhaus, renovierungsbedürftig / sanierungsbedürftig",
        )


if __name__ == "__main__":
    unittest.main()
