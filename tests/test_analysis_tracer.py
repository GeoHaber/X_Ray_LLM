"""
Tests for Analysis.tracer — FunctionTracer runtime I/O capture.
"""
from __future__ import annotations

import json
import pytest

from Analysis.tracer import (
    FunctionTracer,
    TraceProfile,
    _type_tag,
    _safe_repr,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _add(a: int, b: int) -> int:
    """Simple pure function for testing."""
    return a + b


def _greet(name: str, greeting: str = "Hello") -> str:
    """Function with a keyword arg."""
    return f"{greeting}, {name}!"


def _boom(x: int) -> int:
    """Function that raises on negative input."""
    if x < 0:
        raise ValueError("no negatives")
    return x * 2


def _noop() -> None:
    """No-arg, no-return function."""
    pass


# ── _type_tag / _safe_repr tests ────────────────────────────────────────────

class TestTypeTagAndRepr:
    """Tests for the _type_tag and _safe_repr helper functions."""

    def test_type_tag_int(self):
        assert _type_tag(42) == "int"

    def test_type_tag_str(self):
        assert _type_tag("hello") == "str"

    def test_type_tag_none(self):
        assert _type_tag(None) == "None"

    def test_type_tag_list(self):
        assert _type_tag([1, 2, 3]) == "list"

    def test_type_tag_dict(self):
        assert _type_tag({"a": 1}) == "dict"

    def test_safe_repr_normal(self):
        assert _safe_repr(42) == "42"

    def test_safe_repr_string(self):
        assert _safe_repr("hi") == "'hi'"

    def test_safe_repr_truncation(self):
        long_str = "x" * 300
        result = _safe_repr(long_str, limit=50)
        assert len(result) == 51  # 50 chars + "…"
        assert result.endswith("…")


# ── FunctionTracer.wrap ─────────────────────────────────────────────────────

class TestTracerWrap:
    """Tests for FunctionTracer.wrap preserving behaviour and capturing I/O."""

    def test_wrap_preserves_return(self):
        """Wrapped function returns the same value."""
        tracer = FunctionTracer()
        wrapped = tracer.wrap(_add)
        assert wrapped(3, 4) == 7

    def test_wrap_preserves_name(self):
        """Wrapped function preserves __name__."""
        tracer = FunctionTracer()
        wrapped = tracer.wrap(_add)
        assert wrapped.__name__ == "_add"

    def test_wrap_captures_call_count(self):
        """Call count increments on each call."""
        tracer = FunctionTracer()
        wrapped = tracer.wrap(_add)
        wrapped(1, 2)
        wrapped(3, 4)
        wrapped(5, 6)
        prof = tracer.profiles()[0]
        assert prof.call_count == 3

    def test_wrap_captures_arg_types(self):
        """Observed arg types are recorded."""
        tracer = FunctionTracer()
        wrapped = tracer.wrap(_add)
        wrapped(1, 2)
        prof = tracer.profiles()[0]
        assert "int" in prof.observed_arg_types.get("a", set())
        assert "int" in prof.observed_arg_types.get("b", set())

    def test_wrap_captures_return_types(self):
        """Observed return types are recorded."""
        tracer = FunctionTracer()
        wrapped = tracer.wrap(_add)
        wrapped(1, 2)
        prof = tracer.profiles()[0]
        assert "int" in prof.observed_return_types

    def test_wrap_captures_kwargs(self):
        """Kwargs are captured correctly."""
        tracer = FunctionTracer()
        wrapped = tracer.wrap(_greet)
        wrapped("World", greeting="Hi")
        prof = tracer.profiles()[0]
        assert "str" in prof.observed_arg_types.get("greeting", set())
        assert prof.samples[0].kwargs_repr.get("greeting") == "'Hi'"

    def test_wrap_captures_samples(self):
        """I/O samples are recorded."""
        tracer = FunctionTracer()
        wrapped = tracer.wrap(_add)
        wrapped(10, 20)
        prof = tracer.profiles()[0]
        assert len(prof.samples) == 1
        sample = prof.samples[0]
        assert sample.args_repr == ["10", "20"]
        assert sample.output_repr == "30"
        assert sample.output_type == "int"
        assert sample.error is None

    def test_wrap_records_timing(self):
        """Elapsed time is non-negative."""
        tracer = FunctionTracer()
        wrapped = tracer.wrap(_add)
        wrapped(1, 2)
        prof = tracer.profiles()[0]
        assert prof.total_time_us >= 0
        assert prof.samples[0].elapsed_us >= 0


# ── Exception tracking ──────────────────────────────────────────────────────

class TestTracerExceptions:
    """Tests for exception tracking in FunctionTracer."""

    def test_exception_propagated(self):
        """Exceptions still propagate normally."""
        tracer = FunctionTracer()
        wrapped = tracer.wrap(_boom)
        with pytest.raises(ValueError, match="no negatives"):
            wrapped(-1)

    def test_exception_recorded(self):
        """Exception type is recorded in the profile."""
        tracer = FunctionTracer()
        wrapped = tracer.wrap(_boom)
        try:
            wrapped(-1)
        except ValueError:
            pass
        prof = tracer.profiles()[0]
        assert "ValueError" in prof.exceptions_seen

    def test_exception_marks_impure(self):
        """Functions that throw are marked as impure."""
        tracer = FunctionTracer()
        wrapped = tracer.wrap(_boom)
        try:
            wrapped(-1)
        except ValueError:
            pass
        prof = tracer.profiles()[0]
        assert prof.is_pure is False

    def test_exception_sample_has_error(self):
        """Error sample has the error field set."""
        tracer = FunctionTracer()
        wrapped = tracer.wrap(_boom)
        try:
            wrapped(-1)
        except ValueError:
            pass
        prof = tracer.profiles()[0]
        assert prof.samples[0].error == "ValueError"

    def test_mixed_success_and_error(self):
        """Profile tracks both success and error calls."""
        tracer = FunctionTracer()
        wrapped = tracer.wrap(_boom)
        wrapped(5)
        try:
            wrapped(-1)
        except ValueError:
            pass
        prof = tracer.profiles()[0]
        assert prof.call_count == 2
        assert "int" in prof.observed_return_types
        assert "ValueError" in prof.exceptions_seen


# ── Sample cap ───────────────────────────────────────────────────────────────

class TestTracerSampleCap:
    """Tests for the MAX_SAMPLES cap on recorded I/O pairs."""

    def test_samples_capped(self):
        """Samples are capped at max_samples."""
        tracer = FunctionTracer(max_samples=5)
        wrapped = tracer.wrap(_add)
        for i in range(20):
            wrapped(i, i)
        prof = tracer.profiles()[0]
        assert len(prof.samples) == 5
        assert prof.call_count == 20  # still counts all


# ── profile_for ──────────────────────────────────────────────────────────────

class TestProfileFor:
    """Tests for the profile_for lookup method."""

    def test_lookup_by_name(self):
        """Can find a profile by function name."""
        tracer = FunctionTracer()
        tracer.wrap(_add)(1, 2)
        assert tracer.profile_for("_add") is not None

    def test_lookup_missing(self):
        """Returns None for unknown functions."""
        tracer = FunctionTracer()
        assert tracer.profile_for("nonexistent") is None


# ── Noop function ────────────────────────────────────────────────────────────

class TestTracerNoop:
    """Tests for tracing a no-arg, no-return function."""

    def test_noop_returns_none(self):
        """Wrapped noop returns None."""
        tracer = FunctionTracer()
        wrapped = tracer.wrap(_noop)
        assert wrapped() is None

    def test_noop_captures_none_type(self):
        """Return type None is captured."""
        tracer = FunctionTracer()
        wrapped = tracer.wrap(_noop)
        wrapped()
        prof = tracer.profiles()[0]
        assert "None" in prof.observed_return_types


# ── Serialisation roundtrip ─────────────────────────────────────────────────

class TestTracerSerialisation:
    """Tests for save/load JSON roundtrip."""

    def test_save_load_roundtrip(self, tmp_path):
        """Profiles survive a save→load roundtrip."""
        tracer = FunctionTracer()
        wrapped = tracer.wrap(_add)
        wrapped(1, 2)
        wrapped(3, 4)

        path = tmp_path / "trace.json"
        tracer.save(path)

        loaded = tracer.load(path)
        assert len(loaded) == 1
        prof = loaded[0]
        assert prof.func_name == "_add"
        assert prof.call_count == 2
        assert "int" in prof.observed_return_types
        assert len(prof.samples) == 2

    def test_save_creates_valid_json(self, tmp_path):
        """Saved file is valid JSON."""
        tracer = FunctionTracer()
        tracer.wrap(_add)(1, 2)
        path = tmp_path / "trace.json"
        tracer.save(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(data, list)
        assert data[0]["func_name"] == "_add"


# ── TraceProfile properties ─────────────────────────────────────────────────

class TestTraceProfileProperties:
    """Tests for derived properties on TraceProfile."""

    def test_avg_time_us(self):
        """Average time is computed correctly."""
        tp = TraceProfile(
            func_name="f", module="m", qualname="m.f",
            param_names=[], call_count=10, total_time_us=1000,
        )
        assert tp.avg_time_us == 100.0

    def test_avg_time_us_zero_calls(self):
        """avg_time_us handles zero calls without division error."""
        tp = TraceProfile(
            func_name="f", module="m", qualname="m.f",
            param_names=[], call_count=0, total_time_us=0,
        )
        assert tp.avg_time_us == 0.0

    def test_dominant_return_type(self):
        """dominant_return_type returns the first seen type."""
        tp = TraceProfile(
            func_name="f", module="m", qualname="m.f",
            param_names=[], observed_return_types={"int", "str"},
        )
        assert tp.dominant_return_type in ("int", "str")

    def test_dominant_return_type_empty(self):
        """dominant_return_type returns 'unknown' when no types seen."""
        tp = TraceProfile(
            func_name="f", module="m", qualname="m.f",
            param_names=[],
        )
        assert tp.dominant_return_type == "unknown"

    def test_to_dict(self):
        """to_dict produces a JSON-serialisable dict."""
        tp = TraceProfile(
            func_name="f", module="m", qualname="m.f",
            param_names=["x"], call_count=1, total_time_us=500,
            observed_return_types={"int"},
        )
        d = tp.to_dict()
        assert d["func_name"] == "f"
        assert d["call_count"] == 1
        json.dumps(d)  # must not raise


# ── Reset ────────────────────────────────────────────────────────────────────

class TestTracerReset:
    """Tests for FunctionTracer.reset clearing all data."""

    def test_reset_clears_profiles(self):
        """Reset removes all collected profiles."""
        tracer = FunctionTracer()
        tracer.wrap(_add)(1, 2)
        assert len(tracer.profiles()) == 1
        tracer.reset()
        assert len(tracer.profiles()) == 0
