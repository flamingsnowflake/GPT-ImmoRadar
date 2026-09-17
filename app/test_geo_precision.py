import json
import os
import sqlite3
import tempfile
import unittest

from config_loader import CONFIG
from geo_precision import (
    GEO_PRECISION_EXACT,
    GEO_PRECISION_LOCALITY,
    GEO_PRECISION_MISSING,
    classify_geo_precision,
    normalize_geo_precision,
)
from incomplete_workflow import geo_rows
from scoring import score_house, score_land


class GeoPrecisionTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        CONFIG.config_dir = os.path.abspath(
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "config",
            )
        )

    def _complete_house(self, location):

        return {
            "portal": "immowelt",
            "property_type": "house",
            "location": location,
            "price": 120000,
            "plot_area": 1200,
            "living_area": 120,
            "condition_class": "good",
            "neighbour_checked_at": "checked",
            "neighbour_class": "village",
            "noise_checked_at": "checked",
            "water_score": 10,
            "energy_updated_at": "checked",
            "energy_certificate_status": "available",
            "energy_class": "D",
            "latitude": 51.7440632,
            "longitude": 11.6862024,
        }

    def test_manual_coordinates_are_exact(self):

        precision = classify_geo_precision(
            {
                "location": "Hitzacker (29456)",
                "manual_latitude": 53.15,
                "manual_longitude": 11.05,
            }
        )

        self.assertEqual(
            precision,
            GEO_PRECISION_EXACT,
        )

    def test_street_and_house_number_are_exact(self):

        self.assertEqual(
            classify_geo_precision(
                {
                    "location": (
                        "Obere Kirchstr. 18, "
                        "39444 Hecklingen"
                    )
                }
            ),
            GEO_PRECISION_EXACT,
        )

    def test_rural_address_without_street_suffix_is_exact(self):

        for location in (
            "Tümplingsgrund 1, Löbitz, Burgenlandkreis",
            "Altköpsen 17, Hohenmölsen, Burgenlandkreis",
            "Straße des Friedens 12, 06184 Kabelsketal",
        ):
            with self.subTest(location=location):
                self.assertEqual(
                    classify_geo_precision(
                        {"location": location}
                    ),
                    GEO_PRECISION_EXACT,
                )

    def test_parcel_number_is_not_an_exact_address(self):

        for location in (
            "Flurstück 17, Gemarkung Zöschen",
            "Bauplatz 3, Hitzacker (29456)",
        ):
            with self.subTest(location=location):
                self.assertEqual(
                    classify_geo_precision(
                        {"location": location}
                    ),
                    GEO_PRECISION_LOCALITY,
                )

    def test_postcode_and_town_are_locality(self):

        self.assertEqual(
            classify_geo_precision(
                {
                    "location": "Hitzacker (29456)"
                }
            ),
            GEO_PRECISION_LOCALITY,
        )

    def test_empty_location_is_missing(self):

        self.assertEqual(
            classify_geo_precision(
                {"location": "-"}
            ),
            GEO_PRECISION_MISSING,
        )

    def test_locality_clears_centroid_and_geo_results(self):

        property_data = normalize_geo_precision(
            {
                "location": "Hitzacker (29456)",
                "latitude": 53.15,
                "longitude": 11.05,
                "water_score": 18,
                "neighbour_class": "isolated",
                "noise_checked_at": "checked",
            }
        )

        self.assertEqual(
            property_data["geo_precision"],
            GEO_PRECISION_LOCALITY,
        )
        self.assertIsNone(property_data["latitude"])
        self.assertIsNone(property_data["longitude"])
        self.assertIsNone(property_data["water_score"])
        self.assertIsNone(property_data["neighbour_class"])
        self.assertIsNone(property_data["noise_checked_at"])

    def test_exact_scoring_is_unchanged(self):

        property_data = self._complete_house(
            "Obere Kirchstr. 18, 39444 Hecklingen"
        )

        original = score_house(
            property_data
        )

        explicit = score_house(
            {
                **property_data,
                "geo_precision": GEO_PRECISION_EXACT,
            }
        )

        self.assertEqual(original, explicit)
        self.assertIsNotNone(original["score"])

    def test_locality_gets_provisional_range(self):

        property_data = self._complete_house(
            "Hitzacker (29456)"
        )

        result = score_house(
            property_data
        )

        self.assertIsNone(result["score"])
        self.assertEqual(
            result["rating"],
            "provisional",
        )
        self.assertTrue(result["provisional"])
        self.assertLess(
            result["score_min"],
            result["score_max"],
        )
        self.assertEqual(
            result["incomplete_reasons"],
            [],
        )

    def test_land_locality_gets_provisional_range(self):

        result = score_land(
            {
                "property_type": "land",
                "location": "Sachsendorf, Barby (39240)",
                "price": 30000,
                "plot_area": 1200,
                "primary_residence": "unknown",
                "buildability": "NO_INFORMATION",
            }
        )

        self.assertIsNone(result["score"])
        self.assertEqual(
            result["rating"],
            "provisional",
        )
        self.assertLess(
            result["score_min"],
            result["score_max"],
        )

    def test_exact_land_scoring_is_unchanged(self):

        property_data = {
            "property_type": "land",
            "location": "Musterweg 2, 12345 Musterort",
            "price": 30000,
            "plot_area": 1200,
            "primary_residence": "unknown",
            "buildability": "NO_INFORMATION",
            "latitude": 52.0,
            "longitude": 11.0,
            "water_score": 10,
            "water_class": "stream",
            "water_distance_km": 1.0,
            "neighbour_class": "village",
            "neighbour_checked_at": "checked",
            "noise_checked_at": "checked",
        }

        original = score_land(
            property_data
        )
        explicit = score_land(
            {
                **property_data,
                "geo_precision": GEO_PRECISION_EXACT,
            }
        )

        self.assertEqual(original, explicit)
        self.assertIsNotNone(original["score"])

    def test_locality_does_not_hide_other_incomplete_work(self):

        property_data = self._complete_house(
            "Hitzacker (29456)"
        )
        property_data["energy_updated_at"] = None

        result = score_house(
            property_data
        )

        self.assertEqual(
            result["rating"],
            "incomplete",
        )
        self.assertEqual(
            result["incomplete_reasons"],
            ["Energie"],
        )

    def test_missing_location_remains_geo_lab_work(self):

        temp = tempfile.NamedTemporaryFile(
            suffix=".sqlite3",
            delete=False,
        )
        temp.close()

        try:
            conn = sqlite3.connect(temp.name)
            conn.execute(
                """
                CREATE TABLE properties (
                    id INTEGER PRIMARY KEY,
                    portal TEXT,
                    portal_id TEXT,
                    property_type TEXT,
                    location TEXT,
                    geo_precision TEXT,
                    rating TEXT,
                    is_ko INTEGER,
                    score_details TEXT,
                    last_seen TEXT
                )
                """
            )
            conn.executemany(
                """
                INSERT INTO properties (
                    id,
                    portal,
                    portal_id,
                    property_type,
                    location,
                    geo_precision,
                    rating,
                    is_ko,
                    score_details,
                    last_seen
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        1,
                        "immowelt",
                        "locality",
                        "house",
                        "Hitzacker (29456)",
                        "locality",
                        "incomplete",
                        0,
                        json.dumps(
                            {
                                "incomplete_reasons": [
                                    "Wasser"
                                ]
                            }
                        ),
                        "2026-09-01",
                    ),
                    (
                        2,
                        "immowelt",
                        "missing",
                        "house",
                        None,
                        "missing",
                        "incomplete",
                        0,
                        json.dumps(
                            {
                                "incomplete_reasons": [
                                    "Wasser"
                                ]
                            }
                        ),
                        "2026-09-01",
                    ),
                ),
            )
            conn.commit()
            conn.close()

            rows = geo_rows(temp.name)

            self.assertEqual(
                [row["portal_id"] for row in rows],
                ["missing"],
            )

        finally:
            os.unlink(temp.name)

    def test_missing_location_ignores_stale_geo_points(self):

        property_data = self._complete_house(None)
        property_data.update(
            {
                "geo_precision": GEO_PRECISION_MISSING,
                "latitude": 52.0,
                "longitude": 11.0,
                "water_score": 20,
                "neighbour_class": "isolated",
                "neighbour_checked_at": "checked",
                "noise_checked_at": "checked",
            }
        )

        result = score_house(
            property_data
        )

        self.assertEqual(
            result["rating"],
            "incomplete",
        )
        self.assertIn(
            "Wasser",
            result["incomplete_reasons"],
        )
        self.assertIn(
            "Freilage/Nachbarn",
            result["incomplete_reasons"],
        )
        self.assertIn(
            "Lärm",
            result["incomplete_reasons"],
        )


if __name__ == "__main__":
    unittest.main()
