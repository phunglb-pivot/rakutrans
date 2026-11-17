"""
File Drag-and-Drop Dropzone component for RakuTrans AI.
Supports both native TkinterDnD2 drag & drop and interactive click-to-browse fallback.
"""

from pathlib import Path
from typing import Callable, List, Optional
import customtkinter as ctk
from tkinter import filedialog

try:
    from tkinterdnd2 import DND_FILES
    HAS_TKDND = True
except ImportError:
    HAS_TKDND = False


from base_translator import (
    HIGH_REQUEST_WARNING_THRESHOLD,
    LARGE_FILE_SIZE_BYTES,
    estimate_translation_requests,
)
from translator_registry import TranslatorRegistry
from components.ui_system import CustomButton
from components.icons import get_icon


def get_file_type_badge(suffix: str, t_func: Optional[Callable[[str], str]] = None) -> tuple[str, str]:
    """Returns (icon_name, label_badge) for a given file suffix."""
    s = suffix.lower()
    txt_badge = t_func("badge_plain_text") if t_func else "Plain Text"
    if s == ".xlsx":
        return ("file_excel", "Excel")
    elif s in [".csv", ".tsv"]:
        return ("file_excel", "CSV/TSV")
    elif s == ".docx":
        return ("file_word", "Word")
    elif s == ".pptx":
        return ("file_ppt", "PowerPoint")
    elif s == ".pdf":
        return ("file_pdf", "PDF")
    elif s == ".md":
        return ("file_md", "Markdown")
    elif s == ".json":
        return ("file_json", "JSON")
    elif s == ".txt":
        return ("file_text", txt_badge)
    return ("file_generic", s.lstrip(".").upper() or "FILE")


def format_file_size(num_bytes: int) -> str:
    """Format byte size to human-readable string."""
    for unit in ["B", "KB", "MB", "GB"]:
        if num_bytes < 1024.0:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} TB"


