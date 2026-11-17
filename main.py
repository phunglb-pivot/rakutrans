"""
RakuTrans AI - Bootstrap & Application Entry Point.
Launches the CustomTkinter desktop user interface or provides a CLI fallback.
"""

import sys

if sys.version_info < (3, 10):
    print(
        f"[RakuTrans AI] Python 3.10 or higher is required "
        f"(detected {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}).\n"
        "Run ./run.sh (macOS/Linux) or run_windows.bat (Windows) to auto-detect a compatible Python."
    )
    sys.exit(1)

import argparse
from pathlib import Path
from typing import Optional

from config import AI_PROVIDERS, APP_NAME, AppConfig, TranslationOptions, DEFAULT_TARGET_LANGUAGE
from i18n import I18nManager


def run_cli_translation(
    file_path: str,
    tgt_lang: Optional[str] = None,
    src_lang: Optional[str] = None,
    keep_it: bool = True,
    append_source: bool = False,
    bilingual: bool = False,
    custom_context: str = "",
    model: Optional[str] = None,
    provider: Optional[str] = None,
    output_path: Optional[str] = None,
):
    """Headless CLI translation runner."""
    from llm_manager import LLMManager
    from translator_registry import TranslatorRegistry

    config = AppConfig.load()
    i18n = I18nManager(config.ui_language)
    tgt_lang = tgt_lang or config.target_language

    clean_model = (model or "").strip()
    clean_provider = (provider or "").strip()
    if clean_model and not clean_provider:
        print(i18n.t("cli_err_model_requires_provider"))
        sys.exit(1)

    if clean_provider:
        if clean_provider not in AI_PROVIDERS:
            print(
                i18n.t(
                    "cli_err_unknown_provider",
                    provider=clean_provider,
                    providers=", ".join(AI_PROVIDERS.keys()),
                )
            )
            sys.exit(1)
        config.active_provider = clean_provider

    if clean_provider or clean_model:
        # Never persist temporary CLI --provider/--model overrides into GUI config.json
        config.save = lambda: None
    if clean_model:
        config.selected_models[config.active_provider] = clean_model

    active_provider = (config.active_provider or "").strip()
    if active_provider not in AI_PROVIDERS:
        print(
            i18n.t(
                "cli_err_unknown_provider",
                provider=active_provider or "(none)",
                providers=", ".join(AI_PROVIDERS.keys()),
            )
        )
        sys.exit(1)

    active_model = (config.get_active_model() or "").strip()
    if not active_model:
        print(i18n.t("cli_err_no_model", provider=active_provider))
        sys.exit(1)

    active_key = (config.get_effective_api_key(active_provider) or "").strip()
    if not active_key:
        env_var = AI_PROVIDERS[active_provider].get("env_key", "")
        print(
            i18n.t(
                "cli_err_no_api_key",
                provider=active_provider,
                env_var=env_var,
            )
        )
        sys.exit(1)

    path = Path(file_path)
    if not path.exists():
        print(i18n.t("cli_err_file_not_found", path=file_path))
        sys.exit(1)

    if not TranslatorRegistry.is_supported(path):
        supported = ", ".join(TranslatorRegistry.get_supported_extensions())
        print(
            i18n.t(
                "cli_err_unsupported_file",
                error=f"'{path.suffix}' ({supported})",
            )
        )
        sys.exit(1)

    if bilingual and not TranslatorRegistry.supports_bilingual(path):
        bilingual_exts = ", ".join(TranslatorRegistry.get_bilingual_extensions()) or ".xlsx"
        print(
            i18n.t(
                "cli_warn_bilingual_ignored",
                extensions=bilingual_exts,
                suffix=path.suffix or "(none)",
            )
        )
        bilingual = False

    llm_manager = LLMManager(config)
    options = TranslationOptions(
        keep_it_terms=keep_it,
        append_original_words=append_source,
        custom_context=custom_context,
        bilingual_mode=bilingual,
    )

    print(
        i18n.t(
            "cli_translating_header",
            filename=path.name,
            target_lang=tgt_lang,
            provider=active_provider,
            model=active_model,
        )
    )

    def on_progress(current: int, _total: int, msg: str):
        print(i18n.t("cli_progress_line", pct=current, message=msg))

    try:
        translator = TranslatorRegistry.create_translator(path, config, llm_manager)
        out_file = translator.process_file(
            file_path=file_path,
            target_lang=tgt_lang,
            source_lang=src_lang or "auto",
            options=options,
            progress_callback=on_progress,
            custom_output_path=output_path,
        )

        print(i18n.t("cli_success_saved", path=out_file))
    except InterruptedError as e:
        print(i18n.t("cli_cancelled", error=e))
        sys.exit(1)
    except Exception as e:
        print(i18n.t("cli_failed", message=e))
        sys.exit(1)


