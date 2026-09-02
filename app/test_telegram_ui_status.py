import unittest

from telegram_ui import (
    property_action_keyboard,
)


class TelegramUiStatusTest(unittest.TestCase):

    def _labels(self, status):

        keyboard = property_action_keyboard(
            "ABC",
            "house",
            "new",
            favorite=False,
            user_status=status,
        )

        return [
            button["text"]
            for row in keyboard[
                "inline_keyboard"
            ]
            for button in row
        ]

    def test_active_has_both_actions(self):

        labels = self._labels(
            "active"
        )

        self.assertIn(
            "⛔ Offline",
            labels,
        )

        self.assertIn(
            "🙈 Kein Interesse",
            labels,
        )

    def test_offline_has_restore_button(self):

        labels = self._labels(
            "offline"
        )

        self.assertIn(
            "↩️ Wieder online",
            labels,
        )

        self.assertNotIn(
            "🙈 Kein Interesse",
            labels,
        )

    def test_not_interested_has_restore_button(self):

        labels = self._labels(
            "not_interested"
        )

        self.assertIn(
            "↩️ Wieder interessant",
            labels,
        )

        self.assertNotIn(
            "⛔ Offline",
            labels,
        )


if __name__ == "__main__":
    unittest.main()
