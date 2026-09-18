"""
Unit tests for TranslatorRegistry and Strategy Pattern architecture.
"""

import tempfile
import unittest
from pathlib import Path

from config import AppConfig
from translator_registry import TranslatorRegistry
from excel_parser import ExcelTranslator
from markdown_parser import MarkdownTranslator
from docx_parser import DocxTranslator
from pptx_parser import PptxTranslator
from data_parser import CsvTranslator, JsonTranslator, TextTranslator


class MockLLMManager:
    def translate_batch(self, texts, *args, **kwargs):
        return [f"[Translated] {t}" for t in texts]


class TestTranslatorRegistry(unittest.TestCase):

    def test_supported_extensions(self):
        exts = TranslatorRegistry.get_supported_extensions()
        expected = [".csv", ".docx", ".json", ".md", ".pptx", ".tsv", ".txt", ".xlsx"]
        for exp in expected:
            self.assertIn(exp, exts)

    def test_is_supported(self):
        self.assertTrue(TranslatorRegistry.is_supported("test.xlsx"))
        self.assertTrue(TranslatorRegistry.is_supported("path/to/doc.docx"))
        self.assertTrue(TranslatorRegistry.is_supported("presentation.pptx"))
        self.assertTrue(TranslatorRegistry.is_supported("data.csv"))
        self.assertTrue(TranslatorRegistry.is_supported("data.tsv"))
        self.assertTrue(TranslatorRegistry.is_supported("locale.json"))
        self.assertTrue(TranslatorRegistry.is_supported("notes.txt"))
        self.assertTrue(TranslatorRegistry.is_supported("README.md"))

        self.assertFalse(TranslatorRegistry.is_supported("binary.exe"))
        self.assertFalse(TranslatorRegistry.is_supported("image.png"))

    def test_get_translator_class(self):
        self.assertIs(TranslatorRegistry.get_translator_class(".xlsx"), ExcelTranslator)
        self.assertIs(TranslatorRegistry.get_translator_class(".md"), MarkdownTranslator)
        self.assertIs(TranslatorRegistry.get_translator_class(".docx"), DocxTranslator)
        self.assertIs(TranslatorRegistry.get_translator_class(".pptx"), PptxTranslator)
        self.assertIs(TranslatorRegistry.get_translator_class(".csv"), CsvTranslator)
        self.assertIs(TranslatorRegistry.get_translator_class(".tsv"), CsvTranslator)
        self.assertIs(TranslatorRegistry.get_translator_class(".json"), JsonTranslator)
        self.assertIs(TranslatorRegistry.get_translator_class(".txt"), TextTranslator)

        with self.assertRaises(ValueError):
            TranslatorRegistry.get_translator_class(".unknown")

    def test_create_translator(self):
        config = AppConfig()
        mock_llm = MockLLMManager()

        t_docx = TranslatorRegistry.create_translator("file.docx", config, mock_llm)
        self.assertIsInstance(t_docx, DocxTranslator)

        t_json = TranslatorRegistry.create_translator("file.json", config, mock_llm)
        self.assertIsInstance(t_json, JsonTranslator)

    def test_inspect_nonexistent_file(self):
        res = TranslatorRegistry.inspect("nonexistent_file_path.docx")
        self.assertIn("error", res)


if __name__ == "__main__":
    unittest.main()