class DropZone(ctk.CTkFrame):
    """
    Visual drag-and-drop zone with file preview, browse button, and clear button.
    """

    def __init__(
        self,
        master,
        on_file_selected: Callable[[str], None],
        get_translation: Callable[[str], str],
        is_file_supported: Optional[Callable[[Path], bool]] = None,
        supported_extensions_fn: Optional[Callable[[], List[str]]] = None,
        on_invalid_file: Optional[Callable[[str, str], None]] = None,
        config_provider: Optional[Callable[[], object]] = None,
        **kwargs
    ):
        super().__init__(
            master,
            corner_radius=10,
            border_width=1,
            border_color=("#E4E4E7", "#27272A"),
            fg_color="transparent",
            **kwargs
        )
        self.on_file_selected = on_file_selected
        self.t = get_translation
        self._is_file_supported = is_file_supported or TranslatorRegistry.is_supported
        self._supported_extensions_fn = supported_extensions_fn or TranslatorRegistry.get_supported_extensions
        self.on_invalid_file = on_invalid_file
        self._config_provider = config_provider
        self.selected_file: Optional[str] = None
        self._enabled = True
        self._inspect_token = 0
        self._last_inspect_info: Optional[dict] = None
        self._last_inspect_suffix: str = ""
        self._last_file_size: int = 0
        self._border_reset_after_id = None

        self._setup_ui()
        self._setup_dnd()

    def _sorted_supported_extensions(self) -> List[str]:
        return sorted({e.lower() for e in self._supported_extensions_fn()})

    def _format_supported_extensions(self) -> str:
        return ", ".join(self._sorted_supported_extensions())

    def _format_supported_patterns(self) -> str:
        exts = self._sorted_supported_extensions()
        return " ".join(f"*{ext}" for ext in exts) or "*.*"

    def _setup_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.inner_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.inner_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # Icon or badge
        self.icon_label = ctk.CTkLabel(
            self.inner_frame,
            text="",
            image=get_icon("folder_hero", "default", 44),
            cursor="hand2"
        )
        self.icon_label.pack(pady=(5, 8))

        # Title prompt
        self.title_label = ctk.CTkLabel(
            self.inner_frame,
            text=self.t("drag_drop_title", formats=self._format_supported_extensions()),
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=("#18181B", "#FAFAFA"),
            cursor="hand2"
        )
        self.title_label.pack(pady=(0, 2))

        # Subtitle
        self.subtitle_label = ctk.CTkLabel(
            self.inner_frame,
            text=self.t("drag_drop_subtitle"),
            font=ctk.CTkFont(size=12),
            text_color=("#71717A", "#A1A1AA")
        )
        self.subtitle_label.pack(pady=(0, 10))

        # Browse & Clear action buttons
        self.btn_frame = ctk.CTkFrame(self.inner_frame, fg_color="transparent")
        self.btn_frame.pack(pady=5)

        self.browse_btn = CustomButton(
            self.btn_frame,
            text=self.t("browse_button"),
            command=self._browse_file,
            variant="secondary",
            size="md",
            width=140
        )
        self.browse_btn.pack(side="left", padx=6)

        self.clear_btn = CustomButton(
            self.btn_frame,
            text=self.t("clear_file"),
            command=self.clear,
            variant="outline",
            size="md",
            width=80
        )
        # Hidden until a file is selected

        # Selected file status tag
        self.file_info_label = ctk.CTkLabel(
            self.inner_frame,
            text="",
            font=ctk.CTkFont(size=12),
            text_color=("#71717A", "#A1A1AA")
        )

        # Pre-scan Inspector badge
        self.inspector_label = ctk.CTkLabel(
            self.inner_frame,
            text="",
            font=ctk.CTkFont(size=11),
            fg_color=("#F4F4F5", "#27272A"),
            text_color=("#71717A", "#A1A1AA"),
            corner_radius=6,
            padx=10,
            pady=4
        )

        # Large file / high request count warning badge
        self.workload_warning_label = ctk.CTkLabel(
            self.inner_frame,
            text="",
            font=ctk.CTkFont(size=11),
            fg_color=("#FEF3C7", "#451A03"),
            text_color=("#B45309", "#FBBF24"),
            corner_radius=6,
            padx=10,
            pady=4,
            wraplength=540,
            justify="center",
        )

        # Bind click to browse when no file is selected
        def _on_zone_click(e=None):
            if self._enabled and not self.selected_file:
                self._browse_file()

        self.bind("<Button-1>", _on_zone_click)
        self.inner_frame.bind("<Button-1>", _on_zone_click)
        self.title_label.bind("<Button-1>", _on_zone_click)
        self.subtitle_label.bind("<Button-1>", _on_zone_click)
        self.icon_label.bind("<Button-1>", _on_zone_click)

    def _setup_dnd(self):
        """Enable drag and drop if TkinterDnD is available."""
        if HAS_TKDND:
            try:
                self.drop_target_register(DND_FILES)
                self.dnd_bind("<<Drop>>", self._on_drop)
                self.dnd_bind("<<DragEnter>>", self._on_drag_enter)
                self.dnd_bind("<<DragLeave>>", self._on_drag_leave)
            except Exception as e:
                print(f"[Info] TkinterDnD registration note: {e}")

    def _on_drag_enter(self, event):
        self.configure(border_color=("#71717A", "#A1A1AA"))

    def _on_drag_leave(self, event):
        self.configure(
            border_color=("#71717A", "#A1A1AA") if self.selected_file else ("#E4E4E7", "#27272A")
        )

    def _parse_drop_paths(self, raw_data: str) -> List[str]:
        if not raw_data:
            return []
        try:
            items = list(self.tk.splitlist(raw_data))
        except Exception:
            items = [raw_data]
        cleaned_items: List[str] = []
        for item in items:
            cleaned = str(item).strip()
            if (cleaned.startswith("{") and cleaned.endswith("}")) or (
                cleaned.startswith('"') and cleaned.endswith('"')
            ):
                cleaned = cleaned[1:-1]
            if cleaned:
                cleaned_items.append(cleaned)
        return cleaned_items

    def _notify_invalid_file(self, reason: str, file_path: str):
        self.configure(border_color=("#DC2626", "#EF4444"))
        if getattr(self, "_border_reset_after_id", None):
            try:
                self.after_cancel(self._border_reset_after_id)
            except Exception:
                pass
        def _reset_border():
            self._border_reset_after_id = None
            try:
                if self.winfo_exists():
                    self.configure(
                        border_color=("#71717A", "#A1A1AA") if self.selected_file else ("#E4E4E7", "#27272A")
                    )
            except Exception:
                pass
        try:
            self._border_reset_after_id = self.after(2000, _reset_border)
        except Exception:
            self._border_reset_after_id = None

        msg_key = "err_unsupported_file" if reason == "unsupported" else "err_no_file"
        msg = (
            self.t(msg_key, formats=self._format_supported_extensions())
            if reason == "unsupported"
            else self.t(msg_key)
        )
        if not self.selected_file:
            self.inspector_label.configure(text=msg, text_color=("#DC2626", "#EF4444"))
            self.inspector_label.pack(pady=(6, 2))
        if self.on_invalid_file:
            self.on_invalid_file(msg, file_path)

    def _on_drop(self, event):
        self.configure(
            border_color=("#71717A", "#A1A1AA") if self.selected_file else ("#E4E4E7", "#27272A")
        )
        if not self._enabled:
            return
        paths = self._parse_drop_paths(event.data)
        if not paths:
            return
        self.set_file(paths[0])

    def _browse_file(self):
        if not self._enabled:
            return
        supported_exts = set(self._sorted_supported_extensions())
        all_pattern = self._format_supported_patterns()
        filetypes = [(self.t("filetype_supported", patterns=all_pattern), all_pattern)]

        def _filter_exts(label_key: str, exts: list[str]):
            allowed = [f"*{e}" for e in exts if e in supported_exts]
            if allowed:
                filetypes.append((self.t(label_key), " ".join(allowed)))

        _filter_exts("filetype_pdf", [".pdf"])
        _filter_exts("filetype_office", [".docx", ".pptx"])
        _filter_exts("filetype_spreadsheets", [".xlsx", ".csv", ".tsv"])
        _filter_exts("filetype_text", [".md", ".txt"])
        _filter_exts("filetype_json", [".json"])
        filetypes.append((self.t("filetype_all"), "*.*"))

        chosen = filedialog.askopenfilename(title=self.t("dialog_select_file"), filetypes=filetypes)
        if chosen:
            self.set_file(chosen)

    def set_file(self, file_path: str):
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            self._notify_invalid_file("not_file", file_path)
            return

        if not self._is_file_supported(path):
            self._notify_invalid_file("unsupported", file_path)
            return

        suffix = path.suffix.lower()
        self.selected_file = str(path.resolve())
        self._inspect_token += 1
        self._last_inspect_info = None
        self._last_inspect_suffix = suffix
        self.inspector_label.pack_forget()
        self.inspector_label.configure(text="", text_color=("#71717A", "#A1A1AA"))
        self.workload_warning_label.pack_forget()
        self.workload_warning_label.configure(text="")
        file_size = path.stat().st_size
        self._last_file_size = file_size
        size_str = format_file_size(file_size)
        
        # Display file info with dynamic badge
        icon_name, badge = get_file_type_badge(suffix, self.t)
        self.icon_label.configure(text="", image=get_icon(icon_name, "default", 44))
        self.title_label.configure(text=f"[{badge}]  {path.name}")
        self.subtitle_label.configure(text=self.t("file_info_path", path=path.parent))
        self.file_info_label.configure(text=self.t("file_info_size", size=size_str))
        self.file_info_label.pack(pady=(4, 0))

        # Show clear button
        self.clear_btn.pack(side="left", padx=6)
        self.configure(border_color=("#71717A", "#A1A1AA"))

        # Run Pre-scan File Inspection in background thread
        self._update_workload_warning()
        self._run_inspection(self.selected_file, suffix)

        self.on_file_selected(self.selected_file)

    def _format_inspection_text(self, suffix: str, info: dict) -> str:
        if suffix == ".xlsx":
            return self.t(
                "inspect_excel_badge",
                sheets=info.get("sheet_count", 0),
                cells=info.get("translatable_cells", 0),
                unique=info.get("unique_texts", 0),
                formulas=info.get("formula_count", 0)
            )
        if suffix == ".md":
            return self.t(
                "inspect_md_badge",
                words=info.get("word_count", 0),
                sections=info.get("section_count", 0),
                chars=info.get("char_count", 0)
            )
        if suffix == ".docx":
            return self.t(
                "inspect_docx_badge",
                paragraphs=info.get("paragraphs", 0),
                tables=info.get("tables", 0),
                words=info.get("word_count", 0),
                segments=info.get("translatable_segments", 0)
            )
        if suffix == ".pptx":
            return self.t(
                "inspect_pptx_badge",
                slides=info.get("slides", 0),
                shapes=info.get("shapes", 0),
                words=info.get("word_count", 0),
                segments=info.get("translatable_segments", 0)
            )
        if suffix == ".pdf":
            return self.t(
                "inspect_pdf_badge",
                pages=info.get("page_count", 0),
                words=info.get("word_count", 0),
                segments=info.get("translatable_segments", 0),
                chars=info.get("char_count", 0)
            )
        if suffix in [".csv", ".tsv"]:
            return self.t(
                "inspect_csv_badge",
                rows=info.get("rows", 0),
                cols=info.get("columns", 0),
                cells=info.get("translatable_cells", 0),
                unique=info.get("unique_texts", 0)
            )
        if suffix == ".json":
            return self.t(
                "inspect_json_badge",
                keys=info.get("total_keys", 0),
                strings=info.get("translatable_strings", 0),
                unique=info.get("unique_texts", 0)
            )
        if suffix == ".txt":
            return self.t(
                "inspect_txt_badge",
                lines=info.get("line_count", 0),
                words=info.get("word_count", 0),
                chars=info.get("char_count", 0)
            )
        return ""

    def _run_inspection(self, file_path: str, suffix: str):
        import threading

        token = self._inspect_token

        def worker():
            try:
                info = TranslatorRegistry.inspect(file_path)
                if not info or "error" in info:
                    return
                self.after(
                    0,
                    lambda tok=token, p=file_path, s=suffix, data=info: self._on_inspection_ready(tok, p, s, data),
                )
            except Exception as e:
                print(f"[Debug] Inspector note: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _update_workload_warning(self):
        if not self.selected_file or self._config_provider is None:
            self.workload_warning_label.pack_forget()
            self.workload_warning_label.configure(text="")
            return

        size_bytes = self._last_file_size
        size_str = format_file_size(size_bytes)
        if self._last_inspect_info is None:
            if size_bytes >= LARGE_FILE_SIZE_BYTES:
                self.workload_warning_label.configure(
                    text=self.t("large_file_badge_scanning", size=size_str)
                )
                self.workload_warning_label.pack(pady=(4, 2))
            else:
                self.workload_warning_label.pack_forget()
                self.workload_warning_label.configure(text="")
            return

        cfg = self._config_provider()
        est_reqs = estimate_translation_requests(self._last_inspect_info, cfg)
        if size_bytes >= LARGE_FILE_SIZE_BYTES or est_reqs >= HIGH_REQUEST_WARNING_THRESHOLD:
            self.workload_warning_label.configure(
                text=self.t("large_file_badge_warning", size=size_str, reqs=est_reqs)
            )
            self.workload_warning_label.pack(pady=(4, 2))
        else:
            self.workload_warning_label.pack_forget()
            self.workload_warning_label.configure(text="")

    def _on_inspection_ready(self, token: int, file_path: str, suffix: str, info: dict):
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        if token != self._inspect_token or self.selected_file != file_path:
            return
        self._last_inspect_info = info
        self._last_inspect_suffix = suffix
        msg = self._format_inspection_text(suffix, info)
        self._show_inspection(msg)
        self._update_workload_warning()

    def _show_inspection(self, text: str):
        if self.selected_file and text:
            self.inspector_label.configure(text=text, text_color=("#71717A", "#A1A1AA"))
            self.inspector_label.pack(pady=(6, 2))

    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        state = "normal" if enabled else "disabled"
        self.browse_btn.configure(state=state)
        self.clear_btn.configure(state=state)

    def clear(self):
        self._inspect_token += 1
        self._last_inspect_info = None
        self._last_inspect_suffix = ""
        self._last_file_size = 0
        self.selected_file = None
        self.icon_label.configure(text="", image=get_icon("folder_hero", "default", 44))
        self.title_label.configure(text=self.t("drag_drop_title", formats=self._format_supported_extensions()))
        self.subtitle_label.configure(text=self.t("drag_drop_subtitle"))
        self.file_info_label.pack_forget()
        self.inspector_label.pack_forget()
        self.inspector_label.configure(text="", text_color=("#71717A", "#A1A1AA"))
        self.workload_warning_label.pack_forget()
        self.workload_warning_label.configure(text="")
        self.clear_btn.pack_forget()
        self.configure(border_color=("#E4E4E7", "#27272A"))
        self.on_file_selected("")

    def refresh_i18n(self):
        """Update localized texts when language changes."""
        self.browse_btn.set_text(self.t("browse_button"))
        self.clear_btn.set_text(self.t("clear_file"))
        if not self.selected_file:
            self.title_label.configure(text=self.t("drag_drop_title", formats=self._format_supported_extensions()))
            self.subtitle_label.configure(text=self.t("drag_drop_subtitle"))
        elif self.selected_file:
            path = Path(self.selected_file)
            if not path.exists() or not path.is_file():
                self.clear()
                return
            file_size = path.stat().st_size
            self._last_file_size = file_size
            size_str = format_file_size(file_size)
            suffix = path.suffix.lower()
            icon_name, badge = get_file_type_badge(suffix, self.t)
            self.icon_label.configure(text="", image=get_icon(icon_name, "default", 44))
            self.title_label.configure(text=f"[{badge}]  {path.name}")
            self.subtitle_label.configure(text=self.t("file_info_path", path=path.parent))
            self.file_info_label.configure(text=self.t("file_info_size", size=size_str))
            if self._last_inspect_info and self._last_inspect_suffix == suffix:
                msg = self._format_inspection_text(suffix, self._last_inspect_info)
                self._show_inspection(msg)
                self._update_workload_warning()
            else:
                self._update_workload_warning()
                self._run_inspection(self.selected_file, suffix)

    def destroy(self):
        self._inspect_token += 1
        if getattr(self, "_border_reset_after_id", None):
            try:
                self.after_cancel(self._border_reset_after_id)
            except Exception:
                pass
            self._border_reset_after_id = None
        super().destroy()
