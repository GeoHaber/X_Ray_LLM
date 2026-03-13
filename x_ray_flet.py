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
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import flet as ft

# -- Flet version gate --------------------------------------------------------
_MIN_FLET = (0, 80, 0)


def _check_flet_version() -> None:
    """Ensure Flet >= 0.80.0 is installed; exit with guidance if not."""
    from packaging.version import Version

    installed = Version(ft.__version__)
    required = Version(".".join(str(p) for p in _MIN_FLET))
    if installed >= required:
        return

    print(
        f"\n[X-Ray] Flet {ft.__version__} is too old -- "
        f"minimum required is {required}.\n"
        f"        Please upgrade manually:\n"
        f"          pip install flet>={required}\n"
    )
    sys.exit(1)


_check_flet_version()


# â”€â”€ Ensure project root is importable â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Core.types import FunctionRecord, ClassRecord  # noqa: E402
from Core.config import SMELL_THRESHOLDS  # noqa: E402
from Core.i18n import t, LOCALES  # noqa: E402
from Core.ui_bridge import set_bridge, get_bridge  # noqa: E402
from Analysis.ast_utils import extract_functions_from_file, collect_py_files  # noqa: E402
from Analysis.smells import CodeSmellDetector  # noqa: E402
from Analysis.duplicates import DuplicateFinder  # noqa: E402
from Analysis.reporting import compute_grade  # noqa: E402
from Analysis.rust_advisor import RustAdvisor  # noqa: E402
from UI.tabs.shared import (  # noqa: E402
    TH,
    _show_snack,
    build_html_report,
    SEV_COLORS,
    MONO_FONT,
    SZ_XS,
    SZ_SM,
    SZ_BODY,
    SZ_MD,
    SZ_SECTION,
    SZ_H3,
    SZ_H2,
)
from UI.shell_v2 import build_shell_v2  # noqa: E402 — v8.0 redesigned shell

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
                logger.debug("FletBridge.log page.update failed", exc_info=True)

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
                logger.debug("FletBridge.status progress_cb failed", exc_info=True)

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
            logger.debug("FletBridge.progress failed", exc_info=True)


# All theme constants (MONO_FONT, SZ_*, BTN_*, GRADE_COLORS, SEV_*)
# are imported from UI.tabs.shared - single source of truth.

# ═══════════════════════════════════════════════════════════════════════════════
#  SCAN ENGINE
# ═══════════════════════════════════════════════════════════════════════════════


def _scan_codebase(root: Path, exclude: List[str], progress_cb=None):
    """Parse all .py files. Returns (funcs, classes, errors, file_count).
    progress_cb(files_done, total_files, current_file) is called per file."""
    py_files = collect_py_files(root, exclude or None)
    total = len(py_files)
    funcs, classes, errors = [], [], []
    _lock = threading.Lock()
    done = [0]

    def _parse_one(f):
        fn, cl, err = extract_functions_from_file(f, root)
        with _lock:
            done[0] += 1
            _done = done[0]
        if progress_cb:
            progress_cb(_done, total, str(f))
        return fn, cl, err, f

    with concurrent.futures.ThreadPoolExecutor() as pool:
        futs = [pool.submit(_parse_one, f) for f in py_files]
        for fut in concurrent.futures.as_completed(futs):
            fn, cl, err, fpath = fut.result()
            # as_completed yields one-at-a-time so extend is safe here
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


# ── v8.0 New Analysis Phase Functions ────────────────────────────────────────


def _phase_satd(root, results):
    """Run SATD scanner and store results in results['_satd']."""
    try:
        from Analysis.satd import SATDScanner

        scanner = SATDScanner()
        summary = scanner.scan_directory(root)
        results["_satd"] = summary.as_dict()
        results["_satd_summary"] = summary  # keep object for QualityGate
    except Exception as exc:
        results["_satd"] = {"error": str(exc)}


def _phase_hotspots(root, results):
    """Run git hotspot analysis and store results in results['_hotspots']."""
    try:
        from Analysis.git_hotspots import HotspotAnalyzer

        # Pass complexity map if available from smells/complexity data
        cx_map = {}
        for f in results.get("_functions", []):
            fp = getattr(f, "file_path", None) or ""
            cc = getattr(f, "complexity", 0) or 0
            if fp:
                prev = cx_map.get(fp, 0)
                cx_map[fp] = max(prev, cc)
        analyzer = HotspotAnalyzer(root)
        report = analyzer.analyze(days=90, complexity_map=cx_map)
        results["_hotspots"] = report.as_dict()
    except Exception as exc:
        results["_hotspots"] = {"error": str(exc)}


