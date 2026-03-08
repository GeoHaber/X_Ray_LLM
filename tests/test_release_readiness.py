"""tests/test_release_readiness.py — Tests for the release readiness analyzer."""

import textwrap

import pytest

from Analysis.release_readiness import ReleaseReadinessAnalyzer
from Analysis.release_checklist import generate_checklist, format_checklist


# ── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_project(tmp_path):
    """Create a minimal Python project for testing."""
    # config.py with version
    (tmp_path / "config.py").write_text('__version__ = "1.0.0"\n')

    # pyproject.toml with same version
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.0.0"\n')

    # requirements.txt with pinned deps
    (tmp_path / "requirements.txt").write_text("requests==2.31.0\nflask==3.0.0\n")

    # A module with docstrings
    (tmp_path / "good_module.py").write_text(textwrap.dedent('''\
        """Module docstring."""

        def greet(name: str) -> str:
            """Say hello."""
            return f"Hello {name}"

        class Greeter:
            """A greeter class."""
            pass
    '''))

    # A module with TODOs and no docstrings
    (tmp_path / "bad_module.py").write_text(textwrap.dedent('''\
        # TODO: clean this up
        # FIXME: this is broken
        # NOCOMMIT: debug stuff

        def frobnicate(x):
            return x * 2

        class Widget:
            pass
    '''))

    # __init__.py
    (tmp_path / "__init__.py").write_text("")

    return tmp_path


# ── Marker scanner tests ────────────────────────────────────────────────

def test_finds_todo_fixme_nocommit(tmp_project):
    analyzer = ReleaseReadinessAnalyzer()
    report = analyzer.analyze(tmp_project)

    kinds = {m.kind for m in report.markers}
    assert "TODO" in kinds
    assert "FIXME" in kinds
    assert "NOCOMMIT" in kinds


def test_marker_count(tmp_project):
    analyzer = ReleaseReadinessAnalyzer()
    report = analyzer.analyze(tmp_project)
    assert len(report.markers) == 3  # TODO + FIXME + NOCOMMIT


def test_marker_severity(tmp_project):
    analyzer = ReleaseReadinessAnalyzer()
    report = analyzer.analyze(tmp_project)

    nocommit = [m for m in report.markers if m.kind == "NOCOMMIT"]
    assert nocommit[0].severity == "critical"

    fixme = [m for m in report.markers if m.kind == "FIXME"]
    assert fixme[0].severity == "warning"

    todo = [m for m in report.markers if m.kind == "TODO"]
    assert todo[0].severity == "info"


# ── Docstring coverage tests ────────────────────────────────────────────

def test_docstring_coverage(tmp_project):
    analyzer = ReleaseReadinessAnalyzer()
    report = analyzer.analyze(tmp_project)

    # good_module has 2 documented (greet, Greeter)
    # bad_module has 2 undocumented (frobnicate, Widget)
    assert report.docstring_total == 4
    assert report.docstring_documented == 2
    assert len(report.docstring_gaps) == 2


def test_docstring_skips_private(tmp_project):
    (tmp_project / "private_stuff.py").write_text(
        "def _internal(): pass\nclass _Hidden: pass\n"
    )
    analyzer = ReleaseReadinessAnalyzer()
    report = analyzer.analyze(tmp_project)
    # Private names (starting with _) should not affect counts
    private_gaps = [g for g in report.docstring_gaps if g.name.startswith("_")]
    assert len(private_gaps) == 0


# ── Version consistency tests ────────────────────────────────────────────

def test_versions_consistent(tmp_project):
    analyzer = ReleaseReadinessAnalyzer()
    report = analyzer.analyze(tmp_project)
    assert report.versions_consistent is True
    assert len(report.version_sources) == 2  # config.py + pyproject.toml


def test_versions_mismatch(tmp_project):
    (tmp_project / "config.py").write_text('__version__ = "2.0.0"\n')
    analyzer = ReleaseReadinessAnalyzer()
    report = analyzer.analyze(tmp_project)
    assert report.versions_consistent is False


# ── Dependency pinning tests ─────────────────────────────────────────────

def test_pinned_deps(tmp_project):
    analyzer = ReleaseReadinessAnalyzer()
    report = analyzer.analyze(tmp_project)
    assert len(report.unpinned_deps) == 0  # both are ==


