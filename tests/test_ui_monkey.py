"""
tests/test_ui_monkey.py
=======================
Headless "monkey" test for the shell_v2 navigation.

Calls every section builder and sub-tab builder with a realistic mock
scan result, exercising the full navigation tree WITHOUT starting a Flet
server.  Any missing-argument or AttributeError crashes surface here
before the user clicks on them in the live app.

Run from the X_Ray root:
    python -m pytest tests/test_ui_monkey.py -v
"""

from __future__ import annotations
from unittest.mock import MagicMock
from typing import Any, Dict


# ── Minimal mock page ─────────────────────────────────────────────────────────


def _mock_page() -> MagicMock:
    page = MagicMock()
    page.update = MagicMock()
    page.overlay = []
    page.data = {}
    return page


# ── Realistic minimal scan result ─────────────────────────────────────────────


def _fake_results() -> Dict[str, Any]:
    from Core.types import FunctionRecord, SmellIssue, Severity

    func = FunctionRecord(
        name="fake_fn",
        file_path="fake.py",
        line_start=1,
        line_end=10,
        complexity=3,
        nesting_depth=1,
        parameters=[],
        docstring="doc",
        code="def fake_fn(): pass",
        size_lines=10,
        return_type=None,
        decorators=[],
        calls_to=[],
        code_hash="abc",
        structure_hash="xyz",
    )
    smell = SmellIssue(
        file_path="fake.py",
        line=1,
        end_line=5,
        category="long-function",
        severity=Severity.WARNING,
        name="fake_fn",
        metric_value=10,
        message="Too long",
        suggestion="Split it",
    )
    return {
        "grade": {
            "letter": "B",
            "score": 72.0,
            "label": "Good",
            "breakdown": {"quality": 70, "security": 80, "maintainability": 66},
        },
        "meta": {"files": 106, "functions": 820, "classes": 45, "duration": 12.3},
        "smells": {"critical": 2, "warning": 5, "info": 10, "total": 17, "error": None},
        "_smell_issues": [smell],
        "duplicates": {"groups": 3, "total_lines": 90, "error": None},
        "_dup_groups": [],
        "lint": {"total": 22, "by_code": {}, "error": None},
        "_lint_issues": [],
        "security": {"critical": 1, "warning": 3, "info": 2, "total": 6, "error": None},
        "_sec_issues": [],
        "rustify": {"total_scored": 50, "pure_count": 12, "top_score": 88},
        "_rust_candidates": [],
        "_functions": [func],
        "_scan_path": r"C:\fake\project",
        "_gate": {"passed": True, "score": 74, "violations": [], "badge": "✅"},
        "_diagrams": {},
        "_satd": {"total": 5},
    }


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestShellV2Sections:
    """Exercise every public section builder in shell_v2."""

    def setup_method(self):
        self.page = _mock_page()
        self.results = _fake_results()
        self.state = {
            "root_path": r"C:\fake\project",
            "recent_paths": [r"C:\fake\project"],
            "modes": {"smells": True, "lint": True},
            "results": self.results,
        }

    # ── Home ──────────────────────────────────────────────────────────────────

    def test_home_no_results(self):
        from UI.shell_v2 import build_home_section

        ctrl = build_home_section(
            self.state, MagicMock(), MagicMock(), MagicMock(), results=None
        )
        assert ctrl is not None

    def test_home_with_results(self):
        from UI.shell_v2 import build_home_section

        ctrl = build_home_section(
            self.state, MagicMock(), MagicMock(), MagicMock(), results=self.results
        )
        assert ctrl is not None

    # ── Overview ──────────────────────────────────────────────────────────────

    def test_overview_section(self):
        from UI.shell_v2 import build_overview_section

        ctrl = build_overview_section(self.results, self.page)
        assert ctrl is not None

    def test_overview_no_gate(self):
        from UI.shell_v2 import build_overview_section

        results = dict(self.results)
        results["_gate"] = {}
        ctrl = build_overview_section(results, self.page)
        assert ctrl is not None

    # ── Issues ────────────────────────────────────────────────────────────────

    def test_issues_section(self):
        from UI.shell_v2 import build_issues_section

        ctrl = build_issues_section(self.results, self.page)
        assert ctrl is not None

    def test_issues_empty(self):
        from UI.shell_v2 import build_issues_section

        ctrl = build_issues_section({}, self.page)
        assert ctrl is not None

    # ── Architecture ──────────────────────────────────────────────────────────

    def test_arch_section(self):
        from UI.shell_v2 import build_arch_section

        ctrl = build_arch_section(self.results, self.page)
        assert ctrl is not None

    def test_arch_no_data(self):
        from UI.shell_v2 import build_arch_section

        ctrl = build_arch_section({}, self.page)
        assert ctrl is not None

    # ── Actions ───────────────────────────────────────────────────────────────

    def test_actions_section(self):
        from UI.shell_v2 import build_actions_section

        ctrl = build_actions_section(self.results, self.page)
        assert ctrl is not None

    def test_actions_no_data(self):
        from UI.shell_v2 import build_actions_section

        ctrl = build_actions_section({}, self.page)
        assert ctrl is not None

    # ── Settings ──────────────────────────────────────────────────────────────

    def test_settings_section(self):
        from UI.shell_v2 import build_settings_section

        ctrl = build_settings_section(self.state, self.page, self.results)
        assert ctrl is not None

    def test_settings_no_results(self):
        from UI.shell_v2 import build_settings_section

        ctrl = build_settings_section(self.state, self.page, None)
        assert ctrl is not None

    # ── Left rail ─────────────────────────────────────────────────────────────

    def test_left_rail_no_results(self):
        from UI.shell_v2 import build_left_rail

        rail = build_left_rail("home", lambda s: None, results=None)
        assert rail is not None

    def test_left_rail_with_results(self):
        from UI.shell_v2 import build_left_rail

        rail = build_left_rail("overview", lambda s: None, results=self.results)
        assert rail is not None

    # ── Full shell ────────────────────────────────────────────────────────────

    def test_full_shell_no_results(self):
        from UI.shell_v2 import build_shell_v2

        shell = build_shell_v2(
            page=self.page,
            state=self.state,
            on_scan=MagicMock(),
            on_pick_dir=MagicMock(),
            on_apply_path=MagicMock(),
            results=None,
        )
        assert shell is not None

    def test_full_shell_with_results(self):
        from UI.shell_v2 import build_shell_v2

        shell = build_shell_v2(
            page=self.page,
            state=self.state,
            on_scan=MagicMock(),
            on_pick_dir=MagicMock(),
            on_apply_path=MagicMock(),
            results=self.results,
        )
        assert shell is not None


