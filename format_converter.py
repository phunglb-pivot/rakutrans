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
- Word (.docx) -> PDF (.pdf) / Text (.txt)
- PowerPoint (.pptx) -> Markdown (.md) / Text (.txt)
- Markdown (.md) -> Word (.docx) / Excel (.xlsx) / CSV (.csv)
- Text (.txt) -> Markdown (.md) / Word (.docx)
"""

import csv
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, List, Optional, Set, Tuple, Union
from xml.sax.saxutils import escape as xml_escape

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from base_translator import detect_text_encoding
from config import get_smart_output_path, get_unique_output_path
from data_parser import CsvTranslator
from excel_parser import load_workbook_safe
from markdown_parser import match_code_fence_open

_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_MD_SEP_CELL_RE = re.compile(r"^:?-{1,}:?$")
_STRICT_INT_RE = re.compile(r"^-?(?:0|[1-9]\d*)$")
_STRICT_FLOAT_RE = re.compile(r"^-?(?:0|[1-9]\d*)\.(\d+)$")

SOFFICE_TIMEOUT_SECONDS = 90.0
SOFFICE_CANDIDATE_PATHS: Tuple[str, ...] = (
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    "~/Applications/LibreOffice.app/Contents/MacOS/soffice",
    "/opt/homebrew/bin/soffice",
    "/usr/local/bin/soffice",
    "/usr/bin/soffice",
    "/usr/bin/libreoffice",
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    r"%ProgramFiles%\LibreOffice\program\soffice.exe",
    r"%ProgramFiles(x86)%\LibreOffice\program\soffice.exe",
)
UNICODE_PDF_FONT_CANDIDATES: Tuple[str, ...] = (
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    r"C:\Windows\Fonts\arialuni.ttf",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\meiryo.ttc",
    r"C:\Windows\Fonts\msgothic.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
)


# -----------------------------------------------------------------------------
# Shared Deterministic Markdown & Value Helpers
# -----------------------------------------------------------------------------

def _is_md_table_line(line: str) -> bool:
    s = line.strip()
    return len(s) >= 2 and s.startswith("|") and s.endswith("|")


def _split_md_table_row(line: str) -> List[str]:
    """
    Splits a GitHub-Flavored Markdown table row into unescaped cell strings.
    Properly keeps escaped pipes ('\\|') inside their cell while splitting on
    unescaped delimiters ('|' or '\\\\|').
    """
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    # Strip trailing '|' only if unescaped (preceded by an even number of backslashes)
    if s.endswith("|"):
        bs_count = 0
        idx = len(s) - 2
        while idx >= 0 and s[idx] == "\\":
            bs_count += 1
            idx -= 1
        if bs_count % 2 == 0:
            s = s[:-1]

    cells: List[str] = []
    buf: List[str] = []
    i = 0
    n = len(s)

    while i < n:
        ch = s[i]
        if ch == "\\" and i + 1 < n:
            nxt = s[i + 1]
            if nxt in ("|", "\\"):
                buf.append(nxt)
                i += 2
                continue
        if ch == "|":
            cell_raw = "".join(buf).strip()
            cell_clean = re.sub(r"<br\s*/?>", "\n", cell_raw, flags=re.IGNORECASE)
            cells.append(cell_clean)
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1

    cell_raw = "".join(buf).strip()
    cell_clean = re.sub(r"<br\s*/?>", "\n", cell_raw, flags=re.IGNORECASE)
    cells.append(cell_clean)
    return cells


def _is_md_separator_row(cells: List[str], row_idx: int) -> bool:
    """
    Returns True only for the GFM delimiter row immediately following the table header
    (row_idx == 1) where every cell matches ':?-{1,}:?'.
    Preserves real data rows containing '---' in row_idx >= 2.
    """
    if row_idx != 1 or not cells:
        return False
    return all(bool(_MD_SEP_CELL_RE.fullmatch(c.strip())) for c in cells)


def _escape_md_cell(val: Any) -> str:
    if val is None:
        return ""
    s = str(val).replace("\x0b", "\n").replace("\\", "\\\\").replace("|", "\\|")
    s = s.replace("\r\n", "<br>").replace("\n", "<br>")
    return s.strip()


def _coerce_excel_value(raw: str) -> Tuple[Union[int, float, str], Optional[str]]:
    """
    Converts strictly formatted numeric strings to int/float without corrupting
    leading-zero identifiers ('001', '0912...'), version strings ('1.2.3'),
    or non-finite words ('nan', 'inf'). Returns (value, optional_number_format).
    """
    s = raw.strip()
    if not s:
        return s, None

    if _STRICT_INT_RE.fullmatch(s):
        return int(s), None

    m_float = _STRICT_FLOAT_RE.fullmatch(s)
    if m_float:
        frac = m_float.group(1)
        num_format = f"0.{'0' * len(frac)}" if frac.endswith("0") else None
        return float(s), num_format

    return raw, None


def _unique_sheet_name(raw_title: str, existing_names: List[str]) -> str:
    """Builds a valid, unique Excel sheet name <= 31 characters."""
    cleaned = re.sub(r'[\\/*?:\[\]]', "_", (raw_title or "").strip())
    base = cleaned[:31] or "Sheet1"
    if base not in existing_names:
        return base
    counter = 1
    while True:
        suffix = f"_{counter}"
        candidate = f"{(cleaned or 'Sheet')[: max(1, 31 - len(suffix))]}{suffix}"
        if candidate not in existing_names:
            return candidate
        counter += 1


# -----------------------------------------------------------------------------
# PDF Conversions
# -----------------------------------------------------------------------------

_BULLET_START_RE = re.compile(r"^(?:[•●▪◦・\-*]|\d+[.)])\s+")


def _is_cjk_char(ch: str) -> bool:
    o = ord(ch)
    return (
        0x3000 <= o <= 0x30FF
        or 0x3400 <= o <= 0x4DBF
        or 0x4E00 <= o <= 0x9FFF
        or 0xF900 <= o <= 0xFAFF
        or 0xAC00 <= o <= 0xD7AF
        or 0xFF00 <= o <= 0xFFEF
    )


def _join_text_pair(prev: str, curr: str) -> str:
    if not prev:
        return curr
    if not curr:
        return prev
    if len(prev) >= 2 and prev.endswith("-") and prev[-2].isascii() and prev[-2].isalpha() and curr[0].isascii() and curr[0].islower():
        return prev[:-1] + curr
    if _is_cjk_char(prev[-1]) or _is_cjk_char(curr[0]):
        return prev + curr
    return f"{prev} {curr}"


def _clean_pdf_cell_text(raw: Optional[str]) -> str:
    if not raw:
        return ""
    lines = [ln.strip() for ln in str(raw).splitlines() if ln.strip()]
    if not lines:
        return ""
    acc = lines[0]
    for ln in lines[1:]:
        acc = _join_text_pair(acc, ln)
    return acc


def _compute_pdf_body_font_size(pdf_doc) -> float:
    """Computes character-weighted modal font size across the PDF document."""
    size_weights: dict[float, int] = {}
    for page in pdf_doc:
        try:
            page_dict = page.get_text("dict")
        except Exception:
            continue
        for block in page_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    txt = (span.get("text") or "").strip()
                    if not txt:
                        continue
                    sz = round(float(span.get("size", 11.0)), 1)
                    size_weights[sz] = size_weights.get(sz, 0) + len(txt)
    if not size_weights:
        return 11.0
    return max(size_weights.items(), key=lambda kv: kv[1])[0]


def _bbox_overlaps_any(bbox: Tuple[float, float, float, float], targets: List[Tuple[float, float, float, float]]) -> bool:
    x0, y0, x1, y1 = bbox
    area = max(1e-6, (x1 - x0) * (y1 - y0))
    cx, cy = (x0 + x1) * 0.5, (y0 + y1) * 0.5
    for tx0, ty0, tx1, ty1 in targets:
        if tx0 <= cx <= tx1 and ty0 <= cy <= ty1:
            return True
        ix0, iy0 = max(x0, tx0), max(y0, ty0)
        ix1, iy1 = min(x1, tx1), min(y1, ty1)
        if ix1 > ix0 and iy1 > iy0:
            if ((ix1 - ix0) * (iy1 - iy0)) / area >= 0.5:
                return True
    return False


def _extract_pdf_page_elements(page, body_size: float) -> List[Tuple[str, Any]]:
    """
    Extracts structured elements [('h1'|'h2'|'h3'|'p'|'bullet', str) | ('table', List[List[str]])]
    in vertical reading order using PyMuPDF layout coordinates and font sizes.
    """
    positioned: List[Tuple[float, float, float, str, Any]] = []
    table_bboxes: List[Tuple[float, float, float, float]] = []

    if hasattr(page, "find_tables"):
        try:
            found = page.find_tables()
            for tbl in getattr(found, "tables", []):
                raw_rows = tbl.extract() or []
                cleaned_rows = [
                    [_clean_pdf_cell_text(c) for c in row]
                    for row in raw_rows
                ]
                non_empty_rows = [r for r in cleaned_rows if any(c for c in r)]
                if len(non_empty_rows) >= 2 or (non_empty_rows and len(non_empty_rows[0]) >= 2):
                    table_bboxes.append(tuple(tbl.bbox))
                    positioned.append((tbl.bbox[1], tbl.bbox[0], tbl.bbox[3], "table", non_empty_rows))
        except Exception:
            pass

    page_dict = page.get_text("dict")
    for block in page_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        bbox = tuple(block.get("bbox", (0.0, 0.0, 0.0, 0.0)))
        if table_bboxes and _bbox_overlaps_any(bbox, table_bboxes):
            continue

        raw_lines = block.get("lines", [])
        parsed_lines: List[Tuple[Tuple[float, float, float, float], str, float, bool]] = []
        for ln in raw_lines:
            spans = ln.get("spans", [])
            line_text = "".join(sp.get("text", "") for sp in spans).strip()
            if not line_text:
                continue
            total_chars = 0
            weighted_sz = 0.0
            bold_chars = 0
            for sp in spans:
                st = (sp.get("text") or "").strip()
                if not st:
                    continue
                n_ch = len(st)
                total_chars += n_ch
                weighted_sz += float(sp.get("size", body_size)) * n_ch
                if int(sp.get("flags", 0)) & 16:
                    bold_chars += n_ch
            avg_sz = weighted_sz / max(1, total_chars)
            is_bold = bold_chars > (total_chars * 0.5)
            parsed_lines.append((tuple(ln.get("bbox", bbox)), line_text, avg_sz, is_bold))

        if not parsed_lines:
            continue

        heights = [max(1.0, lb[3] - lb[1]) for lb, _, _, _ in parsed_lines]
        median_h = sorted(heights)[len(heights) // 2]

        # Group visual lines into logical paragraphs inside the block
        sub_paras: List[Tuple[float, float, float, List[str], float, bool]] = []
        cur_y0, cur_x0 = parsed_lines[0][0][1], parsed_lines[0][0][0]
        cur_texts = [parsed_lines[0][1]]
        cur_sz_acc = parsed_lines[0][2] * len(parsed_lines[0][1])
        cur_len = len(parsed_lines[0][1])
        cur_bold_len = len(parsed_lines[0][1]) if parsed_lines[0][3] else 0
        prev_y1 = parsed_lines[0][0][3]

        for lb, ltext, lsz, lbold in parsed_lines[1:]:
            v_gap = lb[1] - prev_y1
            starts_bullet = bool(_BULLET_START_RE.match(ltext))
            if starts_bullet or v_gap > max(4.0, median_h * 0.55):
                sub_paras.append((
                    cur_y0,
                    cur_x0,
                    prev_y1,
                    cur_texts,
                    cur_sz_acc / max(1, cur_len),
                    cur_bold_len > (cur_len * 0.5),
                ))
                cur_y0, cur_x0 = lb[1], lb[0]
                cur_texts = [ltext]
                cur_sz_acc = lsz * len(ltext)
                cur_len = len(ltext)
                cur_bold_len = len(ltext) if lbold else 0
            else:
                cur_texts.append(ltext)
                cur_sz_acc += lsz * len(ltext)
                cur_len += len(ltext)
                if lbold:
                    cur_bold_len += len(ltext)
            prev_y1 = lb[3]

        sub_paras.append((
            cur_y0,
            cur_x0,
            prev_y1,
            cur_texts,
            cur_sz_acc / max(1, cur_len),
            cur_bold_len > (cur_len * 0.5),
        ))

        for py0, px0, py1, p_lines, p_sz, p_bold in sub_paras:
            joined = p_lines[0]
            for nxt in p_lines[1:]:
                joined = _join_text_pair(joined, nxt)
            joined = joined.strip()
            if not joined:
                continue

            if _BULLET_START_RE.match(joined):
                clean_bullet = _BULLET_START_RE.sub("", joined, count=1).strip()
                positioned.append((py0, px0, py1, "bullet", clean_bullet))
            elif p_sz >= body_size * 1.55 and len(joined) < 200:
                positioned.append((py0, px0, py1, "h1", joined))
            elif p_sz >= body_size * 1.25 and len(joined) < 200:
                positioned.append((py0, px0, py1, "h2", joined))
            elif (
                (p_sz >= body_size * 1.1 or (p_bold and len(joined) < 100 and not joined.endswith((".", "。", "!", "?"))))
                and len(p_lines) <= 2
            ):
                positioned.append((py0, px0, py1, "h3", joined))
            else:
                positioned.append((py0, px0, py1, "p", joined))

    positioned.sort(key=lambda item: (round(item[0], 1), round(item[1], 1)))

    # Coalesce consecutive body 'p' blocks separated only by single-line leading (common in Notion/Web PDFs)
    line_gap_limit = max(6.5, body_size * 0.55)
    merged: List[Tuple[float, float, float, str, Any]] = []
    for item in positioned:
        y0, x0, y1, kind, payload = item
        if merged and kind == "p" and merged[-1][3] == "p":
            prev_y0, prev_x0, prev_y1, prev_kind, prev_payload = merged[-1]
            v_gap = y0 - prev_y1
            if abs(x0 - prev_x0) <= 12.0 and -1.0 <= v_gap <= line_gap_limit:
                merged[-1] = (prev_y0, prev_x0, max(prev_y1, y1), "p", _join_text_pair(prev_payload, payload))
                continue
        merged.append(item)

    return [(kind, payload) for _, _, _, kind, payload in merged]


def _convert_pdf2docx_cancellable(
    converter: Any,
    out_file: Path,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> None:
    """Runs pdf2docx page parsing with per-page cancellation support when available."""
    if cancel_check and cancel_check():
        raise InterruptedError("Conversion cancelled by user.")

    can_step = (
        cancel_check is not None
        and hasattr(converter, "default_settings")
        and hasattr(converter, "load_pages")
        and hasattr(converter, "parse_document")
        and hasattr(converter, "make_docx")
    )
    if not can_step:
        converter.convert(str(out_file))
        return

    settings = dict(converter.default_settings)
    if settings.get("multi_processing"):
        converter.convert(str(out_file))
        return

    converter.load_pages(0, None, None).parse_document(**settings)
    pages = getattr(converter, "_pages", None)
    if pages is None:
        converter.parse_pages(**settings)
        converter.make_docx(str(out_file), **settings)
        return

    for page in pages:
        if getattr(page, "skip_parsing", False):
            continue
        if cancel_check():
            raise InterruptedError("Conversion cancelled by user.")
        try:
            page.parse(**settings)
        except Exception:
            if settings.get("raw_exceptions") or not (
                not settings.get("debug") and settings.get("ignore_page_error")
            ):
                raise

    if cancel_check():
        raise InterruptedError("Conversion cancelled by user.")
    converter.make_docx(str(out_file), **settings)


def pdf_to_docx(
    pdf_path: str,
    docx_output_path: Optional[str] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> str:
    """
    Converts a PDF (.pdf) document into an editable Microsoft Word (.docx) document.
    Uses pdf2docx to reconstruct flow-based paragraphs, styles, images, and tables,
    with layout-aware PyMuPDF structured fallback.
    """
    src = Path(pdf_path)
    if not src.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    if cancel_check and cancel_check():
        raise InterruptedError("Conversion cancelled by user.")

    out_file = Path(docx_output_path) if docx_output_path else get_unique_output_path(src.with_suffix(".docx"))
    out_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        from pdf2docx import Converter
        cv = Converter(str(src))
        try:
            _convert_pdf2docx_cancellable(cv, out_file, cancel_check=cancel_check)
        finally:
            cv.close()
    except InterruptedError:
        raise
    except Exception:
        import docx
        doc = docx.Document()
        try:
            import pymupdf
            pdoc = pymupdf.open(str(src))
            try:
                body_size = _compute_pdf_body_font_size(pdoc)
                for page_idx, page in enumerate(pdoc):
                    if cancel_check and cancel_check():
                        raise InterruptedError("Conversion cancelled by user.")
                    if page_idx > 0:
                        doc.add_page_break()
                    for kind, payload in _extract_pdf_page_elements(page, body_size):
                        if kind == "h1":
                            doc.add_heading(payload, level=1)
                        elif kind == "h2":
                            doc.add_heading(payload, level=2)
                        elif kind == "h3":
                            doc.add_heading(payload, level=3)
                        elif kind == "bullet":
                            doc.add_paragraph(payload, style="List Bullet")
                        elif kind == "p":
                            doc.add_paragraph(payload)
                        elif kind == "table" and payload:
                            num_cols = max(len(r) for r in payload)
                            tbl = doc.add_table(rows=len(payload), cols=num_cols)
                            tbl.style = "Table Grid"
                            for r_i, row in enumerate(payload):
                                for c_i, val in enumerate(row):
                                    tbl.cell(r_i, c_i).text = val
            finally:
                pdoc.close()
        except InterruptedError:
            raise
        except Exception:
            import pypdf
            reader = pypdf.PdfReader(str(src))
            for page_idx, page in enumerate(reader.pages):
                if cancel_check and cancel_check():
                    raise InterruptedError("Conversion cancelled by user.")
                if page_idx > 0:
                    doc.add_page_break()
                text = page.extract_text() or ""
                for para in text.split("\n\n"):
                    p_str = para.strip()
                    if p_str:
                        doc.add_paragraph(p_str)
        doc.save(str(out_file))

    return str(out_file)


def pdf_to_markdown(pdf_path: str, md_output_path: Optional[str] = None) -> str:
    """
    Converts a PDF file to clean structured Markdown using PyMuPDF layout & table extraction
    (detecting headings relative to body font size and joining wrapped lines without splitting CJK words).
    """
    src = Path(pdf_path)
    if not src.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    out_file = Path(md_output_path) if md_output_path else get_unique_output_path(src.with_suffix(".md"))
    out_file.parent.mkdir(parents=True, exist_ok=True)

    md_lines: List[str] = []
    try:
        import pymupdf
        doc = pymupdf.open(str(src))
        try:
            body_size = _compute_pdf_body_font_size(doc)
            has_h1 = False
            page_chunks: List[str] = []
            for idx, page in enumerate(doc):
                elems = _extract_pdf_page_elements(page, body_size)
                if not elems:
                    continue
                p_out: List[str] = []
                for kind, payload in elems:
                    if kind == "h1":
                        has_h1 = True
                        p_out.append(f"# {payload}\n")
                    elif kind == "h2":
                        p_out.append(f"## {payload}\n")
                    elif kind == "h3":
                        p_out.append(f"### {payload}\n")
                    elif kind == "bullet":
                        p_out.append(f"- {payload}")
                    elif kind == "p":
                        p_out.append(f"{payload}\n")
                    elif kind == "table" and payload:
                        header = [_escape_md_cell(c) for c in payload[0]]
                        p_out.append("\n| " + " | ".join(header) + " |")
                        p_out.append("| " + " | ".join(["---"] * len(header)) + " |")
                        for row in payload[1:]:
                            cells = [_escape_md_cell(c) for c in row]
                            padded = cells + [""] * (len(header) - len(cells))
                            p_out.append("| " + " | ".join(padded[: len(header)]) + " |")
                        p_out.append("")
                page_chunks.append("\n".join(p_out).strip())

            if not has_h1:
                md_lines.append(f"# {src.stem}\n")
            md_lines.append("\n\n".join(c for c in page_chunks if c))
        finally:
            doc.close()

        rendered = "\n".join(md_lines).strip()
        if rendered:
            with open(out_file, "w", encoding="utf-8") as f:
                f.write(rendered + "\n")
            return str(out_file)
    except Exception:
        pass

    # Secondary fallback via MarkItDown or pypdf
    try:
        from markitdown import MarkItDown
        mid = MarkItDown()
        res = mid.convert(str(src))
        if res and res.text_content and res.text_content.strip():
            with open(out_file, "w", encoding="utf-8") as f:
                f.write(res.text_content.strip() + "\n")
            return str(out_file)
    except Exception:
        pass

    md_lines = [f"# {src.stem}\n"]
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
    """Converts a PDF file to clean plain text with unwrapped lines and page dividers."""
    src = Path(pdf_path)
    if not src.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    out_file = Path(txt_output_path) if txt_output_path else get_unique_output_path(src.with_suffix(".txt"))
    out_file.parent.mkdir(parents=True, exist_ok=True)

    pages_text: List[str] = []
    try:
        import pymupdf
        doc = pymupdf.open(str(src))
        try:
            body_size = _compute_pdf_body_font_size(doc)
            for idx, page in enumerate(doc):
                elems = _extract_pdf_page_elements(page, body_size)
                lines_out: List[str] = []
                for kind, payload in elems:
                    if kind == "table":
                        for row in payload:
                            lines_out.append("\t".join(row))
                    elif kind == "bullet":
                        lines_out.append(f"- {payload}")
                    else:
                        lines_out.append(str(payload))
                t = "\n\n".join(lines_out).strip()
                pages_text.append(f"--- Page {idx + 1} ---\n{t}")
        finally:
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

def _merged_row_values(ws_values, ws_formulas) -> List[List[Any]]:
    """
    Reads cell values from a worksheet, falling back to formula strings from ws_formulas
    when data_only=True returns None for uncached formulas.
    """
    val_rows = list(ws_values.iter_rows(values_only=True))
    if ws_formulas is None:
        return [list(r) for r in val_rows]

    f_rows = list(ws_formulas.iter_rows(values_only=True))
    merged_rows: List[List[Any]] = []
    for r_idx, v_row in enumerate(val_rows):
        f_row = f_rows[r_idx] if r_idx < len(f_rows) else ()
        out_row: List[Any] = []
        for c_idx, v_val in enumerate(v_row):
            if v_val is None and c_idx < len(f_row):
                f_val = f_row[c_idx]
                if isinstance(f_val, str) and f_val.strip().startswith("="):
                    out_row.append(f_val)
                    continue
            out_row.append(v_val)
        merged_rows.append(out_row)
    return merged_rows


def excel_to_markdown(xlsx_path: str, md_output_path: Optional[str] = None) -> str:
    """
    Converts an Excel (.xlsx) workbook into a clean, multi-sheet Markdown document.
    Each sheet is represented with a heading and a GitHub-flavored Markdown table.
    Preserves formula text when cached formula results are absent.
    """
    src = Path(xlsx_path)
    if not src.exists():
        raise FileNotFoundError(f"Excel file not found: {xlsx_path}")

    out_file = Path(md_output_path) if md_output_path else get_unique_output_path(src.with_suffix(".md"))
    wb_val = load_workbook_safe(str(src), data_only=True, read_only=True)
    wb_formula = load_workbook_safe(str(src), data_only=False, read_only=True)

    md_lines: List[str] = [f"# {src.stem}\n"]

    try:
        formula_names = set(wb_formula.sheetnames)
        for ws_val in wb_val.worksheets:
            sheet_name = ws_val.title
            ws_formula = wb_formula[sheet_name] if sheet_name in formula_names else None
            raw_rows = _merged_row_values(ws_val, ws_formula)
            filtered_rows = [
                row for row in raw_rows if any(c is not None and str(c).strip() != "" for c in row)
            ]

            if not filtered_rows:
                continue

            md_lines.append(f"## {sheet_name}\n")

            # If row 0 is a single-cell title banner followed by multi-column rows, emit it as a subheading
            first_non_empty = [c for c in filtered_rows[0] if c is not None and str(c).strip() != ""]
            if (
                len(filtered_rows) >= 2
                and len(first_non_empty) == 1
                and sum(1 for c in filtered_rows[1] if c is not None and str(c).strip() != "") >= 2
            ):
                md_lines.append(f"### {str(first_non_empty[0]).strip()}\n")
                filtered_rows = filtered_rows[1:]

            max_cols = max(len(r) for r in filtered_rows)
            active_cols = [
                c
                for c in range(max_cols)
                if any(c < len(r) and r[c] is not None and str(r[c]).strip() != "" for r in filtered_rows)
            ]

            if not active_cols:
                continue

            table_rows = [
                [_escape_md_cell(r[c] if c < len(r) else None) for c in active_cols]
                for r in filtered_rows
            ]

            header_cells = table_rows[0]
            md_lines.append("| " + " | ".join(header_cells) + " |")
            md_lines.append("| " + " | ".join(["---"] * len(header_cells)) + " |")

            for data_row in table_rows[1:]:
                padded = data_row + [""] * (len(header_cells) - len(data_row))
                md_lines.append("| " + " | ".join(padded[: len(header_cells)]) + " |")

            md_lines.append("")
    finally:
        wb_val.close()
        wb_formula.close()

    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines).strip() + "\n")

    return str(out_file)


def markdown_to_excel(md_path: str, xlsx_output_path: Optional[str] = None) -> str:
    """
    Converts a Markdown (.md) document into a styled Excel (.xlsx) workbook.
    Preserves tables (including escaped pipes and dash-only cells), leading zeros,
    subheadings, lists, code blocks, and prose paragraphs without leaving orphan sheets.
    """
    src = Path(md_path)
    if not src.exists():
        raise FileNotFoundError(f"Markdown file not found: {md_path}")

    out_file = Path(xlsx_output_path) if xlsx_output_path else get_unique_output_path(src.with_suffix(".xlsx"))
    enc = detect_text_encoding(src)
    with open(src, "r", encoding=enc, errors="replace") as f:
        content = f.read()

    wb = openpyxl.Workbook()
    default_sheet = wb.active
    default_sheet.title = "Document"

    header_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    title_font = Font(name="Segoe UI", size=13, bold=True, color="1F4E79")
    subhead_font = Font(name="Segoe UI", size=11, bold=True, color="1F4E79")
    normal_font = Font(name="Segoe UI", size=10)
    code_font = Font(name="Consolas", size=10)
    thin_border = Border(
        left=Side(style="thin", color="D9D9D9"),
        right=Side(style="thin", color="D9D9D9"),
        top=Side(style="thin", color="D9D9D9"),
        bottom=Side(style="thin", color="D9D9D9"),
    )
    center_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left_align = Alignment(horizontal="left", vertical="center", wrap_text=True)

    lines = content.splitlines()
    current_sheet = default_sheet
    current_row = 1
    sheet_has_content = False
    has_named_section_sheet = False
    pending_doc_title: Optional[str] = None
    idx = 0

    def flush_pending_title():
        nonlocal current_row, pending_doc_title, sheet_has_content
        if pending_doc_title is not None:
            c = current_sheet.cell(row=current_row, column=1, value=pending_doc_title)
            c.font = title_font
            current_row += 2
            pending_doc_title = None
            sheet_has_content = True

    while idx < len(lines):
        raw_line = lines[idx]
        line = raw_line.strip()
        if not line:
            idx += 1
            continue

        # Fenced code block (must be checked before '#' headings and '|' tables)
        fence_open = match_code_fence_open(raw_line)
        if fence_open:
            flush_pending_title()
            fence_char, fence_len = fence_open
            close_re = re.compile(rf"^\s*{re.escape(fence_char)}{{{fence_len},}}\s*$")
            code_lines: List[str] = []
            idx += 1
            while idx < len(lines) and not close_re.match(lines[idx]):
                code_lines.append(lines[idx])
                idx += 1
            if idx < len(lines):
                idx += 1
            if code_lines:
                c = current_sheet.cell(row=current_row, column=1, value="\n".join(code_lines))
                c.font = code_font
                c.alignment = left_align
                current_row += 2
                sheet_has_content = True
            continue

        heading_m = _MD_HEADING_RE.match(line)
        if heading_m:
            level = len(heading_m.group(1))
            heading_text = heading_m.group(2).strip()
            if level == 1:
                if not sheet_has_content and not has_named_section_sheet and pending_doc_title is None:
                    pending_doc_title = heading_text
                else:
                    flush_pending_title()
                    c = current_sheet.cell(row=current_row, column=1, value=heading_text)
                    c.font = title_font
                    current_row += 2
                    sheet_has_content = True
            elif level == 2:
                if not sheet_has_content and not has_named_section_sheet:
                    # Reuse initial default_sheet cleanly without creating an orphan "Document" sheet
                    current_sheet.title = _unique_sheet_name(heading_text, [])
                    if pending_doc_title:
                        wb.properties.title = pending_doc_title
                        pending_doc_title = None
                else:
                    new_name = _unique_sheet_name(heading_text, list(wb.sheetnames))
                    current_sheet = wb.create_sheet(title=new_name)
                    current_row = 1
                has_named_section_sheet = True
                sheet_has_content = False
            else:
                flush_pending_title()
                c = current_sheet.cell(row=current_row, column=1, value=heading_text)
                c.font = subhead_font
                current_row += 1
                sheet_has_content = True
            idx += 1
            continue

        if _is_md_table_line(line):
            flush_pending_title()
            table_lines: List[str] = []
            while idx < len(lines) and _is_md_table_line(lines[idx]):
                table_lines.append(lines[idx].strip())
                idx += 1

            table_data: List[List[str]] = []
            for t_idx, t_line in enumerate(table_lines):
                cells = _split_md_table_row(t_line)
                if _is_md_separator_row(cells, t_idx):
                    continue
                table_data.append(cells)

            for r_idx, row_values in enumerate(table_data):
                is_header = r_idx == 0
                for c_idx, val in enumerate(row_values):
                    cell = current_sheet.cell(row=current_row + r_idx, column=c_idx + 1)
                    if is_header:
                        cell.value = val
                    else:
                        coerced_val, num_fmt = _coerce_excel_value(val)
                        cell.value = coerced_val
                        if num_fmt:
                            cell.number_format = num_fmt

                    cell.border = thin_border
                    if is_header:
                        cell.font = header_font
                        cell.fill = header_fill
                        cell.alignment = center_align
                    else:
                        cell.font = normal_font
                        cell.alignment = left_align

                line_count = max((str(v).count("\n") + 1 for v in row_values), default=1)
                base_h = 24 if is_header else 20
                current_sheet.row_dimensions[current_row + r_idx].height = max(base_h, line_count * 16)

            if table_data:
                current_row += len(table_data) + 1
                sheet_has_content = True
            continue

        # Prose / list / blockquote fallback (preserve instead of silently skipping)
        flush_pending_title()
        c = current_sheet.cell(row=current_row, column=1, value=line)
        c.font = normal_font
        c.alignment = left_align
        current_row += 1
        sheet_has_content = True
        idx += 1

    # If document had only '# Title' and nothing else, flush it so sheet isn't blank
    if not sheet_has_content and pending_doc_title is not None:
        flush_pending_title()

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
    wb.close()
    return str(out_file)


# -----------------------------------------------------------------------------
# CSV Conversions
# -----------------------------------------------------------------------------

def _detect_csv_params(file_path: Path) -> Tuple[str, str]:
    """Detects encoding and delimiter deterministically via shared helpers."""
    enc = detect_text_encoding(file_path)
    delim = CsvTranslator._detect_delimiter(file_path, enc)
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
    ws.title = _unique_sheet_name(src.stem, [])

    header_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    normal_font = Font(name="Segoe UI", size=10)
    thin_border = Border(
        left=Side(style="thin", color="D9D9D9"),
        right=Side(style="thin", color="D9D9D9"),
        top=Side(style="thin", color="D9D9D9"),
        bottom=Side(style="thin", color="D9D9D9"),
    )
    left_align = Alignment(horizontal="left", vertical="center")
    center_align = Alignment(horizontal="center", vertical="center")

    with open(src, "r", encoding=enc, errors="replace", newline="") as f:
        reader = csv.reader(f, delimiter=delim)
        for r_idx, row in enumerate(reader, start=1):
            is_header = r_idx == 1
            for c_idx, val in enumerate(row, start=1):
                cell = ws.cell(row=r_idx, column=c_idx)
                val_str = str(val).strip()
                if is_header:
                    cell.value = val_str
                else:
                    coerced_val, num_fmt = _coerce_excel_value(val_str)
                    cell.value = coerced_val
                    if num_fmt:
                        cell.number_format = num_fmt

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
    wb.close()
    return str(out_file)


def excel_to_csv(xlsx_path: str, csv_output_path: Optional[str] = None) -> str:
    """
    Exports Excel (.xlsx) worksheet to CSV with UTF-8-SIG.
    Uses the active sheet if non-empty, otherwise falls back to the first non-empty sheet,
    preserving formula strings when cached values are missing.
    """
    src = Path(xlsx_path)
    if not src.exists():
        raise FileNotFoundError(f"Excel file not found: {xlsx_path}")

    out_file = Path(csv_output_path) if csv_output_path else get_unique_output_path(src.with_suffix(".csv"))
    wb_val = load_workbook_safe(str(src), data_only=True, read_only=True)
    wb_formula = load_workbook_safe(str(src), data_only=False, read_only=True)

    try:
        formula_names = set(wb_formula.sheetnames)
        non_empty: List[List[Any]] = []
        active_ws = wb_val.active
        if active_ws is not None and hasattr(active_ws, "iter_rows"):
            ws_formula = wb_formula[active_ws.title] if active_ws.title in formula_names else None
            rows = _merged_row_values(active_ws, ws_formula)
            non_empty = [r for r in rows if any(c is not None and str(c).strip() != "" for c in r)]

        if not non_empty:
            for cand_val in wb_val.worksheets:
                if cand_val is active_ws:
                    continue
                cand_f = wb_formula[cand_val.title] if cand_val.title in formula_names else None
                cand_rows = _merged_row_values(cand_val, cand_f)
                cand_non_empty = [
                    r for r in cand_rows if any(c is not None and str(c).strip() != "" for c in r)
                ]
                if cand_non_empty:
                    non_empty = cand_non_empty
                    break

        out_file.parent.mkdir(parents=True, exist_ok=True)
        with open(out_file, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            for row in non_empty:
                writer.writerow(["" if c is None else str(c) for c in row])
    finally:
        wb_val.close()
        wb_formula.close()

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
                rows.append([_escape_md_cell(c) for c in r])

    out_file.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        out_file.write_text(f"# {src.stem}\n\n*Empty CSV dataset*\n", encoding="utf-8")
        return str(out_file)

    md_lines = [f"# {src.stem}\n"]
    header = rows[0]
    md_lines.append("| " + " | ".join(header) + " |")
    md_lines.append("| " + " | ".join(["---"] * len(header)) + " |")

    for data_row in rows[1:]:
        padded = data_row + [""] * (len(header) - len(data_row))
        md_lines.append("| " + " | ".join(padded[: len(header)]) + " |")

    with open(out_file, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines).strip() + "\n")

    return str(out_file)


def markdown_to_csv(md_path: str, csv_output_path: Optional[str] = None) -> str:
    """Extracts tables from a Markdown file and writes to CSV."""
    src = Path(md_path)
    if not src.exists():
        raise FileNotFoundError(f"Markdown file not found: {md_path}")

    out_file = Path(csv_output_path) if csv_output_path else get_unique_output_path(src.with_suffix(".csv"))
    enc = detect_text_encoding(src)
    with open(src, "r", encoding=enc, errors="replace") as f:
        content = f.read()

    lines = content.splitlines()
    table_rows: List[List[str]] = []
    idx = 0
    in_fence = False
    fence_char = ""
    fence_len = 0

    while idx < len(lines):
        raw_line = lines[idx]
        if not in_fence:
            fence_open = match_code_fence_open(raw_line)
            if fence_open:
                in_fence = True
                fence_char, fence_len = fence_open
                idx += 1
                continue
        if in_fence:
            if re.match(rf"^\s*{re.escape(fence_char)}{{{fence_len},}}\s*$", raw_line):
                in_fence = False
            idx += 1
            continue

        if _is_md_table_line(raw_line):
            block_idx = 0
            while idx < len(lines) and _is_md_table_line(lines[idx]):
                cells = _split_md_table_row(lines[idx])
                if not _is_md_separator_row(cells, block_idx):
                    table_rows.append(cells)
                block_idx += 1
                idx += 1
            continue
        idx += 1

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
        *(
            os.path.expandvars(os.path.expanduser(raw_path))
            for raw_path in SOFFICE_CANDIDATE_PATHS
        ),
    ]
    for c in candidates:
        if c and os.path.exists(c) and os.path.isfile(c):
            return c
    return None


def _register_unicode_pdf_font() -> str:
    """Registers the broadest Unicode/CJK font available for ReportLab fallback."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    for fp in UNICODE_PDF_FONT_CANDIDATES:
        if os.path.exists(fp):
            try:
                fname = f"RakuDocxFont_{re.sub(r'[^A-Za-z0-9_]', '_', os.path.basename(fp))}"
                if fname in pdfmetrics.getRegisteredFontNames():
                    return fname
                if fp.lower().endswith(".ttc"):
                    pdfmetrics.registerFont(TTFont(fname, fp, subfontIndex=0))
                else:
                    pdfmetrics.registerFont(TTFont(fname, fp))
                return fname
            except Exception:
                continue
    return "Helvetica"


