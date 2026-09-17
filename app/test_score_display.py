import json
import unittest

from score_display import completed_score_lines


class ScoreDisplayTest(unittest.TestCase):

    def test_weighted_score_is_shown_below_independent_base_score(self):

        lines = completed_score_lines(
            {
                "score": 59,
                "score_details": json.dumps(
                    {
                        "score": 59,
                        "base_score": 84,
                        "location_weighting_applied": True,
                        "location_reference": "Plötzkau",
                    }
                ),
            }
        )

        self.assertEqual(
            lines,
            [
                "⭐ Gesamtscore ohne Plötzkau: 84/100",
                "📍 Gewichteter Plötzkau-Score: 59/100",
            ],
        )

    def test_unweighted_score_keeps_single_total(self):

        self.assertEqual(
            completed_score_lines(
                {
                    "score": 72,
                    "score_details": {
                        "score": 72,
                        "base_score": 72,
                        "location_weighting_applied": False,
                    },
                }
            ),
            ["⭐ Gesamtscore: 72/100"],
        )

    def test_weighted_view_puts_ploetzkau_score_first(self):

        lines = completed_score_lines(
            {
                "score": 81,
                "base_score": 91,
                "location_weighting_applied": True,
                "location_reference": "Plötzkau",
            },
            weighted_first=True,
        )

        self.assertEqual(
            lines,
            [
                "📍 Gewichteter Plötzkau-Score: 81/100",
                "⭐ Gesamtscore ohne Plötzkau: 91/100",
            ],
        )


if __name__ == "__main__":
    unittest.main()
