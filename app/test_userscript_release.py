import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.3.3"
CANONICAL = ROOT / "userscripts" / "immobilien-energy.user.js"
COMPATIBLE = ROOT / "userscripts" / "immobilienmonitor-browser-energy.user.js"
ARCHIVE = (
    ROOT
    / "userscripts"
    / "archive"
    / f"Immobilienmonitor-Browser-Energie-{VERSION}.zip"
)
ARCHIVE_MEMBER = f"Immobilienmonitor-Browser-Energie-{VERSION}.user.js"


class UserscriptReleaseTest(unittest.TestCase):
    def test_both_userscripts_keep_mobile_immowelt_panel_clear(self):
        for path in (CANONICAL, COMPATIBLE):
            source = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertIn(f"// @version      {VERSION}", source)
                self.assertIn('info.portal === "immowelt"', source)
                self.assertIn('"(max-width: 768px)"', source)
                self.assertIn(
                    '"calc(96px + env(safe-area-inset-bottom, 0px))"',
                    source,
                )
                self.assertIn('mobileImmowelt ? "12px" : "18px"', source)
                self.assertIn('window.addEventListener(', source)
                self.assertIn('"resize"', source)

    def test_release_archive_contains_exact_canonical_source(self):
        if not ARCHIVE.exists():
            self.skipTest(
                "private release archive is not part of public snapshots"
            )

        with zipfile.ZipFile(ARCHIVE) as release:
            self.assertEqual(release.namelist(), [ARCHIVE_MEMBER])
            self.assertEqual(release.read(ARCHIVE_MEMBER), CANONICAL.read_bytes())


if __name__ == "__main__":
    unittest.main()
