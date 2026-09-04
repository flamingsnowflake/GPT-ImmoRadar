"""State and deterministic extraction for the guided Telegram dog-tax workflow."""
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from dog_tax import DogTaxTariff, DogTaxTier, POSITIONAL_TIERS, TOTAL_COUNT_TIERS, calculate_dog_tax


FIELDS = ('municipality_name', 'municipality_key', 'valid_from', 'model', 'rates', 'source_version')


def new_session(property_data, property_type='house', number='new'):
    return {'property': dict(property_data), 'property_type': property_type, 'number': number,
            'stage': 'source', 'source_reference': None, 'municipality_source': None}


def _money(value):
    try:
        normalized = value.replace('.', '').replace(',', '.') if ',' in value else value
        amount = Decimal(normalized)
    except (InvalidOperation, AttributeError) as exc:
        raise ValueError('Die Steuersätze konnten nicht als Eurobeträge gelesen werden.') from exc
    if not amount.is_finite() or amount < 0 or amount * 100 != (amount * 100).to_integral_value():
        raise ValueError('Steuersätze müssen nichtnegative Eurobeträge mit höchstens zwei Nachkommastellen sein.')
    return int(amount * 100)


def extract_fields(text):
    flat = re.sub(r'\s+', ' ', text.replace('\xad', '')).strip()
    values = {}
    patterns = [
        r'(?:für\s+(?:den\s+)?)?1\.\s*Hund\D{0,25}(\d[\d.,]*)\s*(?:Euro|€)',
        r'(?:für\s+(?:den\s+)?)?2\.\s*Hund\D{0,25}(\d[\d.,]*)\s*(?:Euro|€)',
        r'(?:für\s+)?(?:jeden\s+)?weitere[nr]?\s+Hund\D{0,25}(\d[\d.,]*)\s*(?:Euro|€)',
    ]
    found = [re.search(pattern, flat, re.I) for pattern in patterns]
    if all(found):
        values['rates'] = ';'.join(str(Decimal(_money(match.group(1))) / 100).replace('.', ',') for match in found)
        values['model'] = 'staffel'
    dates = []
    for pattern in (r'gültig\s+ab\s+(\d{2}\.\d{2}\.\d{4})', r'tritt\s+am\s+(\d{2}\.\d{2}\.\d{4})\s+in\s+Kraft'):
        for match in re.findall(pattern, flat, re.I):
            try:
                dates.append(datetime.strptime(match, '%d.%m.%Y').date())
            except ValueError:
                pass
    if dates:
        values['valid_from'] = max(dates).isoformat()
    title = re.search(r'Hundesteuersatzung\s+der\s+(?:Stadt|Gemeinde)\s+([^\n(]{2,80})', text, re.I)
    if title:
        values['document_municipality'] = title.group(1).strip(' .–-')
    if re.search(r'(?:Lesefassung|Mit\s+Einarbeitung\s+der)', text, re.I):
        change = re.search(r'(\d+)\.\s*Änderungssatzung', text, re.I)
        values['source_version'] = 'Lesefassung' + (f' inkl. {change.group(1)}. Änderungssatzung' if change else '')
    elif re.search(r'Änderungssatzung', text, re.I):
        values['source_version'] = 'Änderungssatzung'
    elif re.search(r'Neufassung', text, re.I):
        values['source_version'] = 'Neufassung'
        values['document_warning'] = ('Die Quelle sieht wie eine Ausgangsfassung aus. '
                                      'Bitte auf der amtlichen Satzungsseite nach Änderungen oder einer Lesefassung suchen.')
    page = None
    page_markers = list(re.finditer(r'\[\[SEITE (\d+)\]\]', text))
    for index, match in enumerate(page_markers):
        end = page_markers[index + 1].start() if index + 1 < len(page_markers) else len(text)
        page_text = text[match.end():end]
        if re.search(r'(?:Steuersätze|1\.\s*Hund)', page_text, re.I):
            page = match.group(1)
            break
    values['citation'] = '§ Steuersätze' + (f', PDF-Seite {page}' if page else '')
    return values


def apply_automatic_results(session, municipality, source_reference, text):
    session['source_reference'] = source_reference
    session['municipality_name'] = municipality['name']
    session['municipality_key'] = municipality['key']
    session['municipality_source'] = municipality['source_url']
    session['municipality_verified'] = True
    session.update(extract_fields(text))
    document_name = session.get('document_municipality')
    if document_name:
        expected_tokens = set(re.findall(r'[a-zäöüß]{4,}', session['municipality_name'].casefold()))
        document_tokens = set(re.findall(r'[a-zäöüß]{4,}', document_name.casefold()))
        if expected_tokens and not expected_tokens.intersection(document_tokens):
            session['document_warning'] = f'Dokument nennt „{document_name}", Objekt liegt in „{session["municipality_name"]}“.'
    return next_prompt(session)


def apply_document_results(session, source_reference, text):
    session['source_reference'] = source_reference
    session.update(extract_fields(text))
    return next_prompt(session)


