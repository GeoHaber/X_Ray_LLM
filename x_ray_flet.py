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
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import flet as ft

# -- Flet version gate --------------------------------------------------------
_MIN_FLET = (0, 80, 0)


def _check_flet_version() -> None:
    """Ensure Flet >= 0.80.0 is installed; auto-upgrade if not."""
    from packaging.version import Version

    installed = Version(ft.__version__)
    required = Version(".".join(str(p) for p in _MIN_FLET))
    if installed >= required:
        return

    print(
        f"\n[X-Ray] Flet {ft.__version__} is too old -- "
        f"minimum required is {required}.\n"
        f"        Upgrading now ...\n"
    )
    subprocess.check_call(  # nosec B603
        [sys.executable, "-m", "pip", "install", f"flet>={required}"],
    )
    print("\n[X-Ray] Flet upgraded successfully.  Please restart the application.\n")
    sys.exit(0)


_check_flet_version()


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
from UI.tabs.shared import (  # noqa: E402
    TH,
    is_narrow,
    _show_snack,
    metric_tile,
    _build_markdown_report,
    build_dimension_cards,
    build_severity_bar,
    build_trend_indicator,
    build_sparkline,
    build_html_report,
)
from UI.tabs.smells_tab import _build_smells_tab  # noqa: E402
from UI.tabs.duplicates_tab import _build_duplicates_tab  # noqa: E402
from UI.tabs.lint_tab import _build_lint_tab  # noqa: E402
from UI.tabs.security_tab import _build_security_tab  # noqa: E402
from UI.tabs.heatmap_tab import _build_heatmap_tab  # noqa: E402
from UI.tabs.complexity_tab import _build_complexity_tab  # noqa: E402
from UI.tabs.graph_tab import _build_graph_tab  # noqa: E402
from UI.tabs.nexus_tab import _build_nexus_tab  # noqa: E402
from UI.tabs.auto_rustify_tab import _build_auto_rustify_tab  # noqa: E402
from UI.tabs.rustify_tab import _build_rustify_tab  # noqa: E402
from UI.tabs.ui_health_tab import _build_ui_health_tab  # noqa: E402
from UI.tabs.ui_compat_tab import _build_ui_compat_tab  # noqa: E402
from UI.tabs.verification_tab import _build_verification_tab  # noqa: E402
from UI.tabs.release_readiness_tab import _build_release_readiness_tab  # noqa: E402

import concurrent.futures  # noqa: E402

logger = logging.getLogger(__name__)


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
        # Generate import graph
        if hasattr(analyzer, "build_graph"):
            results["import_graph"] = analyzer.build_graph(
                root, exclude=exclude or None
            )
    except Exception as exc:
        results["imports"] = {"error": str(exc)}


def _phase_verification(root, results):
    try:
        from Analysis.verification import VerificationAnalyzer

        analyzer = VerificationAnalyzer(root)
        # Use existing AST data if available
        ast_data = {
            "functions": results.get("_functions", []),
            "classes": results.get("_classes", []),
        }
        results["verification"] = analyzer.verify_project(ast_data)
    except Exception as exc:
        results["verification"] = {"error": str(exc)}


def _phase_release_readiness(root, exclude, results):
    try:
        from Analysis.release_readiness import ReleaseReadinessAnalyzer

        analyzer = ReleaseReadinessAnalyzer()
        report = analyzer.analyze(
            root,
            exclude=exclude,
            functions=results.get("_functions", []),
            classes=results.get("_classes", []),
        )
        summary = analyzer.summary()
        results["release_readiness"] = summary
        # Stash marker detail for the UI tab
        results["_release_markers_detail"] = [
            {
                "kind": m.kind,
                "file_path": m.file_path,
                "line": m.line,
                "text": m.text,
                "severity": m.severity,
            }
            for m in report.markers
        ]
        # Checklist is generated later in _run_scan after grade is computed
    except Exception as exc:
        results["release_readiness"] = {"error": str(exc)}


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
    (
        "verification",
        t("tab_verification")
        if "tab_verification" in LOCALES.get("en", {})
        else "Verification",
    ),
    ("release_readiness", "Release Readiness"),
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
        ("verification", lambda: _phase_verification(ctx.root, results)),
        (
            "release_readiness",
            lambda: _phase_release_readiness(ctx.root, ctx.exclude, results),
        ),
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

        # Generate release checklist *after* grade is available
        if "release_readiness" in results:
            from Analysis.release_checklist import generate_checklist

            checklist = generate_checklist(results)
            results["release_checklist"] = {
                "go": checklist.go,
                "blockers": checklist.blockers,
                "warnings": checklist.warnings,
                "items": [
                    {
                        "label": i.label,
                        "passed": i.passed,
                        "detail": i.detail,
                        "severity": i.severity,
                    }
                    for i in checklist.items
                ],
            }

        results["meta"]["duration"] = round(time.time() - t0, 2)
        return results

    except Exception as e:
        import traceback

        logger.error(f"Scan pipeline failed: {e}\n{traceback.format_exc()}")
        return {"error": str(e), "traceback": traceback.format_exc()}
    finally:
        if ctx.page is not None:
            set_bridge(PrintBridge())


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
    ("verification", "Verification", lambda r, p: _build_verification_tab(r, p)),
    (
        "release_readiness",
        "Release Readiness",
        lambda r, p: _build_release_readiness_tab(r, p),
    ),
]


