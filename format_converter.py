"""
Format conversion engine for RakuTrans AI.
Enables cross-format document and data conversions:
- PDF (.pdf) -> Word (.docx)
- PDF (.pdf) -> Markdown (.md)
- PDF (.pdf) -> Text (.txt)
- Excel (.xlsx) <-> Markdown (.md)
- Excel (.xlsx) <-> CSV (.csv)
- CSV/TSV (.csv, .tsv) <-> Excel (.xlsx)
- CSV/TSV (.csv, .tsv) <-> Markdown (.md)
- Word (.docx) <-> Markdown (.md)
- Word (.docx) -> Text (.txt)
- PowerPoint (.pptx) -> Markdown (.md)
- PowerPoint (.pptx) -> Text (.txt)
- Markdown (.md) -> Word (.docx)
- Text (.txt) -> Markdown (.md) / Word (.docx)
"""

import csv
import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from config import get_smart_output_path, get_unique_output_path


# -----------------------------------------------------------------------------
# PDF Conversions
# -----------------------------------------------------------------------------

def pdf_to_docx(pdf_path: str, docx_output_path: Optional[str] = None) -> str:
    """
    Converts a PDF (.pdf) document into an editable Microsoft Word (.docx) document.
    Uses pdf2docx to reconstruct flow-based paragraphs, styles, images, and tables.
    """
    src = Path(pdf_path)
    if not src.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    out_file = Path(docx_output_path) if docx_output_path else get_unique_output_path(src.with_suffix(".docx"))
    out_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        from pdf2docx import Converter
        cv = Converter(str(src))
        cv.convert(str(out_file))
        cv.close()
    except Exception as e:
        # Fallback using python-docx with text blocks if pdf2docx encounters issues
        import docx
        doc = docx.Document()
        doc.add_heading(src.stem, level=0)
        try:
            import pymupdf
            pdoc = pymupdf.open(str(src))
            for page_idx, page in enumerate(pdoc):
                doc.add_heading(f"Page {page_idx + 1}", level=1)
                text = page.get_text()
                for para in text.split("\n\n"):
                    p_str = para.strip()
                    if p_str:
                        doc.add_paragraph(p_str)
            pdoc.close()
        except Exception:
            import pypdf
            reader = pypdf.PdfReader(str(src))
            for page_idx, page in enumerate(reader.pages):
                doc.add_heading(f"Page {page_idx + 1}", level=1)
                text = page.extract_text() or ""
                for para in text.split("\n\n"):
                    p_str = para.strip()
                    if p_str:
                        doc.add_paragraph(p_str)
        doc.save(str(out_file))

    return str(out_file)


def pdf_to_markdown(pdf_path: str, md_output_path: Optional[str] = None) -> str:
    """Converts a PDF file to clean structured Markdown."""
    src = Path(pdf_path)
    if not src.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    out_file = Path(md_output_path) if md_output_path else get_unique_output_path(src.with_suffix(".md"))
    out_file.parent.mkdir(parents=True, exist_ok=True)

    # Attempt conversion via markitdown first
    try:
        from markitdown import MarkItDown
        mid = MarkItDown()
        res = mid.convert(str(src))
        if res and res.text_content and len(res.text_content.strip()) > 20:
            with open(out_file, "w", encoding="utf-8") as f:
                f.write(res.text_content.strip() + "\n")
            return str(out_file)
    except Exception:
        pass

    # High-precision fallback via PyMuPDF or pypdf
    md_lines: List[str] = []
    doc_title = re.sub(r"^\[Translated\]_", "", src.stem)
    md_lines.append(f"# {doc_title}\n")

    try:
        import pymupdf
        doc = pymupdf.open(str(src))
        for idx, page in enumerate(doc):
            md_lines.append(f"\n## Page {idx + 1}\n")
            text = page.get_text() or ""
            for p in text.split("\n\n"):
                p_clean = p.strip()
                if p_clean:
                    md_lines.append(f"{p_clean}\n")
        doc.close()
    except Exception:
        import pypdf
        reader = pypdf.PdfReader(str(src))
        for idx, page in enumerate(reader.pages):
            md_lines.append(f"\n## Page {idx + 1}\n")
            text = page.extract_text() or ""
            for p in text.split("\n\n"):
                p_clean = p.strip()
                if p_clean:
                    md_lines.append(f"{p_clean}\n")

    with open(out_file, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines).strip() + "\n")

    return str(out_file)