def next_prompt(session):
    prompts = {
        'municipality_name': 'Wie heißt die zuständige Gemeinde? Bitte nur den Gemeindenamen senden.',
        'municipality_key': 'Welchen achtstelligen amtlichen Gemeindeschlüssel zeigt das Gemeindeverzeichnis?',
        'valid_from': 'Seit wann gelten diese Sätze? Bitte als JJJJ-MM-TT senden; falls unbekannt: ?',
        'model': 'Wie wird gerechnet? Bitte unten „Staffel je Hund“ oder „Satz für alle Hunde“ wählen.',
        'rates': 'Welche normalen Jahressätze nennt die Satzung? Bitte nur die Beträge senden, z. B. 50;63;75.',
        'source_version': 'Wie lautet der Satzungsstand, z. B. „Lesefassung inkl. 1. Änderung“?',
    }
    for field in FIELDS:
        if session.get(field) in (None, ''):
            session['stage'] = field
            return prompts[field]
    session['stage'] = 'preview'
    return preview_text(session)


def accept_answer(session, text):
    stage = session.get('stage')
    value = str(text or '').strip()
    if stage == 'municipality_name':
        if not value:
            raise ValueError('Der Gemeindename darf nicht leer sein.')
        session[stage] = value
    elif stage == 'municipality_key':
        if not re.fullmatch(r'\d{8}', value):
            raise ValueError('Bitte genau acht Ziffern senden.')
        session[stage] = value
        session['municipality_source'] = f'https://www.statistikportal.de/de/gemeindeverzeichnis/{value}'
    elif stage == 'valid_from':
        if value != '?':
            date.fromisoformat(value)
        session[stage] = value
    elif stage == 'rates':
        rates = [_money(item.strip()) for item in value.split(';') if item.strip()]
        if not rates:
            raise ValueError('Bitte mindestens einen Jahressatz senden.')
        session[stage] = ';'.join(str(Decimal(rate) / 100).replace('.', ',') for rate in rates)
    elif stage == 'source_version':
        if not value:
            raise ValueError('Der Satzungsstand darf nicht leer sein.')
        session[stage] = value
    else:
        raise ValueError('Bitte eine der angezeigten Schaltflächen verwenden.')
    return next_prompt(session)


def choose_model(session, model):
    if model not in ('staffel', 'alle'):
        raise ValueError('Unbekanntes Berechnungsmodell.')
    session['model'] = model
    return next_prompt(session)


def tariff_from_session(session):
    rates = [_money(item.strip()) for item in session['rates'].split(';')]
    model = POSITIONAL_TIERS if session['model'] == 'staffel' else TOTAL_COUNT_TIERS
    return DogTaxTariff(session['municipality_key'], session['municipality_name'], model,
                        tuple(DogTaxTier(i + 1, rate) for i, rate in enumerate(rates)), None,
                        None if session['valid_from'] == '?' else date.fromisoformat(session['valid_from']),
                        session['source_version'], date.today(), session['source_reference'])


def preview_text(session):
    tariff = tariff_from_session(session)
    result = calculate_dog_tax(tariff, 9)
    rates = ' / '.join(item.strip() + ' €' for item in session['rates'].split(';'))
    model = 'Staffel je Hund' if session['model'] == 'staffel' else 'Satz nach Gesamtzahl für jeden Hund'
    source = session['source_reference']
    warnings = [session[key] for key in ('document_warning', 'existing_warning') if session.get(key)]
    warning = ''.join('\n\n⚠️ ' + item for item in warnings)
    key_status = 'amtlich geprüft' if session.get('municipality_verified') else 'manuell bestätigt'
    annual = f'{result.annual_cents / 100:.2f}'.replace('.', ',')
    monthly = str(result.monthly_euros).replace('.', ',')
    return (f'🐕 Hundesteuer prüfen\n\nObjekt: {session["property"].get("title") or session["property"]["portal_id"]}\n'
            f'📍 {session["municipality_name"]} · AGS {key_status}: {session["municipality_key"]}\n'
            f'📜 {session["source_version"]} · gültig ab {session["valid_from"]}\n'
            f'💶 {model}: {rates}\n'
            f'9 normale Hunde: {annual} €/Jahr · {monthly} €/Monat\n'
            f'Fundstelle: {session.get("citation") or "bitte in der Quelle prüfen"}\n'
            f'Satzung: {source}\nAGS-Quelle: {session["municipality_source"]}'
            f'{warning}\n\nErst „Bestätigen“ speichert die Angaben.')


def note_existing_tariff(session, existing):
    if existing is None:
        session.pop('existing_warning', None)
        return preview_text(session)
    new = tariff_from_session(session)
    old_signature = (existing.calculation_model, existing.normal_dog_tiers, existing.valid_from,
                     existing.source_version, existing.source_url)
    new_signature = (new.calculation_model, new.normal_dog_tiers, new.valid_from,
                     new.source_version, new.source_url)
    if old_signature != new_signature:
        session['existing_warning'] = (f'Für {existing.municipality_name} ist bereits „{existing.source_version}“ gespeichert. '
                                       'Bestätigen ersetzt diesen Tarif für alle zugeordneten Objekte.')
    else:
        session.pop('existing_warning', None)
    return preview_text(session)
