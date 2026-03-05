#!/usr/bin/env python3
"""
x_ray_flet.py — Flet Desktop/Web GUI for X-Ray Code Quality Scanner
======================================================================

Launch with::

    python x_ray_flet.py                  # native desktop window
    flet run x_ray_flet.py                # same, via flet CLI
    flet run --web x_ray_flet.py          # opens in browser

Features:
  - Native Material 3 desktop app (Flutter engine)
  - Light / Dark mode toggle
  - Multi-language support (EN, RO, ES, FR, DE)
  - First-run onboarding stepper
  - Animated progress screen with file counter & ETA
  - All scan tabs: Smells, Duplicates, Lint, Security, Rustify
  - Heatmap, Complexity, Auto-Rustify Pipeline tabs
  - JSON + Markdown export
  - One-click Ruff auto-fix
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess  # nosec B404
import sys
import textwrap
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import flet as ft

# â”€â”€ Ensure project root is importable â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Core.types import FunctionRecord, ClassRecord  # noqa: E402
from Core.config import __version__, SMELL_THRESHOLDS  # noqa: E402
from Core.i18n import t, set_locale, get_locale, LOCALES  # noqa: E402
from Core.ui_bridge import set_bridge, get_bridge  # noqa: E402
from Analysis.ast_utils import extract_functions_from_file, collect_py_files  # noqa: E402
from Analysis.smells import CodeSmellDetector  # noqa: E402
from Analysis.duplicates import DuplicateFinder  # noqa: E402
from Analysis.reporting import compute_grade  # noqa: E402
from Analysis.rust_advisor import RustAdvisor  # noqa: E402
from Analysis.smart_graph import SmartGraph  # noqa: E402
from Analysis.NexusMode.orchestrator import NexusOrchestrator  # noqa: E402
from UI.tabs.shared import (  # noqa: E402
    TH,
    is_narrow,
    _show_snack,
    glass_card,
    metric_tile,
    section_title,
    bar_chart,
    _empty_result_box,
    _empty_state,
    _build_issue_tile,
    _build_markdown_report,
    _code_panel,
    _bucket_values,
)

import ast  # noqa: E402
import concurrent.futures  # noqa: E402

logger = logging.getLogger(__name__)

# â”€â”€ Conditional imports for auto-rustify â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
try:
    from Analysis.auto_rustify import (
        RustifyPipeline,
        detect_system,
        py_type_to_rust as _py_type_to_rust,
        _translate_body,
    )

    HAS_AUTO_RUSTIFY = True
except ImportError:
    HAS_AUTO_RUSTIFY = False


# ═══════════════════════════════════════════════════════════════════════════════
#  FLET-SPECIFIC UI BRIDGE
# ═══════════════════════════════════════════════════════════════════════════════


class FletBridge:
    """
    UI bridge for the Flet desktop app.

    Satisfies the UIBridge Protocol and is registered via
    ``set_bridge(FletBridge(page, log_list, progress_cb))``
    before any scan is kicked off.

    Parameters
    ----------
    page : ft.Page
        The active Flet page (needed for page.update()).
    log_list : ft.ListView | None
        If provided, log lines are appended here as ft.Text controls.
        Pass None to suppress in-UI log lines.
    progress_cb : callable | None
        Existing progress callback signature:
        ``progress_cb(frac, label, files_done, total_files, eta_secs)``
        Called on each progress() call so the animated progress bar
        stays in sync.
    """

    def __init__(
        self, page: ft.Page, log_list: "ft.ListView | None" = None, progress_cb=None
    ) -> None:
        self._page = page
        self._log_list = log_list
        self._progress_cb = progress_cb
        self._last_label = ""

    # -- UIBridge Protocol methods ------------------------------------------

    def log(self, msg: str) -> None:
        """Append a log line to the in-app log panel (if one was given)."""
        if self._log_list is not None:
            try:
                self._log_list.controls.append(
                    ft.Text(
                        msg,
                        size=SZ_SM,
                        font_family=MONO_FONT,
                        color=TH.dim,
                        selectable=True,
                    )
                )
                self._page.update()
            except Exception:  # nosec
                pass

    def status(self, label: str) -> None:
        """Update current phase label; also emitted as a log line."""
        self._last_label = label
        self.log(f"\n  >> {label}")
        if self._progress_cb:
            try:
                self._progress_cb(
                    get_bridge()._last_frac  # type: ignore[attr-defined]
                    if hasattr(get_bridge(), "_last_frac")
                    else 0.0,
                    label,
                    0,
                    0,
                    -1,
                )
            except Exception:
                pass

    def progress(self, done: int, total: int, label: str = "") -> None:
        """Forward progress to the Flet animated progress bar callback."""
        if not self._progress_cb:
            return
        try:
            frac = (done / max(total, 1)) if total > 0 else 0.0
            frac = max(0.0, min(1.0, frac))
            # Store for status() to reference
            self._last_frac = frac  # type: ignore[attr-defined]
            self._progress_cb(frac, label or self._last_label, done, total, -1)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
#  THEME ENGINE  —  Dynamic Light / Dark
# ═══════════════════════════════════════════════════════════════════════════════

MONO_FONT = "Cascadia Code, Consolas, SF Mono, monospace"

# â”€â”€ Consistent sizing constants â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
SZ_XS = 11  # version numbers, copyright, tiny meta
SZ_SM = 12  # captions, file paths, code blocks, subtitles
SZ_BODY = 13  # secondary body, descriptions, meta info
SZ_MD = 14  # list-item titles, expansion-tile titles, body
SZ_LG = 15  # card titles, emphasized body
SZ_SECTION = 17  # section headings
SZ_H3 = 18  # panel titles, sub-headings
SZ_H2 = 22  # dialog titles, major headings
SZ_SIDEBAR = 24  # sidebar logo
SZ_HERO = 34  # landing-page hero title
SZ_DISPLAY = 40  # grade letter, decorative emoji

BTN_H_SM = 36  # secondary / export buttons
BTN_H_MD = 40  # normal action buttons
BTN_RADIUS = 10  # consistent border-radius for all buttons

# â”€â”€ Responsive breakpoints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
BP_NARROW = 900  # below this  single-column / drawer sidebar

GRADE_COLORS = {
    "A+": "#00c853",
    "A": "#00c853",
    "A-": "#00e676",
    "B+": "#64dd17",
    "B": "#aeea00",
    "B-": "#ffd600",
    "C+": "#ffab00",
    "C": "#ff6d00",
    "C-": "#ff3d00",
    "D+": "#dd2c00",
    "D": "#d50000",
    "D-": "#b71c1c",
    "F": "#880e4f",
}

SEV_ICONS = {"critical": "[!]", "warning": "[~]", "info": "[i]"}
SEV_COLORS = {
    "critical": ft.Colors.RED_400,
    "warning": ft.Colors.AMBER_400,
    "info": ft.Colors.GREEN_400,
}

# ═══════════════════════════════════════════════════════════════════════════════
#  SCAN ENGINE  (reused from x_ray_ui.py logic)
# ═══════════════════════════════════════════════════════════════════════════════


def _scan_codebase(root: Path, exclude: List[str], progress_cb=None):
    """Parse all .py files. Returns (funcs, classes, errors, file_count).
    progress_cb(files_done, total_files, current_file) is called per file."""
    py_files = collect_py_files(root, exclude or None)
    total = len(py_files)
    funcs, classes, errors = [], [], []
    done = [0]

    def _parse_one(f):
        fn, cl, err = extract_functions_from_file(f, root)
        done[0] += 1
        if progress_cb:
            progress_cb(done[0], total, str(f))
        return fn, cl, err, f

    with concurrent.futures.ThreadPoolExecutor() as pool:
        futs = [pool.submit(_parse_one, f) for f in py_files]
        for fut in concurrent.futures.as_completed(futs):
            fn, cl, err, fpath = fut.result()
            funcs.extend(fn)
            classes.extend(cl)
            if err:
                errors.append(f"{fpath}: {err}")
    return funcs, classes, errors, total


# â”€â”€ Individual scan phase helpers (keep _run_scan lean) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def _phase_smells(functions, classes, thresholds, results):
    det = CodeSmellDetector(thresholds=thresholds)
    smells = det.detect(functions, classes)
    results["smells"] = det.summary()
    results["_smell_issues"] = smells


def _phase_duplicates(functions, results):
    finder = DuplicateFinder()
    finder.find(functions)
    results["duplicates"] = finder.summary()
    results["_dup_groups"] = finder.groups


def _phase_lint(root, exclude, results):
    try:
        from Core.scan_phases import run_lint_phase

        linter, lint_issues = run_lint_phase(root, exclude=exclude or None)
        if linter:
            results["lint"] = linter.summary(lint_issues)
            results["_lint_issues"] = lint_issues
        else:
            results["lint"] = {"error": "Ruff not installed"}
    except Exception as exc:
        results["lint"] = {"error": str(exc)}


def _phase_security(root, exclude, results):
    try:
        from Core.scan_phases import run_security_phase

        sec, sec_issues = run_security_phase(root, exclude=exclude or None)
        if sec:
            results["security"] = sec.summary(sec_issues)
            results["_sec_issues"] = sec_issues
        else:
            results["security"] = {"error": "Bandit not installed"}
    except Exception as exc:
        results["security"] = {"error": str(exc)}


def _phase_rustify(functions, results):
    advisor = RustAdvisor()
    candidates = advisor.score(functions)
    results["rustify"] = {
        "total_scored": len(candidates),
        "pure_count": sum(1 for c in candidates if c.is_pure),
        "top_score": candidates[0].score if candidates else 0,
    }
    results["_rust_candidates"] = candidates


def _phase_ui_compat(root, exclude, results):
    try:
        from Analysis.ui_compat import UICompatAnalyzer

        analyzer = UICompatAnalyzer()
        raw_issues = analyzer.analyze(root, exclude=exclude or None)
        smell_issues = [i.to_smell() for i in raw_issues]
        results["ui_compat"] = analyzer.summary(raw=raw_issues)
        results["_ui_compat_issues"] = smell_issues
        results["_ui_compat_raw"] = raw_issues
    except Exception as exc:
        results["ui_compat"] = {"error": str(exc)}


def _phase_ui_health(root, exclude, results):
    try:
        from Analysis.ui_health import UIHealthAnalyzer

        analyzer = UIHealthAnalyzer()
        raw_issues = analyzer.analyze(root, exclude=exclude or None)
        smell_issues = [i.to_smell() for i in raw_issues]
        results["ui_health"] = analyzer.summary(raw=raw_issues)
        results["_ui_health_issues"] = smell_issues
        results["_ui_health_raw"] = raw_issues
    except Exception as exc:
        results["ui_health"] = {"error": str(exc)}


def _phase_health(root, results):
    try:
        from Core.scan_phases import run_health_phase

        analyzer = run_health_phase(root)
        results["health"] = analyzer.summary()
    except Exception as exc:
        results["health"] = {"error": str(exc)}


def _phase_typecheck(root, exclude, results):
    try:
        from Core.scan_phases import run_typecheck_phase

        tc, tc_issues = run_typecheck_phase(root, exclude=exclude or None)
        if tc:
            results["typecheck"] = tc.summary(tc_issues)
            results["_typecheck_issues"] = tc_issues
        else:
            results["typecheck"] = {"error": "Pyright not installed"}
    except Exception as exc:
        results["typecheck"] = {"error": str(exc)}


def _phase_format(root, exclude, results):
    try:
        from Core.scan_phases import run_format_phase

        fmt, fmt_issues = run_format_phase(root, exclude=exclude or None)
        if fmt:
            results["format"] = fmt.summary(fmt_issues)
            results["_format_issues"] = fmt_issues
        else:
            results["format"] = {"error": "Ruff not installed"}
    except Exception as exc:
        results["format"] = {"error": str(exc)}


def _phase_imports(root, exclude, results):
    try:
        from Core.scan_phases import run_imports_phase

        analyzer, imp_issues = run_imports_phase(root, exclude=exclude or None)
        results["imports"] = (
            analyzer.summary(imp_issues)
            if hasattr(analyzer, "summary")
            else {"total": len(imp_issues)}
        )
        results["_import_issues"] = imp_issues
    except Exception as exc:
        results["imports"] = {"error": str(exc)}


def _make_parse_progress_cb(progress_cb, parse_t0):
    """Create a progress callback for the parse phase."""
    if not progress_cb:
        return None

    def _on_parse(done, total, current_file):
        elapsed = time.time() - parse_t0
        rate = done / max(elapsed, 0.01)
        eta = (total - done) / rate if rate > 0 else 0
        frac = 0.05 + (done / max(total, 1)) * 0.35
        short = current_file if len(current_file) <= 50 else "" + current_file[-47:]
        progress_cb(frac, f"Parsing {short}", done, total, eta)

    return _on_parse


def _collect_code_map(functions):
    """Build a lookup dict from function keys to source code."""
    code_map = {}
    for fn in functions:
        code_map[f"{fn.file_path}:{fn.line_start}"] = fn.code
        code_map[fn.key] = fn.code
    return code_map


def _run_flet_ast_parsing(
    root: Path, exclude: List[str], progress_cb: Optional[Callable], t0: float
) -> tuple[List[FunctionRecord], List[ClassRecord], List[str], int]:
    parse_cb = _make_parse_progress_cb(progress_cb, t0)
    return _scan_codebase(root, exclude, progress_cb=parse_cb)


from dataclasses import dataclass  # noqa: E402
from enum import Enum  # noqa: E402


class PhaseStatus(Enum):
    """Status of a scan phase shown in the phase checklist UI."""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    SKIPPED = "skipped"
    FAILED = "failed"


PHASE_REGISTRY = [
    ("smells", "Code Smells"),
    ("duplicates", "Duplicates"),
    ("lint", "Lint (Ruff)"),
    ("security", "Security (Bandit)"),
    ("typecheck", "Type Check (Pyright)"),
    ("format", "Format Check"),
    ("health", "Project Health"),
    ("imports", "Import Health"),
    ("rustify", "Rust Candidates"),
    ("ui_compat", "UI Compat"),
    ("ui_health", "UI Health"),
]


@dataclass
class FletScanContext:
    root: Path
    modes: Dict[str, bool]
    exclude: List[str]
    thresholds: Dict[str, int]
    progress_cb: Optional[Callable] = None
    phase_cb: Optional[Callable] = None
    page: Optional["ft.Page"] = None
    log_list: Optional["ft.ListView"] = None


def _run_flet_phases(
    ctx: FletScanContext,
    functions: List[FunctionRecord],
    classes: List[ClassRecord],
    results: Dict[str, Any],
) -> None:
    phase_cb = ctx.phase_cb

    _phases = [
        ("smells", lambda: _phase_smells(functions, classes, ctx.thresholds, results)),
        ("duplicates", lambda: _phase_duplicates(functions, results)),
        ("lint", lambda: _phase_lint(ctx.root, ctx.exclude, results)),
        ("security", lambda: _phase_security(ctx.root, ctx.exclude, results)),
        ("typecheck", lambda: _phase_typecheck(ctx.root, ctx.exclude, results)),
        ("format", lambda: _phase_format(ctx.root, ctx.exclude, results)),
        ("health", lambda: _phase_health(ctx.root, results)),
        ("imports", lambda: _phase_imports(ctx.root, ctx.exclude, results)),
        ("rustify", lambda: _phase_rustify(functions, results)),
        ("ui_compat", lambda: _phase_ui_compat(ctx.root, ctx.exclude, results)),
        ("ui_health", lambda: _phase_ui_health(ctx.root, ctx.exclude, results)),
    ]
    for key, runner in _phases:
        if not ctx.modes.get(key):
            if phase_cb:
                phase_cb(key, PhaseStatus.SKIPPED, 0)
            continue
        if phase_cb:
            phase_cb(key, PhaseStatus.RUNNING, 0)
        t0 = time.time()
        try:
            runner()
            elapsed = time.time() - t0
            if phase_cb:
                phase_cb(key, PhaseStatus.DONE, elapsed)
        except Exception:
            elapsed = time.time() - t0
            if phase_cb:
                phase_cb(key, PhaseStatus.FAILED, elapsed)


def _run_scan(ctx: FletScanContext) -> Dict[str, Any]:
    """Run the full scan pipeline."""
    from Core.ui_bridge import PrintBridge

    if ctx.page is not None:
        set_bridge(
            FletBridge(ctx.page, log_list=ctx.log_list, progress_cb=ctx.progress_cb)
        )

    try:
        results: Dict[str, Any] = {"meta": {}}
        t0 = time.time()

        need_ast = (
            ctx.modes.get("smells")
            or ctx.modes.get("duplicates")
            or ctx.modes.get("rustify")
        )
        functions, classes, errors, file_count = [], [], [], 0

        if need_ast:
            if ctx.phase_cb:
                ctx.phase_cb("_parse", PhaseStatus.RUNNING, 0)
            parse_t0 = time.time()
            functions, classes, errors, file_count = _run_flet_ast_parsing(
                ctx.root, ctx.exclude, ctx.progress_cb, t0
            )
            if ctx.phase_cb:
                ctx.phase_cb("_parse", PhaseStatus.DONE, time.time() - parse_t0)

        results["meta"].update(
            files=file_count,
            functions=len(functions),
            classes=len(classes),
            errors=len(errors),
            error_list=errors[:20],
        )

        if need_ast:
            results["_code_map"] = _collect_code_map(functions)
            results["_functions"] = functions

        _run_flet_phases(ctx, functions, classes, results)

        results["grade"] = compute_grade(results)
        results["meta"]["duration"] = round(time.time() - t0, 2)
        return results

    except Exception as e:
        import traceback

        logger.error(f"Scan pipeline failed: {e}\n{traceback.format_exc()}")
        return {"error": str(e), "traceback": traceback.format_exc()}
    finally:
        if ctx.page is not None:
            set_bridge(PrintBridge())


# ═══════════════════════════════════════════════════════════════════════════════
#  RUST SKETCH GENERATOR
# ═══════════════════════════════════════════════════════════════════════════════


def _generate_rust_sketch(func: FunctionRecord) -> str:
    if not HAS_AUTO_RUSTIFY:
        return f"// auto_rustify not available\nfn {func.name}() {{ todo!() }}"
    try:
        tree = ast.parse(textwrap.dedent(func.code))
        fn_node = next(
            (
                n
                for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            ),
            None,
        )
        if fn_node is None:
            return f"// Could not parse {func.name}"
        params = []
        for arg in fn_node.args.args:
            if arg.arg == "self":
                continue
            rtype = (
                _py_type_to_rust(ast.unparse(arg.annotation))
                if arg.annotation
                else "PyObject"
            )
            params.append(f"{arg.arg}: {rtype}")
        ret = ""
        if fn_node.returns:
            ret = f" -> {_py_type_to_rust(ast.unparse(fn_node.returns))}"
        body = _translate_body(fn_node, "    ")
        kw = "async " if isinstance(fn_node, ast.AsyncFunctionDef) else ""
        sig = f"{kw}fn {func.name}({', '.join(params)}){ret}"
        return f"pub {sig} {{\n{body}\n}}"
    except Exception:
        return f"// Transpiler error for {func.name}\ntodo!()"


# ═══════════════════════════════════════════════════════════════════════════════
#  TAB RENDERERS
# ═══════════════════════════════════════════════════════════════════════════════


def _build_smells_tab(results: Dict[str, Any]) -> ft.Control:
    """Render the Smells analysis tab."""
    summary = results.get("smells", {})
    issues: list = results.get("_smell_issues", [])
    code_map = results.get("_code_map", {})
    if not issues:
        return _empty_result_box()

    metrics = ft.Row(
        [
            metric_tile("", summary.get("total", 0), t("total")),
            metric_tile(
                "[!]", summary.get("critical", 0), t("critical"), ft.Colors.RED_400
            ),
            metric_tile(
                "[~]", summary.get("warning", 0), t("warning"), ft.Colors.AMBER_400
            ),
            metric_tile("", summary.get("info", 0), t("info"), ft.Colors.GREEN_400),
        ],
        spacing=8,
    )

    by_cat = summary.get("by_category", {})
    cat_chart = ft.Container()
    if by_cat:
        cat_data = sorted(by_cat.items(), key=lambda x: -x[1])
        cat_chart = ft.Column(
            [
                section_title(t("by_category")),
                bar_chart([(c, n, "#ff6b6b") for c, n in cat_data[:12]]),
            ],
            spacing=8,
        )

    sorted_issues = sorted(
        issues,
        key=lambda x: (
            0 if x.severity == "critical" else 1 if x.severity == "warning" else 2
        ),
    )[:80]
    issue_tiles = [_build_issue_tile(s, code_map) for s in sorted_issues]

    return ft.Column(
        [
            metrics,
            ft.Divider(color=TH.divider, height=30),
            cat_chart,
            ft.Divider(color=TH.divider, height=20),
            section_title(t("all_issues")),
            ft.ListView(
                controls=issue_tiles,
                expand=True,
                spacing=4,
                padding=5,
                auto_scroll=False,
            ),
        ],
        spacing=10,
        expand=True,
    )


def _build_dup_group_tile(g, code_map):
    """Build one expansion tile for a duplicate group."""
    sim_pct = f"{g.avg_similarity:.0%}"
    func_names = ", ".join(f.get("name", "?") for f in g.functions[:3])
    controls = []
    if g.merge_suggestion:
        controls.append(
            ft.Container(
                content=ft.Text(
                    f"Tip: {g.merge_suggestion}", size=SZ_BODY, italic=True
                ),
                bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.BLUE_200),
                padding=10,
                border_radius=6,
            )
        )
    for f in g.functions:
        loc = f"{f.get('file', '?')}:{f.get('line', '?')}"
        code = code_map.get(loc, code_map.get(f.get("key", ""), ""))
        controls.append(
            ft.Column(
                [
                    ft.Text(
                        f" {loc} — {f.get('name', '?')} ({f.get('size', '?')} lines)",
                        size=SZ_BODY,
                        font_family=MONO_FONT,
                        color=TH.accent,
                    ),
                    ft.Container(
                        content=ft.Text(
                            code[:400] if code else "N/A",
                            font_family=MONO_FONT,
                            size=SZ_SM,
                            selectable=True,
                            color=TH.dim,
                            no_wrap=False,
                        ),
                        bgcolor=TH.code_bg,
                        border_radius=8,
                        padding=10,
                    )
                    if code
                    else ft.Container(),
                ],
                spacing=4,
            )
        )
    return ft.ExpansionTile(
        title=ft.Text(
            f"Group {g.group_id} — {g.similarity_type} ({sim_pct})", size=SZ_MD
        ),
        subtitle=ft.Text(func_names, size=SZ_SM, color=TH.muted),
        controls=[ft.Container(content=ft.Column(controls, spacing=8), padding=12)],
    )


def _build_duplicates_tab(results: Dict[str, Any]) -> ft.Control:
    """Render the Duplicates analysis tab."""
    summary = results.get("duplicates", {})
    groups = results.get("_dup_groups", [])
    code_map = results.get("_code_map", {})

    if not groups:
        return _empty_result_box()

    metrics = ft.Row(
        [
            metric_tile(
                ft.Icon(ft.Icons.SHIELD, size=18, color=TH.accent),
                summary.get("total_groups", 0),
                t("groups"),
            ),
            metric_tile("", summary.get("exact_duplicates", 0), t("exact")),
            metric_tile("", summary.get("near_duplicates", 0), t("near")),
            metric_tile("", summary.get("semantic_duplicates", 0), t("semantic")),
        ],
        spacing=8,
    )
    group_tiles = [_build_dup_group_tile(g, code_map) for g in groups[:50]]

    return ft.Column(
        [
            metrics,
            metric_tile("", summary.get("total_functions_involved", 0), t("involved")),
            ft.Divider(color=TH.divider, height=20),
            ft.ListView(
                controls=group_tiles, expand=True, spacing=4, auto_scroll=False
            ),
        ],
        spacing=10,
        expand=True,
    )


def _build_lint_fix_bar(results, summary, page):
    """Build the auto-fix button + result text for lint tab."""
    fix_result = ft.Text("", size=SZ_BODY)

    def on_auto_fix(_e):
        scan_path = results.get("_scan_path", "")
        if not scan_path:
            fix_result.value = "No scan path available"
            page.update()
            return
        try:
            r = subprocess.run(
                ["ruff", "check", "--fix", scan_path],  # nosec B607
                capture_output=True,
                text=True,
                timeout=60,
            )
            fix_result.value = f"Auto-fix done! {r.stdout.strip()}"
            fix_result.color = ft.Colors.GREEN_400
        except FileNotFoundError:
            fix_result.value = "Ruff not found"
            fix_result.color = ft.Colors.RED_400
        except subprocess.TimeoutExpired:
            fix_result.value = "Timed out"
            fix_result.color = ft.Colors.RED_400
        page.update()

    if summary.get("fixable", 0) > 0:
        return ft.Row(
            [
                ft.Button(
                    f"{t('auto_fix')} ({summary['fixable']})",
                    on_click=on_auto_fix,
                    bgcolor=TH.accent2,
                    color=ft.Colors.WHITE,
                    height=BTN_H_MD,
                    style=ft.ButtonStyle(
                        shape=ft.RoundedRectangleBorder(radius=BTN_RADIUS)
                    ),
                ),
                fix_result,
            ],
            spacing=12,
        )
    return ft.Container()


def _build_lint_issue_tile(s):
    """Build a single expansion tile for a lint issue."""
    icon = SEV_ICONS.get(s.severity, "")
    fix_tag = " " if getattr(s, "fixable", False) else ""
    return ft.ExpansionTile(
        title=ft.Text(
            f"{icon} [{getattr(s, 'rule_code', 'LINT')}] {s.message[:80]}{fix_tag}",
            size=SZ_MD,
        ),
        subtitle=ft.Text(f"{s.file_path}:{s.line}", size=SZ_SM, color=TH.muted),
        controls=[
            ft.Container(
                content=ft.Column(
                    [
                        ft.Text(
                            f"{t('issue')}: {s.message}",
                            weight=ft.FontWeight.BOLD,
                            size=SZ_MD,
                        ),
                        ft.Text(
                            f"{t('fix')}: {s.suggestion}",
                            size=SZ_BODY,
                            color=ft.Colors.BLUE_200,
                        )
                        if s.suggestion
                        else ft.Container(),
                    ]
                ),
                padding=12,
                bgcolor=ft.Colors.with_opacity(0.03, TH.text),
                border_radius=8,
            )
        ],
    )


def _build_lint_tab(results: Dict[str, Any], page: ft.Page) -> ft.Control:
    """Render the Lint analysis tab."""
    summary = results.get("lint", {})
    issues = results.get("_lint_issues", [])

    if summary.get("error"):
        return ft.Text(f"{summary['error']}", color=ft.Colors.AMBER_400, size=SZ_LG)
    if not issues:
        return _empty_result_box()

    metrics = ft.Row(
        [
            metric_tile("", summary.get("total", 0), t("total")),
            metric_tile(
                "[!]", summary.get("critical", 0), t("critical"), ft.Colors.RED_400
            ),
            metric_tile(
                "[~]", summary.get("warning", 0), t("warning"), ft.Colors.AMBER_400
            ),
            metric_tile("", summary.get("fixable", 0), t("auto_fixable"), TH.accent2),
        ],
        spacing=8,
    )

    fix_btn = _build_lint_fix_bar(results, summary, page)

    by_rule = summary.get("by_rule", {})
    rule_chart = ft.Container()
    if by_rule:
        top_rules = sorted(by_rule.items(), key=lambda x: -x[1])[:10]
        rule_chart = ft.Column(
            [
                section_title("Top Rules"),
                bar_chart([(r, c, "#ff9800") for r, c in top_rules]),
            ],
            spacing=8,
        )

    issue_tiles = [_build_lint_issue_tile(s) for s in issues[:100]]

    return ft.Column(
        [
            metrics,
            fix_btn,
            ft.Divider(color=TH.divider, height=20),
            rule_chart,
            ft.Divider(color=TH.divider, height=20),
            section_title(t("all_issues")),
            ft.ListView(
                controls=issue_tiles, expand=True, spacing=4, auto_scroll=False
            ),
        ],
        spacing=10,
        expand=True,
    )


def _build_security_tab(results: Dict[str, Any]) -> ft.Control:
    summary = results.get("security", {})
    issues = results.get("_sec_issues", [])

    if summary.get("error"):
        return ft.Text(f"{summary['error']}", color=ft.Colors.AMBER_400, size=SZ_LG)
    if not issues:
        return ft.Container(
            content=ft.Text(
                f"[ok] {t('no_issues')}", color=ft.Colors.GREEN_400, size=SZ_LG
            ),
            padding=20,
        )

    metrics = ft.Row(
        [
            metric_tile("", summary.get("total", 0), t("total")),
            metric_tile("[!]", summary.get("critical", 0), "High", ft.Colors.RED_400),
            metric_tile(
                "[~]", summary.get("warning", 0), "Medium", ft.Colors.AMBER_400
            ),
        ],
        spacing=8,
    )

    issue_tiles = []
    for s in issues[:100]:
        sev = s.severity
        icon = SEV_ICONS.get(sev, "")
        ctrls = [
            ft.Text(f"{t('issue')}: {s.message}", weight=ft.FontWeight.BOLD, size=SZ_MD)
        ]
        if s.suggestion:
            ctrls.append(
                ft.Text(
                    f"{t('fix')}: {s.suggestion}",
                    size=SZ_BODY,
                    color=ft.Colors.BLUE_200,
                )
            )
        if getattr(s, "confidence", ""):
            ctrls.append(
                ft.Text(f"Confidence: {s.confidence}", size=SZ_SM, color=TH.muted)
            )
        issue_tiles.append(
            ft.ExpansionTile(
                title=ft.Text(
                    f"{icon} [{getattr(s, 'rule_code', '?')}] {s.message[:70]}",
                    size=SZ_MD,
                ),
                subtitle=ft.Text(f"{s.file_path}:{s.line}", size=SZ_SM, color=TH.muted),
                leading=ft.Icon(
                    ft.Icons.SECURITY, color=SEV_COLORS.get(sev, ft.Colors.GREY_400)
                ),
                controls=[
                    ft.Container(
                        content=ft.Column(ctrls),
                        padding=12,
                        bgcolor=ft.Colors.with_opacity(0.03, TH.text),
                        border_radius=8,
                    )
                ],
            )
        )

    return ft.Column(
        [
            metrics,
            ft.Divider(color=TH.divider, height=20),
            section_title(t("all_issues")),
            ft.ListView(
                controls=issue_tiles, expand=True, spacing=4, auto_scroll=False
            ),
        ],
        spacing=10,
        expand=True,
    )


def _build_rustify_candidate(rank, cand, code_map):
    """Build a single expansion tile for a Rust-portability candidate."""
    fn = cand.func
    purity = "Pure" if cand.is_pure else "[!] Impure"
    code = code_map.get(f"{fn.file_path}:{fn.line_start}", code_map.get(fn.key, ""))
    rust_code = _generate_rust_sketch(fn) if code else "// No source"

    ctrls = [
        ft.Row(
            [
                ft.Text(
                    f"Score: {cand.score}",
                    weight=ft.FontWeight.BOLD,
                    color=TH.accent,
                    size=SZ_MD,
                ),
                ft.Text(f"| {purity}", size=SZ_BODY),
                ft.Text(f"| CC={fn.complexity}", size=SZ_BODY, color=TH.dim),
                ft.Text(f"| {fn.size_lines} lines", size=SZ_BODY, color=TH.dim),
            ],
            spacing=8,
        ),
        ft.Text(f" {fn.file_path}:{fn.line_start}", size=SZ_SM, color=TH.muted),
    ]
    if cand.reason:
        ctrls.append(
            ft.Text(
                f"Tip: {cand.reason}",
                size=SZ_SM,
                italic=True,
                color=ft.Colors.AMBER_200,
            )
        )
    if code:
        ctrls.append(
            ft.Row(
                [
                    _code_panel("Python", "PY", code, ft.Colors.AMBER_300),
                    _code_panel("Rust", "RS", rust_code, ft.Colors.CYAN_200),
                ],
                spacing=12,
                expand=True,
            )
        )

    return ft.ExpansionTile(
        title=ft.Text(f"#{rank}  {fn.name}", size=SZ_MD, weight=ft.FontWeight.BOLD),
        subtitle=ft.Text(
            f"Score: {cand.score} | {purity} | CC={fn.complexity}", size=SZ_SM
        ),
        leading=ft.Icon(
            ft.Icons.BOLT, color=(ft.Colors.GREEN_400 if cand.score > 20 else TH.accent)
        ),
        controls=[ft.Container(content=ft.Column(ctrls, spacing=6), padding=12)],
    )


def _build_score_distribution(candidates):
    """Build score distribution chart for Rustify tab."""
    buckets = {"0-5": 0, "5-10": 0, "10-15": 0, "15-20": 0, "20-25": 0, "25+": 0}
    bucket_colors = {
        "0-5": "#ff5722",
        "5-10": "#ff5722",
        "10-15": "#ffd600",
        "15-20": "#ffd600",
        "20-25": "#00c853",
        "25+": "#00c853",
    }
    for c in candidates:
        s = c.score
        bk = (
            "25+"
            if s >= 25
            else "20-25"
            if s >= 20
            else "15-20"
            if s >= 15
            else "10-15"
            if s >= 10
            else "5-10"
            if s >= 5
            else "0-5"
        )
        buckets[bk] += 1

    return ft.Column(
        [
            section_title("Score Distribution"),
            bar_chart([(k, v, bucket_colors[k]) for k, v in buckets.items()]),
        ],
        spacing=8,
    )


def _build_rustify_tab(results: Dict[str, Any]) -> ft.Control:
    """Build the Rust-portability candidate tab."""
    candidates = results.get("_rust_candidates", [])
    summary = results.get("rustify", {})
    code_map = results.get("_code_map", {})

    if not candidates:
        return ft.Text(
            "No Rustify candidates. Need functions with 5+ lines.",
            color=TH.dim,
            size=SZ_LG,
        )

    metrics = ft.Row(
        [
            metric_tile("", summary.get("total_scored", 0), t("scored")),
            metric_tile(
                "[ok]", summary.get("pure_count", 0), t("pure"), ft.Colors.GREEN_400
            ),
            metric_tile("", summary.get("top_score", 0), t("top_score"), TH.accent),
            metric_tile(
                "",
                summary.get("total_scored", 0) - summary.get("pure_count", 0),
                t("impure"),
                ft.Colors.RED_400,
            ),
        ],
        spacing=8,
    )

    cand_tiles = [
        _build_rustify_candidate(rank, cand, code_map)
        for rank, cand in enumerate(candidates[:30], 1)
    ]

    return ft.Column(
        [
            metrics,
            ft.Divider(color=TH.divider, height=20),
            section_title(f" Top Rust Candidates ({min(30, len(candidates))})", ""),
            ft.ListView(controls=cand_tiles, expand=True, spacing=4, auto_scroll=False),
            ft.Divider(color=TH.divider, height=20),
            _build_score_distribution(candidates),
        ],
        spacing=10,
        expand=True,
    )


def _build_heatmap_tab(results: Dict[str, Any]) -> ft.Control:
    file_issues: Counter = Counter()
    sources = [
        ("_smell_issues", "smells"),
        ("_lint_issues", "lint"),
        ("_sec_issues", "security"),
    ]
    for key, cat in sources:
        for s in results.get(key, []):
            file_issues[s.file_path] += 1

    if not file_issues:
        return ft.Text(f"[ok] {t('no_issues')}", color=ft.Colors.GREEN_400, size=SZ_LG)

    ranked = file_issues.most_common(30)
    mx = ranked[0][1] if ranked else 1

    tiles = []
    for fpath, total in ranked:
        pct = total / mx
        color = (
            "#d50000"
            if pct > 0.75
            else "#ff6d00"
            if pct > 0.5
            else "#ffab00"
            if pct > 0.25
            else "#00c853"
        )
        display = fpath if len(fpath) <= 55 else "" + fpath[-52:]
        tiles.append(
            ft.Container(
                content=ft.Row(
                    [
                        ft.Text(
                            f"{display}",
                            size=SZ_BODY,
                            font_family=MONO_FONT,
                            color=TH.dim,
                            expand=True,
                            no_wrap=True,
                            overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                        ft.Container(
                            content=ft.Container(
                                bgcolor=color,
                                border_radius=3,
                                width=max(4, pct * 200),
                                height=12,
                            ),
                            bgcolor=TH.bar_bg,
                            border_radius=3,
                            width=200,
                            height=12,
                            clip_behavior=ft.ClipBehavior.HARD_EDGE,
                        ),
                        ft.Text(
                            str(total),
                            size=SZ_MD,
                            weight=ft.FontWeight.BOLD,
                            font_family=MONO_FONT,
                            width=40,
                            color=color,
                        ),
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=ft.Padding.symmetric(vertical=6, horizontal=10),
                border=ft.Border.only(left=ft.BorderSide(3, color)),
                bgcolor=TH.card,
                border_radius=8,
                margin=ft.Margin.only(bottom=4),
            )
        )

    total_issues = sum(file_issues.values())
    return ft.Column(
        [
            section_title(t("worst_files")),
            ft.Text(
                f"{total_issues} {t('issues_across')} {len(file_issues)} {t('files')}",
                size=SZ_BODY,
                color=TH.muted,
            ),
            ft.ListView(controls=tiles, expand=True, spacing=2, auto_scroll=False),
        ],
        spacing=10,
        expand=True,
    )


_CC_BUCKETS = ("1-3", "4-7", "8-14", "15-24", "25+")
_CC_LIMITS = (25, 15, 8, 4, 1)
_CC_COLORS = {
    "1-3": "#00c853",
    "4-7": "#64dd17",
    "8-14": "#ffd600",
    "15-24": "#ff6d00",
    "25+": "#d50000",
}
_SZ_BUCKETS = ("1-10", "11-25", "26-50", "51-100", "100+")
_SZ_LIMITS = (100, 50, 25, 10, 1)
_SZ_COLORS = {
    "1-10": "#00c853",
    "11-25": "#64dd17",
    "26-50": "#ffd600",
    "51-100": "#ff6d00",
    "100+": "#d50000",
}


def _build_fn_tile(fn, code_map):
    """Build one expansion tile for a function in the complexity tab."""
    cc_color = (
        "#d50000"
        if fn.complexity >= 15
        else "#ff6d00"
        if fn.complexity >= 8
        else "#ffd600"
    )
    code = code_map.get(f"{fn.file_path}:{fn.line_start}", code_map.get(fn.key, ""))
    return ft.ExpansionTile(
        title=ft.Text(f"CC {fn.complexity}  ·  {fn.name}", size=SZ_MD),
        subtitle=ft.Text(
            f"{fn.file_path}:{fn.line_start} ({fn.size_lines} lines)",
            size=SZ_SM,
            color=TH.muted,
        ),
        leading=ft.Container(
            content=ft.Text(
                str(fn.complexity),
                size=SZ_LG,
                weight=ft.FontWeight.BOLD,
                color=cc_color,
                text_align=ft.TextAlign.CENTER,
            ),
            bgcolor=ft.Colors.with_opacity(0.15, cc_color),
            border_radius=8,
            width=36,
            height=36,
            alignment=ft.Alignment(0, 0),
        ),
        controls=[
            ft.Container(
                content=ft.Text(
                    code[:500] if code else "N/A",
                    font_family=MONO_FONT,
                    size=SZ_SM,
                    selectable=True,
                    color=TH.dim,
                    no_wrap=False,
                ),
                bgcolor=TH.code_bg,
                border_radius=8,
                padding=10,
            )
        ]
        if code
        else [],
    )


def _build_complexity_tab(results: Dict[str, Any]) -> ft.Control:
    """Render the Complexity analysis tab."""
    functions: list = results.get("_functions", [])
    if not functions:
        return ft.Text(
            "No functions available. Enable Smells or Duplicates.",
            color=TH.dim,
            size=SZ_LG,
        )

    complexities = [f.complexity for f in functions]
    sizes = [f.size_lines for f in functions]
    avg_cc = sum(complexities) / len(complexities)
    max_cc = max(complexities)
    med_cc = sorted(complexities)[len(complexities) // 2]

    metrics = ft.Row(
        [
            metric_tile("", f"{avg_cc:.1f}", t("avg_complexity")),
            metric_tile("", max_cc, t("max_complexity"), ft.Colors.RED_400),
            metric_tile("", med_cc, "Median CC"),
            metric_tile("", f"{sum(sizes) / len(sizes):.0f}", "Avg Size"),
        ],
        spacing=8,
    )

    cc_buckets = _bucket_values(complexities, _CC_BUCKETS, _CC_LIMITS)
    cc_chart = ft.Column(
        [
            section_title(t("cc_distribution")),
            bar_chart([(k, v, _CC_COLORS[k]) for k, v in cc_buckets.items()]),
        ],
        spacing=8,
    )

    sz_buckets = _bucket_values(sizes, _SZ_BUCKETS, _SZ_LIMITS)
    sz_chart = ft.Column(
        [
            section_title(t("size_distribution")),
            bar_chart(
                [(f"{k} lines", v, _SZ_COLORS[k]) for k, v in sz_buckets.items()]
            ),
        ],
        spacing=8,
    )

    code_map = results.get("_code_map", {})
    top_fns = sorted(functions, key=lambda f: f.complexity, reverse=True)[:15]
    fn_tiles = [_build_fn_tile(fn, code_map) for fn in top_fns]

    return ft.Column(
        [
            metrics,
            ft.Divider(color=TH.divider, height=20),
            cc_chart,
            ft.Divider(color=TH.divider, height=20),
            sz_chart,
            ft.Divider(color=TH.divider, height=20),
            section_title(t("most_complex")),
            ft.ListView(controls=fn_tiles, expand=True, spacing=4, auto_scroll=False),
        ],
        spacing=10,
        expand=True,
    )


def _generate_graph_html(graph: SmartGraph) -> str:
    """Generate a self-contained HTML page with vis-network force graph."""
    import json as _json

    nodes_json = _json.dumps(graph.nodes)
    edges_json = _json.dumps(graph.edges)
    is_dark = TH.is_dark()
    bg = "#0a0e14" if is_dark else "#f6f8fa"
    text_color = "#e6edf3" if is_dark else "#1f2328"
    border_color = "rgba(255,255,255,0.12)" if is_dark else "#d0d7de"
    legend_bg = "rgba(20,24,32,0.85)" if is_dark else "rgba(255,255,255,0.9)"

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:{bg}; font-family:'Segoe UI',sans-serif; overflow:hidden; }}
  #graph {{ width:100vw; height:100vh; }}
  #legend {{
    position:fixed; top:12px; right:12px; padding:12px 16px;
    background:{legend_bg}; border:1px solid {border_color};
    border-radius:10px; font-size:12px; color:{text_color};
    backdrop-filter:blur(8px); z-index:10;
  }}
  #legend h4 {{ margin:0 0 6px; font-size:13px; opacity:0.7; }}
  .dot {{ display:inline-block; width:10px; height:10px;
          border-radius:50%; margin-right:6px; vertical-align:middle; }}
  #controls {{
    position:fixed; bottom:12px; left:12px; display:flex; gap:6px; z-index:10;
  }}
  #controls button {{
    background:{legend_bg}; border:1px solid {border_color};
    border-radius:6px; padding:6px 12px; cursor:pointer;
    font-size:12px; color:{text_color};
  }}
  #controls button:hover {{ border-color:#00d4ff; }}
  #info {{
    position:fixed; top:12px; left:12px; padding:8px 12px;
    background:{legend_bg}; border:1px solid {border_color};
    border-radius:8px; font-size:11px; color:{text_color};
    opacity:0.7; z-index:10;
  }}
</style>
</head>
<body>
<div id="graph"></div>
<div id="legend">
  <h4>Health</h4>
  <div><span class="dot" style="background:#2ecc71"></span> Healthy</div>
  <div><span class="dot" style="background:#f39c12"></span> Warning</div>
  <div><span class="dot" style="background:#e74c3c"></span> Critical</div>
  <div style="margin-top:6px; opacity:0.6; font-size:11px;">
    Lines = duplicate pairs<br>Node size = function lines
  </div>
</div>
<div id="info">Scroll to zoom · Drag to pan · Click node to focus</div>
<div id="controls">
  <button onclick="network.fit()">Fit All</button>
  <button onclick="network.stabilize(100)">Stabilize</button>
</div>
<script>
var nodes = new vis.DataSet({nodes_json});
var edges = new vis.DataSet({edges_json});
var container = document.getElementById('graph');
var data = {{ nodes: nodes, edges: edges }};
var options = {{
  nodes: {{
    shape:'dot', font:{{ size:12, color:'{text_color}', face:'Segoe UI' }},
    borderWidth:1, borderWidthSelected:3,
    shadow:{{ enabled:true, size:8, color:'rgba(0,0,0,0.3)' }},
    scaling:{{ min:8, max:40, label:{{ enabled:true, min:10, max:18 }} }}
  }},
  edges: {{
    color:{{ color:'rgba(0,212,255,0.25)', highlight:'#00d4ff', hover:'#00d4ff' }},
    smooth:{{ type:'continuous' }}, width:1.5, hoverWidth:3,
    selectionWidth:3
  }},
  physics: {{
    stabilization:{{ enabled:true, iterations:200 }},
    barnesHut:{{
      gravitationalConstant:-15000,
      centralGravity:0.4,
      springLength:180,
      springConstant:0.02,
      damping:0.12,
      avoidOverlap:0.3
    }}
  }},
  interaction: {{
    hover:true, tooltipDelay:150, zoomView:true,
    dragView:true, navigationButtons:false
  }},
  groups: {{
    healthy:  {{ color:{{ background:'#2ecc71', border:'#27ae60' }} }},
    warning:  {{ color:{{ background:'#f39c12', border:'#e67e22' }} }},
    critical: {{ color:{{ background:'#e74c3c', border:'#c0392b' }} }}
  }}
}};
// Map health to group for vis-network
nodes.forEach(function(n) {{
  n.group = n.health || 'healthy';
  n.value = n.size || 10;
}});
nodes.update(nodes.get());
var network = new vis.Network(container, data, options);
network.once('stabilizationIterationsDone', function() {{
  network.setOptions({{ physics:{{ stabilization:false }} }});
}});
</script>
</body>
</html>"""


