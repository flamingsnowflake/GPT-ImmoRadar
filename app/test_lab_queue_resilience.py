import json
import sqlite3
import tempfile
import unittest

from incomplete_workflow import (
    condition_rows,
    energy_rows,
)


class LabQueueResilienceTests(
    unittest.TestCase
):

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
                portal_id TEXT NOT NULL,
                property_type TEXT,
                rating TEXT,
                is_ko INTEGER DEFAULT 0,
                last_seen TEXT,
                score_details TEXT,
                condition_class TEXT,
                energy_certificate_status TEXT,
                energy_updated_at TEXT
            )
            """
        )

        db.commit()
        db.close()

        return handle.name

    def insert_house(
        self,
        db_path,
        *,
        rating="incomplete",
        condition_class="unknown",
        energy_status="unknown",
        energy_updated_at=None,
        incomplete_reasons=None,
    ):

        db = sqlite3.connect(
            db_path
        )

        db.execute(
            """
            INSERT INTO properties (
                id,
                portal,
                portal_id,
                property_type,
                rating,
                is_ko,
                last_seen,
                score_details,
                condition_class,
                energy_certificate_status,
                energy_updated_at
            )
            VALUES (
                1,
                'immoscout24',
                'test-1',
                'house',
                ?,
                0,
                '2026-09-01T00:00:00+00:00',
                ?,
                ?,
                ?,
                ?
            )
            """,
            (
                rating,
                json.dumps({
                    "incomplete_reasons":
                        incomplete_reasons
                        or []
                }),
                condition_class,
                energy_status,
                energy_updated_at,
            ),
        )

        db.commit()
        db.close()

    def test_blacklisted_condition_leaves_queue(
        self
    ):

        db_path = self.make_db()
        self.insert_house(
            db_path
        )

        self.assertEqual(
            len(
                condition_rows(
                    db_path
                )
            ),
            1,
        )

        db = sqlite3.connect(
            db_path
        )
        db.execute(
            """
            UPDATE properties
            SET rating = 'blacklisted'
            """
        )
        db.commit()
        db.close()

        self.assertEqual(
            condition_rows(
                db_path
            ),
            [],
        )

    def test_deleted_condition_leaves_queue(
        self
    ):

        db_path = self.make_db()
        self.insert_house(
            db_path
        )

        db = sqlite3.connect(
            db_path
        )
        db.execute(
            "DELETE FROM properties"
        )
        db.commit()
        db.close()

        self.assertEqual(
            condition_rows(
                db_path
            ),
            [],
        )

    def test_live_energy_state_beats_stale_snapshot(
        self
    ):

        db_path = self.make_db()
        self.insert_house(
            db_path,
            condition_class="good",
            energy_status="available",
            energy_updated_at=(
                "2026-09-01T00:00:00+00:00"
            ),
            incomplete_reasons=[
                "Energie"
            ],
        )

        self.assertEqual(
            energy_rows(
                db_path
            ),
            [],
        )

    def test_not_available_yet_stays_open(
        self
    ):

        db_path = self.make_db()
        self.insert_house(
            db_path,
            condition_class="good",
            energy_status=(
                "not_available_yet"
            ),
            energy_updated_at=(
                "2026-09-01T00:00:00+00:00"
            ),
        )

        self.assertEqual(
            len(
                energy_rows(
                    db_path
                )
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()
