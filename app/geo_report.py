"""User-visible outcome of a complete geo scan."""


def geo_report_lines(property_data):
    errors = property_data.get('_geo_errors') or {}
    checks = [
        ('Wasser', property_data.get('water_score') is not None),
        ('Nachbarn', bool(property_data.get('neighbour_checked_at'))
         and property_data.get('neighbour_class') not in (None, '', 'unknown')),
        ('Lärm/Bahn', bool(property_data.get('noise_checked_at'))),
    ]
    lines = []
    for label, complete in checks:
        if complete and label not in errors:
            lines.append(f'✅ {label}: neu berechnet')
        else:
            reason = errors.get(label) or 'keine verwertbaren Daten; Prüfung bleibt offen'
            lines.append(f'⚠️ {label}: {reason}')
    return lines
