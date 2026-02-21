"""
Tests for Analysis/security.py — SecurityAnalyzer (Bandit integration).
"""
import pytest
import json
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

from Core.types import Severity
from Analysis.security import SecurityAnalyzer
from tests.conftest_analyzers import (
    make_mock_analyze, assert_empty_output_returns_empty,
    assert_invalid_json_returns_empty, assert_all_issues_are_smell_issues,
    assert_not_available_when_tool_missing, assert_returns_empty_when_not_available,
    assert_timeout_returns_empty, assert_file_not_found_returns_empty,
)

# Shared mock-analyze callable for SecurityAnalyzer
_sec_mock = make_mock_analyze(SecurityAnalyzer, "/usr/bin/bandit")


# ── helpers ──────────────────────────────────────────────────────────

# Sample Bandit JSON output (mimics real bandit -f json)
SAMPLE_BANDIT_OUTPUT = json.dumps({
    "errors": [],
    "generated_at": "2026-02-17T12:00:00Z",
    "metrics": {},
    "results": [
        {
            "code": "    subprocess.run('echo hello', shell=True)\n",
            "col_offset": 4,
            "end_col_offset": 47,
            "filename": "/project/utils.py",
            "issue_confidence": "HIGH",
            "issue_cwe": {"id": 78, "link": ""},
            "issue_severity": "HIGH",
            "issue_text": "subprocess call with shell=True identified, security issue.",
            "line_number": 15,
            "line_range": [15],
            "more_info": "",
            "test_id": "B602",
            "test_name": "subprocess_popen_with_shell_equals_true",
        },
        {
            "code": "    h = hashlib.md5(b'data')\n",
            "col_offset": 8,
            "end_col_offset": 31,
            "filename": "/project/core/hasher.py",
            "issue_confidence": "HIGH",
            "issue_severity": "HIGH",
            "issue_text": "Use of weak MD5 hash for security. Consider usedforsecurity=False",
            "line_number": 42,
            "line_range": [42],
            "more_info": "",
            "test_id": "B324",
            "test_name": "hashlib",
        },
        {
            "code": "    assert x > 0\n",
            "col_offset": 4,
            "end_col_offset": 18,
            "filename": "/project/tests/test_foo.py",
            "issue_confidence": "HIGH",
            "issue_severity": "LOW",
            "issue_text": "Use of assert detected.",
            "line_number": 10,
            "line_range": [10],
            "more_info": "",
            "test_id": "B101",
            "test_name": "assert_used",
        },
        {
            "code": "    requests.get(url)\n",
            "col_offset": 4,
            "end_col_offset": 24,
            "filename": "/project/api.py",
            "issue_confidence": "LOW",
            "issue_severity": "MEDIUM",
            "issue_text": "Call to requests without timeout",
            "line_number": 88,
            "line_range": [88],
            "more_info": "",
            "test_id": "B113",
            "test_name": "request_without_timeout",
        },
        {
            "code": "    exec(code)\n",
            "col_offset": 4,
            "end_col_offset": 14,
            "filename": "/project/dynamic.py",
            "issue_confidence": "HIGH",
            "issue_severity": "MEDIUM",
            "issue_text": "Use of exec detected.",
            "line_number": 33,
            "line_range": [33],
            "more_info": "",
            "test_id": "B102",
            "test_name": "exec_used",
        },
    ]
})


# ════════════════════════════════════════════════════════════════════
#  Availability
# ════════════════════════════════════════════════════════════════════

class TestSecurityAvailability:

    def test_available_when_bandit_found(self):
        with patch("shutil.which", return_value="/usr/bin/bandit"):
            analyzer = SecurityAnalyzer()
            assert analyzer.available is True

    def test_not_available_when_bandit_missing(self):
        assert_not_available_when_tool_missing(SecurityAnalyzer)

    def test_returns_empty_when_not_available(self):
        assert_returns_empty_when_not_available(SecurityAnalyzer)


# ════════════════════════════════════════════════════════════════════
#  Severity Mapping
# ════════════════════════════════════════════════════════════════════