def _layout_nodes_concentric(nodes: list):
    """Position nodes in concentric rings by health: criticalinner, healthyouter."""
    import math

    groups = {"healthy": [], "warning": [], "critical": []}
    for i, node in enumerate(nodes):
        groups.get(node.get("health", "healthy"), groups["healthy"]).append(i)
    n = len(nodes)
    x, y = [0.0] * n, [0.0] * n
    for health, radius in [("critical", 0.15), ("warning", 0.40), ("healthy", 0.75)]:
        indices = groups.get(health, [])
        count = len(indices)
        for j, idx in enumerate(indices):
            angle = 2 * math.pi * j / max(count, 1) + (hash(health) % 100) * 0.01
            x[idx] = 0.5 + radius * 0.45 * math.cos(angle)
            y[idx] = 0.5 + radius * 0.45 * math.sin(angle)
    return x, y, groups


def _build_graph_canvas(graph: SmartGraph) -> ft.Control:
    """Build an in-app Canvas preview of the codebase health graph."""
    import flet.canvas as cv

    node_x, node_y, groups = _layout_nodes_concentric(graph.nodes)
    id_to_idx = {node["id"]: i for i, node in enumerate(graph.nodes)}

    health_colors = {"healthy": "#2ecc71", "warning": "#f39c12", "critical": "#e74c3c"}

    def _paint(canvas: cv.Canvas, event: cv.CanvasResizeEvent):
        w, h = event.width, event.height

        # Draw edges first (underneath)
        for edge in graph.edges:
            src, dst = id_to_idx.get(edge.get("from")), id_to_idx.get(edge.get("to"))
            if src is not None and dst is not None:
                canvas.shapes.append(
                    cv.Line(
                        node_x[src] * w,
                        node_y[src] * h,
                        node_x[dst] * w,
                        node_y[dst] * h,
                        paint=ft.Paint(
                            color="rgba(0,212,255,0.15)",
                            stroke_width=1,
                            style=ft.PaintingStyle.STROKE,
                        ),
                    )
                )

        # Draw nodes
        for i, node in enumerate(graph.nodes):
            color = health_colors.get(node.get("health", "healthy"), "#2ecc71")
            size = max(3, min(14, node.get("size", 10) / 5))
            cx, cy = node_x[i] * w, node_y[i] * h

            # Glow
            canvas.shapes.append(
                cv.Circle(
                    cx,
                    cy,
                    size + 3,
                    paint=ft.Paint(color=f"{color}30", style=ft.PaintingStyle.FILL),
                )
            )
            # Dot
            canvas.shapes.append(
                cv.Circle(
                    cx,
                    cy,
                    size,
                    paint=ft.Paint(color=color, style=ft.PaintingStyle.FILL),
                )
            )

            # Label for larger nodes
            if size >= 5 and len(graph.nodes) < 200:
                canvas.shapes.append(
                    cv.Text(
                        cx + size + 3,
                        cy - 5,
                        node.get("label", ""),
                        style=ft.TextStyle(size=8, color=TH.dim),
                    )
                )

        canvas.update()

    return cv.Canvas(on_resize=_paint, expand=True)


