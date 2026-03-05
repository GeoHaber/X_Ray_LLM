"""
Tests for Analysis.rust_advisor — Rust candidate scoring and verification.
"""

from __future__ import annotations

import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Set

from Analysis.rust_advisor import (
    RustAdvisor,
    RustCandidate,
    _detect_purity,
    _count_external_deps,
)
from tests.conftest import make_func


def _rf(name="my_func", code="def my_func(a, b):\n    return a + b\n", **kw):
    """Rust advisor tests: make_func with defaults for purity/scoring."""
    kw.setdefault("parameters", ["a", "b"])
    kw.setdefault("return_type", "int")
    kw.setdefault("docstring", "Test function.")
    kw.setdefault("complexity", 1)
    kw.setdefault("size_lines", 10)
    return make_func(name=name, code=code, **kw)


@dataclass
class _FakeTraceProfile:
    """Minimal trace profile stand-in for tests."""

    func_name: str = "my_func"
    call_count: int = 500
    avg_time_us: float = 2000.0
    observed_arg_types: Dict[str, Set[str]] = field(default_factory=dict)
    samples: list = field(default_factory=list)


# ── Purity detection ────────────────────────────────────────────────────────


class TestPurityDetection:
    """Tests for the _detect_purity AST heuristic."""

    def test_pure_function(self):
        """Simple arithmetic function is detected as pure."""
        func = _rf(code="def f(a, b):\n    return a + b\n")
        assert _detect_purity(func) is True

    def test_impure_print(self):
        """Function calling print is impure."""
        func = _rf(code="def f(x):\n    print(x)\n    return x\n")
        assert _detect_purity(func) is False

    def test_impure_file_write(self):
        """Function calling open is impure."""
        func = _rf(code="def f():\n    f = open('a.txt')\n    return f\n")
        assert _detect_purity(func) is False

    def test_impure_global(self):
        """Function using global statement is impure."""
        func = _rf(code="def f():\n    global x\n    x = 1\n")
        assert _detect_purity(func) is False

    def test_impure_list_append(self):
        """Function calling list.append is impure."""
        func = _rf(code="def f(lst):\n    lst.append(1)\n")
        assert _detect_purity(func) is False

    def test_pure_list_comprehension(self):
        """List comprehension is pure."""
        func = _rf(code="def f(x):\n    return [i*2 for i in x]\n")
        assert _detect_purity(func) is True

    def test_syntax_error_returns_false(self):
        """Unparseable code returns False."""
        func = _rf(code="def f( invalid syntax ::::")
        assert _detect_purity(func) is False


# ── External dep counting ───────────────────────────────────────────────────


class TestExternalDeps:
    """Tests for _count_external_deps."""

    def test_no_deps(self):
        """Function with no impure calls has 0 deps."""
        func = _rf(calls_to=["add", "multiply"])
        assert _count_external_deps(func) == 0

    def test_with_print(self):
        """Function calling print has 1 dep."""
        func = _rf(calls_to=["print", "add"])
        assert _count_external_deps(func) == 1

    def test_multiple_deps(self):
        """Multiple impure calls counted."""
        func = _rf(calls_to=["open", "write", "close"])
        assert _count_external_deps(func) == 3  # open, write, close all impure


# ── RustAdvisor scoring ─────────────────────────────────────────────────────


