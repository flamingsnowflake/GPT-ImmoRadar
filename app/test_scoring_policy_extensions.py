import unittest

from scoring import (
    _ohne_makler_price_effect,
    energy_score_adjustment,
)


class ScoringPolicyExtensionsTest(unittest.TestCase):

    def test_ohne_makler_gets_at_least_three_points(self):

        price_config = {
            "brackets": [
                {
                    "max": 200000,
                    "points": 20,
                },
                {
                    "max": None,
                    "points": 10,
                },
            ]
        }

        result = _ohne_makler_price_effect(
            {
                "portal": "ohne-makler",
                "url": "https://www.ohne-makler.net/immobilie/123/",
            },
            150000,
            price_config,
        )

        self.assertTrue(
            result["applies"]
        )
        self.assertEqual(
            result["bonus_points"],
            3,
        )
        self.assertAlmostEqual(
            result["discounted_purchase_price"],
            145500.0,
        )

    def test_ohne_makler_can_gain_more_if_three_percent_crosses_bracket(self):

        price_config = {
            "brackets": [
                {
                    "max": 160000,
                    "points": 22,
                },
                {
                    "max": 190000,
                    "points": 19,
                },
                {
                    "max": None,
                    "points": 0,
                },
            ]
        }

        result = _ohne_makler_price_effect(
            {
                "url": "https://www.ohne-makler.net/immobilie/123/",
            },
            164000,
            price_config,
        )

        self.assertEqual(
            result["bracket_gain"],
            3,
        )
        self.assertEqual(
            result["bonus_points"],
            3,
        )

    def test_other_portal_gets_no_bonus(self):

        price_config = {
            "brackets": [
                {
                    "max": None,
                    "points": 10,
                },
            ]
        }

        result = _ohne_makler_price_effect(
            {
                "portal": "immowelt",
                "url": "https://www.immowelt.de/expose/example",
            },
            150000,
            price_config,
        )

        self.assertFalse(
            result["applies"]
        )
        self.assertEqual(
            result["bonus_points"],
            0,
        )

    def test_no_label_uses_h_penalty(self):

        adjustment, reason = energy_score_adjustment(
            {
                "energy_certificate_status": "no_label",
            },
            {
                "class_adjustments": {
                    "A": 2,
                    "H": -8,
                }
            },
        )

        self.assertEqual(
            adjustment,
            -8,
        )
        self.assertIn(
            "wie H",
            reason,
        )

    def test_unknown_energy_gets_uncertainty_penalty(self):

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
            "-7",
            reason,
        )

    def test_not_required_gets_uncertainty_penalty(self):

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
            "-7",
            reason,
        )

    def test_not_available_yet_remains_neutral(self):

        adjustment, reason = energy_score_adjustment(
            {
                "energy_certificate_status": "not_available_yet",
            },
            {
                "class_adjustments": {
                    "H": -8,
                }
            },
        )

        self.assertEqual(
            adjustment,
            0,
        )
        self.assertIn(
            "noch nicht verfügbar",
            reason,
        )


if __name__ == "__main__":
    unittest.main()
