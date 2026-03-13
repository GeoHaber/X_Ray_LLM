"""Core/scan_phases.py — Shared scan phase runners for X-Ray CLI tools.

Consolidates the duplicated scan_codebase, phase runners, and report
collection logic that was previously copy-pasted across x_ray_claude.py,
x_ray_exe.py, and Lang/python_ast.py.
"""

from __future__ import annotations

import os
import concurrent.futures
import logging
from pathlib import Path
from typing import List, Tuple

from typing import NamedTuple, Any as _Any

from Core.types import FunctionRecord, ClassRecord
from Core.ui_bridge import get_bridge
from Analysis.ast_utils import extract_functions_from_file, collect_py_files
from Analysis.smells import CodeSmellDetector
from Analysis.duplicates import DuplicateFinder
from Analysis.reporting import (
    print_smells,
    print_duplicates,
    print_format_report,
    print_lint_report,
    print_security_report,
    print_unified_grade,
)


class AnalysisComponents(NamedTuple):
    """Bundle of analysis objects for collect_reports."""

    detector: _Any
    finder: _Any
    format_analyzer: _Any
    format_issues: _Any
    linter: _Any
    lint_issues: _Any
    sec_analyzer: _Any
    sec_issues: _Any
    web_detector: _Any = None
    health_analyzer: _Any = None
    imports_analyzer: _Any = None
    imports_issues: _Any = None
    typecheck_analyzer: _Any = None
    typecheck_issues: _Any = None
    release_analyzer: _Any = None


# ---------------------------------------------------------------------------
# Codebase scanning
# ---------------------------------------------------------------------------


