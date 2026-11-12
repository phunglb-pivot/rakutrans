"""
Unit tests for Searchable Select language component, diacritics stripping, and language catalog.
"""

import unittest
from config import (
    get_all_languages,
    DEFAULT_TARGET_LANGUAGE,
    normalize_language_name,
    get_target_lang_code
)
from components.searchable_select import _strip_accents


class TestSearchableSelect(unittest.TestCase):

    def test_strip_accents(self):
        self.assertEqual(_strip_accents("Tiếng Việt"), "Tieng Viet")
        self.assertEqual(_strip_accents("Français"), "Francais")
        self.assertEqual(_strip_accents("Español"), "Espanol")
        self.assertEqual(_strip_accents("München"), "Munchen")
        self.assertEqual(_strip_accents("English"), "English")
        self.assertEqual(_strip_accents("日本語"), "日本語")

    def test_all_languages_catalog(self):
        langs = get_all_languages()
        self.assertTrue(len(langs) >= 50)

        # Check alphabetical order by English name
        names = [l.name.lower() for l in langs]
        self.assertEqual(names, sorted(names))
        self.assertEqual(DEFAULT_TARGET_LANGUAGE, "English (English)")

        # Check key languages exist
        codes = {l.code for l in langs}
        self.assertIn("vi", codes)
        self.assertIn("en", codes)
        self.assertIn("ja", codes)
        self.assertIn("zh-CN", codes)
        self.assertIn("ko", codes)
        self.assertIn("fr", codes)
        self.assertIn("de", codes)
        self.assertIn("es", codes)

        # Check display_name format: "Native (English)"
        for l in langs:
            self.assertIn("(", l.display_name)
            self.assertIn(")", l.display_name)
            self.assertTrue(l.display_name.startswith(l.native_name))

    def test_normalize_language_name(self):
        # Code inputs
        self.assertEqual(normalize_language_name("vi"), "Tiếng Việt (Vietnamese)")
        self.assertEqual(normalize_language_name("en"), "English (English)")
        self.assertEqual(normalize_language_name("ja"), "日本語 (Japanese)")
        self.assertEqual(normalize_language_name("fr"), "Français (French)")
        self.assertEqual(normalize_language_name("ko"), "한국어 (Korean)")

        # English name inputs
        self.assertEqual(normalize_language_name("Vietnamese"), "Tiếng Việt (Vietnamese)")
        self.assertEqual(normalize_language_name("Japanese"), "日本語 (Japanese)")
        self.assertEqual(normalize_language_name("German"), "Deutsch (German)")

        # Native name inputs
        self.assertEqual(normalize_language_name("Tiếng Việt"), "Tiếng Việt (Vietnamese)")
        self.assertEqual(normalize_language_name("日本語"), "日本語 (Japanese)")

        # Already full display format
        self.assertEqual(normalize_language_name("Tiếng Việt (Vietnamese)"), "Tiếng Việt (Vietnamese)")

        # None / Empty fallback
        self.assertEqual(normalize_language_name(None), DEFAULT_TARGET_LANGUAGE)
        self.assertEqual(normalize_language_name(""), DEFAULT_TARGET_LANGUAGE)

    def test_get_target_lang_code(self):
        self.assertEqual(get_target_lang_code("Tiếng Việt (Vietnamese)"), "vi")
        self.assertEqual(get_target_lang_code("Vietnamese"), "vi")
        self.assertEqual(get_target_lang_code("vi"), "vi")
        self.assertEqual(get_target_lang_code("日本語 (Japanese)"), "ja")
        self.assertEqual(get_target_lang_code("Japanese"), "ja")
        self.assertEqual(get_target_lang_code("English (English)"), "en")
        self.assertEqual(get_target_lang_code("Français (French)"), "fr")
        self.assertEqual(get_target_lang_code("한국어 (Korean)"), "ko")
        self.assertEqual(get_target_lang_code("Deutsch (German)"), "de")
        self.assertEqual(get_target_lang_code("Español (Spanish)"), "es")
        self.assertEqual(get_target_lang_code("Русский (Russian)"), "ru")
        self.assertEqual(get_target_lang_code("ไทย (Thai)"), "th")

    def test_floating_overlay_zero_layout_shift(self):
        """Verify that opening the dropdown floats over content with zero layout shift."""
        import customtkinter as ctk
        from components.searchable_select import SearchableLanguageSelect

        root = ctk.CTk()
        root.geometry("500x600")

        frame = ctk.CTkFrame(root)
        frame.pack(fill="both", expand=True, padx=20, pady=20)

        changed_vals = []
        sel = SearchableLanguageSelect(
            frame,
            current_language="en",
            on_change=lambda v: changed_vals.append(v),
            width=300,
            height=36
        )
        sel.pack(fill="x", pady=(0, 10))

        below_widget = ctk.CTkLabel(frame, text="Dropzone content below", height=80)
        below_widget.pack(fill="x")

        root.update()

        initial_sel_height = sel.winfo_height()
        y_before = below_widget.winfo_rooty()

        # Open dropdown
        sel.open()
        root.update()

        # Height of the select widget container expands when dropdown panel is opened
        self.assertGreater(sel.winfo_height(), initial_sel_height)
        # Panel should be mapped
        self.assertTrue(sel.is_open)
        self.assertTrue(sel.panel.winfo_ismapped())

        # Select a language programmatically
        sel._choose("Tiếng Việt (Vietnamese)")
        root.update()

        self.assertFalse(sel.is_open)
        self.assertEqual(sel.get(), "Tiếng Việt (Vietnamese)")
        self.assertEqual(changed_vals, ["Tiếng Việt (Vietnamese)"])
        self.assertEqual(below_widget.winfo_rooty(), y_before)

        # Test click outside auto-dismiss
        sel.open()
        root.update()
        self.assertTrue(sel.is_open)

        # Simulate click outside (top-left corner of root window)
        root.event_generate("<ButtonPress-1>", x=5, y=5)
        root.update()
        self.assertFalse(sel.is_open)

        # Test click input toggles open / close
        btn = sel.trigger_btn
        leaf = root.winfo_containing(btn.winfo_rootx() + 50, btn.winfo_rooty() + 15)
        leaf.event_generate("<ButtonPress-1>", x=10, y=10)
        root.update()
        leaf.event_generate("<ButtonRelease-1>", x=10, y=10)
        root.update()
        self.assertTrue(sel.is_open)

        leaf.event_generate("<ButtonPress-1>", x=10, y=10)
        root.update()
        leaf.event_generate("<ButtonRelease-1>", x=10, y=10)
        root.update()
        self.assertFalse(sel.is_open)

        # Test search scrolls list back up to the top
        sel.open()
        root.update()
        sel.scroll_list._parent_canvas.yview_moveto(0.9)
        root.update()
        self.assertGreater(sel.scroll_list._parent_canvas.yview()[0], 0.4)

        sel.search_var.set("viet")
        root.update()
        self.assertEqual(sel.scroll_list._parent_canvas.yview()[0], 0.0)

        root.destroy()

    def test_recent_languages_behavior(self):
        """Verify that recent languages list keeps max 3 items and orders by MRU."""
        import customtkinter as ctk
        from components.searchable_select import SearchableLanguageSelect

        root = ctk.CTk()
        root.geometry("400x500")

        sel = SearchableLanguageSelect(
            root,
            current_language="vi",
            recent_languages=[
                "Tiếng Việt (Vietnamese)",
                "English (English)",
                "日本語 (Japanese)"
            ]
        )
        sel.pack()
        root.update()

        # Initial recents
        self.assertEqual(len(sel.recent_languages), 3)
        self.assertEqual(sel.recent_languages[0], "Tiếng Việt (Vietnamese)")

        # Choosing another language (e.g. French) pushes it to the front and keeps max 3
        sel._choose("Français (French)")
        root.update()

        self.assertEqual(len(sel.recent_languages), 3)
        self.assertEqual(sel.recent_languages[0], "Français (French)")
        self.assertEqual(sel.recent_languages[1], "Tiếng Việt (Vietnamese)")
        self.assertEqual(sel.recent_languages[2], "English (English)")

        # Choosing an existing recent language (e.g. English) moves it to the front
        sel._choose("English (English)")
        root.update()

        self.assertEqual(len(sel.recent_languages), 3)
        self.assertEqual(sel.recent_languages[0], "English (English)")
        self.assertEqual(sel.recent_languages[1], "Français (French)")
        self.assertEqual(sel.recent_languages[2], "Tiếng Việt (Vietnamese)")

        # Test set_recent_languages
        sel.set_recent_languages(["German", "Korean", "Spanish", "Italian"])
        self.assertEqual(len(sel.recent_languages), 3)
        self.assertEqual(sel.recent_languages[0], "Deutsch (German)")
        self.assertEqual(sel.recent_languages[1], "한국어 (Korean)")
        self.assertEqual(sel.recent_languages[2], "Español (Spanish)")

        # Test opening dropdown with recents rendered
        sel.open()
        root.update()
        self.assertTrue(sel.is_open)

        # When searching, recent section is hidden and results are filtered
        sel.search_var.set("viet")
        root.update()
        btn_texts = [b.cget("text") for b in sel._buttons]
        self.assertTrue(any("Vietnamese" in t for t in btn_texts))

        root.destroy()


if __name__ == "__main__":
    unittest.main()

