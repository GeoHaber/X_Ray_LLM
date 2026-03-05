"""
tests/test_ui_compat.py — Tests for the UI API Compatibility Analyzer
======================================================================

Validates that Analysis.ui_compat correctly:
  1. Extracts UI framework calls from Python AST
  2. Detects invalid keyword arguments
  3. Produces correct SmellIssue output
  4. Handles edge cases (star-kwargs, nested attrs, missing modules)
  5. Catches real-world Flet API mismatches
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import List

import pytest

from Analysis.ui_compat import (
    UICompatAnalyzer,
    UICompatIssue,
    _edit_distance,
    _extract_aliases,
    _UICallVisitor,
    _top_params,
)
from Core.types import SmellIssue, Severity


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_py(tmp_path: Path, code: str, name: str = "test_app.py") -> Path:
    """Write *code* to a temp .py file and return its path."""
    p = tmp_path / name
    p.write_text(textwrap.dedent(code), encoding="utf-8")
    return p


def _analyze_code(tmp_path: Path, code: str, extra_modules=None) -> List[UICompatIssue]:
    """Shortcut: write code, analyze, return issues."""
    p = _write_py(tmp_path, code)
    analyzer = UICompatAnalyzer(extra_modules=extra_modules or set())
    return analyzer.analyze(p)


# ---------------------------------------------------------------------------
# Unit tests — helpers
# ---------------------------------------------------------------------------


class TestEditDistance:
    def test_identical(self):
        assert _edit_distance("hello", "hello") == 0

    def test_single_insert(self):
        assert _edit_distance("abc", "abcd") == 1

    def test_single_delete(self):
        assert _edit_distance("abcd", "abc") == 1

    def test_substitution(self):
        assert _edit_distance("cat", "bat") == 1

    def test_empty(self):
        assert _edit_distance("", "abc") == 3

    def test_real_typo(self):
        # "conten" → "content" should be close
        assert _edit_distance("conten", "content") <= 2

    def test_tabs_vs_tab(self):
        assert _edit_distance("tabs", "tab") <= 2


class TestTopParams:
    def test_basic(self):
        params = frozenset(["alpha", "beta", "gamma"])
        result = _top_params(params, n=10)
        assert "alpha" in result
        assert "beta" in result
        assert "gamma" in result

    def test_truncation(self):
        params = frozenset([f"p{i}" for i in range(20)])
        result = _top_params(params, n=5)
        assert "more" in result

    def test_filters_private(self):
        params = frozenset(["_private", "public", "self"])
        result = _top_params(params, n=10)
        assert "_private" not in result
        assert "self" not in result
        assert "public" in result


# ---------------------------------------------------------------------------
# Unit tests — alias extraction
# ---------------------------------------------------------------------------


class TestExtractAliases:
    def test_import_as(self):
        import ast

        tree = ast.parse("import flet as ft")
        aliases = _extract_aliases(tree)
        assert aliases == {"ft": "flet"}

    def test_import_plain(self):
        import ast

        tree = ast.parse("import tkinter")
        aliases = _extract_aliases(tree)
        assert aliases == {"tkinter": "tkinter"}

    def test_multiple_imports(self):
        import ast

        tree = ast.parse("import flet as ft\nimport tkinter as tk")
        aliases = _extract_aliases(tree)
        assert aliases["ft"] == "flet"
        assert aliases["tk"] == "tkinter"

    def test_no_ui_import(self):
        import ast

        tree = ast.parse("import os\nimport json")
        aliases = _extract_aliases(tree)
        assert "os" in aliases
        assert "json" in aliases


# ---------------------------------------------------------------------------
# Unit tests — call visitor
# ---------------------------------------------------------------------------


class TestUICallVisitor:
    def test_simple_call(self):
        import ast

        code = "ft.Text('hello', size=14)"
        tree = ast.parse(code)
        v = _UICallVisitor({"ft": "flet"}, "test.py")
        v.visit(tree)
        assert len(v.calls) == 1
        c = v.calls[0]
        assert c.full_qual == "ft.Text"
        assert c.resolved_name == "flet.Text"
        assert c.kwargs_used == ["size"]
        assert c.positional_count == 1

    def test_nested_attr(self):
        import ast

        code = "ft.Padding.symmetric(vertical=10)"
        tree = ast.parse(code)
        v = _UICallVisitor({"ft": "flet"}, "test.py")
        v.visit(tree)
        assert len(v.calls) == 1
        c = v.calls[0]
        assert c.full_qual == "ft.Padding.symmetric"
        assert c.resolved_name == "flet.Padding.symmetric"
        assert c.is_method is True
        assert "vertical" in c.kwargs_used

    def test_ignores_non_ui(self):
        import ast

        code = "os.path.join('a', 'b')"
        tree = ast.parse(code)
        v = _UICallVisitor({"ft": "flet"}, "test.py")
        v.visit(tree)
        assert len(v.calls) == 0

    def test_multiple_kwargs(self):
        import ast

        code = "ft.Container(content=x, bgcolor='red', padding=10)"
        tree = ast.parse(code)
        v = _UICallVisitor({"ft": "flet"}, "test.py")
        v.visit(tree)
        assert len(v.calls) == 1
        assert set(v.calls[0].kwargs_used) == {"content", "bgcolor", "padding"}


# ---------------------------------------------------------------------------
# Integration — real Flet validation
# ---------------------------------------------------------------------------


class TestFletCompatValid:
    """Test valid Flet API calls for basic widgets."""

    @pytest.fixture(autouse=True)
    def _skip_no_flet(self):
        pytest.importorskip("flet")

    def test_valid_text_call(self, tmp_path):
        issues = _analyze_code(
            tmp_path,
            """
            import flet as ft
            t = ft.Text("hello", size=14, color="white", weight=ft.FontWeight.BOLD)
        """,
        )
        assert len(issues) == 0

    def test_valid_container_call(self, tmp_path):
        issues = _analyze_code(
            tmp_path,
            """
            import flet as ft
            c = ft.Container(content=ft.Text("x"), bgcolor="red",
                             padding=10, border_radius=8)
        """,
        )
        assert len(issues) == 0

    def test_valid_column_row(self, tmp_path):
        issues = _analyze_code(
            tmp_path,
            """
            import flet as ft
            col = ft.Column(controls=[], spacing=10, expand=True)
            row = ft.Row(controls=[], spacing=5, alignment=ft.MainAxisAlignment.CENTER)
        """,
        )
        assert len(issues) == 0

    def test_valid_button(self, tmp_path):
        issues = _analyze_code(
            tmp_path,
            """
            import flet as ft
            b = ft.Button("Click", on_click=lambda e: None,
                          bgcolor="blue", color="white")
        """,
        )
        assert len(issues) == 0

    def test_valid_snackbar(self, tmp_path):
        issues = _analyze_code(
            tmp_path,
            """
            import flet as ft
            s = ft.SnackBar(content=ft.Text("msg"), open=True)
        """,
        )
        assert len(issues) == 0

    def test_valid_dropdown(self, tmp_path):
        issues = _analyze_code(
            tmp_path,
            """
            import flet as ft
            d = ft.Dropdown(value="a", options=[])
        """,
        )
        assert len(issues) == 0

    def test_valid_checkbox(self, tmp_path):
        issues = _analyze_code(
            tmp_path,
            """
            import flet as ft
            c = ft.Checkbox(label="opt", value=True,
                            fill_color="blue", check_color="white")
        """,
        )
        assert len(issues) == 0

    def test_valid_alertdialog(self, tmp_path):
        issues = _analyze_code(
            tmp_path,
            """
            import flet as ft
            d = ft.AlertDialog(
                modal=True, title=ft.Text("T"),
                content=ft.Text("C"), actions=[])
        """,
        )
        assert len(issues) == 0


class TestFletCompatValidAdvanced:
    """Test valid Flet API calls for tabs, layout, and style utilities."""

    @pytest.fixture(autouse=True)
    def test_valid_tab_label_only(self, tmp_path):
        issues = _analyze_code(
            tmp_path,
            """
            import flet as ft
            t = ft.Tab(label="Hello", icon="icon")
        """,
        )
        assert len(issues) == 0

    def test_valid_tabbar(self, tmp_path):
        issues = _analyze_code(
            tmp_path,
            """
            import flet as ft
            tb = ft.TabBar(
                tabs=[ft.Tab(label="A")],
                label_color="white",
                indicator_color="blue",
                divider_color="grey",
            )
        """,
        )
        assert len(issues) == 0

    def test_valid_tabs_new_api(self, tmp_path):
        issues = _analyze_code(
            tmp_path,
            """
            import flet as ft
            tabs = ft.Tabs(
                content=ft.Row([ft.Tab(label="A")]),
                length=1,
                selected_index=0,
                animation_duration=300,
            )
        """,
        )
        assert len(issues) == 0

    def test_valid_expansion_tile(self, tmp_path):
        issues = _analyze_code(
            tmp_path,
            """
            import flet as ft
            e = ft.ExpansionTile(
                title=ft.Text("T"),
                controls=[ft.Text("body")],
                expanded=False)
        """,
        )
        assert len(issues) == 0

    def test_valid_navigation_drawer(self, tmp_path):
        issues = _analyze_code(
            tmp_path,
            """
            import flet as ft
            d = ft.NavigationDrawer(
                controls=[ft.Text("x")],
                selected_index=0)
        """,
        )
        assert len(issues) == 0

    def test_valid_padding_symmetric(self, tmp_path):
        issues = _analyze_code(
            tmp_path,
            """
            import flet as ft
            p = ft.Padding.symmetric(vertical=10, horizontal=5)
        """,
        )
        assert len(issues) == 0

    def test_valid_border_only(self, tmp_path):
        issues = _analyze_code(
            tmp_path,
            """
            import flet as ft
            b = ft.Border.only(left=ft.BorderSide(2, "red"))
        """,
        )
        assert len(issues) == 0

    def test_valid_colors_with_opacity(self, tmp_path):
        issues = _analyze_code(
            tmp_path,
            """
            import flet as ft
            c = ft.Colors.with_opacity(0.15, "red")
        """,
        )
        assert len(issues) == 0

    # ── INVALID calls — must be caught ────────────────────────────────


class TestFletCompatInvalid:
    """Test invalid Flet API calls and edge cases."""

    @pytest.fixture(autouse=True)
    def test_expansion_tile_initially_expanded_invalid(self, tmp_path):
        """initially_expanded was renamed to expanded in newer Flet."""
        issues = _analyze_code(
            tmp_path,
            """
            import flet as ft
            e = ft.ExpansionTile(
                title=ft.Text("T"),
                initially_expanded=False)
        """,
        )
        assert len(issues) == 1
        assert issues[0].bad_kwarg == "initially_expanded"

    def test_tab_content_invalid(self, tmp_path):
        """ft.Tab does NOT accept content= in new Flet."""
        issues = _analyze_code(
            tmp_path,
            """
            import flet as ft
            t = ft.Tab(label="X", content=ft.Text("body"))
        """,
        )
        assert len(issues) == 1
        assert issues[0].bad_kwarg == "content"

    def test_tab_text_invalid(self, tmp_path):
        """ft.Tab uses 'label', not 'text'."""
        issues = _analyze_code(
            tmp_path,
            """
            import flet as ft
            t = ft.Tab(text="X")
        """,
        )
        assert len(issues) == 1
        assert issues[0].bad_kwarg == "text"

    def test_tabs_old_api_invalid(self, tmp_path):
        """ft.Tabs does NOT accept tabs=, label_color=, etc."""
        issues = _analyze_code(
            tmp_path,
            """
            import flet as ft
            tabs = ft.Tabs(
                tabs=[ft.Tab(label="A")],
                label_color="white",
                indicator_color="blue",
                divider_color="grey",
            )
        """,
        )
        bad = {i.bad_kwarg for i in issues}
        assert "tabs" in bad
        assert "label_color" in bad
        assert "indicator_color" in bad
        assert "divider_color" in bad

    def test_tabs_unselected_label_color_invalid(self, tmp_path):
        """ft.Tabs does NOT accept unselected_label_color."""
        issues = _analyze_code(
            tmp_path,
            """
            import flet as ft
            tabs = ft.Tabs(
                content=ft.Row([]),
                length=1,
                unselected_label_color="grey",
            )
        """,
        )
        assert any(i.bad_kwarg == "unselected_label_color" for i in issues)

    def test_multiple_bad_kwargs_one_call(self, tmp_path):
        """Multiple bad kwargs in a single call should each be reported."""
        issues = _analyze_code(
            tmp_path,
            """
            import flet as ft
            tabs = ft.Tabs(tabs=[], label_color="w",
                           unselected_label_color="g",
                           indicator_color="b", divider_color="d")
        """,
        )
        assert len(issues) == 5

    # ── Edge cases ────────────────────────────────────────────────────

    def test_no_kwargs_ok(self, tmp_path):
        """Positional-only calls should not trigger issues."""
        issues = _analyze_code(
            tmp_path,
            """
            import flet as ft
            t = ft.Text("hello")
        """,
        )
        assert len(issues) == 0

    def test_non_ui_module_ignored(self, tmp_path):
        """Calls to non-UI modules should be ignored."""
        issues = _analyze_code(
            tmp_path,
            """
            import os
            os.path.join('a', 'b')
        """,
        )
        assert len(issues) == 0

    def test_syntax_error_file_skipped(self, tmp_path):
        """Files with syntax errors should be silently skipped."""
        p = tmp_path / "bad.py"
        p.write_text("import flet as ft\ndef broken(:\n", encoding="utf-8")
        analyzer = UICompatAnalyzer()
        issues = analyzer.analyze(p)
        assert len(issues) == 0

    def test_missing_module_skipped(self, tmp_path):
        """If the module can't be imported, skip gracefully."""
        issues = _analyze_code(
            tmp_path,
            """
            import nonexistent_ui_lib as nui
            nui.Widget(bad_param=True)
        """,
            extra_modules={"nonexistent_ui_lib"},
        )
        assert len(issues) == 0


