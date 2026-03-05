from pathlib import Path
from typing import List, Dict, Any, NamedTuple
from Core.types import (
    FunctionRecord,
    ClassRecord,
    SmellIssue,
    DuplicateGroup,
    LibrarySuggestion,
    Severity,
)
from typing import List, Dict, Any, NamedTuple, Optional
from Core.types import FunctionRecord, ClassRecord, SmellIssue, DuplicateGroup, LibrarySuggestion, Severity
from Core.config import __version__, SEP
from Core.ui_bridge import get_bridge


class ScanData(NamedTuple):
    """Bundle of analysis results for report generation."""

    functions: List[FunctionRecord]
    classes: List[ClassRecord]
    smells: List[SmellIssue]
    duplicates: List[DuplicateGroup]
    suggestions: List[LibrarySuggestion]


def print_smells(smells: List[SmellIssue], summary: Dict[str, Any]):
    """Print the ASCII smell report."""
    print(f"\n{SEP}")
    print("CODE SMELL REPORT (X-Ray)")
    print(f"{SEP}")
    bridge = get_bridge()
    bridge.log(f"\n{SEP}")
    bridge.log("CODE SMELL REPORT (X-Ray)")
    bridge.log(f"{SEP}")

    if not smells:
        bridge.log("No smells found! Clean code.")
        return

    # Sort: Critical first, then by file
    sorted_smells = sorted(
        smells,
        key=lambda s: (
            0 if s.severity == Severity.CRITICAL else 1,
            s.file_path,
            s.line,
        ),
    )

    for s in sorted_smells:
        icon = Severity.icon(s.severity)
        loc = f"{s.file_path}:{s.line}"
        bridge.log(f"{icon} [{s.category.upper()}] in {s.name or '?'}")
        bridge.log(f"    Location: {loc}")
        bridge.log(f"    Issue:    {s.message}")
        if s.suggestion:
            bridge.log(f"    Fix:      {s.suggestion}")
        if s.llm_analysis:
            bridge.log(f"    AI Tip:   {s.llm_analysis}")
        bridge.log("")

    bridge.log(f"Summary: {summary['total']} issues ({summary['critical']} critical)")


def print_duplicates(duplicates: List[DuplicateGroup], summary: Dict[str, Any]):
    """Print the ASCII duplicate report."""
    print(f"\n{SEP}")
    print("SIMILAR FUNCTIONS (X-Ray)")
    print(f"{SEP}")
    bridge = get_bridge()
    bridge.log(f"\n{SEP}")
    bridge.log("SIMILAR FUNCTIONS (X-Ray)")
    bridge.log(f"{SEP}")

    if not duplicates:
        bridge.log("No significant duplication found.")
        return

    for g in duplicates:
        print(
            f"Group {g.group_id} ({g.similarity_type}, avg sim: {g.avg_similarity:.2f})"
        )
        bridge.log(f"Group {g.group_id} ({g.similarity_type}, avg sim: {g.avg_similarity:.2f})")
        for f in g.functions:
            bridge.log(f"  - {f['file']}:{f['line']} ({f['name']})")
        bridge.log("")


def print_format_report(issues: List[SmellIssue], summary: Dict[str, Any]):
    """Print the ASCII format report (Ruff format --check results)."""
    print(f"\n{SEP}")
    print("FORMAT REPORT (Ruff)")
    print(f"{SEP}")

    if not issues:
        print("All files are formatted. Clean code.")
        return

    print(f"  Total: {summary['total']} file(s) need formatting")
    print("")
    for s in issues[:30]:
        print(f"    {s.file_path}")
    if len(issues) > 30:
        print(f"    ... and {len(issues) - 30} more")
    print("")
    print("  Fix: ruff format .")