def pdf_to_text(pdf_path: str, txt_output_path: Optional[str] = None) -> str:
    """Converts a PDF file to clean plain text with page dividers."""
    src = Path(pdf_path)
    if not src.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    out_file = Path(txt_output_path) if txt_output_path else get_unique_output_path(src.with_suffix(".txt"))
    out_file.parent.mkdir(parents=True, exist_ok=True)

    pages_text: List[str] = []
    try:
        import pymupdf
        doc = pymupdf.open(str(src))
        for idx, page in enumerate(doc):
            t = (page.get_text() or "").strip()
            pages_text.append(f"--- Page {idx + 1} ---\n{t}")
        doc.close()
    except Exception:
        import pypdf
        reader = pypdf.PdfReader(str(src))
        for idx, page in enumerate(reader.pages):
            t = (page.extract_text() or "").strip()
            pages_text.append(f"--- Page {idx + 1} ---\n{t}")

    with open(out_file, "w", encoding="utf-8") as f:
        f.write("\n\n".join(pages_text).strip() + "\n")

    return str(out_file)


# -----------------------------------------------------------------------------
# Excel Conversions
# -----------------------------------------------------------------------------

def excel_to_markdown(xlsx_path: str, md_output_path: Optional[str] = None) -> str:
    """
    Converts an Excel (.xlsx) workbook into a clean, multi-sheet Markdown document.
    Each sheet is represented with a heading and a GitHub-flavored Markdown table.
    """
    src = Path(xlsx_path)
    if not src.exists():
        raise FileNotFoundError(f"Excel file not found: {xlsx_path}")

    out_file = Path(md_output_path) if md_output_path else get_unique_output_path(src.with_suffix(".md"))
    wb = openpyxl.load_workbook(str(src), data_only=True)

    md_lines: List[str] = []
    doc_title = re.sub(r"^\[Translated\]_", "", src.stem)
    md_lines.append(f"# {doc_title}\n")

    def sanitize_cell(val) -> str:
        if val is None:
            return ""
        s = str(val).replace("\r\n", "<br>").replace("\n", "<br>").replace("|", "\\|")
        return s.strip()

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        raw_rows = list(ws.iter_rows(values_only=True))
        filtered_rows = [row for row in raw_rows if any(c is not None and str(c).strip() != "" for c in row)]

        if not filtered_rows:
            continue

        md_lines.append(f"## {sheet_name}\n")
        max_cols = max(len(r) for r in filtered_rows)
        active_cols = [c for c in range(max_cols) if any(c < len(r) and r[c] is not None and str(r[c]).strip() != "" for r in filtered_rows)]

        if not active_cols:
            continue

        table_rows = []
        for r in filtered_rows:
            row_cells = [sanitize_cell(r[c] if c < len(r) else None) for c in active_cols]
            table_rows.append(row_cells)

        if not table_rows:
            continue

        header_cells = table_rows[0]
        md_lines.append("| " + " | ".join(header_cells) + " |")
        md_lines.append("| " + " | ".join(["---"] * len(header_cells)) + " |")

        for data_row in table_rows[1:]:
            padded = data_row + [""] * (len(header_cells) - len(data_row))
            md_lines.append("| " + " | ".join(padded[:len(header_cells)]) + " |")

        md_lines.append("")

    wb.close()
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines).strip() + "\n")

    return str(out_file)


