import json
import sqlite3
import tempfile
import unittest

from incomplete_workflow import (
    condition_keyboard,
    condition_rows,
    energy_keyboard,
    energy_rows,
    energy_text,
    geo_keyboard,
    geo_rows,
    geo_text,
    locality_keyboard,
    locality_rows,
    locality_text,
    overview_keyboard,
    stats,
)


class IncompleteWorkflowTest(unittest.TestCase):

    def setUp(self):

        self.temp = tempfile.NamedTemporaryFile(
            suffix=".sqlite3",
            delete=False,
        )
        self.temp.close()
        self.db_path = self.temp.name

        conn = sqlite3.connect(self.db_path)

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
                condition_class TEXT,
                rating TEXT,
                is_ko INTEGER,
                score_details TEXT,
                last_seen TEXT,
                url TEXT,
                latitude REAL,
                longitude REAL,
                manual_coordinates_set_at TEXT,
                geo_precision TEXT
            )
            """
        )

        rows = [
            (
                1,
                "immowelt",
                "A",
                "house",
                "Haus A",
                "Ort A",
                100000,
                120,
                1200,
                "unknown",
                "incomplete",
                0,
                json.dumps(
                    {
                        "incomplete_reasons": [
                            "Preis/Zustand",
                            "Energie",
                        ]
                    }
                ),
                "2026-08-30T10:00:00Z",
                "https://example.invalid/a",
                None,
                None,
                None,
                "locality",
            ),
            (
                2,
                "immowelt",
                "B",
                "farm",
                "Hof B",
                "Ort B",
                None,
                None,
                None,
                "maintained",
                "incomplete",
                0,
                json.dumps(
                    {
                        "incomplete_reasons": [
                            "Preis/Zustand",
                            "Wohnfläche",
                            "Grundstück",
                            "Wasser",
                        ]
                    }
                ),
                "2026-08-30T09:00:00Z",
                "https://example.invalid/b",
                52.1,
                11.2,
                None,
                "missing",
            ),
        ]

        conn.executemany(
            """
            INSERT INTO properties (
                id,
                portal,
                portal_id,
                property_type,
                title,
                location,
                price,
                living_area,
                plot_area,
                condition_class,
                rating,
                is_ko,
                score_details,
                last_seen,
                url,
                latitude,
                longitude,
                manual_coordinates_set_at,
                geo_precision
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

        conn.commit()
        conn.close()

    def tearDown(self):

        import os
        os.unlink(self.db_path)

    def test_stats_split_condition_from_price(self):

        current = stats(self.db_path)

        self.assertEqual(current["Objekte"], 2)
        self.assertEqual(current["Zustand"], 1)
        self.assertEqual(current["Preis"], 1)
        self.assertEqual(current["Energie"], 1)
        self.assertEqual(current["Wohnfläche"], 1)
        self.assertEqual(current["Grundstück"], 1)
        self.assertEqual(current["Geo"], 1)

    def test_condition_queue_only_contains_unknown_condition(self):

        rows = condition_rows(self.db_path)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["portal_id"], "A")

    def test_condition_buttons_carry_workflow_context(self):

        row = condition_rows(self.db_path)[0]
        keyboard = condition_keyboard(row)

        callbacks = [
            button["callback_data"]
            for button_row in keyboard["inline_keyboard"]
            for button in button_row
        ]

        self.assertIn("c:A:r:iwc", callbacks)
        self.assertIn("iw:menu", callbacks)

    def test_energy_queue_only_contains_missing_energy(self):

        rows = energy_rows(self.db_path)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["portal_id"], "A")

    def test_energy_buttons_include_classes_and_neutral_outcomes(self):

        row = energy_rows(self.db_path)[0]
        keyboard = energy_keyboard(row)

        callbacks = [
            button["callback_data"]
            for button_row in keyboard["inline_keyboard"]
            for button in button_row
        ]

        self.assertIn("iwe:A:ap", callbacks)
        self.assertIn("iwe:A:h", callbacks)
        self.assertIn("iwe:A:none", callbacks)
        self.assertIn("iwe:A:nr", callbacks)
        self.assertIn("iwe:A:ny", callbacks)
        self.assertIn("iw:menu", callbacks)

    def test_energy_text_explains_no_data_is_completed_check(self):

        row = energy_rows(self.db_path)[0]

        text = energy_text(
            row,
            1,
            1,
        )

        self.assertIn(
            "Keine Angabe",
            text,
        )
        self.assertIn(
            "nicht mehr unvollständig",
            text,
        )

    def test_geo_queue_only_contains_missing_geo(self):

        rows = geo_rows(self.db_path)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["portal_id"], "B")

    def test_geo_queue_does_not_repeat_confirmed_coordinates(self):

        conn = sqlite3.connect(
            self.db_path
        )

        conn.execute(
            """
            UPDATE properties
            SET
                geo_precision = 'exact',
                latitude = 52.778467,
                longitude = 11.756631,
                manual_coordinates_set_at =
                    '2026-09-01T22:09:00Z'
            WHERE portal_id = 'B'
            """
        )

        conn.commit()
        conn.close()

        self.assertEqual(
            geo_rows(self.db_path),
            [],
        )

        self.assertEqual(
            stats(self.db_path)["Geo"],
            0,
        )

    def test_locality_queue_is_optional_and_advances(self):

        conn = sqlite3.connect(
            self.db_path
        )

        rows = [
            (
                3,
                "C",
                "Haus C",
                "Ort C (12345)",
                52,
                87,
                "2026-08-30T11:00:00Z",
            ),
            (
                4,
                "D",
                "Haus D",
                "Ort D (23456)",
                40,
                75,
                "2026-08-30T12:00:00Z",
            ),
        ]

        for (
            property_id,
            portal_id,
            title,
            location,
            score_min,
            score_max,
            last_seen,
        ) in rows:
            conn.execute(
                """
                INSERT INTO properties (
                    id,
                    portal,
                    portal_id,
                    property_type,
                    title,
                    location,
                    condition_class,
                    rating,
                    is_ko,
                    score_details,
                    last_seen,
                    url,
                    geo_precision
                )
                VALUES (
                    ?, 'immowelt', ?, 'house', ?, ?,
                    'good', 'provisional', 0, ?, ?,
                    'https://example.invalid/locality',
                    'locality'
                )
                """,
                (
                    property_id,
                    portal_id,
                    title,
                    location,
                    json.dumps(
                        {
                            "provisional": True,
                            "score_min": score_min,
                            "score_max": score_max,
                        }
                    ),
                    last_seen,
                ),
            )

        conn.commit()
        conn.close()

        locality = locality_rows(
            self.db_path
        )

        self.assertEqual(
            [row["portal_id"] for row in locality],
            ["C", "D"],
        )

        text = locality_text(
            locality[0],
            1,
            2,
        )

        self.assertIn(
            "52–87 Punkte",
            text,
        )
        self.assertIn(
            "genaue Lage ist noch unbekannt",
            text,
        )

        callbacks = [
            button["callback_data"]
            for button_row in locality_keyboard(
                locality[0]
            )["inline_keyboard"]
            for button in button_row
        ]

        self.assertIn(
            "coords_set:C:house:iwl",
            callbacks,
        )
        self.assertEqual(
            stats(self.db_path)["Lage präzisieren"],
            2,
        )

        overview_callbacks = [
            button["callback_data"]
            for button_row in overview_keyboard(
                self.db_path
            )["inline_keyboard"]
            for button in button_row
        ]

        self.assertIn(
            "iw:locality",
            overview_callbacks,
        )

        conn = sqlite3.connect(
            self.db_path
        )
        conn.execute(
            """
            UPDATE properties
            SET
                geo_precision = 'exact',
                rating = 'interesting',
                latitude = 52.1,
                longitude = 11.2
            WHERE portal_id = 'C'
            """
        )
        conn.commit()
        conn.close()

        self.assertEqual(
            [
                row["portal_id"]
                for row in locality_rows(
                    self.db_path
                )
            ],
            ["D"],
        )

    def test_geo_button_reuses_manual_coordinate_dialog(self):

        row = geo_rows(self.db_path)[0]
        keyboard = geo_keyboard(row)

        callbacks = [
            button["callback_data"]
            for button_row in keyboard["inline_keyboard"]
            for button in button_row
        ]

        self.assertIn(
            "coords_set:B:farm:iwg",
            callbacks,
        )
        self.assertIn(
            "iw:menu",
            callbacks,
        )

    def test_geo_text_does_not_claim_to_guess_address(self):

        row = geo_rows(self.db_path)[0]

        text = geo_text(
            row,
            1,
            1,
        )

        self.assertIn(
            "keine genaue Adresse automatisch geraten",
            text,
        )
        self.assertIn(
            "🌊 Wasser",
            text,
        )

    def test_overview_has_energy_condition_and_geo_buttons(self):

        keyboard = overview_keyboard(self.db_path)

        callbacks = [
            button["callback_data"]
            for button_row in keyboard["inline_keyboard"]
            for button in button_row
        ]

        self.assertEqual(
            callbacks,
            [
                "iw:energy",
                "iw:condition",
                "iw:geo",
            ],
        )


if __name__ == "__main__":
    unittest.main()
