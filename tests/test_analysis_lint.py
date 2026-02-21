"""
Tests for Analysis/lint.py — LintAnalyzer (Ruff integration).
"""
import pytest
import json
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

from Core.types import Severity
from Analysis.lint import LintAnalyzer
from tests.conftest_analyzers import (
    make_mock_analyze, assert_empty_output_returns_empty,
    assert_invalid_json_returns_empty, assert_all_issues_are_smell_issues,
    assert_not_available_when_tool_missing, assert_returns_empty_when_not_available,
    assert_timeout_returns_empty, assert_file_not_found_returns_empty,
)

# Shared mock-analyze callable for LintAnalyzer
_lint_mock = make_mock_analyze(LintAnalyzer, "/usr/bin/ruff")


# ── helpers ──────────────────────────────────────────────────────────

# Sample Ruff JSON output (mimics real ruff --output-format=json)
SAMPLE_RUFF_OUTPUT = json.dumps([
    {
        "code": "F401",
        "message": "`os` imported but unused",
        "filename": "/project/test.py",
        "location": {"row": 1, "column": 1},
        "end_location": {"row": 1, "column": 10},
        "fix": {"message": "Remove unused import: `os`", "applicability": "safe"},
        "url": "https://docs.astral.sh/ruff/rules/unused-import/",
    },
    {
        "code": "E722",
        "message": "Do not use bare `except`",
        "filename": "/project/test.py",
        "location": {"row": 20, "column": 5},
        "end_location": {"row": 20, "column": 12},
        "fix": None,
        "url": "https://docs.astral.sh/ruff/rules/bare-except/",
    },
    {
        "code": "F841",
        "message": "Local variable `x` is assigned to but never used",
        "filename": "/project/utils.py",
        "location": {"row": 10, "column": 5},
        "end_location": {"row": 10, "column": 6},
        "fix": {"message": "Remove assignment to unused variable `x`", "applicability": "unsafe"},
        "url": "https://docs.astral.sh/ruff/rules/unused-variable/",
    },
    {
        "code": "F811",
        "message": "Redefinition of unused `func` from line 5",
        "filename": "/project/core.py",
        "location": {"row": 15, "column": 1},
        "end_location": {"row": 15, "column": 10},
        "fix": None,
        "url": "https://docs.astral.sh/ruff/rules/redefined-while-unused/",
    },
])


# ════════════════════════════════════════════════════════════════════
#  Availability
# ════════════════════════════════════════════════════════════════════

class TestLintAvailability:

    def test_available_when_ruff_found(self):
        with patch("shutil.which", return_value="/usr/bin/ruff"):
            analyzer = LintAnalyzer()
            assert analyzer.available is True

    def test_not_available_when_ruff_missing(self):
        assert_not_available_when_tool_missing(LintAnalyzer)

    def test_returns_empty_when_not_available(self):
        assert_returns_empty_when_not_available(LintAnalyzer)


# ════════════════════════════════════════════════════════════════════
#  Severity Mapping
# ════════════════════════════════════════════════════════════════════

class TestLintSeverityMapping:

    def test_f401_maps_to_warning(self):
        assert LintAnalyzer._map_severity("F401") == Severity.WARNING

    def test_e722_maps_to_warning(self):
        assert LintAnalyzer._map_severity("E722") == Severity.WARNING

    def test_f811_maps_to_critical(self):
        assert LintAnalyzer._map_severity("F811") == Severity.CRITICAL

    def test_e999_maps_to_critical(self):
        assert LintAnalyzer._map_severity("E999") == Severity.CRITICAL

    def test_f541_maps_to_info(self):
        assert LintAnalyzer._map_severity("F541") == Severity.INFO

    def test_unknown_f_code_maps_to_warning(self):
        assert LintAnalyzer._map_severity("F999") == Severity.WARNING

    def test_unknown_e_code_maps_to_info(self):
        assert LintAnalyzer._map_severity("E999") == Severity.CRITICAL  # E999 is syntax error

    def test_unknown_w_code_maps_to_info(self):
        assert LintAnalyzer._map_severity("W191") == Severity.INFO


# ════════════════════════════════════════════════════════════════════
#  Category Mapping
# ════════════════════════════════════════════════════════════════════

class TestLintCategoryMapping:

    def test_f401_category(self):
        assert LintAnalyzer._rule_to_category("F401") == "unused-import"

    def test_e722_category(self):
        assert LintAnalyzer._rule_to_category("E722") == "bare-except"

    def test_unknown_code_uses_fallback(self):
        assert LintAnalyzer._rule_to_category("X999") == "lint-X999"


# ════════════════════════════════════════════════════════════════════
#  JSON Parsing
# ════════════════════════════════════════════════════════════════════

