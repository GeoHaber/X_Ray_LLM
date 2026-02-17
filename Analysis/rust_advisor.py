"""
Analysis/rust_advisor.py — Rust Candidate Scoring & Verification
=================================================================

Automatically ranks Python functions by their suitability for Rust
porting based on static AST metrics + optional runtime trace data.

Scoring formula
---------------
A higher score means "port this first":

    score = (
        call_count_weight                     # how often it runs
      + purity_bonus                          # no side effects → safe to port
      + complexity × complexity_weight        # complex → bigger speedup
      + size × size_weight                    # bigger → more opportunity
      - external_dep_penalty                  # I/O, network, etc. = hard to port
      - param_count_penalty                   # many params → fiddly FFI
    )

The advisor also generates **golden fixture files** from observed
I/O samples and can verify a Rust port against them.

Usage::

    advisor = RustAdvisor()
    candidates = advisor.score(functions)                     # static only
    candidates = advisor.score(functions, traces=profiles)    # + runtime
    advisor.generate_golden(candidates[0], output_dir="golden/")
    advisor.verify_golden(rust_fn, "golden/tokenize.json")
"""

from __future__ import annotations

import json
import ast
from ast import literal_eval
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from Core.types import FunctionRecord

try:
    from Analysis.tracer import TraceProfile
except ImportError:
    TraceProfile = None  # type: ignore[misc,assignment]


# ── Side-effect indicators (heuristic AST scan) ─────────────────────────────

_IMPURE_CALLS = frozenset({
    "print", "open", "write", "read", "input",
    "connect", "send", "recv", "request",
    "get", "post", "put", "delete", "patch",
    "execute", "commit", "rollback",
    "mkdir", "rmdir", "unlink", "remove", "rename",
    "subprocess", "system", "popen",
    "sleep", "time",
    "logging", "log", "warn", "error", "info", "debug",
    "random", "randint", "choice", "shuffle",
})

_IMPURE_ATTRS = frozenset({
    "append", "extend", "insert", "pop", "remove", "clear",
    "update", "setdefault",  # dict/set mutation
    "seek", "write", "close", "flush",  # I/O
})


def _detect_purity(func: FunctionRecord) -> bool:
    """Return True if the function appears pure (no side effects)."""
    try:
        tree = ast.parse(func.code)
    except SyntaxError:
        return False

    for node in ast.walk(tree):
        # Global/nonlocal assignments
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            return False
        # Calls to known impure functions
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in _IMPURE_CALLS:
                return False
            if isinstance(node.func, ast.Attribute) and node.func.attr in _IMPURE_ATTRS:
                return False
            if isinstance(node.func, ast.Attribute) and node.func.attr in _IMPURE_CALLS:
                return False
    return True


def _count_external_deps(func: FunctionRecord) -> int:
    """Count calls that look like external I/O or library dependencies."""
    count = 0
    for call in func.calls_to:
        if call in _IMPURE_CALLS or call in _IMPURE_ATTRS:
            count += 1
    return count


# ── Candidate dataclass ─────────────────────────────────────────────────────

@dataclass
class RustCandidate:
    """A scored function ready for Rustification ranking."""
    func: FunctionRecord
    score: float
    is_pure: bool
    external_deps: int
    call_count: int = 0           # from tracer (0 = unknown)
    avg_time_us: float = 0.0     # from tracer
    observed_types: Dict[str, List[str]] = field(default_factory=dict)
    reason: str = ""              # human-readable explanation

    def to_dict(self) -> Dict[str, Any]:
        """Serialise for JSON reports."""
        return {
            "function": self.func.name,
            "file": self.func.file_path,
            "line": self.func.line_start,
            "score": round(self.score, 1),
            "is_pure": self.is_pure,
            "complexity": self.func.complexity,
            "size_lines": self.func.size_lines,
            "external_deps": self.external_deps,
            "call_count": self.call_count,
            "avg_time_us": round(self.avg_time_us, 1),
            "observed_types": self.observed_types,
            "reason": self.reason,
        }


# ── Scoring weights ─────────────────────────────────────────────────────────

_WEIGHTS = {
    "purity_bonus":    15.0,
    "complexity":       1.0,
    "size":             0.1,
    "call_count":       0.5,   # per 100 calls
    "time_per_call":    0.01,  # per µs average
    "external_dep":    -8.0,   # per impure dep
    "param_penalty":   -0.5,   # per param above 3
    "async_penalty":  -20.0,   # async functions are hard to port
}


# ── RustAdvisor ──────────────────────────────────────────────────────────────

