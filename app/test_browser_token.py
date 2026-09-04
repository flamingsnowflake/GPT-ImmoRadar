import os
import tempfile
from pathlib import Path
from unittest.mock import patch
import browser_enrich_server as server


def test_canonical_token_is_reloaded_on_each_request():
    with tempfile.TemporaryDirectory() as directory:
        fixture = Path(directory) / 'token'
        with patch.object(server, 'TOKEN_FILE', fixture), \
             patch.dict(os.environ, {'BROWSER_ENRICH_TOKEN': 'ignored-test-token'}):
            fixture.write_text('first-test-token\n', encoding='utf-8')
            assert server.load_token() == 'first-test-token'
            fixture.write_text('rotated-test-token\n', encoding='utf-8')
            assert server.load_token() == 'rotated-test-token'