def scan_codebase(
    root: Path,
    exclude: List[str] = None,
    include: List[str] = None,
    verbose: bool = False,
) -> Tuple[List[FunctionRecord], List[ClassRecord], List[str]]:
    """Parallel-scan the codebase, returning functions, classes, and errors."""
    py_files = collect_py_files(root, exclude, include)
    all_functions: List[FunctionRecord] = []
    all_classes: List[ClassRecord] = []
    errors: List[str] = []
    total = len(py_files)
    done = 0

    bridge = get_bridge()
    bridge.log(f"  Scanning {total} files using {os.cpu_count() or 4} threads...")

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(16, os.cpu_count() or 4)
    ) as executor:
        futures = {
            executor.submit(extract_functions_from_file, f, root): f for f in py_files
        }
        for future in concurrent.futures.as_completed(futures):
            funcs, clses, err = future.result()
            all_functions.extend(funcs)
            all_classes.extend(clses)
            if err:
                errors.append(f"{futures[future]}: {err}")
            done += 1
            if verbose and total > 20 and done % max(1, total // 10) == 0:
                bridge.progress(
                    done,
                    total,
                    futures[future].name if hasattr(futures[future], "name") else "",
                )

    return all_functions, all_classes, errors


# ---------------------------------------------------------------------------
# Individual analysis phases
# ---------------------------------------------------------------------------


def run_smell_phase(functions, classes):
    """Run AST smell detection (smells + type coverage + dead functions).

    Returns (detector, smells).
    """
    detector = CodeSmellDetector()
    get_bridge().status("Analyzing Code Smells (X-Ray AST)...")
    smells = detector.detect(functions, classes)

    # Tier 4: type hint coverage
    try:
        from Analysis.type_coverage import TypeCoverageAnalyzer

        type_result = TypeCoverageAnalyzer().analyze(functions)
        detector.smells.extend(type_result.get("smells", []))
        smells = detector.smells
    except Exception as exc:  # noqa: BLE001 — keep scan alive if optional phase fails
        logging.getLogger(__name__).warning("type_coverage phase skipped: %s", exc)
    try:
        from Analysis.dead_functions import DeadFunctionDetector

        dead_smells = DeadFunctionDetector().detect(functions)
        detector.smells.extend(dead_smells)
        smells = detector.smells
    except Exception as exc:  # noqa: BLE001 — keep scan alive if optional phase fails
        logging.getLogger(__name__).warning("dead_functions phase skipped: %s", exc)

    return detector, smells


def run_duplicate_phase(functions):
    """Run duplicate detection. Returns finder instance."""
    finder = DuplicateFinder()
    get_bridge().status("Detecting Duplicates (X-Ray)...")
    finder.find(functions)
    return finder


def run_format_phase(root: Path, exclude=None):
    """Run Ruff format check. Returns (analyzer | None, issues)."""
    from Analysis.format import FormatAnalyzer

    fmt = FormatAnalyzer()
    if fmt.available:
        print("\n  >> Running Format Check (Ruff)...")
        return fmt, fmt.analyze(root, exclude=exclude)
    print("\n  [!] Ruff not found — skipping format check.")
    return None, []


def run_lint_phase(root: Path, exclude=None):
    """Run Ruff lint analysis. Returns (analyzer | None, issues)."""
    from Analysis.lint import LintAnalyzer

    linter = LintAnalyzer()
    if linter.available:
        get_bridge().status("Running Linter (Ruff)...")
        return linter, linter.analyze(root, exclude=exclude)
    get_bridge().log("  [!] Ruff not found — skipping lint analysis.")
    return None, []


def run_security_phase(root: Path, exclude=None):
    """Run Bandit security analysis. Returns (analyzer | None, issues)."""
    from Analysis.security import SecurityAnalyzer

    sec = SecurityAnalyzer()
    if sec.available:
        get_bridge().status("Running Security Scan (Bandit)...")
        return sec, sec.analyze(root, exclude=exclude)
    get_bridge().log("  [!] Bandit not found — skipping security scan.")
    return None, []


def run_ui_compat_phase(root: Path, exclude=None):
    """Run UI API compatibility check. Returns (analyzer | None, issues)."""
    from Analysis.ui_compat import UICompatAnalyzer

    analyzer = UICompatAnalyzer()
    get_bridge().status("Checking UI API Compatibility (X-Ray)...")
    raw_issues = analyzer.analyze(root, exclude=exclude)
    smell_issues = [i.to_smell() for i in raw_issues]
    if raw_issues:
        analyzer.print_report(raw_issues)
    else:
        get_bridge().log("  ✅ All UI calls are compatible.")
    return analyzer, raw_issues, smell_issues


def run_web_smell_phase(root: Path, exclude=None):
    """Run JS/TS/React web smell detection. Returns (detector, smells)."""
    from Analysis.web_smells import WebSmellDetector

    detector = WebSmellDetector()
    get_bridge().status("Scanning JS/TS/React Code Smells (X-Ray Web)...")
    smells = detector.detect(root, exclude=exclude)
    return detector, smells


def run_health_phase(root: Path, auto_fix: bool = False):
    """Run project health/structural check. Returns analyzer with report."""
    from Analysis.project_health import ProjectHealthAnalyzer

    analyzer = ProjectHealthAnalyzer()
    get_bridge().status("Checking Project Health (X-Ray)...")
    analyzer.analyze(root, auto_fix=auto_fix)
    return analyzer


def run_imports_phase(root: Path, exclude=None):
    """Run file-level import health analysis. Returns (analyzer, issues)."""
    from Analysis.imports import ImportAnalyzer

    analyzer = ImportAnalyzer()
    get_bridge().status("Checking Import Health (X-Ray)...")
    issues = analyzer.analyze(root, exclude=exclude)
    return analyzer, issues


def run_typecheck_phase(root: Path, exclude=None):
    """Run Pyright type checker. Returns (analyzer | None, issues)."""
    from Analysis.typecheck import TypecheckAnalyzer

    tc = TypecheckAnalyzer()
    if tc.available:
        get_bridge().status("Running Type Checker (Pyright)...")
        return tc, tc.analyze(root, exclude=exclude)
    get_bridge().log("  [!] Pyright not found -- skipping type check.")
    return None, []


def run_smell_fix_phase(root: Path, exclude=None):
    """Run the auto-fix smell engine. Returns SmellFixResult."""
    from Analysis.smell_fixer import SmellFixer

    fixer = SmellFixer()
    get_bridge().status("Auto-Fixing Code Smells (X-Ray)...")
    result = fixer.fix_all(root, exclude=exclude)
    return result


def run_test_gen_phase(
    root: Path,
    functions=None,
    classes=None,
    smells=None,
    js_analyses=None,
    health_checks=None,
    output_dir=None,
    exclude=None,
):
    """Generate monkey tests from analysis data. Returns TestGenReport."""
    from Analysis.test_generator import TestGeneratorEngine

    # Filter out functions/classes from excluded paths
    if exclude:
        functions = [
            f
            for f in (functions or [])
            if not any(f.file_path.startswith(e) for e in exclude)
        ]
        classes = [
            c
            for c in (classes or [])
            if not any(c.file_path.startswith(e) for e in exclude)
        ]

    engine = TestGeneratorEngine(root)
    get_bridge().status("Generating Monkey Tests (X-Ray)...")
    report = engine.generate(
        functions=functions,
        classes=classes,
        smells=smells,
        js_analyses=js_analyses,
        health_checks=health_checks,
        output_dir=output_dir or root,
    )
    return report


def run_release_readiness_phase(
    root: Path,
    exclude=None,
    functions=None,
    classes=None,
):
    """Run pre-release readiness checks. Returns analyzer with report."""
    from Analysis.release_readiness import ReleaseReadinessAnalyzer

    analyzer = ReleaseReadinessAnalyzer()
    get_bridge().status("Checking Release Readiness (X-Ray)...")
    analyzer.analyze(root, exclude=exclude, functions=functions, classes=classes)
    return analyzer


def run_rustify_scan(root: Path, exclude=None) -> dict:
    """Rank functions by Rust-porting suitability and print results."""
    from Analysis.rust_advisor import RustAdvisor

    get_bridge().status("Scanning codebase for Rust candidates...")
    functions, _classes, _errors = scan_codebase(root, exclude=exclude)
    if not functions:
        get_bridge().log("  No functions found.")
        return {"rustify": {"candidates": []}}

    advisor = RustAdvisor()
    candidates = advisor.score(functions)
    advisor.print_candidates(candidates)

    return {
        "rustify": {
            "total_functions": len(functions),
            "scored": len(candidates),
            "pure_count": sum(1 for c in candidates if c.is_pure),
            "candidates": [c.to_dict() for c in candidates],
        }
    }


# ---------------------------------------------------------------------------
# Report collection
# ---------------------------------------------------------------------------


def collect_reports(components: AnalysisComponents) -> dict:
    """Print all analysis reports, compute unified grade, return combined results."""
    detector = components.detector
    finder = components.finder
    fmt_analyzer = components.format_analyzer
    fmt_issues = components.format_issues
    linter = components.linter
    lint_issues = components.lint_issues
    sec_analyzer = components.sec_analyzer
    sec_issues = components.sec_issues
    web_detector = components.web_detector
    health_analyzer = components.health_analyzer
    results: dict = {}

    if detector:
        summary = detector.summary()
        print_smells(detector.smells, summary)
        results["smells"] = summary

    if finder:
        summary = finder.summary()
        print_duplicates(finder.groups, summary)
        results["duplicates"] = summary

    if fmt_analyzer and fmt_issues:
        summary = fmt_analyzer.summary(fmt_issues)
        print_format_report(fmt_issues, summary)
        results["format"] = summary

    if linter and lint_issues:
        summary = linter.summary(lint_issues)
        print_lint_report(lint_issues, summary)
        results["lint"] = summary

    if sec_analyzer and sec_issues:
        summary = sec_analyzer.summary(sec_issues)
        print_security_report(sec_issues, summary)
        results["security"] = summary

    if web_detector:
        summary = web_detector.summary()
        from Analysis.reporting import print_web_report

        print_web_report(web_detector.smells, summary)
        results["web"] = summary

    if health_analyzer and health_analyzer.report:
        summary = health_analyzer.summary()
        from Analysis.reporting import print_health_report

        print_health_report(health_analyzer.report, summary)
        results["health"] = summary

    imports_analyzer = components.imports_analyzer
    imports_issues = components.imports_issues
    if imports_analyzer and imports_issues is not None:
        summary = imports_analyzer.summary(imports_issues)
        from Analysis.reporting import print_imports_report

        print_imports_report(imports_issues, summary)
        results["imports"] = summary

    tc_analyzer = components.typecheck_analyzer
    tc_issues = components.typecheck_issues
    if tc_analyzer and tc_issues is not None:
        summary = tc_analyzer.summary(tc_issues)
        from Analysis.reporting import print_typecheck_report

        print_typecheck_report(tc_issues, summary)
        results["typecheck"] = summary

    release_analyzer = components.release_analyzer
    if release_analyzer and release_analyzer.report:
        summary = release_analyzer.summary()
        from Analysis.reporting import print_release_readiness_report

        print_release_readiness_report(release_analyzer.report, summary)
        results["release_readiness"] = summary

    grade_info = print_unified_grade(results)
    results["grade"] = grade_info

    # Generate release checklist if release readiness was run
    if "release_readiness" in results:
        from Analysis.release_checklist import generate_checklist, format_checklist

        checklist = generate_checklist(results)
        get_bridge().log(format_checklist(checklist))
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

    return results