class RustAdvisor:
    """
    Scores and ranks functions for Rust porting.

    Combines static AST analysis with optional runtime trace data
    to produce a prioritised list of Rust candidates.
    """

    def __init__(self, weights: Optional[Dict[str, float]] = None):
        self.weights = {**_WEIGHTS, **(weights or {})}

    def score(self, functions: List[FunctionRecord],
              traces: Optional[List] = None,
              min_lines: int = 5) -> List[RustCandidate]:
        """Score and rank all functions. Returns sorted list (best first)."""
        trace_map: Dict[str, Any] = {}
        if traces:
            for t in traces:
                trace_map[t.func_name] = t

        candidates = []
        for func in functions:
            if func.size_lines < min_lines:
                continue
            candidate = self._score_one(func, trace_map.get(func.name))
            candidates.append(candidate)

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates

    def _score_one(self, func: FunctionRecord,
                   trace: Optional[Any] = None) -> RustCandidate:
        """Compute Rust-suitability score for a single function."""
        w = self.weights
        pure = _detect_purity(func)
        ext_deps = _count_external_deps(func)

        score = 0.0
        reasons = []

        # Purity bonus
        if pure:
            score += w["purity_bonus"]
            reasons.append("pure")
        else:
            reasons.append("impure")

        # Complexity reward
        score += func.complexity * w["complexity"]
        if func.complexity >= 10:
            reasons.append(f"complex({func.complexity})")

        # Size reward
        score += func.size_lines * w["size"]

        # External dependency penalty
        score += ext_deps * w["external_dep"]
        if ext_deps > 0:
            reasons.append(f"deps({ext_deps})")

        # Param penalty (above 3)
        excess_params = max(0, len(func.parameters) - 3)
        score += excess_params * w["param_penalty"]

        # Async penalty
        if func.is_async:
            score += w["async_penalty"]
            reasons.append("async")

        # Runtime trace bonuses
        call_count = 0
        avg_time_us = 0.0
        observed_types: Dict[str, List[str]] = {}
        if trace is not None:
            call_count = getattr(trace, "call_count", 0)
            avg_time_us = getattr(trace, "avg_time_us", 0.0)
            score += (call_count / 100) * w["call_count"]
            score += avg_time_us * w["time_per_call"]
            if call_count > 100:
                reasons.append(f"hot({call_count} calls)")
            if avg_time_us > 1000:
                reasons.append(f"slow({avg_time_us:.0f}µs)")
            # Merge observed types
            raw = getattr(trace, "observed_arg_types", {})
            observed_types = {k: sorted(v) for k, v in raw.items()}

        return RustCandidate(
            func=func,
            score=max(0, round(score, 1)),
            is_pure=pure,
            external_deps=ext_deps,
            call_count=call_count,
            avg_time_us=avg_time_us,
            observed_types=observed_types,
            reason=", ".join(reasons) if reasons else "baseline",
        )

    # ── Golden fixture generation ────────────────────────────────────────

    def generate_golden(self, candidate: RustCandidate,
                        trace: Optional[Any] = None,
                        output_dir: str = "golden") -> Optional[str]:
        """Generate a golden JSON fixture from trace samples.

        Returns the path to the written file, or None if no samples.
        """
        samples = []
        if trace is not None:
            for s in getattr(trace, "samples", []):
                samples.append({
                    "args": s.args_repr,
                    "kwargs": s.kwargs_repr,
                    "expected_output": s.output_repr,
                    "expected_type": s.output_type,
                    "error": s.error,
                })

        if not samples:
            return None

        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"{candidate.func.name}_golden.json"

        payload = {
            "function": candidate.func.name,
            "file": candidate.func.file_path,
            "signature": candidate.func.signature,
            "is_pure": candidate.is_pure,
            "observed_types": candidate.observed_types,
            "cases": samples,
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return str(path)

    # ── Golden verification ──────────────────────────────────────────────

    @staticmethod
    def verify_golden(rust_fn: Callable, golden_path: str) -> Dict[str, Any]:
        """Run a Rust function against a golden fixture and report results.

        Returns a dict with 'passed', 'failed', 'errors', and 'details'.
        """
        data = json.loads(Path(golden_path).read_text(encoding="utf-8"))
        cases = data.get("cases", [])

        passed = 0
        failed = 0
        errors = 0
        details: List[Dict[str, Any]] = []

        for i, case in enumerate(cases):
            if case.get("error"):
                # Skip error cases — we only verify happy-path parity
                continue
            try:
                # Reconstruct args from repr (best-effort via literal_eval)
                args = [literal_eval(a) for a in case["args"]]
                kwargs = {k: literal_eval(v) for k, v in case.get("kwargs", {}).items()}
                result = rust_fn(*args, **kwargs)
                expected = literal_eval(case["expected_output"])

                if result == expected:
                    passed += 1
                else:
                    failed += 1
                    details.append({
                        "case": i,
                        "status": "MISMATCH",
                        "expected": case["expected_output"],
                        "actual": repr(result),
                    })
            except Exception as exc:
                errors += 1
                details.append({
                    "case": i,
                    "status": "ERROR",
                    "error": str(exc),
                })

        return {
            "golden_file": golden_path,
            "total": len(cases),
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "details": details,
        }

    # ── Reporting ────────────────────────────────────────────────────────

    @staticmethod
    def print_candidates(candidates: List[RustCandidate],
                         top_n: int = 20) -> None:
        """Print a ranked table of Rust candidates."""
        print(f"\n{'='*72}")
        print("  RUST CANDIDATE RANKING")
        print(f"{'='*72}")
        print(f"  {'#':>3}  {'Score':>6}  {'Pure':>4}  {'CC':>3}  "
              f"{'Lines':>5}  {'Calls':>6}  Function")
        print(f"  {'─'*3}  {'─'*6}  {'─'*4}  {'─'*3}  "
              f"{'─'*5}  {'─'*6}  {'─'*40}")

        for i, c in enumerate(candidates[:top_n], 1):
            pure_icon = "Yes" if c.is_pure else " - "
            calls = str(c.call_count) if c.call_count else "  -"
            loc = f"{c.func.file_path}:{c.func.line_start}"
            print(f"  {i:>3}  {c.score:>6.1f}  {pure_icon:>4}  "
                  f"{c.func.complexity:>3}  {c.func.size_lines:>5}  "
                  f"{calls:>6}  {c.func.name}")
            print(f"  {'':>3}  {'':>6}  {'':>4}  {'':>3}  "
                  f"{'':>5}  {'':>6}  {loc}  ({c.reason})")

        total_pure = sum(1 for c in candidates if c.is_pure)
        print(f"\n  {len(candidates)} functions scored, "
              f"{total_pure} pure, "
              f"top score: {candidates[0].score:.1f}" if candidates else "")
        print(f"{'='*72}\n")
