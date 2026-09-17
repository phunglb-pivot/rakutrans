"""
Format conversion engine for RakuTrans AI.
Enables bi-directional cross-format conversion:
- Excel (.xlsx) -> GitHub Flavored Markdown (.md)
- Markdown (.md) -> Formatted Excel workbook (.xlsx)
"""

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from config import get_smart_output_path, get_unique_output_path


def excel_to_markdown(xlsx_path: str, md_output_path: Optional[str] = None) -> str:
    """
    Converts an Excel (.xlsx) workbook into a clean, multi-sheet Markdown document.
    Each sheet is represented with a heading and a GitHub-flavored Markdown table.
    """
    src = Path(xlsx_path)
    if not src.exists():
        raise FileNotFoundError(f"Excel file not found: {xlsx_path}")

    if not md_output_path:
        md_output_path = str(get_unique_output_path(src.with_suffix(".md")))

    wb = openpyxl.load_workbook(str(src), data_only=False)
    md_lines: List[str] = []

    # Title from file name
    doc_title = re.sub(r"^\[Translated\]_", "", src.stem)
    md_lines.append(f"# {doc_title}\n")

    for sheet_idx, sheet_name in enumerate(wb.sheetnames):
        ws = wb[sheet_name]
        md_lines.append(f"## {sheet_name}\n")

        raw_rows = list(ws.iter_rows(values_only=True))
        # Filter out trailing empty rows
        filtered_rows = []
        for row in raw_rows:
            # Check if row has any non-empty cell
            if any(c is not None and str(c).strip() != "" for c in row):
                filtered_rows.append(row)

        if not filtered_rows:
            md_lines.append("*(Trống / Empty sheet)*\n")
            continue

        # Determine maximum column count
        max_cols = max(len(row) for row in filtered_rows)
        # Trim columns if entire columns are empty
        active_cols = []
        for col_idx in range(max_cols):
            has_val = any(
                col_idx < len(r) and r[col_idx] is not None and str(r[col_idx]).strip() != ""
                for r in filtered_rows
            )
            if has_val:
                active_cols.append(col_idx)

        if not active_cols:
            md_lines.append("*(Trống / Empty sheet)*\n")
            continue

        def sanitize_cell(val: any) -> str:
            if val is None:
                return ""
            s = str(val).strip()
            # Replace inner linebreaks with <br> for valid markdown table rows
            s = s.replace("\r\n", "<br>").replace("\n", "<br>")
            # Escape pipes
            s = s.replace("|", "\\|")
            return s

        # Build table
        table_rows: List[List[str]] = []
        for r in filtered_rows:
            row_cells = [sanitize_cell(r[c] if c < len(r) else "") for c in active_cols]
            table_rows.append(row_cells)

        if table_rows:
            # First row as header
            header_cells = table_rows[0]
            # If all header cells are empty, provide generic Column 1, Column 2...
            if all(not c for c in header_cells):
                header_cells = [f"Col {i+1}" for i in range(len(header_cells))]

            md_lines.append("| " + " | ".join(header_cells) + " |")
            md_lines.append("| " + " | ".join(["---"] * len(header_cells)) + " |")

            for data_row in table_rows[1:]:
                md_lines.append("| " + " | ".join(data_row) + " |")

            md_lines.append("")  # Blank line after table

    out_file = Path(md_output_path)
    with open(out_file, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines).strip() + "\n")

    return str(out_file)


