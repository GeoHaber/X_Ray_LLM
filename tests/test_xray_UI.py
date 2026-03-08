"""Comprehensive Flet UI monkey-test & handler-verification suite.

Tests that:
1. Every button in every tab/menu can be discovered and triggered
2. Flet delivers click events to the underlying handler functions
3. Handler functions actually execute and update UI state/widgets
4. No unhandled exceptions leak from any handler
"""

import asyncio
import json
import random
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import flet as ft

XRAY_ROOT = str(Path(__file__).parent.parent)
if XRAY_ROOT not in sys.path:
    sys.path.insert(0, XRAY_ROOT)

from x_ray_flet import main as xray_main  # noqa: E402
from Core.types import FunctionRecord  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockEvent:
    """Simulates a Flet control event for handler testing."""

    def __init__(self, control, page=None, data=""):
        self.control = control
        self.page = page or MagicMock(spec=ft.Page)
        self.data = data
        self.target = getattr(control, "uid", "mock-uid")
        self.name = "click"


def _make_page() -> MagicMock:
    """Create a fully-mocked Flet Page that survives main()."""
    page = MagicMock(spec=ft.Page)
    page.controls = []
    page.overlay = []
    page.services = []
    page.data = {"_onboarded": True}
    page.session_id = "test-session"
    page.width = 1360
    page.height = 880
    page.window = MagicMock()
    page.window.width = 1360
    page.window.height = 880
    page.update = MagicMock()
    page.run_task = MagicMock()
    page.add = lambda *args: page.controls.extend(args)
    page.pop_dialog = MagicMock()
    page.show_drawer = MagicMock()
    page.launch_url = AsyncMock()
    page.drawer = None
    return page


# ── Fake scan results used by tab builders ──

FAKE_RESULTS = {
    "smells": [
        MagicMock(
            name="LongMethod",
            message="Method too long (120 lines)",
            file_path="a.py",
            line=10,
            severity="warning",
            suggestion="Split the method.",
            rule_code="SM001",
        )
    ],
    "duplicates": {"groups": []},
    "lint": {"summary": {"total": 2, "fixable": 1}, "issues": []},
    "security": {"summary": {"total": 1}, "issues": []},
    "rustify": {"candidates": []},
    "ui_compat": {"issues": []},
    "ui_health": {"issues": []},
    "verification": {
        "functional_score": 100,
        "ui_stability_score": 100,
        "issues": [],
        "meta": {"duration": 0.01, "grade": "A+", "score": 100},
    },
    "release_readiness": {
        "score": 90,
        "grade": "A",
        "verdict": "GO",
        "checks": {},
        "markers": [],
    },
    "checklist": {"items": [], "pass_count": 0, "fail_count": 0, "total": 0},
    "grade": {"letter": "A", "score": 90, "breakdown": {}},
    "meta": {"files": 10, "functions": 50, "classes": 5, "duration": 1.2},
    "_smell_issues": [],
    "_lint_issues": [],
    "_sec_issues": [],
    "_functions": [
        FunctionRecord(
            name="main",
            file_path="a.py",
            line_start=1,
            line_end=20,
            size_lines=20,
            parameters=["self"],
            return_type=None,
            decorators=[],
            docstring=None,
            calls_to=[],
            complexity=3,
            nesting_depth=1,
            code_hash="abc123",
            structure_hash="def456",
            code="def main(self): pass",
        )
    ],
    "_classes": [],
    "_dup_groups": [],
    "_scan_path": str(Path(__file__).parent.parent),
}


# ---------------------------------------------------------------------------
# 1. Control tree walker — finds ALL interactive elements
# ---------------------------------------------------------------------------


