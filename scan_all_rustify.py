"""
scan_all_rustify.py — Full Transpiler Audit Across ALL Projects
=================================================================

Scans EVERY Python project under C:\\Users\\Yo930\\Desktop\\_Python
(including OLD_STUFF — old code is perfect training data).

Produces:
  1. Console report — per-project stats + grand total
  2. rustify_all_projects.json — full results
  3. _training_ground/blocked/  — Python functions we CAN'T transpile yet,
     grouped by blocker reason (training data for improving the transpiler)
  4. _training_ground/transpiled/ — functions we CAN transpile,
     saved as .py + .rs pairs (validation data)
"""

from __future__ import annotations

import re as _re
import sys
import time
import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Any
from collections import Counter

# Ensure X_Ray root on path
XRAY_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(XRAY_ROOT))

from Core.scan_phases import scan_codebase  # noqa: E402
from Analysis.rust_advisor import RustAdvisor  # noqa: E402
from Analysis.auto_rustify import (  # noqa: E402
    _is_transpilable,
    _has_name_blocker,
    _ALL_BLOCKERS,
    _FRAMEWORK_MARKERS,
    _UNTRANSLATABLE,
    _PY_MODULE_MARKERS,
)
from Analysis.transpiler import transpile_function_code  # noqa: E402

# ── Configuration ─────────────────────────────────────────────────────

BASE_DIR = Path(r"C:\Users\Yo930\Desktop\_Python")

# Only skip third-party / environment dirs (not our code)
THIRD_PARTY = {
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    ".git",
    "site-packages",
    ".pytest_cache",
    "egg-info",
    "dist",
    "build",
    ".mypy_cache",
    "target",
    ".tox",
    ".eggs",
    "*.egg-info",
}

# Training ground output
TRAINING_DIR = XRAY_ROOT / "_training_ground"
BLOCKED_DIR = TRAINING_DIR / "blocked"
TRANS_DIR = TRAINING_DIR / "transpiled"


# ── Blocker Diagnosis ─────────────────────────────────────────────────


def _classify_markers(markers_hit):
    """Classify hit markers into category + suggestion."""
    fw = [m for m in markers_hit if m in _FRAMEWORK_MARKERS]
    ut = [m for m in markers_hit if m in _UNTRANSLATABLE]
    pm = [m for m in markers_hit if m in _PY_MODULE_MARKERS]
    if fw:
        return "framework_api", f"Uses GUI/web framework: {', '.join(fw)}"
    if ut:
        return (
            "untranslatable_construct",
            f"Uses Python-only constructs: {', '.join(ut)}",
        )
    if pm:
        return "python_module", f"Needs Rust crate equivalents for: {', '.join(pm)}"
    return "code_blocker_mixed", f"Multiple blockers: {', '.join(markers_hit[:5])}"


_STRING_RE = _re.compile(r'["\'].*?["\']')
_EXT_CALL_RE = _re.compile(r"\b\w+\.\w+\(")


def _string_ratio(code: str) -> str:
    total = sum(len(m.group()) for m in _STRING_RE.finditer(code))
    return "{}% string literals".format(round(100 * total / len(code)))


def _ext_call_msg(code: str) -> str:
    return "{} external method calls (limit 20)".format(len(_EXT_CALL_RE.findall(code)))


_PATTERN_CHECKS = [
    (
        "mostly_strings",
        lambda code: (
            len(code) > 50
            and sum(len(m.group()) for m in _STRING_RE.finditer(code)) / len(code) > 0.7
        ),
        _string_ratio,
        "Function is mostly string data, not logic",
    ),
    (
        "too_long",
        lambda code: code.count("\n") > 500,
        lambda code: "{} lines (limit 500)".format(code.count("\n")),
        "Split into smaller functions",
    ),
    (
        "too_many_external_calls",
        lambda code: len(_EXT_CALL_RE.findall(code)) > 20,
        _ext_call_msg,
        "Heavy external API usage — needs crate mappings",
    ),
]


