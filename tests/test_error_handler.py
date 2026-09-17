"""
Unit tests for error_handler module.
Validates diagnostic classification for Quota, Auth, File Lock, Network, and Cancellation errors.
"""

import unittest
from error_handler import diagnose_error, DiagnosticInfo
from i18n import I18nManager


class TestErrorHandler(unittest.TestCase):

    def setUp(self):
        self.i18n = I18nManager("vi")

    def test_quota_error_diagnosis(self):
        err = Exception("429 Resource has been exhausted (check quota)")
        diag = diagnose_error(err, self.i18n)

        self.assertEqual(diag.category, "quota")
        self.assertTrue(diag.can_retry)
        self.assertTrue(diag.requires_settings)
        self.assertIn("429", diag.title)

    def test_auth_error_diagnosis(self):
        err = Exception("401 Unauthorized: API_KEY_INVALID provided")
        diag = diagnose_error(err, self.i18n)

        self.assertEqual(diag.category, "auth")
        self.assertTrue(diag.requires_settings)
        self.assertIn("API", diag.title)

    def test_file_lock_diagnosis(self):
        err = PermissionError("[Errno 13] Permission denied: 'sample.xlsx'")
        diag = diagnose_error(err, self.i18n)

        self.assertEqual(diag.category, "file_lock")
        self.assertTrue(diag.can_retry)
        self.assertFalse(diag.requires_settings)
        self.assertIn("khóa", diag.title.lower())

    def test_network_timeout_diagnosis(self):
        err = ConnectionError("Failed to establish a new connection: Connection timed out")
        diag = diagnose_error(err, self.i18n)

        self.assertEqual(diag.category, "network")
        self.assertTrue(diag.can_retry)
        self.assertIn("mạng", diag.title.lower())

    def test_cancellation_diagnosis(self):
        err = InterruptedError("Translation was cancelled by user.")
        diag = diagnose_error(err, self.i18n)

        self.assertEqual(diag.category, "cancelled")
        self.assertIn("hủy", diag.title.lower())


if __name__ == "__main__":
    unittest.main()
