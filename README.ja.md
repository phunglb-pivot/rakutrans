# RakuTrans AI

[English](README.md) | [日本語](README.ja.md) | [Tiếng Việt](README.vi.md)

多彩なファイル形式に対応したAIドキュメント翻訳デスクトップアプリ：**PDF (`.pdf`)**、**Word (`.docx`)**、**Excel (`.xlsx`)**、**PowerPoint (`.pptx`)**、**CSV/TSV (`.csv`, `.tsv`)**、**JSON (`.json`)**、**プレーンテキスト (`.txt`)**、**Markdown (`.md`)**。

<p align="center">
  <img src="assets/ui.png" alt="RakuTrans AI" />
</p>

---

## 使用技術

- **開発言語**: Python 3.10+
- **GUIフレームワーク**: CustomTkinter, TkinterDnD2
- **ドキュメント処理**: PyMuPDF & pdf2docx (PDF), python-docx (Word), OpenPyXL (Excel), python-pptx (PowerPoint), MarkItDown (Markdown)
- **AIプロバイダー**: Google GenAI (`google-genai`), OpenAI (`openai`), Anthropic Claude (`anthropic`)
- **ストレージ & キャッシュ**: SQLite3 (翻訳メモリ), JSON (設定 & モデルキャッシュ)
- **パッケージング**: PyInstaller

---

## インストール & クイックスタート

### インストール

```bash
git clone https://github.com/phunglb-pivot/rakutrans.git
cd rakutrans
pip install -r requirements.txt
```

### デスクトップアプリの起動

```bash
./run.sh
# または: python3 main.py
```

---

## スタンドアロンアプリのビルド

Pythonのインストールが不要な実行ファイルを生成します：

- **macOS (`.app` & `.dmg`)**: `./build_macos.sh`
- **Windows (`.exe`)**: `build_windows.bat`