def _rl_safe_text(text: str) -> str:
    """Escapes XML markup characters for ReportLab Paragraph and preserves line breaks."""
    return xml_escape(text).replace("\r\n", "\n").replace("\n", "<br/>")


def _iter_docx_body_blocks(doc):
    """
    Yields ('p', Paragraph) or ('tbl', Table) in document reading order across
    body paragraphs, tables, Content Controls (<w:sdt>), and text boxes (<w:txbxContent>).
    """
    import docx

    w_ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    p_tag = f"{w_ns}p"
    tbl_tag = f"{w_ns}tbl"
    sdt_tag = f"{w_ns}sdt"
    sdt_content_tag = f"{w_ns}sdtContent"
    txbx_tag = f"{w_ns}txbxContent"

    seen_elems: Set[Any] = set()

    def walk(container_elem):
        for child in container_elem:
            tag = child.tag
            if tag == p_tag:
                if child not in seen_elems:
                    seen_elems.add(child)
                    yield ("p", docx.text.paragraph.Paragraph(child, doc))
                # Also yield any text box paragraphs nested inside this paragraph
                for tb_p in child.xpath(".//w:txbxContent//w:p"):
                    if tb_p not in seen_elems:
                        seen_elems.add(tb_p)
                        yield ("p", docx.text.paragraph.Paragraph(tb_p, doc))
            elif tag == tbl_tag:
                if child not in seen_elems:
                    seen_elems.add(child)
                    yield ("tbl", docx.table.Table(child, doc))
            elif tag == sdt_tag:
                content = child.find(sdt_content_tag)
                if content is not None:
                    yield from walk(content)
            elif tag in (sdt_content_tag, txbx_tag):
                yield from walk(child)

    yield from walk(doc.element.body)


