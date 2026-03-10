"""
Analysis/tracer.py — Runtime Function Tracer for X-Ray Rustification
=====================================================================

Instruments Python functions to capture real input/output pairs
at runtime.  When the traced target runs (during tests, benchmarks,
or normal usage), the tracer records:

  - Observed argument types  (param → {int, str, …})
  - Observed return types
  - Concrete I/O sample pairs
  - Whether exceptions were raised
  - Call count

The trace data is later merged into the static FunctionRecord to
build a full FunctionProfile — the single source of truth used by
the Rustification pipeline.

Usage::

    tracer = FunctionTracer()

    # Wrap a function
    original_fn = my_module.tokenize
    my_module.tokenize = tracer.wrap(original_fn)

    # Run whatever exercises the function (tests, benchmarks, …)
    import subprocess
    subprocess.run(["python", "-m", "pytest", "tests/", "-q"])

    # Collect profiles
    profiles = tracer.profiles()
"""

from __future__ import annotations

import json
import functools
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set


# ── helpers ──────────────────────────────────────────────────────────────────


def _type_tag(value: Any) -> str:
    """Return a concise string tag for a value's type."""
    t = type(value).__name__
    if t == "NoneType":
        return "None"
    return t


def _safe_repr(value: Any, limit: int = 200) -> str:
    """Return a truncated repr that is safe to serialise."""
    try:
        r = repr(value)
        return r[:limit] + "…" if len(r) > limit else r
    except Exception:
        return "<unrepresentable>"


# ── data classes ─────────────────────────────────────────────────────────────


@dataclass
class IOSample:
    """One observed (inputs → output) sample from a traced call."""

    args_repr: List[str]
    kwargs_repr: Dict[str, str]
    output_repr: str
    output_type: str
    error: Optional[str] = None
    elapsed_us: int = 0  # microseconds


@dataclass
class TraceProfile:
    """Runtime profile for a single traced function."""

    func_name: str
    module: str
    qualname: str
    param_names: List[str]
    observed_arg_types: Dict[str, Set[str]] = field(default_factory=dict)
    observed_return_types: Set[str] = field(default_factory=set)
    exceptions_seen: Set[str] = field(default_factory=set)
    call_count: int = 0
    total_time_us: int = 0
    samples: List[IOSample] = field(default_factory=list)
    is_pure: bool = True  # optimistic; set to False on side-effect indicators

    # ── derived properties ───────────────────────────────────────────────

    @property
    def avg_time_us(self) -> float:
        """Average wall time per call in microseconds."""
        return self.total_time_us / max(self.call_count, 1)

    @property
    def dominant_return_type(self) -> str:
        """Most frequently observed return type."""
        if not self.observed_return_types:
            return "unknown"
        # Pick the first seen (set iteration order in CPython 3.7+)
        return next(iter(self.observed_return_types))

    # ── serialisation ────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a JSON-friendly dict."""
        return {
            "func_name": self.func_name,
            "module": self.module,
            "qualname": self.qualname,
            "param_names": self.param_names,
            "observed_arg_types": {
                k: sorted(v) for k, v in self.observed_arg_types.items()
            },
            "observed_return_types": sorted(self.observed_return_types),
            "exceptions_seen": sorted(self.exceptions_seen),
            "call_count": self.call_count,
            "total_time_us": self.total_time_us,
            "avg_time_us": round(self.avg_time_us, 1),
            "is_pure": self.is_pure,
            "samples": [
                {
                    "args": s.args_repr,
                    "kwargs": s.kwargs_repr,
                    "output": s.output_repr,
                    "output_type": s.output_type,
                    "error": s.error,
                    "elapsed_us": s.elapsed_us,
                }
                for s in self.samples
            ],
        }


# ── FunctionTracer ───────────────────────────────────────────────────────────

MAX_SAMPLES = 50  # cap I/O recordings per function to avoid memory blow-up