class TestSecuritySeverityMapping:
    """Tests for security severity mapping."""

    def _mock_analyze(self, bandit_json: str) -> list:
        """Run analyze with mocked subprocess."""
        return _sec_mock(bandit_json)

    def test_high_maps_to_critical(self):
        issues = self._mock_analyze(SAMPLE_BANDIT_OUTPUT)
        high_issues = [i for i in issues if i.rule_code in ("B602", "B324")]
        for issue in high_issues:
            assert issue.severity == Severity.CRITICAL

    def test_medium_maps_to_warning(self):
        issues = self._mock_analyze(SAMPLE_BANDIT_OUTPUT)
        medium_issues = [i for i in issues if i.rule_code in ("B113", "B102")]
        for issue in medium_issues:
            assert issue.severity == Severity.WARNING

    def test_low_maps_to_info(self):
        issues = self._mock_analyze(SAMPLE_BANDIT_OUTPUT)
        low_issues = [i for i in issues if i.rule_code == "B101"]
        for issue in low_issues:
            assert issue.severity == Severity.INFO


# ════════════════════════════════════════════════════════════════════
#  JSON Parsing
# ════════════════════════════════════════════════════════════════════

class TestSecurityParsing:
    """Tests for security result parsing."""

    def _mock_analyze(self, bandit_json: str) -> list:
        return _sec_mock(bandit_json)

    def test_parses_sample_output(self):
        issues = self._mock_analyze(SAMPLE_BANDIT_OUTPUT)
        # B101 in test file is filtered out → 4 results
        assert len(issues) == 4

    def test_all_issues_are_smell_issues(self):
        issues = self._mock_analyze(SAMPLE_BANDIT_OUTPUT)
        assert_all_issues_are_smell_issues(issues)

    def test_source_is_bandit(self):
        issues = self._mock_analyze(SAMPLE_BANDIT_OUTPUT)
        for issue in issues:
            assert issue.source == "bandit"

    def test_rule_codes_preserved(self):
        issues = self._mock_analyze(SAMPLE_BANDIT_OUTPUT)
        codes = {i.rule_code for i in issues}
        # B101 in test file is filtered out
        assert codes == {"B602", "B324", "B113", "B102"}

    def test_confidence_preserved(self):
        issues = self._mock_analyze(SAMPLE_BANDIT_OUTPUT)
        b113 = [i for i in issues if i.rule_code == "B113"][0]
        assert b113.confidence == "LOW"

        b602 = [i for i in issues if i.rule_code == "B602"][0]
        assert b602.confidence == "HIGH"

    def test_relative_paths(self):
        issues = self._mock_analyze(SAMPLE_BANDIT_OUTPUT)
        paths = {i.file_path for i in issues}
        assert "utils.py" in paths
        assert "api.py" in paths

    def test_lines_correct(self):
        issues = self._mock_analyze(SAMPLE_BANDIT_OUTPUT)
        b602 = [i for i in issues if i.rule_code == "B602"][0]
        assert b602.line == 15

    def test_categories_assigned(self):
        issues = self._mock_analyze(SAMPLE_BANDIT_OUTPUT)
        b602 = [i for i in issues if i.rule_code == "B602"][0]
        assert b602.category == "subprocess-shell"

        b324 = [i for i in issues if i.rule_code == "B324"][0]
        assert b324.category == "weak-hash"

    def test_suggestions_populated(self):
        issues = self._mock_analyze(SAMPLE_BANDIT_OUTPUT)
        b324 = [i for i in issues if i.rule_code == "B324"][0]
        assert "SHA-256" in b324.suggestion or "usedforsecurity" in b324.suggestion

        b602 = [i for i in issues if i.rule_code == "B602"][0]
        assert "shell" in b602.suggestion.lower()

    def test_sorted_critical_first(self):
        issues = self._mock_analyze(SAMPLE_BANDIT_OUTPUT)
        assert issues[0].severity == Severity.CRITICAL

    def test_empty_output_returns_empty(self):
        assert_empty_output_returns_empty(_sec_mock)

    def test_invalid_json_returns_empty(self):
        assert_invalid_json_returns_empty(_sec_mock)

    def test_empty_results_returns_empty(self):
        empty = json.dumps({"errors": [], "results": []})
        issues = self._mock_analyze(empty)
        assert issues == []