def _phase_coupling(root, results):
    """Run temporal coupling analysis and store in results['_coupling']."""
    try:
        from Analysis.temporal_coupling import TemporalCouplingAnalyzer

        analyzer = TemporalCouplingAnalyzer(root)
        report = analyzer.analyze(days=180, min_commits=3, min_coupling=0.25)
        results["_coupling"] = report.as_dict()
    except Exception as exc:
        results["_coupling"] = {"error": str(exc)}


def _phase_ai_debt(root, results):
    """Run AI-generated code detector and store in results['_ai_debt']."""
    try:
        from Analysis.ai_code_detector import AICodeDetector

        detector = AICodeDetector()
        report = detector.scan_directory(root)
        results["_ai_debt"] = report.as_dict()
    except Exception as exc:
        results["_ai_debt"] = {"error": str(exc)}


def _phase_diagrams(root, results):
    """Generate Mermaid/C4 diagrams from import graph and store in results['_diagrams']."""
    try:
        from Analysis.diagram_export import DiagramExporter

        import_graph = results.get("import_graph", {})
        edges = [
            (e.get("source", ""), e.get("target", ""))
            for e in import_graph.get("edges", [])
            if e.get("source") and e.get("target")
        ]
        exporter = DiagramExporter(root=root)
        diagram = exporter.export(edges)
        results["_diagrams"] = {
            "mermaid_flowchart": diagram.mermaid_flowchart,
            "c4_context": diagram.c4_context,
            "c4_component": diagram.c4_component,
            "node_count": diagram.node_count,
            "edge_count": diagram.edge_count,
        }
        # Save .mmd to project root(non-blocking, best-effort)
        try:
            mmd_path = root / "xray_architecture.mmd"
            exporter.save(diagram.mermaid_flowchart, mmd_path)
        except Exception:
            pass
    except Exception as exc:
        results["_diagrams"] = {"error": str(exc)}


def _phase_quality_gate(root, results):
    """Evaluate quality gate and store result in results['_gate']."""
    try:
        from Analysis.quality_gate import QualityGate

        settings_path = root / "xray_settings.json"
        gate = QualityGate(settings_path=settings_path)
        satd_summary = results.get("_satd_summary")
        gate_result = gate.evaluate(results, satd_summary=satd_summary)
        results["_gate"] = gate_result.as_dict()
        # Write gate result JSON for CI
        try:
            gate_result.write_json(root / "xray_gate_result.json")
        except Exception:
            pass
    except Exception as exc:
        results["_gate"] = {"error": str(exc)}


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
    ("design_oracle", "Architectural Review (AI)"),
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
        ("design_oracle", lambda: _phase_design_oracle(results)),
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

        # ── v8.0 new analysis phases ──────────────────────────────────
        _phase_satd(ctx.root, results)
        _phase_hotspots(ctx.root, results)
        _phase_coupling(ctx.root, results)
        _phase_ai_debt(ctx.root, results)
        _phase_diagrams(ctx.root, results)

        results["grade"] = compute_grade(results)

        # Quality gate runs after grade is available
        _phase_quality_gate(ctx.root, results)

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

# ═══════════════════════════════════════════════════════════════════════════════
#  ALL ISSUES TAB — Global search & filter across all scan phases
# ═══════════════════════════════════════════════════════════════════════════════


