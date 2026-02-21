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

import os
import re as _re
import sys
import time
import json
import textwrap
from pathlib import Path
from typing import List, Dict, Any, Tuple
from collections import Counter

# Ensure X_Ray root on path
XRAY_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(XRAY_ROOT))

from Core.scan_phases import scan_codebase
from Analysis.rust_advisor import RustAdvisor
from Analysis.auto_rustify import (
    _is_transpilable, _code_has_blockers, _has_code_pattern_blocker,
    _has_name_blocker, _ALL_BLOCKERS, _FRAMEWORK_MARKERS,
    _UNTRANSLATABLE, _PY_MODULE_MARKERS,
)
from Analysis.transpiler import transpile_function_code

# ── Configuration ─────────────────────────────────────────────────────

BASE_DIR = Path(r"C:\Users\Yo930\Desktop\_Python")

# Only skip third-party / environment dirs (not our code)
THIRD_PARTY = {".venv", "venv", "env", "node_modules", "__pycache__",
               ".git", "site-packages", ".pytest_cache", "egg-info",
               "dist", "build", ".mypy_cache", "target", ".tox",
               ".eggs", "*.egg-info"}

# Training ground output
TRAINING_DIR = XRAY_ROOT / "_training_ground"
BLOCKED_DIR  = TRAINING_DIR / "blocked"
TRANS_DIR    = TRAINING_DIR / "transpiled"


# ── Blocker Diagnosis ─────────────────────────────────────────────────

def diagnose_blockers(name: str, code: str) -> Dict[str, Any]:
    """Return a detailed diagnosis of WHY a function can't be transpiled.

    Returns dict with:
      - reason: short category
      - markers_hit: list of specific markers found in code
      - pattern_issues: list of pattern problems
      - suggestion: what would need to change to unblock it
    """
    result: Dict[str, Any] = {"reason": "", "markers_hit": [],
                               "pattern_issues": [], "suggestion": ""}

    # 1. Name blocker
    if _has_name_blocker(name):
        if name.startswith("test_"):
            result["reason"] = "test_function"
            result["suggestion"] = "Test functions are skipped by design"
        else:
            result["reason"] = "dunder_method"
            result["suggestion"] = f"Dunder method {name} — needs class transpilation"
        return result

    # 2. Code blockers — find WHICH markers hit
    markers_hit = [m for m in _ALL_BLOCKERS if m in code]
    if markers_hit:
        # Classify the markers
        fw = [m for m in markers_hit if m in _FRAMEWORK_MARKERS]
        ut = [m for m in markers_hit if m in _UNTRANSLATABLE]
        pm = [m for m in markers_hit if m in _PY_MODULE_MARKERS]

        result["markers_hit"] = markers_hit
        if fw:
            result["reason"] = "framework_api"
            result["suggestion"] = f"Uses GUI/web framework: {', '.join(fw)}"
        elif ut:
            result["reason"] = "untranslatable_construct"
            result["suggestion"] = f"Uses Python-only constructs: {', '.join(ut)}"
        elif pm:
            result["reason"] = "python_module"
            result["suggestion"] = f"Needs Rust crate equivalents for: {', '.join(pm)}"
        else:
            result["reason"] = "code_blocker_mixed"
            result["suggestion"] = f"Multiple blockers: {', '.join(markers_hit[:5])}"
        return result

    # 3. Pattern blockers
    if code:
        str_chars = sum(len(m.group()) for m in _re.finditer(r'["\'].*?["\']', code))
        mostly_strings = len(code) > 50 and str_chars / len(code) > 0.7
        too_long = code.count("\n") > 500
        too_many_external = len(_re.findall(r'\b\w+\.\w+\(', code)) > 20

        if mostly_strings:
            result["reason"] = "mostly_strings"
            pct = round(100 * str_chars / len(code))
            result["pattern_issues"].append(f"{pct}% string literals")
            result["suggestion"] = "Function is mostly string data, not logic"
        elif too_long:
            result["reason"] = "too_long"
            lines = code.count("\n")
            result["pattern_issues"].append(f"{lines} lines (limit 500)")
            result["suggestion"] = "Split into smaller functions"
        elif too_many_external:
            ext_count = len(_re.findall(r'\b\w+\.\w+\(', code))
            result["reason"] = "too_many_external_calls"
            result["pattern_issues"].append(f"{ext_count} external method calls (limit 20)")
            result["suggestion"] = "Heavy external API usage — needs crate mappings"

        if result["reason"]:
            return result

    # 4. Too many unresolvable calls
    if code:
        unresolvable = len(_re.findall(r'\b[a-z_]\w+\(', code))
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

        # Count .py files (excluding third-party)
        py_files = [f for f in entry.rglob("*.py")
                    if not _is_third_party(str(f))]
        if not py_files:
            continue

        # For "Projects" folder, scan each sub-project individually
        if entry.name == "Projects":
            for sp in sorted(entry.iterdir()):
                if not sp.is_dir() or sp.name in THIRD_PARTY or sp.name.startswith("."):
                    continue
                sp_py = [f for f in sp.rglob("*.py")
                         if not _is_third_party(str(f))]
                if sp_py:
                    projects.append(sp)
        else:
            projects.append(entry)

    return projects


