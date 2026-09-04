"""Half-automatic municipal tax research for Top-10 houses and favorites."""
from datetime import date
from decimal import Decimal, InvalidOperation
from dog_tax import DogTaxTariff, DogTaxTier, POSITIONAL_TIERS, TOTAL_COUNT_TIERS
from dog_tax_store import assign_municipality, save_tariff, research_queue, selected_properties


HELP = (
    '🐕 Hundesteuer · 9 normale Hunde\n\n'
    'Nur Top-10-Häuser und Merkliste werden geprüft. Gemeinde und Satzung bitte anhand amtlicher Quellen bestätigen.\n\n'
    'Gemeinde zuordnen:\n/dogtax_link ID | Gemeindeschlüssel | Gemeinde | HTTPS-Quelle\n\n'
    'Satzung speichern:\n/dogtax_set Gemeindeschlüssel | Gemeinde | gültig-ab (JJJJ-MM-TT oder ?) | staffel/alle | Jahressätze | HTTPS-Quelle | Satzungsstand\n\n'
    'Jahressätze als Eurobeträge mit Semikolon trennen, z. B. 48;80;105. '
    'Der letzte Satz gilt ab dem letzten angegebenen Hund. '
    'staffel = Satz je Hundposition; alle = der Satz nach Gesamtzahl gilt für jeden Hund. '
    'Es werden keine Ermäßigungen oder Gefahrenhund-Sätze unterstellt.'
)


def handle_dog_tax_command(text, db_path, top_rows, favorites):
    command, _, value = text.partition(' ')
    command = command.split('@')[0].lower()
    selected = selected_properties(top_rows, favorites)
    if command in ('/dogtax', '/hundesteuer'):
        queue = research_queue(db_path, top_rows, favorites)
        lines = [HELP, f'\nOffen: {len(queue)} Aufgabe(n)']
        for task in queue:
            if task['kind'] == 'municipality':
                p = task['property']
                lines.append(f"📍 Gemeinde klären: {p['portal_id']} · {p.get('location') or 'Ort unbekannt'}")
            else:
                lines.append(f"📜 Satzung klären: {task['municipality_name']} ({task['municipality_key']})")
        return '\n'.join(lines)
    parts = [part.strip() for part in value.split('|')]
    try:
        if command == '/dogtax_link':
            if len(parts) != 4:
                raise ValueError('Bitte vier Felder mit | trennen. /dogtax zeigt das Format.')
            portal_id, key, name, source = parts
            matches = [p for p in selected if p['portal_id'] == portal_id]
            if len(matches) != 1:
                raise ValueError('Objekt nicht eindeutig in Top-10 oder Merkliste gefunden.')
            assign_municipality(db_path, matches[0], key, name, source)
            return f'✅ Gemeinde {name} zugeordnet. /dogtax zeigt die verbleibenden Prüfungen.'
        if command == '/dogtax_set':
            if len(parts) != 7:
                raise ValueError('Bitte sieben Felder mit | trennen. /dogtax zeigt das Format.')
            key, name, valid, model, rates, url, version = parts
            # Only selected municipalities can open a new research action.
            from dog_tax_store import database, assignment
            with database(db_path) as conn:
                keys = {(assignment(conn, p) or {}).get('municipality_key') for p in selected}
            if key not in keys:
                raise ValueError('Gemeinde zuerst einem Objekt in Top-10 oder Merkliste zuordnen.')
            if model not in ('staffel', 'alle'):
                raise ValueError('Berechnungsmodell muss staffel oder alle sein.')
            values = [Decimal(rate.strip().replace(',', '.')) for rate in rates.split(';')]
            if not values or any(not rate.is_finite() or rate < 0 or rate * 100 != (rate * 100).to_integral_value() for rate in values):
                raise ValueError('Jahressätze müssen nichtnegative Eurobeträge mit höchstens zwei Nachkommastellen sein.')
            tariff = DogTaxTariff(key, name, POSITIONAL_TIERS if model == 'staffel' else TOTAL_COUNT_TIERS,
                tuple(DogTaxTier(i + 1, int(rate * 100)) for i, rate in enumerate(values)),
                None, None if valid == '?' else date.fromisoformat(valid), version, date.today(), url)
            save_tariff(db_path, tariff)
            return f'✅ Satzung für {name} gespeichert; gilt für alle zugeordneten Objekte dieser Gemeinde.'
    except (ValueError, InvalidOperation) as exc:
        return f'⚠️ {exc}'
    return HELP
