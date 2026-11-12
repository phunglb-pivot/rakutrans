# RakuTrans AI

[English](README.md) | [日本語](README.ja.md) | [Tiếng Việt](README.vi.md)

AI-powered Desktop translation application supporting multiple formats: **PDF (`.pdf`)**, **Word (`.docx`)**, **Excel (`.xlsx`)**, **PowerPoint (`.pptx`)**, **CSV/TSV (`.csv`, `.tsv`)**, **JSON (`.json`)**, **Plain Text (`.txt`)**, and **Markdown (`.md`)**.

<p align="center">
  <img src="assets/ui.png" alt="RakuTrans AI" />
</p>

---

## Tech Stack

- **Core Language**: Python 3.10+
- **User Interface (GUI)**: CustomTkinter, TkinterDnD2
- **Document Processing**: PyMuPDF & pdf2docx (PDF), python-docx (Word), OpenPyXL (Excel), python-pptx (PowerPoint), MarkItDown (Markdown)
- **AI Providers**: Google GenAI (`google-genai`), OpenAI (`openai`), Anthropic Claude (`anthropic`)
- **Storage & Cache**: SQLite3 (Translation memory), JSON (Configuration & model cache)
- **Application Packaging**: PyInstaller

---

## Quick Start & Installation

The project includes zero-config self-healing scripts that automatically locate Python 3.10+, create/repair `.venv`, and install dependencies:

### Option 1: One-Click Run (Recommended)

- **macOS / Linux**:
  ```bash
  ./run.sh
  ```
- **Windows**: Double-click `run_windows.bat` or run:
  ```cmd
  run_windows.bat
  ```

*(The scripts automatically set up `.venv`, recover from broken/moved directory paths, and launch the application).*

### Option 2: Standalone Environment Setup

If you prefer to initialize the environment ahead of time:
- **macOS / Linux**: `./setup_env.sh`
- **Windows**: `setup_env.bat`

---

## Standalone Packaging

Build standalone executables without requiring end-users to have Python installed:

- **macOS (`.app` & `.dmg`)**: `./build_macos.sh`
- **Windows (`.exe`)**: `build_windows.bat`
