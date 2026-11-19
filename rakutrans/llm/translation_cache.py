"""
Translation Memory & Caching module for RakuTrans AI.
Uses a local SQLite database to persist translations, eliminating redundant
LLM API calls for duplicate terms and reducing API cost and latency by 40-70%.
"""

import hashlib
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import List, Tuple, Dict, Optional

from config import TranslationOptions, CONFIG_DIR, get_config_dir, normalize_language_name

CACHE_DB_PATH = CONFIG_DIR / "cache.db"
_INITIAL_CACHE_DB_PATH = CACHE_DB_PATH
PROMPT_VERSION = "v6"
_SQL_CHUNK_SIZE = 400
_SQLITE_CONNECT_TIMEOUT_S = 10.0
_SQLITE_BUSY_TIMEOUT_MS = 10000
_SQLITE_WRITE_MAX_RETRIES = 4
_SQLITE_RETRY_BASE_DELAY_S = 0.05


def _normalize_cache_langs(source_lang: Optional[str], target_lang: str) -> Tuple[str, str]:
    """Normalize source and target languages so CLI/GUI aliases share cache entries."""
    src_raw = (source_lang or "").strip()
    if not src_raw or src_raw.lower() == "auto":
        norm_src = "auto"
    else:
        norm_src = normalize_language_name(src_raw)

    tgt_raw = (target_lang or "").strip()
    norm_tgt = normalize_language_name(tgt_raw) if tgt_raw else tgt_raw
    return norm_src, norm_tgt


def compute_options_hash(
    options: Optional[TranslationOptions],
    mode: str = "batch",
    model_id: str = "",
) -> str:
    """Compute deterministic hash of translation options, mode, and model affecting output."""
    opts = options or TranslationOptions()
    clean_mode = (mode or "batch").strip().lower()
    clean_model = (model_id or "").strip()
    raw = (
        f"{PROMPT_VERSION}|mode:{clean_mode}|model:{clean_model}"
        f"|it:{bool(opts.keep_it_terms)}|orig:{bool(opts.append_original_words)}"
        f"|ctx:{(opts.custom_context or '').strip()}"
    )
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]


class TranslationCache:
    """
    Thread-safe local translation cache backed by SQLite.
    """

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is not None:
            self.db_path = Path(db_path)
        elif CACHE_DB_PATH != _INITIAL_CACHE_DB_PATH:
            self.db_path = Path(CACHE_DB_PATH)
        else:
            self.db_path = get_config_dir() / "cache.db"
        self._write_lock = threading.RLock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if not self.db_path.parent.exists():
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=_SQLITE_CONNECT_TIMEOUT_S)
        conn.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS};")
        return conn

    @contextmanager
    def _connection(self):
        conn = self._get_connection()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _run_write(self, fn):
        """Serialize in-process writes and retry transient SQLite lock contention."""
        with self._write_lock:
            last_err: Optional[Exception] = None
            for attempt in range(_SQLITE_WRITE_MAX_RETRIES):
                try:
                    with self._connection() as conn:
                        return fn(conn)
                except sqlite3.OperationalError as e:
                    last_err = e
                    msg = str(e).lower()
                    if ("locked" in msg or "busy" in msg) and attempt < _SQLITE_WRITE_MAX_RETRIES - 1:
                        time.sleep(_SQLITE_RETRY_BASE_DELAY_S * (2 ** attempt))
                        continue
                    raise
            if last_err is not None:
                raise last_err

    def _init_db(self):
        def _init(conn: sqlite3.Connection):
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS translations (
                    source_lang TEXT,
                    target_lang TEXT,
                    source_text TEXT,
                    translated_text TEXT,
                    options_hash TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (source_lang, target_lang, source_text, options_hash)
                );
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_lookup
                ON translations (source_lang, target_lang, options_hash);
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_lookup_auto
                ON translations (target_lang, options_hash, source_text);
            """)

        self._run_write(_init)

    def get_batch(
        self,
        texts: List[str],
        target_lang: str,
        options: Optional[TranslationOptions] = None,
        source_lang: str = "auto",
        mode: str = "batch",
        model_id: str = "",
    ) -> Tuple[Dict[int, str], List[Tuple[int, str]]]:
        """
        Splits an input list of texts into cached items and uncached items.
        Returns:
          - cached_map: {original_index: translated_text}
          - uncached_list: [(original_index, source_text)]
        """
        if not texts:
            return {}, []

        norm_src, norm_tgt = _normalize_cache_langs(source_lang or "auto", target_lang)
        opt_hash = compute_options_hash(options, mode=mode, model_id=model_id)

        unique_queries = list(dict.fromkeys(texts))
        db_map: Dict[str, str] = {}

        with self._connection() as conn:
            for start in range(0, len(unique_queries), _SQL_CHUNK_SIZE):
                chunk = unique_queries[start:start + _SQL_CHUNK_SIZE]
                placeholders = ",".join("?" for _ in chunk)
                if norm_src == "auto":
                    cursor = conn.execute(
                        f"""
                        SELECT source_text, translated_text FROM translations
                        WHERE target_lang = ? AND options_hash = ? AND source_text IN ({placeholders})
                        ORDER BY (source_lang = 'auto') DESC, created_at DESC;
                        """,
                        [norm_tgt, opt_hash, *chunk],
                    )
                else:
                    cursor = conn.execute(
                        f"""
                        SELECT source_text, translated_text FROM translations
                        WHERE source_lang = ? AND target_lang = ? AND options_hash = ?
                          AND source_text IN ({placeholders});
                        """,
                        [norm_src, norm_tgt, opt_hash, *chunk],
                    )
                for src_text, trans_text in cursor:
                    db_map.setdefault(src_text, trans_text)

        cached_map: Dict[int, str] = {}
        uncached_list: List[Tuple[int, str]] = []
        for idx, text in enumerate(texts):
            if text in db_map:
                cached_map[idx] = db_map[text]
            else:
                uncached_list.append((idx, text))

        return cached_map, uncached_list

    def save_batch(
        self,
        source_texts: List[str],
        translated_texts: List[str],
        target_lang: str,
        options: Optional[TranslationOptions] = None,
        source_lang: str = "auto",
        mode: str = "batch",
        model_id: str = "",
    ):
        """Persist newly translated pairs into the cache."""
        if not source_texts or len(source_texts) != len(translated_texts):
            return

        norm_src, norm_tgt = _normalize_cache_langs(source_lang or "auto", target_lang)
        opt_hash = compute_options_hash(options, mode=mode, model_id=model_id)

        records = [
            (norm_src, norm_tgt, src, tr, opt_hash)
            for src, tr in zip(source_texts, translated_texts)
            if src is not None and tr is not None
        ]
        if not records:
            return

        self._run_write(
            lambda conn: conn.executemany(
                """
                INSERT OR REPLACE INTO translations
                (source_lang, target_lang, source_text, translated_text, options_hash)
                VALUES (?, ?, ?, ?, ?);
                """,
                records,
            )
        )

    def count(self) -> int:
        """Returns total cached translation pairs."""
        try:
            with self._connection() as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM translations;")
                return cursor.fetchone()[0]
        except Exception:
            return 0

    def clear(self):
        """Wipes the translation cache."""
        try:
            self._run_write(lambda conn: conn.execute("DELETE FROM translations;"))
        except Exception as e:
            print(f"[Warning] Failed to clear cache: {e}")
