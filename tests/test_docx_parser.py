"""
Unit tests for DocxTranslator (Microsoft Word .docx).
"""

import tempfile
import unittest
from pathlib import Path
from docx import Document

from config import AppConfig
from docx_parser import DocxTranslator
from translation_cache import TranslationCache


class MockLLMManager:
    def __init__(self):
        self.call_count = 0

    def translate_batch(self, texts, target_lang=None, *args, **kwargs):
        self.call_count += 1
        tgt = target_lang or "target"
        return [f"[{tgt}] {t}" for t in texts]


class TestDocxTranslator(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_docx_path = Path(self.temp_dir.name) / "sample.docx"

        # Create a real docx document with paragraphs and tables
        doc = Document()
        doc.add_heading("User Guide", level=1)
        doc.add_paragraph("Welcome to the application user guide.")
        doc.add_paragraph("Please read all instructions carefully.")

        # Add table
        table = doc.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "Feature"
        table.cell(0, 1).text = "Status"
        table.cell(1, 0).text = "Login Authentication"
        table.cell(1, 1).text = "Ready"

        doc.save(str(self.test_docx_path))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_inspect_file(self):
        info = DocxTranslator.inspect_file(str(self.test_docx_path))
        self.assertEqual(info["type"], "docx")
        self.assertGreater(info["paragraphs"], 0)
        self.assertEqual(info["tables"], 1)
        self.assertGreater(info["word_count"], 5)
        self.assertGreater(info["translatable_segments"], 3)

    def test_translation_flow(self):
        config = AppConfig()
        mock_llm = MockLLMManager()
        cache = TranslationCache(db_path=Path(self.temp_dir.name) / "cache.db")
        translator = DocxTranslator(config, mock_llm, cache=cache)

        out_file = translator.process_file(
            file_path=str(self.test_docx_path),
            target_lang="Vietnamese"
        )

        out_path = Path(out_file)
        self.assertTrue(out_path.exists())
        self.assertEqual(out_path.name, "sample_vi.docx")

        # Verify translated content in docx
        translated_doc = Document(str(out_path))
        all_texts = [p.text for p in translated_doc.paragraphs]
        for t in translated_doc.tables:
            for row in t.rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        all_texts.append(p.text)

        joined = " ".join(all_texts)
        self.assertIn("[Vietnamese] User Guide", joined)
        self.assertIn("[Vietnamese] Welcome to the application user guide.", joined)
        self.assertIn("[Vietnamese] Login Authentication", joined)

    def test_caching(self):
        config = AppConfig()
        mock_llm = MockLLMManager()
        cache = TranslationCache(db_path=Path(self.temp_dir.name) / "cache2.db")
        translator = DocxTranslator(config, mock_llm, cache=cache)

        # 1st run: fills cache
        translator.process_file(file_path=str(self.test_docx_path), target_lang="Vietnamese")
        first_calls = mock_llm.call_count
        self.assertGreater(first_calls, 0)

        # 2nd run: should hit cache, call_count should not increase
        translator.process_file(file_path=str(self.test_docx_path), target_lang="Vietnamese")
        self.assertEqual(mock_llm.call_count, first_calls)

        # 3rd run with different options: MUST NOT poison/reuse default cache
        from config import TranslationOptions
        translator.process_file(
            file_path=str(self.test_docx_path),
            target_lang="Vietnamese",
            options=TranslationOptions(append_original_words=True),
        )
        self.assertGreater(mock_llm.call_count, first_calls)

    def test_hyperlinks_nested_tables_and_textboxes_translated(self):
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn

        doc_path = Path(self.temp_dir.name) / "complex.docx"
        doc = Document()

        # Paragraph with <w:hyperlink>
        p = doc.add_paragraph("Prefix ")
        hl = OxmlElement("w:hyperlink")
        r = OxmlElement("w:r")
        t = OxmlElement("w:t")
        t.text = "Click here"
        r.append(t)
        hl.append(r)
        p._p.append(hl)
        p.add_run(" suffix")

        # Nested table inside outer table
        outer = doc.add_table(rows=1, cols=1)
        inner = outer.cell(0, 0).add_table(rows=1, cols=1)
        inner.cell(0, 0).text = "Nested cell text"

        doc.save(str(doc_path))

        config = AppConfig()
        mock_llm = MockLLMManager()
        cache = TranslationCache(db_path=Path(self.temp_dir.name) / "cache_complex.db")
        translator = DocxTranslator(config, mock_llm, cache=cache)

        out_file = translator.process_file(file_path=str(doc_path), target_lang="Vietnamese")
        out_doc = Document(out_file)

        # Hyperlink text must not be duplicated untranslated after translation
        self.assertEqual(out_doc.paragraphs[0].text, "[Vietnamese] Prefix Click here suffix")
        nested_text = out_doc.tables[0].cell(0, 0).tables[0].cell(0, 0).text
        self.assertEqual(nested_text, "[Vietnamese] Nested cell text")

    def test_inline_style_preservation_reordering_and_type3_coalescing(self):
        from docx.shared import RGBColor
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn

        doc_path = Path(self.temp_dir.name) / "inline_styles.docx"
        doc = Document()

        # Paragraph 0: Mixed bold + normal red -> reordered grammar in translation
        p0 = doc.add_paragraph()
        r0 = p0.add_run("Important")
        r0.bold = True
        r1 = p0.add_run(" notice")
        r1.font.color.rgb = RGBColor(0xFF, 0x00, 0x00)

        # Paragraph 1: Uniform runs differing only in Type3 (N 0 R) font names -> 0 inline tags
        p1 = doc.add_paragraph()
        for idx, ch in enumerate(["A", "B", "C"]):
            r = p1.add_run(ch)
            rPr = r._r.get_or_add_rPr()
            rFonts = OxmlElement("w:rFonts")
            rFonts.set(qn("w:ascii"), f"Type3 ({idx + 10} 0 R)")
            rPr.append(rFonts)

        # Paragraph 2: Mixed styles where LLM drops tags -> safe fallback without data loss
        p2 = doc.add_paragraph()
        ra = p2.add_run("Bold")
        ra.bold = True
        p2.add_run(" tail")

        doc.save(str(doc_path))

        seen_inputs = []

        class _InlineMockLLM:
            def translate_batch(self, texts, *args, **kwargs):
                seen_inputs.extend(texts)
                out = []
                for t in texts:
                    if "<s0>Important</s0>" in t:
                        # Reorder <s1> before <s0>
                        out.append("<s1>Thông báo </s1><s0>quan trọng</s0>")
                    elif "<s0>Bold</s0>" in t:
                        # Drop tags on purpose
                        out.append("Đậm đuôi")
                    else:
                        out.append(f"TR:{t}")
                return out

        cache = TranslationCache(db_path=Path(self.temp_dir.name) / "inline_cache.db")
        translator = DocxTranslator(AppConfig(), _InlineMockLLM(), cache=cache)
        out_path = translator.process_file(file_path=str(doc_path), target_lang="Vietnamese")

        # Type3-only font diffs must NOT inject <s0> tags
        self.assertIn("ABC", seen_inputs)
        self.assertFalse(any("<s0>A" in s for s in seen_inputs))

        out_doc = Document(out_path)
        res_p0 = out_doc.paragraphs[0]
        self.assertEqual(res_p0.text, "Thông báo quan trọng")
        # Slot 0 now has non-bold red style from group 1; slot 1 now has bold style from group 0
        self.assertFalse(bool(res_p0.runs[0].bold))
        self.assertEqual(str(res_p0.runs[0].font.color.rgb), "FF0000")
        self.assertTrue(bool(res_p0.runs[1].bold))

        self.assertEqual(out_doc.paragraphs[1].text, "TR:ABC")
        self.assertEqual(out_doc.paragraphs[2].text, "Đậm đuôi")


if __name__ == "__main__":
    unittest.main()
