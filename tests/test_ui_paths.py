"""
Tests for UI path safety — ensures no OS-specific characters break the UI.

Covers:
  1. Backend _fwd() normalizes backslashes
  2. browse_directory() returns forward-slash paths
  3. get_drives() returns forward-slash paths
  4. Simulated JS esc() handles all dangerous characters
  5. Paths with spaces, unicode, special chars survive round-trip
  6. Real filesystem paths on current OS
"""

import json
import os
import platform
import re
import sys
import tempfile
from pathlib import Path

import pytest

# Import from our codebase
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from ui_server import _fwd, browse_directory, get_drives


# ══════════════════════════════════════════════════════════════════════════
# 1. _fwd() — backslash normalization
# ══════════════════════════════════════════════════════════════════════════

class TestFwd:
    """Test the _fwd path normalizer."""

    def test_windows_path(self):
        assert _fwd(r"C:\Users\dvdze\Documents") == "C:/Users/dvdze/Documents"

    def test_unix_path_unchanged(self):
        assert _fwd("/home/user/projects") == "/home/user/projects"

    def test_mixed_slashes(self):
        assert _fwd(r"C:\Users/files\test") == "C:/Users/files/test"

    def test_unc_path(self):
        assert _fwd(r"\\server\share\folder") == "//server/share/folder"

    def test_empty_string(self):
        assert _fwd("") == ""

    def test_single_backslash(self):
        assert _fwd("\\") == "/"

    def test_trailing_backslash(self):
        assert _fwd("C:\\Users\\") == "C:/Users/"

    def test_no_backslash(self):
        assert _fwd("simple/path") == "simple/path"


# ══════════════════════════════════════════════════════════════════════════
# 2. browse_directory() — real filesystem
# ══════════════════════════════════════════════════════════════════════════

class TestBrowseDirectory:
    """Test directory browsing returns safe paths."""

    def test_browse_returns_forward_slashes(self, tmp_path):
        """All paths in browse result must use forward slashes only."""
        subdir = tmp_path / "test_dir"
        subdir.mkdir()
        (tmp_path / "file.txt").write_text("hello")

        result = browse_directory(str(tmp_path))
        assert "error" not in result

        # Check current path
        assert "\\" not in result["current"], f"Backslash in current: {result['current']}"

        # Check parent path
        if result["parent"]:
            assert "\\" not in result["parent"], f"Backslash in parent: {result['parent']}"

        # Check all item paths
        for item in result["items"]:
            assert "\\" not in item["path"], f"Backslash in item path: {item['path']}"

    def test_browse_nonexistent(self):
        result = browse_directory("/this/does/not/exist/ever")
        assert "error" in result

    def test_browse_has_parent(self, tmp_path):
        result = browse_directory(str(tmp_path))
        assert result["parent"] is not None

    def test_browse_items_structure(self, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "file.py").write_text("x=1")

        result = browse_directory(str(tmp_path))
        names = [item["name"] for item in result["items"]]
        assert "sub" in names
        assert "file.py" in names

        for item in result["items"]:
            assert "name" in item
            assert "path" in item
            assert "is_dir" in item

    def test_browse_skips_dotfiles(self, tmp_path):
        (tmp_path / ".hidden").mkdir()
        (tmp_path / ".secret_file").write_text("x")
        (tmp_path / "visible").mkdir()

        result = browse_directory(str(tmp_path))
        names = [item["name"] for item in result["items"]]
        assert ".hidden" not in names
        assert ".secret_file" not in names
        assert "visible" in names

    def test_browse_keeps_dotenv(self, tmp_path):
        (tmp_path / ".env").write_text("KEY=val")

        result = browse_directory(str(tmp_path))
        names = [item["name"] for item in result["items"]]
        assert ".env" in names

    @pytest.mark.skipif(platform.system() != "Windows", reason="Windows-specific")
    def test_browse_windows_root(self):
        """C:/ must work and return forward-slash paths."""
        result = browse_directory("C:/")
        assert "error" not in result
        assert "\\" not in result["current"]


# ══════════════════════════════════════════════════════════════════════════
# 3. get_drives() — safe drive paths
# ══════════════════════════════════════════════════════════════════════════