class TestRustAdvisorScoring:
    """Tests for the RustAdvisor.score method."""

    def test_score_returns_sorted(self):
        """Candidates are sorted by score descending."""
        advisor = RustAdvisor()
        funcs = [
            _rf(name="simple", complexity=1, size_lines=10),
            _rf(name="complex", complexity=20, size_lines=50),
        ]
        candidates = advisor.score(funcs)
        assert candidates[0].func.name == "complex"

    def test_pure_scores_higher(self):
        """Pure functions score higher than impure ones, all else equal."""
        advisor = RustAdvisor()
        pure = _rf(
            name="pure_fn",
            code="def pure_fn(a, b):\n    return a + b\n",
            complexity=5,
            size_lines=10,
        )
        impure = _rf(
            name="impure_fn",
            code="def impure_fn(a):\n    print(a)\n    return a\n",
            complexity=5,
            size_lines=10,
        )
        candidates = advisor.score([pure, impure])
        pure_cand = next(c for c in candidates if c.func.name == "pure_fn")
        impure_cand = next(c for c in candidates if c.func.name == "impure_fn")
        assert pure_cand.score > impure_cand.score

    def test_async_penalty(self):
        """Async functions get penalized."""
        advisor = RustAdvisor()
        sync_fn = _rf(name="sync_fn", complexity=5, size_lines=10)
        async_fn = _rf(name="async_fn", complexity=5, size_lines=10, is_async=True)
        candidates = advisor.score([sync_fn, async_fn])
        sync_c = next(c for c in candidates if c.func.name == "sync_fn")
        async_c = next(c for c in candidates if c.func.name == "async_fn")
        assert sync_c.score > async_c.score

    def test_min_lines_filter(self):
        """Functions below min_lines are excluded."""
        advisor = RustAdvisor()
        small = _rf(name="tiny", size_lines=3)
        big = _rf(name="big", size_lines=50)
        candidates = advisor.score([small, big], min_lines=5)
        assert len(candidates) == 1
        assert candidates[0].func.name == "big"

    def test_trace_data_boosts_score(self):
        """Runtime trace data adds to the score."""
        advisor = RustAdvisor()
        func = _rf(name="hot_fn", complexity=5, size_lines=20)
        trace = _FakeTraceProfile(
            func_name="hot_fn",
            call_count=1000,
            avg_time_us=5000,
        )
        without_trace = advisor.score([func])
        with_trace = advisor.score([func], traces=[trace])
        assert with_trace[0].score > without_trace[0].score

    def test_external_deps_penalty(self):
        """Functions with external deps score lower."""
        advisor = RustAdvisor()
        clean = _rf(
            name="clean",
            calls_to=[],
            complexity=5,
            size_lines=10,
        )
        dirty = _rf(
            name="dirty",
            calls_to=["open", "write", "read"],
            code="def dirty(x):\n    open(x)\n    return x\n",
            complexity=5,
            size_lines=10,
        )
        candidates = advisor.score([clean, dirty])
        clean_c = next(c for c in candidates if c.func.name == "clean")
        dirty_c = next(c for c in candidates if c.func.name == "dirty")
        assert clean_c.score > dirty_c.score

    def test_score_non_negative(self):
        """Score is always >= 0."""
        advisor = RustAdvisor()
        bad = _rf(
            name="terrible",
            code="def terrible(a):\n    print(a)\n    open('f')\n",
            calls_to=["print", "open", "write", "read", "connect"],
            parameters=["a", "b", "c", "d", "e", "f", "g"],
            is_async=True,
            complexity=1,
            size_lines=6,
        )
        candidates = advisor.score([bad])
        assert candidates[0].score >= 0


# ── RustCandidate serialisation ──────────────────────────────────────────────


class TestRustCandidateDict:
    """Tests for RustCandidate.to_dict serialisation."""

    def test_to_dict_keys(self):
        """to_dict contains all expected keys."""
        func = _rf()
        candidate = RustCandidate(
            func=func,
            score=15.5,
            is_pure=True,
            external_deps=0,
            reason="pure, complex(5)",
        )
        d = candidate.to_dict()
        assert d["function"] == "my_func"
        assert d["score"] == 15.5
        assert d["is_pure"] is True
        assert "reason" in d

    def test_to_dict_json_serialisable(self):
        """to_dict output can be JSON-encoded."""
        func = _rf()
        candidate = RustCandidate(
            func=func,
            score=10.0,
            is_pure=True,
            external_deps=0,
        )
        json.dumps(candidate.to_dict())  # must not raise


# ── Golden fixture generation ────────────────────────────────────────────────


