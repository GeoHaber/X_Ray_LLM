"""tests/test_release_readiness_integration.py — Core integration + UI tab tests."""

from pathlib import Path
from unittest.mock import MagicMock
from types import SimpleNamespace



# ═══════════════════════════════════════════════════════════════════════
#  SECTION 1 — CLI argument wiring
# ═══════════════════════════════════════════════════════════════════════

class TestCLIArgs:
    """Verify --release-ready flag is wired correctly."""

    def test_full_scan_enables_release_ready(self):
        from Core.cli_args import normalize_scan_args

        args = SimpleNamespace(
            full_scan=True, smell=False, duplicates=False, lint=False,
            security=False, rustify=False, web=False, health=False,
            typecheck=False, format=False, release_ready=False,
        )
        normalize_scan_args(args)
        assert args.release_ready is True

    def test_release_ready_standalone_counts_as_specific(self):
        from Core.cli_args import normalize_scan_args

        args = SimpleNamespace(
            full_scan=False, smell=False, duplicates=False, lint=False,
            security=False, rustify=False, web=False, health=False,
            typecheck=False, format=False, release_ready=True,
        )
        normalize_scan_args(args)
        # smell/lint/security should NOT be auto-enabled
        assert args.smell is False

    def test_no_flags_defaults_do_not_enable_release_ready(self):
        from Core.cli_args import normalize_scan_args

        args = SimpleNamespace(
            full_scan=False, smell=False, duplicates=False, lint=False,
            security=False, rustify=False, web=False, health=False,
            typecheck=False, format=False, release_ready=False,
        )
        normalize_scan_args(args)
        # Default behaviour: smell + lint + security, NOT release_ready
        assert args.release_ready is False


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 2 — scan_phases integration
# ═══════════════════════════════════════════════════════════════════════