def launch_gui():
    """Bootstraps and launches the CustomTkinter GUI."""
    try:
        import tkinter
    except ImportError:
        py_mm = f"{sys.version_info.major}.{sys.version_info.minor}"
        py_ver = f"{py_mm}.{sys.version_info.micro}"
        print("\n" + "=" * 70)
        print(f" [RakuTrans AI] Tkinter is not found in your current Python ({py_ver}).")
        print("=" * 70)
        print("Why this happens:")
        print("  On macOS with asdf / pyenv, Python was compiled without tcl-tk.")
        print("\nQuick Solutions on macOS:")
        print("  1. Use ./run.sh (it automatically finds a Python 3.10+ with Tkinter if installed)")
        print("  2. Or install Tkinter for Homebrew Python:")
        print(f"       brew install python-tk@{py_mm}")
        print(f"       python{py_mm} main.py")
        print("  3. Or reinstall your active python with Tkinter flags:")
        print("       brew install tcl-tk")
        print("       export PYTHON_CONFIGURE_OPTS=\"--with-tcltk-includes='-I$(brew --prefix tcl-tk)/include' --with-tcltk-libs='-L$(brew --prefix tcl-tk)/lib -ltcl8.6 -ltk8.6'\"")
        print(f"       asdf install python {py_ver}")
        print("  4. Or use RakuTrans in CLI mode right now:")
        print("       python3 main.py --cli --file document.xlsx --tgt Vietnamese")
        print("=" * 70 + "\n")
        sys.exit(1)

    from components.icons import init_windows_app_id
    init_windows_app_id()

    from ui import RakuTransApp

    app = RakuTransApp()
    app.mainloop()


def build_cli_parser() -> argparse.ArgumentParser:
    from format_converter import get_supported_conversion_targets
    from translator_registry import TranslatorRegistry

    supported_exts = ", ".join(TranslatorRegistry.get_supported_extensions())
    convert_targets = ", ".join(get_supported_conversion_targets())
    bilingual_exts = ", ".join(TranslatorRegistry.get_bilingual_extensions())

    parser = argparse.ArgumentParser(
        description=f"{APP_NAME} - Professional Document & Data AI Translator"
    )
    parser.add_argument("--cli", action="store_true", help="Run translation in headless CLI mode")
    parser.add_argument("--file", "-f", type=str, help=f"Path to document file ({supported_exts})")
    parser.add_argument("--tgt", "-t", type=str, default=None, help=f"Target language (default: saved config or {DEFAULT_TARGET_LANGUAGE})")
    parser.add_argument("--src", "-s", type=str, default=None, help="Optional source language filter (default: auto-detect mixed)")
    parser.add_argument("--keep-terms", "--keep-it", dest="keep_it", action=argparse.BooleanOptionalAction, default=True, help="Keep specialized/domain terms untranslated (use --no-keep-terms to disable)")
    parser.add_argument("--append-source", action="store_true", default=False, help="Append original words in parentheses for quoted terms")
    parser.add_argument("--bilingual", action="store_true", default=False, help=f"Keep original sheets alongside translations ({bilingual_exts})")
    parser.add_argument("--context", "-c", type=str, default="", help="Custom context or glossary rules")
    parser.add_argument("--convert", "--convert-to", dest="convert_fmt", type=str, default=None, help=f"Directly convert document to target format without translation (e.g. {convert_targets})")
    parser.add_argument("--output", "-o", dest="output_path", type=str, default=None, help="Optional custom output file path")
    parser.add_argument("--model", "-m", type=str, default=None, help="AI model name")
    parser.add_argument("--provider", "-p", type=str, default=None, choices=list(AI_PROVIDERS.keys()), help="AI provider")
    return parser


def main():
    parser = build_cli_parser()
    args = parser.parse_args()

    if args.convert_fmt and not args.file:
        i18n = I18nManager(AppConfig.load().ui_language)
        print(i18n.t("cli_err_convert_requires_file"))
        sys.exit(1)

    if args.file and args.convert_fmt:
        from format_converter import convert_file_direct
        i18n = I18nManager(AppConfig.load().ui_language)
        try:
            print(f"[{APP_NAME}] {args.file} -> {args.convert_fmt.upper()}...")
            out = convert_file_direct(args.file, args.convert_fmt, output_path=args.output_path)
            print(i18n.t("cli_converted_saved", path=out))
            sys.exit(0)
        except Exception as e:
            print(i18n.t("cli_conversion_failed", error=e))
            sys.exit(1)

    if args.cli or args.file:
        if not args.file:
            i18n = I18nManager(AppConfig.load().ui_language)
            print(i18n.t("cli_err_file_not_found", path="--file"))
            parser.print_help()
            sys.exit(1)
        run_cli_translation(
            file_path=args.file,
            tgt_lang=args.tgt,
            src_lang=args.src,
            keep_it=args.keep_it,
            append_source=args.append_source,
            bilingual=args.bilingual,
            custom_context=args.context,
            model=args.model,
            provider=args.provider,
            output_path=args.output_path,
        )
    else:
        launch_gui()


if __name__ == "__main__":
    main()
