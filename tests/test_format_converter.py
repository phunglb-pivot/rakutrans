"""
Unit tests for format_converter.py
Tests bi-directional conversion between Excel (.xlsx) and Markdown (.md).
"""

import tempfile
import unittest
from pathlib import Path
import openpyxl

from format_converter import (
    excel_to_markdown,
    markdown_to_excel,
    csv_to_excel,
    excel_to_csv,
    csv_to_markdown,
    markdown_to_csv,
    docx_to_markdown,
    markdown_to_docx,
    docx_to_text,
    pptx_to_markdown,
    pptx_to_text,
    text_to_markdown,
    convert_translated_output,
    get_convert_options,
    convert_file_direct
)


class TestFormatConverter(unittest.TestCase):

    def test_excel_to_markdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            xlsx_path = Path(tmpdir) / "test.xlsx"
            md_path = Path(tmpdir) / "test.md"

            # Create test Excel file with 2 sheets
            wb = openpyxl.Workbook()
            ws1 = wb.active
            ws1.title = "Overview"
            ws1.append(["Header A", "Header B", "Header C"])
            ws1.append(["Row 1", "Value 1", 100])
            ws1.append(["Row 2", "Multi\nLine", 200])

            ws2 = wb.create_sheet(title="Details")
            ws2.append(["ID", "Description"])
            ws2.append(["D-01", "Detailed info"])

            wb.save(xlsx_path)

            # Convert
            out = excel_to_markdown(str(xlsx_path), str(md_path))
            self.assertEqual(out, str(md_path))
            self.assertTrue(md_path.exists())

            with open(md_path, "r", encoding="utf-8") as f:
                content = f.read()

            self.assertIn("## Overview", content)
            self.assertIn("## Details", content)
            self.assertIn("| Header A | Header B | Header C |", content)
            self.assertIn("| --- | --- | --- |", content)
            self.assertIn("| Row 1 | Value 1 | 100 |", content)
            self.assertIn("Multi<br>Line", content)
            self.assertIn("| D-01 | Detailed info |", content)

    def test_markdown_to_excel(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            md_path = Path(tmpdir) / "test.md"
            xlsx_path = Path(tmpdir) / "test.xlsx"

            md_content = (
                "# Document Title\n\n"
                "## Section 1\n\n"
                "| Item | Price | Quantity |\n"
                "| --- | --- | --- |\n"
                "| Apple | 1.5 | 10 |\n"
                "| Orange | 2.0 | 5 |\n\n"
                "## Section 2\n\n"
                "| User | Role |\n"
                "| --- | --- |\n"
                "| Alice | Admin |\n"
                "| Bob | Editor |\n"
            )
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(md_content)

            # Convert
            out = markdown_to_excel(str(md_path), str(xlsx_path))
            self.assertEqual(out, str(xlsx_path))
            self.assertTrue(xlsx_path.exists())

            # Read back workbook
            wb = openpyxl.load_workbook(str(xlsx_path))
            self.assertIn("Section 1", wb.sheetnames)
            self.assertIn("Section 2", wb.sheetnames)

            ws1 = wb["Section 1"]
            # Header check
            self.assertEqual(ws1.cell(row=3, column=1).value, "Item")
            self.assertEqual(ws1.cell(row=3, column=2).value, "Price")
            # Data check
            self.assertEqual(ws1.cell(row=4, column=1).value, "Apple")
            self.assertEqual(ws1.cell(row=4, column=2).value, 1.5)
            self.assertEqual(ws1.cell(row=4, column=3).value, 10)

    def test_excel_and_csv_bidirectional(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            xlsx_path = Path(tmpdir) / "data.xlsx"
            csv_path = Path(tmpdir) / "data.csv"

            # 1. Create Excel
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Sales"
            ws.append(["Product", "Revenue", "Units"])
            ws.append(["Laptop", 1200.5, 3])
            ws.append(["Mouse", 25.0, 15])
            wb.save(xlsx_path)

            # 2. Excel -> CSV
            out_csv = excel_to_csv(str(xlsx_path), str(csv_path))
            self.assertEqual(out_csv, str(csv_path))
            self.assertTrue(csv_path.exists())

            with open(csv_path, "r", encoding="utf-8-sig") as f:
                lines = [line.strip() for line in f if line.strip()]
            self.assertEqual(len(lines), 3)
            self.assertIn("Product,Revenue,Units", lines[0])

            # 3. CSV -> Excel
            new_xlsx = Path(tmpdir) / "from_csv.xlsx"
            out_xlsx = csv_to_excel(str(csv_path), str(new_xlsx))
            self.assertEqual(out_xlsx, str(new_xlsx))
            self.assertTrue(new_xlsx.exists())

            wb2 = openpyxl.load_workbook(str(new_xlsx))
            ws2 = wb2.active
            self.assertEqual(ws2.cell(row=1, column=1).value, "Product")
            self.assertEqual(ws2.cell(row=2, column=1).value, "Laptop")
            self.assertEqual(ws2.cell(row=2, column=2).value, 1200.5)
            self.assertEqual(ws2.cell(row=2, column=3).value, 3)

    def test_csv_and_markdown_bidirectional(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "table.csv"
            md_path = Path(tmpdir) / "table.md"

            with open(csv_path, "w", encoding="utf-8") as f:
                f.write("Name,Age,City\nAlice,30,Tokyo\nBob,25,Osaka\n")

            # CSV -> Markdown
            out_md = csv_to_markdown(str(csv_path), str(md_path))
            self.assertEqual(out_md, str(md_path))
            self.assertTrue(md_path.exists())

            with open(md_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("| Name | Age | City |", content)
            self.assertIn("| --- | --- | --- |", content)
            self.assertIn("| Alice | 30 | Tokyo |", content)

            # Markdown -> CSV
            new_csv = Path(tmpdir) / "from_md.csv"
            out_csv = markdown_to_csv(str(md_path), str(new_csv))
            self.assertEqual(out_csv, str(new_csv))
            self.assertTrue(new_csv.exists())

            with open(new_csv, "r", encoding="utf-8-sig") as f:
                csv_lines = [l.strip() for l in f if l.strip()]
            self.assertEqual(csv_lines[0], "Name,Age,City")
            self.assertEqual(csv_lines[1], "Alice,30,Tokyo")

    def test_docx_and_markdown_bidirectional(self):
        import docx
        with tempfile.TemporaryDirectory() as tmpdir:
            docx_path = Path(tmpdir) / "doc.docx"
            md_path = Path(tmpdir) / "doc.md"

            # Create Docx
            doc = docx.Document()
            doc.add_heading("Project Overview", level=1)
            doc.add_heading("Sub-section", level=2)
            doc.add_paragraph("This is introductory text.")
            p_bullet = doc.add_paragraph("Key point A", style="List Bullet")
            table = doc.add_table(rows=2, cols=2)
            table.cell(0, 0).text = "Metric"
            table.cell(0, 1).text = "Score"
            table.cell(1, 0).text = "Accuracy"
            table.cell(1, 1).text = "99%"
            doc.save(docx_path)

            # Docx -> Markdown
            out_md = docx_to_markdown(str(docx_path), str(md_path))
            self.assertEqual(out_md, str(md_path))
            self.assertTrue(md_path.exists())

            with open(md_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("# Project Overview", content)
            self.assertIn("## Sub-section", content)
            self.assertIn("- Key point A", content)
            self.assertIn("| Metric | Score |", content)
            self.assertIn("| Accuracy | 99% |", content)

            # Markdown -> Docx
            new_docx = Path(tmpdir) / "converted.docx"
            out_docx = markdown_to_docx(str(md_path), str(new_docx))
            self.assertEqual(out_docx, str(new_docx))
            self.assertTrue(new_docx.exists())

            doc_check = docx.Document(str(new_docx))
            all_text = " ".join(p.text for p in doc_check.paragraphs)
            self.assertIn("Project Overview", all_text)
            self.assertIn("Key point A", all_text)
            self.assertTrue(len(doc_check.tables) > 0)

    def test_docx_to_text(self):
        import docx
        with tempfile.TemporaryDirectory() as tmpdir:
            docx_path = Path(tmpdir) / "sample.docx"
            txt_path = Path(tmpdir) / "sample.txt"

            doc = docx.Document()
            doc.add_paragraph("Hello world from Docx.")
            table = doc.add_table(rows=1, cols=2)
            table.cell(0, 0).text = "ColA"
            table.cell(0, 1).text = "ColB"
            doc.save(docx_path)

            out_txt = docx_to_text(str(docx_path), str(txt_path))
            self.assertEqual(out_txt, str(txt_path))
            self.assertTrue(txt_path.exists())

            with open(txt_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("Hello world from Docx.", content)
            self.assertIn("ColA\tColB", content)

    def test_pptx_to_markdown_and_text(self):
        from pptx import Presentation
        from pptx.util import Inches

        with tempfile.TemporaryDirectory() as tmpdir:
            pptx_path = Path(tmpdir) / "slides.pptx"
            prs = Presentation()
            slide_layout = prs.slide_layouts[6]
            slide = prs.slides.add_slide(slide_layout)

            tb = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1))
            tb.text_frame.text = "First slide content"

            table_shape = slide.shapes.add_table(2, 2, Inches(1), Inches(2), Inches(4), Inches(2))
            t = table_shape.table
            t.cell(0, 0).text = "A"
            t.cell(0, 1).text = "B"
            t.cell(1, 0).text = "1"
            t.cell(1, 1).text = "2"

            prs.save(pptx_path)

            # PPTX -> Markdown
            md_path = Path(tmpdir) / "slides.md"
            out_md = pptx_to_markdown(str(pptx_path), str(md_path))
            self.assertEqual(out_md, str(md_path))
            self.assertTrue(md_path.exists())

            with open(md_path, "r", encoding="utf-8") as f:
                md_content = f.read()
            self.assertIn("## Slide 1", md_content)
            self.assertIn("First slide content", md_content)
            self.assertIn("| A | B |", md_content)

            # PPTX -> Text
            txt_path = Path(tmpdir) / "slides.txt"
            out_txt = pptx_to_text(str(pptx_path), str(txt_path))
            self.assertEqual(out_txt, str(txt_path))
            self.assertTrue(txt_path.exists())

            with open(txt_path, "r", encoding="utf-8") as f:
                txt_content = f.read()
            self.assertIn("=== Slide 1 ===", txt_content)
            self.assertIn("First slide content", txt_content)

    def test_text_to_markdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            txt_path = Path(tmpdir) / "notes.txt"
            md_path = Path(tmpdir) / "notes.md"

            with open(txt_path, "w", encoding="utf-8") as f:
                f.write("Line 1\nLine 2\n")

            out_md = text_to_markdown(str(txt_path), str(md_path))
            self.assertEqual(out_md, str(md_path))
            self.assertTrue(md_path.exists())

            with open(md_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("# notes", content)
            self.assertIn("Line 1\nLine 2", content)

    def test_convert_translated_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Auto does nothing
            f_auto = Path(tmpdir) / "file.xlsx"
            f_auto.touch()
            self.assertEqual(convert_translated_output(str(f_auto), "auto"), str(f_auto))

            # xlsx -> md
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.append(["Col1", "Col2"])
            ws.append(["A", "B"])
            wb.save(f_auto)

            converted_md = convert_translated_output(str(f_auto), "md")
            self.assertTrue(converted_md.endswith(".md"))
            self.assertTrue(Path(converted_md).exists())

            # md -> xlsx
            converted_xlsx = convert_translated_output(converted_md, "xlsx")
            self.assertTrue(converted_xlsx.endswith(".xlsx"))
            self.assertTrue(Path(converted_xlsx).exists())

            # xlsx -> csv
            converted_csv = convert_translated_output(str(f_auto), "csv")
            self.assertTrue(converted_csv.endswith(".csv"))
            self.assertTrue(Path(converted_csv).exists())

    def test_get_convert_options(self):
        self.assertEqual(get_convert_options(".xlsx"), ["md", "csv"])
        self.assertEqual(get_convert_options("xlsx"), ["md", "csv"])
        self.assertEqual(get_convert_options(".XLSX"), ["md", "csv"])
        self.assertEqual(get_convert_options(".csv"), ["xlsx", "md"])
        self.assertEqual(get_convert_options(".tsv"), ["xlsx", "md"])
        self.assertEqual(get_convert_options(".docx"), ["md", "txt"])
        self.assertEqual(get_convert_options(".pptx"), ["md", "txt"])
        self.assertEqual(get_convert_options(".md"), ["xlsx", "docx", "csv"])
        self.assertEqual(get_convert_options("md"), ["xlsx", "docx", "csv"])
        self.assertEqual(get_convert_options(".txt"), ["md", "docx"])
        self.assertEqual(get_convert_options(".pdf"), [])
        self.assertEqual(get_convert_options(".unknown"), [])

    def test_convert_file_direct(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            xlsx_path = Path(tmpdir) / "sample.xlsx"
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.append(["Header1", "Header2"])
            ws.append(["Value1", "Value2"])
            wb.save(xlsx_path)

            # Direct xlsx -> md
            out_md = convert_file_direct(str(xlsx_path), "md")
            self.assertTrue(Path(out_md).exists())
            self.assertTrue(out_md.endswith("sample.md"))

            # Direct xlsx -> csv
            out_csv = convert_file_direct(str(xlsx_path), "csv")
            self.assertTrue(Path(out_csv).exists())
            self.assertTrue(out_csv.endswith("sample.csv"))

            # Direct csv -> xlsx
            out_xlsx = convert_file_direct(out_csv, "xlsx")
            self.assertTrue(Path(out_xlsx).exists())
            self.assertTrue(out_xlsx.endswith("sample (1).xlsx"))

            # Invalid format raises ValueError
            with self.assertRaises(ValueError):
                convert_file_direct(str(xlsx_path), "pdf")


if __name__ == "__main__":
    unittest.main()