def find_all_interactive(controls, depth=0, max_depth=30):
    """Recursively walk a Flet control tree and return all interactive elements."""
    found = []
    if not controls or depth > max_depth:
        return found
    for c in controls:
        # Buttons
        if isinstance(
            c,
            (
                ft.Button,
                ft.ElevatedButton,
                ft.FilledButton,
                ft.TextButton,
                ft.IconButton,
            ),
        ):
            found.append(("button", c))
        # Checkboxes
        elif isinstance(c, ft.Checkbox):
            found.append(("checkbox", c))
        # Dropdowns
        elif isinstance(c, ft.Dropdown):
            found.append(("dropdown", c))
        # NavigationRail
        elif isinstance(c, ft.NavigationRail):
            found.append(("rail", c))
        # Containers with on_click (pill tabs, etc.)
        elif hasattr(c, "on_click") and getattr(c, "on_click") is not None:
            found.append(("clickable", c))

        # Recurse children
        for attr in ("controls", "content", "actions", "leading", "trailing"):
            child = getattr(c, attr, None)
            if child is None:
                continue
            if isinstance(child, list):
                found.extend(find_all_interactive(child, depth + 1, max_depth))
            elif hasattr(child, "controls") or hasattr(child, "content") or hasattr(
                child, "on_click"
            ):
                found.extend(find_all_interactive([child], depth + 1, max_depth))
    return found


async def _trigger(handler, control, page):
    """Fire handler (sync or async) with a MockEvent, return any exception or None."""
    e = MockEvent(control=control, page=page)
    try:
        if asyncio.iscoroutinefunction(handler):
            await handler(e)
        else:
            handler(e)
        return None
    except Exception as exc:
        # Flet "control must be added to page" is expected in headless tests
        if "Control must be added" in str(exc):
            return None
        return exc


# ---------------------------------------------------------------------------
# Helper: collect all text values from a control tree
# ---------------------------------------------------------------------------


def _collect_texts(ctrl, depth=0):
    """Walk the control tree and return all ft.Text.value strings."""
    texts = []
    if depth > 20:
        return texts
    if isinstance(ctrl, ft.Text):
        if ctrl.value:
            texts.append(str(ctrl.value))
    for attr in ("controls", "content"):
        child = getattr(ctrl, attr, None)
        if child is None:
            continue
        if isinstance(child, list):
            for c in child:
                texts.extend(_collect_texts(c, depth + 1))
        else:
            texts.extend(_collect_texts(child, depth + 1))
    return texts


# ===========================================================================
# TEST SUITE
# ===========================================================================


class TestUIBootstrap:
    """Verify that the main Flet app boots without errors."""

    @pytest.mark.asyncio
    async def test_main_builds_ui(self):
        page = _make_page()
        await xray_main(page)
        assert len(page.controls) >= 1, "main() should add at least one root control"

    @pytest.mark.asyncio
    async def test_initial_interactive_elements(self):
        """After boot the sidebar should contain checkboxes and buttons."""
        page = _make_page()
        await xray_main(page)
        elems = find_all_interactive(page.controls)
        types = {t for t, _ in elems}
        assert "checkbox" in types, "Sidebar should have mode checkboxes"
        assert "button" in types or "clickable" in types, "Should have buttons"


