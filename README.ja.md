# RakuTrans AI

[English](README.md) | [日本語](README.ja.md) | [Tiếng Việt](README.vi.md)

**Excel (`.xlsx`)** および **Markdown (`.md`)** ドキュメントのAI翻訳とフォーマット相互変換に対応したデスクトップ／CLIツール。日本語・英語・ベトナム語に最適化されています。

<p align="center">
  <img src="assets/ui.png" alt="RakuTrans AI" />
</p>

---

## 主な機能

- **言語自動検出によるAI翻訳**: 混在言語を自動処理し、翻訳先言語を指定するだけで翻訳可能。
  - **Excel**: 計算式（`=SUM(...)`, `=IF(...)`）、書式、罫線、スタイル、シート構造を100%保持。バイリンガルモード（`_Orig` シート併記）に対応。
  - **Markdown**: 見出し、コードブロック（```` ``` ````）、インラインコード、リンク、表構文を完全保護。
- **翻訳メモリ（ローカルキャッシュ）**: SQLite (`~/.rakutrans/cache.db`) により重複翻訳をスキップし、APIコスト削減と高速化を実現。
- **オフライン・フォーマット相互変換（APIキー不要）**: Excel (`.xlsx`) ⇄ Markdown (`.md`) の双方向直接変換。
- **マルチプロバイダー対応**: Google Gemini, OpenAI, Anthropic Claude（モデル動的取得対応）。
- **モダンなデスクトップGUI**: CustomTkinter（ダーク／ライト）、3言語対応（日英越）、ドラッグ＆ドロップ、事前検査バッジ、ショートカットキー（`⌘/Ctrl+O`, `⌘/Ctrl+Enter`, `Esc`, `⌘/Ctrl+,`）。

---

## 技術スタック (Tech Stack)

- **コア言語**: Python 3.10+
- **GUIフレームワーク**: CustomTkinter, TkinterDnD2
- **ドキュメント処理**: OpenPyXL（Excel）、MarkItDown & Python-Markdown（Markdown）
- **AIプロバイダー**: Google GenAI (`google-genai`), OpenAI (`openai`), Anthropic Claude (`anthropic`)
- **データ管理**: SQLite3（翻訳メモリ）、JSON（設定・モデルキャッシュ）
- **パッケージング**: PyInstaller

---

## クイックスタート

### インストール

```bash
git clone https://github.com/phunglb-pivot/rakutrans.git
cd rakutrans
pip install -r requirements.txt
```

### GUI起動

```bash
./run.sh
# または: python3 main.py
```

### CLI実行

```bash
# Excelファイルをベトナム語に翻訳
python3 main.py --cli --file document.xlsx --tgt Vietnamese

# Excelを翻訳しつつMarkdown形式で出力
python3 main.py --cli --file document.xlsx --tgt Vietnamese --output-format md
```

#### CLIオプション

| オプション | 短縮形 | デフォルト値 | 説明 |
| :--- | :--- | :--- | :--- |
| `--cli` | | `False` | CLIモードで実行 |
| `--file` | `-f` | *なし* | 入力ファイルパス（CLIでは必須） |
| `--tgt` | `-t` | `Vietnamese` | 翻訳先言語（`Vietnamese`, `English`, `Japanese` 等） |
| `--src` | `-s` | `None` | 原文言語フィルター（デフォルト: 自動検出） |
| `--keep-terms` | `--keep-it` | `True` | 専門用語・IT用語をそのまま保持 |
| `--append-source` | | `False` | 原文をかっこ書きで併記 |
| `--context` | `-c` | `""` | 用語集やカスタムコンテキスト |
| `--model` | `-m` | *設定値* | AIモデル名（例: `gemini-3.6-flash`, `gpt-4o-mini`） |
| `--provider` | `-p` | *設定値* | プロバイダー（`Gemini`, `OpenAI`, `Claude`） |
| `--output-format` | `-out-fmt` | `auto` | 出力形式（`auto`, `xlsx`, `md`） |

---

## パッケージング（単体アプリ化）

Python不要のスタンドアロン実行ファイルを作成:

- **macOS (`.app` & `.dmg`)**: `./build_macos.sh`
- **Windows (`.exe`)**: `build_windows.bat`

---

## ライセンス

MIT License