# ════════════════════════════════════════════════════════════════════
#  Summary
# ════════════════════════════════════════════════════════════════════

class TestSecuritySummary:
    """Tests for security summary generation."""

    def test_summary_counts(self):
        """Verify security summary correctly counts issues by severity."""
        with patch("shutil.which", return_value="/usr/bin/bandit"):
            analyzer = SecurityAnalyzer()

        mock_result = MagicMock()
        mock_result.stdout = SAMPLE_BANDIT_OUTPUT

        with patch("subprocess.run", return_value=mock_result):
            issues = analyzer.analyze(Path("/project"))

        summary = analyzer.summary(issues)
        # B101 in test file is filtered → 4 total
        assert summary["total"] == 4
        assert summary["critical"] == 2   # B602, B324
        assert summary["warning"] == 2    # B113, B102
        assert summary["info"] == 0       # B101 filtered
        assert summary["source"] == "bandit"
        assert "by_rule" in summary
        assert "worst_files" in summary
        assert "by_confidence" in summary

    def test_summary_confidence_breakdown(self):
        with patch("shutil.which", return_value="/usr/bin/bandit"):
            analyzer = SecurityAnalyzer()

        mock_result = MagicMock()
        mock_result.stdout = SAMPLE_BANDIT_OUTPUT

        with patch("subprocess.run", return_value=mock_result):
            issues = analyzer.analyze(Path("/project"))

        summary = analyzer.summary(issues)
        # B101 filtered → 3 HIGH confidence (B602, B324, B102)
        assert summary["by_confidence"]["HIGH"] == 3


# ════════════════════════════════════════════════════════════════════
#  Fix Suggestions
# ════════════════════════════════════════════════════════════════════

class TestSecuritySuggestions:

    def test_known_suggestions(self):
        known = {
            "B101": "assert",
            "B102": "exec",
            "B113": "timeout",
            "B324": "SHA-256",
            "B602": "shell",
        }
        for test_id, keyword in known.items():
            suggestion = SecurityAnalyzer._suggest_fix(test_id, "")
            assert keyword.lower() in suggestion.lower(), \
                f"B{test_id} suggestion should mention '{keyword}': got '{suggestion}'"

    def test_unknown_returns_generic(self):
        suggestion = SecurityAnalyzer._suggest_fix("B999", "")
        assert "review" in suggestion.lower() or "best practice" in suggestion.lower()


# ════════════════════════════════════════════════════════════════════
#  Error Handling
# ════════════════════════════════════════════════════════════════════

class TestSecurityErrorHandling:

    def test_timeout_returns_empty(self):
        assert_timeout_returns_empty(SecurityAnalyzer, "/usr/bin/bandit", "bandit")

    def test_file_not_found_returns_empty(self):
        assert_file_not_found_returns_empty(SecurityAnalyzer, "/usr/bin/bandit")


# ════════════════════════════════════════════════════════════════════
#  Live Integration (skip if bandit not installed)
# ════════════════════════════════════════════════════════════════════