# ---------------------------------------------------------------------------
# Integration — SmellIssue conversion
# ---------------------------------------------------------------------------


class TestSmellConversion:
    @pytest.fixture(autouse=True)
    def test_to_smell_fields(self, tmp_path):
        issues = _analyze_code(
            tmp_path,
            """
            import flet as ft
            t = ft.Tab(label="X", content=ft.Text("body"))
        """,
        )
        assert len(issues) == 1
        smell = issues[0].to_smell()
        assert isinstance(smell, SmellIssue)
        assert smell.severity == Severity.CRITICAL
        assert smell.category == "ui-compat"
        assert smell.source == "ui-compat"
        assert smell.rule_code == "UC001"
        assert "content" in smell.message
        assert "flet.Tab" in smell.name

    def test_suggestion_present(self, tmp_path):
        issues = _analyze_code(
            tmp_path,
            """
            import flet as ft
            t = ft.Tab(text="X")
        """,
        )
        smell = issues[0].to_smell()
        # Should suggest something useful
        assert len(smell.suggestion) > 0


# ---------------------------------------------------------------------------
# Summary / Reporting
# ---------------------------------------------------------------------------


class TestSummary:
    @pytest.fixture(autouse=True)
    def test_summary_structure(self, tmp_path):
        issues = _analyze_code(
            tmp_path,
            """
            import flet as ft
            ft.Tab(label="A", content=ft.Text("x"))
            ft.Tabs(tabs=[], label_color="w")
        """,
        )
        analyzer = UICompatAnalyzer()
        summary = analyzer.summary(raw=issues)
        assert "total" in summary
        assert summary["total"] == 3  # content + tabs + label_color
        assert "by_widget" in summary
        assert "by_file" in summary
        assert "bad_kwargs" in summary

    def test_print_report_no_crash(self, tmp_path, capsys):
        """print_report should not crash on empty or non-empty results."""
        analyzer = UICompatAnalyzer()
        analyzer.print_report([])
        out = capsys.readouterr().out
        assert "compatible" in out.lower() or "✅" in out

        issues = _analyze_code(
            tmp_path,
            """
            import flet as ft
            ft.Tab(content=ft.Text("x"))
        """,
        )
        analyzer.print_report(issues)
        out = capsys.readouterr().out
        assert "content" in out


