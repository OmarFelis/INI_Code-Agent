"""
Code-Agent — LLM Cache.
SQLite-backed cache for LLM responses to avoid re-processing identical code.
Cache key = SHA256(code + prompt_version).
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path

import structlog

logger = structlog.get_logger()

# Bump this when you change the LLM prompt structure.
# All cached responses with an older version will be ignored.
PROMPT_VERSION = "v2.1"

_DEFAULT_CACHE_DIR = ".cache/llm"
_DEFAULT_TTL_DAYS = 30


class LLMCache:
    """
    SQLite-backed cache for LLM responses.

    Usage::

        cache = LLMCache()
        cached = cache.get(prompt_text)
        if cached:
            return cached

        result = await bedrock_call(...)
        cache.put(prompt_text, result)
    """

    def __init__(
        self,
        cache_dir: str = _DEFAULT_CACHE_DIR,
        ttl_days: int = _DEFAULT_TTL_DAYS,
    ):
        self._ttl_seconds = ttl_days * 86400
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = str(self._cache_dir / "cache.db")
        self._init_db()

    # ── Public API ────────────────────────────────────────────────────

    def get(self, prompt: str, prompt_version: str = PROMPT_VERSION) -> dict | None:
        """
        Retrieve a cached LLM response.

        Returns None on cache miss or if the entry has expired.
        """
        key = self._make_key(prompt, prompt_version)
        now = time.time()

        try:
            conn = sqlite3.connect(self._db_path)
            cursor = conn.execute(
                "SELECT response_json, created_at FROM llm_cache WHERE cache_key = ?",
                (key,),
            )
            row = cursor.fetchone()
            conn.close()

            if row is None:
                return None

            response_json, created_at = row

            # Check TTL
            if (now - created_at) > self._ttl_seconds:
                self._delete(key)
                return None

            return json.loads(response_json)

        except Exception as e:
            logger.warning("llm_cache_get_error", error=str(e))
            return None

    def put(self, prompt: str, result: dict, prompt_version: str = PROMPT_VERSION) -> None:
        """Store an LLM response in cache."""
        # Don't cache error responses
        if "error" in result and len(result) <= 2:
            return

        key = self._make_key(prompt, prompt_version)
        now = time.time()

        try:
            conn = sqlite3.connect(self._db_path)
            conn.execute(
                """INSERT OR REPLACE INTO llm_cache (cache_key, prompt_version, response_json, created_at)
                   VALUES (?, ?, ?, ?)""",
                (key, prompt_version, json.dumps(result, ensure_ascii=False), now),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning("llm_cache_put_error", error=str(e))

    def stats(self) -> dict:
        """Return cache statistics."""
        try:
            conn = sqlite3.connect(self._db_path)
            cursor = conn.execute("SELECT COUNT(*) FROM llm_cache")
            total = cursor.fetchone()[0]

            cursor = conn.execute(
                "SELECT COUNT(*) FROM llm_cache WHERE created_at > ?",
                (time.time() - self._ttl_seconds,),
            )
            valid = cursor.fetchone()[0]
            conn.close()

            # File size
            db_size = os.path.getsize(self._db_path) if os.path.exists(self._db_path) else 0

            return {
                "total_entries": total,
                "valid_entries": valid,
                "expired_entries": total - valid,
                "db_size_mb": round(db_size / (1024 * 1024), 2),
                "prompt_version": PROMPT_VERSION,
            }
        except Exception as e:
            return {"error": str(e)}

    def clear(self) -> int:
        """Delete all cached entries. Returns number of deleted rows."""
        try:
            conn = sqlite3.connect(self._db_path)
            cursor = conn.execute("DELETE FROM llm_cache")
            deleted = cursor.rowcount
            conn.commit()
            conn.close()
            logger.info("llm_cache_cleared", deleted=deleted)
            return deleted
        except Exception as e:
            logger.warning("llm_cache_clear_error", error=str(e))
            return 0

    def cleanup_expired(self) -> int:
        """Remove expired entries. Returns number of deleted rows."""
        try:
            conn = sqlite3.connect(self._db_path)
            cursor = conn.execute(
                "DELETE FROM llm_cache WHERE created_at < ?",
                (time.time() - self._ttl_seconds,),
            )
            deleted = cursor.rowcount
            conn.commit()
            conn.close()
            if deleted:
                logger.info("llm_cache_cleanup", deleted=deleted)
            return deleted
        except Exception as e:
            logger.warning("llm_cache_cleanup_error", error=str(e))
            return 0

    # ── Private ───────────────────────────────────────────────────────

    @staticmethod
    def _make_key(prompt: str, prompt_version: str) -> str:
        """Generate a SHA256 cache key from prompt + version."""
        raw = f"{prompt_version}::{prompt}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _delete(self, key: str) -> None:
        try:
            conn = sqlite3.connect(self._db_path)
            conn.execute("DELETE FROM llm_cache WHERE cache_key = ?", (key,))
            conn.commit()
            conn.close()
        except Exception:
            pass

    def _init_db(self) -> None:
        """Create the cache table if it doesn't exist."""
        try:
            conn = sqlite3.connect(self._db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS llm_cache (
                    cache_key TEXT PRIMARY KEY,
                    prompt_version TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_llm_cache_created ON llm_cache(created_at)"
            )
            conn.commit()
            conn.close()
            logger.debug("llm_cache_initialized", db=self._db_path)
        except Exception as e:
            logger.warning("llm_cache_init_error", error=str(e))
