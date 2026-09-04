"""Best-case assessment using the normal scorer; never persists assumptions."""
from config_loader import CONFIG
from geo_precision import clear_geo_derived_data, effective_geo_precision
from property_types import is_house_type
from scoring import score_house, score_land, ENERGY_CLASS_ORDER

CHANCE_THRESHOLD = 75


def best_case_result(property_data):
    house = is_house_type(property_data.get('property_type'))
    scorer = score_house if house else score_land
    original = scorer(property_data)
    if original.get('ko'):
        return original
    candidate = dict(property_data)
    rules = CONFIG.score_config()['house' if house else 'land']['scoring']
    precision = candidate.get('geo_precision') or effective_geo_precision(candidate)
    if precision != 'exact':
        # A centroid has no reliable parcel-specific geo components.
        clear_geo_derived_data(candidate)
    candidate['_geo_precision_bypass'] = True
    if candidate.get('price') is None:
        candidate['price'] = 0
    for field in ('plot_area', 'living_area') if house else ('plot_area',):
        if candidate.get(field) is None:
            candidate[field] = max(b['min'] for b in rules[field]['brackets'])
    if not candidate.get('neighbour_class') or candidate['neighbour_class'] == 'unknown':
        values = rules['neighbours']['values']
        candidate['neighbour_class'] = max(values, key=values.get)
    candidate['neighbour_checked_at'] = candidate.get('neighbour_checked_at') or 'BEST_CASE'
    if candidate.get('water_score') is None and (house or candidate.get('water_distance_km') is None):
        candidate['water_score'] = 20
    candidate['noise_checked_at'] = candidate.get('noise_checked_at') or 'BEST_CASE'
    if candidate.get('rail_distance_m') is not None and candidate.get('rail_annual_traffic') is None:
        candidate['rail_annual_traffic'] = 0
    if house:
        surcharges = rules['price']['condition_surcharge']
        if candidate.get('condition_class') not in surcharges or candidate.get('condition_class') == 'unknown':
            known = {k: v for k, v in surcharges.items() if k != 'unknown'}
            candidate['condition_class'] = min(known, key=known.get)
        status = candidate.get('energy_certificate_status') or 'unknown'
        # Explicit no-label/not-required decisions and known bad classes/values stay.
        if status not in ('no_label', 'not_required'):
            if (str(candidate.get('energy_class') or '').upper() not in ENERGY_CLASS_ORDER
                    and candidate.get('energy_value_kwh') is None):
                values = rules.get('energy', {}).get('class_adjustments', {})
                candidate['energy_class'] = max(values, key=values.get) if values else 'A+'
            if status in ('unknown', 'not_available_yet'):
                candidate['energy_certificate_status'] = 'available'
        candidate['energy_updated_at'] = candidate.get('energy_updated_at') or 'BEST_CASE'
    else:
        for field in ('primary_residence', 'buildability'):
            if candidate.get(field) in (None, '', 'unknown', 'NO_INFORMATION'):
                values = rules[field]['values']
                candidate[field] = max(values, key=values.get)
    return scorer(candidate)


def max_reachable_score(property_data):
    result = best_case_result(property_data)
    return 0 if result.get('ko') else result.get('score')


def qualifies_as_chance(property_data):
    maximum = max_reachable_score(property_data)
    return maximum is not None and maximum > CHANCE_THRESHOLD