def diagnose_blockers(name: str, code: str) -> Dict[str, Any]:
    """Return a detailed diagnosis of WHY a function can't be transpiled."""
    result: Dict[str, Any] = {
        "reason": "",
        "markers_hit": [],
        "pattern_issues": [],
        "suggestion": "",
    }

    if _has_name_blocker(name):
        if name.startswith("test_"):
            result["reason"] = "test_function"
            result["suggestion"] = "Test functions are skipped by design"
        else:
            result["reason"] = "dunder_method"
            result["suggestion"] = f"Dunder method {name} — needs class transpilation"
        return result

    markers_hit = [m for m in _ALL_BLOCKERS if m in code]
    if markers_hit:
        result["markers_hit"] = markers_hit
        result["reason"], result["suggestion"] = _classify_markers(markers_hit)
        return result

    if code:
        for reason, check, issue_fn, suggestion in _PATTERN_CHECKS:
            if check(code):
                result["reason"] = reason
                result["pattern_issues"].append(issue_fn(code))
                result["suggestion"] = suggestion
                return result

    if code:
        unresolvable = len(_re.findall(r"\b[a-z_]\w+\(", code))
        result["reason"] = "too_many_unresolvable_calls"
        result["pattern_issues"].append(f"{unresolvable} function calls (limit 20)")
        result["suggestion"] = "Too many unknown function references"
    else:
        result["reason"] = "empty_code"
        result["suggestion"] = "No source code available"
    return result


# ── Project Discovery ─────────────────────────────────────────────────


def _is_third_party(path: str) -> bool:
    """Check if path contains a third-party directory."""
    parts = path.replace("\\", "/").split("/")
    return any(p in THIRD_PARTY for p in parts)


def _scan_subprojects(entry: Path) -> List[Path]:
    """Scan a "Projects" folder for individual sub-projects with .py files."""
    subs = []
    for sp in sorted(entry.iterdir()):
        if not sp.is_dir() or sp.name in THIRD_PARTY or sp.name.startswith("."):
            continue
        sp_py = [f for f in sp.rglob("*.py") if not _is_third_party(str(f))]
        if sp_py:
            subs.append(sp)
    return subs