# ---------------------------------------------------------------------------
# Full-tree scan
# ---------------------------------------------------------------------------


class TestTreeScan:
    @pytest.fixture(autouse=True)
    def test_analyze_tree(self, tmp_path):
        """Should recursively find issues across multiple files."""
        sub = tmp_path / "sub"
        sub.mkdir()
        _write_py(
            tmp_path,
            """
            import flet as ft
            ft.Tab(content=ft.Text("a"))
        """,
            "app1.py",
        )
        _write_py(
            sub,
            """
            import flet as ft
            ft.Tabs(tabs=[], label_color="w")
        """,
            "app2.py",
        )
        analyzer = UICompatAnalyzer()
        issues = analyzer.analyze_tree(tmp_path)
        assert len(issues) >= 3  # 1 from app1 + 2 from app2

    def test_exclude_dirs(self, tmp_path):
        """Excluded dirs should be skipped."""
        venv = tmp_path / ".venv"
        venv.mkdir()
        _write_py(
            venv,
            """
            import flet as ft
            ft.Tab(content=ft.Text("a"))
        """,
            "hidden.py",
        )
        _write_py(
            tmp_path,
            """
            import flet as ft
            ft.Text("clean", size=14)
        """,
            "clean.py",
        )
        analyzer = UICompatAnalyzer()
        issues = analyzer.analyze_tree(tmp_path)
        assert len(issues) == 0  # .venv excluded, clean.py is clean


# ---------------------------------------------------------------------------
# Self-scan — run on our own codebase
# ---------------------------------------------------------------------------


class TestSelfScan:
    """Run the analyzer on x_ray_flet.py and verify known bugs are detected."""

    @pytest.fixture(autouse=True)
    def test_xray_flet_known_issues(self):
        """After the tabs rewrite, x_ray_flet.py should have zero UI compat issues."""
        flet_path = Path(__file__).resolve().parent.parent / "x_ray_flet.py"
        if not flet_path.exists():
            pytest.skip("x_ray_flet.py not found")
        analyzer = UICompatAnalyzer()
        issues = analyzer.analyze(flet_path)
        assert len(issues) == 0, (
            f"Expected 0 UI compat issues in x_ray_flet.py but found {len(issues)}:\n"
            + "\n".join(
                f"  L{i.call.line}: {i.bad_kwarg} in {i.call.resolved_name}"
                for i in issues
            )
        )
