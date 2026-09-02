import sqlite3
import tempfile
import unittest

from lab_terminal import (
    get_terminal_event,
    page_is_unavailable,
    purge_property,
)


class LabTerminalTests(unittest.TestCase):

    def make_db(self):

        handle = tempfile.NamedTemporaryFile(
            suffix=".sqlite3",
            delete=False,
        )
        handle.close()

        db = sqlite3.connect(
            handle.name
        )

        db.execute(
            """
            CREATE TABLE properties (
                id INTEGER PRIMARY KEY,
                portal TEXT NOT NULL,
                portal_id TEXT NOT NULL
            )
            """
        )

        db.execute(
            """
            CREATE TABLE property_searches (
                property_id INTEGER,
                search_id TEXT
            )
            """
        )

        db.execute(
            """
            CREATE TABLE property_favorites (
                portal_id TEXT PRIMARY KEY,
                marked_at TEXT
            )
            """
        )

        db.execute(
            """
            CREATE TABLE property_user_status (
                portal_id TEXT PRIMARY KEY,
                status TEXT,
                updated_at TEXT
            )
            """
        )

        db.execute(
            """
            INSERT INTO properties (
                id,
                portal,
                portal_id
            )
            VALUES (1, 'immoscout24', 'abc')
            """
        )

        db.execute(
            "INSERT INTO property_searches VALUES (1, 's1')"
        )

        db.execute(
            "INSERT INTO property_favorites VALUES ('abc', 'now')"
        )

        db.execute(
            "INSERT INTO property_user_status VALUES ('abc', 'offline', 'now')"
        )

        db.commit()
        db.close()

        return handle.name

    def test_unavailable_page_markers(self):

        samples = (
            "Dieses Angebot ist nicht mehr verfügbar",
            "Dieses Immobilienangebot ist nicht mehr verfügbar",
            "Die von Ihnen aufgerufene Immobilie ist nicht mehr verfügbar",
            "Dieses Exposé ist nicht mehr verfügbar",
        )

        for sample in samples:
            with self.subTest(sample=sample):
                self.assertTrue(
                    page_is_unavailable(
                        sample
                    )
                )

        self.assertFalse(
            page_is_unavailable(
                "Schönes Einfamilienhaus mit Garten"
            )
        )

    def test_purge_removes_related_rows_and_records_event(self):

        db_path = self.make_db()
        db = sqlite3.connect(
            db_path
        )

        purge_property(
            db,
            1,
            "immoscout24",
            "abc",
        )

        db.commit()

        self.assertIsNone(
            db.execute(
                "SELECT 1 FROM properties WHERE id = 1"
            ).fetchone()
        )

        self.assertIsNone(
            db.execute(
                "SELECT 1 FROM property_searches WHERE property_id = 1"
            ).fetchone()
        )

        self.assertIsNone(
            db.execute(
                "SELECT 1 FROM property_favorites WHERE portal_id = 'abc'"
            ).fetchone()
        )

        self.assertIsNone(
            db.execute(
                "SELECT 1 FROM property_user_status WHERE portal_id = 'abc'"
            ).fetchone()
        )

        db.close()

        event = get_terminal_event(
            db_path,
            "immoscout24",
            "abc",
        )

        self.assertIsNotNone(
            event
        )
        self.assertEqual(
            event["status"],
            "purged",
        )


if __name__ == "__main__":
    unittest.main()