def discover_projects(base: Path) -> List[Path]:
    """Find ALL directories that contain .py files.

    Scans everything — OLD_STUFF, archives, sub-projects, you name it.
    Only skips .venv/node_modules/site-packages (third-party, not our code).
    """
    projects = []
    for entry in sorted(base.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        if entry.name in THIRD_PARTY:
            continue

        py_files = [f for f in entry.rglob("*.py") if not _is_third_party(str(f))]
        if not py_files:
            continue

        if entry.name == "Projects":
            projects.extend(_scan_subprojects(entry))
        else:
            projects.append(entry)

    return projects


# ── Project Scanner ───────────────────────────────────────────────────


def _try_transpile(func, code, project_name):
    """Attempt transpilation; return a result dict."""
    base = {
        "name": getattr(func, "name", ""),
        "file": str(getattr(func, "file", "")),
        "project": project_name,
        "python_code": code,
        "python_lines": code.count("\n") + 1,
    }
    try:
        rust = transpile_function_code(code)
        todo_count = rust.count("todo!()")
        return {
            **base,
            "rust_code": rust,
            "rust_lines": rust.count("\n") + 1,
            "todo_count": todo_count,
            "clean": todo_count == 0,
        }
    except Exception as ex:
        return {
            **base,
            "rust_code": f"// TRANSPILE ERROR: {ex}",
            "rust_lines": 0,
            "todo_count": 0,
            "clean": False,
            "error": str(ex),
        }


@dataclass
class _ClassifyCtx:
    """Mutable context for _classify_function accumulators."""

    project_name: str
    blocker_counts: Counter
    marker_freq: Counter
    blocked_out: List[Dict[str, Any]]
    transpiled_out: List[Dict[str, Any]]


def _classify_function(func, ctx: _ClassifyCtx):
    """Classify one function as transpilable or blocked, appending to lists."""
    code = getattr(func, "code", "") or ""
    name = getattr(func, "name", "") or ""

    if _is_transpilable(func):
        if code.strip() and len(code) < 5000:
            ctx.transpiled_out.append(_try_transpile(func, code, ctx.project_name))
        return True

    diag = diagnose_blockers(name, code)
    ctx.blocker_counts[diag["reason"]] += 1
    for m in diag.get("markers_hit", []):
        ctx.marker_freq[m] += 1
    ctx.blocked_out.append(
        {
            "name": name,
            "file": str(getattr(func, "file", "")),
            "project": ctx.project_name,
            "python_code": code[:3000],
            "lines": code.count("\n") + 1 if code else 0,
            "reason": diag["reason"],
            "markers_hit": diag["markers_hit"],
            "pattern_issues": diag["pattern_issues"],
            "suggestion": diag["suggestion"],
        }
    )
    return False


_EMPTY_PROJECT = {
    "total_functions": 0,
    "transpilable": 0,
    "transpilable_pct": 0.0,
    "blocker_breakdown": {},
    "blocker_marker_freq": {},
    "top_candidates": [],
    "blocked_functions": [],
    "transpiled_functions": [],
}


def scan_project(project_path: Path) -> Dict[str, Any]:
    """Scan a single project, classify every function, collect training data."""
    t0 = time.time()
    exclude = list(THIRD_PARTY)

    try:
        functions, classes, _errors = scan_codebase(project_path, exclude=exclude)
    except Exception as e:
        return {
            "name": project_path.name,
            "error": str(e),
            "blocked_functions": [],
            "transpiled_functions": [],
        }

    if not functions:
        return {
            "name": project_path.name,
            "path": str(project_path),
            "total_classes": len(classes),
            **_EMPTY_PROJECT,
            "time_s": round(time.time() - t0, 2),
        }

    advisor = RustAdvisor()
    candidates = advisor.score(functions)

    ctx = _ClassifyCtx(
        project_name=project_path.name,
        blocker_counts=Counter(),
        marker_freq=Counter(),
        blocked_out=[],
        transpiled_out=[],
    )

    transpilable = sum(_classify_function(fn, ctx) for fn in functions)

    top_info = [
        {
            "name": c.func.name,
            "score": round(c.score, 1),
            "is_pure": c.is_pure,
            "complexity": c.func.complexity,
        }
        for c in candidates[:5]
    ]

    total = len(functions)
    return {
        "name": project_path.name,
        "path": str(project_path),
        "total_functions": total,
        "total_classes": len(classes),
        "transpilable": transpilable,
        "transpilable_pct": round(100 * transpilable / total, 1),
        "blocker_breakdown": dict(ctx.blocker_counts.most_common()),
        "blocker_marker_freq": dict(ctx.marker_freq.most_common(20)),
        "top_candidates": top_info,
        "blocked_functions": ctx.blocked_out,
        "transpiled_functions": ctx.transpiled_out,
        "time_s": round(time.time() - t0, 2),
    }


# ── Training Ground Output ───────────────────────────────────────────


def _write_jsonl(path: Path, items):
    """Write a list of dicts as JSONL to *path*."""
    with open(path, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def _group_and_write(items, key_fn, out_dir, sanitize_fn):
    """Group *items* by key, write each group as JSONL, return counts."""
    groups: Dict[str, List[Dict]] = {}
    for item in items:
        for key in key_fn(item):
            groups.setdefault(key, []).append(item)
    counts = {}
    for key in sorted(groups, key=lambda k: -len(groups[k])):
        safe = sanitize_fn(key)
        _write_jsonl(out_dir / f"{safe}.jsonl", groups[key])
        counts[key] = len(groups[key])
    return counts


def _safe_reason(reason):
    return reason.replace(" ", "_").replace("/", "_")


def _safe_marker(marker):
    s = (
        marker.strip()
        .replace(".", "_")
        .replace("(", "")
        .replace(")", "")
        .replace(" ", "_")
        .replace("*", "star")
        .replace("{", "brace")
        .replace("}", "")
    )
    return s or "empty"


def save_training_ground(all_results: List[Dict[str, Any]]) -> Dict[str, int]:
    """Save blocked functions as training data and transpiled pairs."""
    BLOCKED_DIR.mkdir(parents=True, exist_ok=True)
    (BLOCKED_DIR / "by_reason").mkdir(exist_ok=True)
    (BLOCKED_DIR / "by_marker").mkdir(exist_ok=True)
    TRANS_DIR.mkdir(parents=True, exist_ok=True)

    all_blocked: List[Dict] = []
    all_transpiled: List[Dict] = []
    for r in all_results:
        all_blocked.extend(r.get("blocked_functions", []))
        all_transpiled.extend(r.get("transpiled_functions", []))

    _write_jsonl(BLOCKED_DIR / "all_blocked.jsonl", all_blocked)

    reason_counts = _group_and_write(
        all_blocked,
        lambda it: [it.get("reason", "unknown")],
        BLOCKED_DIR / "by_reason",
        _safe_reason,
    )
    marker_counts = _group_and_write(
        all_blocked,
        lambda it: it.get("markers_hit", []),
        BLOCKED_DIR / "by_marker",
        _safe_marker,
    )

    _write_jsonl(TRANS_DIR / "pairs.jsonl", all_transpiled)
    clean_count = sum(1 for it in all_transpiled if it.get("clean"))

    stats = {
        "total_blocked": len(all_blocked),
        "total_transpiled": len(all_transpiled),
        "by_reason": reason_counts,
        "by_marker": marker_counts,
        "transpiled_clean": clean_count,
        "transpiled_with_todos": len(all_transpiled) - clean_count,
    }
    with open(TRAINING_DIR / "summary.json", "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)
    return stats


# ── Pretty Printer ────────────────────────────────────────────────────


def print_project_result(result: Dict[str, Any]) -> None:
    """Pretty-print results for a single project."""
    name = result["name"]
    if "error" in result:
        print(f"\n  [!!] {name}: ERROR -- {result['error']}")
        return
    total = result["total_functions"]
    trans = result["transpilable"]
    pct = result.get("transpilable_pct", 0)
    t = result["time_s"]

    bar_len = 30
    filled = int(bar_len * pct / 100) if pct else 0
    bar = "#" * filled + "-" * (bar_len - filled)

    print(f"\n{'_' * 66}")
    print(f"  Project: {name}")
    print(f"  Path:    {result.get('path', '?')}")
    print(f"{'_' * 66}")
    print(f"  Functions: {total:,}   |   Classes: {result.get('total_classes', 0):,}")
    print(f"  Transpilable: {trans:,} / {total:,}  ({pct}%)")
    print(f"  [{bar}] {pct}%")
    print(f"  Scan time: {t:.1f}s")

    # Blocker breakdown
    bd = result.get("blocker_breakdown", {})
    blocked = total - trans
    if blocked > 0:
        print(f"\n  Blocker breakdown ({blocked} blocked):")
        for reason, count in bd.items():
            print(f"    {reason:35s}: {count:4d}")

    # Top marker frequency
    mf = result.get("blocker_marker_freq", {})
    if mf:
        top_markers = sorted(mf.items(), key=lambda x: -x[1])[:8]
        print("\n  Most frequent blocking markers:")
        for marker, count in top_markers:
            print(f"    {repr(marker):25s}: {count:4d} functions")

    # Top candidates
    top = result.get("top_candidates", [])
    if top:
        print("\n  Top Rust candidates:")
        for c in top:
            pure = "PURE" if c["is_pure"] else "    "
            print(
                f"    [{pure}] {c['name']:30s} score={c['score']:6.1f}  cx={c['complexity']}"
            )


def _aggregate_totals(all_results):
    """Sum per-project results into grand totals + global counters."""
    totals = {
        "functions": 0,
        "transpilable": 0,
        "classes": 0,
        "blocked": 0,
        "transpiled_clean": 0,
    }
    global_reasons: Counter = Counter()
    global_markers: Counter = Counter()
    for r in all_results:
        if "error" in r:
            continue
        totals["functions"] += r["total_functions"]
        totals["transpilable"] += r["transpilable"]
        totals["classes"] += r.get("total_classes", 0)
        totals["blocked"] += len(r.get("blocked_functions", []))
        for reason, cnt in r.get("blocker_breakdown", {}).items():
            global_reasons[reason] += cnt
        for marker, cnt in r.get("blocker_marker_freq", {}).items():
            global_markers[marker] += cnt
    return totals, global_reasons, global_markers


def _print_grand_total(projects, totals, elapsed, global_reasons, global_markers):
    """Print the grand-total summary block."""
    grand_pct = (
        round(100 * totals["transpilable"] / totals["functions"], 1)
        if totals["functions"]
        else 0
    )
    print(f"\n{'=' * 66}")
    print("  GRAND TOTAL ACROSS ALL PROJECTS")
    print(f"{'=' * 66}")
    print(f"  Projects scanned:     {len(projects)}")
    print(f"  Total functions:      {totals['functions']:,}")
    print(f"  Total classes:        {totals['classes']:,}")
    print(
        f"  Transpilable:         {totals['transpilable']:,} / {totals['functions']:,}  ({grand_pct}%)"
    )
    print(f"  Clean translations:   {totals['transpiled_clean']:,} (no todo!())")
    print(f"  Blocked (training):   {totals['blocked']:,}")
    print(f"  Total time:           {elapsed:.1f}s")
    print(f"{'=' * 66}")

    if global_reasons:
        print("\n  GLOBAL BLOCKER REASONS:")
        for reason, cnt in global_reasons.most_common():
            print(f"    {reason:35s}: {cnt:5d}")
    if global_markers:
        print("\n  GLOBAL TOP 15 BLOCKING MARKERS (training priorities):")
        for marker, cnt in global_markers.most_common(15):
            print(f"    {repr(marker):25s}: {cnt:5d} functions")
    return grand_pct


@dataclass
class _ReportCtx:
    """Bundle of data for _save_report."""

    all_results: list
    totals: dict
    grand_pct: float
    global_reasons: Counter
    global_markers: Counter
    elapsed: float


def _save_report(ctx: _ReportCtx):
    """Write the slim JSON report (no bulky code)."""
    slim_results = []
    for r in ctx.all_results:
        slim = {
            k: v
            for k, v in r.items()
            if k not in ("blocked_functions", "transpiled_functions")
        }
        slim["blocked_count"] = len(r.get("blocked_functions", []))
        slim["transpiled_count"] = len(r.get("transpiled_functions", []))
        slim_results.append(slim)

    report_path = XRAY_ROOT / "rustify_all_projects.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "projects": slim_results,
                "totals": ctx.totals,
                "grand_pct": ctx.grand_pct,
                "global_blocker_reasons": dict(ctx.global_reasons.most_common()),
                "global_blocker_markers": dict(ctx.global_markers.most_common(30)),
                "training_ground": str(TRAINING_DIR),
                "elapsed_s": round(ctx.elapsed, 2),
            },
            f,
            indent=2,
            ensure_ascii=False,
        )
    print(f"\n  Report: {report_path}")


def main():
    print("=" * 66)
    print("  X-RAY Rust Transpiler -- Full Audit (ALL projects)")
    print(f"  Base: {BASE_DIR}")
    print(f"  Training output: {TRAINING_DIR}")
    print("=" * 66)

    print("\n  Discovering projects (including old/archive code)...")
    projects = discover_projects(BASE_DIR)
    print(f"  Found {len(projects)} scannable projects:")
    for p in projects:
        print(f"    - {p.relative_to(BASE_DIR)}")

    all_results = []
    t_start = time.time()

    for i, proj in enumerate(projects, 1):
        print(f"\n  [{i}/{len(projects)}] Scanning {proj.name}...")
        result = scan_project(proj)
        all_results.append(result)
        print_project_result(result)

    print(f"\n  Saving training ground to {TRAINING_DIR}...")
    tg_stats = save_training_ground(all_results)

    totals, global_reasons, global_markers = _aggregate_totals(all_results)
    totals["transpiled_clean"] = tg_stats.get("transpiled_clean", 0)
    elapsed = time.time() - t_start

    grand_pct = _print_grand_total(
        projects, totals, elapsed, global_reasons, global_markers
    )

    print("\n  TRAINING GROUND SAVED:")
    print(f"    {BLOCKED_DIR / 'all_blocked.jsonl'}")
    print(f"      -> {tg_stats['total_blocked']:,} blocked functions")
    for reason, cnt in sorted(
        tg_stats.get("by_reason", {}).items(), key=lambda x: -x[1]
    ):
        print(f"      {reason}.jsonl ({cnt:,} functions)")
    print(f"    {TRANS_DIR / 'pairs.jsonl'}")
    print(f"      -> {tg_stats['total_transpiled']:,} Python->Rust pairs")
    print(f"      -> {tg_stats.get('transpiled_clean', 0):,} clean (no todo!())")

    _save_report(
        _ReportCtx(
            all_results=all_results,
            totals=totals,
            grand_pct=grand_pct,
            global_reasons=global_reasons,
            global_markers=global_markers,
            elapsed=elapsed,
        )
    )


if __name__ == "__main__":
    main()