# ═══════════════════════════════════════════════════════════════════════════════
#  ALL ISSUES TAB — Global search & filter across all scan phases
# ═══════════════════════════════════════════════════════════════════════════════

def _collect_all_issues(results):
    """Collect all issues from all scan phases into a unified list."""
    all_issues = []
    # Smell issues
    for s in results.get("_smell_issues", []):
        all_issues.append({
            "phase": "Smells", "severity": getattr(s, "severity", "info"),
            "name": getattr(s, "name", ""), "message": getattr(s, "message", ""),
            "file_path": getattr(s, "file_path", ""), "line": getattr(s, "line", 0),
            "category": getattr(s, "category", ""),
            "suggestion": getattr(s, "suggestion", ""),
        })
    # Lint issues
    for li in results.get("_lint_issues", []):
        sev = "critical" if getattr(li, "severity", "") == "critical" else \
              "warning" if getattr(li, "severity", "") == "warning" else "info"
        all_issues.append({
            "phase": "Lint", "severity": sev,
            "name": getattr(li, "code", getattr(li, "name", "")),
            "message": getattr(li, "message", str(li)),
            "file_path": getattr(li, "file_path", getattr(li, "path", "")),
            "line": getattr(li, "line", 0),
            "category": "lint", "suggestion": getattr(li, "suggestion", ""),
        })
    # Security issues
    for si in results.get("_sec_issues", []):
        sev = "critical" if getattr(si, "severity", "") in ("critical", "HIGH") else \
              "warning" if getattr(si, "severity", "") in ("warning", "MEDIUM") else "info"
        all_issues.append({
            "phase": "Security", "severity": sev,
            "name": getattr(si, "test_id", getattr(si, "name", "")),
            "message": getattr(si, "message", getattr(si, "issue_text", str(si))),
            "file_path": getattr(si, "file_path", getattr(si, "filename", "")),
            "line": getattr(si, "line", getattr(si, "line_number", 0)),
            "category": "security", "suggestion": getattr(si, "suggestion", ""),
        })
    # UI compat issues
    for ui in results.get("_ui_compat_issues", []):
        all_issues.append({
            "phase": "UI Compat", "severity": getattr(ui, "severity", "info"),
            "name": getattr(ui, "name", ""), "message": getattr(ui, "message", ""),
            "file_path": getattr(ui, "file_path", ""), "line": getattr(ui, "line", 0),
            "category": "ui_compat", "suggestion": getattr(ui, "suggestion", ""),
        })
    # UI health issues
    for uh in results.get("_ui_health_issues", []):
        all_issues.append({
            "phase": "UI Health", "severity": getattr(uh, "severity", "info"),
            "name": getattr(uh, "name", ""), "message": getattr(uh, "message", ""),
            "file_path": getattr(uh, "file_path", ""), "line": getattr(uh, "line", 0),
            "category": "ui_health", "suggestion": getattr(uh, "suggestion", ""),
        })
    # Sort: critical first, then warning, then info
    sev_order = {"critical": 0, "warning": 1, "info": 2}
    all_issues.sort(key=lambda x: sev_order.get(x["severity"], 3))
    return all_issues