def markdown_to_excel(md_path: str, xlsx_output_path: Optional[str] = None) -> str:
    """Converts a Markdown (.md) document into a styled Excel (.xlsx) workbook."""
    src = Path(md_path)
    if not src.exists():
        raise FileNotFoundError(f"Markdown file not found: {md_path}")

    out_file = Path(xlsx_output_path) if xlsx_output_path else get_unique_output_path(src.with_suffix(".xlsx"))

    with open(src, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    wb = openpyxl.Workbook()
    default_sheet = wb.active
    default_sheet.title = "Document"

    header_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    title_font = Font(name="Segoe UI", size=13, bold=True, color="1F4E79")
    normal_font = Font(name="Segoe UI", size=10)
    thin_border = Border(
        left=Side(style="thin", color="D9D9D9"),
        right=Side(style="thin", color="D9D9D9"),
        top=Side(style="thin", color="D9D9D9"),
        bottom=Side(style="thin", color="D9D9D9")
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

        if line.startswith("# "):
            title_text = line[2:].strip()
            cell = current_sheet.cell(row=current_row, column=1, value=title_text)
            cell.font = title_font
            current_row += 2
            idx += 1
            continue

        if line.startswith("## "):
            section_title = line[3:].strip()
            clean_title = re.sub(r'[\\/*?:\[\]]', "_", section_title)[:31]
            if sheet_created_count == 0 and current_row == 1:
                current_sheet.title = clean_title or "Sheet1"
            else:
                sheet_name = clean_title or f"Sheet{len(wb.sheetnames) + 1}"
                counter = 1
                while sheet_name in wb.sheetnames:
                    sheet_name = f"{clean_title[:28]}_{counter}"
                    counter += 1
                current_sheet = wb.create_sheet(title=sheet_name)
                current_row = 1
            sheet_created_count += 1
            idx += 1
            continue

        if line.startswith("|") and line.endswith("|"):
            table_lines = []
            while idx < len(lines) and lines[idx].strip().startswith("|") and lines[idx].strip().endswith("|"):
                table_lines.append(lines[idx].strip())
                idx += 1

            table_data = []
            for t_line in table_lines:
                inner = t_line[1:-1]
                cells = [c.strip().replace("<br>", "\n").replace("\\|", "|") for c in inner.split("|")]
                if set("".join(cells).replace("-", "").replace(":", "").strip()) == set():
                    continue
                table_data.append(cells)

            for r_idx, row_values in enumerate(table_data):
                is_header = (r_idx == 0)
                for c_idx, val in enumerate(row_values):
                    cell = current_sheet.cell(row=current_row + r_idx, column=c_idx + 1)
                    if val.isdigit():
                        cell.value = int(val)
                    else:
                        try:
                            cell.value = float(val) if ("." in val or "," in val) else val
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

                current_sheet.row_dimensions[current_row + r_idx].height = 24 if is_header else 20

            current_row += len(table_data) + 1
            continue

        idx += 1

    # Auto-adjust column widths
    for ws in wb.worksheets:
        for col in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                if cell.value is not None:
                    lines_in_cell = str(cell.value).split("\n")
                    longest = max(len(l) for l in lines_in_cell)
                    max_len = max(max_len, longest)
            ws.column_dimensions[col_letter].width = max(10, min(max_len + 3, 50))

    out_file.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(out_file))
    return str(out_file)


# -----------------------------------------------------------------------------
# CSV Conversions
# -----------------------------------------------------------------------------

def _detect_csv_params(file_path: Path) -> Tuple[str, str]:
    """Detects encoding and delimiter for CSV/TSV."""
    candidate_enc = ["utf-8-sig", "utf-8", "cp1252", "latin1"]
    enc = "utf-8"
    for e in candidate_enc:
        try:
            with open(file_path, "r", encoding=e) as f:
                f.read(4096)
            enc = e
            break
        except (UnicodeDecodeError, LookupError):
            continue

    delim = "\t" if file_path.suffix.lower() == ".tsv" else ","
    try:
        with open(file_path, "r", encoding=enc) as f:
            sample = f.read(4096)
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
            delim = dialect.delimiter
    except Exception:
        pass

    return enc, delim


def csv_to_excel(csv_path: str, xlsx_output_path: Optional[str] = None) -> str:
    """Converts a CSV or TSV file into a formatted Excel (.xlsx) workbook."""
    src = Path(csv_path)
    if not src.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    out_file = Path(xlsx_output_path) if xlsx_output_path else get_unique_output_path(src.with_suffix(".xlsx"))
    enc, delim = _detect_csv_params(src)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = src.stem[:31]

    header_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    normal_font = Font(name="Segoe UI", size=10)
    thin_border = Border(
        left=Side(style="thin", color="D9D9D9"),
        right=Side(style="thin", color="D9D9D9"),
        top=Side(style="thin", color="D9D9D9"),
        bottom=Side(style="thin", color="D9D9D9")
    )
    left_align = Alignment(horizontal="left", vertical="center")
    center_align = Alignment(horizontal="center", vertical="center")

    with open(src, "r", encoding=enc, errors="replace", newline="") as f:
        reader = csv.reader(f, delimiter=delim)
        for r_idx, row in enumerate(reader, start=1):
            is_header = (r_idx == 1)
            for c_idx, val in enumerate(row, start=1):
                cell = ws.cell(row=r_idx, column=c_idx)
                val_str = str(val).strip()
                if val_str.isdigit():
                    cell.value = int(val_str)
                else:
                    try:
                        cell.value = float(val_str) if "." in val_str else val_str
                    except ValueError:
                        cell.value = val_str

                cell.border = thin_border
                if is_header:
                    cell.font = header_font
                    cell.fill = header_fill
                    cell.alignment = center_align
                else:
                    cell.font = normal_font
                    cell.alignment = left_align

    for col in ws.columns:
        max_len = max((len(str(c.value or "")) for c in col), default=0)
        col_letter = get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = max(10, min(max_len + 3, 50))

    out_file.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(out_file))
    return str(out_file)


