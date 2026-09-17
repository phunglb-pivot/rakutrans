# RakuTrans AI

[English](README.md) | [日本語](README.ja.md) | [Tiếng Việt](README.vi.md)

Desktop & CLI tool for AI-powered translation and 2-way format conversion between **Excel (`.xlsx`)** and **Markdown (`.md`)**. Specially optimized for Japanese, English, and Vietnamese.

---

## Key Features

- **Smart Multilingual Translation**: Auto-detects mixed source languages; only the target language needs to be selected.
  - **Excel**: Preserves 100% of formulas (`=SUM(...)`, `=IF(...)`), cell formatting, styles, and sheet structure. Optional bilingual mode (`_Orig` sheets).
  - **Markdown**: Preserves headers, code blocks (```` ``` ````), inline code, links, and tables.
- **Translation Memory (Local Cache)**: Embedded SQLite (`~/.rakutrans/cache.db`) saves repeated segments, reducing API cost and latency.
- **Offline Format Conversion (No API Key)**: Direct 2-way conversion between Excel (`.xlsx`) and Markdown (`.md`).
- **Multi-Provider AI**: Google Gemini, OpenAI, and Anthropic Claude with dynamic live model discovery.
- **Modern Desktop UI**: CustomTkinter interface with Dark/Light modes, i18n (EN, JA, VI), drag-and-drop, pre-scan file inspection, and keyboard shortcuts (`⌘/Ctrl+O`, `⌘/Ctrl+Enter`, `Esc`, `⌘/Ctrl+,`).

---

## Tech Stack

- **Core**: Python 3.10+
- **GUI**: CustomTkinter, TkinterDnD2
- **Document Processing**: OpenPyXL (Excel), MarkItDown & Python-Markdown (Markdown)
- **AI Providers**: Google GenAI (`google-genai`), OpenAI (`openai`), Anthropic Claude (`anthropic`)
- **Storage & Caching**: SQLite3 (Translation Memory), JSON (Configs & Models Cache)
- **Packaging**: PyInstaller

---

## Quickstart

### Installation

```bash
git clone https://github.com/phunglb-pivot/rakutrans.git
cd rakutrans
pip install -r requirements.txt
```

### Run GUI

```bash
./run.sh
# or: python3 main.py
```

### Run CLI

```bash
# Translate Excel to Vietnamese
python3 main.py --cli --file document.xlsx --tgt Vietnamese

# Translate & convert Excel to Markdown
python3 main.py --cli --file document.xlsx --tgt Vietnamese --output-format md
```

#### CLI Options

| Option | Short | Default | Description |
| :--- | :--- | :--- | :--- |
| `--cli` | | `False` | Run in headless CLI mode |
| `--file` | `-f` | *None* | Path to `.xlsx` or `.md` file (required in CLI) |
| `--tgt` | `-t` | `Vietnamese` | Target language (`Vietnamese`, `English`, `Japanese`, etc.) |
| `--src` | `-s` | `None` | Source language filter (default: auto-detect) |
| `--keep-terms` | `--keep-it` | `True` | Keep IT/domain terms untranslated |
| `--append-source` | | `False` | Append original words in parentheses |
| `--context` | `-c` | `""` | Custom glossary or context prompt |
| `--model` | `-m` | *Configured* | AI model name (e.g. `gemini-3.6-flash`, `gpt-4o-mini`) |
| `--provider` | `-p` | *Configured* | Provider (`Gemini`, `OpenAI`, `Claude`) |
| `--output-format` | `-out-fmt` | `auto` | Target output format (`auto`, `xlsx`, `md`) |

---

## Packaging

Build standalone executables (no Python installation required):

- **macOS (`.app` & `.dmg`)**: `./build_macos.sh`
- **Windows (`.exe`)**: `build_windows.bat`

---

## License

MIT License
