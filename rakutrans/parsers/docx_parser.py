"""
Word (.docx) parsing and translation engine for RakuTrans AI.
Uses python-docx to translate documents while preserving paragraphs,
tables (including nested), text boxes, headers/footers, hyperlinks, and inline run styles.
"""

import copy
from pathlib import Path
import re
from typing import List, Dict, Set, Callable, Optional, Any, Tuple
import docx
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from rakutrans.parsers.base_translator import (
    BaseTranslator,
    build_inline_tagged_text,
    contains_literal_inline_tags,
    count_words_multilingual,
    parse_inline_tagged_text,
    safe_save_file,
    should_translate_text,
    strip_inline_tags,
)
from rakutrans.core.config import TranslationOptions, get_smart_output_path

_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_TXBX_CONTENT_TAG = f"{_W_NS}txbxContent"
_HYPERLINK_TAG = f"{_W_NS}hyperlink"
_R_TAG = f"{_W_NS}r"
_RPR_TAG = f"{_W_NS}rPr"
_RFONTS_TAG = f"{_W_NS}rFonts"
_P_TAG = f"{_W_NS}p"
_T_TAG = f"{_W_NS}t"
_TAB_TAG = f"{_W_NS}tab"
_BR_TAG = f"{_W_NS}br"


def _is_structural_break(br_elem) -> bool:
    return br_elem.get(qn("w:type")) in ("page", "column")


def _collect_direct_t_units(p_elem) -> List[Tuple[Any, Optional[Any], Optional[Any], str]]:
    """
    Collects (elem, r_elem, hyperlink_elem, text_val) tuples belonging directly to p_elem
    (including <w:t>, <w:tab/>, and soft <w:br/>) without descending into nested text boxes
    or nested paragraphs.
    """
    units: List[Tuple[Any, Optional[Any], Optional[Any], str]] = []

    def walk(node, curr_r=None, curr_hl=None):
        for child in node:
            tag = child.tag
            if tag == _TXBX_CONTENT_TAG or tag == _P_TAG:
                continue
            next_r = child if tag == _R_TAG else curr_r
            next_hl = child if tag == _HYPERLINK_TAG else curr_hl
            if tag == _T_TAG:
                units.append((child, next_r, next_hl, child.text or ""))
            elif tag == _TAB_TAG:
                units.append((child, next_r, next_hl, "\t"))
            elif tag == _BR_TAG and not _is_structural_break(child):
                units.append((child, next_r, next_hl, "\n"))
            else:
                walk(child, next_r, next_hl)

    walk(p_elem)
    return units


def _semantic_run_style(r_elem: Optional[Any], hl_elem: Optional[Any]) -> Tuple:
    """
    Extracts semantic visual styling of a Word run while ignoring per-glyph
    PDF conversion artifacts (e.g. 'Type3 (N 0 R)' font entries, kerning, lang tags).
    """
    hl_id = id(hl_elem) if hl_elem is not None else None
    if r_elem is None:
        return (hl_id, False, False, None, False, None, None, None, None, None)

    rpr = r_elem.find(_RPR_TAG)
    if rpr is None:
        return (hl_id, False, False, None, False, None, None, None, None, None)

    def _bool_prop(local_name: str) -> bool:
        el = rpr.find(f"{_W_NS}{local_name}")
        if el is None:
            return False
        val = el.get(f"{_W_NS}val")
        return val not in ("0", "false", "off")

    def _val_prop(local_name: str) -> Optional[str]:
        el = rpr.find(f"{_W_NS}{local_name}")
        return el.get(f"{_W_NS}val") if el is not None else None

    color = _val_prop("color")
    if color == "auto":
        color = None

    font_name = None
    rfonts = rpr.find(_RFONTS_TAG)
    if rfonts is not None:
        raw_font = (
            rfonts.get(f"{_W_NS}ascii")
            or rfonts.get(f"{_W_NS}eastAsia")
            or rfonts.get(f"{_W_NS}hAnsi")
        )
        if raw_font and not raw_font.startswith("Type3 ("):
            font_name = raw_font

    return (
        hl_id,
        _bool_prop("b"),
        _bool_prop("i"),
        _val_prop("u"),
        _bool_prop("strike") or _bool_prop("dstrike"),
        color,
        _val_prop("highlight"),
        _val_prop("sz"),
        _val_prop("vertAlign"),
        font_name,
    )