class TestGetDrives:
    """Test drive listing returns safe paths."""

    def test_drives_have_forward_slashes(self):
        drives = get_drives()
        assert len(drives) > 0
        for d in drives:
            assert "\\" not in d["path"], f"Backslash in drive path: {d['path']}"
            assert d["is_dir"] is True

    @pytest.mark.skipif(platform.system() != "Windows", reason="Windows-specific")
    def test_windows_c_drive_present(self):
        drives = get_drives()
        paths = [d["path"] for d in drives]
        assert "C:/" in paths

    @pytest.mark.skipif(platform.system() == "Windows", reason="Unix-specific")
    def test_unix_root_present(self):
        drives = get_drives()
        assert drives == [{"name": "/", "path": "/", "is_dir": True}]


# ══════════════════════════════════════════════════════════════════════════
# 4. JS esc() simulation — dangerous characters in inline handlers
# ══════════════════════════════════════════════════════════════════════════

def js_esc(s: str) -> str:
    """Python simulation of the JS esc() function from ui.html.

    The JS version does:
      1. Create a text node (escapes HTML: < > & etc.)
      2. .replace(/'/g, '&#39;')
      3. .replace(/"/g, '&quot;')

    This function replicates that behavior identically.
    """
    # Step 1: HTML entity encoding (what textContent → innerHTML does)
    s = s.replace("&", "&amp;")
    s = s.replace("<", "&lt;")
    s = s.replace(">", "&gt;")
    # Step 2-3: quote escaping
    s = s.replace("'", "&#39;")
    s = s.replace('"', "&quot;")
    return s


class TestJsEsc:
    """Test that the JS esc() function handles all dangerous characters."""

    def test_html_entities(self):
        assert "&lt;" in js_esc("<script>")
        assert "&gt;" in js_esc("</script>")
        assert "&amp;" in js_esc("a & b")

    def test_single_quotes(self):
        """Single quotes would break onclick='...' handlers."""
        result = js_esc("it's a path")
        assert "'" not in result
        assert "&#39;" in result

    def test_double_quotes(self):
        result = js_esc('say "hello"')
        assert '"' not in result.replace("&quot;", "")

    def test_backslash_passes_through(self):
        """Backslash is NOT escaped by esc() — must be handled by backend _fwd()."""
        result = js_esc(r"C:\Users\test")
        # This proves backslash goes through raw — backend MUST normalize first
        assert "\\" in result

    def test_forward_slash_safe(self):
        """Forward slashes are safe in all contexts."""
        result = js_esc("C:/Users/test")
        assert result == "C:/Users/test"


# ══════════════════════════════════════════════════════════════════════════
# 5. Dangerous path characters — complete inventory
# ══════════════════════════════════════════════════════════════════════════

class TestDangerousChars:
    """
    Test every character class that could break inline JS handlers.

    Inline handler: onclick="browse('PATH_HERE')"
    Danger zones:
      - Backslash → JS escape sequences (\n, \t, \0, etc.)
      - Single quote → breaks out of string literal
      - Double quote → breaks out of attribute
      - Backtick → breaks if used in template literal
      - Newline/CR → breaks string literal
      - < > → HTML injection
      - & → HTML entity confusion
      - Null byte → string truncation
    """

    # Characters that are dangerous in inline onclick="fn('HERE')"
    DANGEROUS_IN_JS_STRING = {
        "\\": "backslash — JS escape",
        "'": "single quote — breaks string",
        '"': "double quote — breaks attribute",
        "\n": "newline — breaks JS string",
        "\r": "carriage return — breaks JS string",
        "\t": "tab — may break display",
        "\0": "null byte — truncates string",
        "`": "backtick — template literal",
    }

    DANGEROUS_IN_HTML = {
        "<": "less than — HTML tag injection",
        ">": "greater than — HTML tag injection",
        "&": "ampersand — HTML entity confusion",
    }

    def test_backend_removes_backslashes(self):
        """_fwd() must eliminate all backslashes from paths."""
        paths = [
            r"C:\Users\test",
            r"C:\new\test",         # \n and \t sequences!
            r"C:\0data\readme",     # \0 sequence!
            r"C:\return\file",      # \r sequence!
            r"\\network\share",     # UNC path
        ]
        for p in paths:
            result = _fwd(p)
            assert "\\" not in result, f"Backslash survived in: {p!r} → {result!r}"

    def test_esc_handles_html_injection(self):
        """HTML chars must be escaped."""
        for char, desc in self.DANGEROUS_IN_HTML.items():
            result = js_esc(f"path{char}test")
            assert char not in result or char in ("&",), f"{desc}: {char!r} not escaped"
            # & appears in entity form &amp; — that's fine
            if char == "&":
                assert "&amp;" in result

    def test_esc_handles_quotes(self):
        """Quotes must be escaped."""
        assert "'" not in js_esc("it's")
        assert '"' not in js_esc('say "hi"').replace("&quot;", "")

    def test_combined_attack_string(self):
        """Test a path containing EVERY dangerous character."""
        attack = """C:/Users/O'Brien/<script>&"hello`"""
        result = js_esc(attack)
        # None of the raw dangerous chars should remain
        assert "<" not in result
        assert ">" not in result
        assert "'" not in result
        assert '"' not in result.replace("&quot;", "")

    def test_newline_in_path_detected(self):
        """If a path somehow contains a newline, esc() does NOT fix it.

        This test documents the limitation — newlines in filenames are rare
        but possible on Linux. The backend should strip them.
        """
        path_with_newline = "path\nwith\nnewlines"
        result = js_esc(path_with_newline)
        # esc() doesn't handle newlines — they pass through!
        # This means the backend is the only defense.
        # On real filesystems, _fwd() doesn't fix this either.
        # Document this as a known limitation.
        assert "\n" in result  # Known: esc() doesn't strip newlines


