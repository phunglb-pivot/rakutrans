"""
Unit tests for PptxTranslator (Microsoft PowerPoint .pptx).
"""

import tempfile
import unittest
from pathlib import Path
from pptx import Presentation
from pptx.util import Inches

from rakutrans.core.config import AppConfig
from rakutrans.parsers.pptx_parser import PptxTranslator
from rakutrans.llm.translation_cache import TranslationCache


class MockLLMManager:
    def __init__(self):
        self.call_count = 0

    def translate_batch(self, texts, target_lang=None, *args, **kwargs):
        self.call_count += 1
        tgt = target_lang or "target"
        return [f"[{tgt}] {t}" for t in texts]


class TestPptxTranslator(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_pptx_path = Path(self.temp_dir.name) / "presentation.pptx"

        prs = Presentation()
        # Slide 1: Title slide
        blank_slide_layout = prs.slide_layouts[6]
        slide = prs.slides.add_slide(blank_slide_layout)

        txBox = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1))
        tf = txBox.text_frame
        p = tf.paragraphs[0]
        p.text = "Quarterly Business Review"

        p2 = tf.add_paragraph()
        p2.text = "Performance and Outlook"

        prs.save(str(self.test_pptx_path))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_inspect_file(self):
        info = PptxTranslator.inspect_file(str(self.test_pptx_path))
        self.assertEqual(info["type"], "pptx")
        self.assertEqual(info["slides"], 1)
        self.assertGreater(info["shapes"], 0)
        self.assertGreater(info["word_count"], 3)
        self.assertGreater(info["translatable_segments"], 1)

    def test_translation_flow(self):
        config = AppConfig()
        mock_llm = MockLLMManager()
        cache = TranslationCache(db_path=Path(self.temp_dir.name) / "cache.db")
        translator = PptxTranslator(config, mock_llm, cache=cache)

        out_file = translator.process_file(
            file_path=str(self.test_pptx_path),
            target_lang="Vietnamese"
        )

        out_path = Path(out_file)
        self.assertTrue(out_path.exists())
        self.assertEqual(out_path.name, "presentation_vi.pptx")

        translated_prs = Presentation(str(out_path))
        all_texts = []
        for slide in translated_prs.slides:
            for shape in slide.shapes:
                if shape.has_text_frame:
                    for p in shape.text_frame.paragraphs:
                        all_texts.append(p.text)

        joined = " ".join(all_texts)
        self.assertIn("[Vietnamese] Quarterly Business Review", joined)
        self.assertIn("[Vietnamese] Performance and Outlook", joined)

    def test_options_cache_isolation_and_group_shapes_notes(self):
        from rakutrans.core.config import TranslationOptions

        pptx_path = Path(self.temp_dir.name) / "grouped.pptx"
        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        grp = slide.shapes.add_group_shape()
        tb = grp.shapes.add_textbox(Inches(1), Inches(1), Inches(3), Inches(1))
        tb.text_frame.text = "Inside group"
        slide.notes_slide.notes_text_frame.text = "Speaker note line"
        prs.save(str(pptx_path))

        config = AppConfig()
        mock_llm = MockLLMManager()
        cache = TranslationCache(db_path=Path(self.temp_dir.name) / "pptx_cache.db")
        translator = PptxTranslator(config, mock_llm, cache=cache)

        out1 = translator.process_file(file_path=str(pptx_path), target_lang="Vietnamese")
        calls_after_1 = mock_llm.call_count
        self.assertGreater(calls_after_1, 0)

        out_prs = Presentation(out1)
        grp_texts = [
            p.text
            for s in out_prs.slides[0].shapes
            if hasattr(s, "shapes")
            for sub in s.shapes
            for p in sub.text_frame.paragraphs
        ]
        self.assertIn("[Vietnamese] Inside group", grp_texts)
        self.assertIn("[Vietnamese] Speaker note line", out_prs.slides[0].notes_slide.notes_text_frame.text)

        # Different TranslationOptions must NOT reuse previous cache
        translator.process_file(
            file_path=str(pptx_path),
            target_lang="Vietnamese",
            options=TranslationOptions(append_original_words=True),
        )
        self.assertGreater(mock_llm.call_count, calls_after_1)

    def test_pptx_inline_style_preservation_and_reordering(self):
        from pptx.dml.color import RGBColor

        pptx_path = Path(self.temp_dir.name) / "inline_styles.pptx"
        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        tb = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(1))
        p = tb.text_frame.paragraphs[0]
        r0 = p.add_run()
        r0.text = "Critical"
        r0.font.bold = True
        r1 = p.add_run()
        r1.text = " warning"
        r1.font.color.rgb = RGBColor(0xCC, 0x00, 0x00)
        prs.save(str(pptx_path))

        class _ReorderLLM:
            def translate_batch(self, texts, *args, **kwargs):
                return ["<s1>Cảnh báo </s1><s0>nghiêm trọng</s0>" for _ in texts]

        cache = TranslationCache(db_path=Path(self.temp_dir.name) / "pptx_inline_cache.db")
        translator = PptxTranslator(AppConfig(), _ReorderLLM(), cache=cache)
        out_path = translator.process_file(file_path=str(pptx_path), target_lang="Vietnamese")

        out_prs = Presentation(out_path)
        res_p = out_prs.slides[0].shapes[0].text_frame.paragraphs[0]
        self.assertEqual(res_p.text, "Cảnh báo nghiêm trọng")
        self.assertFalse(bool(res_p.runs[0].font.bold))
        self.assertEqual(str(res_p.runs[0].font.color.rgb), "CC0000")
        self.assertTrue(bool(res_p.runs[1].font.bold))

    def test_pptx_line_breaks_no_x000b_and_merged_table_dedup(self):
        pptx_path = Path(self.temp_dir.name) / "breaks_merged.pptx"
        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[6])

        # Paragraph with <a:br> line break
        tb = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1))
        p = tb.text_frame.paragraphs[0]
        p.text = "First line\nSecond line"

        # Table with horizontally merged cells
        tbl_shape = slide.shapes.add_table(2, 2, Inches(1), Inches(2.5), Inches(4), Inches(1.5))
        tbl = tbl_shape.table
        tbl.cell(0, 0).text = "Merged Header"
        tbl.cell(0, 0).merge(tbl.cell(0, 1))
        tbl.cell(1, 0).text = "Cell A"
        tbl.cell(1, 1).text = "Cell B"
        prs.save(str(pptx_path))

        seen_texts = []

        class _SpyLLM:
            def translate_batch(self, texts, *args, **kwargs):
                seen_texts.extend(texts)
                return [f"TR:{t}" for t in texts]

        info = PptxTranslator.inspect_file(str(pptx_path))
        self.assertEqual(info["translatable_segments"], 4)

        cache = TranslationCache(db_path=Path(self.temp_dir.name) / "pptx_br_cache.db")
        translator = PptxTranslator(AppConfig(), _SpyLLM(), cache=cache)
        out = translator.process_file(file_path=str(pptx_path), target_lang="Vietnamese")

        # Merged header must be sent once, not duplicated
        self.assertEqual(seen_texts.count("Merged Header"), 1)

        out_prs = Presentation(out)
        out_p = out_prs.slides[0].shapes[0].text_frame.paragraphs[0]
        self.assertNotIn("_x000B_", out_p.text)
        self.assertEqual(out_p.text, "TR:First line\x0bSecond line")
        self.assertEqual(out_prs.slides[0].shapes[1].table.cell(0, 0).text, "TR:Merged Header")


if __name__ == "__main__":
    unittest.main()