class TestModeCheckboxes:
    """Every mode checkbox should update state when toggled."""

    ALL_MODES = [
        "smells",
        "duplicates",
        "lint",
        "security",
        "typecheck",
        "format",
        "health",
        "imports",
        "rustify",
        "ui_compat",
        "ui_health",
        "verification",
        "release_readiness",
    ]

    @pytest.mark.asyncio
    async def test_all_mode_checkboxes_present(self):
        page = _make_page()
        await xray_main(page)
        elems = find_all_interactive(page.controls)
        checkboxes = [(t, c) for t, c in elems if t == "checkbox"]
        cb_keys = {c.data for _, c in checkboxes if c.data}
        for mode in self.ALL_MODES:
            assert mode in cb_keys, f"Missing checkbox for mode '{mode}'"

    @pytest.mark.asyncio
    async def test_checkbox_toggle_updates_state(self):
        page = _make_page()
        await xray_main(page)
        state = page.data["_state"]
        elems = find_all_interactive(page.controls)
        checkboxes = [(t, c) for t, c in elems if t == "checkbox" and c.data]

        for _, cb in checkboxes:
            key = cb.data
            if key not in self.ALL_MODES:
                continue
            original = state["modes"].get(key)
            # Toggle to opposite
            cb.value = not original
            handler = cb.on_change
            assert handler is not None, f"Checkbox '{key}' has no on_change handler"
            await _trigger(handler, cb, page)
            assert state["modes"][key] == (not original), (
                f"Mode '{key}' was not updated from {original} to {not original}"
            )
            # Toggle back
            cb.value = original
            await _trigger(handler, cb, page)

    @pytest.mark.asyncio
    async def test_toggle_all_checkbox(self):
        page = _make_page()
        await xray_main(page)
        state = page.data["_state"]
        elems = find_all_interactive(page.controls)
        checkboxes = [(t, c) for t, c in elems if t == "checkbox"]

        # Find the "All / None" checkbox
        toggle = None
        for _, cb in checkboxes:
            if getattr(cb, "label", "") == "All / None":
                toggle = cb
                break
        assert toggle is not None, "All/None master checkbox not found"

        # Uncheck all
        toggle.value = False
        await _trigger(toggle.on_change, toggle, page)
        for key in self.ALL_MODES:
            assert state["modes"][key] is False, (
                f"Mode '{key}' should be False after uncheck-all"
            )

        # Re-check all
        toggle.value = True
        await _trigger(toggle.on_change, toggle, page)
        for key in self.ALL_MODES:
            assert state["modes"][key] is True, (
                f"Mode '{key}' should be True after check-all"
            )


class TestScanButton:
    """The scan button should guard on root_path and invoke the handler."""

    @pytest.mark.asyncio
    async def test_scan_without_path_shows_error(self):
        """Clicking scan with no directory selected should not crash."""
        page = _make_page()
        await xray_main(page)
        state = page.data["_state"]
        state["root_path"] = ""  # ensure no path

        elems = find_all_interactive(page.controls)
        buttons = [(t, c) for t, c in elems if t in ("button", "clickable")]

        # Find the scan button — it's the one with ft.Icons.BOLT icon
        scan_btn = None
        for _, b in buttons:
            icon = getattr(b, "icon", None)
            if icon == ft.Icons.BOLT:
                scan_btn = b
                break

        if scan_btn and scan_btn.on_click:
            exc = await _trigger(scan_btn.on_click, scan_btn, page)
            assert exc is None, f"Scan handler raised: {exc}"