def _dedup_docx_table_rows(table) -> List[List[Tuple[Any, bool]]]:
    """
    Extracts table rows as (cell, is_primary_tc) pairs so merged table cells
    are only emitted once instead of duplicating cell text/images across spans.
    """
    seen_tcs: Set[Any] = set()
    rows_out: List[List[Tuple[Any, bool]]] = []
    for row in table.rows:
        row_cells: List[Tuple[Any, bool]] = []
        for cell in row.cells:
            is_primary = cell._tc not in seen_tcs
            if is_primary:
                seen_tcs.add(cell._tc)
            row_cells.append((cell, is_primary))
        rows_out.append(row_cells)
    return rows_out


def _compute_soffice_timeout(src_path: Path) -> float:
    """Scales LibreOffice PDF export timeout with input DOCX size for large (>10MB) files."""
    try:
        size_mb = src_path.stat().st_size / (1024.0 * 1024.0)
    except OSError:
        size_mb = 0.0
    return max(SOFFICE_TIMEOUT_SECONDS, min(600.0, SOFFICE_TIMEOUT_SECONDS + size_mb * 15.0))


def docx_to_pdf(
    docx_path: str,
    pdf_output_path: Optional[str] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> str:
    """
    Converts a Microsoft Word (.docx) document to a PDF document.
    Attempts system engines (LibreOffice CLI / docx2pdf) first,
    falling back to pure-Python flow-based rendering via python-docx and ReportLab Platypus.
    """
    src = Path(docx_path)
    if not src.exists():
        raise FileNotFoundError(f"Word document not found: {docx_path}")

    if cancel_check and cancel_check():
        raise InterruptedError("Conversion cancelled by user.")

    out_file = Path(pdf_output_path) if pdf_output_path else get_unique_output_path(src.with_suffix(".pdf"))
    out_file.parent.mkdir(parents=True, exist_ok=True)

    # 1. Try LibreOffice CLI if available (poll so user cancellation terminates soffice immediately)
    import shutil
    import subprocess
    soffice_bin = _find_soffice_binary()
    if soffice_bin:
        try:
            import tempfile
            soffice_timeout = _compute_soffice_timeout(src)
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
                with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
                    deadline = time.monotonic() + soffice_timeout
                    while True:
                        if cancel_check and cancel_check():
                            proc.terminate()
                            try:
                                proc.wait(timeout=3.0)
                            except subprocess.TimeoutExpired:
                                proc.kill()
                            proc.communicate()
                            raise InterruptedError("Conversion cancelled by user.")
                        rc = proc.poll()
                        if rc is not None:
                            _, err_b = proc.communicate()
                            if rc != 0:
                                raise subprocess.CalledProcessError(rc, cmd, stderr=err_b)
                            break
                        if time.monotonic() >= deadline:
                            proc.terminate()
                            try:
                                proc.wait(timeout=3.0)
                            except subprocess.TimeoutExpired:
                                proc.kill()
                            proc.communicate()
                            raise subprocess.TimeoutExpired(cmd, soffice_timeout)
                        time.sleep(0.2)

                gen_pdf = Path(tmp_dir) / f"{src.stem}.pdf"
                if gen_pdf.exists():
                    shutil.copy2(gen_pdf, out_file)
                    return str(out_file)
        except InterruptedError:
            raise
        except Exception as e:
            print(f"[Warning] LibreOffice conversion failed, falling back to python renderer: {e}")

    # 2. Try docx2pdf if installed (macOS/Windows with MS Word)
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

    font_name = _register_unicode_pdf_font()
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
    usable_width = letter[0] - 80.0

    def get_element_images(elem, max_w: float = 480.0, max_h: float = 380.0):
        imgs = []
        try:
            blips = elem.xpath(".//a:blip/@r:embed")
            for rId in blips:
                if rId in doc.part.rels:
                    rel = doc.part.rels[rId]
                    if "image" in rel.target_ref:
                        blob = rel.target_part.blob
                        with PILImage.open(io.BytesIO(blob)) as im:
                            w, h = im.size
                        scale = min(1.0, max_w / max(1, w), max_h / max(1, h))
                        disp_w = max(10.0, w * scale)
                        disp_h = max(10.0, h * scale)
                        imgs.append(RLImage(io.BytesIO(blob), width=disp_w, height=disp_h))
        except Exception:
            pass
        return imgs

    for kind, obj in _iter_docx_body_blocks(doc):
        if cancel_check and cancel_check():
            raise InterruptedError("Conversion cancelled by user.")
        if kind == "p":
            p = obj
            for img in get_element_images(p._p):
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
                story.append(Paragraph(_rl_safe_text(text), st))
        elif kind == "tbl":
            table = obj
            dedup_rows = _dedup_docx_table_rows(table)
            table_data = []
            max_cols = max((len(r) for r in dedup_rows), default=0)
            col_w = usable_width / max(1, max_cols)
            for row_cells in dedup_rows:
                row_data = []
                for cell, is_primary in row_cells:
                    if not is_primary:
                        row_data.append(Paragraph("", body_style))
                        continue
                    cell_flowables = []
                    ctext = cell.text.strip()
                    if ctext:
                        cell_flowables.append(Paragraph(_rl_safe_text(ctext), body_style))
                    cell_imgs = get_element_images(cell._tc, max_w=max(30.0, col_w - 12.0), max_h=240.0)
                    cell_flowables.extend(cell_imgs)
                    if not cell_flowables:
                        cell_flowables.append(Paragraph("", body_style))
                    row_data.append(cell_flowables if len(cell_flowables) > 1 else cell_flowables[0])
                table_data.append(row_data)
            if table_data:
                col_widths = [usable_width / max_cols] * max_cols if max_cols > 0 else None
                rl_table = Table(table_data, colWidths=col_widths, repeatRows=0)
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
    try:
        pdf_doc.build(story)
    except Exception:
        # Fallback if a single giant table row exceeds ReportLab's single-page LayoutError limit
        flat_story = []
        for item in story:
            if isinstance(item, Table):
                for row in item._cellvalues:
                    for cell_item in row:
                        if isinstance(cell_item, list):
                            flat_story.extend(cell_item)
                        else:
                            flat_story.append(cell_item)
            else:
                flat_story.append(item)
        pdf_doc.build(flat_story or [Paragraph("", body_style)])
    return str(out_file)


def docx_to_markdown(docx_path: str, md_output_path: Optional[str] = None) -> str:
    """
    Converts a Microsoft Word (.docx) document to GitHub Flavored Markdown,
    strictly preserving the original interleaving order of paragraphs, text boxes, SDTs, and tables.
    """
    src = Path(docx_path)
    if not src.exists():
        raise FileNotFoundError(f"Word document not found: {docx_path}")

    out_file = Path(md_output_path) if md_output_path else get_unique_output_path(src.with_suffix(".md"))
    import docx
    doc = docx.Document(str(src))

    md_lines: List[str] = []
    has_top_heading = any(
        p.text.strip() and ("heading 1" in ((p.style.name if p.style else "").lower()) or "title" in ((p.style.name if p.style else "").lower()))
        for p in doc.paragraphs[:3]
    )
    if not has_top_heading:
        md_lines.append(f"# {src.stem}\n")

    for kind, obj in _iter_docx_body_blocks(doc):
        if kind == "p":
            p = obj
            txt = p.text.strip()
            if not txt:
                continue
            style_name = p.style.name.lower() if p.style else ""
            if "title" in style_name:
                md_lines.append(f"# {txt}\n")
            elif "heading 1" in style_name:
                md_lines.append(f"## {txt}\n" if not has_top_heading else f"# {txt}\n")
            elif "heading 2" in style_name:
                md_lines.append(f"### {txt}\n" if not has_top_heading else f"## {txt}\n")
            elif "heading 3" in style_name:
                md_lines.append(f"#### {txt}\n" if not has_top_heading else f"### {txt}\n")
            elif "heading 4" in style_name:
                md_lines.append(f"##### {txt}\n" if not has_top_heading else f"#### {txt}\n")
            elif "list bullet" in style_name:
                md_lines.append(f"- {txt}")
            else:
                md_lines.append(f"{txt}\n")
        elif kind == "tbl":
            t_rows = [
                [_escape_md_cell(cell.text) if is_primary else "" for cell, is_primary in row_cells]
                for row_cells in _dedup_docx_table_rows(obj)
            ]
            if t_rows:
                header = t_rows[0]
                md_lines.append("\n| " + " | ".join(header) + " |")
                md_lines.append("| " + " | ".join(["---"] * len(header)) + " |")
                for row in t_rows[1:]:
                    padded = row + [""] * (len(header) - len(row))
                    md_lines.append("| " + " | ".join(padded[: len(header)]) + " |")
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

    enc = detect_text_encoding(src)
    with open(src, "r", encoding=enc, errors="replace") as f:
        content = f.read()

    lines = content.splitlines()
    idx = 0
    while idx < len(lines):
        raw_line = lines[idx]
        stripped = raw_line.strip()
        if not stripped:
            idx += 1
            continue

        # Fenced code blocks
        fence_open = match_code_fence_open(raw_line)
        if fence_open:
            fence_char, fence_len = fence_open
            close_re = re.compile(rf"^\s*{re.escape(fence_char)}{{{fence_len},}}\s*$")
            code_lines: List[str] = []
            idx += 1
            while idx < len(lines) and not close_re.match(lines[idx]):
                code_lines.append(lines[idx])
                idx += 1
            if idx < len(lines):
                idx += 1
            if code_lines:
                p = doc.add_paragraph()
                run = p.add_run("\n".join(code_lines))
                run.font.name = "Courier New"
            continue

        heading_m = _MD_HEADING_RE.match(stripped)
        if heading_m:
            level = min(len(heading_m.group(1)) - 1, 9)
            doc.add_heading(heading_m.group(2).strip(), level=level)
            idx += 1
            continue

        if _is_md_table_line(stripped):
            table_lines = []
            while idx < len(lines) and _is_md_table_line(lines[idx]):
                table_lines.append(lines[idx].strip())
                idx += 1

            parsed_rows = []
            for t_idx, tl in enumerate(table_lines):
                cells = _split_md_table_row(tl)
                if _is_md_separator_row(cells, t_idx):
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

        if re.match(r"^[-*+]\s+", stripped):
            item_text = re.sub(r"^[-*+]\s+", "", stripped)
            doc.add_paragraph(item_text, style="List Bullet")
            idx += 1
            continue

        p = doc.add_paragraph()
        p.add_run(stripped)
        idx += 1

    out_file.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_file))
    return str(out_file)


