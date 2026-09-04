import tempfile
import unittest
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from dog_tax import DogTaxTariff, DogTaxTier, POSITIONAL_TIERS
from dog_tax_store import (assign_municipality, save_assignment_and_tariff, save_tariff,
                           property_tax_text, research_queue)
from dog_tax_workflow import handle_dog_tax_command


class DogTaxStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = str(Path(self.directory.name) / 'test.sqlite3')
        self.p = dict(portal='test', portal_id='one', title='Synthetic home', location='Exampletown', price=120000, plot_area=2000, living_area=120)
        self.other = dict(self.p, portal_id='two', title='Another home')
        self.tariff = DogTaxTariff('12345678', 'Exampletown', POSITIONAL_TIERS,
                                  (DogTaxTier(1, 4800), DogTaxTier(2, 8000), DogTaxTier(3, 10500)),
                                  None, date(2024, 1, 1), 'Example ordinance', date.today(), 'https://municipality.example/tax')

    def assign(self, p):
        assign_municipality(self.db, p, '12345678', 'Exampletown', 'https://municipality.example/area')

    def test_union_deduplicates_properties_and_municipalities(self):
        self.assertEqual(len(research_queue(self.db, [self.p], [self.p, self.other])), 2)
        for p in (self.p, self.other):
            self.assign(p)
        tasks = research_queue(self.db, [self.p], [self.p, self.other])
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]['kind'], 'tariff')

    def test_unknown_is_not_zero_and_shared_tariff_removes_tasks(self):
        self.assign(self.p)
        self.assertIn('unbekannt', property_tax_text(self.db, self.p))
        save_tariff(self.db, self.tariff)
        self.assign(self.other)
        self.assertEqual(research_queue(self.db, [self.p], [self.other]), [])
        for p in (self.p, self.other):
            result = property_tax_text(self.db, p)
            self.assertIn('863,00 €/Jahr', result)
            self.assertIn('71,92 €/Monat', result)
            self.assertIn('https://municipality.example/tax', result)
            self.assertIn('2024-01-01', result)

    def test_no_unselected_tasks_are_created(self):
        self.assign(self.other)
        self.assertEqual(research_queue(self.db, [], []), [])
        error = handle_dog_tax_command('/dogtax_link two | 12345678 | Exampletown | https://municipality.example', self.db, [self.p], [])
        self.assertIn('nicht eindeutig', error)

    def test_coordinate_changes_invalidate_assignment(self):
        self.assign(self.p)
        save_tariff(self.db, self.tariff)
        changed = dict(self.p, manual_latitude=52, manual_longitude=11)
        self.assertIn('Gemeinde noch nicht bestätigt', property_tax_text(self.db, changed))

    def test_future_rate_does_not_apply_early(self):
        self.assign(self.p)
        save_tariff(self.db, replace(self.tariff, valid_from=date.today() + timedelta(days=30)))
        self.assertIn('unbekannt', property_tax_text(self.db, self.p))

    def test_guided_confirmation_saves_assignment_and_tariff_together(self):
        save_assignment_and_tariff(
            self.db, self.p, self.tariff,
            'https://www.statistikportal.de/de/gemeindeverzeichnis/12345678',
        )
        self.assertIn('863,00 €/Jahr', property_tax_text(self.db, self.p))

    def test_command_validates_and_calculates_household_tiers(self):
        self.assign(self.p)
        command = '/dogtax_set 12345678 | Exampletown | 2024-01-01 | alle | 120;132;144 | https://municipality.example/tax | Example ordinance'
        self.assertIn('✅', handle_dog_tax_command(command, self.db, [self.p], []))
        self.assertIn('1296,00 €/Jahr', property_tax_text(self.db, self.p))
        self.assertIn('⚠️', handle_dog_tax_command(command.replace('120;132;144', '-1'), self.db, [self.p], []))
