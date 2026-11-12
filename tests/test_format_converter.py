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


if __name__ == "__main__":
    unittest.main()