def test_unpinned_deps(tmp_project):
    (tmp_project / "requirements.txt").write_text("requests>=2.0\nflask\n")
    analyzer = ReleaseReadinessAnalyzer()
    report = analyzer.analyze(tmp_project)
    assert len(report.unpinned_deps) == 2


# ── Orphan module tests ─────────────────────────────────────────────────

def test_orphan_detection(tmp_project):
    # good_module and bad_module are not imported anywhere → orphans
    analyzer = ReleaseReadinessAnalyzer()
    report = analyzer.analyze(tmp_project)
    orphan_paths = {o.file_path for o in report.orphan_modules}
    assert "good_module.py" in orphan_paths
    assert "bad_module.py" in orphan_paths


def test_non_orphan(tmp_project):
    # Make a module that imports good_module
    (tmp_project / "main.py").write_text("import good_module\nimport bad_module\n")
    analyzer = ReleaseReadinessAnalyzer()
    report = analyzer.analyze(tmp_project)
    orphan_paths = {o.file_path for o in report.orphan_modules}
    assert "good_module.py" not in orphan_paths
    assert "bad_module.py" not in orphan_paths


# ── Summary and scoring tests ───────────────────────────────────────────

def test_summary_keys(tmp_project):
    analyzer = ReleaseReadinessAnalyzer()
    analyzer.analyze(tmp_project)
    s = analyzer.summary()

    assert "total" in s
    assert "critical" in s
    assert "warning" in s
    assert "info" in s
    assert "markers" in s
    assert "docstring_coverage_pct" in s
    assert "versions_consistent" in s
    assert "unpinned_deps" in s
    assert "orphan_modules" in s
    assert "score" in s
    assert "grade" in s


def test_score_range(tmp_project):
    analyzer = ReleaseReadinessAnalyzer()
    report = analyzer.analyze(tmp_project)
    assert 0.0 <= report.score <= 100.0


# ── Release checklist tests ─────────────────────────────────────────────

def test_checklist_generation():
    """Test checklist with mock results."""
    results = {
        "grade": {"score": 92, "letter": "A"},
        "security": {"critical": 0},
        "smells": {"critical": 0},
        "lint": {"critical": 0},
        "typecheck": {"critical": 0},
        "release_readiness": {
            "markers_by_kind": {"TODO": 2},
            "docstring_coverage_pct": 80.0,
            "docstring_documented": 80,
            "docstring_total": 100,
            "vulnerabilities": 0,
            "dep_audit_available": False,
            "versions_consistent": True,
            "version_sources": [{"source": "config.py", "version": "1.0.0"}],
            "unpinned_deps": 0,
            "orphan_modules": 0,
        },
    }
    checklist = generate_checklist(results)
    assert checklist.go is True  # no blockers
    assert checklist.blockers == 0


def test_checklist_blocks_on_critical_security():
    results = {
        "grade": {"score": 50, "letter": "D"},
        "security": {"critical": 3},
        "smells": {"critical": 0},
        "lint": {"critical": 0},
        "typecheck": {"critical": 0},
        "release_readiness": {
            "markers_by_kind": {"NOCOMMIT": 1},
            "docstring_coverage_pct": 10.0,
            "docstring_documented": 10,
            "docstring_total": 100,
            "vulnerabilities": 5,
            "dep_audit_available": True,
            "versions_consistent": False,
            "version_sources": [
                {"source": "config.py", "version": "1.0.0"},
                {"source": "pyproject.toml", "version": "2.0.0"},
            ],
            "unpinned_deps": 10,
            "orphan_modules": 5,
        },
    }
    checklist = generate_checklist(results)
    assert checklist.go is False
    assert checklist.blockers >= 3  # grade, security, NOCOMMIT, vulns


def test_checklist_format_output():
    results = {
        "grade": {"score": 95, "letter": "A"},
        "security": {"critical": 0},
        "smells": {"critical": 0},
        "lint": {"critical": 0},
        "typecheck": {"critical": 0},
        "release_readiness": {
            "markers_by_kind": {},
            "docstring_coverage_pct": 90.0,
            "docstring_documented": 90,
            "docstring_total": 100,
            "vulnerabilities": 0,
            "dep_audit_available": True,
            "versions_consistent": True,
            "version_sources": [{"source": "config.py", "version": "1.0.0"}],
            "unpinned_deps": 0,
            "orphan_modules": 0,
        },
    }
    checklist = generate_checklist(results)
    output = format_checklist(checklist)
    assert "RELEASE READINESS" in output
    assert "GO" in output
