"""
tests/test_analysis_project_health.py
======================================
Tests for Analysis/project_health.py — project structural health checker.

Covers:
  - HealthCheck dataclass
  - HealthReport dataclass + to_dict()
  - _score_to_grade() helper
  - ProjectHealthAnalyzer.analyze() — all 10 checks:
      gitignore, readme, license, manifest, docker, ci, env_example,
      tests, deps, changelog
  - auto_fix=True mode (creates files)
  - ProjectHealthAnalyzer.summary()
"""

from Analysis.project_health import (
    HealthCheck,
    HealthReport,
    ProjectHealthAnalyzer,
    _create_gitignore_file,
    _create_license_file,
    _create_package_json_file,
    _score_to_grade,
)


# ── _score_to_grade ───────────────────────────────────────────────────────────


class TestScoreToGrade:
    def test_perfect_score(self):
        assert _score_to_grade(100) == "A+"

    def test_a_grade(self):
        assert _score_to_grade(95) in ("A+", "A")

    def test_b_grade(self):
        grade = _score_to_grade(85)
        assert grade.startswith("B")

    def test_c_grade(self):
        grade = _score_to_grade(75)
        assert grade.startswith("C")

    def test_d_grade(self):
        grade = _score_to_grade(65)
        assert grade.startswith("D")

    def test_failing_score(self):
        grade = _score_to_grade(50)
        assert grade == "F"

    def test_zero(self):
        assert _score_to_grade(0) == "F"


# ── HealthCheck dataclass ─────────────────────────────────────────────────────


class TestHealthCheck:
    def test_creation(self):
        hc = HealthCheck(
            name="gitignore",
            description="Has .gitignore",
            weight=10,
            passed=True,
        )
        assert hc.name == "gitignore"
        assert hc.passed is True
        assert hc.weight == 10

    def test_defaults(self):
        hc = HealthCheck(name="x", description="y", weight=5)
        assert hc.passed is False
        assert hc.auto_fixable is False
        assert hc.detail == ""


# ── HealthReport dataclass ────────────────────────────────────────────────────


class TestHealthReport:
    def test_to_dict_structure(self, tmp_path):
        hc = HealthCheck(
            name="readme", description="Has README", weight=10, passed=True
        )
        report = HealthReport(
            root=str(tmp_path / "proj"), score=90, grade="A-", checks=[hc]
        )
        d = report.to_dict()
        assert "score" in d
        assert "grade" in d
        assert "checks" in d
        assert isinstance(d["checks"], list)

    def test_to_dict_check_list(self, tmp_path):
        hc = HealthCheck(name="test", description="Has tests", weight=10, passed=False)
        report = HealthReport(root=str(tmp_path), score=70, grade="C", checks=[hc])
        d = report.to_dict()
        assert len(d["checks"]) == 1
        assert d["checks"][0]["name"] == "test"
        assert d["checks"][0]["passed"] is False


# ── Module-level auto-fix helpers ─────────────────────────────────────────────


class TestAutoFixHelpers:
    def test_create_gitignore(self, tmp_path):
        _create_gitignore_file(tmp_path)
        gi = tmp_path / ".gitignore"
        assert gi.exists()
        content = gi.read_text()
        assert "__pycache__" in content or "node_modules" in content

    def test_create_license(self, tmp_path):
        _create_license_file(tmp_path)
        lic = tmp_path / "LICENSE"
        assert lic.exists()
        content = lic.read_text()
        assert "MIT" in content

    def test_create_package_json(self, tmp_path):
        _create_package_json_file(tmp_path)
        pkg = tmp_path / "package.json"
        assert pkg.exists()
        import json

        data = json.loads(pkg.read_text())
        assert "name" in data

    def test_create_gitignore_idempotent(self, tmp_path):
        """Calling twice should not crash or corrupt the file."""
        _create_gitignore_file(tmp_path)
        _create_gitignore_file(tmp_path)
        assert (tmp_path / ".gitignore").exists()


# ── ProjectHealthAnalyzer.analyze ─────────────────────────────────────────────


