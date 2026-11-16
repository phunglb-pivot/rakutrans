"""
Unit tests for the Format Converter module.
Verifies bidirectional conversions between Excel, CSV, Word, PowerPoint, Markdown, and PDF.
"""

import tempfile
import unittest
from pathlib import Path

import openpyxl
import docx
from pptx import Presentation
from reportlab.pdfgen import canvas

from format_converter import (
    excel_to_markdown,
    markdown_to_excel,
    excel_to_csv,
    csv_to_excel,
    csv_to_markdown,
    markdown_to_csv,
    docx_to_markdown,
    markdown_to_docx,
    docx_to_text,
    pptx_to_markdown,
    pptx_to_text,
    text_to_markdown,
    pdf_to_text,
    pdf_to_markdown,
    pdf_to_docx,
    get_convert_options,
    convert_file_direct,
)


class TestFormatConverter(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_excel_to_markdown_and_back(self):
        xlsx_file = self.tmp_path / "test.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Sales"
        ws.append(["Item", "Price", "Qty"])
        ws.append(["Apple", 10.5, 3])
        ws.append(["Banana", 5.0, 10])
        wb.save(str(xlsx_file))

        md_file = excel_to_markdown(str(xlsx_file))
        self.assertTrue(Path(md_file).exists())
        content = Path(md_file).read_text(encoding="utf-8")
        self.assertIn("| Item | Price | Qty |", content)
        self.assertIn("Apple", content)

        # Convert back
        new_xlsx = markdown_to_excel(str(md_file))
        self.assertTrue(Path(new_xlsx).exists())
        wb2 = openpyxl.load_workbook(str(new_xlsx))
        self.assertIn("Sales", wb2.sheetnames)
        ws2 = wb2["Sales"]
        self.assertEqual(ws2.cell(row=2, column=1).value, "Apple")

    def test_excel_and_csv_bidirectional(self):
        xlsx_file = self.tmp_path / "data.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Name", "Age"])
        ws.append(["Alice", 30])
        wb.save(str(xlsx_file))

        csv_file = excel_to_csv(str(xlsx_file))
        self.assertTrue(Path(csv_file).exists())
        content = Path(csv_file).read_text(encoding="utf-8-sig")
        self.assertIn("Alice", content)

        new_xlsx = csv_to_excel(str(csv_file))
        self.assertTrue(Path(new_xlsx).exists())

    def test_csv_and_markdown_bidirectional(self):
        csv_file = self.tmp_path / "table.csv"
        csv_file.write_text("ID,Name,Role\n1,Bob,Engineer\n2,Carol,Designer\n", encoding="utf-8")

        md_file = csv_to_markdown(str(csv_file))
        self.assertTrue(Path(md_file).exists())
        md_content = Path(md_file).read_text(encoding="utf-8")
        self.assertIn("| ID | Name | Role |", md_content)
        self.assertIn("Engineer", md_content)

        new_csv = markdown_to_csv(str(md_file))
        self.assertTrue(Path(new_csv).exists())
        csv_content = Path(new_csv).read_text(encoding="utf-8-sig")
        self.assertIn("Engineer", csv_content)

    def test_docx_and_markdown_bidirectional(self):
        doc_file = self.tmp_path / "sample.docx"
        doc = docx.Document()
        doc.add_heading("Project Report", level=1)
        doc.add_paragraph("This is the executive summary.")
        doc.save(str(doc_file))

        md_file = docx_to_markdown(str(doc_file))
        self.assertTrue(Path(md_file).exists())
        content = Path(md_file).read_text(encoding="utf-8")
        self.assertIn("Project Report", content)
        self.assertIn("executive summary", content)

        new_docx = markdown_to_docx(str(md_file))
        self.assertTrue(Path(new_docx).exists())

    def test_docx_to_text(self):
        doc_file = self.tmp_path / "sample2.docx"
        doc = docx.Document()
        doc.add_paragraph("Paragraph one.")
        doc.add_paragraph("Paragraph two.")
        doc.save(str(doc_file))

        txt_file = docx_to_text(str(doc_file))
        self.assertTrue(Path(txt_file).exists())
        content = Path(txt_file).read_text(encoding="utf-8")
        self.assertIn("Paragraph one.", content)
        self.assertIn("Paragraph two.", content)

    def test_pptx_to_markdown_and_text(self):
        pptx_file = self.tmp_path / "pres.pptx"
        prs = Presentation()
        blank_slide = prs.slide_layouts[6]
        slide = prs.slides.add_slide(blank_slide)
        tx_box = slide.shapes.add_textbox(100, 100, 300, 100)
        tx_box.text_frame.text = "Slide 1 Content"
        prs.save(str(pptx_file))

        md_file = pptx_to_markdown(str(pptx_file))
        self.assertTrue(Path(md_file).exists())
        self.assertIn("Slide 1 Content", Path(md_file).read_text(encoding="utf-8"))

        txt_file = pptx_to_text(str(pptx_file))
        self.assertTrue(Path(txt_file).exists())
        self.assertIn("Slide 1 Content", Path(txt_file).read_text(encoding="utf-8"))

    def test_text_to_markdown(self):
        txt_file = self.tmp_path / "notes.txt"
        txt_file.write_text("Note item 1\nNote item 2\n", encoding="utf-8")

        md_file = text_to_markdown(str(txt_file))
        self.assertTrue(Path(md_file).exists())
        self.assertIn("Note item 1", Path(md_file).read_text(encoding="utf-8"))

    def test_pdf_conversions(self):
        pdf_file = self.tmp_path / "doc.pdf"
        c = canvas.Canvas(str(pdf_file))
        c.drawString(100, 700, "Header Title In PDF")
        c.drawString(100, 650, "Body paragraph content inside test PDF.")
        c.save()

        # PDF -> Text
        txt_file = pdf_to_text(str(pdf_file))
        self.assertTrue(Path(txt_file).exists())
        self.assertIn("Header Title In PDF", Path(txt_file).read_text(encoding="utf-8"))

        # PDF -> Markdown
        md_file = pdf_to_markdown(str(pdf_file))
        self.assertTrue(Path(md_file).exists())
        self.assertIn("Header Title In PDF", Path(md_file).read_text(encoding="utf-8"))

        # PDF -> Word (.docx)
        docx_file = pdf_to_docx(str(pdf_file))
        self.assertTrue(Path(docx_file).exists())

    def test_get_convert_options(self):
        self.assertEqual(get_convert_options("pdf"), ["docx", "md", "txt"])
        self.assertEqual(get_convert_options(".xlsx"), ["csv", "md"])
        self.assertEqual(get_convert_options("csv"), ["xlsx", "md"])
        self.assertEqual(get_convert_options(".docx"), ["pdf", "md", "txt"])
        self.assertEqual(get_convert_options("pptx"), ["md", "txt"])
        self.assertEqual(get_convert_options("md"), ["docx", "xlsx", "csv"])
        self.assertEqual(get_convert_options("txt"), ["md", "docx"])
        self.assertEqual(get_convert_options("unknown"), [])

    def test_convert_file_direct(self):
        csv_file = self.tmp_path / "data.csv"
        csv_file.write_text("A,B\n1,2\n", encoding="utf-8")
        out_xlsx = convert_file_direct(str(csv_file), "xlsx")
        self.assertTrue(Path(out_xlsx).exists())
        self.assertTrue(out_xlsx.endswith(".xlsx"))

        # Test DOCX -> PDF conversion
        import docx
        doc = docx.Document()
        doc.add_heading("Test Docx to PDF", 0)
        doc.add_paragraph("Paragraph content.")
        test_docx = self.tmp_path / "sample_convert.docx"
        doc.save(str(test_docx))
        out_pdf = convert_file_direct(str(test_docx), "pdf")
        self.assertTrue(Path(out_pdf).exists())
        self.assertTrue(out_pdf.endswith(".pdf"))

    def test_markdown_excel_roundtrip_preserves_pipes_dashes_zeros_formulas_and_prose(self):
        src_xlsx = self.tmp_path / "edge.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "DataSheet"
        ws.append(["ID", "Expr", "Note", "Calc"])
        ws.append(["001", "A | B", "---", "=1+1"])
        ws.append(["0912345678", "1.2.3", "ok", "10.50"])
        wb.save(str(src_xlsx))
        wb.close()

        md_file = excel_to_markdown(str(src_xlsx))
        md_text = Path(md_file).read_text(encoding="utf-8")
        self.assertIn("=1+1", md_text)
        self.assertIn("A \\| B", md_text)

        rt_xlsx = markdown_to_excel(md_file)
        wb_rt = openpyxl.load_workbook(rt_xlsx)
        self.assertEqual(wb_rt.sheetnames, ["DataSheet"])
        ws_rt = wb_rt["DataSheet"]
        self.assertEqual(ws_rt.cell(2, 1).value, "001")
        self.assertEqual(ws_rt.cell(2, 2).value, "A | B")
        self.assertEqual(ws_rt.cell(2, 3).value, "---")
        self.assertEqual(ws_rt.cell(2, 4).value, "=1+1")
        self.assertEqual(ws_rt.cell(3, 1).value, "0912345678")
        self.assertEqual(ws_rt.cell(3, 2).value, "1.2.3")
        wb_rt.close()

        # Markdown with prose, ### heading, list, code fence should not be dropped in Excel
        prose_md = self.tmp_path / "prose.md"
        prose_md.write_text(
            "# Report\n\n### Overview\n\nIntro paragraph line.\n\n- Bullet one\n\n```bash\n# comment\necho ok\n```\n",
            encoding="utf-8",
        )
        prose_xlsx = markdown_to_excel(str(prose_md))
        wb_p = openpyxl.load_workbook(prose_xlsx)
        values = [r[0] for r in wb_p.active.iter_rows(values_only=True) if r and r[0] is not None]
        wb_p.close()
        joined = "\n".join(str(v) for v in values)
        self.assertIn("Overview", joined)
        self.assertIn("Intro paragraph line.", joined)
        self.assertIn("- Bullet one", joined)
        self.assertIn("echo ok", joined)

    def test_csv_to_excel_preserves_leading_zeros(self):
        csv_file = self.tmp_path / "ids.csv"
        csv_file.write_text("ID,Phone,Amount\n001,0912345678,12.50\n", encoding="utf-8")
        xlsx_file = csv_to_excel(str(csv_file))
        wb = openpyxl.load_workbook(xlsx_file)
        ws = wb.active
        self.assertEqual(ws.cell(2, 1).value, "001")
        self.assertEqual(ws.cell(2, 2).value, "0912345678")
        self.assertEqual(ws.cell(2, 3).value, 12.5)
        wb.close()

    def test_docx_to_markdown_preserves_table_order_and_txt_to_docx_is_literal(self):
        doc_path = self.tmp_path / "ordered.docx"
        doc = docx.Document()
        doc.add_paragraph("Before table")
        tbl = doc.add_table(rows=2, cols=2)
        tbl.cell(0, 0).text = "ColA"
        tbl.cell(0, 1).text = "ColB"
        tbl.cell(1, 0).text = "X | Y"
        tbl.cell(1, 1).text = "---"
        doc.add_paragraph("After table")
        doc.save(str(doc_path))

        md_out = docx_to_markdown(str(doc_path))
        md_content = Path(md_out).read_text(encoding="utf-8")
        self.assertLess(md_content.index("Before table"), md_content.index("ColA"))
        self.assertLess(md_content.index("ColA"), md_content.index("After table"))

        # Plain text -> DOCX must NOT turn '#' or '| a | b |' into headings/tables
        txt_path = self.tmp_path / "raw.txt"
        txt_path.write_text("# Not Heading\n\n| a | b |", encoding="utf-8")
        out_docx = convert_file_direct(str(txt_path), "docx")
        d2 = docx.Document(out_docx)
        self.assertEqual(len(d2.tables), 0)
        self.assertEqual([p.text for p in d2.paragraphs], ["# Not Heading", "| a | b |"])

    def test_docx_to_pdf_reportlab_xml_escape_and_table_images(self):
        from unittest.mock import patch
        import pypdf
        import format_converter
        from PIL import Image

        img_path = self.tmp_path / "cell.png"
        Image.new("RGB", (40, 40), color="blue").save(img_path)

        doc_path = self.tmp_path / "xml_markup.docx"
        doc = docx.Document()
        doc.add_paragraph("<br>Literal tag <tag>hello</tag> & ampersand")
        tbl = doc.add_table(rows=1, cols=2)
        tbl.cell(0, 0).text = "Row <1> & <br>"
        run = tbl.cell(0, 1).paragraphs[0].add_run()
        run.add_picture(str(img_path))
        doc.save(str(doc_path))

        with patch.object(format_converter, "_find_soffice_binary", return_value=None):
            pdf_out = format_converter.docx_to_pdf(str(doc_path), str(self.tmp_path / "fallback.pdf"))

        reader = pypdf.PdfReader(pdf_out)
        text = "\n".join(p.extract_text() or "" for p in reader.pages)
        self.assertIn("<tag>hello</tag>", text)
        self.assertIn("<br>Literal tag", text)
        self.assertIn("Row <1> & <br>", text)

    def test_convertible_extensions_registry_and_structured_pdf_to_markdown(self):
        import glob
        from format_converter import get_convertible_extensions, is_convert_supported

        exts = get_convertible_extensions()
        self.assertIn(".pdf", exts)
        self.assertIn(".xlsx", exts)
        self.assertNotIn(".json", exts)
        self.assertFalse(is_convert_supported("locale.json"))
        self.assertTrue(is_convert_supported("report.pdf"))

        # Verify structured PDF -> Markdown on real Japanese multi-page PDF with tables if present
        sample_pdfs = glob.glob("examples/*.pdf")
        if sample_pdfs:
            md_path = pdf_to_markdown(sample_pdfs[0], str(self.tmp_path / "example.md"))
            md_text = Path(md_path).read_text(encoding="utf-8")
            self.assertIn("# 【社外向け】", md_text)
            self.assertIn("映画『アイアンマン』で、主人公トニー・スタークがAIアシスタントの「J.A.R.V.I.S.（ジャーヴィス）」", md_text)
            self.assertIn("| --- |", md_text)


if __name__ == "__main__":
    unittest.main()