def _build_all_issues_tab(all_issues, results, page):
    """Build the unified All Issues tab with search/filter."""
    from UI.tabs.shared import _code_snippet_container

    code_map = results.get("_code_map", {})
    filtered = list(all_issues)
    list_view = ft.ListView(spacing=4, expand=True, padding=10)

    severity_filter = [None]  # None = all
    search_text = [""]

    def _build_issue_row(issue):
        sev = issue["severity"]
        color = SEV_COLORS.get(sev, TH.dim)
        phase_colors = {
            "Smells": "#00d4ff", "Lint": "#64dd17", "Security": "#ff6d00",
            "UI Compat": "#7c4dff", "UI Health": "#ffd600",
        }
        phase_color = phase_colors.get(issue["phase"], TH.dim)

        code = code_map.get(f"{issue['file_path']}:{issue['line']}", "")

        tile_controls = []
        if issue["message"]:
            tile_controls.append(
                ft.Text(issue["message"], size=SZ_BODY, color=TH.dim, no_wrap=False)
            )
        if issue["suggestion"]:
            tile_controls.append(
                ft.Text(f"Fix: {issue['suggestion']}", size=SZ_SM,
                        color=ft.Colors.BLUE_200, no_wrap=False)
            )
        if code:
            tile_controls.append(_code_snippet_container(code, 300))

        return ft.ExpansionTile(
            title=ft.Row(
                [
                    ft.Container(
                        width=8, height=8, border_radius=4, bgcolor=color,
                    ),
                    ft.Container(
                        content=ft.Text(issue["phase"], size=SZ_XS,
                                        color=phase_color, weight=ft.FontWeight.BOLD),
                        bgcolor=ft.Colors.with_opacity(0.1, phase_color),
                        border_radius=8,
                        padding=ft.Padding.symmetric(horizontal=6, vertical=2),
                    ),
                    ft.Text(issue["name"] or issue["category"], size=SZ_MD,
                            color=TH.text, expand=True),
                ],
                spacing=8,
            ),
            subtitle=ft.Text(
                f"{issue['file_path']}:{issue['line']}" if issue['file_path'] else "",
                size=SZ_SM, color=TH.muted, italic=True,
            ),
            controls=[
                ft.Container(
                    content=ft.Column(tile_controls),
                    padding=12,
                    bgcolor=ft.Colors.with_opacity(0.03, TH.text),
                    border_radius=8,
                )
            ] if tile_controls else [],
            expanded=False,
        )

    def _refresh_list():
        sf = severity_filter[0]
        st = search_text[0].lower()
        showing = []
        for issue in all_issues:
            if sf and issue["severity"] != sf:
                continue
            if st:
                searchable = f"{issue['name']} {issue['message']} {issue['file_path']} {issue['phase']} {issue['category']}".lower()
                if st not in searchable:
                    continue
            showing.append(issue)
        list_view.controls = [_build_issue_row(i) for i in showing[:200]]
        count_text.value = f"{len(showing)} of {len(all_issues)} issues"
        page.update()

    def on_search(e):
        search_text[0] = e.control.value or ""
        _refresh_list()

    def on_filter_severity(sev):
        def handler(e):
            severity_filter[0] = sev if severity_filter[0] != sev else None
            # Update button styles
            for btn, s in sev_buttons:
                active = severity_filter[0] == s
                btn.bgcolor = SEV_COLORS.get(s, TH.card) if active else TH.card
                btn.content.color = ft.Colors.WHITE if active else TH.dim
            _refresh_list()
        return handler

    search_box = ft.TextField(
        hint_text="Search all issues...",
        prefix_icon=ft.Icons.SEARCH,
        border_color=TH.border,
        color=TH.text,
        on_change=on_search,
        dense=True,
        expand=True,
        border_radius=12,
    )

    count_text = ft.Text(
        f"{len(all_issues)} issues", size=SZ_SM, color=TH.muted,
    )

    sev_buttons = []
    for sev_name in ("critical", "warning", "info"):
        btn = ft.Container(
            content=ft.Text(sev_name.capitalize(), size=SZ_SM, color=TH.dim),
            bgcolor=TH.card,
            border_radius=16,
            padding=ft.Padding.symmetric(horizontal=10, vertical=4),
            on_click=on_filter_severity(sev_name),
            animate=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
        )
        sev_buttons.append((btn, sev_name))

    # Initial render
    list_view.controls = [_build_issue_row(i) for i in all_issues[:200]]

    return ft.Column(
        [
            ft.Row(
                [search_box] + [b[0] for b in sev_buttons] + [count_text],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            list_view,
        ],
        expand=True,
        spacing=8,
    )


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

    # Add the "All Issues" search/filter tab
    all_issues = _collect_all_issues(results)
    if all_issues:
        tab_names.insert(0, f"All Issues ({len(all_issues)})")
        tab_panels.insert(0, _build_all_issues_tab(all_issues, results, page))

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

    def on_export_html(e):
        try:
            html = build_html_report(results)
            path = Path(state["root_path"]) / "xray_report.html"
            path.write_text(html, encoding="utf-8")
            _show_snack(page, f" HTML report saved to {path}")
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
                        " HTML Report",
                        on_click=on_export_html,
                        bgcolor=TH.card,
                        color=TH.accent,
                        height=BTN_H_SM,
                        style=ft.ButtonStyle(
                            shape=ft.RoundedRectangleBorder(radius=BTN_RADIUS),
                            side=ft.BorderSide(1, TH.accent),
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


def _build_dashboard_header(grade_card, stats, penalty_chips, narrow: bool,
                            dimension_cards=None, severity_bar=None,
                            trend_row=None, sparkline=None):
    """Build the responsive header layout (narrow=stacked, wide=side-by-side)."""
    # Build extra info rows
    extra_rows = []
    if dimension_cards:
        extra_rows.append(dimension_cards)
    if severity_bar:
        extra_rows.append(severity_bar)
    if trend_row or sparkline:
        trend_items = []
        if trend_row:
            trend_items.append(trend_row)
        if sparkline:
            trend_items.append(sparkline)
        extra_rows.append(
            ft.Row(trend_items, spacing=16,
                   vertical_alignment=ft.CrossAxisAlignment.CENTER)
        )

    if narrow:
        return ft.Column(
            [
                grade_card,
                stats,
                (
                    ft.Row(penalty_chips, spacing=6, scroll=ft.ScrollMode.AUTO)
                    if penalty_chips
                    else ft.Container()
                ),
                *extra_rows,
            ],
            spacing=12,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )
    return ft.Column(
        [
            ft.Row(
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
            ),
            *extra_rows,
        ],
        spacing=10,
    )


def _build_main_dashboard(page, state, main_content, results):
    """Build the full results dashboard (grade card + tabs + export bar)."""
    narrow = is_narrow(page)
    grade = results.get("grade", {})
    meta = results.get("meta", {})
    breakdown = grade.get("breakdown", {})

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

    penalty_chips = _build_penalty_chips(breakdown)

    # SonarQube-style dimension rating cards
    dimension_cards = build_dimension_cards(breakdown)

    # Severity summary bar — aggregated across all phases
    severity_bar = build_severity_bar(results)

    # Trend indicator — compare with previous scan
    history = _load_scan_history(state.get("root_path", ""))
    prev_score = history[-2]["score"] if len(history) >= 2 else None
    trend_row = build_trend_indicator(grade.get("score", 0), prev_score)
    sparkline = build_sparkline(
        [h["score"] for h in history[-10:]]
    ) if len(history) >= 2 else ft.Container()

    header = _build_dashboard_header(
        grade_card, stats, penalty_chips, narrow,
        dimension_cards=dimension_cards,
        severity_bar=severity_bar,
        trend_row=trend_row,
        sparkline=sparkline,
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


def _build_main_landing(page, main_content, on_start_scan):
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
                    ft.Container(height=10),
                    ft.Container(
                        content=ft.Button(
                            f"      {t('scan_start').upper()}      ",
                            icon=ft.Icons.BOLT,
                            height=56,
                            color=ft.Colors.WHITE,
                            bgcolor=TH.accent2,
                            style=ft.ButtonStyle(
                                shape=ft.RoundedRectangleBorder(radius=16),
                                text_style=ft.TextStyle(size=16, weight=ft.FontWeight.BOLD, letter_spacing=1.5),
                            ),
                            on_click=on_start_scan,
                        ),
                        shadow=ft.BoxShadow(
                            blur_radius=20,
                            spread_radius=2,
                            color=ft.Colors.with_opacity(0.3, TH.accent2),
                        ),
                    ),
                    ft.Container(height=30),
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

    # Save to history for trend tracking
    grade = results.get("grade", {})
    meta = results.get("meta", {})
    if state["root_path"] and grade:
        _save_scan_to_history(state["root_path"], grade, meta)

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
    for key, _label in PHASE_REGISTRY:
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
        _cb("verification", "Verification"),
        _cb("release_readiness", "Release Readiness"),
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
_HISTORY_FILE = Path(__file__).parent / "xray_scan_history.json"
_MAX_RECENT = 5
_MAX_HISTORY = 50


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


def _load_scan_history(project_path: str) -> list:
    """Load scan history entries for a given project path."""
    try:
        data = json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return []
        return data.get(project_path, [])
    except Exception:
        return []


def _save_scan_to_history(project_path: str, grade: dict, meta: dict) -> None:
    """Append a scan result summary to the history file."""
    try:
        data = json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    history = data.get(project_path, [])
    import datetime
    history.append({
        "score": grade.get("score", 0),
        "letter": grade.get("letter", "?"),
        "files": meta.get("files", 0),
        "functions": meta.get("functions", 0),
        "duration": meta.get("duration", 0),
        "timestamp": datetime.datetime.now().isoformat(),
    })
    data[project_path] = history[-_MAX_HISTORY:]
    try:
        _HISTORY_FILE.write_text(
            json.dumps(data, indent=2, default=str), encoding="utf-8"
        )
    except Exception:
        pass


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
                "verification": True,
                "release_readiness": True,
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


def _show_keyboard_help(page):
    """Show a dialog with available keyboard shortcuts."""
    shortcuts = [
        ("Ctrl + S", "Start Scan"),
        ("Ctrl + E", "Export JSON"),
        ("Ctrl + H", "Export HTML Report"),
        ("Ctrl + D", "Toggle Dark/Light Theme"),
        ("F1", "Show This Help"),
    ]
    rows = [
        ft.Row(
            [
                ft.Container(
                    content=ft.Text(key, size=SZ_SM, color=TH.accent,
                                    font_family=MONO_FONT, weight=ft.FontWeight.BOLD),
                    bgcolor=TH.card, border_radius=6,
                    padding=ft.Padding.symmetric(horizontal=8, vertical=3),
                    border=ft.Border.all(1, TH.border),
                    width=120,
                ),
                ft.Text(desc, size=SZ_BODY, color=TH.text),
            ],
            spacing=12,
        )
        for key, desc in shortcuts
    ]
    dlg = ft.AlertDialog(
        title=ft.Text("Keyboard Shortcuts", size=SZ_H3,
                       weight=ft.FontWeight.BOLD, color=TH.accent),
        content=ft.Container(
            content=ft.Column(rows, spacing=8, tight=True),
            width=340, padding=8,
        ),
        actions=[
            ft.TextButton("Close", on_click=lambda e: page.pop_dialog()),
        ],
        shape=ft.RoundedRectangleBorder(radius=14),
    )
    page.show_dialog(dlg)


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

    return layout, main_content, build_dashboard, start_scan


async def main(page: ft.Page):
    """Flet application entry point."""
    _setup_page(page)
    state, path_text, pick_directory, apply_path = await _setup_main_state(page)

    layout, main_content, build_dashboard, start_scan = _build_main_ui(
        page, state, path_text, pick_directory, apply_path
    )

    if state.get("results"):
        build_dashboard(state["results"])
    else:
        _build_main_landing(page, main_content, start_scan)

    page.add(layout)
    _install_resize_handler(page, main)

    # ── Keyboard shortcuts ─────────────────────────────────────────────────
    async def on_keyboard(e: ft.KeyboardEvent):
        if e.ctrl:
            if e.key == "S":
                # Ctrl+S → Start Scan
                await start_scan(e)
            elif e.key == "E":
                # Ctrl+E → Quick JSON export
                if state.get("results"):
                    try:
                        export = {k: v for k, v in state["results"].items() if not k.startswith("_")}
                        path = Path(state["root_path"]) / "xray_report.json"
                        path.write_text(json.dumps(export, indent=2, default=str), encoding="utf-8")
                        _show_snack(page, f" Saved to {path}")
                    except Exception as exc:
                        _show_snack(page, f" Export failed: {exc}", bgcolor=ft.Colors.RED_400)
            elif e.key == "H":
                # Ctrl+H → HTML export
                if state.get("results"):
                    try:
                        html = build_html_report(state["results"])
                        path = Path(state["root_path"]) / "xray_report.html"
                        path.write_text(html, encoding="utf-8")
                        _show_snack(page, f" HTML report saved to {path}")
                    except Exception as exc:
                        _show_snack(page, f" Export failed: {exc}", bgcolor=ft.Colors.RED_400)
            elif e.key == "D":
                # Ctrl+D → Toggle theme
                TH.toggle()
                page.data["_onboarded"] = True
                try:
                    page.pop_dialog()
                except Exception:
                    pass
                page.controls.clear()
                page.run_task(main, page)
        elif e.key == "F1":
            _show_keyboard_help(page)

    page.on_keyboard_event = on_keyboard

    if not page.data.get("_onboarded"):
        page.data["_onboarded"] = True
        _show_onboarding(page)


# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    ft.run(main)

