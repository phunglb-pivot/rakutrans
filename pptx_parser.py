"""
PowerPoint (.pptx) parsing and translation engine for RakuTrans AI.
Uses python-pptx to translate slide decks while preserving slide layouts,
shapes, nested groups, tables, inline run formatting, and speaker notes.
"""

import copy
from pathlib import Path
from typing import List, Dict, Set, Callable, Optional, Any, Tuple
from lxml import etree
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.text.text import _Paragraph

from base_translator import (
    BaseTranslator,
    build_inline_tagged_text,
    contains_literal_inline_tags,
    count_words_multilingual,
    parse_inline_tagged_text,
    safe_save_file,
    should_translate_text,
    strip_inline_tags,
)
from config import TranslationOptions, get_smart_output_path

_A_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_A_RPR_TAG = f"{_A_NS}rPr"
_A_R_TAG = f"{_A_NS}r"
_A_BR_TAG = f"{_A_NS}br"
_A_T_TAG = f"{_A_NS}t"
_A_FLD_TAG = f"{_A_NS}fld"


def _should_translate(text: Optional[str]) -> bool:
    """Checks if a string has translatable content."""
    return should_translate_text(text, ignore_formulas=False)


def _normalize_pptx_text(text: Optional[str]) -> str:
    """Converts DrawingML soft-break control char (\\x0b / \\v) to standard newlines."""
    if not text:
        return ""
    return text.replace("\x0b", "\n").replace("\r\n", "\n")


def iter_pptx_shapes(shapes):
    """Recursively yields shapes including nested GROUP shapes."""
    for shape in shapes:
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            try:
                sub_shapes = shape.shapes
            except (AttributeError, NotImplementedError, TypeError):
                continue
            yield from iter_pptx_shapes(sub_shapes)
        else:
            yield shape


def _semantic_pptx_run_style(r_elem) -> Tuple:
    """Extracts semantic DrawingML run styling ignoring editor metadata attributes (lang, dirty, smt)."""
    rpr = r_elem.find(_A_RPR_TAG)
    if rpr is None:
        return (None,) * 10

    def _child_bytes(local_name: str) -> Optional[bytes]:
        el = rpr.find(f"{_A_NS}{local_name}")
        return etree.tostring(el) if el is not None else None

    latin = rpr.find(f"{_A_NS}latin")
    typeface = latin.get("typeface") if latin is not None else None

    return (
        rpr.get("b"),
        rpr.get("i"),
        rpr.get("u"),
        rpr.get("strike"),
        rpr.get("sz"),
        rpr.get("baseline"),
        _child_bytes("solidFill"),
        _child_bytes("highlight"),
        _child_bytes("hlinkClick"),
        typeface,
    )


def _extract_pptx_paragraph_units(p: _Paragraph) -> Tuple[str, List[Tuple[Any, str]]]:
    """
    Collects direct <a:r> elements and maps <a:br> elements to '\\n' so line breaks
    are preserved cleanly without writing escaped '_x000B_' control characters or
    corrupting dynamic <a:fld> fields.
    """
    run_entries: List[Tuple[Any, str]] = []
    pending_br = ""
    raw_parts: List[str] = []

    for child in p._p:
        if child.tag == _A_R_TAG:
            t_el = child.find(_A_T_TAG)
            txt = _normalize_pptx_text(t_el.text if t_el is not None else "")
            if pending_br:
                txt = pending_br + txt
                pending_br = ""
            raw_parts.append(txt)
            run_entries.append((child, txt))
        elif child.tag == _A_BR_TAG:
            raw_parts.append("\n")
            if run_entries:
                prev_r, prev_txt = run_entries[-1]
                run_entries[-1] = (prev_r, prev_txt + "\n")
            else:
                pending_br += "\n"
        elif child.tag == _A_FLD_TAG:
            # Keep dynamic fields (slide numbers/dates) intact and out of static run edits
            pass

    if pending_br and run_entries:
        last_r, last_txt = run_entries[-1]
        run_entries[-1] = (last_r, last_txt + pending_br)

    return "".join(raw_parts), run_entries


def _remove_pptx_br_elements(p_elem) -> None:
    for br in list(p_elem.findall(_A_BR_TAG)):
        p_elem.remove(br)


