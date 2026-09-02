import subprocess
import sys
import unittest


class BrowserConfigScopeTests(unittest.TestCase):

    def test_import_does_not_change_global_config_dir(self):

        code = r'''
from config_loader import CONFIG

before = CONFIG.config_dir

import browser_enrich_server  # noqa: F401

after = CONFIG.config_dir

if after != before:
    raise SystemExit(
        f"config_dir changed on import: {before!r} -> {after!r}"
    )
'''

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                code,
            ],
            capture_output=True,
            text=True,
        )

        self.assertEqual(
            result.returncode,
            0,
            msg=(
                result.stdout
                + result.stderr
            ),
        )


if __name__ == "__main__":
    unittest.main()
