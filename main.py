"""
RakuTrans AI - Bootstrap & Application Entry Point.
Launches the CustomTkinter desktop user interface or provides a CLI fallback.
"""

import sys
import argparse
from pathlib import Path

from config import AppConfig, TranslationOptions


def run_cli_translation(
    file_path: str,
    tgt_lang: str = "Vietnamese",
    src_lang: str = None,
    keep_it: bool = True,
    append_source: bool = False,
    custom_context: str = "",
    model: str = None,
    provider: str = None,
    output_format: str = "auto"
):
    """Headless CLI translation runner."""
    from llm_manager import LLMManager
    from translator_registry import TranslatorRegistry
    from format_converter import convert_translated_output

    config = AppConfig.load()
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
    if output_format and output_format != "auto":
        print(f"Output Format: {output_format.upper()}")

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

        # Cross-format conversion if requested
        if output_format and output_format != "auto":
            final_out = convert_translated_output(out_file, output_format)
            if final_out != out_file:
                print(f"Format converted ({output_format}): {final_out}")
                out_file = final_out

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

    from ui import RakuTransApp

    app = RakuTransApp()
    app.mainloop()


def main():
    parser = argparse.ArgumentParser(
        description="RakuTrans AI - Professional Document & Data AI Translator"
    )
    parser.add_argument("--cli", action="store_true", help="Run translation in headless CLI mode")
    parser.add_argument("--file", "-f", type=str, help="Path to document file to translate (.xlsx, .docx, .pptx, .csv, .md, .json, .txt)")
    parser.add_argument("--tgt", "-t", type=str, default="Vietnamese", help="Target language (default: Vietnamese)")
    parser.add_argument("--src", "-s", type=str, default=None, help="Optional source language filter (default: auto-detect mixed)")
    parser.add_argument("--keep-terms", "--keep-it", dest="keep_it", action="store_true", default=True, help="Keep specialized/domain terms untranslated")
    parser.add_argument("--append-source", action="store_true", default=False, help="Append original words in parentheses for quoted terms")
    parser.add_argument("--context", "-c", type=str, default="", help="Custom context or glossary rules")
    parser.add_argument("--model", "-m", type=str, default=None, help="AI model name (e.g. gemini-3.6-flash, gpt-4o)")
    parser.add_argument("--provider", "-p", type=str, default=None, choices=["Gemini", "OpenAI", "Claude"], help="AI provider")
    parser.add_argument("--output-format", "-out-fmt", type=str, default="auto", choices=["auto", "xlsx", "md", "docx", "csv", "tsv", "txt"], help="Target output format: auto, xlsx, md, docx, csv, txt")

    args = parser.parse_args()

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
            provider=args.provider,
            output_format=args.output_format
        )
    else:
        launch_gui()


if __name__ == "__main__":
    main()