def excel_to_csv(xlsx_path: str, csv_output_path: Optional[str] = None) -> str:
    """Exports active sheet of an Excel (.xlsx) workbook to CSV with UTF-8-SIG."""
    src = Path(xlsx_path)
    if not src.exists():
        raise FileNotFoundError(f"Excel file not found: {xlsx_path}")

    out_file = Path(csv_output_path) if csv_output_path else get_unique_output_path(src.with_suffix(".csv"))
    wb = openpyxl.load_workbook(str(src), data_only=True)
    ws = wb.active

    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        for row in ws.iter_rows(values_only=True):
            if any(c is not None and str(c).strip() != "" for c in row):
                writer.writerow(["" if c is None else str(c) for c in row])

    wb.close()
    return str(out_file)


def csv_to_markdown(csv_path: str, md_output_path: Optional[str] = None) -> str:
    """Converts CSV or TSV file into a GitHub Flavored Markdown table."""
    src = Path(csv_path)
    if not src.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    out_file = Path(md_output_path) if md_output_path else get_unique_output_path(src.with_suffix(".md"))
    enc, delim = _detect_csv_params(src)

    rows = []
    with open(src, "r", encoding=enc, errors="replace", newline="") as f:
        reader = csv.reader(f, delimiter=delim)
        for r in reader:
            if any(c.strip() != "" for c in r):
                rows.append([c.strip().replace("\r\n", "<br>").replace("\n", "<br>").replace("|", "\\|") for c in r])

    if not rows:
        out_file.write_text(f"# {src.stem}\n\n*Empty CSV dataset*\n", encoding="utf-8")
        return str(out_file)

    md_lines = [f"# {src.stem}\n"]
    header = rows[0]
    md_lines.append("| " + " | ".join(header) + " |")
    md_lines.append("| " + " | ".join(["---"] * len(header)) + " |")

    for data_row in rows[1:]:
        padded = data_row + [""] * (len(header) - len(data_row))
        md_lines.append("| " + " | ".join(padded[:len(header)]) + " |")

    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines).strip() + "\n")

    return str(out_file)