def print_lint_report(issues: List[SmellIssue], summary: Dict[str, Any]):
    """Print the ASCII lint report (Ruff results)."""
    bridge = get_bridge()
    bridge.log(f"\n{SEP}")
    bridge.log("LINT REPORT (Ruff)")
    bridge.log(f"{SEP}")

    if not issues:
        bridge.log("No lint issues found! Clean code.")
        return

    # Show top issues by rule (not every single issue)
    by_rule = summary.get("by_rule", {})
    print(
        f"  Total: {summary['total']} issues ({summary.get('fixable', 0)} auto-fixable)"
    )
    print(
        f"  Critical: {summary['critical']}  "
        f"Warning: {summary['warning']}  "
        f"Info: {summary.get('info', 0)}"
    )
    print("")

    print("  Top Rules:")
    bridge.log(f"  Total: {summary['total']} issues "
               f"({summary.get('fixable', 0)} auto-fixable)")
    bridge.log(f"  Critical: {summary['critical']}  "
               f"Warning: {summary['warning']}  "
               f"Info: {summary.get('info', 0)}")
    bridge.log("")

    bridge.log("  Top Rules:")
    for rule, count in sorted(by_rule.items(), key=lambda x: -x[1])[:10]:
        bridge.log(f"    {count:4d}  {rule}")
    bridge.log("")

    # Show worst files
    worst = summary.get("worst_files", {})
    if worst:
        bridge.log("  Worst Files:")
        for f, count in sorted(worst.items(), key=lambda x: -x[1])[:10]:
            bridge.log(f"    {count:4d}  {f}")
    bridge.log("")

    # Show critical issues in detail
    critical = [i for i in issues if i.severity == Severity.CRITICAL]
    if critical:
        bridge.log(f"  Critical Issues ({len(critical)}):")
        for s in critical[:20]:
            icon = Severity.icon(s.severity)
            bridge.log(f"    {icon} {s.file_path}:{s.line} — {s.message}")
            if s.suggestion:
                bridge.log(f"       Fix: {s.suggestion}")
        if len(critical) > 20:
            bridge.log(f"    ... and {len(critical) - 20} more")


def print_security_report(issues: List[SmellIssue], summary: Dict[str, Any]):
    """Print the ASCII security report (Bandit results)."""
    bridge = get_bridge()
    bridge.log(f"\n{SEP}")
    bridge.log("SECURITY REPORT (Bandit)")
    bridge.log(f"{SEP}")

    if not issues:
        bridge.log("No security issues found! Secure code.")
        return

    print(f"  Total: {summary['total']} issues")
    print(
        f"  Critical (HIGH): {summary['critical']}  "
        f"Warning (MEDIUM): {summary['warning']}  "
        f"Info (LOW): {summary.get('info', 0)}"
    )
    print("")
    bridge.log(f"  Total: {summary['total']} issues")
    bridge.log(f"  Critical (HIGH): {summary['critical']}  "
               f"Warning (MEDIUM): {summary['warning']}  "
               f"Info (LOW): {summary.get('info', 0)}")
    bridge.log("")

    _print_issues_by_severity(issues, Severity.CRITICAL, "HIGH Severity")
    _print_issues_by_severity(issues, Severity.WARNING, "MEDIUM Severity", limit=15)

    by_rule = summary.get("by_rule", {})
    if by_rule:
        bridge.log("  Issue Types:")
        for rule, count in sorted(by_rule.items(), key=lambda x: -x[1])[:10]:
            bridge.log(f"    {count:4d}  {rule}")


def _print_issues_by_severity(
    issues: List[SmellIssue], severity: str, label: str, *, limit: int = 0
):
    """Print issues of a given severity with optional limit."""
    bridge = get_bridge()
    filtered = [i for i in issues if i.severity == severity]
    if not filtered:
        return
    bridge.log(f"  {label} ({len(filtered)}):")
    show = filtered[:limit] if limit else filtered
    for s in show:
        icon = Severity.icon(s.severity)
        bridge.log(f"    {icon} {s.file_path}:{s.line} — {s.message}")
        if s.suggestion and not limit:
            bridge.log(f"       Fix: {s.suggestion}")
    if limit and len(filtered) > limit:
        bridge.log(f"    ... and {len(filtered) - limit} more")
    bridge.log("")


# ── Grade helpers (extracted to reduce complexity) ──────────────

