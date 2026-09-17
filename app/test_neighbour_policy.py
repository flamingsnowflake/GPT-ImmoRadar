import unittest

from config_loader import CONFIG
from monitor import classify_neighbours
from neighbour_policy import reclassify_stored_neighbours
from scoring import plot_points


class NeighbourPolicyTest(unittest.TestCase):

    @staticmethod
    def buildings(
        nearest,
        within_50,
        within_100=10,
        within_250=20,
    ):

        return {
            "nearest_building_m": nearest,
            "buildings_50m": within_50,
            "buildings_100m": within_100,
            "buildings_250m": within_250,
        }

    def test_isolated_requires_100_metres_to_nearest_building(self):

        self.assertEqual(
            classify_neighbours(
                self.buildings(100, 0)
            ),
            "isolated",
        )

        self.assertNotEqual(
            classify_neighbours(
                self.buildings(99.9, 3)
            ),
            "isolated",
        )

    def test_no_building_in_search_radius_is_isolated(self):

        self.assertEqual(
            classify_neighbours(
                self.buildings(None, 0, 0, 0)
            ),
            "isolated",
        )

    def test_few_neighbours_allows_at_most_two_within_50_metres(self):

        self.assertEqual(
            classify_neighbours(
                self.buildings(30, 2)
            ),
            "few_neighbours",
        )

        self.assertEqual(
            classify_neighbours(
                self.buildings(30, 3)
            ),
            "loose_development",
        )

    def test_missing_50_metre_measurement_grants_no_bonus_class(self):

        buildings = self.buildings(30, 3)
        buildings.pop("buildings_50m")

        self.assertEqual(
            classify_neighbours(buildings),
            "loose_development",
        )

    def test_stored_measurements_use_current_isolation_threshold(self):

        property_data = {
            **self.buildings(150, 0),
            "neighbour_class": "few_neighbours",
            "neighbour_checked_at": "checked",
        }

        self.assertEqual(
            reclassify_stored_neighbours(property_data),
            "isolated",
        )

    def test_stored_class_is_kept_without_usable_measurements(self):

        self.assertEqual(
            reclassify_stored_neighbours({
                "neighbour_class": "village_edge",
                "neighbour_checked_at": "checked",
            }),
            "village_edge",
        )

    def test_house_and_land_use_steep_plot_scale(self):

        config = CONFIG.score_config()

        for model in ("house", "land"):
            plot_config = config[model]["scoring"]["plot_area"]
            self.assertEqual(
                [
                    plot_points(area, plot_config)
                    for area in (1000, 1500, 2000, 3000, 5000)
                ],
                [3, 7, 10, 15, 20],
            )

    def test_isolation_points_are_strong_in_both_models(self):

        config = CONFIG.score_config()
        house = config["house"]["scoring"]["neighbours"]["values"]
        land = config["land"]["scoring"]["neighbours"]["values"]

        self.assertEqual(house["isolated"], 25)
        self.assertEqual(house["few_neighbours"], 20)
        self.assertEqual(house["dense"], 0)
        self.assertEqual(land["isolated"], 20)
        self.assertEqual(land["few_neighbours"], 16)
        self.assertEqual(land["dense"], 0)


if __name__ == "__main__":
    unittest.main()
