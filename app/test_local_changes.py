"""Regression coverage for the two production-only fixes (issue #12)."""
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import monitor
import incomplete_workflow
import user_status
with tempfile.TemporaryDirectory() as temporary:
    with patch.object(monitor, 'DB_PATH', str(Path(temporary) / 'test.sqlite3')), \
         patch('user_status.ensure_user_status_table'):
        import telegram_commands as telegram
telegram.ensure_user_status_table = user_status.ensure_user_status_table


class LocalChangesTests(unittest.TestCase):
    def test_unlet_house_is_not_blacklisted(self):
        with patch.object(monitor.CONFIG, 'blacklist_terms', return_value=['vermietet']):
            for text in ['Aktuelle Nutzung: Nicht vermietet', 'NICHT   VERMIETET']:
                self.assertFalse(monitor.is_blacklisted(text, property_type='house'))

    def test_actual_rental_and_other_terms_remain_blacklisted(self):
        with patch.object(monitor.CONFIG, 'blacklist_terms', return_value=['vermietet', 'erbbaurecht']):
            for text in ['Das Haus ist vermietet', 'Nicht vermietet, aber Erbbaurecht',
                         'Haupthaus nicht vermietet. Einliegerwohnung vermietet.']:
                self.assertTrue(monitor.is_blacklisted(text, property_type='house'))

    def test_skip_only_hides_current_item_for_this_pass(self):
        telegram.SKIPPED_LOCALITY_LAB.clear()
        rows = [{'portal_id': 'one'}, {'portal_id': 'two'}]
        callback = {'id': 'callback', 'data': 'iwl_skip:one',
                    'message': {'message_id': 123, 'chat': {'id': 'test'}}}
        with patch.object(telegram, 'TELEGRAM_CHAT_ID', 'test'), \
             patch.object(telegram, 'telegram_api'), \
             patch.object(telegram, 'incomplete_locality_rows', return_value=rows), \
             patch.object(telegram, 'incomplete_locality_text', return_value='next') as card, \
             patch.object(telegram, 'incomplete_locality_keyboard', return_value={}):
            telegram.handle_callback(callback)
            self.assertEqual(telegram.SKIPPED_LOCALITY_LAB, {'one'})
            card.assert_called_once_with(rows[1], 1, 1)
            self.assertEqual(len(rows), 2)
        telegram.SKIPPED_LOCALITY_LAB.clear()

    def test_reopening_locality_starts_new_pass(self):
        telegram.SKIPPED_LOCALITY_LAB.add('one')
        callback = {'id': 'callback', 'data': 'iw:locality',
                    'message': {'message_id': 123, 'chat': {'id': 'test'}}}
        with patch.object(telegram, 'TELEGRAM_CHAT_ID', 'test'), \
             patch.object(telegram, 'telegram_api'), \
             patch.object(telegram, 'incomplete_first_locality', return_value=(None, 0)), \
             patch.object(telegram, 'incomplete_overview_text', return_value='done'), \
             patch.object(telegram, 'incomplete_overview_keyboard', return_value={}):
            telegram.handle_callback(callback)
        self.assertEqual(telegram.SKIPPED_LOCALITY_LAB, set())


if __name__ == '__main__':
    unittest.main()