def _iter_table_paragraphs(table, seen_p_elems: Set[Any]):
    """Recursively yields paragraphs inside tables and nested tables."""
    for row in table.rows:
        for cell in row.cells:
            for p in cell.paragraphs:
                if p._p not in seen_p_elems:
                    seen_p_elems.add(p._p)
                    yield p
            for nested_tbl in cell.tables:
                yield from _iter_table_paragraphs(nested_tbl, seen_p_elems)


def _iter_container_paragraphs(container, parent_doc, seen_p_elems: Set[Any]):
    """Yields paragraphs from a document or header/footer container including tables, SDTs, and text boxes."""
    for p in getattr(container, "paragraphs", []):
        if p._p not in seen_p_elems:
            seen_p_elems.add(p._p)
            yield p

    for tbl in getattr(container, "tables", []):
        yield from _iter_table_paragraphs(tbl, seen_p_elems)

    root_elem = getattr(container, "_element", None)
    if root_elem is not None:
        for xpath_expr in (".//w:txbxContent//w:p", ".//w:sdtContent//w:p"):
            for p_elem in root_elem.xpath(xpath_expr):
                if p_elem not in seen_p_elems:
                    seen_p_elems.add(p_elem)
                    yield Paragraph(p_elem, parent_doc)


def _iter_all_paragraphs(doc: docx.document.Document):
    """Yields unique paragraphs across body, tables, nested tables, SDTs, headers/footers, footnotes/endnotes, and text boxes."""
    seen_p_elems: Set[Any] = set()

    for p in doc.paragraphs:
        if p._p not in seen_p_elems:
            seen_p_elems.add(p._p)
            yield p

    for table in doc.tables:
        yield from _iter_table_paragraphs(table, seen_p_elems)

    for xpath_expr in (".//w:txbxContent//w:p", ".//w:sdtContent//w:p"):
        for p_elem in doc.element.body.xpath(xpath_expr):
            if p_elem not in seen_p_elems:
                seen_p_elems.add(p_elem)
                yield Paragraph(p_elem, doc)

    for section in doc.sections:
        for hf_attr in (
            "header",
            "first_page_header",
            "even_page_header",
            "footer",
            "first_page_footer",
            "even_page_footer",
        ):
            hf = getattr(section, hf_attr, None)
            if hf is not None and not getattr(hf, "is_linked_to_previous", False):
                yield from _iter_container_paragraphs(hf, doc, seen_p_elems)

    # Footnotes and endnotes XML parts (if present in the Word archive)
    try:
        for rel in doc.part.rels.values():
            reltype = getattr(rel, "reltype", "") or ""
            if reltype.endswith("/footnotes") or reltype.endswith("/endnotes"):
                target_part = getattr(rel, "target_part", None)
                note_root = getattr(target_part, "_element", None)
                if note_root is None:
                    continue
                for note_tag in ("w:footnote", "w:endnote"):
                    for note_el in note_root.xpath(f".//{note_tag}"):
                        if note_el.get(qn("w:type")) in ("separator", "continuationSeparator"):
                            continue
                        for p_elem in note_el.xpath(".//w:p"):
                            if p_elem not in seen_p_elems:
                                seen_p_elems.add(p_elem)
                                yield Paragraph(p_elem, doc)
    except Exception:
        pass


def _set_w_t_text(t_elem, value: str) -> None:
    t_elem.text = value
    if value and (value[0].isspace() or value[-1].isspace()):
        t_elem.set(qn("xml:space"), "preserve")
    elif qn("xml:space") in t_elem.attrib:
        del t_elem.attrib[qn("xml:space")]


def _clear_direct_units(
    units: List[Tuple[Any, Optional[Any], Optional[Any], str]],
    keep_nodes: Optional[Set[Any]] = None,
) -> None:
    """Clears <w:t> nodes and removes soft <w:br/> / <w:tab/> nodes from direct paragraph units."""
    keep = keep_nodes or set()
    for el, _r, _hl, _txt in units:
        if el in keep:
            continue
        if el.tag == _T_TAG:
            _set_w_t_text(el, "")
        elif el.tag in (_TAB_TAG, _BR_TAG):
            parent = el.getparent()
            if parent is not None:
                parent.remove(el)