class TestIndividualTabBuilders:
    """Directly exercise every tab builder with correct argument counts."""

    def setup_method(self):
        self.page = _mock_page()
        self.results = _fake_results()

    def test_smells_tab(self):
        from UI.tabs.smells_tab import _build_smells_tab

        ctrl = _build_smells_tab(self.results)
        assert ctrl is not None

    def test_duplicates_tab(self):
        from UI.tabs.duplicates_tab import _build_duplicates_tab

        ctrl = _build_duplicates_tab(self.results)
        assert ctrl is not None

    def test_lint_tab(self):
        from UI.tabs.lint_tab import _build_lint_tab
        import inspect

        sig = inspect.signature(_build_lint_tab)
        params = list(sig.parameters)
        # Call with correct arity
        if "page" in params:
            ctrl = _build_lint_tab(self.results, self.page)
        else:
            ctrl = _build_lint_tab(self.results)
        assert ctrl is not None

    def test_security_tab(self):
        from UI.tabs.security_tab import _build_security_tab

        ctrl = _build_security_tab(self.results)
        assert ctrl is not None

    def test_graph_tab(self):
        from UI.tabs.graph_tab import _build_graph_tab

        ctrl = _build_graph_tab(self.results, self.page)
        assert ctrl is not None

    def test_heatmap_tab(self):
        from UI.tabs.heatmap_tab import _build_heatmap_tab

        ctrl = _build_heatmap_tab(self.results)
        assert ctrl is not None

    def test_complexity_tab(self):
        from UI.tabs.complexity_tab import _build_complexity_tab

        ctrl = _build_complexity_tab(self.results)
        assert ctrl is not None

    def test_diagrams_tab(self):
        from UI.tabs.diagrams_tab import _build_diagrams_tab

        ctrl = _build_diagrams_tab(self.results, self.page)
        assert ctrl is not None

    def test_auto_rustify_tab(self):
        from UI.tabs.auto_rustify_tab import _build_auto_rustify_tab

        ctrl = _build_auto_rustify_tab(self.results, self.page)
        assert ctrl is not None

    def test_nexus_tab(self):
        from UI.tabs.nexus_tab import _build_nexus_tab

        ctrl = _build_nexus_tab(self.results, self.page)
        assert ctrl is not None

    def test_rustify_tab(self):
        from UI.tabs.rustify_tab import _build_rustify_tab

        ctrl = _build_rustify_tab(self.results)
        assert ctrl is not None

    def test_debt_tab(self):
        from UI.tabs.debt_tab import _build_debt_tab

        ctrl = _build_debt_tab(self.results)
        assert ctrl is not None