def _collect_all_issues(results):
    """Collect all issues from all scan phases into a unified list."""
    all_issues = []
    # Smell issues
    for s in results.get("_smell_issues", []):
        all_issues.append(
            {
                "phase": "Smells",
                "severity": getattr(s, "severity", "info"),
                "name": getattr(s, "name", ""),
                "message": getattr(s, "message", ""),
                "file_path": getattr(s, "file_path", ""),
                "line": getattr(s, "line", 0),
                "category": getattr(s, "category", ""),
                "suggestion": getattr(s, "suggestion", ""),
            }
        )
    # Lint issues
    for li in results.get("_lint_issues", []):
        sev = (
            "critical"
            if getattr(li, "severity", "") == "critical"
            else "warning"
            if getattr(li, "severity", "") == "warning"
            else "info"
        )
        all_issues.append(
            {
                "phase": "Lint",
                "severity": sev,
                "name": getattr(li, "code", getattr(li, "name", "")),
                "message": getattr(li, "message", str(li)),
                "file_path": getattr(li, "file_path", getattr(li, "path", "")),
                "line": getattr(li, "line", 0),
                "category": "lint",
                "suggestion": getattr(li, "suggestion", ""),
            }
        )
    # Security issues
    for si in results.get("_sec_issues", []):
        sev = (
            "critical"
            if getattr(si, "severity", "") in ("critical", "HIGH")
            else "warning"
            if getattr(si, "severity", "") in ("warning", "MEDIUM")
            else "info"
        )
        all_issues.append(
            {
                "phase": "Security",
                "severity": sev,
                "name": getattr(si, "test_id", getattr(si, "name", "")),
                "message": getattr(si, "message", getattr(si, "issue_text", str(si))),
                "file_path": getattr(si, "file_path", getattr(si, "filename", "")),
                "line": getattr(si, "line", getattr(si, "line_number", 0)),
                "category": "security",
                "suggestion": getattr(si, "suggestion", ""),
            }
        )
    # UI compat issues
    for ui in results.get("_ui_compat_issues", []):
        all_issues.append(
            {
                "phase": "UI Compat",
                "severity": getattr(ui, "severity", "info"),
                "name": getattr(ui, "name", ""),
                "message": getattr(ui, "message", ""),
                "file_path": getattr(ui, "file_path", ""),
                "line": getattr(ui, "line", 0),
                "category": "ui_compat",
                "suggestion": getattr(ui, "suggestion", ""),
            }
        )
    # UI health issues
    for uh in results.get("_ui_health_issues", []):
        all_issues.append(
            {
                "phase": "UI Health",
                "severity": getattr(uh, "severity", "info"),
                "name": getattr(uh, "name", ""),
                "message": getattr(uh, "message", ""),
                "file_path": getattr(uh, "file_path", ""),
                "line": getattr(uh, "line", 0),
                "category": "ui_health",
                "suggestion": getattr(uh, "suggestion", ""),
            }
        )
    # Sort: critical first, then warning, then info
    sev_order = {"critical": 0, "warning": 1, "info": 2}
    all_issues.sort(key=lambda x: sev_order.get(x["severity"], 3))
    return all_issues


def _build_issue_row(issue, code_map):
    """Build a single issue expansion tile for the All Issues list."""
    from UI.tabs.shared import _code_snippet_container

    sev = issue["severity"]
    color = SEV_COLORS.get(sev, TH.dim)
    phase_colors = {
        "Smells": "#00d4ff",
        "Lint": "#64dd17",
        "Security": "#ff6d00",
        "UI Compat": "#7c4dff",
        "UI Health": "#ffd600",
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
            ft.Text(
                f"Fix: {issue['suggestion']}",
                size=SZ_SM,
                color=ft.Colors.BLUE_200,
                no_wrap=False,
            )
        )
    if code:
        tile_controls.append(_code_snippet_container(code, 300))

    return ft.ExpansionTile(
        title=ft.Row(
            [
                ft.Container(
                    width=8,
                    height=8,
                    border_radius=4,
                    bgcolor=color,
                ),
                ft.Container(
                    content=ft.Text(
                        issue["phase"],
                        size=SZ_XS,
                        color=phase_color,
                        weight=ft.FontWeight.BOLD,
                    ),
                    bgcolor=ft.Colors.with_opacity(0.1, phase_color),
                    border_radius=8,
                    padding=ft.Padding.symmetric(horizontal=6, vertical=2),
                ),
                ft.Text(
                    issue["name"] or issue["category"],
                    size=SZ_MD,
                    color=TH.text,
                    expand=True,
                ),
            ],
            spacing=8,
        ),
        subtitle=ft.Text(
            f"{issue['file_path']}:{issue['line']}" if issue["file_path"] else "",
            size=SZ_SM,
            color=TH.muted,
            italic=True,
        ),
        controls=[
            ft.Container(
                content=ft.Column(tile_controls),
                padding=12,
                bgcolor=ft.Colors.with_opacity(0.03, TH.text),
                border_radius=8,
            )
        ]
        if tile_controls
        else [],
        expanded=False,
    )


def _build_all_issues_tab(all_issues, results, page):
    """Build the unified All Issues tab with search/filter."""

    code_map = results.get("_code_map", {})
    list_view = ft.ListView(spacing=4, expand=True, padding=10)

    severity_filter = [None]  # None = all
    search_text = [""]

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
        list_view.controls = [_build_issue_row(i, code_map) for i in showing[:200]]
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
        f"{len(all_issues)} issues",
        size=SZ_SM,
        color=TH.muted,
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
    list_view.controls = [_build_issue_row(i, code_map) for i in all_issues[:200]]

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


