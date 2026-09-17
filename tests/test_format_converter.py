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

    def test_get_convert_options(self):
        self.assertEqual(get_convert_options(".xlsx"), ["md"])
        self.assertEqual(get_convert_options("xlsx"), ["md"])
        self.assertEqual(get_convert_options(".XLSX"), ["md"])
        self.assertEqual(get_convert_options(".md"), ["xlsx"])
        self.assertEqual(get_convert_options("md"), ["xlsx"])
        self.assertEqual(get_convert_options(".MD"), ["xlsx"])
        self.assertEqual(get_convert_options(".txt"), [])
        self.assertEqual(get_convert_options(".pdf"), [])

    def test_convert_file_direct(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            xlsx_path = Path(tmpdir) / "sample.xlsx"
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.append(["Header1", "Header2"])
            ws.append(["Value1", "Value2"])
            wb.save(xlsx_path)

            # Direct xlsx -> md (smart name: sample.md)
            out_md = convert_file_direct(str(xlsx_path), "md")
            self.assertTrue(Path(out_md).exists())
            self.assertTrue(out_md.endswith("sample.md"))
            with open(out_md, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("Header1", content)
            self.assertIn("Value1", content)

            # Direct xlsx -> md again when sample.md exists -> sample (1).md
            out_md_2 = convert_file_direct(str(xlsx_path), "md")
            self.assertTrue(out_md_2.endswith("sample (1).md"))

            # Direct md -> xlsx (since sample.xlsx exists, smart name -> sample (1).xlsx)
            out_xlsx = convert_file_direct(out_md, "xlsx")
            self.assertTrue(Path(out_xlsx).exists())
            self.assertTrue(out_xlsx.endswith("sample (1).xlsx"))
            wb_check = openpyxl.load_workbook(out_xlsx)
            self.assertTrue(len(wb_check.sheetnames) > 0)

            # Invalid format raises ValueError
            with self.assertRaises(ValueError):
                convert_file_direct(str(xlsx_path), "txt")


if __name__ == "__main__":
    unittest.main()