def _build_graph_metrics(graph) -> ft.Row:
    """Build the top metrics row for the graph tab."""
    healthy = sum(1 for n in graph.nodes if n.get("health") == "healthy")
    warning = sum(1 for n in graph.nodes if n.get("health") == "warning")
    critical = sum(1 for n in graph.nodes if n.get("health") == "critical")

    return ft.Row(
        [
            metric_tile("", healthy, "Healthy", ft.Colors.GREEN_400),
            metric_tile("[~]", warning, "Warning", ft.Colors.AMBER_400),
            metric_tile("[!]", critical, "Critical", ft.Colors.RED_400),
            metric_tile("", len(graph.edges), "Dup Links", TH.accent),
        ],
        spacing=8,
    )


def _build_graph_group_chart(graph) -> ft.Control:
    """Build the 'per-group breakdown' bar chart for the graph tab."""
    group_counts = Counter(
        str(Path(n.get("group", ".")).name) or "root" for n in graph.nodes
    )
    top_groups = group_counts.most_common(10)
    if not top_groups:
        return ft.Container()
    return bar_chart([(g, c, TH.accent) for g, c in top_groups])


def _build_graph_tab(results: Dict[str, Any], page: ft.Page) -> ft.Control:
    """Build the codebase health graph tab with interactive HTML viewer."""
    functions = results.get("_functions", [])
    smells = results.get("_smell_issues", [])
    dup_groups = results.get("_dup_groups", [])

    if not functions:
        return ft.Text(
            "No functions available. Enable Smells or Duplicates.",
            color=TH.dim,
            size=SZ_LG,
        )

    graph = SmartGraph()
    graph.build(functions, smells, dup_groups or [], Path("."))

    metrics = _build_graph_metrics(graph)

    # Write full interactive HTML graph
    html_content = _generate_graph_html(graph)
    graph_dir = ROOT / "_scratch"
    graph_dir.mkdir(exist_ok=True)
    graph_file = graph_dir / "_graph_view.html"
    graph_file.write_text(html_content, encoding="utf-8")

    def _open_graph(_e):
        page.launch_url(graph_file.as_uri())

    group_chart = _build_graph_group_chart(graph)

    # Canvas preview
    canvas_preview = ft.Container(
        content=_build_graph_canvas(graph),
        height=400,
        expand=True,
        bgcolor=TH.code_bg,
        border=ft.Border.all(1, TH.border),
        border_radius=12,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
    )

    return ft.Column(
        [
            glass_card(
                ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Text(
                                    " Codebase Health Graph",
                                    size=SZ_H3,
                                    weight=ft.FontWeight.BOLD,
                                    font_family=MONO_FONT,
                                    color=TH.accent,
                                ),
                                ft.Container(expand=True),
                                ft.Button(
                                    " Open Interactive Graph",
                                    on_click=_open_graph,
                                    bgcolor=TH.accent2,
                                    color=ft.Colors.WHITE,
                                    height=BTN_H_SM,
                                    style=ft.ButtonStyle(
                                        shape=ft.RoundedRectangleBorder(
                                            radius=BTN_RADIUS
                                        )
                                    ),
                                ),
                            ],
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Text(
                            "Nodes = functions (green/orange/red) · "
                            "Edges = duplicate links · "
                            "Size = function lines",
                            size=SZ_BODY,
                            color=TH.muted,
                        ),
                    ]
                )
            ),
            metrics,
            ft.Divider(color=TH.divider, height=12),
            canvas_preview,
            ft.Divider(color=TH.divider, height=12),
            section_title("Components"),
            group_chart,
        ],
        spacing=10,
        expand=True,
        scroll=ft.ScrollMode.ADAPTIVE,
    )


