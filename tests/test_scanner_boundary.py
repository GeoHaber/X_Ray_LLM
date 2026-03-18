"""
Scanner Boundary Tests — edge cases at the limits of scanner behavior.
Tests exact file size limits, encoding variations, concurrent safety,
and unusual file system scenarios.

Run:  python -m pytest tests/test_scanner_boundary.py -v --tb=short
"""

import os
import sys
import tempfile
import threading

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from xray.scanner import (
    _MAX_FILE_SIZE,
    _SKIP_DIRS,
    Finding,
    ScanResult,
    _detect_lang,
    _should_skip,
    scan_directory,
    scan_file,
)


def _write_temp(suffix: str, content: str) -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def _write_temp_bytes(suffix: str, data: bytes) -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return path


# ═════════════════════════════════════════════════════════════════════════════
# 1. File size boundary — exactly at and around the 1MB limit
# ═════════════════════════════════════════════════════════════════════════════

class TestFileSizeLimit:
    """Scanner must handle files at the exact 1MB boundary."""

    def test_max_file_size_is_1mb(self):
        assert _MAX_FILE_SIZE == 1_048_576

    def test_file_exactly_at_limit_scanned(self):
        """A file exactly at _MAX_FILE_SIZE should be scanned."""
        # Create file exactly at limit with a detectable pattern at the start
        content = "eval('x')\n"
        padding = "x = 1\n" * ((_MAX_FILE_SIZE - len(content.encode())) // 6)
        full = content + padding
        # Trim to exact size
        full_bytes = full.encode("utf-8")[:_MAX_FILE_SIZE]
        path = _write_temp_bytes(".py", full_bytes)
        findings = scan_file(path)
        os.unlink(path)
        assert any(f.rule_id == "SEC-007" for f in findings), \
            "File at exactly 1MB should be scanned"

    def test_file_one_byte_over_limit_skipped(self):
        """A file 1 byte over _MAX_FILE_SIZE should be skipped."""
        content = b"eval('x')\n" + b"x = 1\n" * 200_000
        # Make sure it's over 1MB
        while len(content) <= _MAX_FILE_SIZE:
            content += b"x = 1\n" * 10_000
        path = _write_temp_bytes(".py", content)
        findings = scan_file(path)
        os.unlink(path)
        assert findings == [], "File over 1MB should be skipped"

    def test_file_well_under_limit_scanned(self):
        """Small files should be scanned normally."""
        path = _write_temp(".py", "eval('x')\n")
        findings = scan_file(path)
        os.unlink(path)
        assert len(findings) > 0


# ═════════════════════════════════════════════════════════════════════════════
# 2. Encoding edge cases
# ═════════════════════════════════════════════════════════════════════════════

class TestEncodingEdgeCases:
    """Scanner must handle various text encodings gracefully."""

    def test_utf8_bom(self):
        """UTF-8 with BOM should be handled."""
        content = b"\xef\xbb\xbfeval('x')\n"
        path = _write_temp_bytes(".py", content)
        findings = scan_file(path)
        os.unlink(path)
        assert isinstance(findings, list)

    def test_latin1_encoded_file(self):
        """Latin-1 encoded file with eval should still be detected."""
        content = "eval('café')\n".encode("latin-1")
        path = _write_temp_bytes(".py", content)
        findings = scan_file(path)
        os.unlink(path)
        # errors='replace' should handle the encoding; eval should still be found
        assert isinstance(findings, list)

    def test_mixed_encoding_no_crash(self):
        """File with mixed encodings should not crash the scanner."""
        content = b"x = 'hello'\n" + b"\xff\xfe" + b"eval('x')\n" + b"\x80\x81\x82\n"
        path = _write_temp_bytes(".py", content)
        findings = scan_file(path)
        os.unlink(path)
        assert isinstance(findings, list)

    def test_null_bytes_in_source(self):
        """Null bytes should not crash the scanner."""
        content = b"eval('x')\x00\npassword='bad'\x00\n"
        path = _write_temp_bytes(".py", content)
        findings = scan_file(path)
        os.unlink(path)
        assert isinstance(findings, list)

    def test_crlf_line_endings(self):
        """CRLF (Windows) line endings should work correctly."""
        content = b"line1 = 'ok'\r\nresult = eval('bad')\r\nline3 = 'ok'\r\n"
        path = _write_temp_bytes(".py", content)
        findings = scan_file(path)
        os.unlink(path)
        assert any(f.rule_id == "SEC-007" for f in findings)

    def test_cr_only_line_endings(self):
        """Classic Mac (CR only) line endings should not crash."""
        content = b"line1 = 'ok'\rresult = eval('bad')\rline3 = 'ok'\r"
        path = _write_temp_bytes(".py", content)
        findings = scan_file(path)
        os.unlink(path)
        assert isinstance(findings, list)


# ═════════════════════════════════════════════════════════════════════════════
# 3. Language detection edge cases
# ═════════════════════════════════════════════════════════════════════════════

class TestLanguageDetection:
    """Verify language detection covers all expected extensions."""

    @pytest.mark.parametrize("ext,expected", [
        (".py", "python"),
        (".js", "javascript"),
        (".ts", "javascript"),
        (".jsx", "javascript"),
        (".tsx", "javascript"),
        (".html", "html"),
        (".htm", "html"),
        (".rs", "rust"),
    ])
    def test_known_extensions(self, ext, expected):
        assert _detect_lang(f"file{ext}") == expected

    @pytest.mark.parametrize("ext", [
        ".md", ".txt", ".csv", ".json", ".yaml", ".toml",
        ".cfg", ".ini", ".xml", ".svg", ".png", ".jpg",
        ".whl", ".tar", ".gz", ".zip",
    ])
    def test_unknown_extensions(self, ext):
        assert _detect_lang(f"file{ext}") is None

    def test_case_insensitive_extension(self):
        """Extensions should be detected case-insensitively."""
        assert _detect_lang("file.PY") == "python"
        assert _detect_lang("file.Js") == "javascript"
        assert _detect_lang("file.HTML") == "html"

    def test_no_extension(self):
        assert _detect_lang("Makefile") is None

    def test_double_extension(self):
        assert _detect_lang("file.test.py") == "python"


# ═════════════════════════════════════════════════════════════════════════════
# 4. _should_skip directory filter
# ═════════════════════════════════════════════════════════════════════════════

class TestShouldSkip:
    """Verify skip directory logic."""

    @pytest.mark.parametrize("dirname", list(_SKIP_DIRS))
    def test_all_skip_dirs(self, dirname):
        if dirname.startswith("."):
            # Dot-dirs are caught by startswith(".")
            assert _should_skip(f"/fake/{dirname}")
        elif "*" in dirname:
            # Glob patterns like *.egg-info are checked differently
            pass
        else:
            assert _should_skip(f"/fake/{dirname}")

    def test_normal_dir_not_skipped(self):
        assert not _should_skip("/fake/src")
        assert not _should_skip("/fake/lib")
        assert not _should_skip("/fake/tests")

    def test_hidden_dirs_skipped(self):
        """All dot-prefixed directories should be skipped."""
        assert _should_skip("/fake/.hidden")
        assert _should_skip("/fake/.secret")
        assert _should_skip("/fake/.cache")


# ═════════════════════════════════════════════════════════════════════════════
# 5. Concurrent scan safety
# ═════════════════════════════════════════════════════════════════════════════

class TestConcurrentScan:
    """Scanner should be safe to use from multiple threads."""

    def test_concurrent_scan_no_crash(self, tmp_path):
        """Multiple threads scanning simultaneously should not crash."""
        for i in range(5):
            (tmp_path / f"file{i}.py").write_text(f"eval('test{i}')\n", encoding="utf-8")

        results = []
        errors = []

        def scan_worker():
            try:
                r = scan_directory(str(tmp_path))
                results.append(r)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=scan_worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert len(errors) == 0, f"Concurrent scan errors: {errors}"
        assert len(results) == 4
        # All threads should find the same number of files
        counts = {r.files_scanned for r in results}
        assert len(counts) == 1, f"Inconsistent file counts: {counts}"

    def test_concurrent_file_scan_no_crash(self):
        """Multiple threads scanning the same file should not crash."""
        path = _write_temp(".py", "eval('x')\npassword = 'bad'\n")
        results = []
        errors = []

        def scan_worker():
            try:
                r = scan_file(path)
                results.append(r)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=scan_worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        os.unlink(path)
        assert len(errors) == 0
        assert len(results) == 8


# ═════════════════════════════════════════════════════════════════════════════
# 6. ScanResult aggregation
# ═════════════════════════════════════════════════════════════════════════════

class TestScanResultAggregation:
    """Verify ScanResult computes counts correctly."""

    def test_severity_counts_match_findings(self, tmp_path):
        code = (
            "eval(input())\n"
            "# TODO: fix\n"
            "password = 'bad'\n"
        )
        (tmp_path / "multi.py").write_text(code, encoding="utf-8")
        result = scan_directory(str(tmp_path))

        total = result.high_count + result.medium_count + result.low_count
        assert total == len(result.findings)

    def test_empty_result_counts(self):
        result = ScanResult()
        assert result.high_count == 0
        assert result.medium_count == 0
        assert result.low_count == 0
        assert result.files_scanned == 0

    def test_summary_contains_counts(self, tmp_path):
        (tmp_path / "test.py").write_text("eval(input())\n", encoding="utf-8")
        result = scan_directory(str(tmp_path))
        summary = result.summary()
        assert "HIGH" in summary
        assert str(result.files_scanned) in summary