def _write_value_into_slot(target_el, r_elem, value: str) -> None:
    """
    Writes text into target <w:t> / <w:r>, emitting genuine <w:tab/> and <w:br/>
    elements instead of literal '\\n' inside <w:t> (which Word collapses).
    """
    clean = (value or "").replace("\r\n", "\n")
    if target_el is not None and target_el.tag != _T_TAG:
        parent = target_el.getparent()
        replacement = OxmlElement("w:t")
        if parent is not None:
            pos = list(parent).index(target_el)
            parent.remove(target_el)
            parent.insert(pos, replacement)
            target_el = replacement
        elif r_elem is not None:
            r_elem.append(replacement)
            target_el = replacement
        else:
            return
    elif target_el is None:
        if r_elem is not None:
            target_el = OxmlElement("w:t")
            r_elem.append(target_el)
        else:
            return

    if "\n" not in clean and "\t" not in clean:
        _set_w_t_text(target_el, clean)
        return

    parent = target_el.getparent()
    if parent is None:
        _set_w_t_text(target_el, clean)
        return

    tokens = [tok for tok in re.split(r"(\n|\t)", clean) if tok != ""]
    if not tokens:
        _set_w_t_text(target_el, "")
        return

    insert_idx = list(parent).index(target_el)
    parent.remove(target_el)
    for tok in tokens:
        if tok == "\n":
            parent.insert(insert_idx, OxmlElement("w:br"))
        elif tok == "\t":
            parent.insert(insert_idx, OxmlElement("w:tab"))
        else:
            t_node = OxmlElement("w:t")
            _set_w_t_text(t_node, tok)
            parent.insert(insert_idx, t_node)
        insert_idx += 1


def _prepare_paragraph_item(
    p: Paragraph,
) -> Tuple[Paragraph, str, Optional[List[Dict[str, Any]]], str, str]:
    """
    Extracts translation payload and semantic inline style groups for a paragraph.
    Returns (paragraph, query_text, style_groups_or_None, outer_prefix, outer_suffix).
    """
    units = _collect_direct_t_units(p._p)
    raw_text = "".join(txt for _, _, _, txt in units) if units else p.text
    prefix = raw_text[: len(raw_text) - len(raw_text.lstrip())]
    suffix = raw_text[len(raw_text.rstrip()) :]

    non_empty_units = [(el, r, hl, txt) for el, r, hl, txt in units if txt != ""]
    if not non_empty_units:
        return p, raw_text.strip(), None, prefix, suffix

    # 1. Group contiguous units sharing semantic visual style
    raw_groups: List[Dict[str, Any]] = []
    for el, r_el, hl_el, txt in non_empty_units:
        sig = _semantic_run_style(r_el, hl_el)
        rpr = r_el.find(_RPR_TAG) if r_el is not None else None
        if raw_groups and raw_groups[-1]["sig"] == sig:
            raw_groups[-1]["nodes"].append(el)
            raw_groups[-1]["runs"].append(r_el)
            raw_groups[-1]["text"] += txt
        else:
            raw_groups.append({
                "sig": sig,
                "nodes": [el],
                "runs": [r_el],
                "text": txt,
                "has_hl": hl_el is not None,
                "rpr_template": copy.deepcopy(rpr) if rpr is not None else None,
            })

    # 2. Merge whitespace-only boundary groups into adjacent content groups
    groups: List[Dict[str, Any]] = []
    pending_ws_nodes: List[Any] = []
    pending_ws_runs: List[Any] = []
    pending_ws_text = ""

    for g in raw_groups:
        if not g["text"].strip():
            if groups:
                groups[-1]["nodes"].extend(g["nodes"])
                groups[-1]["runs"].extend(g["runs"])
                groups[-1]["text"] += g["text"]
            else:
                pending_ws_nodes.extend(g["nodes"])
                pending_ws_runs.extend(g["runs"])
                pending_ws_text += g["text"]
        else:
            if pending_ws_text:
                g["nodes"] = pending_ws_nodes + g["nodes"]
                g["runs"] = pending_ws_runs + g["runs"]
                g["text"] = pending_ws_text + g["text"]
                pending_ws_nodes = []
                pending_ws_runs = []
                pending_ws_text = ""
            groups.append(g)

    if pending_ws_text and groups:
        groups[-1]["nodes"].extend(pending_ws_nodes)
        groups[-1]["runs"].extend(pending_ws_runs)
        groups[-1]["text"] += pending_ws_text

    if len(groups) < 2 or contains_literal_inline_tags(raw_text):
        return p, raw_text.strip(), None, prefix, suffix

    # Strip outer paragraph whitespace once before encoding <s0>...</s0>
    if prefix and groups[0]["text"].startswith(prefix):
        groups[0]["text"] = groups[0]["text"][len(prefix) :]
    if suffix and groups[-1]["text"].endswith(suffix):
        groups[-1]["text"] = groups[-1]["text"][: len(groups[-1]["text"]) - len(suffix)]

    tagged_query = build_inline_tagged_text([(g, g["text"]) for g in groups])
    return p, tagged_query, groups, prefix, suffix


