"""Shared test patterns for LintAnalyzer and SecurityAnalyzer tests.

Eliminates duplicate test logic between test_analysis_lint.py and
test_analysis_security.py by providing reusable assertion helpers.
"""

import subprocess as sp
from pathlib import Path
from unittest.mock import patch, MagicMock

from Core.types import SmellIssue


def make_mock_analyze(analyzer_cls, tool_binary):
    """Factory: create a mock-analyze callable for a given analyzer class.

    Returns a function(raw_output: str) -> list[SmellIssue] that patches
    shutil.which and subprocess.run so the analyzer parses *raw_output*
    without touching the real filesystem.
    """

    def _mock_analyze(raw_output: str) -> list:
        with patch("shutil.which", return_value=tool_binary):
            analyzer = analyzer_cls()
        mock_result = MagicMock()
        mock_result.stdout = raw_output
        mock_result.returncode = 1
        with patch("subprocess.run", return_value=mock_result):
            return analyzer.analyze(Path("/project"))

    return _mock_analyze


# ── Assertion helpers ────────────────────────────────────────────────


def assert_empty_output_returns_empty(mock_analyze):
    """Empty subprocess output → []."""
    assert mock_analyze("") == []


def assert_invalid_json_returns_empty(mock_analyze):
    """Invalid JSON subprocess output → []."""
    assert mock_analyze("not json at all {{{") == []


def assert_all_issues_are_smell_issues(issues):
    """Every issue must be a SmellIssue instance."""
    for issue in issues:
        assert isinstance(issue, SmellIssue)


def assert_not_available_when_tool_missing(analyzer_cls):
    """Analyzer reports not-available when its CLI tool is missing."""
    with patch("shutil.which", return_value=None):
        analyzer = analyzer_cls()
        assert analyzer.available is False


def assert_returns_empty_when_not_available(analyzer_cls):
    """Analyzer.analyze() returns [] when tool is missing."""
    with patch("shutil.which", return_value=None):
        analyzer = analyzer_cls()
        assert analyzer.analyze(Path("/fake/path")) == []


def assert_timeout_returns_empty(analyzer_cls, tool_binary, tool_cmd):
    """Subprocess TimeoutExpired → []."""
    with patch("shutil.which", return_value=tool_binary):
        analyzer = analyzer_cls()
    with patch(
        "subprocess.run", side_effect=sp.TimeoutExpired(cmd=tool_cmd, timeout=120)
    ):
        assert analyzer.analyze(Path("/project")) == []


def assert_file_not_found_returns_empty(analyzer_cls, tool_binary):
    """Subprocess FileNotFoundError → []."""
    with patch("shutil.which", return_value=tool_binary):
        analyzer = analyzer_cls()
    with patch("subprocess.run", side_effect=FileNotFoundError):
        assert analyzer.analyze(Path("/project")) == []
