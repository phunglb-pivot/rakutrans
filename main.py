"""
RakuTrans AI - Bootstrap & Application Entry Point.
Launches the CustomTkinter desktop user interface or provides a CLI fallback.
"""

import sys
import argparse
from pathlib import Path
from typing import Optional

from config import AppConfig, TranslationOptions, DEFAULT_TARGET_LANGUAGE


def run_cli_translation(
    file_path: str,
    tgt_lang: Optional[str] = None,
    src_lang: Optional[str] = None,
    keep_it: bool = True,
    append_source: bool = False,
    custom_context: str = "",
    model: Optional[str] = None,
    provider: Optional[str] = None
):
    """Headless CLI translation runner."""
    from llm_manager import LLMManager
    from translator_registry import TranslatorRegistry

    config = AppConfig.load()
    tgt_lang = tgt_lang or config.target_language
    if provider:
        config.active_provider = provider
    elif model:
        # Auto-detect provider from model name
        m_lower = model.lower()
        if "gemini" in m_lower:
            config.active_provider = "Gemini"
        elif any(k in m_lower for k in ["gpt", "o1", "o3", "chatgpt"]):
            config.active_provider = "OpenAI"
        elif "claude" in m_lower:
            config.active_provider = "Claude"

    if model:
        config.selected_models[config.active_provider] = model
    llm_manager = LLMManager(config)
    options = TranslationOptions(
        keep_it_terms=keep_it,
        append_original_words=append_source,
        custom_context=custom_context
    )

    path = Path(file_path)
    if not path.exists():
        print(f"Error: File '{file_path}' does not exist.")
        sys.exit(1)

    if not TranslatorRegistry.is_supported(path):
        supported = ", ".join(TranslatorRegistry.get_supported_extensions())
        print(f"Error: Unsupported file format '{path.suffix}'. Supported formats: {supported}")
        sys.exit(1)

    suffix = path.suffix.lower()
    print(f"=== RakuTrans AI CLI ===")
    print(f"File: {file_path}")
    print(f"Provider: {config.active_provider} ({config.get_active_model()})")
    print(f"Target Language: {tgt_lang} (Auto-detect mixed source)")

    def on_progress(current: int, total: int, msg: str):
        print(f"[{current:3d}%] {msg}")

    try:
        translator = TranslatorRegistry.create_translator(path, config, llm_manager)
        out_file = translator.process_file(
            file_path=file_path,
            target_lang=tgt_lang,
            source_lang=src_lang,
            options=options,
            progress_callback=on_progress
        )

        print(f"\nSuccess! Output saved to: {out_file}")
    except Exception as e:
        print(f"\nTranslation failed: {e}")
        sys.exit(1)


def launch_gui():
    """Bootstraps and launches the CustomTkinter GUI."""
    try:
        import tkinter
    except ImportError as e:
        print("\n" + "=" * 70)
        print(" [RakuTrans AI] Tkinter is not found in your current Python installation.")
        print("=" * 70)
        print("Why this happens:")
        print("  On macOS with asdf / pyenv, Python was compiled without tcl-tk.")
        print("\nQuick Solutions on macOS:")
        print("  1. Run with Homebrew Python:")
        print("       brew install python-tk@3.12")
        print("       python3.12 main.py")
        print("  2. Or reinstall your active python with Tkinter flags:")
        print("       brew install tcl-tk")
        print("       export PYTHON_CONFIGURE_OPTS=\"--with-tcltk-includes='-I$(brew --prefix tcl-tk)/include' --with-tcltk-libs='-L$(brew --prefix tcl-tk)/lib -ltcl8.6 -ltk8.6'\"")
        print("       asdf install python 3.12.9")
        print("  3. Or use RakuTrans in CLI mode right now:")
        print("       python3 main.py --cli --file document.xlsx --tgt Vietnamese")
        print("=" * 70 + "\n")
        sys.exit(1)

    from components.icons import init_windows_app_id
    init_windows_app_id()

    from ui import RakuTransApp

    app = RakuTransApp()
    app.mainloop()


def main():
    parser = argparse.ArgumentParser(
        description="RakuTrans AI - Professional Document & Data AI Translator"
    )
    parser.add_argument("--cli", action="store_true", help="Run translation in headless CLI mode")
    parser.add_argument("--file", "-f", type=str, help="Path to document file to translate (.xlsx, .docx, .pptx, .pdf, .csv, .md, .json, .txt)")
    parser.add_argument("--tgt", "-t", type=str, default=None, help=f"Target language (default: saved config or {DEFAULT_TARGET_LANGUAGE})")
    parser.add_argument("--src", "-s", type=str, default=None, help="Optional source language filter (default: auto-detect mixed)")
    parser.add_argument("--keep-terms", "--keep-it", dest="keep_it", action="store_true", default=True, help="Keep specialized/domain terms untranslated")
    parser.add_argument("--append-source", action="store_true", default=False, help="Append original words in parentheses for quoted terms")
    parser.add_argument("--context", "-c", type=str, default="", help="Custom context or glossary rules")
    parser.add_argument("--convert", "--convert-to", dest="convert_fmt", type=str, default=None, help="Directly convert document to target format without translation (e.g. docx, md, xlsx, csv, txt)")
    parser.add_argument("--model", "-m", type=str, default=None, help="AI model name (e.g. gemini-3.6-flash, gpt-4o)")
    parser.add_argument("--provider", "-p", type=str, default=None, choices=["Gemini", "OpenAI", "Claude"], help="AI provider")

    args = parser.parse_args()

    if args.file and args.convert_fmt:
        from format_converter import convert_file_direct
        try:
            print(f"[RakuTrans Converter] Converting {args.file} -> {args.convert_fmt.upper()}...")
            out = convert_file_direct(args.file, args.convert_fmt)
            print(f"[RakuTrans Converter] Conversion completed successfully! Output: {out}")
            sys.exit(0)
        except Exception as e:
            print(f"[RakuTrans Converter] Error: {e}")
            sys.exit(1)

    if args.cli or args.file:
        if not args.file:
            print("Error: --file argument is required when using CLI mode.")
            parser.print_help()
            sys.exit(1)
        run_cli_translation(
            file_path=args.file,
            tgt_lang=args.tgt,
            src_lang=args.src,
            keep_it=args.keep_it,
            append_source=args.append_source,
            custom_context=args.context,
            model=args.model,
            provider=args.provider
        )
    else:
        launch_gui()


if __name__ == "__main__":
    main()