class TestScanPhasesIntegration:
    """Verify `run_release_readiness_phase` returns a valid analyzer."""

    def test_phase_returns_analyzer_with_report(self, tmp_path):
        (tmp_path / "app.py").write_text(
            '"""Module."""\ndef run(): pass\n# TODO: finish\n'
        )
        (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.1.0"\n')
        (tmp_path / "requirements.txt").write_text("click==8.0.0\n")

        from Core.scan_phases import run_release_readiness_phase

        analyzer = run_release_readiness_phase(tmp_path)
        assert analyzer is not None
        assert analyzer.report is not None
        assert 0 <= analyzer.report.score <= 100

    def test_summary_dict_has_expected_keys(self, tmp_path):
        (tmp_path / "main.py").write_text("def hello(): pass\n")
        from Core.scan_phases import run_release_readiness_phase

        analyzer = run_release_readiness_phase(tmp_path)
        s = analyzer.summary()
        expected_keys = {
            "total", "critical", "warning", "info", "markers",
            "markers_by_kind", "docstring_coverage_pct", "docstring_total",
            "docstring_documented", "docstring_gaps", "vulnerabilities",
            "dep_audit_available", "versions_consistent", "version_sources",
            "unpinned_deps", "orphan_modules", "score", "grade",
        }
        assert expected_keys.issubset(set(s.keys()))


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 3 — Reporting integration
# ═══════════════════════════════════════════════════════════════════════

class TestReporting:
    """Verify the reporting printer works with release readiness data."""

    def test_print_release_readiness_report_runs(self, tmp_path):
        (tmp_path / "a.py").write_text("# TODO: x\ndef f(): pass\n")
        from Analysis.release_readiness import ReleaseReadinessAnalyzer
        from Analysis.reporting import print_release_readiness_report

        analyzer = ReleaseReadinessAnalyzer()
        report = analyzer.analyze(tmp_path)
        summary = analyzer.summary()
        # Should not raise
        print_release_readiness_report(report, summary)

    def test_release_readiness_penalty_rule_exists(self):
        from Analysis.reporting import _PENALTY_RULES

        keys = [r[0] for r in _PENALTY_RULES]
        assert "release_readiness" in keys


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 4 — Checklist edge cases
# ═══════════════════════════════════════════════════════════════════════

class TestChecklistEdgeCases:
    """Extended checklist tests beyond test_release_readiness.py."""

    def _base_results(self, **overrides):
        r = {
            "grade": {"score": 90, "letter": "A"},
            "security": {"critical": 0},
            "smells": {"critical": 0},
            "lint": {"critical": 0},
            "typecheck": {"critical": 0},
            "release_readiness": {
                "markers_by_kind": {},
                "docstring_coverage_pct": 80.0,
                "docstring_documented": 80,
                "docstring_total": 100,
                "vulnerabilities": 0,
                "dep_audit_available": True,
                "versions_consistent": True,
                "version_sources": [{"source": "config.py", "version": "1.0.0"}],
                "unpinned_deps": 0,
                "orphan_modules": 0,
            },
        }
        for k, v in overrides.items():
            if isinstance(v, dict) and k in r:
                r[k].update(v)
            else:
                r[k] = v
        return r

    def test_go_when_all_pass(self):
        from Analysis.release_checklist import generate_checklist

        c = generate_checklist(self._base_results())
        assert c.go is True
        assert c.blockers == 0

    def test_no_go_on_low_grade(self):
        from Analysis.release_checklist import generate_checklist

        c = generate_checklist(
            self._base_results(grade={"score": 30, "letter": "D"})
        )
        assert c.go is False

    def test_no_go_on_nocommit(self):
        from Analysis.release_checklist import generate_checklist

        r = self._base_results()
        r["release_readiness"]["markers_by_kind"] = {"NOCOMMIT": 1}
        c = generate_checklist(r)
        assert c.go is False

    def test_health_check_included(self):
        from Analysis.release_checklist import generate_checklist

        r = self._base_results()
        r["health"] = {"score": 90}
        c = generate_checklist(r)
        labels = [i.label for i in c.items]
        assert any("health" in l.lower() for l in labels)

    def test_health_check_warns_if_low(self):
        from Analysis.release_checklist import generate_checklist

        r = self._base_results()
        r["health"] = {"score": 40}
        c = generate_checklist(r)
        health_item = [i for i in c.items if "health" in i.label.lower()][0]
        assert health_item.passed is False
        assert health_item.severity == "warning"

    def test_pip_audit_not_available_shows_info(self):
        from Analysis.release_checklist import generate_checklist

        r = self._base_results()
        r["release_readiness"]["dep_audit_available"] = False
        c = generate_checklist(r)
        audit_item = [i for i in c.items if "audit" in i.label.lower() or "CVE" in i.label][0]
        assert audit_item.severity == "info"

    def test_custom_min_grade(self):
        from Analysis.release_checklist import generate_checklist

        r = self._base_results(grade={"score": 75, "letter": "B-"})
        # With min_grade="A", B- should fail
        c = generate_checklist(r, min_grade="A")
        assert c.go is False

    def test_custom_min_docstring_pct(self):
        from Analysis.release_checklist import generate_checklist

        r = self._base_results()
        r["release_readiness"]["docstring_coverage_pct"] = 50.0
        c = generate_checklist(r, min_docstring_pct=60.0)
        doc_item = [i for i in c.items if "docstring" in i.label.lower()][0]
        assert doc_item.passed is False


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 5 — Flet phase & tab registration
# ═══════════════════════════════════════════════════════════════════════

class TestFletRegistration:
    """Verify release readiness is properly registered in x_ray_flet."""

    def test_phase_registry_has_release_readiness(self):
        from x_ray_flet import PHASE_REGISTRY

        keys = [k for k, _ in PHASE_REGISTRY]
        assert "release_readiness" in keys

    def test_tab_builders_has_release_readiness(self):
        from x_ray_flet import _TAB_BUILDERS

        keys = [k for k, _, _ in _TAB_BUILDERS]
        assert "release_readiness" in keys

    def test_init_state_has_release_readiness_mode(self):
        page = MagicMock()
        page.data = None

        from x_ray_flet import _init_state

        state = _init_state(page)
        assert "release_readiness" in state["modes"]
        assert state["modes"]["release_readiness"] is True


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 6 — Tab builder unit tests
# ═══════════════════════════════════════════════════════════════════════

class TestReleaseReadinessTab:
    """Unit tests for the release readiness Flet tab."""

    def _mock_results(self):
        return {
            "release_readiness": {
                "score": 85.0,
                "grade": "B+",
                "markers": 3,
                "markers_by_kind": {"TODO": 2, "FIXME": 1},
                "docstring_coverage_pct": 72.5,
                "docstring_total": 40,
                "docstring_documented": 29,
                "docstring_gaps": 11,
                "vulnerabilities": 0,
                "dep_audit_available": True,
                "versions_consistent": True,
                "version_sources": [
                    {"source": "pyproject.toml", "version": "1.0.0"},
                    {"source": "config.py", "version": "1.0.0"},
                ],
                "unpinned_deps": 2,
                "orphan_modules": 1,
                "total": 6,
                "critical": 0,
                "warning": 3,
                "info": 3,
            },
            "release_checklist": {
                "go": True,
                "blockers": 0,
                "warnings": 1,
                "items": [
                    {"label": "Overall grade ≥ B", "passed": True, "detail": "", "severity": ""},
                    {"label": "No critical security issues", "passed": True, "detail": "", "severity": ""},
                    {"label": "FIXME/HACK markers reviewed", "passed": False, "detail": "1 FIXME/HACK", "severity": "warning"},
                ],
            },
            "_release_markers_detail": [
                {"kind": "TODO", "file_path": "app.py", "line": 5, "text": "# TODO: fix", "severity": "info"},
                {"kind": "FIXME", "file_path": "app.py", "line": 10, "text": "# FIXME: broken", "severity": "warning"},
            ],
        }

    def test_tab_returns_control(self):
        import flet as ft
        from UI.tabs.release_readiness_tab import _build_release_readiness_tab

        page = MagicMock(spec=ft.Page)
        result = _build_release_readiness_tab(self._mock_results(), page)
        assert isinstance(result, ft.Control)

    def test_tab_empty_results_returns_placeholder(self):
        import flet as ft
        from UI.tabs.release_readiness_tab import _build_release_readiness_tab

        page = MagicMock(spec=ft.Page)
        result = _build_release_readiness_tab({}, page)
        assert isinstance(result, ft.Container)

    def test_tab_handles_no_checklist(self):
        import flet as ft
        from UI.tabs.release_readiness_tab import _build_release_readiness_tab

        results = {
            "release_readiness": {
                "score": 90.0,
                "grade": "A",
                "markers": 0,
                "markers_by_kind": {},
                "docstring_coverage_pct": 100.0,
                "docstring_total": 10,
                "docstring_documented": 10,
                "vulnerabilities": 0,
                "dep_audit_available": False,
                "versions_consistent": True,
                "version_sources": [],
                "unpinned_deps": 0,
                "orphan_modules": 0,
            },
        }
        page = MagicMock(spec=ft.Page)
        result = _build_release_readiness_tab(results, page)
        assert isinstance(result, ft.Control)

    def test_tab_no_go_verdict(self):
        import flet as ft
        from UI.tabs.release_readiness_tab import _build_release_readiness_tab

        results = self._mock_results()
        results["release_checklist"]["go"] = False
        results["release_checklist"]["blockers"] = 2

        page = MagicMock(spec=ft.Page)
        result = _build_release_readiness_tab(results, page)
        assert isinstance(result, ft.ListView)

    def test_tab_with_marker_detail(self):
        import flet as ft
        from UI.tabs.release_readiness_tab import _build_release_readiness_tab

        results = self._mock_results()
        page = MagicMock(spec=ft.Page)
        result = _build_release_readiness_tab(results, page)
        # Should be a full ListView (not the empty placeholder)
        assert isinstance(result, ft.ListView)

    def test_tab_with_version_mismatch(self):
        import flet as ft
        from UI.tabs.release_readiness_tab import _build_release_readiness_tab

        results = self._mock_results()
        results["release_readiness"]["versions_consistent"] = False
        results["release_readiness"]["version_sources"] = [
            {"source": "pyproject.toml", "version": "1.0.0"},
            {"source": "config.py", "version": "2.0.0"},
        ]

        page = MagicMock(spec=ft.Page)
        result = _build_release_readiness_tab(results, page)
        assert isinstance(result, ft.ListView)


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 7 — Flet _phase_release_readiness integration
# ═══════════════════════════════════════════════════════════════════════

class TestFletPhaseFunction:
    """Test the _phase_release_readiness function in x_ray_flet."""

    def test_phase_populates_results(self, tmp_path):
        (tmp_path / "app.py").write_text("def run(): pass\n# TODO: x\n")
        (tmp_path / "requirements.txt").write_text("requests==2.31.0\n")

        from x_ray_flet import _phase_release_readiness

        results = {"_functions": [], "_classes": []}
        _phase_release_readiness(tmp_path, [], results)

        assert "release_readiness" in results
        assert "release_checklist" in results
        assert isinstance(results["release_readiness"].get("score"), (int, float))

    def test_phase_handles_exceptions(self, tmp_path):
        from x_ray_flet import _phase_release_readiness

        results = {}
        # Pass a non-existent path to trigger error handling
        _phase_release_readiness(Path("/nonexistent/path/xyz"), [], results)
        assert "release_readiness" in results
        # Either error dict or valid results (depending on how gracefully it handles)
