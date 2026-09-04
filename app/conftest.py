"""Run application tests against isolated state and repository configuration."""
import os
import tempfile
from pathlib import Path

for key in ('IMAP_HOST', 'IMAP_USER', 'IMAP_PASSWORD', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID'):
    os.environ[key] = 'test'

import monitor
from config_loader import CONFIG

_state = tempfile.TemporaryDirectory(prefix='immoradar-tests-')
monitor.DB_PATH = str(Path(_state.name) / 'test.sqlite3')
CONFIG.config_dir = str(Path(__file__).resolve().parent.parent / 'config')
os.environ['PYTHONPATH'] = str(Path(__file__).resolve().parent)
monitor.get_db().close()

# These are operator-run scripts, not isolated unit tests (network/mail/CLI input).
collect_ignore = ['noise_all_test.py', 'test_imap.py', 'test_immowelt.py']


def pytest_sessionfinish(session, exitstatus):
    _state.cleanup()