# ── Project Scanner ───────────────────────────────────────────────────

def scan_project(project_path: Path) -> Dict[str, Any]:
    """Scan a single project, classify every function, collect training data."""
    t0 = time.time()
    exclude = list(THIRD_PARTY)

    try:
        functions, classes, errors = scan_codebase(project_path, exclude=exclude)
    except Exception as e:
        return {"name": project_path.name, "error": str(e),
                "blocked_functions": [], "transpiled_functions": []}

    if not functions:
        return {
            "name": project_path.name,
            "path": str(project_path),
            "total_functions": 0, "total_classes": len(classes),
            "transpilable": 0, "transpilable_pct": 0.0,
            "blocker_breakdown": {}, "blocker_marker_freq": {},
            "top_candidates": [],
            "blocked_functions": [], "transpiled_functions": [],
            "time_s": round(time.time() - t0, 2),
        }

    # Score with RustAdvisor
    advisor = RustAdvisor()
    candidates = advisor.score(functions)

    # ── Classify every function ──────────────────────────────────────
    transpilable_count = 0
    blocker_counts: Dict[str, int] = Counter()
    marker_freq: Dict[str, int] = Counter()

    blocked_functions: List[Dict[str, Any]] = []
    transpiled_functions: List[Dict[str, Any]] = []

    for func in functions:
        code = getattr(func, "code", "") or ""
        name = getattr(func, "name", "") or ""
        file_path = getattr(func, "file", "") or ""

        if _is_transpilable(func):
            transpilable_count += 1
            # Try actual transpilation
            if code.strip() and len(code) < 5000:
                try:
                    rust = transpile_function_code(code)
                    todo_count = rust.count("todo!()")
                    transpiled_functions.append({
                        "name": name,
                        "file": str(file_path),
                        "project": project_path.name,
                        "python_code": code,
                        "rust_code": rust,
                        "python_lines": code.count("\n") + 1,
                        "rust_lines": rust.count("\n") + 1,
                        "todo_count": todo_count,
                        "clean": todo_count == 0,
                    })
                except Exception as ex:
                    transpiled_functions.append({
                        "name": name,
                        "file": str(file_path),
                        "project": project_path.name,
                        "python_code": code,
                        "rust_code": f"// TRANSPILE ERROR: {ex}",
                        "python_lines": code.count("\n") + 1,
                        "rust_lines": 0,
                        "todo_count": 0,
                        "clean": False,
                        "error": str(ex),
                    })
        else:
            # Diagnose WHY it's blocked
            diag = diagnose_blockers(name, code)
            blocker_counts[diag["reason"]] += 1
            for m in diag.get("markers_hit", []):
                marker_freq[m] += 1

            blocked_functions.append({
                "name": name,
                "file": str(file_path),
                "project": project_path.name,
                "python_code": code[:3000],  # cap at 3k chars
                "lines": code.count("\n") + 1 if code else 0,
                "reason": diag["reason"],
                "markers_hit": diag["markers_hit"],
                "pattern_issues": diag["pattern_issues"],
                "suggestion": diag["suggestion"],
            })

    # Top 5 candidates by score
    top = candidates[:5]
    top_info = [{
        "name": c.func.name, "score": round(c.score, 1),
        "is_pure": c.is_pure, "complexity": c.func.complexity,
    } for c in top]

    total = len(functions)
    return {
        "name": project_path.name,
        "path": str(project_path),
        "total_functions": total,
        "total_classes": len(classes),
        "transpilable": transpilable_count,
        "transpilable_pct": round(100 * transpilable_count / total, 1),
        "blocker_breakdown": dict(blocker_counts.most_common()),
        "blocker_marker_freq": dict(marker_freq.most_common(20)),
        "top_candidates": top_info,
        "blocked_functions": blocked_functions,
        "transpiled_functions": transpiled_functions,
        "time_s": round(time.time() - t0, 2),
    }


