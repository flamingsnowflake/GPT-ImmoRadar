"""Municipality tariffs and explicitly confirmed property assignments."""
import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date
from urllib.parse import urlparse

from dog_tax import DogTaxTariff, DogTaxTier, calculate_dog_tax


@contextmanager
def database(path):
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute('CREATE TABLE IF NOT EXISTS dog_tax_tariffs (municipality_key TEXT PRIMARY KEY, tariff_json TEXT NOT NULL)')
        conn.execute('CREATE TABLE IF NOT EXISTS dog_tax_assignments (portal TEXT NOT NULL, portal_id TEXT NOT NULL, location_key TEXT NOT NULL, municipality_key TEXT NOT NULL, municipality_name TEXT NOT NULL, source_url TEXT NOT NULL, PRIMARY KEY (portal, portal_id))')
        yield conn
        conn.commit()
    finally:
        conn.close()


def validate_key(key):
    if not re.fullmatch(r'\d{8}', str(key)):
        raise ValueError('Der amtliche Gemeindeschlüssel muss acht Ziffern haben.')


def validate_source(url):
    if re.fullmatch(r'telegram-upload:sha256:[0-9a-f]{64}:[A-Za-z0-9._-]{1,80}', str(url or '')):
        return
    parsed = urlparse(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Bitte die HTTPS-Quelle der zuständigen Gemeinde angeben.')


def location_key(p):
    identity = [p.get('location'), p.get('manual_latitude') or p.get('latitude'),
                p.get('manual_longitude') or p.get('longitude')]
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()


def assign_municipality(path, p, key, name, source_url):
    validate_key(key)
    validate_source(source_url)
    if not name.strip():
        raise ValueError('Der Gemeindename fehlt.')
    with database(path) as conn:
        conn.execute('INSERT OR REPLACE INTO dog_tax_assignments VALUES (?, ?, ?, ?, ?, ?)',
                     (p['portal'], p['portal_id'], location_key(p), key, name.strip(), source_url))


def save_tariff(path, tariff):
    validate_key(tariff.municipality_key)
    validate_source(tariff.source_url)
    if not tariff.source_version.strip() or not tariff.municipality_name.strip():
        raise ValueError('Gemeinde und Satzungsstand fehlen.')
    with database(path) as conn:
        conn.execute('INSERT OR REPLACE INTO dog_tax_tariffs VALUES (?, ?)',
                     (tariff.municipality_key, json.dumps(asdict(tariff), default=str, ensure_ascii=False)))


def save_assignment_and_tariff(path, property_data, tariff, municipality_source_url):
    validate_key(tariff.municipality_key)
    validate_source(municipality_source_url)
    validate_source(tariff.source_url)
    if not tariff.source_version.strip() or not tariff.municipality_name.strip():
        raise ValueError('Gemeinde und Satzungsstand fehlen.')
    assignment_values = (
        property_data['portal'], property_data['portal_id'], location_key(property_data),
        tariff.municipality_key, tariff.municipality_name.strip(), municipality_source_url,
    )
    tariff_values = (
        tariff.municipality_key,
        json.dumps(asdict(tariff), default=str, ensure_ascii=False),
    )
    with database(path) as conn:
        conn.execute('INSERT OR REPLACE INTO dog_tax_assignments VALUES (?, ?, ?, ?, ?, ?)', assignment_values)
        conn.execute('INSERT OR REPLACE INTO dog_tax_tariffs VALUES (?, ?)', tariff_values)


def load_tariff(conn, key, today=None):
    tariff = load_stored_tariff(conn, key)
    if tariff and tariff.valid_from and tariff.valid_from > (today or date.today()):
        return None
    return tariff


def load_stored_tariff(conn, key):
    row = conn.execute('SELECT tariff_json FROM dog_tax_tariffs WHERE municipality_key = ?', (key,)).fetchone()
    if not row:
        return None
    data = json.loads(row['tariff_json'])
    data['normal_dog_tiers'] = tuple(DogTaxTier(**tier) for tier in data['normal_dog_tiers'])
    data['valid_from'] = date.fromisoformat(data['valid_from']) if data['valid_from'] else None
    data['checked_on'] = date.fromisoformat(data['checked_on'])
    return DogTaxTariff(**data)


def assignment(conn, p):
    row = conn.execute('SELECT * FROM dog_tax_assignments WHERE portal = ? AND portal_id = ? AND location_key = ?',
                       (p['portal'], p['portal_id'], location_key(p))).fetchone()
    return dict(row) if row else None


def selected_properties(top_rows, favorite_rows):
    result, identities, fingerprints = [], set(), set()
    for p in [*top_rows, *favorite_rows]:
        identity = (p.get('portal'), p.get('portal_id'))
        fingerprint = (str(p.get('title') or '').casefold().strip(),
                       str(p.get('location') or '').casefold().strip(),
                       *(round(float(p[k])) if p.get(k) is not None else None for k in ('price', 'plot_area', 'living_area')))
        if identity in identities or (fingerprint[0] and fingerprint[1] and fingerprint in fingerprints):
            continue
        identities.add(identity)
        fingerprints.add(fingerprint)
        result.append(dict(p))
    return result


def research_queue(path, top_rows, favorite_rows):
    tasks, seen = [], set()
    with database(path) as conn:
        for p in selected_properties(top_rows, favorite_rows):
            assigned = assignment(conn, p)
            if assigned:
                key = assigned['municipality_key']
                if load_tariff(conn, key) is not None or key in seen:
                    continue
                seen.add(key)
                tasks.append({'kind': 'tariff', **assigned})
            else:
                tasks.append({'kind': 'municipality', 'property': p})
    return tasks


def property_tax_text(path, p, dogs=9):
    with database(path) as conn:
        assigned = assignment(conn, p)
        if not assigned:
            return '🐕 Hundesteuer: unbekannt · Gemeinde noch nicht bestätigt'
        tariff = load_tariff(conn, assigned['municipality_key'])
    if tariff is None:
        return f"🐕 Hundesteuer: unbekannt · {assigned['municipality_name']} · Satzung noch offen"
    result = calculate_dog_tax(tariff, dogs)
    euros = f'{result.annual_cents / 100:.2f}'.replace('.', ',')
    monthly = str(result.monthly_euros).replace('.', ',')
    tiers = ', '.join(f'ab Hund {t.from_dog}: {t.annual_cents / 100:.2f} €'.replace('.', ',') for t in tariff.normal_dog_tiers)
    model = 'Staffel je Hund' if tariff.calculation_model == 'positional_tiers' else 'Satz nach Gesamtzahl gilt für jeden Hund'
    return (f'🐕 {tariff.municipality_name} · {dogs} normale Hunde\n'
            f'{euros} €/Jahr · {monthly} €/Monat\n{model}: {tiers}\n'
            f'Gültig ab: {tariff.valid_from or "nicht ausgewiesen"} · {tariff.source_version}\n'
            f'Geprüft: {tariff.checked_on}\nQuelle: {tariff.source_url}\n'
            'Zusatzinformation; ohne Einfluss auf Score oder Rangfolge.')