def markdown_to_excel(md_path: str, xlsx_output_path: Optional[str] = None) -> str:
    """
    Parses a Markdown document and converts tables and sections into a professionally styled Excel workbook.
    """
    src = Path(md_path)
    if not src.exists():
        raise FileNotFoundError(f"Markdown file not found: {md_path}")

    if not xlsx_output_path:
        xlsx_output_path = str(get_unique_output_path(src.with_suffix(".xlsx")))

    with open(src, "r", encoding="utf-8") as f:
        content = f.read()

    wb = openpyxl.Workbook()
    # Default sheet
    default_sheet = wb.active
    default_sheet.title = "Document"

    # Styling definitions
    header_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    section_font = Font(name="Segoe UI", size=14, bold=True, color="1F4E79")
    title_font = Font(name="Segoe UI", size=16, bold=True, color="0F243E")
    normal_font = Font(name="Segoe UI", size=10)
    bold_font = Font(name="Segoe UI", size=10, bold=True)
    
    thin_border = Border(
        left=Side(style="thin", color="D3D3D3"),
        right=Side(style="thin", color="D3D3D3"),
        top=Side(style="thin", color="D3D3D3"),
        bottom=Side(style="thin", color="D3D3D3")
    )
    center_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left_align = Alignment(horizontal="left", vertical="center", wrap_text=True)

    lines = content.splitlines()
    current_sheet = default_sheet
    current_row = 1
    sheet_created_count = 0

    idx = 0
    while idx < len(lines):
        line = lines[idx].strip()
        if not line:
            idx += 1
            continue

        # Document main title (# Title)
        if line.startswith("# ") and not line.startswith("## "):
            title_text = line[2:].strip()
            cell = current_sheet.cell(row=current_row, column=1, value=title_text)
            cell.font = title_font
            current_row += 2
            idx += 1
            continue

        # Section / Sheet heading (## Sheet or Section)
        if line.startswith("## "):
            section_title = line[3:].strip()
            # If default sheet is still untouched and at row 1, reuse it
            clean_title = re.sub(r'[\\/*?:\[\]]', '_', section_title)[:31]
            if current_row == 1 and sheet_created_count == 0:
                current_sheet.title = clean_title
                sheet_created_count += 1
            else:
                # Create a new sheet for this major section if clean_title isn't duplicate
                sheet_name = clean_title
                counter = 2
                while sheet_name in wb.sheetnames:
                    sheet_name = f"{clean_title[:28]}_{counter}"
                    counter += 1
                current_sheet = wb.create_sheet(title=sheet_name)
                current_row = 1
                sheet_created_count += 1

            cell = current_sheet.cell(row=current_row, column=1, value=section_title)
            cell.font = section_font
            current_row += 2
            idx += 1
            continue

        # Markdown Table Detection (| cell | cell |)
        if line.startswith("|") and line.endswith("|"):
            table_lines = []
            while idx < len(lines) and lines[idx].strip().startswith("|") and lines[idx].strip().endswith("|"):
                table_lines.append(lines[idx].strip())
                idx += 1

            # Parse table lines
            table_data: List[List[str]] = []
            is_first = True
            for t_line in table_lines:
                # Check if delimiter row (| --- | --- |)
                inner = t_line.strip("|").strip()
                if set(inner.replace("|", "").replace("-", "").replace(":", "").strip()) == set():
                    # Delimiter row, skip
                    continue

                cells = [c.strip().replace("<br>", "\n").replace("\\|", "|") for c in t_line.strip("|").split("|")]
                table_data.append(cells)

            if table_data:
                # Write table to Excel
                start_row = current_row
                for r_idx, row_values in enumerate(table_data):
                    is_header = (r_idx == 0)
                    for c_idx, val in enumerate(row_values):
                        cell = current_sheet.cell(row=current_row, column=c_idx + 1)
                        # Try parsing numbers
                        if val.isdigit():
                            cell.value = int(val)
                        else:
                            try:
                                cell.value = float(val) if "." in val else val
                            except ValueError:
                                cell.value = val

                        cell.border = thin_border
                        if is_header:
                            cell.font = header_font
                            cell.fill = header_fill
                            cell.alignment = center_align
                        else:
                            cell.font = normal_font
                            cell.alignment = left_align

                    current_row += 1

                current_row += 2  # Space after table
            continue

        # Normal text paragraph or list item
        cell = current_sheet.cell(row=current_row, column=1, value=line)
        cell.font = normal_font
        cell.alignment = left_align
        current_row += 1
        idx += 1

    # Auto-adjust column widths for all sheets
    for ws in wb.worksheets:
        for col in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                val = cell.value
                if val:
                    # Account for linebreaks
                    lines_in_cell = str(val).split("\n")
                    longest = max(len(l) for l in lines_in_cell)
                    if longest > max_len:
                        max_len = longest
            # Constrain width between 12 and 60
            ws.column_dimensions[col_letter].width = max(12, min(max_len + 4, 60))

    out_file = Path(xlsx_output_path)
    wb.save(str(out_file))
    return str(out_file)


def convert_translated_output(
    translated_file: str,
    target_format: str = "auto"
) -> str:
    """
    Checks if post-translation conversion is requested:
    - 'auto': leaves file in original format.
    - 'xlsx': converts markdown to xlsx if needed.
    - 'md': converts excel to markdown if needed.
    Returns the path to the final output file.
    """
    path = Path(translated_file)
    fmt = (target_format or "auto").lower()

    if fmt == "auto":
        return str(path)

    if fmt == "md" and path.suffix.lower() == ".xlsx":
        md_path = str(get_unique_output_path(path.with_suffix(".md")))
        return excel_to_markdown(str(path), md_path)

    if fmt == "xlsx" and path.suffix.lower() == ".md":
        xlsx_path = str(get_unique_output_path(path.with_suffix(".xlsx")))
        return markdown_to_excel(str(path), xlsx_path)

    return str(path)


def get_convert_options(file_ext: str) -> list:
    """
    Returns available target format keys for a given source file extension.
    E.g. '.xlsx' -> ['md'], '.md' -> ['xlsx']
    """
    ext = file_ext.lower().lstrip(".")
    if ext == "xlsx":
        return ["md"]
    elif ext == "md":
        return ["xlsx"]
    return []


def convert_file_direct(source_path: str, target_format: str) -> str:
    """
    Directly convert a file to target_format without any translation.
    target_format: 'md' or 'xlsx'
    Returns path to the converted output file.
    """
    path = Path(source_path)
    fmt = target_format.lower().strip(".")

    if fmt == "md" and path.suffix.lower() == ".xlsx":
        out_path = str(get_smart_output_path(source_path=path, target_format=".md"))
        return excel_to_markdown(str(path), out_path)

    if fmt == "xlsx" and path.suffix.lower() == ".md":
        out_path = str(get_smart_output_path(source_path=path, target_format=".xlsx"))
        return markdown_to_excel(str(path), out_path)

    raise ValueError(f"Cannot convert {path.suffix} to .{fmt}")
