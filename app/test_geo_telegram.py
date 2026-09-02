import json
import os
import sqlite3
import sys
import tempfile
import types
import unittest

from config_loader import CONFIG


_BOOTSTRAP_DB = tempfile.NamedTemporaryFile(
    suffix=".sqlite3",
    delete=False,
)
_BOOTSTRAP_DB.close()

_bootstrap_conn = sqlite3.connect(
    _BOOTSTRAP_DB.name
)
_bootstrap_conn.execute(
    """
    CREATE TABLE properties (
        id INTEGER PRIMARY KEY,
        portal_id TEXT,
        score INTEGER,
        rating TEXT,
        is_ko INTEGER,
        score_details TEXT
    )
    """
)
_bootstrap_conn.commit()
_bootstrap_conn.close()

_MONITOR_STUB = types.ModuleType("monitor")
_MONITOR_STUB.DB_PATH = _BOOTSTRAP_DB.name
_MONITOR_STUB.TELEGRAM_TOKEN = "test"
_MONITOR_STUB.TELEGRAM_CHAT_ID = "test"
_MONITOR_STUB.enrich_property = lambda conn, data: data
sys.modules.setdefault("monitor", _MONITOR_STUB)

import telegram_commands


class GeoTelegramTest(unittest.TestCase):

    @classmethod
    def tearDownClass(cls):
        os.unlink(_BOOTSTRAP_DB.name)

    def setUp(self):

        CONFIG.config_dir = os.path.abspath(
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "config",
            )
        )

        self.temp = tempfile.NamedTemporaryFile(
            suffix=".sqlite3",
            delete=False,
        )
        self.temp.close()
        telegram_commands.DB_PATH = self.temp.name

        conn = sqlite3.connect(self.temp.name)
        conn.execute(
            """
            CREATE TABLE properties (
                id INTEGER PRIMARY KEY,
                portal TEXT,
                portal_id TEXT,
                property_type TEXT,
                title TEXT,
                location TEXT,
                price REAL,
                living_area REAL,
                plot_area REAL,
                score INTEGER,
                rating TEXT,
                is_ko INTEGER,
                score_details TEXT,
                latitude REAL,
                longitude REAL,
                water_score INTEGER,
                neighbour_class TEXT,
                buildings_100m INTEGER,
                last_seen TEXT
            )
            """
        )

        rows = (
            (
                1,
                "immowelt",
                "exact-70",
                "land",
                "Exact 70",
                "Musterstr. 1, 12345 Musterort",
                30000,
                None,
                1200,
                70,
                "interesting",
                0,
                json.dumps({}),
                52.0,
                11.0,
                10,
                "village",
                5,
                "2026-09-01",
            ),
            (
                2,
                "immowelt",
                "locality-65-95",
                "land",
                "Locality 65–95",
                "Musterort (12345)",
                30000,
                None,
                1500,
                None,
                "provisional",
                0,
                json.dumps(
                    {
                        "provisional": True,
                        "score_min": 65,
                        "score_max": 95,
                    }
                ),
                None,
                None,
                None,
                None,
                None,
                "2026-09-01",
            ),
            (
                3,
                "immowelt",
                "exact-60",
                "land",
                "Exact 60",
                "Musterweg 2, 12345 Musterort",
                30000,
                None,
                1100,
                60,
                "interesting",
                0,
                json.dumps({}),
                52.1,
                11.1,
                8,
                "village",
                10,
                "2026-09-01",
            ),
        )

        conn.executemany(
            """
            INSERT INTO properties
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        os.unlink(self.temp.name)

    def test_top_list_includes_and_conservatively_ranks_locality(self):

        rows = telegram_commands.get_top_property_rows(
            "land",
            3,
        )

        self.assertEqual(
            [row["portal_id"] for row in rows],
            [
                "exact-70",
                "locality-65-95",
                "exact-60",
            ],
        )

    def test_card_labels_provisional_range(self):

        card = telegram_commands.format_property_card(
            {
                "portal_id": "locality",
                "property_type": "land",
                "title": "Locality",
                "location": "Musterort (12345)",
                "score": None,
                "rating": "provisional",
                "score_details": json.dumps(
                    {
                        "provisional": True,
                        "score_min": 52,
                        "score_max": 87,
                    }
                ),
            }
        )

        self.assertIn(
            "⭐ 52–87 Punkte | "
            "📍 Lage nur auf Ortsebene bekannt",
            card,
        )


if __name__ == "__main__":
    unittest.main()
