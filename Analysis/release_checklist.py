"""Analysis/release_checklist.py — Go / No-Go release checklist generator.

Aggregates results from all X-Ray analyzers into a single human-readable
checklist that a team lead can review before shipping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Any


@dataclass
class ChecklistItem:
    """Single pass/fail item in the release checklist."""
    label: str
    passed: bool
    detail: str = ""    # short explanation when failed
    severity: str = ""  # "blocker", "warning", "info"


@dataclass
class ReleaseChecklist:
    """Complete go/no-go checklist."""
    items: List[ChecklistItem] = field(default_factory=list)
    go: bool = True
    blockers: int = 0
    warnings: int = 0


def generate_checklist(
    results: Dict[str, Any],
    *,
    min_grade: str = "B",
    max_critical: int = 0,
    min_docstring_pct: float = 40.0,
) -> ReleaseChecklist:
    """Build a release checklist from the combined scan results dict.

    Parameters
    ----------
    results : dict
        The combined results dict from ``collect_reports()``.
    min_grade : str
        Minimum acceptable overall grade (default "B").
    max_critical : int
        Maximum allowed critical issues across all analyzers.
    min_docstring_pct : float
        Minimum docstring coverage percentage.
    """
    items: List[ChecklistItem] = []

    # ── 1. Overall grade ─────────────────────────────────────────────
    grade_info = results.get("grade", {})
    score = grade_info.get("score", 0)
    letter = grade_info.get("letter", "?")
    grade_ok = _grade_ge(letter, min_grade)
    items.append(ChecklistItem(
        label=f"Overall grade ≥ {min_grade}",
        passed=grade_ok,
        detail=f"Score {score}/100 — Grade {letter}",
        severity="blocker" if not grade_ok else "",
    ))

    # ── 2. No critical security issues ───────────────────────────────
    sec = results.get("security", {})
    sec_crit = sec.get("critical", 0)
    items.append(ChecklistItem(
        label="No critical security issues",
        passed=sec_crit == 0,
        detail=f"{sec_crit} critical security finding(s)" if sec_crit else "",
        severity="blocker" if sec_crit else "",
    ))

    # ── 3. No critical lint / smells ─────────────────────────────────
    total_crit = 0
    for key in ("smells", "lint", "typecheck"):
        total_crit += results.get(key, {}).get("critical", 0)
    crit_ok = total_crit <= max_critical
    items.append(ChecklistItem(
        label=f"Critical issues ≤ {max_critical}",
        passed=crit_ok,
        detail=f"{total_crit} critical issue(s) across smells/lint/typecheck" if not crit_ok else "",
        severity="blocker" if not crit_ok else "",
    ))

    # ── 4. NOCOMMIT markers ──────────────────────────────────────────
    release = results.get("release_readiness", {})
    markers_by_kind = release.get("markers_by_kind", {})
    nocommit = markers_by_kind.get("NOCOMMIT", 0)
    items.append(ChecklistItem(
        label="No NOCOMMIT markers",
        passed=nocommit == 0,
        detail=f"{nocommit} NOCOMMIT comment(s) found" if nocommit else "",
        severity="blocker" if nocommit else "",
    ))

    # ── 5. TODO/FIXME count ──────────────────────────────────────────
    fixme_count = markers_by_kind.get("FIXME", 0) + markers_by_kind.get("HACK", 0)
    todo_count = markers_by_kind.get("TODO", 0)
    items.append(ChecklistItem(
        label="FIXME/HACK markers reviewed",
        passed=fixme_count == 0,
        detail=f"{fixme_count} FIXME/HACK + {todo_count} TODO comment(s)" if fixme_count else f"{todo_count} TODO(s) remaining",
        severity="warning" if fixme_count else ("info" if todo_count else ""),
    ))

    # ── 6. Docstring coverage ────────────────────────────────────────
    doc_pct = release.get("docstring_coverage_pct", 100.0)
    doc_ok = doc_pct >= min_docstring_pct
    items.append(ChecklistItem(
        label=f"Docstring coverage ≥ {min_docstring_pct:.0f}%",
        passed=doc_ok,
        detail=f"{doc_pct:.1f}% documented ({release.get('docstring_documented', 0)}/{release.get('docstring_total', 0)})",
        severity="warning" if not doc_ok else "",
    ))

    # ── 7. Dependency vulnerabilities ────────────────────────────────
    vuln_count = release.get("vulnerabilities", 0)
    dep_avail = release.get("dep_audit_available", False)
    if dep_avail:
        items.append(ChecklistItem(
            label="No known dependency CVEs",
            passed=vuln_count == 0,
            detail=f"{vuln_count} vulnerability(ies) found" if vuln_count else "",
            severity="blocker" if vuln_count else "",
        ))
    else:
        items.append(ChecklistItem(
            label="Dependency audit (pip-audit)",
            passed=False,
            detail="pip-audit not installed — install with: pip install pip-audit",
            severity="info",
        ))

    # ── 8. Version consistency ───────────────────────────────────────
    versions_ok = release.get("versions_consistent", True)
    vsources = release.get("version_sources", [])
    if vsources:
        items.append(ChecklistItem(
            label="Version strings consistent",
            passed=versions_ok,
            detail="" if versions_ok else "Mismatched: " + ", ".join(
                f'{s["source"]}={s["version"]}' for s in vsources
            ),
            severity="warning" if not versions_ok else "",
        ))

    # ── 9. Dependencies pinned ───────────────────────────────────────
    unpinned = release.get("unpinned_deps", 0)
    items.append(ChecklistItem(
        label="Dependencies pinned (==)",
        passed=unpinned == 0,
        detail=f"{unpinned} unpinned package(s) in requirements" if unpinned else "",
        severity="warning" if unpinned else "",
    ))

    # ── 10. No orphan modules ────────────────────────────────────────
    orphans = release.get("orphan_modules", 0)
    items.append(ChecklistItem(
        label="No orphan modules (dead files)",
        passed=orphans == 0,
        detail=f"{orphans} unreferenced module(s)" if orphans else "",
        severity="info" if orphans else "",
    ))

    # ── 11. Tests pass (from health check if available) ──────────────
    health = results.get("health", {})
    if health:
        items.append(ChecklistItem(
            label="Project health check passes",
            passed=health.get("score", 0) >= 70,
            detail=f"Health score: {health.get('score', 0)}",
            severity="warning" if health.get("score", 0) < 70 else "",
        ))

    # ── Aggregate ────────────────────────────────────────────────────
    blockers = sum(1 for i in items if not i.passed and i.severity == "blocker")
    warnings = sum(1 for i in items if not i.passed and i.severity == "warning")

    return ReleaseChecklist(
        items=items,
        go=blockers == 0,
        blockers=blockers,
        warnings=warnings,
    )


def format_checklist(checklist: ReleaseChecklist) -> str:
    """Render checklist as a human-readable string."""
    lines = []
    lines.append("")
    lines.append("  " + "=" * 60)
    verdict = "GO" if checklist.go else "NO-GO"
    icon = "\u2705" if checklist.go else "\u274c"
    lines.append(f"  {icon}  RELEASE READINESS: {verdict}")
    if checklist.blockers:
        lines.append(f"     {checklist.blockers} blocker(s), {checklist.warnings} warning(s)")
    lines.append("  " + "=" * 60)
    lines.append("")

    for item in checklist.items:
        mark = "\u2705" if item.passed else ("\U0001f534" if item.severity == "blocker" else "\U0001f7e1")
        line = f"  {mark} {item.label}"
        if item.detail:
            line += f"  — {item.detail}"
        lines.append(line)

    lines.append("")
    return "\n".join(lines)


# ── Grade comparison helper ──────────────────────────────────────────

_GRADE_ORDER = ["A+", "A", "A-", "B+", "B", "B-", "C", "D", "F"]


def _grade_ge(actual: str, minimum: str) -> bool:
    """Return True if *actual* grade is >= *minimum*."""
    try:
        return _GRADE_ORDER.index(actual) <= _GRADE_ORDER.index(minimum)
    except ValueError:
        return False