def text_to_docx(txt_path: str, docx_output_path: Optional[str] = None) -> str:
    """Converts a Plain Text (.txt) file into a clean Word (.docx) document without Markdown heuristics."""
    src = Path(txt_path)
    if not src.exists():
        raise FileNotFoundError(f"Text file not found: {txt_path}")

    out_file = Path(docx_output_path) if docx_output_path else get_unique_output_path(src.with_suffix(".docx"))
    import docx
    doc = docx.Document()

    enc = detect_text_encoding(src)
    with open(src, "r", encoding=enc, errors="replace") as f:
        content = f.read()

    for block in content.split("\n\n"):
        cleaned = block.strip("\r\n")
        if cleaned.strip():
            doc.add_paragraph(cleaned)

    out_file.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_file))
    return str(out_file)


def docx_to_text(docx_path: str, txt_output_path: Optional[str] = None) -> str:
    """Extracts text from Word document into plain text (.txt) in document order."""
    src = Path(docx_path)
    if not src.exists():
        raise FileNotFoundError(f"Word document not found: {docx_path}")

    out_file = Path(txt_output_path) if txt_output_path else get_unique_output_path(src.with_suffix(".txt"))
    import docx
    doc = docx.Document(str(src))

    texts: List[str] = []
    for kind, obj in _iter_docx_body_blocks(doc):
        if kind == "p":
            if obj.text.strip():
                texts.append(obj.text.strip())
        elif kind == "tbl":
            for row_cells in _dedup_docx_table_rows(obj):
                row_text = "\t".join(
                    cell.text.strip() for cell, is_primary in row_cells if is_primary and cell.text.strip()
                )
                if row_text.strip():
                    texts.append(row_text)

    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        f.write("\n\n".join(texts).strip() + "\n")

    return str(out_file)


