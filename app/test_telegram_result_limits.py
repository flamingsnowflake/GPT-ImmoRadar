import unittest
from unittest.mock import patch

import telegram_commands


def property_rows(count):
    return [
        {
            "portal_id": f"property-{number:02d}",
            "property_type": "house",
            "title": f"Haus {number:02d}",
        }
        for number in range(1, count + 1)
    ]


class TelegramResultLimitTest(unittest.TestCase):
    def test_favorites_send_at_most_ten_property_cards(self):
        with patch.object(telegram_commands, "TELEGRAM_CHAT_ID", "test"), \
             patch.object(telegram_commands, "get_favorite_rows", return_value=property_rows(12)), \
             patch.object(telegram_commands, "format_property_card", side_effect=lambda p, n: p["portal_id"]), \
             patch.object(telegram_commands, "property_action_keyboard", return_value={"inline_keyboard": []}), \
             patch.object(telegram_commands, "send_message") as send:
            telegram_commands.handle_message(
                {"chat": {"id": "test"}, "text": "/merkliste"}
            )

        self.assertEqual(send.call_count, 11)
        self.assertIn("10 von 12 angezeigt", send.call_args_list[0].args[0])
        sent_cards = [call.args[0] for call in send.call_args_list[1:]]
        self.assertEqual(sent_cards, [f"property-{number:02d}" for number in range(1, 11)])

    def test_dog_tax_selection_lists_at_most_ten_tasks(self):
        tasks = [
            {
                "kind": "municipality",
                "property": {
                    "portal_id": f"tax-{number:02d}",
                    "location": f"Ort {number:02d}",
                },
            }
            for number in range(1, 13)
        ]

        with patch.object(telegram_commands, "TELEGRAM_CHAT_ID", "test"), \
             patch.object(telegram_commands, "dog_tax_research_queue", return_value=tasks), \
             patch.object(telegram_commands, "get_top_property_rows", return_value=[]), \
             patch.object(telegram_commands, "get_favorite_rows", return_value=[]), \
             patch.object(telegram_commands, "send_message") as send:
            telegram_commands.handle_message(
                {"chat": {"id": "test"}, "text": "/hundesteuer"}
            )

        send.assert_called_once()
        text, keyboard = send.call_args.args
        self.assertIn("10 von 12 angezeigt", text)
        self.assertEqual(len(keyboard["inline_keyboard"]), 10)
        self.assertNotIn("Ort 11", text)

    def test_waitlist_with_more_than_ten_rows_renders_one_item(self):
        rows = property_rows(12)
        keyboard = {"inline_keyboard": []}

        with patch.object(telegram_commands, "TELEGRAM_CHAT_ID", "test"), \
             patch.object(telegram_commands, "_lab_rows", return_value=rows), \
             patch.object(telegram_commands, "set_active_condition_lab"), \
             patch.object(telegram_commands.LOCALITY_LAB, "track"), \
             patch.object(telegram_commands, "incomplete_condition_text", return_value="condition-card") as render, \
             patch.object(telegram_commands, "incomplete_condition_keyboard", return_value=keyboard), \
             patch.object(telegram_commands, "telegram_api") as api:
            telegram_commands._render_lab_queue(
                {"message_id": 42},
                "condition",
                True,
                "",
            )

        render.assert_called_once_with(rows[0], 1, 12, waiting=True)
        api.assert_called_once()
        self.assertEqual(api.call_args.args[1]["text"], "condition-card")


if __name__ == "__main__":
    unittest.main()
