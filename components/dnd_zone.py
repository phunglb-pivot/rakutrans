"""
File Drag-and-Drop Dropzone component for RakuTrans AI.
Supports both native TkinterDnD2 drag & drop and interactive click-to-browse fallback.
"""

import os
from pathlib import Path
from typing import Callable, Optional
import customtkinter as ctk
from tkinter import filedialog

try:
    from tkinterdnd2 import DND_FILES
    HAS_TKDND = True
except ImportError:
    HAS_TKDND = False


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
        **kwargs
    ):
        super().__init__(master, corner_radius=12, border_width=2, border_color="#3B8ED0", **kwargs)
        self.on_file_selected = on_file_selected
        self.t = get_translation
        self.selected_file: Optional[str] = None
        self.mode: str = "translate"

        self._setup_ui()
        self._setup_dnd()

    def _setup_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.inner_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.inner_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # Icon or badge
        self.icon_label = ctk.CTkLabel(
            self.inner_frame,
            text="📂",
            font=ctk.CTkFont(size=40)
        )
        self.icon_label.pack(pady=(5, 5))

        # Title prompt
        self.title_label = ctk.CTkLabel(
            self.inner_frame,
            text=self.t("drag_drop_title"),
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.title_label.pack(pady=(0, 2))

        # Subtitle
        self.subtitle_label = ctk.CTkLabel(
            self.inner_frame,
            text=self.t("drag_drop_subtitle"),
            font=ctk.CTkFont(size=12),
            text_color="gray"
        )
        self.subtitle_label.pack(pady=(0, 10))

        # Browse & Clear action buttons
        self.btn_frame = ctk.CTkFrame(self.inner_frame, fg_color="transparent")
        self.btn_frame.pack(pady=5)

        self.browse_btn = ctk.CTkButton(
            self.btn_frame,
            text=self.t("browse_button"),
            command=self._browse_file,
            width=140,
            height=32,
            font=ctk.CTkFont(size=13, weight="bold")
        )
        self.browse_btn.pack(side="left", padx=6)

        self.clear_btn = ctk.CTkButton(
            self.btn_frame,
            text=self.t("clear_file"),
            command=self.clear,
            width=80,
            height=32,
            fg_color="transparent",
            border_width=1,
            text_color=("gray20", "gray80"),
            font=ctk.CTkFont(size=12)
        )
        # Hidden until a file is selected

        # Selected file status tag
        self.file_info_label = ctk.CTkLabel(
            self.inner_frame,
            text="",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#3B8ED0"
        )

        # Pre-scan Inspector badge
        self.inspector_label = ctk.CTkLabel(
            self.inner_frame,
            text="",
            font=ctk.CTkFont(size=11),
            fg_color=("gray85", "#1E293B"),
            corner_radius=6,
            padx=10,
            pady=4
        )

        # Bind click to browse when no file is selected
        def _on_zone_click(e=None):
            if not self.selected_file:
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
        self.configure(border_color="#10B981")  # Emerald green highlight

    def _on_drag_leave(self, event):
        self.configure(border_color="#3B8ED0")

    def _on_drop(self, event):
        self.configure(border_color="#3B8ED0")
        raw_path = event.data
        if not raw_path:
            return

        # Clean wrapped quotes or braces common in macOS/Windows DnD data
        cleaned = raw_path.strip()
        if cleaned.startswith("{") and cleaned.endswith("}"):
            cleaned = cleaned[1:-1]
        elif cleaned.startswith('"') and cleaned.endswith('"'):
            cleaned = cleaned[1:-1]

        self.set_file(cleaned)

    def _browse_file(self):
        filetypes = [
            ("Supported Documents (*.xlsx, *.md)", "*.xlsx *.md"),
            ("Excel Spreadsheets (*.xlsx)", "*.xlsx"),
            ("Markdown Documents (*.md)", "*.md"),
            ("All Files", "*.*")
        ]
        chosen = filedialog.askopenfilename(title="Select Document to Translate", filetypes=filetypes)
        if chosen:
            self.set_file(chosen)

    def set_file(self, file_path: str):
        path = Path(file_path)
        if not path.exists():
            return

        suffix = path.suffix.lower()
        if suffix not in [".xlsx", ".md"]:
            return

        self.selected_file = str(path.resolve())
        size_str = format_file_size(path.stat().st_size)
        
        # Display file info
        badge = "📊 Excel" if suffix == ".xlsx" else "📝 Markdown"
        self.icon_label.configure(text="📊" if suffix == ".xlsx" else "📝")
        self.title_label.configure(text=f"{badge}: {path.name}")
        self.subtitle_label.configure(text=f"Path: {path.parent}")
        self.file_info_label.configure(text=f"Size: {size_str}")
        self.file_info_label.pack(pady=(4, 0))

        # Show clear button
        self.clear_btn.pack(side="left", padx=6)
        self.configure(border_color="#10B981")

        # Run Pre-scan File Inspection in background thread
        self._run_inspection(self.selected_file, suffix)

        self.on_file_selected(self.selected_file)

    def set_mode(self, mode: str):
        """Update active mode ('translate' or 'convert') and refresh inspection badge if file is loaded."""
        self.mode = mode
        if self.selected_file:
            suffix = Path(self.selected_file).suffix.lower()
            self._run_inspection(self.selected_file, suffix)

    def _run_inspection(self, file_path: str, suffix: str):
        import threading

        def worker():
            try:
                if suffix == ".xlsx":
                    from excel_parser import ExcelTranslator
                    info = ExcelTranslator.inspect_file(file_path)
                    if "error" not in info:
                        if self.mode == "convert":
                            msg = self.t(
                                "inspect_excel_convert_badge",
                                sheets=info.get("sheet_count", 0),
                                cells=info.get("translatable_cells", 0),
                                formulas=info.get("formula_count", 0)
                            )
                        else:
                            msg = self.t(
                                "inspect_excel_badge",
                                sheets=info.get("sheet_count", 0),
                                cells=info.get("translatable_cells", 0),
                                unique=info.get("unique_texts", 0),
                                formulas=info.get("formula_count", 0)
                            )
                        self.after(0, lambda: self._show_inspection(msg))
                elif suffix == ".md":
                    from markdown_parser import MarkdownTranslator
                    info = MarkdownTranslator.inspect_file(file_path)
                    if "error" not in info:
                        msg = self.t(
                            "inspect_md_badge",
                            words=info.get("word_count", 0),
                            sections=info.get("section_count", 0),
                            chars=info.get("char_count", 0)
                        )
                        self.after(0, lambda: self._show_inspection(msg))
            except Exception as e:
                print(f"[Debug] Inspector note: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _show_inspection(self, text: str):
        if self.selected_file and text:
            self.inspector_label.configure(text=text)
            self.inspector_label.pack(pady=(6, 2))

    def clear(self):
        self.selected_file = None
        self.icon_label.configure(text="📂")
        self.title_label.configure(text=self.t("drag_drop_title"))
        self.subtitle_label.configure(text=self.t("drag_drop_subtitle"))
        self.file_info_label.pack_forget()
        self.inspector_label.pack_forget()
        self.inspector_label.configure(text="")
        self.clear_btn.pack_forget()
        self.configure(border_color="#3B8ED0")
        self.on_file_selected("")

    def refresh_i18n(self):
        """Update localized texts when language changes."""
        self.browse_btn.configure(text=self.t("browse_button"))
        self.clear_btn.configure(text=self.t("clear_file"))
        if not self.selected_file:
            self.title_label.configure(text=self.t("drag_drop_title"))
            self.subtitle_label.configure(text=self.t("drag_drop_subtitle"))
        elif self.selected_file:
            suffix = Path(self.selected_file).suffix.lower()
            self._run_inspection(self.selected_file, suffix)
