#!/usr/bin/env python3
"""
calibrate_fixtures.py — Use the actual X-Ray detectors to score every
fixture pair, exposing exactly where they land relative to thresholds.

Then generates tough boundary-case fixtures that sit RIGHT AT the detection
edges, creating the hardest possible tests.

Usage:
    python tests/rust_harness/calibrate_fixtures.py
    python tests/rust_harness/calibrate_fixtures.py --verbose
    python tests/rust_harness/calibrate_fixtures.py --generate-boundary
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from x_ray_claude import (  # noqa: E402
    DuplicateFinder,
    FunctionRecord,
    _extract_functions_from_file,
    callgraph_overlap,
    code_similarity,
    cosine_similarity,
    name_similarity,
    semantic_similarity,
    signature_similarity,
    tokenize,
    _term_freq,
)

FIXTURES = Path(__file__).parent / "fixtures"

# The thresholds from the detector
NEAR_DUP_THRESHOLD = 0.70
SEMANTIC_THRESHOLD = 0.50
TOKEN_PREFILTER = 0.25
SIZE_RATIO_MIN = 0.35
SEMANTIC_MIN_LINES = 8


def load_all_functions() -> dict[str, list[FunctionRecord]]:
    """Load functions from every fixture file, keyed by filename."""
    result: dict[str, list[FunctionRecord]] = {}
    for py_file in sorted([*FIXTURES.glob("*.py"), *FIXTURES.glob("*.pysrc")]):
        funcs, _, err = _extract_functions_from_file(py_file, FIXTURES)
        if err:
            print(f"  WARN: {py_file.name}: {err}")
        result[py_file.name] = funcs
    return result


def _compute_similarity_channels(f1: FunctionRecord, f2: FunctionRecord) -> dict:
    """Compute all similarity metrics between two functions."""
    text1 = " ".join(
        [
            f1.name,
            f1.docstring or "",
            " ".join(f1.parameters),
            f1.return_type or "",
            " ".join(f1.calls_to),
            f1.code or "",
        ]
    )
    text2 = " ".join(
        [
            f2.name,
            f2.docstring or "",
            " ".join(f2.parameters),
            f2.return_type or "",
            " ".join(f2.calls_to),
            f2.code or "",
        ]
    )
    tok1 = _term_freq(tokenize(text1))
    tok2 = _term_freq(tokenize(text2))

    da = _term_freq(tokenize(f1.docstring or ""))
    db = _term_freq(tokenize(f2.docstring or ""))

    return {
        "tok_cos": cosine_similarity(tok1, tok2),
        "code_sim": code_similarity(f1.code, f2.code),
        "ns": name_similarity(f1.name, f2.name),
        "ss": signature_similarity(f1, f2),
        "cg": callgraph_overlap(f1, f2),
        "ds": cosine_similarity(da, db) if (da and db) else 0.0,
        "sem": semantic_similarity(f1, f2),
    }


def score_pair_detailed(f1: FunctionRecord, f2: FunctionRecord) -> dict:
    """Run every similarity channel on a pair and return detailed scores."""
    ch = _compute_similarity_channels(f1, f2)

    ratio = (
        (min(f1.size_lines, f2.size_lines) / max(f1.size_lines, f2.size_lines))
        if max(f1.size_lines, f2.size_lines) > 0
        else 0
    )
    exact = f1.code_hash == f2.code_hash
    structural = (
        f1.structure_hash == f2.structure_hash and f1.structure_hash is not None
    )

    return {
        "f1": f"{f1.file_path}::{f1.name}",
        "f2": f"{f2.file_path}::{f2.name}",
        "f1_lines": f1.size_lines,
        "f2_lines": f2.size_lines,
        "size_ratio": round(ratio, 3),
        "exact_hash": exact,
        "structural_hash": structural,
        "token_cosine": round(ch["tok_cos"], 3),
        "code_similarity": round(ch["code_sim"], 3),
        "name_sim": round(ch["ns"], 3),
        "signature_sim": round(ch["ss"], 3),
        "callgraph_overlap": round(ch["cg"], 3),
        "docstring_sim": round(ch["ds"], 3),
        "semantic_composite": round(ch["sem"], 3),
        "detected_as": (
            "exact"
            if exact
            else "structural"
            if structural
            else "near"
            if ch["code_sim"] >= NEAR_DUP_THRESHOLD
            else "semantic"
            if ch["sem"] >= SEMANTIC_THRESHOLD
            else "NONE"
        ),
        "near_margin": round(ch["code_sim"] - NEAR_DUP_THRESHOLD, 3),
        "semantic_margin": round(ch["sem"] - SEMANTIC_THRESHOLD, 3),
    }


_MARGIN_BANDS = [
    (-0.15, "SAFE_MISS"),
    (-0.05, "NEAR_MISS"),
    (0.0, "BOUNDARY_MISS"),
    (0.05, "BOUNDARY_HIT"),
    (0.15, "NEAR_HIT"),
]


def classify_margin(margin: float) -> str:
    """Classify how close a score is to its threshold."""
    for threshold, label in _MARGIN_BANDS:
        if margin < threshold:
            return label
    return "SAFE_HIT"


def run_full_pipeline():
    """Run DuplicateFinder on all fixtures, show actual groups."""
    all_funcs = []
    by_file = load_all_functions()
    for name, funcs in by_file.items():
        all_funcs.extend(funcs)

    finder = DuplicateFinder()
    groups = finder.find(all_funcs, cross_file_only=True)

    print(f"\n  {'=' * 70}")
    print(
        f"    FULL PIPELINE RESULTS ({len(all_funcs)} functions → {len(groups)} groups)"
    )
    print(f"  {'=' * 70}\n")

    for g in groups:
        fnames = [f"{f['name']} ({f['file']})" for f in g.functions]
        print(
            f"    Group {g.group_id}: {g.similarity_type} (avg={g.avg_similarity:.3f})"
        )
        for fn in fnames:
            print(f"      - {fn}")
    return groups


# ── Calibration helpers (extracted from main) ───────────────────────────────

_INTENDED_PAIRS = [
    ("dup_exact_a.pysrc", "dup_exact_b.pysrc"),
    ("dup_near_a.pysrc", "dup_near_b.pysrc"),
    ("dup_structural_a.pysrc", "dup_structural_b.pysrc"),
    ("dup_semantic_a.pysrc", "dup_semantic_b.pysrc"),
]

_INTENDED_PAIR_KEYS = {tuple(sorted(p)) for p in _INTENDED_PAIRS}

_DET_STYLE = {
    "exact": "  [EXACT] ",
    "structural": " [STRUCT]",
    "near": "  [NEAR]  ",
    "semantic": " [SEMAN] ",
    "NONE": "  [----]  ",
}


def _print_inventory(by_file):
    """Print per-file function inventory."""
    for fname, funcs in by_file.items():
        print(f"  {fname}:")
        for f in funcs:
            params = ", ".join(f.parameters[:3])
            calls = ", ".join(f.calls_to[:4])
            print(
                f"    {f.name}({params})  [{f.size_lines}L, "
                f"calls={calls or 'none'}, hash={f.code_hash[:8]}]"
            )
        print()


def _score_file_pair(funcs_a, funcs_b, all_scores, verbose):
    """Score all function pairs between two files."""
    for fa in funcs_a:
        for fb in funcs_b:
            scores = score_pair_detailed(fa, fb)
            all_scores.append(scores)
            det = scores["detected_as"]
            print(f"    {fa.name:25s} <-> {fb.name:25s} => {_DET_STYLE[det]}")
            if not verbose and det != "NONE":
                continue
            print(
                f"      tok_cos={scores['token_cosine']:.3f}  "
                f"code_sim={scores['code_similarity']:.3f}  "
                f"sem={scores['semantic_composite']:.3f}"
            )
            print(
                f"      name={scores['name_sim']:.3f}  "
                f"sig={scores['signature_sim']:.3f}  "
                f"callgraph={scores['callgraph_overlap']:.3f}  "
                f"doc={scores['docstring_sim']:.3f}"
            )
            print(
                f"      near_margin={scores['near_margin']:+.3f} "
                f"({classify_margin(scores['near_margin'])})  "
                f"sem_margin={scores['semantic_margin']:+.3f} "
                f"({classify_margin(scores['semantic_margin'])})"
            )


def _score_pairs(by_file, verbose=False):
    """Score intended cross-file pairs and return all score dicts."""
    print(f"\n  {'=' * 70}")
    print("    CROSS-FILE PAIR SCORING")
    print(f"  {'=' * 70}\n")

    all_scores = []
    for file_a, file_b in _INTENDED_PAIRS:
        funcs_a = by_file.get(file_a, [])
        funcs_b = by_file.get(file_b, [])
        if not funcs_a or not funcs_b:
            print(f"  SKIP {file_a} <-> {file_b}: files not found")
            continue

        print(f"  --- {file_a} <-> {file_b} ---")
        _score_file_pair(funcs_a, funcs_b, all_scores, verbose)
        print()
    return all_scores


def _scan_false_positives(by_file):
    """Check that unintended cross-file pairs don't accidentally match."""
    print(f"\n  {'=' * 70}")
    print("    FALSE POSITIVE SCAN (unintended cross-file matches)")
    print(f"  {'=' * 70}\n")

    all_funcs_flat = [f for funcs in by_file.values() for f in funcs]
    fp_count = 0
    for i, fa in enumerate(all_funcs_flat):
        for fb in all_funcs_flat[i + 1 :]:
            if fa.file_path == fb.file_path:
                continue
            fa_file = (
                Path(fa.file_path).name
                if "/" not in fa.file_path
                else fa.file_path.split("/")[-1]
            )
            fb_file = (
                Path(fb.file_path).name
                if "/" not in fb.file_path
                else fb.file_path.split("/")[-1]
            )
            pair_key = tuple(sorted([fa_file, fb_file]))

            scores = score_pair_detailed(fa, fb)
            if scores["detected_as"] != "NONE" and pair_key not in _INTENDED_PAIR_KEYS:
                fp_count += 1
                print(
                    f"    [FALSE_POS] {fa.name} ({fa_file}) <-> "
                    f"{fb.name} ({fb_file})  => {scores['detected_as']} "
                    f"(sem={scores['semantic_composite']:.3f}, "
                    f"code={scores['code_similarity']:.3f})"
                )

    if fp_count == 0:
        print("    No false positives detected!")
    else:
        print(f"\n    {fp_count} false positive(s) found — fixtures need tuning!")


