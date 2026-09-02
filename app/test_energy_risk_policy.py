import unittest

from scoring import (
    energy_score_adjustment,
    score_house,
)


class EnergyRiskPolicyTest(unittest.TestCase):

    def test_unknown_energy_is_minus_seven(self):

        adjustment, reason = energy_score_adjustment(
            {
                "energy_certificate_status": "unknown",
            },
            {
                "class_adjustments": {
                    "H": -8,
                }
            },
        )

        self.assertEqual(
            adjustment,
            -7,
        )
        self.assertIn(
            "Risiko -7",
            reason,
        )

    def test_not_required_is_minus_seven(self):

        adjustment, reason = energy_score_adjustment(
            {
                "energy_certificate_status": "not_required",
            },
            {
                "class_adjustments": {
                    "H": -8,
                }
            },
        )

        self.assertEqual(
            adjustment,
            -7,
        )
        self.assertIn(
            "Risiko -7",
            reason,
        )

    def test_not_available_yet_stays_incomplete(self):

        result = score_house(
            {
                "price": 120000,
                "plot_area": 1200,
                "living_area": 120,
                "condition_class": "good",
                "neighbour_checked_at": "2026-08-31T10:00:00Z",
                "neighbour_class": "few_neighbours",
                "noise_checked_at": "2026-08-31T10:00:00Z",
                "water_score": 10,
                "energy_updated_at": "2026-08-31T10:00:00Z",
                "energy_certificate_status": "not_available_yet",
            }
        )

        self.assertIsNone(
            result["score"]
        )
        self.assertEqual(
            result["rating"],
            "incomplete",
        )
        self.assertIn(
            "Energie",
            result[
                "incomplete_reasons"
            ],
        )


if __name__ == "__main__":
    unittest.main()
