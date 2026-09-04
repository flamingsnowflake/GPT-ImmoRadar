import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from contextlib import closing
from unittest.mock import patch

from coordinate_parser import parse_coordinates
from test_local_changes import telegram


class CoordinateFormatsTests(unittest.TestCase):
    def test_decimal_and_dms(self):
        for value in ['51.562111, 11.555417', '51,562111; 11,555417',
                      '51°33\'43.6"N 11°33\'19.5"E',
                      '51°33′43,6″n 11°33′19,5″e']:
            lat, lon = parse_coordinates(value)
            self.assertAlmostEqual(lat, 51.562111, places=5)
            self.assertAlmostEqual(lon, 11.555417, places=5)

    def test_hemispheres_and_boundaries(self):
        self.assertEqual(parse_coordinates('11°30\'0"W 51°30\'0"S'), (-51.5, -11.5))
        self.assertEqual(parse_coordinates('90°0\'0"N 180°0\'0"E'), (90, 180))

    def test_invalid_dms_is_rejected(self):
        for value in ['91°0\'0"N 11°0\'0"E', '90°0\'1"N 11°0\'0"E',
                      '51°60\'0"N 11°0\'0"E', '51°0\'60"N 11°0\'0"E',
                      '51°0\'0"N 11°0\'0"S', '51°0\'0"N 11°0\'0"E junk',
                      '51N 11E', '91, 11']:
            self.assertIsNone(parse_coordinates(value), value)


class LocalityAdvanceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = str(Path(self.directory.name) / 'test.sqlite3')
        with closing(sqlite3.connect(self.db, isolation_level=None)) as con:
            con.execute('CREATE TABLE properties (id INTEGER PRIMARY KEY, portal TEXT, portal_id TEXT, rating TEXT, geo_precision TEXT, is_ko INTEGER, last_seen TEXT, score_details TEXT)')
            for i, name in enumerate(['current', 'skipped', 'next']):
                con.execute('INSERT INTO properties VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                            (i + 1, 'test', name, 'provisional', 'locality', 0, str(i), '{}'))
        telegram.LOCALITY_LAB.reset()
        telegram.PENDING_COORDINATES.clear()
        self.addCleanup(telegram.LOCALITY_LAB.reset)
        self.addCleanup(telegram.PENDING_COORDINATES.clear)
        telegram.LOCALITY_LAB.track(123, {'portal': 'test', 'portal_id': 'current'})

    def refresh(self, failure=None):
        with patch.object(telegram, 'DB_PATH', self.db), \
             patch.object(telegram, 'telegram_api', side_effect=failure) as api, \
             patch.object(telegram, 'incomplete_overview_text', return_value='overview'), \
             patch.object(telegram, 'incomplete_overview_keyboard', return_value={}):
            changed = telegram.refresh_active_locality_lab()
        return changed, api

    def test_current_remains_even_if_newer_items_exist(self):
        changed, api = self.refresh()
        self.assertFalse(changed)
        api.assert_not_called()

    def test_blacklist_advances_and_respects_skips(self):
        telegram.LOCALITY_LAB.skipped.add('skipped')
        with closing(sqlite3.connect(self.db, isolation_level=None)) as con:
            con.execute("UPDATE properties SET rating='blacklisted' WHERE portal_id='current'")
        changed, api = self.refresh()
        self.assertTrue(changed)
        self.assertEqual(telegram.LOCALITY_LAB.session['portal_id'], 'next')
        self.assertEqual(api.call_args.args[1]['message_id'], 123)
        with closing(sqlite3.connect(self.db, isolation_level=None)) as con:
            self.assertEqual(con.execute("SELECT rating FROM properties WHERE portal_id='skipped'").fetchone()[0], 'provisional')

    def test_empty_queue_finishes_and_clears_pending(self):
        telegram.PENDING_COORDINATES['chat'] = {'number': 'iwl', 'portal_id': 'current'}
        with closing(sqlite3.connect(self.db, isolation_level=None)) as con:
            con.execute('DELETE FROM properties')
        changed, api = self.refresh()
        self.assertTrue(changed)
        self.assertIsNone(telegram.LOCALITY_LAB.session)
        self.assertNotIn('chat', telegram.PENDING_COORDINATES)
        self.assertIn('Keine weiteren Lagen', api.call_args.args[1]['text'])

    def test_failed_edit_can_retry(self):
        with closing(sqlite3.connect(self.db, isolation_level=None)) as con:
            con.execute("DELETE FROM properties WHERE portal_id='current'")
        changed, _ = self.refresh(RuntimeError('network'))
        self.assertFalse(changed)
        self.assertEqual(telegram.LOCALITY_LAB.session['portal_id'], 'current')
        self.assertTrue(self.refresh()[0])


if __name__ == '__main__':
    unittest.main()