class TestTabBuilders:
    """Each tab builder should produce a valid Flet control tree
    and its interactive elements should fire without exceptions."""

    @pytest.fixture
    def mock_page(self):
        return _make_page()

    # ── Smells tab ──
    def test_smells_tab(self, mock_page):
        from UI.tabs.smells_tab import _build_smells_tab

        ctrl = _build_smells_tab(FAKE_RESULTS)
        assert ctrl is not None

    # ── Duplicates tab ──
    def test_duplicates_tab(self, mock_page):
        from UI.tabs.duplicates_tab import _build_duplicates_tab

        ctrl = _build_duplicates_tab(FAKE_RESULTS)
        assert ctrl is not None

    # ── Lint tab (has auto-fix button) ──
    def test_lint_tab(self, mock_page):
        from UI.tabs.lint_tab import _build_lint_tab

        ctrl = _build_lint_tab(FAKE_RESULTS, mock_page)
        assert ctrl is not None

    @pytest.mark.asyncio
    async def test_lint_autofix_button(self, mock_page):
        from UI.tabs.lint_tab import _build_lint_tab

        # Make fixable > 0 so button appears
        results = dict(FAKE_RESULTS)
        results["lint"] = {"summary": {"total": 2, "fixable": 1}, "issues": []}
        results["_scan_path"] = str(Path(__file__).parent.parent)
        ctrl = _build_lint_tab(results, mock_page)
        elems = find_all_interactive([ctrl])
        buttons = [c for t, c in elems if t == "button"]

        for btn in buttons:
            if btn.on_click:
                with patch("subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(
                        stdout="Fixed 1 issue", returncode=0
                    )
                    exc = await _trigger(btn.on_click, btn, mock_page)
                    assert exc is None, f"Lint auto-fix raised: {exc}"

    # ── Security tab ──
    def test_security_tab(self, mock_page):
        from UI.tabs.security_tab import _build_security_tab

        ctrl = _build_security_tab(FAKE_RESULTS)
        assert ctrl is not None

    # ── UI Compat tab ──
    def test_ui_compat_tab(self, mock_page):
        from UI.tabs.ui_compat_tab import _build_ui_compat_tab

        ctrl = _build_ui_compat_tab(FAKE_RESULTS)
        assert ctrl is not None

    # ── UI Health tab ──
    def test_ui_health_tab(self, mock_page):
        from UI.tabs.ui_health_tab import _build_ui_health_tab

        ctrl = _build_ui_health_tab(FAKE_RESULTS)
        assert ctrl is not None

    # ── Verification tab (has Chaos Monkey button) ──
    def test_verification_tab_renders(self, mock_page):
        from UI.tabs.verification_tab import _build_verification_tab

        ctrl = _build_verification_tab(FAKE_RESULTS, mock_page)
        assert ctrl is not None
        elems = find_all_interactive([ctrl])
        buttons = [c for t, c in elems if t in ("button", "clickable")]
        assert len(buttons) >= 1, "Verification tab should have the Chaos Monkey button"

    @pytest.mark.asyncio
    async def test_verification_monkey_button(self, mock_page):
        from UI.tabs.verification_tab import _build_verification_tab

        ctrl = _build_verification_tab(FAKE_RESULTS, mock_page)
        elems = find_all_interactive([ctrl])
        buttons = [c for t, c in elems if t in ("button", "clickable")]

        for btn in buttons:
            handler = getattr(btn, "on_click", None)
            if handler and asyncio.iscoroutinefunction(handler):
                exc = await _trigger(handler, btn, mock_page)
                assert exc is None, f"Chaos monkey button raised: {exc}"

    # ── Verification data flow ──
    def test_verification_uses_meta_score(self, mock_page):
        """Score and grade should come from verification['meta']."""
        from UI.tabs.verification_tab import _build_verification_tab

        ctrl = _build_verification_tab(FAKE_RESULTS, mock_page)
        texts = _collect_texts(ctrl)
        text_vals = " ".join(texts)
        assert "100" in text_vals or "A+" in text_vals, (
            f"Verification tab should display A+/100 from meta, got: {text_vals[:200]}"
        )

    # ── Release Readiness tab ──
    def test_release_readiness_tab(self, mock_page):
        from UI.tabs.release_readiness_tab import _build_release_readiness_tab

        ctrl = _build_release_readiness_tab(FAKE_RESULTS, mock_page)
        assert ctrl is not None

    # ── Rustify tab ──
    def test_rustify_tab(self, mock_page):
        from UI.tabs.rustify_tab import _build_rustify_tab

        ctrl = _build_rustify_tab(FAKE_RESULTS)
        assert ctrl is not None

    # ── Graph tab ──
    def test_graph_tab(self, mock_page):
        from UI.tabs.graph_tab import _build_graph_tab

        ctrl = _build_graph_tab(FAKE_RESULTS, mock_page)
        assert ctrl is not None

    @pytest.mark.asyncio
    async def test_graph_open_button(self, mock_page):
        from UI.tabs.graph_tab import _build_graph_tab

        ctrl = _build_graph_tab(FAKE_RESULTS, mock_page)
        elems = find_all_interactive([ctrl])
        buttons = [c for t, c in elems if t == "button"]
        for btn in buttons:
            if btn.on_click:
                exc = await _trigger(btn.on_click, btn, mock_page)
                assert exc is None, f"Graph open button raised: {exc}"

    # ── Nexus tab ──
    def test_nexus_tab_renders(self, mock_page):
        from UI.tabs.nexus_tab import _build_nexus_tab

        ctrl = _build_nexus_tab(FAKE_RESULTS, mock_page)
        assert ctrl is not None
        elems = find_all_interactive([ctrl])
        buttons = [c for t, c in elems if t == "button"]
        assert len(buttons) >= 1, "Nexus tab should have the Run button"

    @pytest.mark.asyncio
    async def test_nexus_button_handler(self, mock_page):
        from UI.tabs.nexus_tab import _build_nexus_tab

        ctrl = _build_nexus_tab(FAKE_RESULTS, mock_page)
        elems = find_all_interactive([ctrl])
        buttons = [c for t, c in elems if t == "button"]
        for btn in buttons:
            handler = getattr(btn, "on_click", None)
            if handler:
                with patch("UI.tabs.nexus_tab.NexusOrchestrator") as mock_orch:
                    instance = mock_orch.return_value
                    instance.build_context_graph = MagicMock()
                    instance.graph_index = {"bottlenecks": []}
                    instance.run_transpilation_pipeline = MagicMock(return_value=[])
                    instance.verify_and_build = MagicMock(return_value=[])
                    exc = await _trigger(handler, btn, mock_page)
                    assert exc is None, f"Nexus button raised: {exc}"

    # ── Auto-Rustify tab ──
    def test_auto_rustify_tab(self, mock_page):
        from UI.tabs.auto_rustify_tab import _build_auto_rustify_tab

        ctrl = _build_auto_rustify_tab(FAKE_RESULTS, mock_page)
        assert ctrl is not None

    @pytest.mark.asyncio
    async def test_auto_rustify_button(self, mock_page):
        from UI.tabs.auto_rustify_tab import _build_auto_rustify_tab

        ctrl = _build_auto_rustify_tab(FAKE_RESULTS, mock_page)
        elems = find_all_interactive([ctrl])
        buttons = [c for t, c in elems if t == "button"]
        for btn in buttons:
            handler = getattr(btn, "on_click", None)
            if handler:
                with patch("UI.tabs.auto_rustify_tab.RustifyPipeline") as mock_pipe:
                    report = MagicMock()
                    report.compile_result = MagicMock(success=True)
                    report.errors = []
                    mock_pipe.return_value.run = MagicMock(return_value=report)
                    exc = await _trigger(handler, btn, mock_page)
                    assert exc is None, f"Auto-rustify button raised: {exc}"