class TestGoldenGeneration:
    """Tests for golden fixture generation and verification."""

    def test_generate_golden_no_samples(self, tmp_path):
        """Returns None when no samples available."""
        advisor = RustAdvisor()
        func = _rf()
        candidate = RustCandidate(
            func=func,
            score=10.0,
            is_pure=True,
            external_deps=0,
        )
        result = advisor.generate_golden(candidate, output_dir=str(tmp_path))
        assert result is None

    def test_generate_golden_with_trace(self, tmp_path):
        """Generates a golden file from tracer samples."""
        from Analysis.tracer import IOSample

        advisor = RustAdvisor()
        func = _rf(name="add_fn", code="def add_fn(a, b):\n    return a + b\n")
        candidate = RustCandidate(
            func=func,
            score=10.0,
            is_pure=True,
            external_deps=0,
        )

        # Build a fake trace with samples
        trace = _FakeTraceProfile(func_name="add_fn")
        trace.samples = [
            IOSample(
                args_repr=["1", "2"], kwargs_repr={}, output_repr="3", output_type="int"
            ),
            IOSample(
                args_repr=["10", "20"],
                kwargs_repr={},
                output_repr="30",
                output_type="int",
            ),
        ]

        path = advisor.generate_golden(candidate, trace=trace, output_dir=str(tmp_path))
        assert path is not None
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        assert data["function"] == "add_fn"
        assert len(data["cases"]) == 2

    def test_verify_golden_all_pass(self, tmp_path):
        """Verification passes when Rust fn matches golden."""
        # Create golden file manually
        golden = {
            "function": "add",
            "file": "test.py",
            "signature": "add(a, b) -> int",
            "is_pure": True,
            "observed_types": {},
            "cases": [
                {
                    "args": ["1", "2"],
                    "kwargs": {},
                    "expected_output": "3",
                    "expected_type": "int",
                    "error": None,
                },
                {
                    "args": ["10", "20"],
                    "kwargs": {},
                    "expected_output": "30",
                    "expected_type": "int",
                    "error": None,
                },
            ],
        }
        golden_path = tmp_path / "add_golden.json"
        golden_path.write_text(json.dumps(golden), encoding="utf-8")

        # "Rust" function (just Python for testing)
        def rust_add(a, b):
            return a + b

        result = RustAdvisor.verify_golden(rust_add, str(golden_path))
        assert result["passed"] == 2
        assert result["failed"] == 0
        assert result["errors"] == 0

    def test_verify_golden_detects_mismatch(self, tmp_path):
        """Verification detects when Rust fn gives wrong output."""
        golden = {
            "function": "double",
            "file": "test.py",
            "signature": "double(x) -> int",
            "is_pure": True,
            "observed_types": {},
            "cases": [
                {
                    "args": ["5"],
                    "kwargs": {},
                    "expected_output": "10",
                    "expected_type": "int",
                    "error": None,
                },
            ],
        }
        golden_path = tmp_path / "double_golden.json"
        golden_path.write_text(json.dumps(golden), encoding="utf-8")

        def wrong_double(x):
            return x * 3  # Wrong!

        result = RustAdvisor.verify_golden(wrong_double, str(golden_path))
        assert result["failed"] == 1


# ── print_candidates (smoke test) ───────────────────────────────────────────


class TestPrintCandidates:
    """Smoke test for RustAdvisor.print_candidates output."""

    def test_prints_without_error(self, capsys):
        """print_candidates runs without raising."""
        func = _rf(name="scored_fn", complexity=10, size_lines=25)
        candidate = RustCandidate(
            func=func,
            score=20.0,
            is_pure=True,
            external_deps=0,
            reason="pure, complex(10)",
        )
        RustAdvisor.print_candidates([candidate])
        captured = capsys.readouterr()
        assert "scored_fn" in captured.out
        assert "RUST CANDIDATE" in captured.out

    def test_prints_empty_list(self, capsys):
        """print_candidates handles empty list."""
        RustAdvisor.print_candidates([])
        captured = capsys.readouterr()
        assert "RUST CANDIDATE" in captured.out