# ── Training Ground Output ───────────────────────────────────────────

def save_training_ground(all_results: List[Dict[str, Any]]) -> Dict[str, int]:
    """Save blocked functions as training data and transpiled pairs as validation.

    Structure:
      _training_ground/
        blocked/
          by_reason/
            framework_api.jsonl      — one JSON per line, each is a blocked function
            python_module.jsonl
            untranslatable_construct.jsonl
            ...
          by_marker/
            import_.jsonl            — functions blocked by "import "
            logging_.jsonl           — functions blocked by "logging."
            ...
          all_blocked.jsonl          — every blocked function in one file
        transpiled/
          pairs.jsonl                — {python_code, rust_code, name, ...}
          summary.json               — stats
    """
    BLOCKED_DIR.mkdir(parents=True, exist_ok=True)
    (BLOCKED_DIR / "by_reason").mkdir(exist_ok=True)
    (BLOCKED_DIR / "by_marker").mkdir(exist_ok=True)
    TRANS_DIR.mkdir(parents=True, exist_ok=True)

    # Collect all blocked and transpiled across all projects
    all_blocked: List[Dict] = []
    all_transpiled: List[Dict] = []
    for r in all_results:
        all_blocked.extend(r.get("blocked_functions", []))
        all_transpiled.extend(r.get("transpiled_functions", []))

    stats = {
        "total_blocked": len(all_blocked),
        "total_transpiled": len(all_transpiled),
    }

    # ── Write all_blocked.jsonl ──────────────────────────────────────
    with open(BLOCKED_DIR / "all_blocked.jsonl", "w", encoding="utf-8") as f:
        for item in all_blocked:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    # ── Group by reason ──────────────────────────────────────────────
    by_reason: Dict[str, List[Dict]] = {}
    for item in all_blocked:
        reason = item.get("reason", "unknown")
        by_reason.setdefault(reason, []).append(item)

    reason_counts = {}
    for reason, items in sorted(by_reason.items()):
        safe_name = reason.replace(" ", "_").replace("/", "_")
        path = BLOCKED_DIR / "by_reason" / f"{safe_name}.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            for item in items:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        reason_counts[reason] = len(items)

    stats["by_reason"] = reason_counts

    # ── Group by marker ──────────────────────────────────────────────
    by_marker: Dict[str, List[Dict]] = {}
    for item in all_blocked:
        for marker in item.get("markers_hit", []):
            by_marker.setdefault(marker, []).append(item)

    marker_counts = {}
    for marker, items in sorted(by_marker.items(), key=lambda x: -len(x[1])):
        safe_name = (marker.strip().replace(".", "_").replace("(", "")
                     .replace(")", "").replace(" ", "_").replace("*", "star")
                     .replace("{", "brace").replace("}", ""))
        if not safe_name:
            safe_name = "empty"
        path = BLOCKED_DIR / "by_marker" / f"{safe_name}.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            for item in items:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        marker_counts[marker] = len(items)

    stats["by_marker"] = marker_counts

    # ── Write transpiled pairs ───────────────────────────────────────
    clean_count = 0
    with open(TRANS_DIR / "pairs.jsonl", "w", encoding="utf-8") as f:
        for item in all_transpiled:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
            if item.get("clean"):
                clean_count += 1

    stats["transpiled_clean"] = clean_count
    stats["transpiled_with_todos"] = len(all_transpiled) - clean_count

    # ── Write summary ────────────────────────────────────────────────
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

    print(f"\n{'_'*66}")
    print(f"  Project: {name}")
    print(f"  Path:    {result.get('path', '?')}")
    print(f"{'_'*66}")
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
        print(f"\n  Most frequent blocking markers:")
        for marker, count in top_markers:
            print(f"    {repr(marker):25s}: {count:4d} functions")

    # Top candidates
    top = result.get("top_candidates", [])
    if top:
        print(f"\n  Top Rust candidates:")
        for c in top:
            pure = "PURE" if c["is_pure"] else "    "
            print(f"    [{pure}] {c['name']:30s} score={c['score']:6.1f}  cx={c['complexity']}")