class TestSectionTitle:
    """section_title() must handle both string icons and ft.Icons enums."""

    def test_with_string_icon(self):
        from UI.tabs.shared import section_title

        ctrl = section_title("Test", "★")
        assert isinstance(ctrl, ft.Text)
        assert "★" in ctrl.value

    def test_with_empty_icon(self):
        from UI.tabs.shared import section_title

        ctrl = section_title("Test", "")
        assert isinstance(ctrl, ft.Text)
        assert ctrl.value == "Test"

    def test_with_flet_icon_enum(self):
        from UI.tabs.shared import section_title

        ctrl = section_title("Verification Suite", ft.Icons.VERIFIED_USER)
        # Should return a Row with an Icon + Text, NOT "73802 Verification Suite"
        assert isinstance(ctrl, ft.Row), (
            f"Expected ft.Row for enum icon, got {type(ctrl).__name__}"
        )
        children = ctrl.controls
        assert any(isinstance(c, ft.Icon) for c in children)
        assert any(isinstance(c, ft.Text) for c in children)
        # The text should NOT contain the int codepoint
        for c in children:
            if isinstance(c, ft.Text):
                assert str(ft.Icons.VERIFIED_USER) not in c.value

    def test_with_no_icon(self):
        from UI.tabs.shared import section_title

        ctrl = section_title("Plain Title")
        assert isinstance(ctrl, ft.Text)
        assert ctrl.value == "Plain Title"


