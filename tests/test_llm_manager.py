"""
Unit tests for LLM Manager prompt construction, JSON cleaning, and batching.
"""

import unittest
from config import TranslationOptions
from llm_manager import build_system_prompt, clean_json_text


class TestLLMManager(unittest.TestCase):

    def test_build_system_prompt_options(self):
        # Basic options
        opts = TranslationOptions(
            keep_it_terms=True,
            append_original_words=True,
            custom_context="Rule: preserve sku codes"
        )
        # Test new target_lang signature
        prompt = build_system_prompt("Vietnamese", opts)
        self.assertIn("Vietnamese", prompt)
        self.assertIn("KEEP SPECIALIZED TERMS UNTRANSLATED", prompt)
        self.assertIn("APPEND ORIGINAL SOURCE WORDS", prompt)
        self.assertIn("Rule: preserve sku codes", prompt)

        # Test legacy signature compatibility
        legacy_prompt = build_system_prompt("Japanese", "Vietnamese", opts)
        self.assertIn("Vietnamese", legacy_prompt)
        self.assertIn("KEEP SPECIALIZED TERMS UNTRANSLATED", legacy_prompt)

    def test_clean_json_text(self):
        # Raw json
        raw = '["Xin chào", "Tạm biệt"]'
        self.assertEqual(clean_json_text(raw), raw)

        # Wrapped in markdown json fence
        fenced = '```json\n["Xin chào", "Tạm biệt"]\n```'
        self.assertEqual(clean_json_text(fenced), raw)

        # Wrapped in generic markdown fence with surrounding comments
        messy = 'Here is the translated result:\n```\n["A", "B"]\n```\nHope that helps!'
        self.assertEqual(clean_json_text(messy), '["A", "B"]')

        # Array with surrounding text but no fence
        bare_messy = 'Output: ["Alpha", "Beta"] done.'
        self.assertEqual(clean_json_text(bare_messy), '["Alpha", "Beta"]')


if __name__ == "__main__":
    unittest.main()
