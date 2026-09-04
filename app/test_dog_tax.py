import unittest
from datetime import date
from decimal import Decimal

from dog_tax import (
    POSITIONAL_TIERS,
    TOTAL_COUNT_TIERS,
    DogTaxTariff,
    DogTaxTier,
    calculate_dog_tax,
)


SCHEESSEL_SOURCE = (
    "https://www.scheessel.de/rathaus-service/"
    "buergerservice/was-erledige-ich-wo/"
    "themen/hundesteuer"
)

WIMMELBURG_SOURCE = (
    "https://www.verwaltungsamt-helbra.de/"
    "wp-content/uploads/2026/04/"
    "Wimm_Hundesteuersatzung_2021.pdf"
)

MUENSTER_SOURCE = (
    "https://www.stadt-muenster.de/recht/ortsrecht/"
    "satzungen/detailansicht/satzungsnummer/20.01"
)


class DogTaxTest(unittest.TestCase):

    def test_scheessel_nine_normal_dogs_use_tiers(self):

        tariff = DogTaxTariff(
            municipality_key="03357041",
            municipality_name="Scheeßel",
            calculation_model=POSITIONAL_TIERS,
            normal_dog_tiers=(
                DogTaxTier(
                    from_dog=1,
                    annual_cents=4800,
                ),
                DogTaxTier(
                    from_dog=2,
                    annual_cents=8000,
                ),
                DogTaxTier(
                    from_dog=3,
                    annual_cents=10500,
                ),
            ),
            dangerous_dog_annual_cents=50000,
            valid_from=date(2024, 1, 1),
            source_version="Steuersätze ab 01.01.2024",
            checked_on=date(2026, 9, 2),
            source_url=SCHEESSEL_SOURCE,
        )

        indication = calculate_dog_tax(
            tariff,
            normal_dogs=9,
        )

        self.assertEqual(
            indication.total_dogs,
            9,
        )

        self.assertEqual(
            indication.annual_cents,
            86300,
        )

        self.assertEqual(
            indication.monthly_euros,
            Decimal("71.92"),
        )

        self.assertEqual(
            indication.tariff.source_url,
            SCHEESSEL_SOURCE,
        )

        self.assertEqual(
            indication.tariff.valid_from,
            date(2024, 1, 1),
        )

    def test_wimmelburg_flat_rate_is_one_tier(self):

        tariff = DogTaxTariff(
            municipality_key="15087470",
            municipality_name="Wimmelburg",
            calculation_model=POSITIONAL_TIERS,
            normal_dog_tiers=(
                DogTaxTier(
                    from_dog=1,
                    annual_cents=6000,
                ),
            ),
            dangerous_dog_annual_cents=30000,
            valid_from=date(2022, 1, 1),
            source_version="Satzung vom 09.09.2021",
            checked_on=date(2026, 9, 2),
            source_url=WIMMELBURG_SOURCE,
        )

        indication = calculate_dog_tax(
            tariff,
            normal_dogs=9,
        )

        self.assertEqual(
            indication.annual_cents,
            54000,
        )

        self.assertEqual(
            indication.monthly_euros,
            Decimal("45.00"),
        )

    def test_muenster_total_count_tier_applies_to_every_dog(self):

        tariff = DogTaxTariff(
            municipality_key="05515000",
            municipality_name="Münster",
            calculation_model=TOTAL_COUNT_TIERS,
            normal_dog_tiers=(
                DogTaxTier(
                    from_dog=1,
                    annual_cents=12000,
                ),
                DogTaxTier(
                    from_dog=2,
                    annual_cents=13200,
                ),
                DogTaxTier(
                    from_dog=3,
                    annual_cents=14400,
                ),
            ),
            dangerous_dog_annual_cents=75000,
            valid_from=None,
            source_version=(
                "Fassung der 1. Änderungssatzung "
                "vom 12.12.2025"
            ),
            checked_on=date(2026, 9, 2),
            source_url=MUENSTER_SOURCE,
        )

        indication = calculate_dog_tax(
            tariff,
            normal_dogs=9,
        )

        self.assertEqual(
            indication.annual_cents,
            129600,
        )

        self.assertEqual(
            indication.monthly_euros,
            Decimal("108.00"),
        )


if __name__ == "__main__":
    unittest.main()
