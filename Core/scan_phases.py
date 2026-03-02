"""Core/scan_phases.py — Shared scan phase runners for X-Ray CLI tools.

Consolidates the duplicated scan_codebase, phase runners, and report
collection logic that was previously copy-pasted across x_ray_claude.py,
x_ray_exe.py, and Lang/python_ast.py.
"""

from __future__ import annotations

import os
import concurrent.futures
from pathlib import Path
from typing import List, Tuple

from typing import NamedTuple, Any as _Any

from Core.types import FunctionRecord, ClassRecord
from Core.ui_bridge import get_bridge
from Analysis.ast_utils import extract_functions_from_file, collect_py_files
from Analysis.smells import CodeSmellDetector
from Analysis.duplicates import DuplicateFinder
from Analysis.reporting import (
    print_smells, print_duplicates, print_lint_report,
    print_security_report, print_unified_grade,
)


class AnalysisComponents(NamedTuple):
    """Bundle of analysis objects for collect_reports."""
    detector: _Any
    finder: _Any
    linter: _Any
    lint_issues: _Any
    sec_analyzer: _Any
    sec_issues: _Any
    web_detector: _Any = None
    health_analyzer: _Any = None


# ---------------------------------------------------------------------------
# Codebase scanning
# ---------------------------------------------------------------------------

def scan_codebase(root: Path, exclude: List[str] = None,
                  include: List[str] = None,
                  verbose: bool = False) -> Tuple[
        List[FunctionRecord], List[ClassRecord], List[str]]:
    """Parallel-scan the codebase, returning functions, classes, and errors."""
    py_files = collect_py_files(root, exclude, include)
    all_functions: List[FunctionRecord] = []
    all_classes: List[ClassRecord] = []
    errors: List[str] = []
    total = len(py_files)
    done = 0

    bridge = get_bridge()
    bridge.log(f"  Scanning {total} files using {os.cpu_count() or 4} threads...")

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = {
            executor.submit(extract_functions_from_file, f, root): f
            for f in py_files
        }
        for future in concurrent.futures.as_completed(futures):
            funcs, clses, err = future.result()
            all_functions.extend(funcs)
            all_classes.extend(clses)
            if err:
                errors.append(f"{futures[future]}: {err}")
            done += 1
            if verbose and total > 20 and done % max(1, total // 10) == 0:
                bridge.progress(done, total, futures[future].name
                                if hasattr(futures[future], "name") else "")

    return all_functions, all_classes, errors


# ---------------------------------------------------------------------------
# Individual analysis phases
# ---------------------------------------------------------------------------

def run_smell_phase(functions, classes):
    """Run AST smell detection. Returns (detector, smells)."""
    detector = CodeSmellDetector()
    get_bridge().status("Analyzing Code Smells (X-Ray AST)...")
    smells = detector.detect(functions, classes)
    return detector, smells


def run_duplicate_phase(functions):
    """Run duplicate detection. Returns finder instance."""
    finder = DuplicateFinder()
    get_bridge().status("Detecting Duplicates (X-Ray)...")
    finder.find(functions)
    return finder


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


def run_smell_fix_phase(root: Path, exclude=None):
    """Run the auto-fix smell engine. Returns SmellFixResult."""
    from Analysis.smell_fixer import SmellFixer
    fixer = SmellFixer()
    get_bridge().status("Auto-Fixing Code Smells (X-Ray)...")
    result = fixer.fix_all(root, exclude=exclude)
    return result


def run_test_gen_phase(root: Path, functions=None, classes=None,
                       smells=None, js_analyses=None, health_checks=None,
                       output_dir=None):
    """Generate monkey tests from analysis data. Returns TestGenReport."""
    from Analysis.test_generator import TestGeneratorEngine
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


def run_rustify_scan(root: Path, exclude=None) -> dict:
    """Rank functions by Rust-porting suitability and print results."""
    from Analysis.rust_advisor import RustAdvisor

    get_bridge().status("Scanning codebase for Rust candidates...")
    functions, classes, errors = scan_codebase(root, exclude=exclude)
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
    detector, finder, linter, lint_issues, sec_analyzer, sec_issues, \
        web_detector, health_analyzer = components
    results: dict = {}

    if detector:
        summary = detector.summary()
        print_smells(detector.smells, summary)
        results["smells"] = summary

    if finder:
        summary = finder.summary()
        print_duplicates(finder.groups, summary)
        results["duplicates"] = summary

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

    grade_info = print_unified_grade(results)
    results["grade"] = grade_info
    return results