def _print_margins(all_scores):
    """Print margin analysis showing distance from detection thresholds."""
    print(f"\n  {'=' * 70}")
    print("    MARGIN ANALYSIS (distance from threshold)")
    print(f"  {'=' * 70}\n")

    boundary_cases = []
    for s in all_scores:
        near_class = classify_margin(s["near_margin"])
        sem_class = classify_margin(s["semantic_margin"])
        if "BOUNDARY" in near_class or "BOUNDARY" in sem_class:
            boundary_cases.append(s)
            print(
                f"    BOUNDARY: {s['f1'].split('::')[1]:20s} <-> "
                f"{s['f2'].split('::')[1]:20s}"
            )
            print(
                f"      near: {s['code_similarity']:.3f} (margin={s['near_margin']:+.3f})"
            )
            print(
                f"      sem:  {s['semantic_composite']:.3f} (margin={s['semantic_margin']:+.3f})"
            )

    if not boundary_cases:
        print("    No pairs at boundary thresholds (all clear or all missed)")


def _print_boundary_recommendations():
    """Print recommendations for boundary-case fixtures."""
    print(f"\n  {'=' * 70}")
    print("    BOUNDARY FIXTURE RECOMMENDATIONS")
    print(f"  {'=' * 70}\n")
    print("    The following fixture pairs should be added to stress-test")
    print("    the detection boundaries:\n")
    print("    1. NEAR-DUP BOUNDARY (code_sim ~0.68-0.72):")
    print("       - Two functions with same logic but different variable")
    print("         names, comments, and minor structural changes")
    print("       - One pair at 0.69 (should MISS)")
    print("       - One pair at 0.71 (should HIT)")
    print()
    print("    2. SEMANTIC BOUNDARY (composite ~0.48-0.52):")
    print("       - Two functions with similar names but different calls")
    print("       - One pair at 0.49 (should MISS)")
    print("       - One pair at 0.51 (should HIT)")
    print()
    print("    3. TOKEN PRE-FILTER BOUNDARY (tok_cos ~0.23-0.27):")
    print("       - Two functions that look different but share some vocab")
    print("       - One pair at 0.24 (filtered out, never checked)")
    print("       - One pair at 0.26 (passes filter, then Stage 2 runs)")
    print()
    print("    4. SIZE RATIO BOUNDARY (ratio ~0.33-0.37):")
    print("       - Two functions of very different sizes")
    print("       - One pair with ratio 0.34 (filtered out)")
    print("       - One pair with ratio 0.36 (passes filter)")


def main():
    """Calibrate test fixtures and report duplicate detection accuracy."""
    parser = argparse.ArgumentParser(description="Calibrate fixture scores")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument(
        "--generate-boundary",
        "-g",
        action="store_true",
        help="Print recommendations for boundary fixtures",
    )
    args = parser.parse_args()

    by_file = load_all_functions()
    print(
        f"\n  Loaded {sum(len(v) for v in by_file.values())} functions "
        f"from {len(by_file)} fixture files.\n"
    )

    _print_inventory(by_file)
    all_scores = _score_pairs(by_file, args.verbose)
    _scan_false_positives(by_file)
    _print_margins(all_scores)
    run_full_pipeline()

    if args.generate_boundary:
        _print_boundary_recommendations()


if __name__ == "__main__":
    main()
