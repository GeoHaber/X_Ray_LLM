"""
Analysis/scan_cache.py — Incremental File-Level Parse Cache (v6.0.0)
=====================================================================

Avoids re-parsing unchanged Python files on repeated scans by persisting
per-file metadata (mtime, size, sha256 hash, last extracted results) in a
JSON sidecar at ``~/.cache/xray/scan_cache.json``.

Design
------
* **Key**: absolute file path (str).
* **Invalidation**: file is re-parsed when mtime OR size changes.
  If mtime is unreliable (e.g. on some network shares), a full SHA-256
  content hash comparison is used as a fallback.
* **Thread safety**: cache reads happen before the ThreadPoolExecutor
  is created; writes happen in the finally block after all futures
  complete — no concurrent writes to the same slot.

Usage
-----
    from Analysis.scan_cache import ScanCache

    cache = ScanCache()
    # ...
    cached = cache.get(path)   # None if miss/stale
    if cached is None:
        result = expensive_parse(path)
        cache.put(path, result)
    cache.save()
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional


# Where the cache file lives.  Overridable for tests via XRAY_CACHE_DIR env var.
_DEFAULT_CACHE_DIR = Path.home() / ".cache" / "xray"
_CACHE_FILE_NAME = "scan_cache.json"
_CACHE_VERSION = 1


def _file_stat(path: Path) -> Dict[str, Any]:
    """Return a dict with mtime and size for *path*.  Returns {} on failure."""
    try:
        st = path.stat()
        return {"mtime": st.st_mtime, "size": st.st_size}
    except OSError:
        return {}


def _file_hash(path: Path) -> str:
    """SHA-256 of file content, '' on failure."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


class ScanCache:
    """
    File-level parse cache backed by a JSON file on disk.

    Typical lifecycle::

        cache = ScanCache()               # loads from disk
        hit = cache.get(path)             # None → miss / stale
        if hit is None:
            result = parse(path)
            cache.put(path, result)
        cache.save()                      # flush to disk
    """

    def __init__(self, cache_dir: Optional[Path] = None, *, enabled: bool = True):
        env_dir = os.environ.get("XRAY_CACHE_DIR")
        self._dir = Path(env_dir) if env_dir else (cache_dir or _DEFAULT_CACHE_DIR)
        self._path = self._dir / _CACHE_FILE_NAME
        self._enabled = enabled
        self._lock = threading.Lock()
        self._dirty = False
        self._data: Dict[str, Any] = {}
        if enabled:
            self._load()

    # ── public API ────────────────────────────────────────────────────────────

    def get(self, path: Path) -> Optional[Dict[str, Any]]:
        """Return cached parse result for *path*, or None on cache miss / stale entry."""
        if not self._enabled:
            return None
        key = str(path.resolve())
        stat = _file_stat(path)
        if not stat:
            return None
        with self._lock:
            entry = self._data.get(key)
        if entry is None:
            return None
        # Fast check: mtime + size unchanged → hit
        if entry.get("mtime") == stat["mtime"] and entry.get("size") == stat["size"]:
            return entry.get("result")
        # Slow fallback: content hash (mtime can lie on some filesystems)
        content_hash = _file_hash(path)
        if content_hash and content_hash == entry.get("hash"):
            # Update mtime/size so next hit is fast
            with self._lock:
                entry["mtime"] = stat["mtime"]
                entry["size"] = stat["size"]
                self._dirty = True
            return entry.get("result")
        return None  # stale

    def put(self, path: Path, result: Any) -> None:
        """Store a parse result for *path*."""
        if not self._enabled:
            return
        key = str(path.resolve())
        stat = _file_stat(path)
        with self._lock:
            self._data[key] = {
                "mtime": stat.get("mtime"),
                "size": stat.get("size"),
                "hash": _file_hash(path),
                "result": result,
                "version": _CACHE_VERSION,
            }
            self._dirty = True

    def invalidate(self, path: Path) -> None:
        """Force a cache miss for *path* on next access."""
        key = str(path.resolve())
        with self._lock:
            self._data.pop(key, None)
            self._dirty = True

    def save(self) -> None:
        """Flush in-memory cache to disk if dirty."""
        if not self._enabled or not self._dirty:
            return
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            with self._lock:
                payload = dict(self._data)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            tmp.replace(self._path)
            self._dirty = False
        except Exception:
            pass  # cache is a best-effort optimisation — never crash on failure

    def clear(self) -> None:
        """Wipe all cached entries."""
        with self._lock:
            self._data.clear()
            self._dirty = True

    @property
    def size(self) -> int:
        """Number of entries in the in-memory cache."""
        return len(self._data)

    # ── internals ─────────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Load cache from disk, silently ignoring any errors."""
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            # Evict entries from a different schema version
            self._data = {
                k: v
                for k, v in raw.items()
                if isinstance(v, dict) and v.get("version") == _CACHE_VERSION
            }
        except Exception:
            self._data = {}


# Module-level singleton — shared across imports in the same process.
_cache_ref: list = [
    None
]  # [Optional[ScanCache]] — mutable container avoids global keyword
_init_lock = threading.Lock()


def get_cache(*, enabled: bool = True) -> ScanCache:
    """Return (or create) the process-wide ScanCache singleton."""
    with _init_lock:
        if _cache_ref[0] is None:
            _cache_ref[0] = ScanCache(enabled=enabled)
    return _cache_ref[0]


def reset_cache() -> None:
    """Reset the global singleton (used in tests)."""
    with _init_lock:
        _cache_ref[0] = None