# ══════════════════════════════════════════════════════════════════════════
# 6. Round-trip: real path → _fwd() → esc() → safe for inline JS
# ══════════════════════════════════════════════════════════════════════════

class TestRoundTrip:
    """Test that real filesystem paths survive the full pipeline."""

    def test_home_directory(self):
        home = str(Path.home())
        safe = js_esc(_fwd(home))
        assert "\\" not in safe
        assert "'" not in safe

    def test_temp_directory(self):
        tmp = tempfile.gettempdir()
        safe = js_esc(_fwd(tmp))
        assert "\\" not in safe

    def test_path_with_spaces(self, tmp_path):
        spaced = tmp_path / "my project" / "sub dir"
        spaced.mkdir(parents=True)
        safe = js_esc(_fwd(str(spaced)))
        assert "\\" not in safe
        assert "my project" in safe

    @pytest.mark.skipif(platform.system() == "Windows", reason="Linux/macOS only")
    def test_path_with_single_quote_unix(self, tmp_path):
        """On Unix, filenames can contain single quotes."""
        quoted = tmp_path / "it's a test"
        quoted.mkdir()
        safe = js_esc(_fwd(str(quoted)))
        assert "'" not in safe
        assert "&#39;" in safe

    def test_browse_result_paths_survive_esc(self, tmp_path):
        """Every path from browse_directory must be safe after esc()."""
        (tmp_path / "sub").mkdir()
        (tmp_path / "file.py").write_text("x")

        result = browse_directory(str(tmp_path))
        assert "error" not in result

        # All paths through the pipeline
        paths_to_check = [result["current"]]
        if result["parent"]:
            paths_to_check.append(result["parent"])
        for item in result["items"]:
            paths_to_check.append(item["path"])

        for p in paths_to_check:
            safe = js_esc(p)
            assert "\\" not in safe, f"Backslash in: {p}"
            assert "'" not in safe, f"Raw single-quote in: {p}"
            # Verify no JS escape sequences would be created
            assert "\n" not in safe, f"Newline in: {p}"
            assert "\r" not in safe, f"Carriage return in: {p}"
            assert "\0" not in safe, f"Null byte in: {p}"


# ══════════════════════════════════════════════════════════════════════════
# 7. Scan API path handling
# ══════════════════════════════════════════════════════════════════════════

class TestScanPaths:
    """Test that scan API accepts forward-slash paths."""

    def test_python_scan_accepts_forward_slash(self, tmp_path):
        """Python scanner must accept forward-slash paths on all OSes."""
        (tmp_path / "test.py").write_text("x = eval(input())")
        from xray.scanner import scan_directory
        fwd_path = _fwd(str(tmp_path))
        result = scan_directory(fwd_path)
        assert result.files_scanned == 1
        assert len(result.findings) > 0

    def test_resolved_path_normalized(self):
        """Path.resolve() on Windows returns backslashes — _fwd must fix."""
        p = Path(".").resolve()
        safe = _fwd(str(p))
        assert "\\" not in safe