def _build_phase_row_pending(label):
    """Build a pending phase row (dimmed, in the queue)."""
    return ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.CIRCLE_OUTLINED, size=12, color=TH.muted),
                ft.Text(label, size=SZ_SM, color=TH.muted),
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.Padding.symmetric(horizontal=24, vertical=3),
        opacity=0.5,
        animate=ft.Animation(300, ft.AnimationCurve.EASE_OUT),
        animate_opacity=ft.Animation(300, ft.AnimationCurve.EASE_OUT),
    )


def _build_phase_active(label):
    """Build the active phase row (prominent, centered, glowing)."""
    return ft.Container(
        content=ft.Row(
            [
                ft.ProgressRing(width=20, height=20, stroke_width=2.5, color="#00d4ff"),
                ft.Text(
                    label,
                    size=SZ_H3,
                    weight=ft.FontWeight.W_600,
                    color="#00d4ff",
                ),
            ],
            spacing=12,
            alignment=ft.MainAxisAlignment.CENTER,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.Padding.symmetric(horizontal=24, vertical=12),
        border_radius=12,
        bgcolor=ft.Colors.with_opacity(0.08, "#00d4ff"),
        border=ft.Border.all(1, ft.Colors.with_opacity(0.2, "#00d4ff")),
        animate=ft.Animation(300, ft.AnimationCurve.EASE_OUT),
    )


def _build_phase_done_counter(done_count, total_count):
    """Build a compact counter showing completed phases."""
    return ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.CHECK_CIRCLE, size=16, color=ft.Colors.GREEN_400),
                ft.Text(
                    f"{done_count} of {total_count} complete",
                    size=SZ_SM,
                    color=ft.Colors.GREEN_400,
                ),
            ],
            spacing=6,
            alignment=ft.MainAxisAlignment.CENTER,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.Padding.symmetric(horizontal=16, vertical=6),
        animate=ft.Animation(300, ft.AnimationCurve.EASE_OUT),
    )