def _dedup_pptx_table_rows(table) -> List[List[Tuple[Any, bool]]]:
    seen_tcs: Set[Any] = set()
    rows_out: List[List[Tuple[Any, bool]]] = []
    for row in table.rows:
        row_cells: List[Tuple[Any, bool]] = []
        for cell in row.cells:
            is_primary = cell._tc not in seen_tcs
            if is_primary:
                seen_tcs.add(cell._tc)
            row_cells.append((cell, is_primary))
        rows_out.append(row_cells)
    return rows_out


def pptx_to_markdown(pptx_path: str, md_output_path: Optional[str] = None) -> str:
    """Extracts slides outline (including grouped shapes), tables, and speaker notes to Markdown."""
    src = Path(pptx_path)
    if not src.exists():
        raise FileNotFoundError(f"PowerPoint presentation not found: {pptx_path}")

    out_file = Path(md_output_path) if md_output_path else get_unique_output_path(src.with_suffix(".md"))
    from pptx import Presentation
    from pptx_parser import iter_pptx_shapes

    prs = Presentation(str(src))

    md_lines = [f"# {src.stem}\n"]
    for idx, slide in enumerate(prs.slides, start=1):
        md_lines.append(f"## Slide {idx}\n")
        title_shape = getattr(slide.shapes, "title", None)
        for shape in iter_pptx_shapes(slide.shapes):
            if shape.has_text_frame:
                is_title = title_shape is not None and shape == title_shape
                for p in shape.text_frame.paragraphs:
                    txt = p.text.replace("\x0b", " ").strip()
                    if txt:
                        md_lines.append(f"### {txt}" if is_title else f"- {txt}")
            if shape.has_table:
                t_rows = [
                    [_escape_md_cell(c.text) if is_primary else "" for c, is_primary in row_cells]
                    for row_cells in _dedup_pptx_table_rows(shape.table)
                ]
                if t_rows:
                    header = t_rows[0]
                    md_lines.append("\n| " + " | ".join(header) + " |")
                    md_lines.append("| " + " | ".join(["---"] * len(header)) + " |")
                    for r in t_rows[1:]:
                        padded = r + [""] * (len(header) - len(r))
                        md_lines.append("| " + " | ".join(padded[: len(header)]) + " |")
                    md_lines.append("")

        if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
            notes_txt = slide.notes_slide.notes_text_frame.text.replace("\x0b", "\n").strip()
            if notes_txt:
                md_lines.append(f"\n> **Notes:** {notes_txt}\n")

        md_lines.append("")

    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines).strip() + "\n")

    return str(out_file)