class TestSecurityLiveIntegration:
    """These tests actually run bandit. Skipped if not installed."""

    @pytest.fixture(autouse=True)
    def check_bandit(self):
        if shutil.which("bandit") is None:
            pytest.skip("bandit not installed")

    def test_scan_fixture_with_shell_true(self, tmp_path):
        """Scan a file with shell=True and verify detection."""
        bad_file = tmp_path / "bad.py"
        bad_file.write_text(
            "import subprocess\n\n"
            "def run_cmd():\n"
            "    subprocess.run('echo hello', shell=True)\n"
        )

        analyzer = SecurityAnalyzer()
        issues = analyzer.analyze(tmp_path)

        # Should find at least B602 (shell=True) and B404 (import subprocess)
        codes = {i.rule_code for i in issues}
        assert "B602" in codes or "B603" in codes

    def test_scan_fixture_with_md5(self, tmp_path):
        """Scan a file with MD5 and verify detection."""
        bad_file = tmp_path / "hasher.py"
        bad_file.write_text(
            "import hashlib\n\n"
            "def make_hash():\n"
            "    return hashlib.md5(b'data').hexdigest()\n"
        )

        analyzer = SecurityAnalyzer()
        issues = analyzer.analyze(tmp_path)

        codes = {i.rule_code for i in issues}
        assert "B324" in codes or "B303" in codes

    def test_clean_file_minimal_issues(self, tmp_path):
        """Scan a clean file — should have no HIGH issues."""
        clean = tmp_path / "clean.py"
        clean.write_text('"""Clean module."""\n\n\ndef greet(name: str) -> str:\n    """Say hello."""\n    return f"Hello, {name}"\n')

        analyzer = SecurityAnalyzer()
        issues = analyzer.analyze(tmp_path)
        high = [i for i in issues if i.severity == Severity.CRITICAL]
        assert len(high) == 0

    def test_summary_structure(self, tmp_path):
        """Verify summary dict has expected keys."""
        bad_file = tmp_path / "bad.py"
        bad_file.write_text(
            "import subprocess\n"
            "subprocess.run('echo hi', shell=True)\n"
        )

        analyzer = SecurityAnalyzer()
        issues = analyzer.analyze(tmp_path)
        summary = analyzer.summary(issues)

        assert "total" in summary
        assert "critical" in summary
        assert "warning" in summary
        assert "by_rule" in summary
        assert "by_confidence" in summary
        assert "worst_files" in summary
        assert summary["source"] == "bandit"


# ════════════════════════════════════════════════════════════════════
#  Edge Cases & Filtering
# ════════════════════════════════════════════════════════════════════

class TestSecurityEdgeCases:
    """Tests for security edge case handling."""

    def _mock_analyze(self, bandit_json: str) -> list:
        return _sec_mock(bandit_json)

    def test_b101_in_non_test_file_is_kept(self):
        """B101 (assert-used) in a production file should NOT be filtered."""
        data = json.dumps({"errors": [], "results": [{
            "code": "    assert x > 0\n", "col_offset": 4,
            "end_col_offset": 18, "filename": "/project/utils.py",
            "issue_confidence": "HIGH", "issue_severity": "LOW",
            "issue_text": "Use of assert.", "line_number": 5,
            "line_range": [5], "more_info": "", "test_id": "B101",
            "test_name": "assert_used",
        }]})
        issues = self._mock_analyze(data)
        assert len(issues) == 1
        assert issues[0].rule_code == "B101"

    def test_b404_always_filtered(self):
        """B404 (import-subprocess) should always be filtered out."""
        data = json.dumps({"errors": [], "results": [{
            "code": "import subprocess\n", "col_offset": 0,
            "end_col_offset": 20, "filename": "/project/run.py",
            "issue_confidence": "HIGH", "issue_severity": "LOW",
            "issue_text": "Consider possible security implications.",
            "line_number": 1, "line_range": [1], "more_info": "",
            "test_id": "B404", "test_name": "import_subprocess",
        }]})
        issues = self._mock_analyze(data)
        assert len(issues) == 0

    def test_progress_bar_stripped(self):
        """Bandit progress bar before JSON should be stripped cleanly."""
        preamble = "Working... ---------------------------------------- 100%  0:00:01\n"
        raw = preamble + SAMPLE_BANDIT_OUTPUT
        issues = self._mock_analyze(raw)
        assert len(issues) == 4  # B101 filtered

    def test_severity_threshold_high(self):
        """severity_threshold='high' passes -lll flag."""
        with patch("shutil.which", return_value="/usr/bin/bandit"):
            analyzer = SecurityAnalyzer(severity_threshold="high")
        mock_result = MagicMock()
        mock_result.stdout = json.dumps({"errors": [], "results": []})
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            analyzer.analyze(Path("/project"))
            cmd = mock_run.call_args[0][0]
            assert "-lll" in cmd

    def test_extra_args_forwarded(self):
        """extra_args are appended to the bandit command."""
        with patch("shutil.which", return_value="/usr/bin/bandit"):
            analyzer = SecurityAnalyzer(extra_args=["--skip", "B101"])
        mock_result = MagicMock()
        mock_result.stdout = json.dumps({"errors": [], "results": []})
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            analyzer.analyze(Path("/project"))
            cmd = mock_run.call_args[0][0]
            assert "--skip" in cmd
            assert "B101" in cmd
