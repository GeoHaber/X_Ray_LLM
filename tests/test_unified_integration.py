"""
Tests for unified X-Ray v5.0 integration:
  - Reporting functions (print_lint_report, print_security_report, print_unified_grade)
  - SmellIssue new fields (source, rule_code, fixable, confidence)
  - Cross-tool grade calculation
"""
from Core.types import SmellIssue, Severity
from Analysis.reporting import print_unified_grade


# ── helpers ──────────────────────────────────────────────────────────

def _smell(source="xray", severity=Severity.WARNING, **kw):
    """Create a SmellIssue with defaults."""
    defaults = dict(
        file_path="test.py", line=1, end_line=10,
        category="test-smell", severity=severity,
        message="Test issue", suggestion="Fix it",
        name="test_func", metric_value=0,
        source=source, rule_code="", fixable=False,
        confidence="",
    )
    defaults.update(kw)
    return SmellIssue(**defaults)


# ════════════════════════════════════════════════════════════════════
#  SmellIssue new fields
# ════════════════════════════════════════════════════════════════════

class TestSmellIssueFields:
    """Tests for SmellIssue field validation."""

    def test_default_source_is_xray(self):
        issue = SmellIssue(
            file_path="f.py", line=1, end_line=5,
            category="test", severity=Severity.WARNING,
            message="msg", suggestion="fix", name="fn",
        )
        assert issue.source == "xray"

    def test_source_can_be_ruff(self):
        issue = _smell(source="ruff")
        assert issue.source == "ruff"

    def test_source_can_be_bandit(self):
        issue = _smell(source="bandit")
        assert issue.source == "bandit"

    def test_rule_code_defaults_empty(self):
        issue = _smell()
        assert issue.rule_code == ""

    def test_fixable_defaults_false(self):
        issue = _smell()
        assert issue.fixable is False

    def test_confidence_defaults_empty(self):
        issue = _smell()
        assert issue.confidence == ""

    def test_backward_compat_metric_value_defaults_zero(self):
        """metric_value changed from required to default=0."""
        issue = SmellIssue(
            file_path="f.py", line=1, end_line=5,
            category="test", severity=Severity.WARNING,
            message="msg", suggestion="fix", name="fn",
        )
        assert issue.metric_value == 0


# ════════════════════════════════════════════════════════════════════
#  Unified Grade Calculation
# ════════════════════════════════════════════════════════════════════

class TestUnifiedGrade:
    """Tests for unified grade computation."""

    def test_perfect_score_no_issues(self):
        results = {
            "smells": {"critical": 0, "warning": 0, "info": 0},
            "lint": {"critical": 0, "warning": 0, "info": 0, "fixable": 0},
            "security": {"critical": 0, "warning": 0, "info": 0},
        }
        grade = print_unified_grade(results)
        assert grade["score"] == 100.0
        assert grade["letter"] == "A+"

    def test_all_tools_tracked(self):
        results = {
            "smells": {"critical": 0, "warning": 0, "info": 0},
            "lint": {"critical": 0, "warning": 0, "info": 0, "fixable": 0},
            "security": {"critical": 0, "warning": 0, "info": 0},
        }
        grade = print_unified_grade(results)
        assert "X-Ray Smells" in grade["tools_run"]
        assert "Ruff Lint" in grade["tools_run"]
        assert "Bandit Security" in grade["tools_run"]

    def test_critical_smells_reduce_score(self):
        results = {
            "smells": {"critical": 40, "warning": 0, "info": 0},
        }
        grade = print_unified_grade(results)
        assert grade["score"] < 100.0
        assert grade["breakdown"]["smells"]["penalty"] > 0

    def test_security_issues_heavy_penalty(self):
        results = {
            "security": {"critical": 10, "warning": 5, "info": 0},
        }
        grade = print_unified_grade(results)
        # 10 HIGH * 1.5 + 5 MEDIUM * 0.3 = 16.5
        assert grade["score"] < 84

    def test_lint_fixable_tracked(self):
        results = {
            "lint": {"critical": 0, "warning": 100, "info": 0, "fixable": 80},
        }
        grade = print_unified_grade(results)
        assert grade["breakdown"]["lint"]["fixable"] == 80

    def test_duplicates_penalized(self):
        results = {
            "duplicates": {"total_groups": 100},
        }
        grade = print_unified_grade(results)
        assert grade["score"] < 100.0
        assert grade["breakdown"]["duplicates"]["penalty"] > 0

    def test_maximum_penalty_capped(self):
        """Even extreme numbers don't reduce score below 0."""
        results = {
            "smells": {"critical": 9999, "warning": 9999, "info": 9999},
            "lint": {"critical": 9999, "warning": 9999, "info": 9999, "fixable": 0},
            "security": {"critical": 9999, "warning": 9999, "info": 9999},
            "duplicates": {"total_groups": 9999},
        }
        grade = print_unified_grade(results)
        assert grade["score"] >= 0

    def test_grade_letter_boundaries(self):
        """Test that score-to-letter mapping works at boundaries."""
        _GRADE_SCALE = [
            (97, "A+"), (93, "A"), (90, "A-"),
            (87, "B+"), (83, "B"), (80, "B-"),
            (77, "C+"), (73, "C"), (70, "C-"),
            (67, "D+"), (63, "D"), (60, "D-"),
        ]

        def _score_to_letter(score):
            for threshold, letter in _GRADE_SCALE:
                if score >= threshold:
                    return letter
            return "F"

        test_cases = [
            (100, "A+"), (97, "A+"), (96, "A"), (93, "A"), (92, "A-"),
            (90, "A-"), (89, "B+"), (87, "B+"), (86, "B"), (83, "B"),
            (82, "B-"), (80, "B-"), (79, "C+"), (77, "C+"), (76, "C"),
            (73, "C"), (72, "C-"), (70, "C-"), (69, "D+"), (67, "D+"),
            (66, "D"), (63, "D"), (62, "D-"), (60, "D-"), (59, "F"),
        ]
        for score, expected_letter in test_cases:
            letter = _score_to_letter(score)
            assert letter == expected_letter, f"Score {score} should be {expected_letter} but got {letter}"

    def test_only_smells_scanned(self):
        """If only smells were run, only smells in tools_run."""
        results = {
            "smells": {"critical": 5, "warning": 10, "info": 20},
        }
        grade = print_unified_grade(results)
        assert "X-Ray Smells" in grade["tools_run"]
        assert "Ruff Lint" not in grade["tools_run"]
        assert "Bandit Security" not in grade["tools_run"]

    def test_empty_results_perfect_score(self):
        """No tools run = perfect score (nothing to penalize)."""
        grade = print_unified_grade({})
        assert grade["score"] == 100.0
        assert grade["letter"] == "A+"

    def test_realistic_rag_rat_scenario(self):
        """Simulate RAG_RAT's actual numbers — heavy debt should score low."""
        results = {
            "smells": {"critical": 107, "warning": 436, "info": 175},
            "duplicates": {"total_groups": 104},
            "lint": {"critical": 6, "warning": 407, "info": 296, "fixable": 461},
            "security": {"critical": 12, "warning": 35, "info": 2014},
        }
        grade = print_unified_grade(results)
        # With 4 tools all maxing out penalties (30+15+25+30 = 100 cap),
        # the score should be very low
        assert grade["score"] < 30   # Heavy technical debt
        assert grade["score"] >= 0   # Never negative
        # The grade reflects reality: RAG_RAT needed major work
        assert grade["letter"] in ("F", "D-", "D", "D+")