def markdown_to_csv(md_path: str, csv_output_path: Optional[str] = None) -> str:
    """Extracts tables from a Markdown file and writes to CSV."""
    src = Path(md_path)
    if not src.exists():
        raise FileNotFoundError(f"Markdown file not found: {md_path}")

    out_file = Path(csv_output_path) if csv_output_path else get_unique_output_path(src.with_suffix(".csv"))
    with open(src, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    lines = content.splitlines()
    table_rows = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            inner = stripped[1:-1]
            cells = [c.strip().replace("<br>", "\n").replace("\\|", "|") for c in inner.split("|")]
            if set("".join(cells).replace("-", "").replace(":", "").strip()) == set():
                continue
            table_rows.append(cells)

    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(table_rows)

    return str(out_file)


# -----------------------------------------------------------------------------
# Word & PowerPoint Conversions
# -----------------------------------------------------------------------------

def _find_soffice_binary() -> Optional[str]:
    """
    Locates the LibreOffice/soffice headless executable across macOS, Windows, and Linux.
    Searches system PATH as well as standard OS application directories.
    """
    import shutil
    candidates = [
        shutil.which("soffice"),
        shutil.which("libreoffice"),
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        os.path.expanduser("~/Applications/LibreOffice.app/Contents/MacOS/soffice"),
        "/opt/homebrew/bin/soffice",
        "/usr/local/bin/soffice",
        "/usr/bin/soffice",
        "/usr/bin/libreoffice",
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        os.path.expandvars(r"%ProgramFiles%\LibreOffice\program\soffice.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\LibreOffice\program\soffice.exe"),
    ]
    for c in candidates:
        if c and os.path.exists(c) and os.path.isfile(c):
            return c
    return None


def docx_to_pdf(docx_path: str, pdf_output_path: Optional[str] = None) -> str:
    """
    Converts a Microsoft Word (.docx) document to a PDF document.
    Attempts system engines (LibreOffice CLI / docx2pdf) first,
    falling back to high-fidelity pure-Python flow-based rendering
    via python-docx and ReportLab Platypus with Unicode fonts.
    """
    src = Path(docx_path)
    if not src.exists():
        raise FileNotFoundError(f"Word document not found: {docx_path}")

    out_file = Path(pdf_output_path) if pdf_output_path else get_unique_output_path(src.with_suffix(".pdf"))
    out_file.parent.mkdir(parents=True, exist_ok=True)

    # 1. Try LibreOffice CLI if available (preserves 100% typography, exact sizes, fonts, styles, tables, and images)
    import shutil
    import subprocess
    soffice_bin = _find_soffice_binary()
    if soffice_bin:
        try:
            import tempfile
            with tempfile.TemporaryDirectory() as tmp_dir:
                cmd = [
                    soffice_bin,
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    tmp_dir,
                    str(src),
                ]
                subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=90)
                gen_pdf = Path(tmp_dir) / f"{src.stem}.pdf"
                if gen_pdf.exists():
                    shutil.copy2(gen_pdf, out_file)
                    return str(out_file)
        except Exception as e:
            print(f"[Warning] LibreOffice conversion failed, falling back to python renderer: {e}")

    # 2. Try docx2pdf if installed (macOS with MS Word, Windows with MS Word)
    try:
        from docx2pdf import convert
        convert(str(src), str(out_file))
        if out_file.exists():
            return str(out_file)
    except Exception:
        pass

    import io
    import docx
    from PIL import Image as PILImage
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    # Resolve Unicode font
    font_candidates = [
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        r"C:\Windows\Fonts\arialuni.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\msjh.ttc",
        r"C:\Windows\Fonts\meiryo.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    font_name = "Helvetica"
    for fp in font_candidates:
        if os.path.exists(fp):
            try:
                fname = f"RakuDocxFont_{os.path.basename(fp).replace('.', '_')}"
                pdfmetrics.registerFont(TTFont(fname, fp))
                font_name = fname
                break
            except Exception:
                continue

    doc = docx.Document(str(src))
    styles = getSampleStyleSheet()

    body_style = ParagraphStyle(
        "RakuDocxBody",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=10.5,
        leading=14.5,
        spaceAfter=6,
    )
    h1_style = ParagraphStyle(
        "RakuDocxH1",
        parent=styles["Heading1"],
        fontName=font_name,
        fontSize=16,
        leading=20,
        spaceBefore=10,
        spaceAfter=6,
    )
    h2_style = ParagraphStyle(
        "RakuDocxH2",
        parent=styles["Heading2"],
        fontName=font_name,
        fontSize=13,
        leading=17,
        spaceBefore=8,
        spaceAfter=4,
    )
    h3_style = ParagraphStyle(
        "RakuDocxH3",
        parent=styles["Heading3"],
        fontName=font_name,
        fontSize=11,
        leading=15,
        spaceBefore=6,
        spaceAfter=3,
    )

    story = []

    def get_element_images(elem):
        imgs = []
        try:
            blips = elem.xpath('.//a:blip/@r:embed')
            for rId in blips:
                if rId in doc.part.rels:
                    rel = doc.part.rels[rId]
                    if 'image' in rel.target_ref:
                        blob = rel.target_part.blob
                        im = PILImage.open(io.BytesIO(blob))
                        w, h = im.size
                        scale = min(1.0, 480.0 / max(1, w), 380.0 / max(1, h))
                        disp_w = max(10.0, w * scale)
                        disp_h = max(10.0, h * scale)
                        imgs.append(RLImage(io.BytesIO(blob), width=disp_w, height=disp_h))
        except Exception:
            pass
        return imgs

    # Process document elements in order
    for elem in doc.element.body:
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag == "p":
            p = docx.text.paragraph.Paragraph(elem, doc)
            # 1. Check and add any images embedded in paragraph
            p_imgs = get_element_images(p._p)
            for img in p_imgs:
                story.append(img)
                story.append(Spacer(1, 4))

            text = p.text.strip()
            if text:
                s_name = (p.style.name if p.style else "").lower()
                if "heading 1" in s_name or "title" in s_name:
                    st = h1_style
                elif "heading 2" in s_name:
                    st = h2_style
                elif "heading 3" in s_name:
                    st = h3_style
                else:
                    st = body_style
                story.append(Paragraph(text, st))
        elif tag == "tbl":
            table = docx.table.Table(elem, doc)
            table_data = []
            for row in table.rows:
                row_data = []
                for cell in row.cells:
                    ctext = cell.text.strip()
                    row_data.append(Paragraph(ctext, body_style))
                table_data.append(row_data)
            if table_data:
                rl_table = Table(table_data)
                rl_table.setStyle(TableStyle([
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ]))
                story.append(rl_table)
                story.append(Spacer(1, 8))

    if not story:
        story.append(Paragraph("", body_style))

    pdf_doc = SimpleDocTemplate(
        str(out_file),
        pagesize=letter,
        leftMargin=40,
        rightMargin=40,
        topMargin=40,
        bottomMargin=40,
    )
    pdf_doc.build(story)
    return str(out_file)


def docx_to_markdown(docx_path: str, md_output_path: Optional[str] = None) -> str:
    """Converts a Microsoft Word (.docx) document to GitHub Flavored Markdown."""
    src = Path(docx_path)
    if not src.exists():
        raise FileNotFoundError(f"Word document not found: {docx_path}")

    out_file = Path(md_output_path) if md_output_path else get_unique_output_path(src.with_suffix(".md"))
    import docx
    doc = docx.Document(str(src))

    md_lines = [f"# {src.stem}\n"]
    for p in doc.paragraphs:
        txt = p.text.strip()
        if not txt:
            continue
        style_name = p.style.name.lower() if p.style else ""
        if "heading 1" in style_name:
            md_lines.append(f"## {txt}\n")
        elif "heading 2" in style_name:
            md_lines.append(f"### {txt}\n")
        elif "heading 3" in style_name:
            md_lines.append(f"#### {txt}\n")
        else:
            md_lines.append(f"{txt}\n")

    for t in doc.tables:
        t_rows = []
        for r in t.rows:
            t_rows.append([cell.text.strip().replace("\n", "<br>").replace("|", "\\|") for cell in r.cells])
        if t_rows:
            header = t_rows[0]
            md_lines.append("\n| " + " | ".join(header) + " |")
            md_lines.append("| " + " | ".join(["---"] * len(header)) + " |")
            for row in t_rows[1:]:
                padded = row + [""] * (len(header) - len(row))
                md_lines.append("| " + " | ".join(padded[:len(header)]) + " |")
            md_lines.append("")

    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines).strip() + "\n")

    return str(out_file)


