import unittest

from manual_coordinates import (
    coordinates_keyboard,
    parse_coordinates,
    resolve_manual_location,
)


class ManualCoordinatesTest(unittest.TestCase):

    def test_parse_coordinates_accepts_decimal_comma(self):

        self.assertEqual(
            parse_coordinates(
                "52,403560, 12,147920"
            ),
            (
                52.403560,
                12.147920,
            ),
        )

    def test_parse_coordinates_rejects_invalid_range(self):

        self.assertIsNone(
            parse_coordinates(
                "152.0, 12.0"
            )
        )

    def test_resolve_direct_coordinates_does_not_geocode(self):

        result = resolve_manual_location(
            "52.403560 12.147920"
        )

        self.assertEqual(
            result["latitude"],
            52.403560,
        )
        self.assertEqual(
            result["longitude"],
            12.147920,
        )
        self.assertEqual(
            result["source"],
            "telegram",
        )
        self.assertIsNone(
            result["display_name"]
        )

    def test_coordinate_keyboard_preserves_callbacks(self):

        keyboard = coordinates_keyboard(
            "ABC",
            "house",
            "new",
            manual=True,
        )

        callbacks = [
            button["callback_data"]
            for row in keyboard[
                "inline_keyboard"
            ]
            for button in row
        ]

        self.assertEqual(
            callbacks,
            [
                "coords_set:ABC:house:new",
                "coords_auto:ABC:house:new",
                "back:ABC:house:new",
            ],
        )


if __name__ == "__main__":
    unittest.main()
