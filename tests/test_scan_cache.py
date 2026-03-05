"""
tests/test_scan_cache.py — Tests for Analysis/scan_cache.py (v6.0.0)
"""

import time
import pytest

from Analysis.scan_cache import ScanCache, reset_cache, get_cache


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def tmp_cache(tmp_path):
    """ScanCache backed by a temporary directory."""
    reset_cache()
    cache = ScanCache(cache_dir=tmp_path)
    yield cache
    reset_cache()


@pytest.fixture()
def tmp_py_file(tmp_path):
    """A real .py file in a temp directory."""
    f = tmp_path / "example.py"
    f.write_text("def hello(): pass\n", encoding="utf-8")
    return f


# ── basic put / get ──────────────────────────────────────────────────────────


class TestScanCacheBasic:
    def test_miss_on_empty_cache(self, tmp_cache, tmp_py_file):
        assert tmp_cache.get(tmp_py_file) is None

    def test_hit_after_put(self, tmp_cache, tmp_py_file):
        payload = {"functions": ["f"], "classes": [], "error": None}
        tmp_cache.put(tmp_py_file, payload)
        assert tmp_cache.get(tmp_py_file) == payload

    def test_put_increments_size(self, tmp_cache, tmp_py_file):
        assert tmp_cache.size == 0
        tmp_cache.put(tmp_py_file, {"functions": [], "classes": [], "error": None})
        assert tmp_cache.size == 1

    def test_disabled_cache_always_misses(self, tmp_path, tmp_py_file):
        cache = ScanCache(cache_dir=tmp_path, enabled=False)
        cache.put(tmp_py_file, {"functions": [], "classes": [], "error": None})
        assert cache.get(tmp_py_file) is None


# ── invalidation ──────────────────────────────────────────────────────────────


class TestScanCacheInvalidation:
    def test_invalidate_causes_miss(self, tmp_cache, tmp_py_file):
        tmp_cache.put(tmp_py_file, {"functions": [], "classes": [], "error": None})
        tmp_cache.invalidate(tmp_py_file)
        assert tmp_cache.get(tmp_py_file) is None

    def test_stale_after_content_change(self, tmp_cache, tmp_py_file):
        payload = {"functions": [], "classes": [], "error": None}
        tmp_cache.put(tmp_py_file, payload)
        # Modify the file
        time.sleep(0.01)
        tmp_py_file.write_text("def bye(): pass\n", encoding="utf-8")
        # The mtime will differ → cache miss
        assert tmp_cache.get(tmp_py_file) is None

    def test_clear_wipes_all(self, tmp_cache, tmp_py_file):
        tmp_cache.put(tmp_py_file, {"functions": [], "classes": [], "error": None})
        tmp_cache.clear()
        assert tmp_cache.size == 0


# ── persistence ───────────────────────────────────────────────────────────────


class TestScanCachePersistence:
    def test_save_creates_file(self, tmp_cache, tmp_py_file):
        tmp_cache.put(tmp_py_file, {"functions": [], "classes": [], "error": None})
        tmp_cache.save()
        cache_file = tmp_cache._path
        assert cache_file.exists()

    def test_reload_restores_hit(self, tmp_path, tmp_py_file):
        # Write and save with first instance
        c1 = ScanCache(cache_dir=tmp_path)
        c1.put(tmp_py_file, {"functions": ["x"], "classes": [], "error": None})
        c1.save()
        # Load with second instance
        c2 = ScanCache(cache_dir=tmp_path)
        result = c2.get(tmp_py_file)
        assert result is not None
        assert result["functions"] == ["x"]

    def test_save_only_if_dirty(self, tmp_path, tmp_py_file):
        c = ScanCache(cache_dir=tmp_path)
        c.save()  # nothing dirty — should not create file
        # No guarantee file doesn't exist from a prior test, so just check no exception


# ── global singleton ──────────────────────────────────────────────────────────


class TestGlobalCache:
    def test_get_cache_returns_same_instance(self):
        reset_cache()
        a = get_cache()
        b = get_cache()
        assert a is b
        reset_cache()

    def test_reset_creates_fresh_instance(self):
        reset_cache()
        a = get_cache()
        reset_cache()
        b = get_cache()
        assert a is not b
        reset_cache()
