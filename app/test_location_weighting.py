import copy
import unittest
from pathlib import Path
from unittest.mock import patch

from config_loader import CONFIG
from scoring import location_weighting_details, score_house


PLOETZKAU_LATITUDE = 51.7440632
PLOETZKAU_LONGITUDE = 11.6862024


class LocationWeightingTest(unittest.TestCase):

    def setUp(self):
        config_dir = Path(__file__).resolve().parent.parent / "config"
        config_patch = patch.object(
            CONFIG, "config_dir", str(config_dir)
        )
        config_patch.start()
        self.addCleanup(config_patch.stop)

        self.config = {
            "enabled": True,
            "reference_name": "Plötzkau",
            "latitude": PLOETZKAU_LATITUDE,
            "longitude": PLOETZKAU_LONGITUDE,
            "max_distance_km": 100,
            "existing_score_weight": 0.8,
            "proximity_score_weight": 0.2,
        }

    def test_reference_location_has_full_proximity_score(self):
        details = location_weighting_details(
            80,
            {
                "latitude": PLOETZKAU_LATITUDE,
                "longitude": PLOETZKAU_LONGITUDE,
            },
            self.config,
        )

        self.assertEqual(details["distance_to_reference_km"], 0.0)
        self.assertEqual(details["proximity_score"], 100.0)
        self.assertEqual(details["score"], 84)

    def test_proximity_score_falls_linearly(self):
        latitude_roughly_50_km_north = (
            PLOETZKAU_LATITUDE + 50 / 111.195
        )

        details = location_weighting_details(
            80,
            {
                "latitude": latitude_roughly_50_km_north,
                "longitude": PLOETZKAU_LONGITUDE,
            },
            self.config,
        )

        self.assertAlmostEqual(
            details["distance_to_reference_km"], 50.0, delta=0.1
        )
        self.assertAlmostEqual(
            details["proximity_score"], 50.0, delta=0.1
        )
        self.assertEqual(details["score"], 74)

    def test_distance_beyond_100_km_has_zero_proximity_score(self):
        details = location_weighting_details(
            80,
            {
                "latitude": PLOETZKAU_LATITUDE + 1,
                "longitude": PLOETZKAU_LONGITUDE,
            },
            self.config,
        )

        self.assertGreater(details["distance_to_reference_km"], 100)
        self.assertEqual(details["proximity_score"], 0.0)
        self.assertEqual(details["score"], 64)

    def test_neighbour_class_does_not_add_a_separate_bonus(self):
        property_data = {
            "latitude": PLOETZKAU_LATITUDE,
            "longitude": PLOETZKAU_LONGITUDE,
        }

        isolated = location_weighting_details(
            80,
            {**property_data, "neighbour_class": "isolated"},
            self.config,
        )
        few = location_weighting_details(
            80,
            {**property_data, "neighbour_class": "few_neighbours"},
            self.config,
        )
        loose = location_weighting_details(
            80,
            {**property_data, "neighbour_class": "loose_development"},
            self.config,
        )

        self.assertEqual(isolated["score"], 84)
        self.assertEqual(few["score"], 84)
        self.assertEqual(loose["score"], 84)
        self.assertNotIn("neighbour_preference_bonus", isolated)

    def test_exceptional_base_score_can_exceed_100(self):
        details = location_weighting_details(
            108,
            {
                "latitude": PLOETZKAU_LATITUDE,
                "longitude": PLOETZKAU_LONGITUDE,
            },
            self.config,
        )

        self.assertEqual(details["score"], 106)
        self.assertLessEqual(details["score"], 110)

    def test_missing_coordinates_cannot_produce_exact_score(self):
        self.assertIsNone(
            location_weighting_details(80, {}, self.config)
        )

    def test_house_score_contains_weighting_details(self):
        root_config = copy.deepcopy(CONFIG.score_config())
        root_config["location_weighting"] = self.config
        house = {
            "object_type": "house",
            "price": 150000,
            "plot_area": 1000,
            "living_area": 120,
            "condition_class": "good",
            "water_score": 5,
            "neighbour_class": "isolated",
            "neighbour_checked_at": "2026-09-07T00:00:00Z",
            "noise_checked_at": "2026-09-07T00:00:00Z",
            "energy_class": "C",
            "energy_certificate_status": "available",
            "energy_updated_at": "2026-09-07T00:00:00Z",
            "latitude": PLOETZKAU_LATITUDE,
            "longitude": PLOETZKAU_LONGITUDE,
        }

        with patch.object(CONFIG, "score_config", return_value=root_config):
            result = score_house(house)

        self.assertFalse(result["ko"])
        self.assertEqual(result["score"], round(
            result["base_score"] * 0.8 + 100 * 0.2
        ))
        self.assertEqual(result["location_reference"], "Plötzkau")
        self.assertTrue(any(
            "80 %" in reason
            and "20 %" in reason
            and "Freilagebonus" not in reason
            for reason in result["reasons"]
        ))

    def test_perfect_house_uses_energy_bonus_above_100(self):
        root_config = copy.deepcopy(CONFIG.score_config())
        root_config["location_weighting"] = self.config
        house = {
            "object_type": "house",
            "price": 0,
            "plot_area": 5000,
            "living_area": 150,
            "condition_class": "turnkey",
            "water_score": 20,
            "neighbour_class": "isolated",
            "neighbour_checked_at": "checked",
            "noise_checked_at": "checked",
            "energy_class": "A+",
            "energy_certificate_status": "available",
            "energy_updated_at": "checked",
            "latitude": PLOETZKAU_LATITUDE,
            "longitude": PLOETZKAU_LONGITUDE,
        }

        with patch.object(CONFIG, "score_config", return_value=root_config):
            result = score_house(house)

        self.assertEqual(result["base_score"], 108)
        self.assertEqual(result["score"], 106)
        self.assertFalse(any(
            "Lärm: +0 (Lärm:" in reason
            for reason in result["reasons"]
        ))

        house["portal"] = "ohne-makler"
        with patch.object(CONFIG, "score_config", return_value=root_config):
            broker_free_result = score_house(house)

        self.assertEqual(broker_free_result["base_score"], 110)
        self.assertEqual(broker_free_result["score"], 108)


if __name__ == "__main__":
    unittest.main()