def _set_pptx_run_elem_text_with_breaks(p_elem, r_elem, text: str, rpr_template=None) -> None:
    """
    Writes text into DrawingML <a:r>, splitting any '\\n' into proper <a:br/> + <a:r> siblings
    so python-pptx never escapes '\\x0b' into literal '_x000B_'.
    """
    clean = _normalize_pptx_text(text)
    if rpr_template is None:
        rpr = r_elem.find(_A_RPR_TAG)
        rpr_template = copy.deepcopy(rpr) if rpr is not None else None

    parts = clean.split("\n")
    t_el = r_elem.find(_A_T_TAG)
    if t_el is None:
        t_el = etree.SubElement(r_elem, _A_T_TAG)
    t_el.text = parts[0]

    if len(parts) <= 1:
        return

    insert_pos = list(p_elem).index(r_elem) + 1
    for part in parts[1:]:
        br_el = etree.Element(_A_BR_TAG)
        if rpr_template is not None:
            br_el.append(copy.deepcopy(rpr_template))
        p_elem.insert(insert_pos, br_el)
        insert_pos += 1

        new_r = etree.Element(_A_R_TAG)
        if rpr_template is not None:
            new_r.append(copy.deepcopy(rpr_template))
        new_t = etree.SubElement(new_r, _A_T_TAG)
        new_t.text = part
        p_elem.insert(insert_pos, new_r)
        insert_pos += 1


def _prepare_pptx_paragraph_item(
    p: _Paragraph,
) -> Tuple[_Paragraph, str, Optional[List[Dict[str, Any]]], str, str]:
    """Extracts translation payload and inline style groups for a PowerPoint paragraph."""
    raw_text, run_entries = _extract_pptx_paragraph_units(p)
    if not raw_text:
        raw_text = _normalize_pptx_text(p.text)
    prefix = raw_text[: len(raw_text) - len(raw_text.lstrip())]
    suffix = raw_text[len(raw_text.rstrip()) :]

    non_empty_entries = [(r_el, txt) for r_el, txt in run_entries if txt != ""]
    if not non_empty_entries:
        return p, raw_text.strip(), None, prefix, suffix

    raw_groups: List[Dict[str, Any]] = []
    for r_el, txt in non_empty_entries:
        sig = _semantic_pptx_run_style(r_el)
        rpr = r_el.find(_A_RPR_TAG)
        has_hl = rpr is not None and rpr.find(f"{_A_NS}hlinkClick") is not None
        if raw_groups and raw_groups[-1]["sig"] == sig:
            raw_groups[-1]["r_elems"].append(r_el)
            raw_groups[-1]["text"] += txt
        else:
            raw_groups.append({
                "sig": sig,
                "r_elems": [r_el],
                "text": txt,
                "has_hl": has_hl,
                "rpr_template": copy.deepcopy(rpr) if rpr is not None else None,
            })

    # Merge whitespace-only boundary groups into adjacent content groups
    groups: List[Dict[str, Any]] = []
    pending_ws_elems: List[Any] = []
    pending_ws_text = ""

    for g in raw_groups:
        if not g["text"].strip():
            if groups:
                groups[-1]["r_elems"].extend(g["r_elems"])
                groups[-1]["text"] += g["text"]
            else:
                pending_ws_elems.extend(g["r_elems"])
                pending_ws_text += g["text"]
        else:
            if pending_ws_text:
                g["r_elems"] = pending_ws_elems + g["r_elems"]
                g["text"] = pending_ws_text + g["text"]
                pending_ws_elems = []
                pending_ws_text = ""
            groups.append(g)

    if pending_ws_text and groups:
        groups[-1]["r_elems"].extend(pending_ws_elems)
        groups[-1]["text"] += pending_ws_text

    if len(groups) < 2 or contains_literal_inline_tags(raw_text):
        return p, raw_text.strip(), None, prefix, suffix

    if prefix and groups[0]["text"].startswith(prefix):
        groups[0]["text"] = groups[0]["text"][len(prefix) :]
    if suffix and groups[-1]["text"].endswith(suffix):
        groups[-1]["text"] = groups[-1]["text"][: len(groups[-1]["text"]) - len(suffix)]

    tagged_query = build_inline_tagged_text([(g, g["text"]) for g in groups])
    return p, tagged_query, groups, prefix, suffix