def markdown_to_docx(md_path: str, docx_output_path: Optional[str] = None) -> str:
    """Converts a Markdown (.md) document into a styled Word (.docx) document."""
    src = Path(md_path)
    if not src.exists():
        raise FileNotFoundError(f"Markdown file not found: {md_path}")

    out_file = Path(docx_output_path) if docx_output_path else get_unique_output_path(src.with_suffix(".docx"))
    import docx
    doc = docx.Document()

    with open(src, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    lines = content.splitlines()
    idx = 0
    while idx < len(lines):
        line = lines[idx].rstrip()
        stripped = line.strip()
        if not stripped:
            idx += 1
            continue

        if stripped.startswith("# "):
            doc.add_heading(stripped[2:], level=0)
            idx += 1
            continue
        if stripped.startswith("## "):
            doc.add_heading(stripped[3:], level=1)
            idx += 1
            continue
        if stripped.startswith("### "):
            doc.add_heading(stripped[4:], level=2)
            idx += 1
            continue

        if stripped.startswith("|") and stripped.endswith("|"):
            table_lines = []
            while idx < len(lines) and lines[idx].strip().startswith("|") and lines[idx].strip().endswith("|"):
                table_lines.append(lines[idx].strip())
                idx += 1

            parsed_rows = []
            for tl in table_lines:
                inner = tl[1:-1]
                cells = [c.strip().replace("<br>", "\n").replace("\\|", "|") for c in inner.split("|")]
                if set("".join(cells).replace("-", "").replace(":", "").strip()) == set():
                    continue
                parsed_rows.append(cells)

            if parsed_rows:
                num_cols = max(len(r) for r in parsed_rows)
                t = doc.add_table(rows=len(parsed_rows), cols=num_cols)
                t.style = "Table Grid"
                for r_idx, r_data in enumerate(parsed_rows):
                    for c_idx, val in enumerate(r_data):
                        cell = t.cell(r_idx, c_idx)
                        cell.text = val
                        if r_idx == 0:
                            for p in cell.paragraphs:
                                for run in p.runs:
                                    run.bold = True
            continue

        p = doc.add_paragraph()
        p.add_run(stripped)
        idx += 1

    out_file.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_file))
    return str(out_file)


