import unittest

from energy_data import (
    normalize_energy_data,
)
from incomplete_energy import (
    _energy_data_is_final,
    energy_choice_payload,
)


class IncompleteEnergyTest(unittest.TestCase):

    def test_energy_class_choice(self):

        payload = energy_choice_payload(
            "ap"
        )

        self.assertEqual(
            payload["energy_class"],
            "A+",
        )
        self.assertEqual(
            payload["energy_certificate_status"],
            "available",
        )

    def test_no_label_is_explicit_status(self):

        payload = energy_choice_payload(
            "nl"
        )

        self.assertEqual(
            payload["energy_certificate_status"],
            "no_label",
        )

        normalized = normalize_energy_data(
            payload
        )

        self.assertEqual(
            normalized["energy_certificate_status"],
            "no_label",
        )
        self.assertIsNone(
            normalized["energy_class"]
        )

    def test_no_energy_data_is_completed_unknown_check(self):

        payload = energy_choice_payload(
            "none"
        )

        self.assertEqual(
            payload["energy_certificate_status"],
            "unknown",
        )
        self.assertEqual(
            payload["energy_certificate_type"],
            "unknown",
        )

    def test_not_required_choice(self):

        payload = energy_choice_payload(
            "nr"
        )

        self.assertEqual(
            payload["energy_certificate_status"],
            "not_required",
        )

    def test_not_available_yet_choice(self):

        payload = energy_choice_payload(
            "ny"
        )

        self.assertEqual(
            payload["energy_certificate_status"],
            "not_available_yet",
        )

    def test_not_available_yet_remains_editable(self):

        self.assertFalse(
            _energy_data_is_final(
                {
                    "energy_updated_at":
                        "2026-08-31T10:00:00+00:00",
                    "energy_certificate_status":
                        "not_available_yet",
                }
            )
        )

    def test_final_energy_data_is_protected(self):

        self.assertTrue(
            _energy_data_is_final(
                {
                    "energy_updated_at":
                        "2026-08-31T10:00:00+00:00",
                    "energy_certificate_status":
                        "available",
                }
            )
        )

        self.assertTrue(
            _energy_data_is_final(
                {
                    "energy_updated_at":
                        "2026-08-31T10:00:00+00:00",
                    "energy_certificate_status":
                        "unknown",
                }
            )
        )

    def test_manual_value_accepts_german_decimal_comma(self):

        normalized = normalize_energy_data(
            {
                "energy_value_kwh": "184,7",
                "energy_certificate_status": "available",
                "energy_certificate_type": "unknown",
            }
        )

        self.assertEqual(
            normalized["energy_value_kwh"],
            184.7,
        )

    def test_unknown_choice_is_rejected(self):

        with self.assertRaises(
            ValueError
        ):
            energy_choice_payload(
                "banana"
            )


if __name__ == "__main__":
    unittest.main()