def _apply_pptx_paragraph_translation(
    p: _Paragraph,
    translated: str,
    groups: Optional[List[Dict[str, Any]]] = None,
    prefix: str = "",
    suffix: str = "",
) -> None:
    """Applies translated string back to PowerPoint paragraph preserving inline run styles and line breaks."""
    translated = _normalize_pptx_text(translated)
    r_elems = list(p._p.findall(_A_R_TAG))

    if groups:
        segments = parse_inline_tagged_text(translated, len(groups))
        if segments is not None:
            first_idx, first_txt = segments[0]
            segments[0] = (first_idx, f"{prefix}{first_txt}")
            last_idx, last_txt = segments[-1]
            segments[-1] = (last_idx, f"{last_txt}{suffix}")

            order = [idx for idx, _ in segments]
            if order == list(range(len(groups))):
                _remove_pptx_br_elements(p._p)
                assigned_elems: Set[Any] = set()
                for idx, seg_text in segments:
                    g_elems = groups[idx]["r_elems"]
                    assigned_elems.add(g_elems[0])
                    for extra in g_elems[1:]:
                        t_el = extra.find(_A_T_TAG)
                        if t_el is not None:
                            t_el.text = ""
                for r_el in r_elems:
                    if r_el not in assigned_elems:
                        t_el = r_el.find(_A_T_TAG)
                        if t_el is not None:
                            t_el.text = ""
                for idx, seg_text in segments:
                    target_r = groups[idx]["r_elems"][0]
                    _set_pptx_run_elem_text_with_breaks(
                        p._p, target_r, seg_text, rpr_template=groups[idx]["rpr_template"]
                    )
                return

            has_hyperlinks = any(g["has_hl"] for g in groups)
            if not has_hyperlinks and len(segments) == len(groups) and len(set(order)) == len(groups):
                _remove_pptx_br_elements(p._p)
                assigned_elems = set()
                for pos, (src_idx, seg_text) in enumerate(segments):
                    slot_elems = groups[pos]["r_elems"]
                    target_r = slot_elems[0]
                    assigned_elems.add(target_r)
                    for extra in slot_elems[1:]:
                        t_el = extra.find(_A_T_TAG)
                        if t_el is not None:
                            t_el.text = ""
                    old_rpr = target_r.find(_A_RPR_TAG)
                    if old_rpr is not None:
                        target_r.remove(old_rpr)
                    tpl_rpr = groups[src_idx]["rpr_template"]
                    if tpl_rpr is not None:
                        target_r.insert(0, copy.deepcopy(tpl_rpr))
                for r_el in r_elems:
                    if r_el not in assigned_elems:
                        t_el = r_el.find(_A_T_TAG)
                        if t_el is not None:
                            t_el.text = ""
                for pos, (src_idx, seg_text) in enumerate(segments):
                    target_r = groups[pos]["r_elems"][0]
                    _set_pptx_run_elem_text_with_breaks(
                        p._p, target_r, seg_text, rpr_template=groups[src_idx]["rpr_template"]
                    )
                return

            plain = "".join(seg_text for _, seg_text in segments)
            _remove_pptx_br_elements(p._p)
            if r_elems:
                target_r = next(
                    (r for r in r_elems if ((r.find(_A_T_TAG).text if r.find(_A_T_TAG) is not None else "") or "").strip()),
                    r_elems[0],
                )
                for r in r_elems:
                    if r is not target_r:
                        t_el = r.find(_A_T_TAG)
                        if t_el is not None:
                            t_el.text = ""
                _set_pptx_run_elem_text_with_breaks(p._p, target_r, plain)
            else:
                p.text = plain
            return

        translated = strip_inline_tags(translated)

    final_text = _normalize_pptx_text(f"{prefix}{translated}{suffix}")
    _remove_pptx_br_elements(p._p)
    if r_elems:
        target_r = next(
            (r for r in r_elems if ((r.find(_A_T_TAG).text if r.find(_A_T_TAG) is not None else "") or "").strip()),
            r_elems[0],
        )
        for r in r_elems:
            if r is not target_r:
                t_el = r.find(_A_T_TAG)
                if t_el is not None:
                    t_el.text = ""
        _set_pptx_run_elem_text_with_breaks(p._p, target_r, final_text)
    else:
        p.text = final_text