def docx_to_text(docx_path: str, txt_output_path: Optional[str] = None) -> str:
    """Extracts text from Word document into plain text (.txt)."""
    src = Path(docx_path)
    if not src.exists():
        raise FileNotFoundError(f"Word document not found: {docx_path}")

    out_file = Path(txt_output_path) if txt_output_path else get_unique_output_path(src.with_suffix(".txt"))
    import docx
    doc = docx.Document(str(src))

    texts = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    for t in doc.tables:
        for row in t.rows:
            row_text = "\t".join(cell.text.strip() for cell in row.cells)
            if row_text:
                texts.append(row_text)

    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        f.write("\n\n".join(texts).strip() + "\n")

    return str(out_file)


def pptx_to_markdown(pptx_path: str, md_output_path: Optional[str] = None) -> str:
    """Extracts slides outline and tables from PowerPoint (.pptx) to Markdown."""
    src = Path(pptx_path)
    if not src.exists():
        raise FileNotFoundError(f"PowerPoint presentation not found: {pptx_path}")

    out_file = Path(md_output_path) if md_output_path else get_unique_output_path(src.with_suffix(".md"))
    from pptx import Presentation
    prs = Presentation(str(src))

    md_lines = [f"# {src.stem}\n"]
    for idx, slide in enumerate(prs.slides, start=1):
        md_lines.append(f"## Slide {idx}\n")
        for shape in slide.shapes:
            if shape.has_text_frame:
                for p in shape.text_frame.paragraphs:
                    txt = p.text.strip()
                    if txt:
                        md_lines.append(f"- {txt}")
            if shape.has_table:
                t_rows = []
                for row in shape.table.rows:
                    t_rows.append([c.text.strip().replace("\n", "<br>").replace("|", "\\|") for c in row.cells])
                if t_rows:
                    header = t_rows[0]
                    md_lines.append("\n| " + " | ".join(header) + " |")
                    md_lines.append("| " + " | ".join(["---"] * len(header)) + " |")
                    for r in t_rows[1:]:
                        padded = r + [""] * (len(header) - len(r))
                        md_lines.append("| " + " | ".join(padded[:len(header)]) + " |")
                    md_lines.append("")
        md_lines.append("")

    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines).strip() + "\n")

    return str(out_file)


def pptx_to_text(pptx_path: str, txt_output_path: Optional[str] = None) -> str:
    """Extracts text from PowerPoint (.pptx) into plain text."""
    src = Path(pptx_path)
    if not src.exists():
        raise FileNotFoundError(f"PowerPoint presentation not found: {pptx_path}")

    out_file = Path(txt_output_path) if txt_output_path else get_unique_output_path(src.with_suffix(".txt"))
    from pptx import Presentation
    prs = Presentation(str(src))

    texts = []
    for idx, slide in enumerate(prs.slides, start=1):
        texts.append(f"=== Slide {idx} ===")
        for shape in slide.shapes:
            if shape.has_text_frame:
                for p in shape.text_frame.paragraphs:
                    txt = p.text.strip()
                    if txt:
                        texts.append(txt)
            if shape.has_table:
                for row in shape.table.rows:
                    row_txt = "\t".join(c.text.strip() for c in row.cells)
                    if row_txt:
                        texts.append(row_txt)
        texts.append("")

    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        f.write("\n".join(texts).strip() + "\n")

    return str(out_file)