def _run_nexus_pipeline(results, page, status_text, progress_bar, trans_results_col):
    scan_path = results.get("_scan_path", "")
    if not scan_path:
        status_text.value = "Select directory first"
        page.update()
        return
    progress_bar.visible = True
    status_text.value = "Starting Nexus Orchestrator..."
    status_text.color = TH.dim
    trans_results_col.controls.clear()
    page.update()

    try:

        def cb(num, total):
            progress_bar.value = num / max(1, total)
            page.update()

        orchestrator = NexusOrchestrator(Path(scan_path))

        status_text.value = "Building Graph..."
        page.update()

        transpiler_path = Path(scan_path) / "Analysis" / "transpiler.py"
        files_to_scan = (
            [transpiler_path]
            if transpiler_path.exists()
            else list(Path(scan_path).rglob("*.py"))[:10]
        )
        orchestrator.build_context_graph(files_to_scan, progress_cb=cb)

        status_text.value = f"Transpiling {len(orchestrator.graph_index.get('bottlenecks', []))} bottlenecks..."
        progress_bar.value = 0
        page.update()
        res = orchestrator.run_transpilation_pipeline("x-ray", progress_cb=cb)

        status_text.value = "Verifying Generated Rust with Cargo..."
        progress_bar.value = 0
        page.update()
        verified = orchestrator.verify_and_build(res, progress_cb=cb)

        status_text.value = f"[ok] Nexus Pipeline complete! {len(verified)}/{len(res)} passed Cargo Check."
        status_text.color = ft.Colors.GREEN_400

        for r in res:
            color = (
                ft.Colors.GREEN_400
                if r.get("status") == "success"
                else ft.Colors.RED_400
            )
            trans_results_col.controls.append(
                ft.Text(f"{r.get('function')}: {r.get('status')}", color=color)
            )

    except Exception as ex:
        status_text.value = f"Error: {ex}"
        status_text.color = ft.Colors.RED_400

    progress_bar.visible = False
    page.update()


def _build_nexus_tab(results: Dict[str, Any], page: ft.Page) -> ft.Control:
    status_text = ft.Text("", size=SZ_MD, color=TH.dim)
    prog_bar = ft.ProgressBar(
        width=500, color=TH.accent, bgcolor=TH.card, value=0, visible=False
    )
    trans_results_col = ft.Column(scroll=ft.ScrollMode.ADAPTIVE, height=300)

    btn = ft.Button(
        " Run Nexus Mode Orchestrator",
        on_click=lambda e: _run_nexus_pipeline(
            results, page, status_text, prog_bar, trans_results_col
        ),
        bgcolor=TH.accent2,
        color=ft.Colors.WHITE,
        height=BTN_H_MD,
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=BTN_RADIUS)),
    )

    return ft.Column(
        [
            glass_card(
                ft.Column(
                    [
                        ft.Text(
                            " Nexus Mode Orchestrator",
                            size=SZ_H3,
                            weight=ft.FontWeight.BOLD,
                            font_family=MONO_FONT,
                            color=TH.accent,
                        ),
                        ft.Text(
                            "Knowledge graph-based transpilation and autonomous verification.",
                            size=SZ_BODY,
                            color=TH.muted,
                        ),
                    ]
                )
            ),
            ft.Divider(color=TH.divider, height=20),
            ft.Row([btn, status_text], spacing=12),
            prog_bar,
            ft.Container(
                content=trans_results_col,
                padding=10,
                bgcolor=TH.bg,
                border=ft.Border.all(1, TH.border),
                border_radius=8,
                expand=True,
            ),
        ],
        spacing=10,
        expand=True,
    )


