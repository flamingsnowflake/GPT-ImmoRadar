"""House cost assessment shared by hard filters and scoring."""


def house_costs(price, condition_class, config):
    price_config = config.get('scoring', {}).get('price', {})
    surcharges = price_config.get('condition_surcharge', {})
    known = condition_class in surcharges and condition_class != 'unknown'
    surcharge = surcharges.get(condition_class, surcharges.get('unknown', 100000))
    effective = None if price is None else price + surcharge
    limit = config.get('hard_filters', {}).get('max_price')
    # Unknown-condition estimates are not evidence for a hard rejection.
    assessed = effective if known else price
    over_budget = assessed is not None and limit is not None and assessed > limit
    reason = None
    if over_budget:
        euros = lambda number: f'{number:,.0f} €'.replace(',', '.')
        if known:
            reason = (f'Budget überschritten: Kaufpreis {euros(price)} + '
                      f'notwendige Zusatzkosten {euros(surcharge)} = '
                      f'{euros(effective)} > Grenze {euros(limit)}')
        else:
            reason = (f'Budget überschritten: Kaufpreis {euros(price)} > '
                      f'Grenze {euros(limit)}; Zusatzkosten noch offen')
    return {'surcharge': surcharge, 'effective_price': effective,
            'condition_known': known, 'limit': limit, 'ko_reason': reason}
