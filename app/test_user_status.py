import json
import os
import sqlite3
import tempfile
import unittest

from user_status import (
    ensure_user_status_table,
    get_user_status,
    set_user_status,
    toggle_user_status,
)


class UserStatusTest(unittest.TestCase):

    def setUp(self):

        self.temp = tempfile.NamedTemporaryFile(
            suffix=".sqlite3",
            delete=False,
        )
        self.temp.close()
        self.db_path = self.temp.name

        conn = sqlite3.connect(
            self.db_path
        )

        conn.execute(
            """
            CREATE TABLE properties (
                id INTEGER PRIMARY KEY,
                portal TEXT,
                portal_id TEXT,
                title TEXT,
                property_type TEXT,
                score INTEGER,
                rating TEXT,
                is_ko INTEGER,
                score_details TEXT,
                last_seen TEXT
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE spam_objects (
                portal TEXT NOT NULL,
                portal_id TEXT NOT NULL,
                title TEXT,
                marked_at TEXT NOT NULL,
                UNIQUE(portal, portal_id)
            )
            """
        )

        conn.execute(
            """
            INSERT INTO properties (
                id,
                portal,
                portal_id,
                title,
                property_type,
                score,
                rating,
                is_ko,
                score_details,
                last_seen
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "immowelt",
                "A",
                "Haus A",
                "house",
                74,
                "interesting",
                0,
                json.dumps(
                    {
                        "score": 74,
                        "rating": "interesting",
                        "ko": False,
                    }
                ),
                "2026-08-30T10:00:00Z",
            )
        )

        conn.commit()
        conn.close()

    def tearDown(self):

        os.unlink(
            self.db_path
        )

    def test_offline_toggle_does_not_touch_score(self):

        result = toggle_user_status(
            self.db_path,
            "A",
            "offline",
        )

        self.assertEqual(
            result["status"],
            "offline",
        )

        conn = sqlite3.connect(
            self.db_path
        )

        row = conn.execute(
            """
            SELECT score, rating, is_ko
            FROM properties
            WHERE portal_id = 'A'
            """
        ).fetchone()

        conn.close()

        self.assertEqual(
            row,
            (74, "interesting", 0),
        )

        result = toggle_user_status(
            self.db_path,
            "A",
            "offline",
        )

        self.assertEqual(
            result["status"],
            "active",
        )

        self.assertEqual(
            get_user_status(
                self.db_path,
                "A",
            ),
            "active",
        )

    def test_not_interested_toggle_updates_spam_only(self):

        result = toggle_user_status(
            self.db_path,
            "A",
            "not_interested",
        )

        self.assertEqual(
            result["status"],
            "not_interested",
        )

        conn = sqlite3.connect(
            self.db_path
        )

        spam = conn.execute(
            """
            SELECT 1
            FROM spam_objects
            WHERE portal_id = 'A'
            """
        ).fetchone()

        row = conn.execute(
            """
            SELECT score, rating, is_ko
            FROM properties
            WHERE portal_id = 'A'
            """
        ).fetchone()

        conn.close()

        self.assertIsNotNone(
            spam
        )

        self.assertEqual(
            row,
            (74, "interesting", 0),
        )

        toggle_user_status(
            self.db_path,
            "A",
            "not_interested",
        )

        conn = sqlite3.connect(
            self.db_path
        )

        spam = conn.execute(
            """
            SELECT 1
            FROM spam_objects
            WHERE portal_id = 'A'
            """
        ).fetchone()

        conn.close()

        self.assertIsNone(
            spam
        )

    def test_statuses_are_mutually_exclusive(self):

        set_user_status(
            self.db_path,
            "A",
            "offline",
        )

        set_user_status(
            self.db_path,
            "A",
            "not_interested",
        )

        self.assertEqual(
            get_user_status(
                self.db_path,
                "A",
            ),
            "not_interested",
        )

    def test_legacy_offline_is_migrated_and_score_restored(self):

        conn = sqlite3.connect(
            self.db_path
        )

        conn.execute(
            """
            UPDATE properties
            SET
                score = NULL,
                rating = 'offline',
                is_ko = 1,
                score_details = ?
            WHERE portal_id = 'A'
            """,
            (
                json.dumps(
                    {
                        "score": None,
                        "rating": "incomplete",
                        "ko": False,
                        "incomplete_reasons": [
                            "Wasser"
                        ],
                    }
                ),
            )
        )

        conn.commit()
        conn.close()

        ensure_user_status_table(
            self.db_path
        )

        self.assertEqual(
            get_user_status(
                self.db_path,
                "A",
            ),
            "offline",
        )

        conn = sqlite3.connect(
            self.db_path
        )

        row = conn.execute(
            """
            SELECT score, rating, is_ko
            FROM properties
            WHERE portal_id = 'A'
            """
        ).fetchone()

        conn.close()

        self.assertEqual(
            row,
            (None, "incomplete", 0),
        )


if __name__ == "__main__":
    unittest.main()