def pptx_to_text(pptx_path: str, txt_output_path: Optional[str] = None) -> str:
    """Extracts text from PowerPoint (.pptx) including grouped shapes and speaker notes into plain text."""
    src = Path(pptx_path)
    if not src.exists():
        raise FileNotFoundError(f"PowerPoint presentation not found: {pptx_path}")

    out_file = Path(txt_output_path) if txt_output_path else get_unique_output_path(src.with_suffix(".txt"))
    from pptx import Presentation
    from pptx_parser import iter_pptx_shapes

    prs = Presentation(str(src))

    texts = []
    for idx, slide in enumerate(prs.slides, start=1):
        texts.append(f"=== Slide {idx} ===")
        for shape in iter_pptx_shapes(slide.shapes):
            if shape.has_text_frame:
                for p in shape.text_frame.paragraphs:
                    txt = p.text.replace("\x0b", "\n").strip()
                    if txt:
                        texts.append(txt)
            if shape.has_table:
                for row_cells in _dedup_pptx_table_rows(shape.table):
                    row_txt = "\t".join(
                        c.text.replace("\x0b", " ").strip()
                        for c, is_primary in row_cells
                        if is_primary and c.text.strip()
                    )
                    if row_txt.strip():
                        texts.append(row_txt)

        if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
            notes_txt = slide.notes_slide.notes_text_frame.text.replace("\x0b", "\n").strip()
            if notes_txt:
                texts.append(f"[Notes] {notes_txt}")

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
    enc = detect_text_encoding(src)
    with open(src, "r", encoding=enc, errors="replace") as f:
        content = f.read()

    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(f"# {src.stem}\n\n" + content.strip() + "\n")

    return str(out_file)


