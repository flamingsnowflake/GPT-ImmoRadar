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

    def test_find_result_has_direct_property_button(self):
        with patch.object(telegram_commands, "DB_PATH", self.db):
            text, keyboard = telegram_commands.find_properties("gusborn", with_keyboard=True)

        self.assertIn("Charmantes EFH", text)
        self.assertIn("Klein Gusborn", text)
        button = keyboard["inline_keyboard"][0][0]
        self.assertEqual(button["text"], "🏠 Details 1")
        self.assertEqual(
            button["callback_data"],
            "property:6a16384f-a717-4ab4-ad30-c53c3b991251:house:find",
        )
        self.assertLessEqual(len(button["callback_data"].encode()), 64)

    def test_empty_search_has_no_keyboard(self):
        text, keyboard = telegram_commands.find_properties("", with_keyboard=True)
        self.assertIn("Verwendung", text)
        self.assertIsNone(keyboard)


if __name__ == "__main__":
    unittest.main()
