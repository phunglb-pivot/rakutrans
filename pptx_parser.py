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


def _should_translate(text: Optional[str]) -> bool:
    """Checks if a string has translatable content."""
    return should_translate_text(text, ignore_formulas=False)


def iter_pptx_shapes(shapes):
    """Recursively yields shapes including nested GROUP shapes."""
    for shape in shapes:
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            try:
                yield from iter_pptx_shapes(shape.shapes)
            except Exception:
                pass
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


def _prepare_pptx_paragraph_item(
    p: _Paragraph,
) -> Tuple[_Paragraph, str, Optional[List[Dict[str, Any]]], str, str]:
    """Extracts translation payload and inline style groups for a PowerPoint paragraph."""
    raw_text = p.text
    prefix = raw_text[: len(raw_text) - len(raw_text.lstrip())]
    suffix = raw_text[len(raw_text.rstrip()) :]

    runs = list(p.runs)
    non_empty_runs = [r for r in runs if (r.text or "") != ""]
    if not non_empty_runs:
        return p, raw_text.strip(), None, prefix, suffix

    raw_groups: List[Dict[str, Any]] = []
    for r in non_empty_runs:
        sig = _semantic_pptx_run_style(r._r)
        rpr = r._r.find(_A_RPR_TAG)
        has_hl = rpr is not None and rpr.find(f"{_A_NS}hlinkClick") is not None
        if raw_groups and raw_groups[-1]["sig"] == sig:
            raw_groups[-1]["runs"].append(r)
            raw_groups[-1]["text"] += r.text or ""
        else:
            raw_groups.append({
                "sig": sig,
                "runs": [r],
                "text": r.text or "",
                "has_hl": has_hl,
                "rpr_template": copy.deepcopy(rpr) if rpr is not None else None,
            })

    # Merge whitespace-only boundary groups into adjacent content groups
    groups: List[Dict[str, Any]] = []
    pending_ws_runs: List[Any] = []
    pending_ws_text = ""

    for g in raw_groups:
        if not g["text"].strip():
            if groups:
                groups[-1]["runs"].extend(g["runs"])
                groups[-1]["text"] += g["text"]
            else:
                pending_ws_runs.extend(g["runs"])
                pending_ws_text += g["text"]
        else:
            if pending_ws_text:
                g["runs"] = pending_ws_runs + g["runs"]
                g["text"] = pending_ws_text + g["text"]
                pending_ws_runs = []
                pending_ws_text = ""
            groups.append(g)

    if pending_ws_text and groups:
        groups[-1]["runs"].extend(pending_ws_runs)
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
    """Applies translated string back to PowerPoint paragraph preserving inline run styles."""
    runs = list(p.runs)
    if groups:
        segments = parse_inline_tagged_text(translated, len(groups))
        if segments is not None:
            first_idx, first_txt = segments[0]
            segments[0] = (first_idx, f"{prefix}{first_txt}")
            last_idx, last_txt = segments[-1]
            segments[-1] = (last_idx, f"{last_txt}{suffix}")

            order = [idx for idx, _ in segments]
            if order == list(range(len(groups))):
                assigned_runs: Set[int] = set()
                for idx, seg_text in segments:
                    g_runs = groups[idx]["runs"]
                    g_runs[0].text = seg_text
                    assigned_runs.add(id(g_runs[0]._r))
                    for extra in g_runs[1:]:
                        extra.text = ""
                for r in runs:
                    if id(r._r) not in assigned_runs:
                        r.text = ""
                return

            has_hyperlinks = any(g["has_hl"] for g in groups)
            if not has_hyperlinks and len(segments) == len(groups) and len(set(order)) == len(groups):
                assigned_runs = set()
                for pos, (src_idx, seg_text) in enumerate(segments):
                    slot_runs = groups[pos]["runs"]
                    target_r = slot_runs[0]
                    target_r.text = seg_text
                    assigned_runs.add(id(target_r._r))
                    for extra in slot_runs[1:]:
                        extra.text = ""
                    old_rpr = target_r._r.find(_A_RPR_TAG)
                    if old_rpr is not None:
                        target_r._r.remove(old_rpr)
                    tpl_rpr = groups[src_idx]["rpr_template"]
                    if tpl_rpr is not None:
                        target_r._r.insert(0, copy.deepcopy(tpl_rpr))
                for r in runs:
                    if id(r._r) not in assigned_runs:
                        r.text = ""
                return

            plain = "".join(seg_text for _, seg_text in segments)
            if runs:
                target_idx = next((idx for idx, r in enumerate(runs) if (r.text or "").strip()), 0)
                for idx, r in enumerate(runs):
                    r.text = plain if idx == target_idx else ""
            else:
                p.text = plain
            return

        translated = strip_inline_tags(translated)

    final_text = f"{prefix}{translated}{suffix}"
    if runs:
        target_idx = next((idx for idx, r in enumerate(runs) if (r.text or "").strip()), 0)
        for idx, r in enumerate(runs):
            r.text = final_text if idx == target_idx else ""
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
        """Yields all paragraphs across all slides, shapes, nested groups, tables, and notes."""
        for slide in prs.slides:
            for shape in iter_pptx_shapes(slide.shapes):
                if shape.has_text_frame:
                    for p in shape.text_frame.paragraphs:
                        yield p
                elif shape.has_table:
                    for row in shape.table.rows:
                        for cell in row.cells:
                            for p in cell.text_frame.paragraphs:
                                yield p

            if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
                for p in slide.notes_slide.notes_text_frame.paragraphs:
                    yield p

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
                text = p.text
                if text:
                    total_words += count_words_multilingual(text)
                    if _should_translate(text):
                        unique_texts.add(text.strip())

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
            p for p in self._iterate_paragraphs(prs) if _should_translate(p.text)
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