def _apply_paragraph_translation(
    p: Paragraph,
    translated: str,
    groups: Optional[List[Dict[str, Any]]] = None,
    prefix: str = "",
    suffix: str = "",
) -> None:
    """Applies translated text back to paragraph preserving inline run styles, tabs/breaks, and hyperlinks."""
    all_units = _collect_direct_t_units(p._p)

    if groups:
        segments = parse_inline_tagged_text(translated, len(groups))
        if segments is not None:
            first_idx, first_txt = segments[0]
            segments[0] = (first_idx, f"{prefix}{first_txt}")
            last_idx, last_txt = segments[-1]
            segments[-1] = (last_idx, f"{last_txt}{suffix}")

            order = [idx for idx, _ in segments]

            # Case 1: Standard order [0, 1, ..., N-1]
            if order == list(range(len(groups))):
                slot_targets = []
                keep_nodes: Set[Any] = set()
                for idx, seg_text in segments:
                    nodes = groups[idx]["nodes"]
                    t_target = next((n for n in nodes if n.tag == _T_TAG), nodes[0])
                    slot_r = groups[idx]["runs"][0]
                    keep_nodes.add(t_target)
                    slot_targets.append((t_target, slot_r, seg_text))
                _clear_direct_units(all_units, keep_nodes=keep_nodes)
                for t_target, slot_r, seg_text in slot_targets:
                    _write_value_into_slot(t_target, slot_r, seg_text)
                return

            # Case 2: Reordered target-language grammar without hyperlinks -> swap run rPr templates
            has_hyperlinks = any(g["has_hl"] for g in groups)
            if not has_hyperlinks and len(segments) == len(groups) and len(set(order)) == len(groups):
                slot_targets = []
                keep_nodes = set()
                for pos, (src_idx, seg_text) in enumerate(segments):
                    slot_nodes = groups[pos]["nodes"]
                    t_target = next((n for n in slot_nodes if n.tag == _T_TAG), slot_nodes[0])
                    slot_run = groups[pos]["runs"][0]
                    keep_nodes.add(t_target)
                    if slot_run is not None:
                        old_rpr = slot_run.find(_RPR_TAG)
                        if old_rpr is not None:
                            slot_run.remove(old_rpr)
                        tpl_rpr = groups[src_idx]["rpr_template"]
                        if tpl_rpr is not None:
                            slot_run.insert(0, copy.deepcopy(tpl_rpr))
                    slot_targets.append((t_target, slot_run, seg_text))
                _clear_direct_units(all_units, keep_nodes=keep_nodes)
                for t_target, slot_run, seg_text in slot_targets:
                    _write_value_into_slot(t_target, slot_run, seg_text)
                return

            # Safe fallback when tags were reordered around hyperlinks or split irregularly
            plain = "".join(seg_text for _, seg_text in segments)
            t_elems = [el for el, _r, _hl, _txt in all_units if el.tag == _T_TAG]
            target_t = next((t for t in t_elems if (t.text or "").strip()), t_elems[0] if t_elems else None)
            if target_t is not None:
                _clear_direct_units(all_units, keep_nodes={target_t})
                _write_value_into_slot(target_t, target_t.getparent(), plain)
                return

        translated = strip_inline_tags(translated)

    final_text = f"{prefix}{translated}{suffix}"
    t_elems = [el for el, _r, _hl, _txt in all_units if el.tag == _T_TAG]
    if t_elems:
        target_t = next((t for t in t_elems if (t.text or "").strip()), t_elems[0])
        _clear_direct_units(all_units, keep_nodes={target_t})
        _write_value_into_slot(target_t, target_t.getparent(), final_text)
    elif p.runs:
        _clear_direct_units(all_units)
        runs = list(p.runs)
        t_node = OxmlElement("w:t")
        runs[0]._r.append(t_node)
        _write_value_into_slot(t_node, runs[0]._r, final_text)
        for r in runs[1:]:
            r.text = ""
    else:
        p.text = final_text


