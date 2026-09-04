import unittest

from scoring import (
    energy_class_from_value,
    energy_score_adjustment,
)


ENERGY_CONFIG = {
    "class_adjustments": {
        "A+": 5,
        "A": 4,
        "B": 3,
        "C": 2,
        "D": 0,
        "E": -2,
        "F": -5,
        "G": -9,
        "H": -14,
    }
}


class EnergyScoringTest(unittest.TestCase):

    def test_value_to_class_boundaries(self):
        self.assertEqual(
            energy_class_from_value(27.7),
            "A+",
        )
        self.assertEqual(
            energy_class_from_value(30),
            "A",
        )
        self.assertEqual(
            energy_class_from_value(200),
            "G",
        )
        self.assertEqual(
            energy_class_from_value(250),
            "G",
        )
        self.assertEqual(
            energy_class_from_value(255.9),
            "H",
        )

    def test_a_plus_bonus(self):
        adjustment, reason = (
            energy_score_adjustment(
                {
                    "energy_certificate_status": "available",
                    "energy_class": "A+",
                    "energy_value_kwh": 27.7,
                    "energy_certificate_type": "consumption",
                },
                ENERGY_CONFIG,
            )
        )

        self.assertEqual(adjustment, 5)
        self.assertIn("A+", reason)
        self.assertIn("27,7", reason)
        self.assertIn("Verbrauch", reason)

    def test_h_penalty(self):
        adjustment, reason = (
            energy_score_adjustment(
                {
                    "energy_certificate_status": "available",
                    "energy_class": "H",
                    "energy_value_kwh": 255.9,
                    "energy_certificate_type": "demand",
                },
                ENERGY_CONFIG,
            )
        )

        self.assertEqual(adjustment, -14)
        self.assertIn("H", reason)
        self.assertIn("Bedarf", reason)

    def test_not_required_keeps_uncertainty_penalty(self):
        adjustment, reason = (
            energy_score_adjustment(
                {
                    "energy_certificate_status": "not_required",
                },
                ENERGY_CONFIG,
            )
        )

        self.assertEqual(adjustment, -7)
        self.assertEqual(
            reason,
            "Ausweis nicht erforderlich | Risiko -7",
        )

    def test_unknown_keeps_uncertainty_penalty(self):
        adjustment, reason = (
            energy_score_adjustment(
                {},
                ENERGY_CONFIG,
            )
        )

        self.assertEqual(adjustment, -7)
        self.assertEqual(reason, "Energie unbekannt | Risiko -7")

    def test_inconsistent_data_uses_worse_class(self):
        adjustment, reason = (
            energy_score_adjustment(
                {
                    "energy_certificate_status": "available",
                    "energy_class": "A+",
                    "energy_value_kwh": 255.9,
                },
                ENERGY_CONFIG,
            )
        )

        self.assertEqual(adjustment, -14)
        self.assertIn(
            "konservativ schlechtere Klasse",
            reason,
        )


if __name__ == "__main__":
    unittest.main()
