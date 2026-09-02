import sqlite3
import unittest
from unittest.mock import patch

from browser_enrich_server import (
    update_database_with_retry,
)


class BrowserDatabaseRetryTests(
    unittest.TestCase
):

    def test_locked_database_is_retried(self):

        expected = {
            "database_status": "enriched",
        }

        with patch(
            "browser_enrich_server.update_database",
            side_effect=[
                sqlite3.OperationalError(
                    "database is locked"
                ),
                expected,
            ],
        ) as update_mock, patch(
            "browser_enrich_server.time.sleep"
        ) as sleep_mock:

            result = update_database_with_retry(
                {"portal_id": "test"},
                attempts=3,
                delay=0.01,
            )

        self.assertEqual(
            result,
            expected,
        )

        self.assertEqual(
            update_mock.call_count,
            2,
        )

        sleep_mock.assert_called_once_with(
            0.01
        )

    def test_non_lock_error_is_not_retried(self):

        with patch(
            "browser_enrich_server.update_database",
            side_effect=sqlite3.OperationalError(
                "no such table: properties"
            ),
        ) as update_mock, patch(
            "browser_enrich_server.time.sleep"
        ) as sleep_mock:

            with self.assertRaises(
                sqlite3.OperationalError
            ):
                update_database_with_retry(
                    {"portal_id": "test"},
                    attempts=3,
                    delay=0.01,
                )

        self.assertEqual(
            update_mock.call_count,
            1,
        )

        sleep_mock.assert_not_called()

    def test_lock_error_is_raised_after_last_attempt(self):

        with patch(
            "browser_enrich_server.update_database",
            side_effect=sqlite3.OperationalError(
                "database table is locked"
            ),
        ) as update_mock, patch(
            "browser_enrich_server.time.sleep"
        ) as sleep_mock:

            with self.assertRaises(
                sqlite3.OperationalError
            ):
                update_database_with_retry(
                    {"portal_id": "test"},
                    attempts=2,
                    delay=0.01,
                )

        self.assertEqual(
            update_mock.call_count,
            2,
        )

        sleep_mock.assert_called_once_with(
            0.01
        )


if __name__ == "__main__":
    unittest.main()