def _build_phase_checklist(phase_rows_container, modes):
    """Build the FIFO scanning queue screen."""
    return ft.Container(
        content=ft.Column(
            [
                ft.Container(height=20),
                phase_rows_container,
                ft.Container(height=20),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=0,
        ),
        padding=ft.Padding.symmetric(horizontal=20, vertical=0),
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

    history.append(
        {
            "score": grade.get("score", 0),
            "letter": grade.get("letter", "?"),
            "files": meta.get("files", 0),
            "functions": meta.get("functions", 0),
            "duration": meta.get("duration", 0),
            "timestamp": datetime.datetime.now().isoformat(),
        }
    )
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


async def _setup_main_state(page: ft.Page):
    """Initialize state and file picker for the main app."""
    state = _init_state(page)

    # Load persisted recent paths into state so sidebar can see them
    settings = _load_settings()
    state.setdefault("recent_paths", settings.get("recent_paths", []))
    # Restore last-used path if the current session hasn't set one yet
    if not state["root_path"] and state["recent_paths"]:
        state["root_path"] = state["recent_paths"][0]

    # FilePicker is instantiated dynamically in pick_directory for desktop clients

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
        if page.web:
            # Fallback for web mode: ask user to type the path
            def _close_dlg(e):
                dlg.open = False
                page.update()

            def _apply_dlg(e):
                if d_path.value:
                    _apply_path(d_path.value)
                dlg.open = False
                page.update()

            d_path = ft.TextField(
                label="Enter Directory Path",
                value=state.get("root_path", ""),
                autofocus=True,
                expand=True,
            )
            dlg = ft.AlertDialog(
                title=ft.Text("Select Directory (Web Mode)"),
                content=d_path,
                actions=[
                    ft.TextButton("Cancel", on_click=_close_dlg),
                    ft.TextButton("Apply", on_click=_apply_dlg),
                ],
            )
            if dlg not in page.overlay:
                page.overlay.append(dlg)
            dlg.open = True
            page.update()
        else:
            # Dynamically instantiate FilePicker to avoid web rendering bugs on page load
            f_picker = None
            for s in page.overlay:
                if type(s).__name__ == "FilePicker":
                    f_picker = s
                    break

            if not f_picker:
                # ONLY create FilePicker on non-web clients
                f_picker = ft.FilePicker()
                page.overlay.append(f_picker)
                page.update()

            try:
                result = await f_picker.get_directory_path(
                    dialog_title=t("select_directory")
                )
                if result:
                    _apply_path(result)
                    page.update()
            except Exception as exc:
                import logging

                logging.error(f"Error opening directory picker: {exc}")

    return state, path_text, pick_directory, _apply_path


def _phase_design_oracle(results):
    try:
        from Analysis.design_oracle import _default_oracle

        functions = results.get("_functions", [])
        file_count = results.get("meta", {}).get("files", 1) or 1
        oracle_res = _default_oracle.analyze(functions, file_count)
        results["design_oracle"] = _default_oracle.summary(oracle_res)
        results["_design_oracle_full"] = oracle_res
    except Exception as exc:
        results["design_oracle"] = {"error": str(exc)}


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
                    content=ft.Text(
                        key,
                        size=SZ_SM,
                        color=TH.accent,
                        font_family=MONO_FONT,
                        weight=ft.FontWeight.BOLD,
                    ),
                    bgcolor=TH.card,
                    border_radius=6,
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
        title=ft.Text(
            "Keyboard Shortcuts", size=SZ_H3, weight=ft.FontWeight.BOLD, color=TH.accent
        ),
        content=ft.Container(
            content=ft.Column(rows, spacing=8, tight=True),
            width=340,
            padding=8,
        ),
        actions=[
            ft.TextButton(
                "Close", on_click=lambda e: (setattr(dlg, "open", False), page.update())
            ),
        ],
        shape=ft.RoundedRectangleBorder(radius=14),
    )
    if dlg not in page.overlay:
        page.overlay.append(dlg)
    dlg.open = True
    page.update()


def _build_scan_progress_shell(phase_rows_container, modes):
    """Build the scan-in-progress shell with phase checklist."""
    return ft.Row(
        [
            ft.Container(
                width=64,
                bgcolor=TH.surface,
                border=ft.Border.only(right=ft.BorderSide(1, TH.divider)),
                content=ft.Column(
                    [
                        ft.Container(
                            content=ft.Text(
                                "☢",
                                size=22,
                                text_align=ft.TextAlign.CENTER,
                                color="#00d4ff",
                            ),
                            width=64,
                            height=48,
                            alignment=ft.Alignment(0, 0),
                        ),
                    ],
                    spacing=2,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=ft.Padding.symmetric(vertical=8),
            ),
            ft.Container(
                expand=True,
                content=ft.Column(
                    [
                        ft.Container(expand=True),
                        ft.Column(
                            [
                                ft.Text(
                                    "☢  Scanning…",
                                    size=28,
                                    weight=ft.FontWeight.BOLD,
                                    color="#00d4ff",
                                    font_family=MONO_FONT,
                                    text_align=ft.TextAlign.CENTER,
                                ),
                                ft.Container(height=16),
                                _build_phase_checklist(phase_rows_container, modes),
                            ],
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=8,
                        ),
                        ft.Container(expand=True),
                    ],
                    expand=True,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=ft.Padding.symmetric(horizontal=60, vertical=20),
                bgcolor=TH.bg,
            ),
        ],
        expand=True,
        spacing=0,
        vertical_alignment=ft.CrossAxisAlignment.STRETCH,
    )


async def _handle_keyboard(e, state, page, do_scan_fn):
    """Handle keyboard shortcuts for the main page."""
    if e.ctrl:
        if e.key == "S":
            await do_scan_fn(e)
        elif e.key == "E":
            if state.get("results"):
                try:
                    export = {
                        k: v
                        for k, v in state["results"].items()
                        if not k.startswith("_")
                    }
                    path = Path(state["root_path"]) / "xray_report.json"
                    path.write_text(
                        json.dumps(export, indent=2, default=str), encoding="utf-8"
                    )
                    _show_snack(page, f"✓ Saved to {path}")
                except Exception as exc:
                    _show_snack(
                        page, f"Export failed: {exc}", bgcolor=ft.Colors.RED_400
                    )
        elif e.key == "H":
            if state.get("results"):
                try:
                    html = build_html_report(state["results"])
                    path = Path(state["root_path"]) / "xray_report.html"
                    path.write_text(html, encoding="utf-8")
                    _show_snack(page, f"✓ HTML report saved to {path}")
                except Exception as exc:
                    _show_snack(
                        page, f"Export failed: {exc}", bgcolor=ft.Colors.RED_400
                    )
        elif e.key == "D":
            TH.toggle()
            page.data["_onboarded"] = True
            page.controls.clear()
            page.run_task(main, page)
    elif e.key == "F1":
        _show_keyboard_help(page)


async def main(page: ft.Page):
    """Flet application entry point — v8.0 redesigned shell."""
    _setup_page(page)
    state, path_text, pick_directory, apply_path = await _setup_main_state(page)

    # ── Path helpers ───────────────────────────────────────────────────────
    async def on_pick_dir(e):
        await pick_directory(e)

    def on_apply_path(path_str: str):
        apply_path(path_str)

    # ── Shell container (will hold the ft.Row rail+content) ────────────────
    page_container = ft.Container(expand=True, bgcolor=TH.bg)

    def _rebuild_shell(results=None):
        """Rebuild the full shell, optionally with results."""

        async def on_scan(e):
            await _do_scan(e)

        shell = build_shell_v2(
            page=page,
            state=state,
            on_scan=on_scan,
            on_pick_dir=on_pick_dir,
            on_apply_path=on_apply_path,
            results=results,
        )
        page_container.content = shell
        page.update()

    async def _do_scan(e):
        """Run the scan and rebuild shell with results."""
        if not state.get("root_path"):
            _show_snack(page, t("select_dir_first"), bgcolor=ft.Colors.RED_400)
            return

        # Phase checklist
        phase_rows_container = ft.Column([], spacing=0)
        phase_states: Dict[str, tuple] = {"_parse": (PhaseStatus.PENDING, 0)}
        for key, _label in PHASE_REGISTRY:
            phase_states[key] = (PhaseStatus.PENDING, 0)

        # Build full ordered list of (key, label) for FIFO display
        _all_phases = [("_parse", "AST Parsing")] + list(PHASE_REGISTRY)

        def _refresh_phase_rows():
            done_count = 0
            active_label = None
            pending_labels = []
            total = len(_all_phases)

            for key, label in _all_phases:
                ps, _el = phase_states.get(key, (PhaseStatus.PENDING, 0))
                if ps in (PhaseStatus.DONE, PhaseStatus.SKIPPED, PhaseStatus.FAILED):
                    done_count += 1
                elif ps == PhaseStatus.RUNNING:
                    active_label = label
                else:
                    pending_labels.append(label)

            controls = []
            # Completed counter (only show when at least 1 done)
            if done_count > 0:
                controls.append(_build_phase_done_counter(done_count, total))
                controls.append(ft.Container(height=12))
            # Active task (prominent)
            if active_label:
                controls.append(_build_phase_active(active_label))
                controls.append(ft.Container(height=12))
            # Remaining queue (dimmed)
            if pending_labels:
                controls.append(
                    ft.Text("QUEUE", size=SZ_XS, color=TH.muted,
                            font_family=MONO_FONT, text_align=ft.TextAlign.CENTER)
                )
                controls.append(ft.Container(height=4))
                for lbl in pending_labels:
                    controls.append(_build_phase_row_pending(lbl))

            phase_rows_container.controls = controls

        def phase_cb(key, status, elapsed):
            phase_states[key] = (status, elapsed)
            _refresh_phase_rows()
            try:
                page.update()
            except Exception:
                pass

        _refresh_phase_rows()

        # Replace shell content with scan progress
        page_container.content = _build_scan_progress_shell(
            phase_rows_container, state.get("modes", {})
        )
        page.update()

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
            _show_snack(page, f"Scan failed: {exc}", bgcolor=ft.Colors.RED_400)
            _rebuild_shell(None)
            return

        if "error" in results:
            _show_snack(
                page, f"Scan error: {results['error']}", bgcolor=ft.Colors.RED_400
            )
            _rebuild_shell(None)
            return

        results["_scan_path"] = state["root_path"]
        state["results"] = results

        # Save to history
        grade = results.get("grade", {})
        meta = results.get("meta", {})
        if state["root_path"] and grade:
            _save_scan_to_history(state["root_path"], grade, meta)

        # Brief completion flash
        page_container.content = _build_scan_complete_screen(results)
        page.update()
        await asyncio.sleep(0.7)

        # Rebuild shell with results (auto-navigate to Overview)
        _rebuild_shell(results)

    # ── Initial render ─────────────────────────────────────────────────────
    _rebuild_shell(state.get("results"))
    page.add(page_container)

    # ── Keyboard shortcuts (preserved from v7) ─────────────────────────────
    async def on_keyboard(e: ft.KeyboardEvent):
        await _handle_keyboard(e, state, page, _do_scan)

    page.on_keyboard_event = on_keyboard

    if not page.data.get("_onboarded"):
        page.data["_onboarded"] = True


# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    ft.run(main)