def main():
    print("=" * 66)
    print("  X-RAY Rust Transpiler -- Full Audit (ALL projects)")
    print(f"  Base: {BASE_DIR}")
    print(f"  Training output: {TRAINING_DIR}")
    print("=" * 66)

    # Discover projects
    print("\n  Discovering projects (including old/archive code)...")
    projects = discover_projects(BASE_DIR)
    print(f"  Found {len(projects)} scannable projects:")
    for p in projects:
        rel = p.relative_to(BASE_DIR)
        print(f"    - {rel}")

    all_results = []
    totals = {"functions": 0, "transpilable": 0, "classes": 0,
              "blocked": 0, "transpiled_clean": 0}
    t_start = time.time()

    for i, proj in enumerate(projects, 1):
        print(f"\n  [{i}/{len(projects)}] Scanning {proj.name}...")
        result = scan_project(proj)
        all_results.append(result)
        print_project_result(result)

        if "error" not in result:
            totals["functions"] += result["total_functions"]
            totals["transpilable"] += result["transpilable"]
            totals["classes"] += result.get("total_classes", 0)
            totals["blocked"] += len(result.get("blocked_functions", []))

    # ── Save training ground ─────────────────────────────────────────
    print(f"\n  Saving training ground to {TRAINING_DIR}...")
    tg_stats = save_training_ground(all_results)
    totals["transpiled_clean"] = tg_stats.get("transpiled_clean", 0)

    # ── Grand total ──────────────────────────────────────────────────
    elapsed = time.time() - t_start
    grand_pct = (round(100 * totals["transpilable"] / totals["functions"], 1)
                 if totals["functions"] else 0)

    print(f"\n{'='*66}")
    print(f"  GRAND TOTAL ACROSS ALL PROJECTS")
    print(f"{'='*66}")
    print(f"  Projects scanned:     {len(projects)}")
    print(f"  Total functions:      {totals['functions']:,}")
    print(f"  Total classes:        {totals['classes']:,}")
    print(f"  Transpilable:         {totals['transpilable']:,} / {totals['functions']:,}  ({grand_pct}%)")
    print(f"  Clean translations:   {totals['transpiled_clean']:,} (no todo!())")
    print(f"  Blocked (training):   {totals['blocked']:,}")
    print(f"  Total time:           {elapsed:.1f}s")
    print(f"{'='*66}")

    # Blocker reason summary across ALL projects
    global_reasons: Counter = Counter()
    global_markers: Counter = Counter()
    for r in all_results:
        for reason, cnt in r.get("blocker_breakdown", {}).items():
            global_reasons[reason] += cnt
        for marker, cnt in r.get("blocker_marker_freq", {}).items():
            global_markers[marker] += cnt

    if global_reasons:
        print(f"\n  GLOBAL BLOCKER REASONS:")
        for reason, cnt in global_reasons.most_common():
            print(f"    {reason:35s}: {cnt:5d}")

    if global_markers:
        print(f"\n  GLOBAL TOP 15 BLOCKING MARKERS (training priorities):")
        for marker, cnt in global_markers.most_common(15):
            print(f"    {repr(marker):25s}: {cnt:5d} functions")

    # ── Training ground summary ──────────────────────────────────────
    print(f"\n  TRAINING GROUND SAVED:")
    print(f"    {BLOCKED_DIR / 'all_blocked.jsonl'}")
    print(f"      -> {tg_stats['total_blocked']:,} blocked functions with full diagnosis")
    print(f"    {BLOCKED_DIR / 'by_reason/'}")
    for reason, cnt in sorted(tg_stats.get("by_reason", {}).items(), key=lambda x: -x[1]):
        print(f"      {reason}.jsonl ({cnt:,} functions)")
    print(f"    {TRANS_DIR / 'pairs.jsonl'}")
    print(f"      -> {tg_stats['total_transpiled']:,} Python->Rust pairs")
    print(f"      -> {tg_stats.get('transpiled_clean', 0):,} clean (no todo!())")

    # Save JSON report (without the bulky code — that's in the training ground)
    report_path = XRAY_ROOT / "rustify_all_projects.json"
    slim_results = []
    for r in all_results:
        slim = {k: v for k, v in r.items()
                if k not in ("blocked_functions", "transpiled_functions")}
        slim["blocked_count"] = len(r.get("blocked_functions", []))
        slim["transpiled_count"] = len(r.get("transpiled_functions", []))
        slim_results.append(slim)

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({
            "projects": slim_results,
            "totals": totals, "grand_pct": grand_pct,
            "global_blocker_reasons": dict(global_reasons.most_common()),
            "global_blocker_markers": dict(global_markers.most_common(30)),
            "training_ground": str(TRAINING_DIR),
            "elapsed_s": round(elapsed, 2),
        }, f, indent=2, ensure_ascii=False)
    print(f"\n  Report: {report_path}")


if __name__ == "__main__":
    main()