def _run_rustify_pipeline(results, page, status_text, progress_bar, error_log=None):
    """Execute the auto-rustify pipeline, updating UI widgets."""
    scan_path = results.get("_scan_path", "")
    if not scan_path:
        status_text.value = t("select_dir_first")
        page.update()
        return
    progress_bar.visible = True
    status_text.value = "Running pipeline..."
    if error_log is not None:
        error_log.value = ""
        error_log.visible = False
    page.update()
    try:

        def cb(frac, label):
            progress_bar.value = min(frac, 1.0)
            status_text.value = label
            page.update()

        output_dir = Path(scan_path) / "_rustified"
        pipeline = RustifyPipeline(
            project_dir=scan_path,
            output_dir=str(output_dir),
            crate_name="xray_rustified",
            min_score=5.0,
            max_candidates=30,
            mode="pyo3",
        )
        report = pipeline.run(progress_cb=cb)
        ok = report.compile_result and report.compile_result.success
        status_text.value = (
            "[ok] Pipeline complete -- compiled!"
            if ok
            else "[!] Pipeline finished with issues"
        )
        status_text.color = ft.Colors.GREEN_400 if ok else ft.Colors.AMBER_400
        # Show full compile error log if compilation failed
        if not ok and error_log is not None:
            stderr = ""
            if report.compile_result and hasattr(report.compile_result, "stderr"):
                stderr = report.compile_result.stderr or ""
            elif report.errors:
                stderr = "\n".join(report.errors)
            if stderr:
                error_log.value = stderr
                error_log.visible = True
    except Exception as ex:
        status_text.value = f"[X] Error: {ex}"
        status_text.color = ft.Colors.RED_400
        if error_log is not None:
            import traceback

            error_log.value = traceback.format_exc()
            error_log.visible = True
    progress_bar.visible = False
    page.update()


def _build_auto_rustify_tab(results: Dict[str, Any], page: ft.Page) -> ft.Control:
    """Render the Auto-Rustify pipeline tab."""
    if not HAS_AUTO_RUSTIFY:
        return ft.Text(
            "auto_rustify module not available.", color=ft.Colors.AMBER_400, size=SZ_LG
        )

    sys_profile = detect_system()
    sys_row = ft.Row(
        [
            metric_tile(
                ft.Icon(ft.Icons.COMPUTER, size=18, color=TH.accent),
                sys_profile.os_name,
                "OS",
            ),
            metric_tile(
                ft.Icon(ft.Icons.MEMORY, size=18, color=TH.accent),
                sys_profile.arch,
                "Arch",
            ),
            metric_tile(
                ft.Icon(ft.Icons.ADS_CLICK, size=18, color=TH.accent),
                sys_profile.rust_target.split("-")[0],
                "Target",
            ),
        ],
        spacing=8,
    )

    status_text = ft.Text("", size=SZ_MD, color=TH.dim)
    prog_bar = ft.ProgressBar(
        width=500, color=TH.accent, bgcolor=TH.card, value=0, visible=False
    )
    # Full scrollable Cargo error log — hidden until compilation fails
    error_log = ft.TextField(
        value="",
        multiline=True,
        read_only=True,
        visible=False,
        min_lines=6,
        max_lines=20,
        text_style=ft.TextStyle(font_family=MONO_FONT),
        text_size=SZ_SM,
        bgcolor=TH.code_bg,
        border_color=ft.Colors.RED_400,
        color=ft.Colors.RED_200,
        label="Cargo compile errors",
        expand=True,
    )

    return ft.Column(
        [
            glass_card(
                ft.Column(
                    [
                        ft.Text(
                            f"{t('tab_auto_rustify')} Pipeline",
                            size=SZ_H3,
                            weight=ft.FontWeight.BOLD,
                            font_family=MONO_FONT,
                            color=TH.accent,
                        ),
                        ft.Text(
                            "End-to-end: Scan -> Score -> Transpile -> "
                            "Compile -> Verify",
                            size=SZ_BODY,
                            color=TH.muted,
                        ),
                    ]
                )
            ),
            sys_row,
            ft.Divider(color=TH.divider, height=20),
            ft.Row(
                [
                    ft.Button(
                        t("run_pipeline"),
                        icon=ft.Icons.ROCKET_LAUNCH,
                        on_click=lambda e: _run_rustify_pipeline(
                            results, page, status_text, prog_bar, error_log
                        ),
                        bgcolor=TH.accent2,
                        color=ft.Colors.WHITE,
                        height=BTN_H_MD,
                        style=ft.ButtonStyle(
                            shape=ft.RoundedRectangleBorder(radius=BTN_RADIUS)
                        ),
                    ),
                    status_text,
                ],
                spacing=12,
            ),
            prog_bar,
            error_log,
        ],
        spacing=10,
    )


def _build_ui_health_tab(results):
    """Render the UI Health tab (Analyzer #10)."""
    health = results.get("ui_health")
    issues = results.get("_ui_health_issues", [])

    if not health or isinstance(health, dict) and health.get("error"):
        return _empty_state("", "UI Health Analysis Failed or Skipped")

    if not issues:
        return _empty_state(
            "",
            "No UI Health Issues Found",
            "All tested UI components are structurally sound and well-connected.",
        )

    list_view = ft.ListView(expand=True, spacing=8, padding=16)

    # Info banner
    list_view.controls.append(
        ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.INFO_OUTLINE, color=TH.accent),
                    ft.Text(
                        f"Found {len(issues)} structural/behavioral UI issue(s).",
                        color=TH.text,
                        weight=ft.FontWeight.W_500,
                    ),
                ]
            ),
            bgcolor=ft.Colors.with_opacity(0.1, TH.accent),
            border_radius=8,
            padding=16,
            margin=ft.Margin.only(bottom=8),
        )
    )

    for issue in issues:
        icon_color = SEV_COLORS.get(issue.severity, TH.muted)
        icon_name = SEV_ICONS.get(issue.severity, ft.Icons.ERROR)

        tile = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(icon_name, color=icon_color, size=20),
                            ft.Text(
                                f"{issue.name} -- {issue.rule_code}",
                                color=TH.text,
                                weight=ft.FontWeight.BOLD,
                            ),
                            ft.Container(expand=True),
                            ft.Text(
                                f"{issue.file_path}:{issue.line}",
                                color=TH.dim,
                                size=SZ_SM,
                            ),
                        ]
                    ),
                    ft.Text(issue.message, color=TH.muted, size=SZ_MD),
                    (
                        ft.Text(
                            f"Tip: {issue.suggestion}",
                            color=TH.accent,
                            size=SZ_SM,
                            italic=True,
                        )
                        if issue.suggestion
                        else ft.Container()
                    ),
                ],
                spacing=4,
            ),
            bgcolor=TH.surface,
            border_radius=8,
            padding=12,
            border=ft.Border.only(left=ft.BorderSide(4, icon_color)),
        )
        list_view.controls.append(tile)

    return list_view


def _build_ui_compat_issue_tile(r):
    """Build one expansion tile for a UI-compat issue."""
    icon = SEV_ICONS.get("critical", "[!]")
    ctrls = [
        ft.Text(
            f"{t('issue')}: '{r.bad_kwarg}' is not valid for {r.call.resolved_name}()",
            weight=ft.FontWeight.BOLD,
            size=SZ_MD,
        ),
    ]
    if r.suggestion:
        ctrls.append(
            ft.Text(
                f"{t('fix')}: {r.suggestion}", size=SZ_BODY, color=ft.Colors.BLUE_200
            )
        )
    if r.accepted:
        top = sorted(r.accepted - {"self"})[:15]
        ctrls.append(
            ft.Text(
                f"Accepted: {', '.join(top)}" + (" …" if len(r.accepted) > 15 else ""),
                size=SZ_SM,
                color=TH.dim,
                font_family=MONO_FONT,
            )
        )
    if r.call.source_snippet:
        ctrls.append(
            ft.Container(
                content=ft.Text(
                    r.call.source_snippet[:400],
                    font_family=MONO_FONT,
                    size=SZ_SM,
                    color=TH.dim,
                    selectable=True,
                    no_wrap=False,
                ),
                bgcolor=TH.code_bg,
                border_radius=8,
                padding=10,
                margin=ft.Margin.only(top=6),
            )
        )
    return ft.ExpansionTile(
        title=ft.Text(f"{icon} {r.call.resolved_name}.{r.bad_kwarg}", size=SZ_MD),
        subtitle=ft.Text(
            f"{r.call.file_path}:{r.call.line}", size=SZ_SM, color=TH.muted
        ),
        leading=ft.Icon(ft.Icons.MONITOR, color=ft.Colors.RED_400),
        controls=[
            ft.Container(
                content=ft.Column(ctrls),
                padding=12,
                bgcolor=ft.Colors.with_opacity(0.03, TH.text),
                border_radius=8,
            )
        ],
        expanded=False,
    )


def _build_sorted_chart(data_dict, title, icon, color):
    """Build a sorted bar chart section from a dict."""
    if not data_dict:
        return ft.Container()
    items = sorted(data_dict.items(), key=lambda x: -x[1])
    return ft.Column(
        [section_title(title, icon), bar_chart([(k, n, color) for k, n in items[:12]])],
        spacing=8,
    )


def _build_ui_compat_tab(results: Dict[str, Any]) -> ft.Control:
    """Render the UI compatibility analysis tab."""
    summary = results.get("ui_compat", {})
    raw_issues = results.get("_ui_compat_raw", [])

    if summary.get("error"):
        return ft.Text(f"{summary['error']}", color=ft.Colors.AMBER_400, size=SZ_LG)
    if not raw_issues:
        return _empty_result_box("all UI calls compatible")

    metrics = ft.Row(
        [
            metric_tile("", summary.get("total", 0), t("total")),
            metric_tile(
                "[!]", summary.get("critical", 0), t("critical"), ft.Colors.RED_400
            ),
            metric_tile("", len(summary.get("by_widget", {})), "Widgets"),
            metric_tile("", len(summary.get("by_file", {})), "Files"),
        ],
        spacing=8,
    )

    kw_chart = _build_sorted_chart(
        summary.get("bad_kwargs", {}), "Bad kwargs", "", "#ff6b6b"
    )
    widget_chart = _build_sorted_chart(
        summary.get("by_widget", {}), "By widget", "", "#ffa502"
    )
    issue_tiles = [_build_ui_compat_issue_tile(r) for r in raw_issues[:100]]

    return ft.Column(
        [
            glass_card(
                ft.Column(
                    [
                        ft.Text(
                            f"{t('tab_ui_compat')}",
                            size=SZ_H3,
                            weight=ft.FontWeight.BOLD,
                            font_family=MONO_FONT,
                            color=TH.accent,
                        ),
                        ft.Text(
                            "Validates UI framework kwargs against live API signatures",
                            size=SZ_BODY,
                            color=TH.muted,
                        ),
                    ]
                )
            ),
            metrics,
            ft.Divider(color=TH.divider, height=20),
            kw_chart,
            widget_chart,
            ft.Divider(color=TH.divider, height=20),
            section_title(t("all_issues")),
            ft.ListView(
                controls=issue_tiles, expand=True, spacing=4, auto_scroll=False
            ),
        ],
        spacing=10,
        expand=True,
    )


# ════════════════════════════════════════════════════════════════════════════════════════════
#  ONBOARDING DIALOG
# ════════════════════════════════════════════════════════════════════════════════════════════════════

_ONBOARD_ICONS = ("1", "2", "3", "4", "5")


def _make_step_dots(n, idx):
    """Build the step-indicator dot row (— current, ○ others)."""
    dots = [
        ft.Text(
            "" if i == idx else "",
            size=SZ_SM if i == idx else SZ_XS,
            color=TH.accent if i == idx else TH.muted,
        )
        for i in range(n)
    ]
    return ft.Row(dots, spacing=6, alignment=ft.MainAxisAlignment.CENTER)


def _update_onboard(st, page):
    """Refresh onboard dialog to reflect current step."""
    i, steps, w = st["idx"], st["steps"], st["w"]
    w["icon"].value = steps[i][2]
    w["title"].value = steps[i][0]
    w["desc"].value = steps[i][1]
    w["label"].value = f"{i + 1} / {st['n']}"
    w["dots"].controls = _make_step_dots(st["n"], i).controls
    if i > 0:
        w["back"].text = t("onboard_back")
        w["back"].on_click = lambda e: _on_back_onboard(st, page)
    else:
        w["back"].text = t("onboard_skip")
        w["back"].on_click = lambda e: page.pop_dialog()
    w["next"].text = t("onboard_got_it") if i == st["n"] - 1 else t("onboard_next")
    page.update()


def _on_next_onboard(st, page):
    """Advance onboarding by one step or close."""
    if st["idx"] >= st["n"] - 1:
        page.pop_dialog()
        return
    st["idx"] += 1
    _update_onboard(st, page)


def _on_back_onboard(st, page):
    """Go back one onboarding step."""
    if st["idx"] > 0:
        st["idx"] -= 1
        _update_onboard(st, page)


def _show_onboarding(page: ft.Page):
    """Display the 5-step onboarding tutorial dialog."""
    steps = [
        (t(f"onboard_step{i}_title"), t(f"onboard_step{i}_desc"), _ONBOARD_ICONS[i - 1])
        for i in range(1, 6)
    ]
    n = len(steps)
    st = {"steps": steps, "n": n, "idx": 0, "w": {}}
    w = st["w"]
    w["icon"] = ft.Text(steps[0][2], size=SZ_H2, text_align=ft.TextAlign.CENTER)
    w["title"] = ft.Text(
        steps[0][0], size=SZ_LG, weight=ft.FontWeight.W_600, color=TH.accent
    )
    w["desc"] = ft.Text(steps[0][1], size=SZ_BODY, color=TH.dim, no_wrap=False)
    w["dots"] = _make_step_dots(n, 0)
    w["label"] = ft.Text(f"1 / {n}", size=SZ_XS, color=TH.muted)
    w["back"] = ft.TextButton(
        t("onboard_skip"),
        on_click=lambda e: page.pop_dialog(),
        style=ft.ButtonStyle(color=TH.muted),
    )
    w["next"] = ft.Button(
        t("onboard_next"),
        on_click=lambda e: _on_next_onboard(st, page),
        bgcolor=TH.accent,
        color=ft.Colors.WHITE,
        height=BTN_H_SM,
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=BTN_RADIUS)),
    )

    dlg = ft.AlertDialog(
        modal=True,
        title=ft.Row(
            [
                ft.Text("", size=SZ_H3),
                ft.Text(
                    t("onboard_title"),
                    size=SZ_H3,
                    weight=ft.FontWeight.BOLD,
                    color=TH.accent,
                ),
            ],
            spacing=8,
        ),
        content=ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [w["icon"], w["title"]],
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    w["desc"],
                    ft.Container(height=8),
                    w["dots"],
                    w["label"],
                    ft.Container(height=4),
                    ft.Row(
                        [w["back"], w["next"]],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                ],
                spacing=6,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                tight=True,
            ),
            width=400,
            padding=ft.Padding.symmetric(horizontal=8, vertical=4),
        ),
        actions=[],
        shape=ft.RoundedRectangleBorder(radius=14),
    )
    page.show_dialog(dlg)