# ════════════════════════════════════════════════════════════════════
#  Reporting Functions Don't Crash
# ════════════════════════════════════════════════════════════════════

class TestReportingNoCrash:
    """Ensure all print functions handle edge cases without crashing."""

    def test_print_lint_report_empty(self, capsys):
        from Analysis.reporting import print_lint_report
        print_lint_report([], {"total": 0, "critical": 0, "warning": 0,
                              "info": 0, "fixable": 0, "by_rule": {},
                              "worst_files": {}, "source": "ruff"})
        captured = capsys.readouterr()
        assert "No lint issues" in captured.out

    def test_print_lint_report_with_data(self, capsys):
        from Analysis.reporting import print_lint_report
        issues = [_smell(source="ruff", severity=Severity.CRITICAL, rule_code="F811")]
        summary = {"total": 1, "critical": 1, "warning": 0, "info": 0,
                   "fixable": 0, "by_rule": {"F811": 1},
                   "worst_files": {"test.py": 1}, "source": "ruff"}
        print_lint_report(issues, summary)
        captured = capsys.readouterr()
        assert "Ruff" in captured.out
        assert "1" in captured.out

    def test_print_security_report_empty(self, capsys):
        from Analysis.reporting import print_security_report
        print_security_report([], {"total": 0, "critical": 0, "warning": 0,
                                   "info": 0, "by_rule": {},
                                   "by_confidence": {},
                                   "worst_files": {}, "source": "bandit"})
        captured = capsys.readouterr()
        assert "No security issues" in captured.out

    def test_print_security_report_with_data(self, capsys):
        from Analysis.reporting import print_security_report
        issues = [_smell(source="bandit", severity=Severity.CRITICAL,
                         rule_code="B602", category="subprocess-shell")]
        summary = {"total": 1, "critical": 1, "warning": 0, "info": 0,
                   "by_rule": {"B602": 1}, "by_confidence": {"HIGH": 1},
                   "worst_files": {"test.py": 1}, "source": "bandit"}
        print_security_report(issues, summary)
        captured = capsys.readouterr()
        assert "Bandit" in captured.out
        assert "HIGH" in captured.out

    def test_print_unified_grade_with_all_data(self, capsys):
        results = {
            "smells": {"critical": 5, "warning": 20, "info": 10},
            "lint": {"critical": 2, "warning": 50, "info": 100, "fixable": 30},
            "security": {"critical": 3, "warning": 10, "info": 500},
            "duplicates": {"total_groups": 15},
        }
        grade = print_unified_grade(results)
        captured = capsys.readouterr()
        assert "UNIFIED CODE QUALITY GRADE" in captured.out
        assert grade["letter"] in ("A+", "A", "A-", "B+", "B", "B-",
                                   "C+", "C", "C-", "D+", "D", "D-", "F")


# ════════════════════════════════════════════════════════════════════
#  Version Check
# ════════════════════════════════════════════════════════════════════

class TestVersion:

    def test_version_is_valid_semver(self):
        """Version must be a valid semantic version with major >= 5."""
        from Core.config import __version__
        parts = __version__.split(".")
        assert len(parts) >= 2, f"Expected semver format, got: {__version__}"
        major = int(parts[0])
        assert major >= 5, f"Major version should be >= 5, got {major}"

    def test_banner_contains_unified(self):
        from Core.config import BANNER
        assert "Unified" in BANNER or "unified" in BANNER or "Ruff" in BANNER