class TestMetricTile:
    """metric_tile() must handle string emoji icons, ft.Icons int enums, and widget icons."""

    def test_string_icon(self):
        from UI.tabs.shared import metric_tile

        tile = metric_tile("📁", "83", "Files")
        assert isinstance(tile, ft.Container)

    def test_int_icon_enum(self):
        from UI.tabs.shared import metric_tile

        tile = metric_tile(ft.Icons.COMMENT, "50%", "Docstrings")
        col = tile.content
        assert isinstance(col, ft.Column)
        icon_widget = col.controls[0]
        # Must be an ft.Icon, NOT a raw int
        assert isinstance(icon_widget, ft.Icon), (
            f"Expected ft.Icon for enum icon, got {type(icon_widget).__name__}"
        )

    def test_widget_icon_passthrough(self):
        from UI.tabs.shared import metric_tile

        custom = ft.Icon(ft.Icons.BUG_REPORT, color="red")
        tile = metric_tile(custom, "3", "CVEs")
        col = tile.content
        assert col.controls[0] is custom


class TestExportButtons:
    """Export handlers should write files with correct content."""

    @pytest.mark.asyncio
    async def test_export_json_handler(self, tmp_path):
        page = _make_page()
        state = {"root_path": str(tmp_path)}
        results = dict(FAKE_RESULTS)
        results["_scan_path"] = str(tmp_path)

        from x_ray_flet import _build_export_bar

        bar = _build_export_bar(page, state, results)
        elems = find_all_interactive([bar])
        buttons = [c for t, c in elems if t == "button"]

        # First button is "Export JSON"
        json_btn = buttons[0] if buttons else None
        assert json_btn is not None
        exc = await _trigger(json_btn.on_click, json_btn, page)
        assert exc is None

        json_file = tmp_path / "xray_report.json"
        assert json_file.exists(), "JSON export should create xray_report.json"
        data = json.loads(json_file.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        # Internal keys starting with _ should be excluded
        for key in data:
            assert not key.startswith("_"), f"Internal key '{key}' leaked into export"

    @pytest.mark.asyncio
    async def test_export_md_handler(self, tmp_path):
        page = _make_page()
        state = {"root_path": str(tmp_path)}
        # Use dict-style smells so _build_markdown_report doesn't error
        results = dict(FAKE_RESULTS)
        results["smells"] = {"total": 1}

        from x_ray_flet import _build_export_bar

        bar = _build_export_bar(page, state, results)
        elems = find_all_interactive([bar])
        buttons = [c for t, c in elems if t == "button"]

        md_btn = buttons[1] if len(buttons) > 1 else None
        assert md_btn is not None
        exc = await _trigger(md_btn.on_click, md_btn, page)
        assert exc is None, f"MD export handler raised: {exc}"

        md_file = tmp_path / "xray_report.md"
        assert md_file.exists(), "Markdown export should create xray_report.md"

    @pytest.mark.asyncio
    async def test_gen_tests_handler(self, tmp_path):
        page = _make_page()
        state = {"root_path": str(tmp_path)}
        results = dict(FAKE_RESULTS)

        from x_ray_flet import _build_export_bar

        bar = _build_export_bar(page, state, results)
        elems = find_all_interactive([bar])
        buttons = [c for t, c in elems if t == "button"]

        gen_btn = buttons[2] if len(buttons) > 2 else None
        if gen_btn and gen_btn.on_click:
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="ok")
                exc = await _trigger(gen_btn.on_click, gen_btn, page)
                assert exc is None
                mock_run.assert_called_once()