class DocxTranslator(BaseTranslator):
    """
    Handles translation of Microsoft Word (.docx) documents.
    Preserves document structure, headings, lists, table cells, hyperlinks, text boxes, and inline run styles.
    Features text deduplication, SQLite translation memory cache, and concurrent batching.
    """

    @classmethod
    def inspect_file(cls, file_path: str) -> Dict[str, Any]:
        """Inspects Word document to count paragraphs, tables, words, and translatable segments."""
        path = Path(file_path)
        if not path.exists():
            return {"type": "docx", "error": "File not found"}

        try:
            doc = Document(str(path))
            p_count = len(doc.paragraphs)
            t_count = len(doc.tables)
            total_words = 0
            total_chars = 0
            unique_texts: Set[str] = set()

            for p in _iter_all_paragraphs(doc):
                text = p.text
                if text:
                    total_words += count_words_multilingual(text)
                    if should_translate_text(text, ignore_formulas=False):
                        trimmed = text.strip()
                        total_chars += len(trimmed)
                        unique_texts.add(trimmed)

            return {
                "type": "docx",
                "paragraphs": p_count,
                "tables": t_count,
                "word_count": total_words,
                "char_count": total_chars,
                "unique_char_count": sum(len(t) for t in unique_texts),
                "translatable_segments": len(unique_texts),
            }
        except Exception as e:
            return {"type": "docx", "error": str(e)}

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
        Translates a Word document into the target language.
        Extracts translatable text segments (with inline style markers when runs differ),
        translates via LLM in concurrent batches, and saves output file with style preservation.
        """
        self._is_cancelled = False
        src = Path(file_path)
        if not src.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        target_lang, source_lang, options = self._resolve_params(
            target_lang, source_lang, options, kwargs
        )

        if progress_callback:
            progress_callback(5, 100, self._t("progress_reading_docx"))

        doc = Document(str(src))
        paragraphs_to_process: List[Paragraph] = [
            p for p in _iter_all_paragraphs(doc) if should_translate_text(p.text, ignore_formulas=False)
        ]

        if not paragraphs_to_process:
            out_path = get_smart_output_path(
                src,
                target_lang=target_lang,
                custom_output_path=custom_output_path,
            )
            saved_path = safe_save_file(lambda p: doc.save(str(p)), out_path)
            if progress_callback:
                progress_callback(100, 100, self._t("progress_no_translatable_doc"))
            return str(saved_path)

        prepared_items = [_prepare_paragraph_item(p) for p in paragraphs_to_process]
        unique_texts = list(dict.fromkeys(query for _, query, _, _, _ in prepared_items if query))
        total_unique = len(unique_texts)

        if progress_callback:
            progress_callback(10, 100, self._t("progress_found_blocks", count=total_unique))

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
            progress_callback(90, 100, self._t("progress_applying_docx"))

        for p, query, groups, prefix, suffix in prepared_items:
            translated = translation_map.get(query)
            if translated is not None:
                _apply_paragraph_translation(p, translated, groups=groups, prefix=prefix, suffix=suffix)

        if progress_callback:
            progress_callback(95, 100, self._t("progress_saving_docx"))

        out_path = get_smart_output_path(
            source_path=src,
            target_lang=target_lang,
            target_format=".docx",
            custom_output_path=custom_output_path,
        )
        saved_path = safe_save_file(lambda p: doc.save(str(p)), out_path)

        if progress_callback:
            progress_callback(100, 100, self._t("progress_saved_file", filename=saved_path.name))

        return str(saved_path)
