"""
Unit tests for PDF document parsing, inspection, and translation via flow conversion pipeline:
    PDF -> DOCX -> Translate -> PDF.
Verifies that PDF translation converts to .docx internally for paragraph flow integrity,
translates via DocxTranslator, and outputs a clean, readable final PDF document.
"""

import tempfile
import unittest
from pathlib import Path

import pypdf
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, PageBreak
from reportlab.lib.styles import getSampleStyleSheet

from config import AppConfig
from pdf_parser import (
    PdfTranslator,
    _should_translate,
)
from translator_registry import TranslatorRegistry


class MockLLMManager:
    def __init__(self, prefix="[Translated] "):
        self.prefix = prefix

    def translate_batch(self, texts, target_lang=None, *args, **kwargs):
        return [f"{self.prefix}{t}" for t in texts]


def _create_sample_pdf(file_path: Path, pages_content: list[list[str]]):
    """Helper to generate a real valid PDF with multiple pages and paragraphs."""
    doc = SimpleDocTemplate(str(file_path), pagesize=letter)
    styles = getSampleStyleSheet()
    story = []

    for page_idx, paragraphs in enumerate(pages_content):
        if page_idx > 0:
            story.append(PageBreak())
        for p in paragraphs:
            story.append(Paragraph(p, styles["Normal"]))

    doc.build(story)


class TestPdfParser(unittest.TestCase):

    def setUp(self):
        self.config = AppConfig()
        self.mock_llm = MockLLMManager()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.temp_dir.name)

        # Create a sample multi-page PDF
        self.sample_pdf = self.tmp_path / "sample.pdf"
        pages = [
            ["Introduction to Project", "This is the first section of the document."],
            ["Architecture Overview", "The system consists of frontend and backend modules.", "123.45"],
        ]
        _create_sample_pdf(self.sample_pdf, pages)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_should_translate(self):
        self.assertTrue(_should_translate("Hello world"))
        self.assertTrue(_should_translate("Tiếng Việt"))
        self.assertTrue(_should_translate("日本語"))
        self.assertFalse(_should_translate(""))
        self.assertFalse(_should_translate("   "))
        self.assertFalse(_should_translate("12345"))
        self.assertFalse(_should_translate("99.99"))
        self.assertFalse(_should_translate("$100"))
        self.assertFalse(_should_translate("---"))

    def test_inspect_file(self):
        info = PdfTranslator.inspect_file(str(self.sample_pdf))
        self.assertEqual(info["type"], "pdf")
        self.assertEqual(info["page_count"], 2)
        self.assertTrue(info["word_count"] > 10)
        self.assertTrue(info["char_count"] > 50)
        self.assertTrue(info["translatable_segments"] >= 3)

    def test_inspect_nonexistent_file(self):
        info = PdfTranslator.inspect_file("nonexistent_file.pdf")
        self.assertEqual(info["type"], "pdf")
        self.assertIn("error", info)

    def test_translator_registry_integration(self):
        self.assertTrue(TranslatorRegistry.is_supported(".pdf"))
        self.assertTrue(TranslatorRegistry.is_supported(self.sample_pdf))
        cls = TranslatorRegistry.get_translator_class(".pdf")
        self.assertEqual(cls, PdfTranslator)

        inspect_res = TranslatorRegistry.inspect(str(self.sample_pdf))
        self.assertEqual(inspect_res["type"], "pdf")
        self.assertEqual(inspect_res["page_count"], 2)

    def test_pipeline_pdf_to_docx_translate_to_pdf(self):
        """Verifies full pipeline: PDF -> DOCX -> Translate -> PDF."""
        translator = PdfTranslator(self.config, self.mock_llm)
        progress_calls = []

        def callback(cur, total, msg):
            progress_calls.append((cur, total, msg))

        out_path = translator.process_file(
            file_path=str(self.sample_pdf),
            target_lang="Tiếng Việt (Vietnamese)",
            progress_callback=callback,
        )

        out_file = Path(out_path)
        self.assertTrue(out_file.exists())
        # Output must be a final PDF document
        self.assertTrue(out_file.name.endswith(".pdf"))
        self.assertTrue(len(progress_calls) > 0)

        # Verify translated PDF contains translated content
        reader = pypdf.PdfReader(str(out_file))
        self.assertTrue(len(reader.pages) >= 1)
        full_text = " ".join((p.extract_text() or "") for p in reader.pages)
        self.assertIn("[Translated]", full_text)
        self.assertIn("Introduction to Project", full_text)

    def test_cancel_translation(self):
        """Verifies that cancel method correctly aborts translation."""
        translator = PdfTranslator(self.config, self.mock_llm)
        translator.cancel()

        with self.assertRaises(InterruptedError):
            translator.process_file(
                file_path=str(self.sample_pdf),
                target_lang="Tiếng Việt",
            )


if __name__ == "__main__":
    unittest.main()