class TestTabPillNavigation:
    """Result tab pills should switch the visible panel on click."""

    @pytest.mark.asyncio
    async def test_pill_click_switches_tab(self):
        from x_ray_flet import _build_result_tabs

        page = _make_page()
        tabs_widget = _build_result_tabs(FAKE_RESULTS, page)
        if tabs_widget is None or not hasattr(tabs_widget, "controls"):
            pytest.skip("No tabs built from FAKE_RESULTS")

        elems = find_all_interactive([tabs_widget])
        pills = [c for t, c in elems if t == "clickable"]

        errors = []
        for i, pill in enumerate(pills):
            handler = getattr(pill, "on_click", None)
            if handler:
                exc = await _trigger(handler, pill, page)
                if exc:
                    errors.append(f"Pill {i}: {exc}")
        assert not errors, f"Pill click errors: {errors}"


class TestChaosMonkey:
    """Random-click stress test across the full UI."""

    @pytest.mark.asyncio
    async def test_chaos_monkey_full_ui(self):
        """Boot the UI, find every interactive element, and click them all."""
        page = _make_page()
        await xray_main(page)

        all_elems = find_all_interactive(page.controls)
        all_elems.extend(find_all_interactive(page.overlay))

        errors = []
        click_count = 0

        for etype, ctrl in all_elems:
            handler = None
            if etype == "checkbox":
                handler = getattr(ctrl, "on_change", None)
            elif etype == "dropdown":
                handler = getattr(
                    ctrl, "on_select", getattr(ctrl, "on_change", None)
                )
            else:
                handler = getattr(ctrl, "on_click", None)

            if handler:
                exc = await _trigger(handler, ctrl, page)
                click_count += 1
                if exc:
                    errors.append(f"{etype} {type(ctrl).__name__}: {exc}")

        print(f"Chaos monkey clicked {click_count} elements, {len(errors)} errors")
        assert not errors, "Chaos monkey found errors:\n" + "\n".join(errors)

    @pytest.mark.asyncio
    async def test_chaos_monkey_random_200(self):
        """200 random clicks should not crash."""
        page = _make_page()
        await xray_main(page)

        errors = []
        for _i in range(200):
            all_elems = find_all_interactive(page.controls)
            all_elems.extend(find_all_interactive(page.overlay))
            clickables = [
                (t, c)
                for t, c in all_elems
                if getattr(c, "on_click", None)
                or getattr(c, "on_change", None)
            ]
            if not clickables:
                continue

            etype, target = random.choice(clickables)
            handler = getattr(target, "on_click", None) or getattr(
                target, "on_change", None
            )
            if handler:
                exc = await _trigger(handler, target, page)
                if exc:
                    errors.append(
                        f"Iter {_i} {etype} {type(target).__name__}: {exc}"
                    )

        assert len(errors) < 5, (
            f"Too many errors in 200 random clicks:\n" + "\n".join(errors[:10])
        )


class TestDashboardTabButtons:
    """After building the dashboard, every tab's buttons should fire correctly."""

    @pytest.mark.asyncio
    async def test_all_dashboard_buttons_fire(self):
        """Build dashboard with FAKE_RESULTS and click every button in every tab."""
        page = _make_page()
        await xray_main(page)
        state = page.data["_state"]
        state["root_path"] = str(Path(__file__).parent.parent)
        state["results"] = FAKE_RESULTS

        from x_ray_flet import _build_main_dashboard

        main_content = ft.Column([], expand=True)
        _build_main_dashboard(page, state, main_content, FAKE_RESULTS)

        elems = find_all_interactive(main_content.controls)
        buttons = [(t, c) for t, c in elems if t in ("button", "clickable")]
        errors = []

        for _etype, btn in buttons:
            handler = getattr(btn, "on_click", None)
            if not handler:
                continue
            with patch(
                "subprocess.run",
                MagicMock(return_value=MagicMock(returncode=0, stdout="ok")),
            ):
                with patch("UI.tabs.nexus_tab.NexusOrchestrator", MagicMock()):
                    with patch(
                        "UI.tabs.auto_rustify_tab.RustifyPipeline", MagicMock()
                    ):
                        exc = await _trigger(handler, btn, page)
                        if exc:
                            errors.append(f"{type(btn).__name__}: {exc}")

        print(f"Dashboard: {len(buttons)} buttons, {len(errors)} errors")
        assert not errors, "Dashboard button errors:\n" + "\n".join(errors)


