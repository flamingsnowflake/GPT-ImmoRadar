import unittest

from analyze_condition_backlog import analyze_row


COLUMNS = {
    "portal_id",
    "title",
    "location",
    "condition",
    "raw_text",
    "browser_text",
    "description",
}


class AnalyzeConditionBacklogTest(unittest.TestCase):

    def _row(self, text="", **overrides):

        row = {
            "portal_id": "X1",
            "title": "Testhaus",
            "location": "Testort",
            "condition": None,
            "raw_text": text,
            "browser_text": None,
            "description": None,
        }

        row.update(overrides)
        return row

    def test_clear_renovation_phrase_is_high(self):

        result = analyze_row(
            self._row(
                "Das Gebäude befindet sich in "
                "renovierungsbedürftigem Zustand."
            ),
            COLUMNS,
        )

        self.assertEqual(
            result["status"],
            "high",
        )
        self.assertEqual(
            result["candidate"],
            "renovation_needed",
        )

    def test_clear_good_phrase_is_high(self):

        result = analyze_row(
            self._row(
                "Die Immobilie befindet sich in "
                "sehr gutem Zustand."
            ),
            COLUMNS,
        )

        self.assertEqual(
            result["status"],
            "high",
        )
        self.assertEqual(
            result["candidate"],
            "good",
        )

    def test_historical_renovation_is_not_high(self):

        result = analyze_row(
            self._row(
                "Das Haus wurde 1998 vollständig saniert."
            ),
            COLUMNS,
        )

        self.assertNotEqual(
            result["status"],
            "high",
        )

    def test_negated_phrase_is_not_high(self):

        result = analyze_row(
            self._row(
                "Das Haus ist nicht bezugsfertig und "
                "benötigt weitere Arbeiten."
            ),
            COLUMNS,
        )

        self.assertNotEqual(
            result["status"],
            "high",
        )

    def test_empty_text_is_no_text(self):

        result = analyze_row(
            self._row(
                "",
                title="",
                location="Testort",
            ),
            COLUMNS,
        )

        self.assertEqual(
            result["status"],
            "no_text",
        )


if __name__ == "__main__":
    unittest.main()