class PptxTranslator(BaseTranslator):
    """
    Handles translation of Microsoft PowerPoint (.pptx) presentations.
    Preserves slide layouts, text boxes, nested group shapes, tables, inline styles, and speaker notes.
    Features text deduplication, local SQLite cache, and concurrent batching.
    """

    @classmethod
    def _iterate_paragraphs(cls, prs: Presentation):
        """Yields unique paragraphs across all slides, shapes, nested groups, deduplicated tables, and notes."""
        seen_p_elems: Set[Any] = set()

        def _yield_unique(p: _Paragraph):
            if p._p not in seen_p_elems:
                seen_p_elems.add(p._p)
                return p
            return None

        for slide in prs.slides:
            for shape in iter_pptx_shapes(slide.shapes):
                if shape.has_text_frame:
                    for p in shape.text_frame.paragraphs:
                        unique_p = _yield_unique(p)
                        if unique_p is not None:
                            yield unique_p
                elif shape.has_table:
                    for row in shape.table.rows:
                        for cell in row.cells:
                            for p in cell.text_frame.paragraphs:
                                unique_p = _yield_unique(p)
                                if unique_p is not None:
                                    yield unique_p

            if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
                for p in slide.notes_slide.notes_text_frame.paragraphs:
                    unique_p = _yield_unique(p)
                    if unique_p is not None:
                        yield unique_p

    @classmethod
    def _has_translatable_content(cls, p: _Paragraph) -> bool:
        raw_text, run_entries = _extract_pptx_paragraph_units(p)
        if not run_entries:
            # Skip paragraphs consisting solely of dynamic fields (<a:fld>)
            if p._p.find(_A_FLD_TAG) is not None:
                return False
            raw_text = _normalize_pptx_text(p.text)
        return _should_translate(raw_text)

    @classmethod
    def inspect_file(cls, file_path: str) -> Dict[str, Any]:
        """Inspects PowerPoint presentation to count slides, shapes, words, and text segments."""
        path = Path(file_path)
        if not path.exists():
            return {"type": "pptx", "error": "File not found"}

        try:
            prs = Presentation(str(path))
            slide_count = len(prs.slides)
            shape_count = sum(len(s.shapes) for s in prs.slides)
            total_words = 0
            unique_texts: Set[str] = set()

            for p in cls._iterate_paragraphs(prs):
                text = _normalize_pptx_text(p.text)
                if text:
                    total_words += count_words_multilingual(text)
                    if cls._has_translatable_content(p):
                        raw_runs_text, run_entries = _extract_pptx_paragraph_units(p)
                        clean = raw_runs_text if run_entries else text
                        if clean.strip():
                            unique_texts.add(clean.strip())

            return {
                "type": "pptx",
                "slides": slide_count,
                "shapes": shape_count,
                "word_count": total_words,
                "translatable_segments": len(unique_texts),
            }
        except Exception as e:
            return {"type": "pptx", "error": str(e)}

    def process_file(
        self,
        file_path: str,
        target_lang: Optional[str] = None,
        source_lang: Optional[str] = "auto",
        options: Optional[TranslationOptions] = None,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        custom_output_path: Optional[str] = None,
        *args,
        **kwargs,
    ) -> str:
        """
        Translates a PowerPoint presentation into the target language.
        Extracts translatable text segments (preserving inline styles), translates via LLM
        in concurrent batches, and saves output file with layout preservation.
        """
        self._is_cancelled = False
        src = Path(file_path)
        if not src.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        target_lang, source_lang, options = self._resolve_params(
            target_lang, source_lang, options, kwargs
        )

        if progress_callback:
            progress_callback(5, 100, "Reading PowerPoint presentation...")

        prs = Presentation(str(src))
        paragraphs_to_process: List[_Paragraph] = [
            p for p in self._iterate_paragraphs(prs) if self._has_translatable_content(p)
        ]

        if not paragraphs_to_process:
            out_path = get_smart_output_path(
                src, target_lang=target_lang, custom_output_path=custom_output_path
            )
            saved_path = safe_save_file(lambda p: prs.save(str(p)), out_path)
            if progress_callback:
                progress_callback(100, 100, "Presentation contains no text to translate.")
            return str(saved_path)

        prepared_items = [_prepare_pptx_paragraph_item(p) for p in paragraphs_to_process]
        unique_texts = list(dict.fromkeys(query for _, query, _, _, _ in prepared_items if query))
        total_unique = len(unique_texts)

        if progress_callback:
            progress_callback(10, 100, f"Found {total_unique} unique text blocks. Checking cache...")

        translation_map = self.translate_unique_texts(
            unique_texts=unique_texts,
            target_lang=target_lang,
            source_lang=source_lang,
            options=options,
            progress_callback=progress_callback,
            progress_start=10,
            progress_span=75,
        )

        if self.is_cancelled:
            raise InterruptedError("Translation cancelled by user.")

        if progress_callback:
            progress_callback(90, 100, "Applying translations to PowerPoint presentation...")

        for p, query, groups, prefix, suffix in prepared_items:
            translated = translation_map.get(query)
            if translated is not None:
                _apply_pptx_paragraph_translation(
                    p, translated, groups=groups, prefix=prefix, suffix=suffix
                )

        if progress_callback:
            progress_callback(95, 100, "Saving translated presentation...")

        out_path = get_smart_output_path(
            source_path=src,
            target_lang=target_lang,
            target_format=".pptx",
            custom_output_path=custom_output_path,
        )
        saved_path = safe_save_file(lambda p: prs.save(str(p)), out_path)

        if progress_callback:
            progress_callback(100, 100, f"Saved: {saved_path.name}")

        return str(saved_path)
