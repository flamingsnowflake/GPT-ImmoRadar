"""Shared neighbour classification rules for new and stored properties."""


def classify_neighbours(buildings):
    """Classify surrounding foreign building polygons."""

    nearest = buildings.get("nearest_building_m")
    b50 = buildings.get("buildings_50m")
    b100 = buildings.get("buildings_100m")
    b250 = buildings.get("buildings_250m")

    # True isolation: no foreign building was found in the search radius,
    # or the nearest one is at least 100 metres away.
    if nearest is None or nearest >= 100:
        return "isolated"

    if b50 is not None and b50 <= 2:
        return "few_neighbours"

    if b100 is None:
        b100 = float("inf")
    if b250 is None:
        b250 = float("inf")

    if b100 <= 30 and b250 <= 150:
        return "loose_development"

    if b100 <= 60 and b250 <= 300:
        return "village_edge"

    if b100 <= 100 and b250 <= 500:
        return "village"

    return "dense"


def reclassify_stored_neighbours(property_data):
    """Apply current rules when a stored neighbour check has usable metrics."""

    current = property_data.get("neighbour_class")

    if not property_data.get("neighbour_checked_at"):
        return current

    measurements = {
        "nearest_building_m": property_data.get("nearest_building_m"),
        "buildings_50m": property_data.get("buildings_50m"),
        "buildings_100m": property_data.get("buildings_100m"),
        "buildings_250m": property_data.get("buildings_250m"),
    }

    if all(value is None for value in measurements.values()):
        return current

    return classify_neighbours(measurements)