_GRADE_THRESHOLDS = [
    (97, "A+"),
    (93, "A"),
    (90, "A-"),
    (87, "B+"),
    (83, "B"),
    (80, "B-"),
    (77, "C+"),
    (73, "C"),
    (70, "C-"),
    (67, "D+"),
    (63, "D"),
    (60, "D-"),
]


def _score_to_letter(score: float) -> str:
    """Map a numeric score (0-100) to a letter grade."""
    for threshold, letter in _GRADE_THRESHOLDS:
        if score >= threshold:
            return letter
    return "F"


# Per-category penalty rules: (key, tool_label, weights, cap, extra_fields)
_PENALTY_RULES: List[tuple] = [
    (
        "smells",
        "X-Ray Smells",
        {"critical": 0.25, "warning": 0.05, "info": 0.01},
        30,
        [],
    ),
    ("duplicates", "X-Ray Duplicates", {}, 15, []),
    ("format", "Ruff Format", {"warning": 0.1}, 10, []),
    (
        "lint",
        "Ruff Lint",
        {"critical": 0.3, "warning": 0.05, "info": 0.005},
        25,
        ["fixable"],
    ),
    (
        "security",
        "Bandit Security",
        {"critical": 1.5, "warning": 0.3, "info": 0.005},
        30,
        [],
    ),
    ("smells",     "X-Ray Smells",    {"critical": 0.25,  "warning": 0.05, "info": 0.01},  30, []),
    ("duplicates", "X-Ray Duplicates", {},  15, []),
    ("lint",       "Ruff Lint",       {"critical": 0.3,   "warning": 0.05, "info": 0.005}, 25, ["fixable"]),
    ("security",   "Bandit Security", {"critical": 1.5,   "warning": 0.3,  "info": 0.005}, 30, []),
    ("web",        "Web Smells (JS/TS)", {"critical": 0.25, "warning": 0.05, "info": 0.01}, 20, []),
    ("health",     "Project Health",  {},  10, []),
]


def _calc_category_penalty(data: Dict[str, Any], key: str) -> tuple:
    """Calculate penalty and breakdown for one category.

    Returns (penalty, detail_dict) or (0, None) if the key has a
    special shape (e.g. duplicates).
    """
    for rule_key, _, weights, cap, extras in _PENALTY_RULES:
        if rule_key != key:
            continue
        if key == "duplicates":
            total_groups = data.get("total_groups", 0)
            penalty = min(total_groups * 0.1, cap)
            return penalty, {"penalty": round(penalty, 1), "groups": total_groups}
        if key == "health":
            # Health penalty: invert the health score (100 - health_score)
            # scaled down to cap
            health_score = data.get("health_score", 100)
            checks_failed = data.get("checks_total", 0) - data.get("checks_passed", 0)
            penalty = min(checks_failed * 1.0, cap)
            return penalty, {"penalty": round(penalty, 1),
                             "health_score": health_score,
                             "checks_failed": checks_failed}
        counts = {k: data.get(k, 0) for k in weights}
        penalty = sum(counts[k] * w for k, w in weights.items())
        penalty = min(penalty, cap)
        detail: Dict[str, Any] = {"penalty": round(penalty, 1), **counts}
        for ef in extras:
            detail[ef] = data.get(ef, 0)
        return penalty, detail
    return 0, None


def _print_breakdown(breakdown: Dict[str, Any]) -> None:
    """Print the per-tool penalty table."""
    bridge = get_bridge()
    for tool, detail in breakdown.items():
        penalty = detail.get("penalty", 0)
        other = {k: v for k, v in detail.items() if k != "penalty"}
        details = ", ".join(f"{k}={v}" for k, v in other.items())
        bridge.log(f"    -{penalty:5.1f} pts  {tool:20s}  ({details})")