# -----------------------------------------------------------------------------
# Options & Unified Registry Dispatcher
# -----------------------------------------------------------------------------

_CONVERSION_REGISTRY = {
    ("pdf", "docx"): pdf_to_docx,
    ("pdf", "md"): pdf_to_markdown,
    ("pdf", "txt"): pdf_to_text,
    ("xlsx", "csv"): excel_to_csv,
    ("xlsx", "md"): excel_to_markdown,
    ("csv", "xlsx"): csv_to_excel,
    ("csv", "md"): csv_to_markdown,
    ("tsv", "xlsx"): csv_to_excel,
    ("tsv", "md"): csv_to_markdown,
    ("docx", "pdf"): docx_to_pdf,
    ("docx", "md"): docx_to_markdown,
    ("docx", "txt"): docx_to_text,
    ("pptx", "md"): pptx_to_markdown,
    ("pptx", "txt"): pptx_to_text,
    ("md", "docx"): markdown_to_docx,
    ("md", "xlsx"): markdown_to_excel,
    ("md", "csv"): markdown_to_csv,
    ("txt", "md"): text_to_markdown,
    ("txt", "docx"): text_to_docx,
}


def _extract_source_ext(file_path_or_ext: Union[str, Path]) -> str:
    raw = str(file_path_or_ext).lower().strip()
    if not raw:
        return ""
    if raw.startswith(".") and "/" not in raw and "\\" not in raw:
        return raw.lstrip(".")
    suffix = Path(raw).suffix.lower().lstrip(".")
    if suffix:
        return suffix
    if "/" not in raw and "\\" not in raw:
        return raw
    return ""