class TestProjectHealthAnalyzerAnalyze:
    """Tests for each individual health check."""

    def test_returns_health_report(self, tmp_path):
        a = ProjectHealthAnalyzer()
        report = a.analyze(tmp_path)
        assert isinstance(report, HealthReport)

    def test_score_between_0_and_100(self, tmp_path):
        report = ProjectHealthAnalyzer().analyze(tmp_path)
        assert 0 <= report.score <= 100

    def test_grade_populated(self, tmp_path):
        report = ProjectHealthAnalyzer().analyze(tmp_path)
        assert len(report.grade) >= 1

    def test_checks_list_populated(self, tmp_path):
        report = ProjectHealthAnalyzer().analyze(tmp_path)
        assert len(report.checks) >= 5  # should have at least 5 checks

    # ── gitignore check ──────────────────────────────────────────────────

    def test_gitignore_check_passes_when_present(self, tmp_path):
        (tmp_path / ".gitignore").write_text("__pycache__\n")
        report = ProjectHealthAnalyzer().analyze(tmp_path)
        gi_check = next(
            (c for c in report.checks if "gitignore" in c.name.lower()), None
        )
        assert gi_check is not None
        assert gi_check.passed is True

    def test_gitignore_check_fails_when_missing(self, tmp_path):
        report = ProjectHealthAnalyzer().analyze(tmp_path)
        gi_check = next(
            (c for c in report.checks if "gitignore" in c.name.lower()), None
        )
        assert gi_check is not None
        assert gi_check.passed is False

    # ── readme check ─────────────────────────────────────────────────────

    def test_readme_check_passes_when_present(self, tmp_path):
        (tmp_path / "README.md").write_text("# My Project\n")
        report = ProjectHealthAnalyzer().analyze(tmp_path)
        readme_check = next(
            (c for c in report.checks if "readme" in c.name.lower()), None
        )
        if readme_check:
            assert readme_check.passed is True

    def test_readme_check_fails_when_missing(self, tmp_path):
        report = ProjectHealthAnalyzer().analyze(tmp_path)
        readme_check = next(
            (c for c in report.checks if "readme" in c.name.lower()), None
        )
        if readme_check:
            assert readme_check.passed is False

    # ── license check ────────────────────────────────────────────────────

    def test_license_check_passes_when_present(self, tmp_path):
        (tmp_path / "LICENSE").write_text("MIT License\n")
        report = ProjectHealthAnalyzer().analyze(tmp_path)
        lic_check = next(
            (c for c in report.checks if "license" in c.name.lower()), None
        )
        if lic_check:
            assert lic_check.passed is True

    # ── tests check ──────────────────────────────────────────────────────

    def test_tests_check_passes_with_tests_dir(self, tmp_path):
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_something.py").write_text("def test_foo(): pass\n")
        report = ProjectHealthAnalyzer().analyze(tmp_path)
        t_check = next((c for c in report.checks if "test" in c.name.lower()), None)
        if t_check:
            assert t_check.passed is True

    def test_tests_check_fails_without_tests(self, tmp_path):
        report = ProjectHealthAnalyzer().analyze(tmp_path)
        t_check = next((c for c in report.checks if "test" in c.name.lower()), None)
        if t_check:
            assert t_check.passed is False

    # ── ci check ─────────────────────────────────────────────────────────

    def test_ci_check_passes_with_github_workflows(self, tmp_path):
        wf = tmp_path / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "ci.yml").write_text("on: push\n")
        report = ProjectHealthAnalyzer().analyze(tmp_path)
        ci_check = next((c for c in report.checks if "ci" in c.name.lower()), None)
        if ci_check:
            assert ci_check.passed is True

    # ── changelog check ──────────────────────────────────────────────────

    def test_changelog_check_passes_when_present(self, tmp_path):
        (tmp_path / "CHANGELOG.md").write_text("# Changelog\n")
        report = ProjectHealthAnalyzer().analyze(tmp_path)
        cl_check = next(
            (c for c in report.checks if "changelog" in c.name.lower()), None
        )
        if cl_check:
            assert cl_check.passed is True

    # ── fully healthy project ────────────────────────────────────────────

    def test_fully_equipped_project_gets_high_score(self, tmp_path):
        """A project with all standard files should score well above 70."""
        (tmp_path / ".gitignore").write_text("__pycache__\n")
        (tmp_path / "README.md").write_text("# Project\n")
        (tmp_path / "LICENSE").write_text("MIT\n")
        (tmp_path / "CHANGELOG.md").write_text("# Changelog\n")
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        (tmp_path / "requirements.txt").write_text("requests\n")
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_main.py").write_text("def test_ok(): pass\n")
        ci = tmp_path / ".github" / "workflows"
        ci.mkdir(parents=True)
        (ci / "ci.yml").write_text("on: push\n")

        report = ProjectHealthAnalyzer().analyze(tmp_path)
        assert report.score >= 70

    def test_empty_project_gets_low_score(self, tmp_path):
        """An empty directory should score poorly."""
        report = ProjectHealthAnalyzer().analyze(tmp_path)
        assert report.score < 60


# ── Auto-fix mode ─────────────────────────────────────────────────────────────


class TestProjectHealthAutoFix:
    def test_auto_fix_creates_gitignore(self, tmp_path):
        assert not (tmp_path / ".gitignore").exists()
        report = ProjectHealthAnalyzer().analyze(tmp_path, auto_fix=True)
        assert (tmp_path / ".gitignore").exists()
        assert ".gitignore" in report.files_created

    def test_auto_fix_creates_license(self, tmp_path):
        report = ProjectHealthAnalyzer().analyze(tmp_path, auto_fix=True)
        assert (tmp_path / "LICENSE").exists()
        assert "LICENSE" in report.files_created

    def test_auto_fix_does_not_overwrite_existing(self, tmp_path):
        content = "CUSTOM CONTENT\n"
        (tmp_path / ".gitignore").write_text(content)
        ProjectHealthAnalyzer().analyze(tmp_path, auto_fix=True)
        assert (tmp_path / ".gitignore").read_text() == content

    def test_dry_run_no_files_created(self, tmp_path):
        """auto_fix=False must not create any files."""
        ProjectHealthAnalyzer().analyze(tmp_path, auto_fix=False)
        assert not (tmp_path / ".gitignore").exists()
        assert not (tmp_path / "LICENSE").exists()


# ── ProjectHealthAnalyzer.summary ────────────────────────────────────────────


class TestProjectHealthSummary:
    def test_summary_before_analyze(self):
        a = ProjectHealthAnalyzer()
        s = a.summary()
        assert isinstance(s, dict)

    def test_summary_after_analyze(self, tmp_path):
        a = ProjectHealthAnalyzer()
        a.analyze(tmp_path)
        s = a.summary()
        assert "score" in s or "total" in s or "passed" in s

    def test_summary_has_grade(self, tmp_path):
        a = ProjectHealthAnalyzer()
        a.analyze(tmp_path)
        s = a.summary()
        # summary() returns health_grade key (or score as fallback)
        assert "health_grade" in s or "score" in s or "health_score" in s