def text_to_markdown(txt_path: str, md_output_path: Optional[str] = None) -> str:
    """Converts a Plain Text (.txt) file into Markdown (.md)."""
    src = Path(txt_path)
    if not src.exists():
        raise FileNotFoundError(f"Text file not found: {txt_path}")

    out_file = Path(md_output_path) if md_output_path else get_unique_output_path(src.with_suffix(".md"))
    with open(src, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(f"# {src.stem}\n\n" + content.strip() + "\n")

    return str(out_file)


# -----------------------------------------------------------------------------
# Options & Dispatcher
# -----------------------------------------------------------------------------

def get_convert_options(file_path_or_ext: str) -> List[str]:
    """
    Returns available target format keys for a given source file extension.
    E.g.:
      '.pdf' -> ['docx', 'md', 'txt']
      '.xlsx' -> ['csv', 'md']
      '.csv', '.tsv' -> ['xlsx', 'md']
      '.docx' -> ['md', 'txt']
      '.pptx' -> ['md', 'txt']
      '.md' -> ['docx', 'xlsx', 'csv']
      '.txt' -> ['md', 'docx']
    """
    ext = file_path_or_ext.lower().lstrip(".")
    if "." in ext:
        ext = ext.split(".")[-1]

    if ext == "pdf":
        return ["docx", "md", "txt"]
    elif ext == "xlsx":
        return ["csv", "md"]
    elif ext in ["csv", "tsv"]:
        return ["xlsx", "md"]
    elif ext == "docx":
        return ["pdf", "md", "txt"]
    elif ext == "pptx":
        return ["md", "txt"]
    elif ext == "md":
        return ["docx", "xlsx", "csv"]
    elif ext == "txt":
        return ["md", "docx"]
    return []


def convert_file_direct(
    source_path: str,
    target_format: str,
    output_path: Optional[str] = None
) -> str:
    """
    Directly converts a document to target_format without translation.
    target_format: 'docx', 'xlsx', 'md', 'csv', 'txt'
    Returns the path to the converted output file.
    """
    path = Path(source_path)
    src_fmt = path.suffix.lower().lstrip(".")
    tgt_fmt = target_format.lower().lstrip(".")

    out = output_path or str(get_smart_output_path(source_path=path, target_format=f".{tgt_fmt}"))

    key = (src_fmt, tgt_fmt)
    if key == ("pdf", "docx"):
        return pdf_to_docx(str(path), out)
    elif key == ("pdf", "md"):
        return pdf_to_markdown(str(path), out)
    elif key == ("pdf", "txt"):
        return pdf_to_text(str(path), out)
    elif key == ("xlsx", "md"):
        return excel_to_markdown(str(path), out)
    elif key == ("xlsx", "csv"):
        return excel_to_csv(str(path), out)
    elif key in [("csv", "xlsx"), ("tsv", "xlsx")]:
        return csv_to_excel(str(path), out)
    elif key in [("csv", "md"), ("tsv", "md")]:
        return csv_to_markdown(str(path), out)
    elif key == ("md", "xlsx"):
        return markdown_to_excel(str(path), out)
    elif key == ("md", "docx"):
        return markdown_to_docx(str(path), out)
    elif key == ("md", "csv"):
        return markdown_to_csv(str(path), out)
    elif key == ("docx", "pdf"):
        return docx_to_pdf(str(path), out)
    elif key == ("docx", "md"):
        return docx_to_markdown(str(path), out)
    elif key == ("docx", "txt"):
        return docx_to_text(str(path), out)
    elif key == ("pptx", "md"):
        return pptx_to_markdown(str(path), out)
    elif key == ("pptx", "txt"):
        return pptx_to_text(str(path), out)
    elif key == ("txt", "md"):
        return text_to_markdown(str(path), out)
    elif key == ("txt", "docx"):
        return markdown_to_docx(str(path), out)
    else:
        raise ValueError(f"Cannot convert .{src_fmt} to .{tgt_fmt}")