def get_convertible_extensions() -> List[str]:
    """Returns sorted list of supported source extensions (e.g. ['.csv', '.docx', ...]) from _CONVERSION_REGISTRY."""
    return sorted({f".{src}" for (src, _) in _CONVERSION_REGISTRY})


def is_convert_supported(file_path_or_ext: Union[str, Path]) -> bool:
    """Returns True if source file extension has at least one conversion target in _CONVERSION_REGISTRY."""
    ext = _extract_source_ext(file_path_or_ext)
    return bool(ext) and any(src == ext for (src, _) in _CONVERSION_REGISTRY)


def get_convert_options(file_path_or_ext: Union[str, Path]) -> List[str]:
    """
    Returns available target format keys for a given source file extension,
    derived directly from _CONVERSION_REGISTRY (Single Source of Truth).
    """
    ext = _extract_source_ext(file_path_or_ext)
    if not ext:
        return []
    return [tgt for (src, tgt) in _CONVERSION_REGISTRY if src == ext]


def convert_file_direct(
    source_path: str,
    target_format: str,
    output_path: Optional[str] = None,
) -> str:
    """
    Directly converts a document to target_format without translation.
    Returns the path to the converted output file.
    """
    path = Path(source_path)
    src_fmt = path.suffix.lower().lstrip(".")
    tgt_fmt = target_format.lower().lstrip(".")

    handler = _CONVERSION_REGISTRY.get((src_fmt, tgt_fmt))
    if handler is None:
        raise ValueError(f"Cannot convert .{src_fmt} to .{tgt_fmt}")

    out = output_path or str(get_smart_output_path(source_path=path, target_format=f".{tgt_fmt}"))
    return handler(str(path), out)
