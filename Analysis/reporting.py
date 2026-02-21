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
from Core.config import __version__, SEP


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

    if not smells:
        print("No smells found! Clean code.")
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
        print(f"{icon} [{s.category.upper()}] in {s.name or '?'}")
        print(f"    Location: {loc}")
        print(f"    Issue:    {s.message}")
        if s.suggestion:
            print(f"    Fix:      {s.suggestion}")
        if s.llm_analysis:
            print(f"    AI Tip:   {s.llm_analysis}")
        print("")

    print(f"Summary: {summary['total']} issues ({summary['critical']} critical)")


def print_duplicates(duplicates: List[DuplicateGroup], summary: Dict[str, Any]):
    """Print the ASCII duplicate report."""
    print(f"\n{SEP}")
    print("SIMILAR FUNCTIONS (X-Ray)")
    print(f"{SEP}")

    if not duplicates:
        print("No significant duplication found.")
        return

    for g in duplicates:
        print(
            f"Group {g.group_id} ({g.similarity_type}, avg sim: {g.avg_similarity:.2f})"
        )
        for f in g.functions:
            print(f"  - {f['file']}:{f['line']} ({f['name']})")
        print("")


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
    print(f"\n{SEP}")
    print("LINT REPORT (Ruff)")
    print(f"{SEP}")

    if not issues:
        print("No lint issues found! Clean code.")
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
    for rule, count in sorted(by_rule.items(), key=lambda x: -x[1])[:10]:
        print(f"    {count:4d}  {rule}")
    print("")

    # Show worst files
    worst = summary.get("worst_files", {})
    if worst:
        print("  Worst Files:")
        for f, count in sorted(worst.items(), key=lambda x: -x[1])[:10]:
            print(f"    {count:4d}  {f}")
    print("")

    # Show critical issues in detail
    critical = [i for i in issues if i.severity == Severity.CRITICAL]
    if critical:
        print(f"  Critical Issues ({len(critical)}):")
        for s in critical[:20]:
            icon = Severity.icon(s.severity)
            print(f"    {icon} {s.file_path}:{s.line} — {s.message}")
            if s.suggestion:
                print(f"       Fix: {s.suggestion}")
        if len(critical) > 20:
            print(f"    ... and {len(critical) - 20} more")


def print_security_report(issues: List[SmellIssue], summary: Dict[str, Any]):
    """Print the ASCII security report (Bandit results)."""
    print(f"\n{SEP}")
    print("SECURITY REPORT (Bandit)")
    print(f"{SEP}")

    if not issues:
        print("No security issues found! Secure code.")
        return

    print(f"  Total: {summary['total']} issues")
    print(
        f"  Critical (HIGH): {summary['critical']}  "
        f"Warning (MEDIUM): {summary['warning']}  "
        f"Info (LOW): {summary.get('info', 0)}"
    )
    print("")

    _print_issues_by_severity(issues, Severity.CRITICAL, "HIGH Severity")
    _print_issues_by_severity(issues, Severity.WARNING, "MEDIUM Severity", limit=15)

    by_rule = summary.get("by_rule", {})
    if by_rule:
        print("  Issue Types:")
        for rule, count in sorted(by_rule.items(), key=lambda x: -x[1])[:10]:
            print(f"    {count:4d}  {rule}")


def _print_issues_by_severity(
    issues: List[SmellIssue], severity: str, label: str, *, limit: int = 0
):
    """Print issues of a given severity with optional limit."""
    filtered = [i for i in issues if i.severity == severity]
    if not filtered:
        return
    print(f"  {label} ({len(filtered)}):")
    show = filtered[:limit] if limit else filtered
    for s in show:
        icon = Severity.icon(s.severity)
        print(f"    {icon} {s.file_path}:{s.line} — {s.message}")
        if s.suggestion and not limit:
            print(f"       Fix: {s.suggestion}")
    if limit and len(filtered) > limit:
        print(f"    ... and {len(filtered) - limit} more")
    print("")


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
    for tool, detail in breakdown.items():
        penalty = detail.get("penalty", 0)
        other = {k: v for k, v in detail.items() if k != "penalty"}
        details = ", ".join(f"{k}={v}" for k, v in other.items())
        print(f"    -{penalty:5.1f} pts  {tool:20s}  ({details})")


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


def print_unified_grade(results: Dict[str, Any]) -> Dict[str, Any]:
    """
    Calculate and print a unified code quality grade based on all scanners.

    The grading system:
      - Starts at 100 points (A+)
      - Deducts points for issues found by each scanner
      - Maps final score to letter grade

    Returns grade_info dict with score, letter, and breakdown.
    """
    print(f"\n{'=' * 64}")
    print("  UNIFIED CODE QUALITY GRADE")
    print(f"{'=' * 64}")

    grade_info = compute_grade(results)

    print(f"\n  Tools used: {', '.join(grade_info['tools_run'])}")
    print(f"\n  Score: {grade_info['score']}/100  Grade: {grade_info['letter']}")
    print("")
    _print_breakdown(grade_info["breakdown"])
    print(f"\n{'=' * 64}\n")

    return grade_info


def print_library_report(suggestions: List[LibrarySuggestion], summary: Dict[str, Any]):
    """Print library structure suggestions."""
    print(f"\n{SEP}")
    print("LIBRARY EXTRACTION")
    print(f"{SEP}")

    if not suggestions:
        print("No library extraction suggestions.")
        return

    for s in suggestions:
        print(f"Proposed Module: {s.module_name}")
        print(f"  Rationale: {s.rationale}")
        print(f"  Unified API: {s.unified_api}")
        print(f"  Candidates ({len(s.functions)}):")
        for f in s.functions[:3]:
            print(f"    - {f['file']}:{f['line']}")
        if len(s.functions) > 3:
            print(f"    ... and {len(s.functions) - 3} more")
        print("")


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
