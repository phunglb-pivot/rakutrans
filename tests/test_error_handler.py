"""
Unit tests for error_handler module.
Validates diagnostic classification for Quota, Auth, File Lock, Network, and Cancellation errors.
"""

import unittest
from error_handler import diagnose_error
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

    def test_structured_llm_error_classification_without_text_keywords(self):
        from llm_manager import LLMError

        auth_err = LLMError("Upstream failure", status_code=401)
        self.assertEqual(diagnose_error(auth_err, self.i18n).category, "auth")

        quota_err = LLMError("Slow down", status_code=429)
        self.assertEqual(diagnose_error(quota_err, self.i18n).category, "quota")

        fmt_err = LLMError("Output cut off", is_format_error=True)
        self.assertEqual(diagnose_error(fmt_err, self.i18n).category, "format")

        billing_err = LLMError(
            "402 RESOURCE_EXHAUSTED: Your prepayment credits are depleted.",
            status_code=402,
            error_status="RESOURCE_EXHAUSTED",
        )
        billing_diag = diagnose_error(billing_err, self.i18n)
        self.assertEqual(billing_diag.category, "quota")
        self.assertTrue(billing_diag.requires_settings)
        self.assertIn("402", billing_diag.message)
        self.assertNotIn("429", billing_diag.title)


if __name__ == "__main__":
    unittest.main()
