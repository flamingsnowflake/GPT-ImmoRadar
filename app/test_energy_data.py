import sqlite3
import tempfile
import unittest

from energy_data import (
    ensure_energy_columns,
    format_energy_summary,
    normalize_energy_data,
    update_property_energy,
)


class EnergyDataTest(unittest.TestCase):

    def test_normalize_available_energy(self):
        result = normalize_energy_data({
            "energy_class": "h",
            "energy_value_kwh": "443,8",
            "energy_certificate_type": "demand",
            "energy_certificate_status": "available",
            "heating_type": "Zentralheizung",
            "energy_source": "Öl",
            "energy_construction_year": "1956",
        })

        self.assertEqual(
            result["energy_class"],
            "H",
        )
        self.assertEqual(
            result["energy_value_kwh"],
            443.8,
        )
        self.assertEqual(
            result["energy_certificate_type"],
            "demand",
        )
        self.assertEqual(
            result["energy_construction_year"],
            1956,
        )

    def test_not_required_clears_rating_fields(self):
        result = normalize_energy_data({
            "energy_class": "A+",
            "energy_value_kwh": 20,
            "energy_certificate_type": "demand",
            "energy_certificate_status": "not_required",
            "heating_type": "Ofenheizung",
        })

        self.assertIsNone(
            result["energy_class"]
        )
        self.assertIsNone(
            result["energy_value_kwh"]
        )
        self.assertEqual(
            result["energy_certificate_type"],
            "unknown",
        )

    def test_data_implies_available_status(self):
        result = normalize_energy_data({
            "energy_class": "C",
            "energy_value_kwh": 85.2,
        })

        self.assertEqual(
            result["energy_certificate_status"],
            "available",
        )

    def test_summary(self):
        summary = format_energy_summary({
            "energy_certificate_status": "available",
            "energy_class": "E",
            "energy_value_kwh": 148.0,
            "energy_certificate_type": "demand",
        })

        self.assertEqual(
            summary,
            "Klasse E | 148,0 kWh/(m²·a) | Bedarf",
        )

    def test_update_property_energy(self):
        with tempfile.NamedTemporaryFile(delete_on_close=False) as tmp:
            conn = sqlite3.connect(tmp.name)
            conn.row_factory = sqlite3.Row

            conn.execute(
                """
                CREATE TABLE properties (
                    id INTEGER PRIMARY KEY,
                    portal TEXT NOT NULL,
                    portal_id TEXT NOT NULL,
                    title TEXT,
                    property_type TEXT
                )
                """
            )

            conn.execute(
                """
                INSERT INTO properties (
                    portal,
                    portal_id,
                    title,
                    property_type
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    "immoscout24",
                    "170214291",
                    "DENKMAL drüber nach!",
                    "farm",
                ),
            )

            ensure_energy_columns(conn)

            row, energy = update_property_energy(
                conn,
                "immoscout24",
                "170214291",
                {
                    "energy_certificate_status": "not_required",
                    "heating_type": "Ofenheizung",
                    "energy_source": "Kohle, Holz",
                },
            )

            self.assertEqual(
                row["property_type"],
                "farm",
            )
            self.assertEqual(
                energy["energy_certificate_status"],
                "not_required",
            )

            stored = conn.execute(
                """
                SELECT
                    energy_certificate_status,
                    heating_type,
                    energy_source
                FROM properties
                WHERE portal = ?
                  AND portal_id = ?
                """,
                (
                    "immoscout24",
                    "170214291",
                ),
            ).fetchone()

            self.assertEqual(
                stored["energy_certificate_status"],
                "not_required",
            )
            self.assertEqual(
                stored["heating_type"],
                "Ofenheizung",
            )
            self.assertEqual(
                stored["energy_source"],
                "Kohle, Holz",
            )

            conn.close()


if __name__ == "__main__":
    unittest.main()