def compute_grade(results: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate quality grade from scan results (no printing).

    Returns dict with score, letter, breakdown, tools_run.
    """
    score = 100.0
    breakdown: Dict[str, Any] = {}
    tools_run: List[str] = []

    for key, tool_label, _w, _c, _e in _PENALTY_RULES:
        if key not in results:
            continue
        tools_run.append(tool_label)
        penalty, detail = _calc_category_penalty(results[key], key)
        if detail is not None:
            score -= penalty
            breakdown[key] = detail

    score = max(0, round(score, 1))
    letter = _score_to_letter(score)

    return {
        "score": score,
        "letter": letter,
        "breakdown": breakdown,
        "tools_run": tools_run,
    }


def print_unified_grade(results: Dict[str, Any],
                        prev_results: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Calculate and print a unified code quality grade based on all scanners.

    The grading system:
      - Starts at 100 points (A+)
      - Deducts points for issues found by each scanner
      - Maps final score to letter grade

    Parameters
    ----------
    prev_results :
        Optional previous scan result dict (from ``Analysis.trend.load_prev_results``).
        When provided, a score delta line is printed below the grade.

    Returns grade_info dict with score, letter, breakdown, and optional delta.
    """
    print(f"\n{'=' * 64}")
    print("  UNIFIED CODE QUALITY GRADE")
    print(f"{'=' * 64}")
    bridge = get_bridge()
    bridge.log(f"\n{'='*64}")
    bridge.log("  UNIFIED CODE QUALITY GRADE")
    bridge.log(f"{'='*64}")

    grade_info = compute_grade(results)

    bridge.log(f"\n  Tools used: {', '.join(grade_info['tools_run'])}")
    bridge.log(f"\n  Score: {grade_info['score']}/100  Grade: {grade_info['letter']}")

    # Trend delta (v6.0.0)
    if prev_results:
        try:
            from Analysis.trend import compare_scans, format_grade_delta
            delta = compare_scans(prev_results, results)
            delta_line = format_grade_delta(delta)
            if delta_line:
                bridge.log(f"  {delta_line}")
            grade_info["delta"] = delta
        except Exception:
            pass

    bridge.log("")
    _print_breakdown(grade_info["breakdown"])
    print(f"\n{'=' * 64}\n")
    bridge.log(f"\n{'='*64}\n")

    return grade_info


def print_library_report(suggestions: List[LibrarySuggestion], summary: Dict[str, Any]):
    """Print library structure suggestions."""
    print(f"\n{SEP}")
    print("LIBRARY EXTRACTION")
    print(f"{SEP}")
    bridge = get_bridge()
    bridge.log(f"\n{SEP}")
    bridge.log("LIBRARY EXTRACTION")
    bridge.log(f"{SEP}")

    if not suggestions:
        bridge.log("No library extraction suggestions.")
        return

    for s in suggestions:
        bridge.log(f"Proposed Module: {s.module_name}")
        bridge.log(f"  Rationale: {s.rationale}")
        bridge.log(f"  Unified API: {s.unified_api}")
        bridge.log(f"  Candidates ({len(s.functions)}):")
        for f in s.functions[:3]:
            bridge.log(f"    - {f['file']}:{f['line']}")
        if len(s.functions) > 3:
            bridge.log(f"    ... and {len(s.functions) - 3} more")
        bridge.log("")


def print_web_report(issues: List[SmellIssue], summary: Dict[str, Any]):
    """Print the ASCII web smell report (JS/TS/React results)."""
    bridge = get_bridge()
    bridge.log(f"\n{SEP}")
    bridge.log("WEB SMELL REPORT (JS/TS/React)")
    bridge.log(f"{SEP}")

    if not issues:
        bridge.log("No web smells found! Clean code.")
        return

    bridge.log(f"  Files scanned: {summary.get('files_scanned', 0)}")
    bridge.log(f"  Functions found: {summary.get('total_functions', 0)}")
    bridge.log(f"  React components: {summary.get('react_components', 0)}")
    bridge.log(f"  Console.log calls: {summary.get('console_logs_total', 0)}")
    bridge.log(f"  Total issues: {summary['total']} "
               f"({summary['critical']} critical, "
               f"{summary['warning']} warning, "
               f"{summary.get('info', 0)} info)")
    bridge.log("")

    # Package categories
    pkg_cats = summary.get("package_categories", {})
    if pkg_cats:
        bridge.log("  Package Categories Detected:")
        for cat, count in sorted(pkg_cats.items(), key=lambda x: -x[1]):
            bridge.log(f"    {count:3d}  {cat}")
        bridge.log("")

    # Top issues by category
    by_cat = summary.get("by_category", {})
    if by_cat:
        bridge.log("  Issues by Category:")
        for cat, count in sorted(by_cat.items(), key=lambda x: -x[1]):
            bridge.log(f"    {count:3d}  {cat}")
        bridge.log("")

    # Critical issues
    critical = [i for i in issues if i.severity == Severity.CRITICAL]
    if critical:
        bridge.log(f"  Critical Issues ({len(critical)}):")
        for s in critical[:15]:
            icon = Severity.icon(s.severity)
            bridge.log(f"    {icon} {s.file_path}:{s.line} - {s.message}")
            if s.suggestion:
                bridge.log(f"       Fix: {s.suggestion}")
        if len(critical) > 15:
            bridge.log(f"    ... and {len(critical) - 15} more")
    bridge.log("")


def print_health_report(report, summary: Dict[str, Any]):
    """Print the ASCII project health report."""
    bridge = get_bridge()
    bridge.log(f"\n{SEP}")
    bridge.log("PROJECT HEALTH REPORT")
    bridge.log(f"{SEP}")

    bridge.log(f"  Health Score: {report.score}/100  Grade: {report.grade}")
    bridge.log(f"  Checks: {summary.get('checks_passed', 0)}/"
               f"{summary.get('checks_total', 0)} passed")
    bridge.log("")

    for check in report.checks:
        icon = "✅" if check.passed else "❌"
        bridge.log(f"  {icon} {check.name:<20} (weight: {check.weight})")
        if not check.passed and check.detail:
            bridge.log(f"     → {check.detail}")

    if report.files_created:
        bridge.log(f"\n  Auto-Created Files:")
        for f in report.files_created:
            bridge.log(f"    ✔ {f}")
    bridge.log("")


def _build_smell_summary(smells):
    """Build smell summary dict."""
    return {
        "total": len(smells),
        "critical": sum(1 for s in smells if s.severity == Severity.CRITICAL),
        "warning": sum(1 for s in smells if s.severity == Severity.WARNING),
        "issues": [
            {
                "file": s.file_path,
                "line": s.line,
                "name": s.name,
                "category": s.category,
                "severity": s.severity,
                "message": s.message,
                "suggestion": s.suggestion,
                "llm_analysis": s.llm_analysis,
                "source": s.source,
            }
            for s in smells
        ],
    }


def _build_dup_summary(duplicates):
    """Build duplicate summary dict."""
    return {
        "total_groups": len(duplicates),
        "total_functions_involved": sum(len(g.functions) for g in duplicates),
        "groups": [
            {
                "id": g.group_id,
                "type": g.similarity_type,
                "avg_sim": g.avg_similarity,
                "functions": g.functions,
            }
            for g in duplicates
        ],
    }


def _build_lib_summary(suggestions):
    """Build library suggestion summary dict."""
    return {
        "total": len(suggestions),
        "suggestions": [
            {
                "module": s.module_name,
                "rationale": s.rationale,
                "api": s.unified_api,
                "candidates": s.functions,
            }
            for s in suggestions
        ],
    }


def build_json_report(
    root: Path, scan_data: ScanData, scan_time: float
) -> Dict[str, Any]:
    """Construct the full JSON report dictionary."""
    functions = scan_data.functions
    classes = scan_data.classes

    return {
        "version": __version__,
        "scan_time_seconds": scan_time,
        "root": str(root),
        "stats": {
            "total_functions": len(functions),
            "total_classes": len(classes),
            "avg_complexity": sum(f.complexity for f in functions) / len(functions)
            if functions
            else 0,
        },
        "smells": _build_smell_summary(scan_data.smells),
        "duplicates": _build_dup_summary(scan_data.duplicates),
        "library_suggestions": _build_lib_summary(scan_data.suggestions),
        "functions": [
            {
                "name": f.name,
                "file": f.file_path,
                "complexity": f.complexity,
                "loc": f.size_lines,
            }
            for f in functions
        ],
    }
