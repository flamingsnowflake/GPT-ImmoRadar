from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP


POSITIONAL_TIERS = "positional_tiers"
TOTAL_COUNT_TIERS = "total_count_tiers"


def _non_negative_integer(value, field_name):

    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
    ):
        raise ValueError(
            f"{field_name} muss eine nichtnegative ganze Zahl sein"
        )

    return value


@dataclass(frozen=True)
class DogTaxTier:

    from_dog: int
    annual_cents: int

    def __post_init__(self):

        if (
            isinstance(self.from_dog, bool)
            or not isinstance(self.from_dog, int)
            or self.from_dog < 1
        ):
            raise ValueError(
                "from_dog muss eine positive ganze Zahl sein"
            )

        _non_negative_integer(
            self.annual_cents,
            "annual_cents",
        )


@dataclass(frozen=True)
class DogTaxTariff:

    municipality_key: str
    municipality_name: str
    calculation_model: str
    normal_dog_tiers: tuple[DogTaxTier, ...]
    dangerous_dog_annual_cents: int | None
    valid_from: date | None
    source_version: str
    checked_on: date
    source_url: str

    def __post_init__(self):

        if self.calculation_model not in {
            POSITIONAL_TIERS,
            TOTAL_COUNT_TIERS,
        }:
            raise ValueError(
                "Unbekanntes Hundesteuer-Berechnungsmodell: "
                f"{self.calculation_model}"
            )

        tier_starts = [
            tier.from_dog
            for tier in self.normal_dog_tiers
        ]

        if (
            not tier_starts
            or tier_starts[0] != 1
            or tier_starts != sorted(set(tier_starts))
        ):
            raise ValueError(
                "Hundesteuerstaffeln müssen eindeutig und "
                "aufsteigend mit Hund 1 beginnen"
            )

        if self.dangerous_dog_annual_cents is not None:
            _non_negative_integer(
                self.dangerous_dog_annual_cents,
                "dangerous_dog_annual_cents",
            )


@dataclass(frozen=True)
class DogTaxIndication:

    tariff: DogTaxTariff
    normal_dogs: int
    dangerous_dogs: int
    annual_cents: int

    @property
    def total_dogs(self):

        return (
            self.normal_dogs
            + self.dangerous_dogs
        )

    @property
    def monthly_euros(self):

        return (
            Decimal(self.annual_cents)
            / Decimal(1200)
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )


def _tier_rate(tiers, dog_number):

    matching_tiers = [
        tier
        for tier in tiers
        if tier.from_dog <= dog_number
    ]

    return matching_tiers[-1].annual_cents


def _normal_dog_tax(tariff, normal_dogs):

    if normal_dogs == 0:
        return 0

    if tariff.calculation_model == POSITIONAL_TIERS:
        return sum(
            _tier_rate(
                tariff.normal_dog_tiers,
                dog_number,
            )
            for dog_number in range(
                1,
                normal_dogs + 1,
            )
        )

    rate = _tier_rate(
        tariff.normal_dog_tiers,
        normal_dogs,
    )

    return normal_dogs * rate


def calculate_dog_tax(
    tariff,
    normal_dogs,
    dangerous_dogs=0,
):

    normal_dogs = _non_negative_integer(
        normal_dogs,
        "normal_dogs",
    )

    dangerous_dogs = _non_negative_integer(
        dangerous_dogs,
        "dangerous_dogs",
    )

    if (
        dangerous_dogs
        and tariff.dangerous_dog_annual_cents is None
    ):
        raise ValueError(
            "Für gefährliche Hunde ist kein Tarif hinterlegt"
        )

    annual_cents = (
        _normal_dog_tax(
            tariff,
            normal_dogs,
        )
        + dangerous_dogs
        * (
            tariff.dangerous_dog_annual_cents
            or 0
        )
    )

    return DogTaxIndication(
        tariff=tariff,
        normal_dogs=normal_dogs,
        dangerous_dogs=dangerous_dogs,
        annual_cents=annual_cents,
    )