class TestLintParsing:
    """Tests for lint output parsing."""

    def _mock_analyze(self, ruff_json: str) -> list:
        """Run analyze with mocked subprocess."""
        return _lint_mock(ruff_json)

    def test_parses_sample_output(self):
        issues = self._mock_analyze(SAMPLE_RUFF_OUTPUT)
        assert len(issues) == 4

    def test_all_issues_are_smell_issues(self):
        issues = self._mock_analyze(SAMPLE_RUFF_OUTPUT)
        assert_all_issues_are_smell_issues(issues)

    def test_source_is_ruff(self):
        issues = self._mock_analyze(SAMPLE_RUFF_OUTPUT)
        for issue in issues:
            assert issue.source == "ruff"

    def test_rule_codes_preserved(self):
        issues = self._mock_analyze(SAMPLE_RUFF_OUTPUT)
        codes = {i.rule_code for i in issues}
        assert codes == {"F401", "E722", "F841", "F811"}

    def test_fixable_flag_set_correctly(self):
        issues = self._mock_analyze(SAMPLE_RUFF_OUTPUT)
        fixable = {i.rule_code: i.fixable for i in issues}
        assert fixable["F401"] is True   # safe fix
        assert fixable["F841"] is True   # unsafe fix (still fixable)
        assert fixable["E722"] is False  # no fix
        assert fixable["F811"] is False  # no fix

    def test_relative_paths(self):
        issues = self._mock_analyze(SAMPLE_RUFF_OUTPUT)
        paths = {i.file_path for i in issues}
        # Should be relative to /project
        assert "test.py" in paths
        assert "utils.py" in paths
        assert "core.py" in paths

    def test_lines_correct(self):
        issues = self._mock_analyze(SAMPLE_RUFF_OUTPUT)
        f401 = [i for i in issues if i.rule_code == "F401"][0]
        assert f401.line == 1

    def test_empty_output_returns_empty(self):
        assert_empty_output_returns_empty(_lint_mock)

    def test_invalid_json_returns_empty(self):
        assert_invalid_json_returns_empty(_lint_mock)

    def test_sorted_critical_first(self):
        issues = self._mock_analyze(SAMPLE_RUFF_OUTPUT)
        # F811 is CRITICAL, should come first
        assert issues[0].rule_code == "F811"


# ════════════════════════════════════════════════════════════════════
#  Summary
# ════════════════════════════════════════════════════════════════════

class TestLintSummary:
    """Tests for lint summary generation."""

    def test_summary_counts(self):
        """Verify lint summary correctly counts issues by severity."""
        with patch("shutil.which", return_value="/usr/bin/ruff"):
            analyzer = LintAnalyzer()

        mock_result = MagicMock()
        mock_result.stdout = SAMPLE_RUFF_OUTPUT

        with patch("subprocess.run", return_value=mock_result):
            issues = analyzer.analyze(Path("/project"))

        summary = analyzer.summary(issues)
        assert summary["total"] == 4
        assert summary["source"] == "ruff"
        assert "by_rule" in summary
        assert "worst_files" in summary
        assert summary["by_rule"]["F401"] == 1
        assert summary["by_rule"]["E722"] == 1

    def test_summary_fixable_count(self):
        with patch("shutil.which", return_value="/usr/bin/ruff"):
            analyzer = LintAnalyzer()

        mock_result = MagicMock()
        mock_result.stdout = SAMPLE_RUFF_OUTPUT

        with patch("subprocess.run", return_value=mock_result):
            issues = analyzer.analyze(Path("/project"))

        summary = analyzer.summary(issues)
        assert summary["fixable"] == 2  # F401 (safe) + F841 (unsafe)


# ════════════════════════════════════════════════════════════════════
#  Error Handling
# ════════════════════════════════════════════════════════════════════

class TestLintErrorHandling:

    def test_timeout_returns_empty(self):
        assert_timeout_returns_empty(LintAnalyzer, "/usr/bin/ruff", "ruff")

    def test_file_not_found_returns_empty(self):
        assert_file_not_found_returns_empty(LintAnalyzer, "/usr/bin/ruff")


# ════════════════════════════════════════════════════════════════════
#  Live Integration (skip if ruff not installed)
# ════════════════════════════════════════════════════════════════════

class TestLintLiveIntegration:
    """These tests actually run ruff. Skipped if not installed."""

    @pytest.fixture(autouse=True)
    def check_ruff(self):
        if shutil.which("ruff") is None:
            pytest.skip("ruff not installed")

    def test_scan_fixture_file(self, tmp_path):
        """Scan a known-bad file and verify issues found."""
        bad_file = tmp_path / "bad.py"
        bad_file.write_text(
            "import os\nimport sys\n\nx = 1; y = 2\n\n"
            "def foo():\n    unused = 42\n    return 1\n\n"
            "try:\n    pass\nexcept:\n    pass\n"
        )

        analyzer = LintAnalyzer()
        issues = analyzer.analyze(tmp_path)
        assert len(issues) > 0

        codes = {i.rule_code for i in issues}
        # Should find at least unused imports
        assert "F401" in codes

    def test_clean_file_no_issues(self, tmp_path):
        """Scan a clean file and verify no issues."""
        clean_file = tmp_path / "clean.py"
        clean_file.write_text('"""Clean module."""\n\n\ndef greet(name: str) -> str:\n    """Say hello."""\n    return f"Hello, {name}"\n')

        analyzer = LintAnalyzer()
        issues = analyzer.analyze(tmp_path)
        assert len(issues) == 0

    def test_summary_structure(self, tmp_path):
        """Verify summary dict has expected keys."""
        bad_file = tmp_path / "bad.py"
        bad_file.write_text("import os\nimport sys\n")

        analyzer = LintAnalyzer()
        issues = analyzer.analyze(tmp_path)
        summary = analyzer.summary(issues)

        assert "total" in summary
        assert "critical" in summary
        assert "warning" in summary
        assert "fixable" in summary
        assert "by_rule" in summary
        assert "worst_files" in summary
        assert summary["source"] == "ruff"
