import json
import unittest
from datetime import date

import telegram_commands
from dog_tax import DogTaxTariff, DogTaxTier, POSITIONAL_TIERS
from dog_tax_store import validate_source
from dog_tax_wizard import (
    accept_answer,
    apply_automatic_results,
    extract_fields,
    new_session,
    preview_text,
    note_existing_tariff,
    tariff_from_session,
)
from municipality_lookup import lookup_municipality


ZERBST_TEXT = """
[[SEITE 1]]
Neufassung der Hundesteuersatzung der Stadt Zerbst/Anhalt
Lesefassung mit Einarbeitung der 1. Änderungssatzung
(gültig ab 01.01.2018)
[[SEITE 3]]
§ 5 Steuersätze
Die Steuer beträgt jährlich:
a) für den 1. Hund 50,00 Euro
b) für den 2. Hund 63,00 Euro
c) für jeden weiteren Hund 75,00 Euro
"""


class DogTaxWizardTest(unittest.TestCase):
    def property(self):
        return dict(portal='test', portal_id='7dc93f81-92a3-419f-a5ad-c79c29b9da45',
                    property_type='house', title='Haus in Lindau', location='Lindau (39264)',
                    latitude=52.0383, longitude=12.1045)

    def test_zerbst_document_is_extracted_and_calculated(self):
        fields = extract_fields(ZERBST_TEXT)
        self.assertEqual(fields['rates'], '50;63;75')
        self.assertEqual(fields['valid_from'], '2018-01-01')
        self.assertEqual(fields['model'], 'staffel')
        self.assertEqual(fields['source_version'], 'Lesefassung inkl. 1. Änderungssatzung')
        self.assertEqual(fields['citation'], '§ Steuersätze, PDF-Seite 3')

        session = new_session(self.property())
        result = apply_automatic_results(session, {
            'key': '15082430', 'name': 'Zerbst/Anhalt',
            'source_url': 'https://www.statistikportal.de/de/gemeindeverzeichnis/15082430',
        }, 'https://www.stadt-zerbst.de/lesefassung.pdf', ZERBST_TEXT)
        self.assertEqual(session['stage'], 'preview')
        self.assertIn('638,00 €/Jahr', result)
        self.assertIn('53,17 €/Monat', result)
        self.assertEqual(tariff_from_session(session).municipality_key, '15082430')

    def test_missing_values_are_requested_one_at_a_time(self):
        session = new_session(self.property())
        session['source_reference'] = 'https://example.invalid/satzung.pdf'
        session['stage'] = 'municipality_name'
        prompt = accept_answer(session, 'Zerbst/Anhalt')
        self.assertEqual(session['stage'], 'municipality_key')
        self.assertIn('achtstelligen', prompt)

    def test_upload_reference_is_valid_source(self):
        validate_source('telegram-upload:sha256:' + 'a' * 64 + ':satzung.pdf')

    def test_keyboards_include_skip_and_confirmation(self):
        session = new_session(self.property())
        self.assertIn('überspringen', str(telegram_commands.dog_tax_prompt_keyboard(session)))
        session.update(stage='preview')
        self.assertIn('Bestätigen', str(telegram_commands.dog_tax_prompt_keyboard(session)))

    def test_existing_different_tariff_is_shown_before_replacement(self):
        session = new_session(self.property())
        apply_automatic_results(session, {
            'key': '15082430', 'name': 'Zerbst/Anhalt',
            'source_url': 'https://www.statistikportal.de/de/gemeindeverzeichnis/15082430',
        }, 'https://www.stadt-zerbst.de/lesefassung.pdf', ZERBST_TEXT)
        old = DogTaxTariff('15082430', 'Zerbst/Anhalt', POSITIONAL_TIERS,
                           (DogTaxTier(1, 3000),), None, None, 'Alte Fassung',
                           date.today(), 'https://example.invalid/alt.pdf')
        self.assertIn('ersetzt diesen Tarif', note_existing_tariff(session, old))

    def test_spatial_match_is_verified_against_official_directory(self):
        overpass = json.dumps({'elements': [{'tags': {
            'admin_level': '8', 'de:amtlicher_gemeindeschluessel': '15082430',
            'name': 'Zerbst/Anhalt',
        }}]}).encode()
        calls = []

        def read(request, timeout=30):
            calls.append(request.full_url)
            return overpass if len(calls) == 1 else b'AGS 15082430 Zerbst/Anhalt'

        result = lookup_municipality(self.property(), read=read)
        self.assertEqual(result['key'], '15082430')
        self.assertEqual(result['name'], 'Zerbst/Anhalt')
        self.assertIn('/15082430', result['source_url'])


if __name__ == '__main__':
    unittest.main()
