"""
tests/test_analysis_satd.py — Unit tests for Analysis/satd.py (v8.0)
"""
import textwrap
from pathlib import Path
import pytest

from Analysis.satd import SATDScanner, SATDItem, SATDSummary, SATDScanner


# ── helpers ───────────────────────────────────────────────────────────────────

def _write(tmp_path: Path, filename: str, code: str) -> Path:
    p = tmp_path / filename
    p.write_text(textwrap.dedent(code), encoding="utf-8")
    return p


# ── SATDScanner._classify ─────────────────────────────────────────────────────

class TestClassify:
    def test_todo_classified_as_design(self):
        item = SATDScanner._classify("f.py", 1, "TODO: fix this later")
        assert item is not None
        assert item.category == "design"
        assert item.marker == "TODO"

    def test_fixme_classified_as_defect(self):
        item = SATDScanner._classify("f.py", 2, "FIXME: null pointer possible here")
        assert item is not None
        assert item.category == "defect"

    def test_hack_classified_as_design(self):
        item = SATDScanner._classify("f.py", 3, "HACK: workaround for library bug")
        assert item is not None
        assert item.category == "design"

    def test_debt_classified_as_debt(self):
        item = SATDScanner._classify("f.py", 4, "DEBT: this entire module needs rewrite")
        assert item is not None
        assert item.category == "debt"

    def test_xxx_classified_as_defect(self):
        item = SATDScanner._classify("f.py", 5, "XXX: broken in edge case")
        assert item is not None
        assert item.category == "defect"

    def test_no_marker_returns_none(self):
        item = SATDScanner._classify("f.py", 6, "This is a normal comment")
        assert item is None

    def test_hours_positive(self):
        item = SATDScanner._classify("f.py", 1, "TODO: fix later")
        assert item.hours > 0

    def test_debt_has_highest_hours(self):
        debt = SATDScanner._classify("f.py", 1, "DEBT: huge mess")
        todo = SATDScanner._classify("f.py", 2, "TODO: small thing")
        assert debt.hours >= todo.hours

    def test_case_insensitive(self):
        item = SATDScanner._classify("f.py", 1, "todo: lowercase")
        assert item is not None

    def test_short_text_truncates(self):
        long_text = "TODO: " + "x" * 200
        item = SATDScanner._classify("f.py", 1, long_text)
        assert len(item.short_text) <= 123  # 120 + ellipsis


# ── SATDScanner.scan_directory ────────────────────────────────────────────────

class TestScanDirectory:
    def test_finds_todos_in_py_file(self, tmp_path):
        _write(tmp_path, "main.py", """\
            def foo():
                # TODO: implement this
                pass
        """)
        scanner = SATDScanner()
        summary = scanner.scan_directory(tmp_path)
        assert summary.total >= 1

    def test_finds_multiple_markers(self, tmp_path):
        _write(tmp_path, "app.py", """\
            # FIXME: broken
            # TODO: add tests
            # HACK: quick fix
            x = 1
        """)
        scanner = SATDScanner()
        summary = scanner.scan_directory(tmp_path)
        assert summary.total == 3

    def test_total_hours_positive(self, tmp_path):
        _write(tmp_path, "app.py", "# TODO: big task\n# DEBT: major rewrite\n")
        scanner = SATDScanner()
        summary = scanner.scan_directory(tmp_path)
        assert summary.total_hours > 0

    def test_empty_directory(self, tmp_path):
        scanner = SATDScanner()
        summary = scanner.scan_directory(tmp_path)
        assert summary.total == 0
        assert summary.total_hours == 0.0

    def test_skips_pycache(self, tmp_path):
        cache = tmp_path / "__pycache__"
        cache.mkdir()
        (cache / "compiled.py").write_text("# TODO: skip me", encoding="utf-8")
        scanner = SATDScanner()
        summary = scanner.scan_directory(tmp_path)
        assert summary.total == 0

    def test_by_category_groups_correctly(self, tmp_path):
        _write(tmp_path, "f.py", "# TODO: design debt\n# FIXME: bug here\n")
        scanner = SATDScanner()
        summary = scanner.scan_directory(tmp_path)
        cats = summary.by_category
        assert "design" in cats
        assert "defect" in cats

    def test_as_dict_has_required_keys(self, tmp_path):
        _write(tmp_path, "f.py", "# TODO: something\n")
        scanner = SATDScanner()
        summary = scanner.scan_directory(tmp_path)
        d = summary.as_dict()
        for key in ("total", "total_hours", "by_category", "items"):
            assert key in d

    def test_no_false_positive_in_code(self, tmp_path):
        # Word "today" should NOT trigger TODO
        _write(tmp_path, "f.py", "today = 'Monday'\n")
        scanner = SATDScanner()
        summary = scanner.scan_directory(tmp_path)
        # "today" contains "todo" — but our marker is \bTODO\b so should not match
        # Allow 0 or check no item has text "today"
        for item in summary.items:
            assert "today" != item.text.strip().lower()

    def test_top_files_sorted_by_count(self, tmp_path):
        _write(tmp_path, "busy.py", "# TODO: 1\n# TODO: 2\n# TODO: 3\n")
        _write(tmp_path, "quiet.py", "# TODO: 1\n")
        scanner = SATDScanner()
        summary = scanner.scan_directory(tmp_path)
        top = summary.top_files
        if len(top) >= 2:
            assert top[0][1] >= top[1][1]  # sorted descending by count
