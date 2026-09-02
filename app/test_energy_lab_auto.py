import unittest

from energy_lab_auto import (
    next_energy_action,
)


class EnergyLabAutoAdvanceTests(unittest.TestCase):

    def test_waits_while_current_object_is_still_open(self):

        action, row = next_energy_action(
            "current",
            [
                {"portal_id": "newer"},
                {"portal_id": "current"},
            ],
        )

        self.assertEqual(action, "wait")
        self.assertIsNone(row)

    def test_advances_when_current_object_disappears(self):

        action, row = next_energy_action(
            "current",
            [
                {"portal_id": "next"},
                {"portal_id": "later"},
            ],
        )

        self.assertEqual(action, "advance")
        self.assertEqual(
            row["portal_id"],
            "next",
        )

    def test_finishes_when_queue_is_empty(self):

        action, row = next_energy_action(
            "current",
            [],
        )

        self.assertEqual(action, "done")
        self.assertIsNone(row)


if __name__ == "__main__":
    unittest.main()
