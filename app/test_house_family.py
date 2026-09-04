import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("IMAP_HOST", "test")
os.environ.setdefault("IMAP_USER", "test")
os.environ.setdefault("IMAP_PASSWORD", "test")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ.setdefault("TELEGRAM_CHAT_ID", "1")

import monitor
import telegram_commands
from property_types import (
    is_house_type,
    property_type_label,
)
from telegram_ui import property_action_keyboard


class HouseFamilyTest(unittest.TestCase):

    def test_house_and_farm_are_house_types(self):
        self.assertTrue(is_house_type("house"))
        self.assertTrue(is_house_type("farm"))
        self.assertFalse(is_house_type("land"))
        self.assertFalse(is_house_type("unknown"))
        self.assertFalse(is_house_type(None))

    def test_property_type_labels(self):
        self.assertEqual(
            property_type_label("farm"),
            "Hof",
        )
        self.assertEqual(
            property_type_label("house"),
            "Haus",
        )
        self.assertEqual(
            property_type_label("land"),
            "Grundstück",
        )

    def test_coordinate_button_preserves_property_context(self):
        keyboard = property_action_keyboard(
            "2593e8ff-d559-4c8d-ae86-7e8523c1138b",
            "house",
            "new",
        )

        first_button = (
            keyboard["inline_keyboard"]
            [0][0]
        )

        self.assertEqual(
            first_button["text"],
            "📍 Koordinaten",
        )

        self.assertEqual(
            first_button["callback_data"],
            "coords:"
            "2593e8ff-d559-4c8d-ae86-7e8523c1138b:"
            "house:new",
        )

        self.assertLessEqual(
            len(
                first_button["callback_data"]
                .encode("utf-8")
            ),
            64,
        )

    def test_property_keyboard_defaults_to_new_context(self):
        keyboard = property_action_keyboard(
            "170210314",
            "house",
        )

        callback_data = [
            button["callback_data"]
            for row in keyboard["inline_keyboard"]
            for button in row
        ]

        self.assertIn(
            "property:170210314:house:new",
            callback_data,
        )
        self.assertIn(
            "inspect:170210314:house:new",
            callback_data,
        )

    def test_farm_gets_condition_button(self):
        keyboard = property_action_keyboard(
            "170214291",
            "farm",
            "new",
        )

        button_texts = [
            button["text"]
            for row in keyboard["inline_keyboard"]
            for button in row
        ]

        self.assertIn(
            "🔧 Zustand",
            button_texts,
        )

    def test_land_has_no_condition_button(self):
        keyboard = property_action_keyboard(
            "land-id",
            "land",
            "new",
        )

        button_texts = [
            button["text"]
            for row in keyboard["inline_keyboard"]
            for button in row
        ]

        self.assertNotIn(
            "🔧 Zustand",
            button_texts,
        )

    def test_land_details_have_buildability_buttons(self):
        keyboard = telegram_commands.property_details_keyboard(
            "land-id",
            "land",
            "new",
        )

        button_texts = [
            button["text"]
            for row in keyboard["inline_keyboard"]
            for button in row
        ]

        self.assertIn(
            "🏗 Bebauungsplan",
            button_texts,
        )

    def test_house_details_have_no_buildability_buttons(self):
        for property_type in ("house", "farm"):
            with self.subTest(property_type=property_type):
                keyboard = telegram_commands.property_details_keyboard(
                    "house-id",
                    property_type,
                    "new",
                )

                button_texts = [
                    button["text"]
                    for row in keyboard["inline_keyboard"]
                    for button in row
                ]

                self.assertNotIn(
                    "🏗 Bebauungsplan",
                    button_texts,
                )
                self.assertNotIn(
                    "🏘 §34 Nachbarn",
                    button_texts,
                )
                self.assertNotIn(
                    "⛔ §35 Außenbereich",
                    button_texts,
                )

    def test_condition_keyboard_defaults_to_new_context(self):
        keyboard = telegram_commands.condition_keyboard(
            "170214291",
            "farm",
        )

        callback_data = [
            button["callback_data"]
            for row in keyboard["inline_keyboard"]
            for button in row
        ]

        self.assertIn(
            "c:170214291:r:new",
            callback_data,
        )
        self.assertIn(
            "back:170214291:farm:new",
            callback_data,
        )

    @patch("monitor.save_property")
    @patch("monitor.score_house")
    @patch("monitor.enrich_property")
    @patch("monitor.classify_house_condition")
    @patch("monitor.detect_property_type")
    def test_farm_uses_house_condition_and_score(
        self,
        detect_property_type,
        classify_house_condition,
        enrich_property,
        score_house,
        save_property,
    ):
        detect_property_type.return_value = "farm"

        classify_house_condition.return_value = {
            "condition_class": "renovation_needed",
            "condition_reason": "test",
            "condition_source": "title",
        }

        enrich_property.side_effect = (
            lambda conn, property_data: property_data
        )

        score_house.return_value = {
            "score": 85,
            "rating": "very_interesting",
            "ko": False,
            "reasons": [],
            "ko_reasons": [],
        }

        save_property.return_value = (
            False,
            218,
        )

        from unittest.mock import MagicMock
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = None
        result = monitor.process_property(
            conn,
            {
                "portal": "immoscout24",
                "portal_id": "170214291",
                "title": "DENKMAL drüber nach!",
            },
            apply_filters=False,
        )

        classify_house_condition.assert_called_once()
        score_house.assert_called()
        self.assertTrue(all(call.args[0]['property_type'] == 'farm' for call in score_house.call_args_list))

        self.assertEqual(
            result["property_data"]["property_type"],
            "farm",
        )

        self.assertEqual(
            result["property_data"]["condition_class"],
            "renovation_needed",
        )

        self.assertEqual(
            result["property_data"]["score"],
            85,
        )

    def test_top_house_rows_include_farms(self):
        with tempfile.NamedTemporaryFile(delete_on_close=False) as tmp:
            conn = sqlite3.connect(tmp.name)

            conn.execute(
                """
                CREATE TABLE properties (
                    portal_id TEXT,
                    property_type TEXT,
                    title TEXT,
                    location TEXT,
                    price REAL,
                    plot_area REAL,
                    buildings_100m INTEGER,
                    is_ko INTEGER,
                    score INTEGER,
                    latitude REAL,
                    longitude REAL,
                    water_score INTEGER,
                    neighbour_class TEXT
                )
                """
            )

            rows = [
                (
                    "house-1",
                    "house",
                    "Haus",
                    "Ort",
                    100000,
                    1000,
                    5,
                    0,
                    80,
                    51.0,
                    11.0,
                    15,
                    "loose_development",
                ),
                (
                    "farm-1",
                    "farm",
                    "Hof",
                    "Ort",
                    120000,
                    8000,
                    5,
                    0,
                    85,
                    51.0,
                    11.0,
                    16,
                    "loose_development",
                ),
                (
                    "land-1",
                    "land",
                    "Grundstück",
                    "Ort",
                    30000,
                    1500,
                    2,
                    0,
                    90,
                    51.0,
                    11.0,
                    18,
                    "isolated",
                ),
            ]

            conn.executemany(
                """
                INSERT INTO properties VALUES (
                    ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?
                )
                """,
                rows,
            )

            conn.execute("ALTER TABLE properties ADD COLUMN rating TEXT DEFAULT 'interesting'")
            conn.execute('ALTER TABLE properties ADD COLUMN score_details TEXT')
            conn.execute('ALTER TABLE properties ADD COLUMN id INTEGER')
            conn.commit()
            conn.close()

            with patch.object(
                telegram_commands,
                "DB_PATH",
                tmp.name,
            ), patch.object(
                telegram_commands.CONFIG,
                "blacklist_terms",
                return_value=[],
            ):
                house_rows = (
                    telegram_commands
                    .get_top_property_rows(
                        "house",
                        3,
                    )
                )

                land_rows = (
                    telegram_commands
                    .get_top_property_rows(
                        "land",
                        3,
                    )
                )

            self.assertEqual(
                {row["portal_id"] for row in house_rows},
                {"house-1", "farm-1"},
            )

            self.assertEqual(
                {row["portal_id"] for row in land_rows},
                {"land-1"},
            )



if __name__ == "__main__":
    unittest.main()
