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
    def test_help_is_complete_and_fits_one_telegram_message(self):
        commands = (
            '/help',
            '/start',
            '/find',
            '/search',
            '/property',
            '/inspect',
            '/merkliste',
            '/favorites',
            '/top3house',
            '/top10house',
            '/top3house_ohne',
            '/top10house_ohne',
            '/top3land',
            '/incomplete',
            '/coords',
            '/coords-auto',
            '/condition',
            '/buildability',
            '/hundesteuer',
            '/dogtax',
            '/dogtax_link',
            '/dogtax_set',
            '/blacklist',
            '/purge',
        )

        for command in commands:
            with self.subTest(command=command):
                self.assertIn(command, telegram.HELP_TEXT)

        self.assertLessEqual(
            len(telegram.HELP_TEXT),
            4096,
        )

    def test_help_command_sends_canonical_help_text(self):
        message = {
            'chat': {'id': 'test'},
            'text': '/help',
        }

        with patch.object(telegram, 'TELEGRAM_CHAT_ID', 'test'), \
             patch.object(telegram, 'send_message') as send:
            telegram.handle_message(message)

        send.assert_called_once_with(
            telegram.HELP_TEXT,
        )

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

    def test_condition_no_interest_saves_and_advances(self):
        callback = {
            'id': 'callback',
            'data': 'iw_nope:ca:house-1',
            'message': {
                'message_id': 123,
                'chat': {'id': 'test'},
            },
        }
        with patch.object(telegram, 'TELEGRAM_CHAT_ID', 'test'), \
             patch.object(telegram, 'telegram_api'), \
             patch.object(telegram, 'set_user_status') as save, \
             patch.object(telegram, 'clear_information_requested') as clear, \
             patch.object(telegram, '_render_lab_queue') as render:
            telegram.handle_callback(callback)

        save.assert_called_once_with(
            telegram.DB_PATH,
            'house-1',
            'not_interested',
        )
        clear.assert_called_once_with(
            telegram.DB_PATH,
            'house-1',
        )
        render.assert_called_once_with(
            callback['message'],
            'condition',
            False,
            '🙈 Kein Interesse gespeichert.\n\n',
        )

    def test_locality_information_requested_saves_and_advances(self):
        callback = {
            'id': 'callback',
            'data': 'iwq:add:l:house-2',
            'message': {
                'message_id': 123,
                'chat': {'id': 'test'},
            },
        }
        with patch.object(telegram, 'TELEGRAM_CHAT_ID', 'test'), \
             patch.object(telegram, 'telegram_api'), \
             patch.object(telegram, 'mark_information_requested') as save, \
             patch.object(telegram, '_render_lab_queue') as render:
            telegram.handle_callback(callback)

        save.assert_called_once_with(
            telegram.DB_PATH,
            'house-2',
            'locality',
        )
        render.assert_called_once_with(
            callback['message'],
            'locality',
            False,
            '📩 Information angefragt.\n\n',
        )

    def test_chance_card_uses_location_waitlist_keyboard(self):
        chance = {
            'portal_id': 'house-3',
            'property_type': 'house',
            'max_reachable_score': 88,
        }

        with patch.object(telegram, 'get_chance_rows', return_value=[chance]), \
             patch.object(telegram, 'format_property_card', return_value='card'), \
             patch.object(telegram, 'property_action_keyboard', return_value={}) as keyboard, \
             patch.object(telegram, 'send_message'):
            telegram.send_chances('house', [])

        keyboard.assert_called_once_with(
            'house-3',
            'house',
            'chance',
        )

    def test_chance_location_requested_saves_without_replacing_card(self):
        callback = {
            'id': 'callback',
            'data': 'cwl:a:house-3:house',
            'message': {
                'message_id': 123,
                'chat': {'id': 'test'},
            },
        }
        keyboard_value = {'inline_keyboard': []}

        with patch.object(telegram, 'TELEGRAM_CHAT_ID', 'test'), \
             patch.object(telegram, 'telegram_api') as api, \
             patch.object(telegram, 'mark_information_requested') as save, \
             patch.object(telegram, 'property_action_keyboard', return_value=keyboard_value):
            telegram.handle_callback(callback)

        save.assert_called_once_with(
            telegram.DB_PATH,
            'house-3',
            'locality',
        )
        self.assertTrue(
            any(
                call.args[0] == 'editMessageReplyMarkup'
                for call in api.call_args_list
            )
        )

    def test_chance_keyboard_shows_requested_location_state(self):
        with patch.object(telegram, 'is_favorite', return_value=False), \
             patch.object(telegram, 'get_user_status', return_value='active'), \
             patch.object(telegram, 'waiting_portal_ids', return_value={'house-3'}):
            keyboard = telegram.property_action_keyboard(
                'house-3',
                'house',
                'chance',
            )

        buttons = [
            button
            for row in keyboard['inline_keyboard']
            for button in row
        ]
        self.assertIn(
            {
                'text': '↩️ Lage wieder offen',
                'callback_data': 'cwl:o:house-3:house',
            },
            buttons,
        )


if __name__ == '__main__':
    unittest.main()