# ════════════════════════════════════════════════════════════════════════════════════════════════════
#  EXTRACTED HELPERS FOR main()
# ═══════════════════════════════════════════════════════════════════════════════════════════════════


def _build_grade_card(grade, narrow):
    """Build the grade display card for the dashboard header."""
    letter = grade.get("letter", "?")
    score = grade.get("score", 0)
    color = GRADE_COLORS.get(letter, "#888")
    # Circular progress ring around the grade letter
    ring = ft.Stack(
        [
            ft.Container(
                content=ft.ProgressRing(
                    value=score / 100.0,
                    width=110,
                    height=110,
                    stroke_width=6,
                    color=color,
                    bgcolor=ft.Colors.with_opacity(0.15, color),
                ),
                alignment=ft.Alignment(0, 0),
            ),
            ft.Container(
                content=ft.Text(
                    letter,
                    size=SZ_DISPLAY,
                    weight=ft.FontWeight.BOLD,
                    color=color,
                    text_align=ft.TextAlign.CENTER,
                    font_family=MONO_FONT,
                ),
                width=110,
                height=110,
                alignment=ft.Alignment(0, 0),
            ),
        ],
        width=110,
        height=110,
    )
    return ft.Container(
        content=ft.Column(
            [
                ring,
                ft.Text(
                    f"{score:.1f} / 100",
                    size=SZ_SECTION,
                    color=ft.Colors.with_opacity(0.8, color),
                    text_align=ft.TextAlign.CENTER,
                ),
                ft.Text(
                    t("quality_score").upper(),
                    size=SZ_SM,
                    color=TH.muted,
                    text_align=ft.TextAlign.CENTER,
                ),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=6,
        ),
        bgcolor=ft.Colors.with_opacity(0.06, color),
        border=ft.Border.all(1, ft.Colors.with_opacity(0.3, color)),
        border_radius=18,
        padding=24,
        width=None if narrow else 200,
        expand=narrow,
        shadow=ft.BoxShadow(blur_radius=24, color=ft.Colors.with_opacity(0.12, color)),
        animate=ft.Animation(500, ft.AnimationCurve.EASE_OUT),
    )


def _build_penalty_chips(breakdown):
    """Build penalty chip controls from the grade breakdown."""
    labels_map = {
        "smells": "Smells",
        "duplicates": "Dups",
        "lint": "Lint",
        "security": "Sec",
        "typecheck": "Types",
        "format": "Format",
        "health": "Health",
        "imports": "Imports",
    }
    chips = []
    for k, d in breakdown.items():
        p = d.get("penalty", 0)
        if p > 0:
            chips.append(
                ft.Container(
                    content=ft.Text(
                        f"{labels_map.get(k, k)} -{p:.0f}", size=SZ_SM, color=TH.text
                    ),
                    bgcolor=TH.chip,
                    border_radius=16,
                    padding=ft.Padding.symmetric(horizontal=10, vertical=4),
                    border=ft.Border.all(1, TH.border),
                )
            )
    return chips


_TAB_BUILDERS = [
    ("smells", "tab_smells", lambda r, _p: _build_smells_tab(r)),
    ("duplicates", "tab_duplicates", lambda r, _p: _build_duplicates_tab(r)),
    ("lint", "tab_lint", lambda r, p: _build_lint_tab(r, p)),
    ("security", "tab_security", lambda r, _p: _build_security_tab(r)),
    ("rustify", "tab_rustify", lambda r, _p: _build_rustify_tab(r)),
    ("ui_compat", "tab_ui_compat", lambda r, _p: _build_ui_compat_tab(r)),
    ("ui_health", "UI Health", lambda r, _p: _build_ui_health_tab(r)),
]


def _build_result_tabs(results, page):
    """Build the tab bar and tab panels for the results dashboard."""
    tab_panels = []
    tab_names = []

    for key, label_key, builder in _TAB_BUILDERS:
        data = results.get(key)
        if data and not (isinstance(data, dict) and data.get("error")):
            tab_names.append(t(label_key))
            tab_panels.append(builder(results, page))

    has_issues = (
        results.get("_smell_issues")
        or results.get("_lint_issues")
        or results.get("_sec_issues")
    )
    if has_issues:
        tab_names.append(t("tab_heatmap"))
        tab_panels.append(_build_heatmap_tab(results))
    if results.get("_functions"):
        tab_names.append(t("tab_complexity"))
        tab_panels.append(_build_complexity_tab(results))
        tab_names.append("Graph")
        tab_panels.append(_build_graph_tab(results, page))
        tab_names.append(t("tab_auto_rustify"))
        tab_panels.append(_build_auto_rustify_tab(results, page))
        tab_names.append("Nexus Mode")
        tab_panels.append(_build_nexus_tab(results, page))

    panel_container = ft.Column(
        [tab_panels[0]] if tab_panels else [], spacing=0, expand=True
    )

    selected = [0]

    def _on_pill_click(idx):
        def handler(e):
            selected[0] = idx
            panel_container.controls = [tab_panels[idx]]
            # Update pill styles
            for i, pill in enumerate(pill_row.controls):
                is_sel = i == idx
                pill.bgcolor = TH.accent if is_sel else TH.card
                pill.content.color = ft.Colors.WHITE if is_sel else TH.dim
            page.update()

        return handler

    pills = []
    for i, name in enumerate(tab_names):
        is_sel = i == 0
        pill = ft.Container(
            content=ft.Text(
                name,
                size=SZ_SM,
                weight=ft.FontWeight.BOLD if is_sel else ft.FontWeight.NORMAL,
                color=ft.Colors.WHITE if is_sel else TH.dim,
            ),
            bgcolor=TH.accent if is_sel else TH.card,
            border_radius=20,
            padding=ft.Padding.symmetric(horizontal=14, vertical=6),
            on_click=_on_pill_click(i),
            animate=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
        )
        pills.append(pill)

    pill_row = ft.Row(pills, spacing=6, scroll=ft.ScrollMode.AUTO)

    if not tab_names:
        return ft.Container()
    return ft.Column(
        [
            pill_row,
            panel_container,
        ],
        expand=True,
        spacing=8,
    )


def _build_export_bar(page, state, results):
    """Build JSON and Markdown export buttons."""

    def on_export_json(e):
        try:
            export = {k: v for k, v in results.items() if not k.startswith("_")}
            path = Path(state["root_path"]) / "xray_report.json"
            path.write_text(json.dumps(export, indent=2, default=str), encoding="utf-8")
            _show_snack(page, f" Saved to {path}")
        except Exception as exc:
            _show_snack(page, f" Export failed: {exc}", bgcolor=ft.Colors.RED_400)

    def on_export_md(e):
        try:
            md = _build_markdown_report(results)
            path = Path(state["root_path"]) / "xray_report.md"
            path.write_text(md, encoding="utf-8")
            _show_snack(page, f" Saved to {path}")
        except Exception as exc:
            _show_snack(page, f" Export failed: {exc}", bgcolor=ft.Colors.RED_400)

    gen_test_status = ft.Text("", size=SZ_SM, color=TH.dim)

    def on_gen_tests(e):
        scan_path = state.get("root_path", "")
        if not scan_path:
            _show_snack(page, t("select_dir_first"), bgcolor=ft.Colors.RED_400)
            return
        gen_test_status.value = " Generating tests…"
        gen_test_status.color = TH.dim
        page.update()
        try:
            cmd = [
                sys.executable,
                str(ROOT / "x_ray_claude.py"),
                "--path",
                scan_path,
                "--gen-tests",
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)  # nosec B603
            out_dir = Path(scan_path) / "tests" / "xray_generated"
            if proc.returncode == 0:
                gen_test_status.value = f"[ok] Tests generated  {out_dir}"
                gen_test_status.color = ft.Colors.GREEN_400
                _show_snack(page, f"[ok] Tests written to {out_dir}")
            else:
                gen_test_status.value = "[!] Generation finished with warnings"
                gen_test_status.color = ft.Colors.AMBER_400
        except subprocess.TimeoutExpired:
            gen_test_status.value = "[X] Timed out (120 s)"
            gen_test_status.color = ft.Colors.RED_400
        except Exception as exc:
            gen_test_status.value = f"[X] {exc}"
            gen_test_status.color = ft.Colors.RED_400
        page.update()

    return ft.Column(
        [
            ft.Row(
                [
                    ft.Button(
                        f"{t('export_json')}",
                        on_click=on_export_json,
                        bgcolor=TH.card,
                        color=TH.text,
                        height=BTN_H_SM,
                        style=ft.ButtonStyle(
                            shape=ft.RoundedRectangleBorder(radius=BTN_RADIUS)
                        ),
                    ),
                    ft.Button(
                        f"{t('export_markdown')}",
                        on_click=on_export_md,
                        bgcolor=TH.card,
                        color=TH.text,
                        height=BTN_H_SM,
                        style=ft.ButtonStyle(
                            shape=ft.RoundedRectangleBorder(radius=BTN_RADIUS)
                        ),
                    ),
                    ft.Button(
                        " Generate Tests",
                        on_click=on_gen_tests,
                        bgcolor=TH.surface,
                        color=TH.accent,
                        height=BTN_H_SM,
                        style=ft.ButtonStyle(
                            shape=ft.RoundedRectangleBorder(radius=BTN_RADIUS),
                            side=ft.BorderSide(1, TH.accent),
                        ),
                    ),
                ],
                spacing=12,
                scroll=ft.ScrollMode.AUTO,
            ),
            gen_test_status,
        ],
        spacing=4,
    )


def _build_main_dashboard(page, state, main_content, results):
    """Build the full results dashboard (grade card + tabs + export bar)."""
    narrow = is_narrow(page)
    grade = results.get("grade", {})
    meta = results.get("meta", {})

    grade_card = _build_grade_card(grade, narrow)

    stats = ft.Row(
        [
            metric_tile(
                ft.Icon(ft.Icons.DESCRIPTION, size=18, color=TH.accent),
                meta.get("files", 0),
                t("files"),
            ),
            metric_tile(
                ft.Icon(ft.Icons.FUNCTIONS, size=18, color=TH.accent),
                meta.get("functions", 0),
                t("functions"),
            ),
            metric_tile(
                ft.Icon(ft.Icons.INVENTORY_2, size=18, color=TH.accent),
                meta.get("classes", 0),
                t("classes"),
            ),
            metric_tile(
                ft.Icon(ft.Icons.TIMER, size=18, color=TH.accent),
                f"{meta.get('duration', 0):.1f}s",
                t("duration"),
            ),
        ],
        spacing=8,
        scroll=ft.ScrollMode.AUTO,
    )

    penalty_chips = _build_penalty_chips(grade.get("breakdown", {}))

    if narrow:
        header = ft.Column(
            [
                grade_card,
                stats,
                (
                    ft.Row(penalty_chips, spacing=6, scroll=ft.ScrollMode.AUTO)
                    if penalty_chips
                    else ft.Container()
                ),
            ],
            spacing=12,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )
    else:
        header = ft.Row(
            [
                grade_card,
                ft.Column(
                    [
                        stats,
                        (
                            ft.Row(penalty_chips, spacing=6, scroll=ft.ScrollMode.AUTO)
                            if penalty_chips
                            else ft.Container()
                        ),
                    ],
                    expand=True,
                    spacing=10,
                ),
            ],
            spacing=20,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )

    result_tabs = _build_result_tabs(results, page)
    export_bar = _build_export_bar(page, state, results)

    # Switch main_content from scroll mode to expand mode for the dashboard.
    # Tab panels handle their own internal scrolling via ListView.
    main_content.scroll = None
    main_content.controls = [
        ft.Container(  # header block — natural height
            content=ft.Column(
                [
                    header,
                    ft.Divider(color=TH.divider, height=1),
                ],
                spacing=10,
            ),
            padding=ft.Padding.only(left=30, right=30, top=30, bottom=10),
            bgcolor=TH.bg,
        ),
        ft.Container(  # tab block — expands to fill remaining space
            content=result_tabs,
            expand=True,
            padding=ft.Padding.symmetric(horizontal=30),
            bgcolor=TH.bg,
        ),
        ft.Container(  # export bar — natural height at bottom
            content=export_bar,
            padding=ft.Padding.only(left=30, right=30, bottom=20, top=10),
            bgcolor=TH.bg,
        ),
    ]
    page.update()


def _landing_card(card_spec, width=240):
    """Build one of the 3-step instruction cards on the landing page."""
    icon, icon_color, step, title, desc = card_spec
    return ft.Container(
        content=ft.Column(
            [
                ft.Container(
                    content=ft.Icon(icon, color=icon_color, size=28),
                    bgcolor=ft.Colors.with_opacity(0.10, icon_color),
                    border_radius=14,
                    width=56,
                    height=56,
                    alignment=ft.Alignment(0, 0),
                    shadow=ft.BoxShadow(
                        blur_radius=12, color=ft.Colors.with_opacity(0.12, icon_color)
                    ),
                ),
                ft.Container(
                    content=ft.Text(
                        str(step),
                        size=SZ_XS,
                        color=icon_color,
                        weight=ft.FontWeight.BOLD,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    width=22,
                    height=22,
                    border_radius=11,
                    bgcolor=ft.Colors.with_opacity(0.12, icon_color),
                    alignment=ft.Alignment(0, 0),
                ),
                ft.Text(title, weight=ft.FontWeight.BOLD, size=SZ_LG, color=TH.text),
                ft.Text(
                    desc, size=SZ_BODY, color=TH.muted, text_align=ft.TextAlign.CENTER
                ),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=8,
        ),
        bgcolor=TH.card,
        border=ft.Border.all(1, TH.border),
        border_radius=16,
        padding=24,
        width=width,
        shadow=ft.BoxShadow(blur_radius=10, color=TH.shadow),
        animate=ft.Animation(300, ft.AnimationCurve.EASE_OUT),
    )


def _build_landing_hero():
    """Build the animated X-RAY logo + subtitle for the landing page."""
    # Glow ring behind the icon
    glow = ft.Container(
        content=ft.Icon(ft.Icons.SEARCH, size=40, color=TH.accent),
        width=90,
        height=90,
        border_radius=45,
        alignment=ft.Alignment(0, 0),
        bgcolor=ft.Colors.with_opacity(0.08, TH.accent),
        border=ft.Border.all(2, ft.Colors.with_opacity(0.2, TH.accent)),
        shadow=ft.BoxShadow(
            blur_radius=30,
            spread_radius=5,
            color=ft.Colors.with_opacity(0.15, TH.accent),
        ),
    )

    return ft.Container(
        content=ft.Column(
            [
                glow,
                ft.Text(
                    "X-RAY",
                    size=SZ_HERO,
                    weight=ft.FontWeight.BOLD,
                    color=TH.accent,
                    font_family=MONO_FONT,
                    text_align=ft.TextAlign.CENTER,
                ),
                ft.Text(
                    t("app_subtitle"),
                    size=SZ_LG,
                    color=TH.muted,
                    text_align=ft.TextAlign.CENTER,
                ),
                ft.Container(height=4),
                ft.Text(
                    f"v{__version__}",
                    size=SZ_XS,
                    color=TH.muted,
                    text_align=ft.TextAlign.CENTER,
                ),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=4,
        ),
        animate=ft.Animation(600, ft.AnimationCurve.EASE_OUT),
    )


_LANDING_CARDS = [
    (
        ft.Icons.FOLDER_OPEN,
        "accent",
        1,
        "Configure",
        "Set project path &\nchoose analyzers",
    ),
    (
        ft.Icons.PLAY_ARROW_ROUNDED,
        "accent2",
        2,
        "Scan",
        "One-click full\ncodebase analysis",
    ),
    (ft.Icons.INSIGHTS, "#00c853", 3, "Explore", "Graph, heatmap &\ninteractive tabs"),
]

_FEATURE_CHIPS = [
    ("", "AST Smells"),
    ("", "Ruff Lint"),
    ("", "Bandit Security"),
    ("", "Duplicates"),
    ("", "Rust Advisor"),
    ("", "Force Graph"),
    ("", "Heatmap"),
    ("", "Complexity"),
]


def _build_main_landing(page, main_content):
    """Build the welcome / landing page with feature showcase."""
    narrow = is_narrow(page)
    cw = 200 if narrow else 240
    color_map = {"accent": TH.accent, "accent2": TH.accent2}
    cards = []
    for icon, clr, step, title, desc in _LANDING_CARDS:
        real_clr = color_map.get(clr, clr)
        real_desc = desc or f"Press '{t('scan_start')}'\nto analyze code"
        cards.append(_landing_card((icon, real_clr, step, title, real_desc), cw))

    cards_layout = (
        ft.Column(cards, spacing=12, horizontal_alignment=ft.CrossAxisAlignment.CENTER)
        if narrow
        else ft.Row(cards, spacing=16, alignment=ft.MainAxisAlignment.CENTER)
    )

    # Feature chip row
    chips = ft.Row(
        [
            ft.Container(
                content=ft.Row(
                    [
                        ft.Text(ic, size=SZ_SM),
                        ft.Text(lbl, size=SZ_SM, color=TH.dim),
                    ],
                    spacing=4,
                    tight=True,
                ),
                bgcolor=TH.chip,
                border_radius=20,
                border=ft.Border.all(1, TH.border),
                padding=ft.Padding.symmetric(horizontal=10, vertical=5),
            )
            for ic, lbl in _FEATURE_CHIPS
        ],
        spacing=6,
        scroll=ft.ScrollMode.AUTO,
        alignment=ft.MainAxisAlignment.CENTER,
    )

    main_content.scroll = ft.ScrollMode.AUTO
    main_content.controls = [
        ft.Container(
            content=ft.Column(
                [
                    ft.Container(height=20 if narrow else 40),
                    _build_landing_hero(),
                    ft.Container(height=20 if narrow else 30),
                    cards_layout,
                    ft.Container(height=20),
                    chips,
                    ft.Container(height=20),
                    ft.TextButton(
                        "– Show Tutorial", on_click=lambda _: _show_onboarding(page)
                    ),
                    ft.Container(height=30),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=8,
            ),
            padding=ft.Padding.symmetric(horizontal=20, vertical=0),
            bgcolor=TH.bg,
            alignment=ft.Alignment(0, -1),
        )
    ]


def _build_phase_row(key, label, status, elapsed=0):
    """Build a single phase row with icon, label, and status suffix."""
    if status == PhaseStatus.RUNNING:
        icon = ft.ProgressRing(width=14, height=14, stroke_width=2, color=TH.accent)
        text_color = TH.accent
        suffix = ""
    elif status == PhaseStatus.DONE:
        icon = ft.Icon(ft.Icons.CHECK_CIRCLE, size=16, color=ft.Colors.GREEN_400)
        text_color = ft.Colors.GREEN_400
        suffix = f"  {elapsed:.1f}s" if elapsed > 0 else ""
    elif status == PhaseStatus.FAILED:
        icon = ft.Icon(ft.Icons.ERROR, size=16, color=ft.Colors.RED_400)
        text_color = ft.Colors.RED_400
        suffix = "  failed"
    elif status == PhaseStatus.SKIPPED:
        icon = ft.Icon(ft.Icons.REMOVE, size=16, color=TH.muted)
        text_color = TH.muted
        suffix = "  skipped"
    else:
        icon = ft.Container(width=16, height=16)
        text_color = TH.dim
        suffix = ""
    return ft.Container(
        content=ft.Row(
            [
                icon,
                ft.Text(label, size=SZ_SM, color=text_color),
                ft.Container(expand=True),
                ft.Text(suffix, size=SZ_XS, color=TH.muted)
                if suffix
                else ft.Container(),
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.Padding.symmetric(horizontal=24, vertical=4),
        animate=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
    )


def _build_phase_checklist(phase_rows_container, modes):
    """Build the full scanning checklist screen."""
    return ft.Container(
        content=ft.Column(
            [
                ft.Container(height=40),
                ft.Text(
                    "SCANNING",
                    size=SZ_H2,
                    weight=ft.FontWeight.BOLD,
                    color=TH.accent,
                    font_family=MONO_FONT,
                    text_align=ft.TextAlign.CENTER,
                ),
                ft.Container(height=16),
                phase_rows_container,
                ft.Container(height=20),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=4,
        ),
        padding=ft.Padding.symmetric(horizontal=20, vertical=0),
        bgcolor=TH.bg,
        alignment=ft.Alignment(0, -1),
    )


def _build_scan_error_screen(exc):
    """Build the scan-failed error panel."""
    return ft.Container(
        content=ft.Column(
            [
                ft.Container(height=80),
                ft.Icon(ft.Icons.ERROR_OUTLINE, size=48, color=ft.Colors.RED_400),
                ft.Text(
                    "Scan Failed",
                    size=SZ_H2,
                    weight=ft.FontWeight.BOLD,
                    color=ft.Colors.RED_400,
                    text_align=ft.TextAlign.CENTER,
                ),
                ft.Text(
                    str(exc)[:300],
                    size=SZ_BODY,
                    color=TH.dim,
                    text_align=ft.TextAlign.CENTER,
                    no_wrap=False,
                ),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=8,
        ),
        padding=30,
        bgcolor=TH.bg,
        alignment=ft.Alignment(0, -1),
    )


def _build_scan_complete_screen(results):
    """Build the brief scan-success summary panel."""
    meta = results.get("meta", {})
    dur = meta.get("duration", 0)
    n_files = meta.get("files", 0)
    n_funcs = meta.get("functions", 0)
    return ft.Container(
        content=ft.Column(
            [
                ft.Container(height=80),
                ft.Icon(ft.Icons.CHECK_CIRCLE, size=48, color=ft.Colors.GREEN_400),
                ft.Text(
                    t("scan_complete"),
                    size=SZ_H2,
                    weight=ft.FontWeight.BOLD,
                    color=ft.Colors.GREEN_400,
                    text_align=ft.TextAlign.CENTER,
                ),
                ft.Text(
                    f"{n_files} {t('files')} \u00b7 "
                    f"{n_funcs} {t('functions')} \u00b7 "
                    f"{dur:.1f}s",
                    size=SZ_SECTION,
                    color=TH.dim,
                    text_align=ft.TextAlign.CENTER,
                ),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=8,
        ),
        padding=ft.Padding.symmetric(horizontal=20, vertical=0),
        bgcolor=TH.bg,
        alignment=ft.Alignment(0, -1),
        animate=ft.Animation(400, ft.AnimationCurve.EASE_OUT),
    )


def _prepare_scan_ui(page, state, main_content, phase_rows_container, modes):
    """Set sidebar status to scanning and show phase checklist."""
    sidebar_status = state.get("_sidebar_status")
    if sidebar_status:
        sidebar_status.content = ft.Row(
            [
                ft.ProgressRing(width=16, height=16, stroke_width=2, color=TH.accent),
                ft.Text(t("scanning"), size=SZ_SM, color=TH.accent, italic=True),
            ],
            spacing=6,
        )

    main_content.controls = [_build_phase_checklist(phase_rows_container, modes)]
    page.update()


def _finalize_scan_ui(page, state, main_content, results):
    """Store results and show scan-complete screen."""
    results["_scan_path"] = state["root_path"]
    state["results"] = results

    sidebar_status = state.get("_sidebar_status")
    if sidebar_status:
        sidebar_status.content = None

    main_content.controls = [_build_scan_complete_screen(results)]
    page.update()


async def _start_scan_handler(page, state, main_content, build_dashboard_fn):
    """Run scan with phase checklist, then show dashboard."""
    if not state["root_path"]:
        _show_snack(page, t("select_dir_first"), bgcolor=ft.Colors.RED_400)
        return

    modes = state["modes"]
    # Build phase state tracking
    phase_states: Dict[str, tuple] = {}
    for key, label in PHASE_REGISTRY:
        phase_states[key] = (PhaseStatus.PENDING, 0)
    phase_states["_parse"] = (PhaseStatus.PENDING, 0)

    phase_rows_container = ft.Column([], spacing=0)

    def _refresh_phase_rows():
        """Rebuild phase row controls from current phase_states."""
        rows = []
        # AST parse row
        ps, el = phase_states.get("_parse", (PhaseStatus.PENDING, 0))
        rows.append(_build_phase_row("_parse", "AST Parsing", ps, el))
        for key, label in PHASE_REGISTRY:
            ps, el = phase_states.get(key, (PhaseStatus.PENDING, 0))
            rows.append(_build_phase_row(key, label, ps, el))
        phase_rows_container.controls = rows

    def phase_cb(key, status, elapsed):
        phase_states[key] = (status, elapsed)
        _refresh_phase_rows()
        try:
            page.update()
        except Exception:
            pass

    _refresh_phase_rows()
    _prepare_scan_ui(page, state, main_content, phase_rows_container, modes)

    try:
        loop = asyncio.get_event_loop()
        ctx = FletScanContext(
            root=Path(state["root_path"]),
            modes=state["modes"],
            exclude=state["exclude"],
            thresholds=state["thresholds"],
            progress_cb=None,
            phase_cb=phase_cb,
            page=page,
            log_list=state.get("log_list"),
        )
        results = await loop.run_in_executor(None, lambda: _run_scan(ctx))
    except Exception as exc:
        sidebar_status = state.get("_sidebar_status")
        if sidebar_status:
            sidebar_status.content = None
        main_content.controls = [_build_scan_error_screen(exc)]
        page.update()
        return

    if "error" in results:
        sidebar_status = state.get("_sidebar_status")
        if sidebar_status:
            sidebar_status.content = None
        main_content.controls = [
            _build_scan_error_screen(results.get("error", "Unknown error"))
        ]
        page.update()
        return

    _finalize_scan_ui(page, state, main_content, results)

    await asyncio.sleep(0.8)
    build_dashboard_fn(results)


def _sidebar_header(theme_icon, lang_dd):
    """Build the sidebar logo + theme/language row."""
    glow_logo = ft.Container(
        content=ft.Text(
            "X-RAY",
            size=SZ_SIDEBAR,
            weight=ft.FontWeight.BOLD,
            color=TH.accent,
            font_family=MONO_FONT,
            text_align=ft.TextAlign.CENTER,
        ),
        bgcolor=ft.Colors.with_opacity(0.05, TH.accent),
        border_radius=12,
        padding=ft.Padding.symmetric(horizontal=10, vertical=6),
    )
    return [
        ft.Container(
            content=ft.Column(
                [
                    glow_logo,
                    ft.Text(
                        t("app_subtitle").upper(),
                        size=SZ_XS,
                        color=TH.muted,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    ft.Text(
                        f"v{__version__}",
                        size=SZ_XS,
                        color=TH.muted,
                        text_align=ft.TextAlign.CENTER,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=2,
            ),
            padding=ft.Padding.only(top=16, bottom=4),
        ),
        ft.Row(
            [
                theme_icon,
                ft.Container(expand=True),
                ft.Icon(ft.Icons.LANGUAGE, size=SZ_LG, color=TH.muted),
                lang_dd,
            ],
            spacing=4,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        ft.Divider(color=TH.divider, height=16),
    ]


def _sidebar_footer():
    """Build the sidebar footer with credits link."""
    return [
        ft.Container(expand=True),
        ft.Divider(color=TH.divider),
        ft.Text(
            "AST \u00b7 Ruff \u00b7 Bandit \u00b7 Rust \u00b7 UI",
            size=SZ_XS,
            color=TH.muted,
            text_align=ft.TextAlign.CENTER,
        ),
        ft.TextButton(
            "github.com/GeoHaber/X_Ray",
            url="https://github.com/GeoHaber/X_Ray",
            style=ft.ButtonStyle(color=TH.muted),
        ),
    ]


def _build_app_sidebar(sidebar_cfg):
    """Build the left sidebar Container from *sidebar_cfg* dict."""
    p = sidebar_cfg
    header = _sidebar_header(p["theme_icon"], p["lang_dd"])
    footer = _sidebar_footer()
    return ft.Container(
        content=ft.Column(
            header
            + [
                ft.Text(
                    t("project_scope").upper(),
                    size=SZ_SM,
                    weight=ft.FontWeight.BOLD,
                    color=TH.muted,
                ),
                ft.Container(height=2),
                ft.Button(
                    t("select_directory"),
                    icon=ft.Icons.FOLDER_OPEN,
                    on_click=p["pick_directory"],
                    width=260,
                    color=TH.accent,
                    bgcolor=TH.card,
                    style=ft.ButtonStyle(
                        shape=ft.RoundedRectangleBorder(radius=BTN_RADIUS)
                    ),
                ),
                p["path_text"],
                *([p["recent_dd"]] if p.get("recent_dd") is not None else []),
                ft.Divider(color=TH.divider, height=12),
                ft.Text(
                    t("scan_modes").upper(),
                    size=SZ_SM,
                    weight=ft.FontWeight.BOLD,
                    color=TH.muted,
                ),
                p["mode_checks"],
                ft.Divider(color=TH.divider, height=12),
                ft.Container(
                    content=ft.Button(
                        t("scan_start"),
                        width=260,
                        icon=ft.Icons.BOLT,
                        height=48,
                        color=ft.Colors.WHITE,
                        bgcolor=TH.accent2,
                        style=ft.ButtonStyle(
                            shape=ft.RoundedRectangleBorder(radius=12)
                        ),
                        on_click=p["start_scan"],
                    ),
                    shadow=ft.BoxShadow(
                        blur_radius=16,
                        spread_radius=2,
                        color=ft.Colors.with_opacity(0.25, TH.accent2),
                    ),
                ),
                ft.Container(height=4),
                p["sidebar_status"],
            ]
            + footer,
            scroll=ft.ScrollMode.AUTO,
            spacing=6,
        ),
        width=280,
        bgcolor=TH.surface,
        border=ft.Border.only(right=ft.BorderSide(1, TH.border)),
        padding=ft.Padding.symmetric(horizontal=12, vertical=8),
    )


def _build_mode_checks(state):
    """Build the mode-toggle checkboxes column with grouped sections."""

    def on_mode(e):
        state["modes"][e.control.data] = e.control.value

    _m = state["modes"]

    def _cb(key, label):
        return ft.Checkbox(
            label=label,
            value=_m.get(key, True),
            on_change=on_mode,
            data=key,
            fill_color=TH.accent,
            check_color=ft.Colors.WHITE,
        )

    def _header(text):
        return ft.Text(text, size=SZ_XS, weight=ft.FontWeight.BOLD, color=TH.muted)

    all_keys = list(_m.keys())
    checkboxes_ref: list = []

    def _toggle_all(e):
        val = e.control.value
        for k in all_keys:
            _m[k] = val
        for cb in checkboxes_ref:
            cb.value = val
        e.control.page.update()

    toggle = ft.Checkbox(
        label="All / None",
        value=all(v for v in _m.values()),
        on_change=_toggle_all,
        fill_color=TH.accent2,
        check_color=ft.Colors.WHITE,
    )

    cbs_quality = [
        _cb("smells", t("smells")),
        _cb("duplicates", t("duplicates")),
        _cb("lint", t("lint")),
    ]
    cbs_sec = [
        _cb("security", t("security")),
        _cb("typecheck", "Type Check"),
        _cb("format", "Format"),
    ]
    cbs_arch = [
        _cb("health", "Project Health"),
        _cb("imports", "Import Health"),
        _cb("rustify", t("rustify")),
        _cb("ui_compat", t("ui_compat")),
        _cb("ui_health", "UI Health"),
    ]

    checkboxes_ref.extend(cbs_quality + cbs_sec + cbs_arch)

    return ft.Column(
        [
            toggle,
            ft.Divider(color=TH.divider, height=4),
            _header("Code Quality"),
            *cbs_quality,
            _header("Security & Types"),
            *cbs_sec,
            _header("Architecture"),
            *cbs_arch,
        ],
        spacing=0,
    )


def _build_theme_lang_controls(page, main_fn):
    """Build theme toggle icon and language dropdown."""
    theme_icon = ft.IconButton(
        icon=(ft.Icons.LIGHT_MODE if TH.is_dark() else ft.Icons.DARK_MODE),
        icon_color=TH.accent,
        tooltip="Toggle Light / Dark",
        icon_size=20,
    )

    def on_theme_toggle(e):
        TH.toggle()
        page.data["_onboarded"] = True
        try:
            page.pop_dialog()
        except Exception:  # nosec B110
            pass
        page.controls.clear()
        page.run_task(main_fn, page)

    theme_icon.on_click = on_theme_toggle

    def on_lang_change(e):
        set_locale(e.control.value)
        page.data = page.data or {}
        page.data["_onboarded"] = True
        try:
            page.pop_dialog()
        except Exception:  # nosec B110
            pass
        page.controls.clear()
        page.run_task(main_fn, page)

    lang_dd = ft.Dropdown(
        value=get_locale(),
        width=120,
        dense=True,
        border_color=TH.border,
        color=TH.text,
        options=[ft.dropdown.Option(key=k, text=f"{v}") for k, v in LOCALES.items()],
        on_select=on_lang_change,
    )
    return theme_icon, lang_dd


def _setup_page(page):
    """Configure page-level appearance & theme settings."""

    def on_error(e):
        logger.error("Flet page error: %s", e.data)

    page.on_error = on_error
    page.title = t("app_title")
    page.theme_mode = ft.ThemeMode.DARK if TH.is_dark() else ft.ThemeMode.LIGHT
    page.bgcolor = TH.bg
    page.window.width = 1360
    page.window.height = 880
    page.padding = 0
    page.spacing = 0
    page.horizontal_alignment = ft.CrossAxisAlignment.STRETCH
    # Register emoji font so Flutter renders emoji correctly on Windows
    _emoji_font_path = "C:/Windows/Fonts/seguiemj.ttf"  # Segoe UI Emoji
    page.fonts = {
        "mono": "Cascadia Code",
        "emoji": _emoji_font_path,
    }
    page.theme = ft.Theme(
        color_scheme_seed=TH.accent,
        font_family="Segoe UI, Segoe UI Emoji, Roboto, Helvetica, Arial, sans-serif",
    )
    page.dark_theme = ft.Theme(
        color_scheme_seed=TH.accent,
        font_family="Segoe UI, Segoe UI Emoji, Roboto, Helvetica, Arial, sans-serif",
    )


_DEFAULT_EXCLUDES = [
    ".venv",
    "venv",
    "__pycache__",
    ".git",
    "_OLD",
    "node_modules",
    "target",
    "build_exe",
    "build_web",
    "build_desktop",
    "X_Ray_Desktop",
    "X_Ray_Standalone",
    "_scratch",
    ".github",
    "_generated_tests",
    "tests/xray_generated",
    "tests",
    "_archive",
    "X_Ray_Rust_Full",
    "dist",
    "build",
    ".eggs",
    ".mypy_cache",
    ".pytest_cache",
]


_SETTINGS_FILE = Path(__file__).parent / "xray_settings.json"
_MAX_RECENT = 5


def _load_settings() -> dict:
    """Load persisted settings; returns {} on any error."""
    try:
        data = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_settings(settings: dict) -> None:
    """Write settings atomically; silently ignores write errors."""
    try:
        _SETTINGS_FILE.write_text(
            json.dumps(settings, indent=2, default=str), encoding="utf-8"
        )
    except Exception:
        pass


def _push_recent_path(path: str) -> None:
    """Prepend *path* to the recent_paths list, keeping at most _MAX_RECENT entries."""
    s = _load_settings()
    recent: list = s.get("recent_paths", [])
    if path in recent:
        recent.remove(path)
    recent.insert(0, path)
    s["recent_paths"] = recent[:_MAX_RECENT]
    _save_settings(s)


def _init_state(page):
    """Initialise or retrieve persisted scan state from page.data."""
    page.data = page.data or {}
    if "_state" not in page.data:
        page.data["_state"] = {
            "root_path": "",
            "results": None,
            "exclude": list(_DEFAULT_EXCLUDES),
            "modes": {
                "smells": True,
                "duplicates": True,
                "lint": True,
                "security": True,
                "typecheck": False,
                "format": True,
                "health": True,
                "imports": True,
                "rustify": True,
                "ui_compat": True,
                "ui_health": True,
            },
            "thresholds": SMELL_THRESHOLDS.copy(),
        }
    else:
        # Merge any new default excludes into existing state
        existing = set(page.data["_state"].get("exclude", []))
        for exc in _DEFAULT_EXCLUDES:
            if exc not in existing:
                page.data["_state"]["exclude"].append(exc)
    return page.data["_state"]


def _build_responsive_layout(page, sidebar, main_content, theme_icon):
    """Return (layout_control, narrow_flag) for the current viewport."""
    narrow = is_narrow(page)
    main_area = ft.Container(content=main_content, bgcolor=TH.bg, expand=True)
    if narrow:
        drawer = ft.NavigationDrawer(controls=[sidebar], bgcolor=TH.surface)
        page.drawer = drawer

        def open_drawer(e):
            page.show_drawer(drawer)

        hamburger = ft.IconButton(
            icon=ft.Icons.MENU,
            icon_color=TH.accent,
            icon_size=28,
            tooltip="Menu",
            on_click=open_drawer,
        )
        top_bar = ft.Container(
            content=ft.Row(
                [
                    hamburger,
                    ft.Text(
                        "X-RAY",
                        size=SZ_H3,
                        weight=ft.FontWeight.BOLD,
                        color=TH.accent,
                        font_family=MONO_FONT,
                    ),
                    ft.Container(expand=True),
                    theme_icon,
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=TH.surface,
            border=ft.Border.only(bottom=ft.BorderSide(1, TH.border)),
            padding=ft.Padding.symmetric(horizontal=8, vertical=4),
        )
        layout = ft.Column([top_bar, main_area], expand=True, spacing=0)
    else:
        layout = ft.Row([sidebar, main_area], expand=True, spacing=0)
    return layout, narrow


def _install_resize_handler(page, main_fn):
    """Wire up a responsive-resize handler that rebuilds on breakpoint change."""
    narrow = is_narrow(page)
    page.data["_was_narrow"] = narrow
    _resize_guard = {"busy": False}

    def on_resize(e):
        if _resize_guard["busy"]:
            return
        try:
            new_narrow = is_narrow(page)
            old_narrow = page.data.get("_was_narrow")
            if old_narrow is not None and new_narrow != old_narrow:
                _resize_guard["busy"] = True
                page.data["_onboarded"] = True
                page.data["_was_narrow"] = new_narrow
                page.controls.clear()
                page.run_task(main_fn, page)
                return
            page.data["_was_narrow"] = new_narrow
        except Exception:  # nosec B110
            pass
        finally:
            _resize_guard["busy"] = False

    page.on_resized = on_resize


async def _setup_main_state(page: ft.Page):
    """Initialize state and file picker for the main app."""
    state = _init_state(page)

    # Load persisted recent paths into state so sidebar can see them
    settings = _load_settings()
    state.setdefault("recent_paths", settings.get("recent_paths", []))
    # Restore last-used path if the current session hasn't set one yet
    if not state["root_path"] and state["recent_paths"]:
        state["root_path"] = state["recent_paths"][0]

    file_picker = ft.FilePicker()
    if not any(isinstance(s, ft.FilePicker) for s in page.services):
        page.services.append(file_picker)

    _prev_path = state.get("root_path", "")
    path_text = ft.Text(
        _prev_path or t("no_dir_selected"),
        color=TH.accent if _prev_path else TH.muted,
        size=SZ_BODY,
        italic=not bool(_prev_path),
        max_lines=2,
        overflow=ft.TextOverflow.ELLIPSIS,
    )

    def _apply_path(p: str):
        """Update state + UI for a newly selected path and persist it."""
        state["root_path"] = p
        path_text.value = p
        path_text.color = TH.accent
        path_text.italic = False
        _push_recent_path(p)
        state["recent_paths"] = _load_settings().get("recent_paths", [])

    async def pick_directory(e):
        result = await file_picker.get_directory_path(
            dialog_title=t("select_directory")
        )
        if result:
            _apply_path(result)
            page.update()

    return state, path_text, pick_directory, _apply_path


def _build_main_ui(page: ft.Page, state: dict, path_text, pick_directory, apply_path):
    """Build the top-level Flet UI layout and wire up scan events."""
    mode_checks = _build_mode_checks(state)
    theme_icon, lang_dd = _build_theme_lang_controls(page, main)
    main_content = ft.Column(
        [],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
    )

    sidebar_status = ft.Container(content=None)
    state["_sidebar_status"] = sidebar_status

    def build_dashboard(results):
        _build_main_dashboard(page, state, main_content, results)

    async def start_scan(e):
        await _start_scan_handler(page, state, main_content, build_dashboard)

    # Build recent-paths dropdown (only if we have any history)
    recent = state.get("recent_paths", [])
    if recent:

        def _on_recent_pick(e):
            chosen = e.control.value
            if chosen:
                apply_path(chosen)
                page.update()

        recent_dd = ft.Dropdown(
            label="Recent paths",
            options=[
                ft.dropdown.Option(
                    key=p, text=p if len(p) <= 38 else "\u2026" + p[-35:]
                )
                for p in recent
            ],
            value=state["root_path"] if state["root_path"] in recent else None,
            on_select=_on_recent_pick,
            bgcolor=TH.card,
            border_color=TH.border,
            width=260,
        )
    else:
        recent_dd = None

    sidebar = _build_app_sidebar(
        {
            "pick_directory": pick_directory,
            "path_text": path_text,
            "recent_dd": recent_dd,
            "mode_checks": mode_checks,
            "start_scan": start_scan,
            "theme_icon": theme_icon,
            "lang_dd": lang_dd,
            "sidebar_status": sidebar_status,
        }
    )

    layout, _narrow = _build_responsive_layout(page, sidebar, main_content, theme_icon)

    return layout, main_content, build_dashboard


async def main(page: ft.Page):
    """Flet application entry point."""
    _setup_page(page)
    state, path_text, pick_directory, apply_path = await _setup_main_state(page)

    layout, main_content, build_dashboard = _build_main_ui(
        page, state, path_text, pick_directory, apply_path
    )

    if state.get("results"):
        build_dashboard(state["results"])
    else:
        _build_main_landing(page, main_content)

    page.add(layout)
    _install_resize_handler(page, main)

    if not page.data.get("_onboarded"):
        page.data["_onboarded"] = True
        _show_onboarding(page)


# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    ft.run(main)