class FunctionTracer:
    """
    Lightweight runtime tracer that wraps callables and records I/O.

    Designed to be injected around target functions during a test run.
    After the test run completes, call :meth:`profiles` to retrieve
    the collected :class:`TraceProfile` objects.

    Example::

        tracer = FunctionTracer()
        my_module.tokenize = tracer.wrap(my_module.tokenize)
        # … run tests …
        for profile in tracer.profiles():
            print(profile.func_name, profile.call_count)
    """

    def __init__(self, max_samples: int = MAX_SAMPLES):
        self._traces: Dict[str, TraceProfile] = {}
        self._max_samples = max_samples

    # ── public API ───────────────────────────────────────────────────────

    def wrap(self, fn: Callable) -> Callable:
        """Return a wrapped version of *fn* that records every call."""
        import inspect

        sig = inspect.signature(fn)
        param_names = [p.name for p in sig.parameters.values() if p.name != "self"]

        module = getattr(fn, "__module__", "") or ""
        qualname = getattr(fn, "__qualname__", fn.__name__)
        key = f"{module}.{qualname}"

        profile = TraceProfile(
            func_name=fn.__name__,
            module=module,
            qualname=qualname,
            param_names=param_names,
        )
        self._traces[key] = profile

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return self._record_call(profile, param_names, fn, args, kwargs)

        # allow easy unwrapping
        wrapper.__wrapped__ = fn  # type: ignore[attr-defined]
        return wrapper

    def profiles(self) -> List[TraceProfile]:
        """Return all collected profiles."""
        return list(self._traces.values())

    def profile_for(self, func_name: str) -> Optional[TraceProfile]:
        """Look up a profile by function name (short name or full key)."""
        for key, prof in self._traces.items():
            if prof.func_name == func_name or key == func_name:
                return prof
        return None

    def save(self, path: str | Path) -> None:
        """Persist all profiles to a JSON file."""
        data = [p.to_dict() for p in self.profiles()]
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load(self, path: str | Path) -> List[TraceProfile]:
        """Load profiles from a previously saved JSON file."""
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        loaded = []
        for item in raw:
            tp = TraceProfile(
                func_name=item["func_name"],
                module=item.get("module", ""),
                qualname=item.get("qualname", ""),
                param_names=item.get("param_names", []),
                call_count=item.get("call_count", 0),
                total_time_us=item.get("total_time_us", 0),
                is_pure=item.get("is_pure", True),
                observed_return_types=set(item.get("observed_return_types", [])),
                exceptions_seen=set(item.get("exceptions_seen", [])),
            )
            # Rebuild observed_arg_types as sets
            for k, v in item.get("observed_arg_types", {}).items():
                tp.observed_arg_types[k] = set(v)
            # Rebuild samples
            for s in item.get("samples", []):
                tp.samples.append(
                    IOSample(
                        args_repr=s.get("args", []),
                        kwargs_repr=s.get("kwargs", {}),
                        output_repr=s.get("output", ""),
                        output_type=s.get("output_type", ""),
                        error=s.get("error"),
                        elapsed_us=s.get("elapsed_us", 0),
                    )
                )
            loaded.append(tp)
        return loaded

    def reset(self) -> None:
        """Clear all collected trace data."""
        self._traces.clear()

    # ── internal ─────────────────────────────────────────────────────────

    def _record_call(
        self,
        profile: TraceProfile,
        param_names: List[str],
        fn: Callable,
        args: tuple,
        kwargs: dict,
    ) -> Any:
        """Execute *fn* and record the I/O into *profile*."""
        profile.call_count += 1

        # Record argument types
        for i, val in enumerate(args):
            name = param_names[i] if i < len(param_names) else f"arg{i}"
            profile.observed_arg_types.setdefault(name, set()).add(_type_tag(val))
        for name, val in kwargs.items():
            profile.observed_arg_types.setdefault(name, set()).add(_type_tag(val))

        # Execute and time
        start = time.perf_counter_ns()
        error_str: Optional[str] = None
        result = None
        try:
            result = fn(*args, **kwargs)
        except Exception as exc:
            error_str = type(exc).__name__
            profile.exceptions_seen.add(error_str)
            profile.is_pure = False  # exceptions suggest impurity
            raise
        finally:
            elapsed = (time.perf_counter_ns() - start) // 1000  # → µs
            profile.total_time_us += elapsed

            # Record return type
            if error_str is None:
                profile.observed_return_types.add(_type_tag(result))

            # Capture sample (capped)
            if len(profile.samples) < self._max_samples:
                profile.samples.append(
                    IOSample(
                        args_repr=[_safe_repr(a) for a in args],
                        kwargs_repr={k: _safe_repr(v) for k, v in kwargs.items()},
                        output_repr=_safe_repr(result) if error_str is None else "",
                        output_type=_type_tag(result) if error_str is None else "",
                        error=error_str,
                        elapsed_us=elapsed,
                    )
                )

        return result


# Module-level API for test compatibility
_default_analyzer = IOSample()

def avg_time_us(*args, **kwargs):
    """Wrapper for IOSample.avg_time_us()."""
    return _default_analyzer.avg_time_us(*args, **kwargs)

def dominant_return_type(*args, **kwargs):
    """Wrapper for IOSample.dominant_return_type()."""
    return _default_analyzer.dominant_return_type(*args, **kwargs)

def load(*args, **kwargs):
    """Wrapper for IOSample.load()."""
    return _default_analyzer.load(*args, **kwargs)

def profile_for(*args, **kwargs):
    """Wrapper for IOSample.profile_for()."""
    return _default_analyzer.profile_for(*args, **kwargs)

def profiles(*args, **kwargs):
    """Wrapper for IOSample.profiles()."""
    return _default_analyzer.profiles(*args, **kwargs)

def reset(*args, **kwargs):
    """Wrapper for IOSample.reset()."""
    return _default_analyzer.reset(*args, **kwargs)

def save(*args, **kwargs):
    """Wrapper for IOSample.save()."""
    return _default_analyzer.save(*args, **kwargs)

def to_dict(*args, **kwargs):
    """Wrapper for IOSample.to_dict()."""
    return _default_analyzer.to_dict(*args, **kwargs)

def wrap(*args, **kwargs):
    """Wrapper for IOSample.wrap()."""
    return _default_analyzer.wrap(*args, **kwargs)