class TestHandlerReactsAndUpdatesUI:
    """Verify that underlying handler functions actually update widget state."""

    @pytest.mark.asyncio
    async def test_nexus_updates_status_text(self):
        """After Nexus pipeline runs, status_text should be updated."""
        page = _make_page()
        from UI.tabs.nexus_tab import _run_nexus_pipeline

        status = ft.Text("")
        prog = ft.ProgressBar(value=0, visible=False)
        results_col = ft.Column()

        with patch("UI.tabs.nexus_tab.NexusOrchestrator") as mock_orch:
            inst = mock_orch.return_value
            inst.build_context_graph = MagicMock()
            inst.graph_index = {"bottlenecks": []}
            inst.run_transpilation_pipeline = MagicMock(return_value=[])
            inst.verify_and_build = MagicMock(return_value=[])

            _run_nexus_pipeline(FAKE_RESULTS, page, status, prog, results_col)

        assert status.value != "", "Status text should be updated after pipeline"
        assert "[ok]" in status.value or "[x]" in status.value, (
            f"Status should have success/error marker, got: {status.value}"
        )

    @pytest.mark.asyncio
    async def test_rustify_updates_status_text(self):
        """After Rustify pipeline runs, status_text should be updated."""
        page = _make_page()
        from UI.tabs.auto_rustify_tab import _run_rustify_pipeline

        status = ft.Text("")
        prog = ft.ProgressBar(value=0, visible=False)

        with patch("UI.tabs.auto_rustify_tab.RustifyPipeline") as mock_pipe:
            report = MagicMock()
            report.compile_result = MagicMock(success=True)
            report.errors = []
            mock_pipe.return_value.run = MagicMock(return_value=report)

            _run_rustify_pipeline(FAKE_RESULTS, page, status, prog)

        assert status.value != "", "Status text should be updated"
        assert "[ok]" in status.value or "[x]" in status.value or "[!]" in status.value

    @pytest.mark.asyncio
    async def test_verification_monkey_disables_button(self):
        """Running chaos monkey should toggle the button disabled state."""
        page = _make_page()
        from UI.tabs.verification_tab import _build_verification_tab

        ctrl = _build_verification_tab(FAKE_RESULTS, page)
        elems = find_all_interactive([ctrl])
        async_buttons = [
            c
            for t, c in elems
            if t == "button"
            and asyncio.iscoroutinefunction(getattr(c, "on_click", None))
        ]
        for btn in async_buttons:
            handler = btn.on_click
            e = MockEvent(control=btn, page=page)
            await handler(e)
            # After completion, button should be re-enabled
            assert not btn.disabled or btn.disabled is False

    def test_mode_checkbox_state_round_trip(self):
        """Toggle a mode checkbox and verify state reflects the change."""
        from x_ray_flet import _init_state, _build_mode_checks

        page = _make_page()
        page.data = {}
        state = _init_state(page)

        original_smells = state["modes"]["smells"]
        checks = _build_mode_checks(state)
        all_cbs = find_all_interactive([checks])
        smells_cb = None
        for _, c in all_cbs:
            if isinstance(c, ft.Checkbox) and getattr(c, "data", None) == "smells":
                smells_cb = c
                break
        assert smells_cb is not None
        smells_cb.value = not original_smells
        smells_cb.on_change(MockEvent(control=smells_cb, page=page))
        assert state["modes"]["smells"] == (not original_smells)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "-x"])
