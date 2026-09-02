import sqlite3
import tempfile
import unittest

from browser_energy import extract_energy_data
from energy_data import normalize_energy_data
import user_status


class EnergyConsistencyFixTests(unittest.TestCase):

    def test_class_overrides_not_available_yet(self):

        data = normalize_energy_data({
            "energy_class": "E",
            "energy_certificate_status": "not_available_yet",
            "energy_certificate_type": "demand",
        })

        self.assertEqual(
            data["energy_certificate_status"],
            "available",
        )

    def test_value_overrides_not_available_yet(self):

        data = normalize_energy_data({
            "energy_value_kwh": "133,9",
            "energy_certificate_status": "not_available_yet",
        })

        self.assertEqual(
            data["energy_certificate_status"],
            "available",
        )

        self.assertEqual(
            data["energy_value_kwh"],
            133.9,
        )

    def test_real_waiting_case_stays_waiting(self):

        data = normalize_energy_data({
            "energy_certificate_status": "not_available_yet",
            "energy_certificate_type": "demand",
        })

        self.assertEqual(
            data["energy_certificate_status"],
            "not_available_yet",
        )

    def test_baujahr_is_not_misread_as_class_b(self):

        data = extract_energy_data(
            """
            Bausubstanz & Energieausweis
            Energieeffizienzklasse:
            Baujahr laut Energieausweis: 1974
            Endenergiebedarf: 133,9 kWh/(m²*a)
            """
        )

        self.assertNotEqual(
            data["energy_class"],
            "B",
        )

        self.assertEqual(
            data["energy_value_kwh"],
            133.9,
        )

        self.assertEqual(
            data["energy_certificate_status"],
            "available",
        )

    def test_user_status_ensure_runs_once_per_process(self):

        with tempfile.NamedTemporaryFile(
            suffix=".sqlite3"
        ) as handle:

            conn = sqlite3.connect(
                handle.name
            )

            conn.execute(
                """
                CREATE TABLE properties (
                    id INTEGER PRIMARY KEY,
                    portal_id TEXT,
                    rating TEXT,
                    score_details TEXT
                )
                """
            )

            conn.commit()
            conn.close()

            user_status._ENSURED_DATABASES.discard(
                handle.name
            )

            user_status.ensure_user_status_table(
                handle.name
            )

            self.assertIn(
                handle.name,
                user_status._ENSURED_DATABASES,
            )

            user_status.ensure_user_status_table(
                handle.name
            )


if __name__ == "__main__":
    unittest.main()
