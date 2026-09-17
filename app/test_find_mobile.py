import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import telegram_commands


class FindMobileTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = str(Path(self.directory.name) / "find.sqlite3")
        conn = sqlite3.connect(self.db)
        try:
            conn.execute(
                """CREATE TABLE properties (
                    portal TEXT, portal_id TEXT, property_type TEXT,
                    title TEXT, location TEXT, price REAL, plot_area REAL,
                    score INTEGER, rating TEXT, is_ko INTEGER,
                    score_details TEXT, url TEXT, last_seen TEXT
                )"""
            )
            conn.execute(
                "INSERT INTO properties VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("test", "6a16384f-a717-4ab4-ad30-c53c3b991251", "house",
                 "Charmantes EFH", "Klein Gusborn, Gusborn (29476)", 210000,
                 1600, 78, "interessant", 0, "{}", "https://example.invalid", "2026-09-04"),
            )
            conn.commit()
        finally:
            conn.close()

    def test_find_result_opens_property_card_before_details(self):
        with patch.object(telegram_commands, "DB_PATH", self.db):
            text, keyboard = telegram_commands.find_properties("gusborn", with_keyboard=True)

        self.assertIn("Charmantes EFH", text)
        self.assertIn("Klein Gusborn", text)
        button = keyboard["inline_keyboard"][0][0]
        self.assertEqual(button["text"], "➡️ Treffer 1")
        self.assertEqual(
            button["callback_data"],
            "back:6a16384f-a717-4ab4-ad30-c53c3b991251:house:new",
        )
        self.assertLessEqual(len(button["callback_data"].encode()), 64)

        callback = {
            "id": "callback",
            "data": button["callback_data"],
            "message": {
                "message_id": 123,
                "chat": {"id": "test"},
            },
        }
        main_keyboard = {"inline_keyboard": [[{"text": "📍 Koordinaten"}]]}

        with patch.object(telegram_commands, "DB_PATH", self.db), \
             patch.object(telegram_commands, "TELEGRAM_CHAT_ID", "test"), \
             patch.object(telegram_commands, "format_property_card", return_value="card"), \
             patch.object(telegram_commands, "property_action_keyboard", return_value=main_keyboard) as actions, \
             patch.object(telegram_commands, "telegram_api") as api:
            telegram_commands.handle_callback(callback)

        actions.assert_called_once_with(
            "6a16384f-a717-4ab4-ad30-c53c3b991251",
            "house",
            "new",
        )
        edit = next(
            call for call in api.call_args_list
            if call.args[0] == "editMessageText"
        )
        self.assertEqual(edit.args[1]["text"], "card")
        self.assertEqual(
            edit.args[1]["reply_markup"],
            telegram_commands.json.dumps(
                main_keyboard
            ),
        )

    def test_empty_search_has_no_keyboard(self):
        text, keyboard = telegram_commands.find_properties("", with_keyboard=True)
        self.assertIn("Verwendung", text)
        self.assertIsNone(keyboard)

    def test_search_caps_long_result_at_ten_after_sorting(self):
        conn = sqlite3.connect(self.db)
        try:
            conn.executemany(
                "INSERT INTO properties VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        "test",
                        f"bulk-{number:02d}",
                        "house",
                        f"Bulk Haus {number:02d}",
                        "Bulkhausen",
                        100000 + number,
                        2000,
                        number,
                        "interesting",
                        0,
                        "{}",
                        "https://example.invalid",
                        f"2026-09-{number:02d}",
                    )
                    for number in range(1, 13)
                ],
            )
            conn.commit()
        finally:
            conn.close()

        with patch.object(telegram_commands, "DB_PATH", self.db):
            text, keyboard = telegram_commands.find_properties(
                "bulk",
                with_keyboard=True,
            )

        self.assertIn("10 von 12 angezeigt", text)
        self.assertEqual(len(keyboard["inline_keyboard"]), 10)
        self.assertIn("Bulk Haus 12", text)
        self.assertNotIn("Bulk Haus 02", text)


if __name__ == "__main__":
    unittest.main()
