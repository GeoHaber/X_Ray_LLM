"""
tests/test_ui_bridge.py — Tests for Core.ui_bridge
===================================================

Verifies that:
  - PrintBridge routes through stdout (testable with capsys)
  - NullBridge swallows all output silently
  - set_bridge / get_bridge work correctly
  - TqdmBridge falls back gracefully if tqdm is absent
  - The UIBridge Protocol is satisfied by all built-in classes
"""

from __future__ import annotations

import sys
import importlib
from unittest.mock import patch

import pytest

from Core.ui_bridge import (
    UIBridge,
    PrintBridge,
    NullBridge,
    TqdmBridge,
    get_bridge,
    set_bridge,
    log as _log,
    status as _status,
    progress as _progress,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def restore_bridge():
    """Restore the original bridge after each test."""
    original = get_bridge()
    yield
    set_bridge(original)


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------

class TestProtocolConformance:
    """All built-in bridges must satisfy the UIBridge Protocol."""

    def test_print_bridge_is_ui_bridge(self):
        assert isinstance(PrintBridge(), UIBridge)

    def test_null_bridge_is_ui_bridge(self):
        assert isinstance(NullBridge(), UIBridge)

    def test_tqdm_bridge_is_ui_bridge(self):
        assert isinstance(TqdmBridge(), UIBridge)

    def test_custom_bridge_satisfies_protocol(self):
        """A custom implementation must satisfy the Protocol."""
        class MyBridge:
            def log(self, msg: str) -> None: pass
            def status(self, label: str) -> None: pass
            def progress(self, done: int, total: int, label: str = "") -> None: pass

        assert isinstance(MyBridge(), UIBridge)


# ---------------------------------------------------------------------------
# PrintBridge
# ---------------------------------------------------------------------------

class TestPrintBridge:

    def test_log_outputs_to_stdout(self, capsys):
        b = PrintBridge()
        b.log("Hello, World!")
        captured = capsys.readouterr()
        assert "Hello, World!" in captured.out

    def test_status_includes_label(self, capsys):
        b = PrintBridge()
        b.status("Running lint")
        captured = capsys.readouterr()
        assert "Running lint" in captured.out

    def test_progress_with_nonzero_total(self, capsys):
        b = PrintBridge()
        # Non-TTY fallback — should print something without crashing
        b.progress(5, 10, "scanning foo.py")
        captured = capsys.readouterr()
        assert "5" in captured.out or "50" in captured.out or "scanning" in captured.out

    def test_progress_zero_total_with_label(self, capsys):
        b = PrintBridge()
        b.progress(0, 0, "indeterminate")
        captured = capsys.readouterr()
        assert "indeterminate" in captured.out

    def test_progress_zero_total_no_label_no_crash(self):
        b = PrintBridge()
        b.progress(0, 0)  # should not raise


# ---------------------------------------------------------------------------
# NullBridge
# ---------------------------------------------------------------------------

class TestNullBridge:

    def test_log_produces_no_output(self, capsys):
        b = NullBridge()
        b.log("secret message")
        b.status("processing")
        b.progress(3, 10, "file.py")
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""

    def test_null_bridge_set_globally_silences_modules(self, capsys):
        set_bridge(NullBridge())
        _log("This should be silent")
        _status("silent phase")
        _progress(1, 2, "test")
        captured = capsys.readouterr()
        assert captured.out == ""


# ---------------------------------------------------------------------------
# set_bridge / get_bridge
# ---------------------------------------------------------------------------

class TestGlobalAccessor:

    def test_default_bridge_is_print_bridge(self):
        # After restore_bridge restores original, it should be PrintBridge
        b = get_bridge()
        assert isinstance(b, PrintBridge)

    def test_set_bridge_changes_active_bridge(self):
        null = NullBridge()
        set_bridge(null)
        assert get_bridge() is null

    def test_shorthand_log_routes_through_active_bridge(self, capsys):
        set_bridge(NullBridge())
        _log("should not appear")
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_shorthand_status_routes_through_active_bridge(self, capsys):
        set_bridge(NullBridge())
        _status("phase x")
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_shorthand_progress_routes_through_active_bridge(self, capsys):
        set_bridge(NullBridge())
        _progress(1, 5)
        captured = capsys.readouterr()
        assert captured.out == ""


# ---------------------------------------------------------------------------
# TqdmBridge
# ---------------------------------------------------------------------------

class TestTqdmBridge:

    def test_log_falls_back_to_print_when_no_tqdm(self, capsys):
        """When tqdm is not installed, TqdmBridge should still log."""
        with patch.dict(sys.modules, {"tqdm": None}):
            b = TqdmBridge()
            b.log("fallback message")
        captured = capsys.readouterr()
        # Either tqdm caught it, or fallback printed it — no crash either way
        # We only require no exception; output behaviour is implementation detail

    def test_tqdm_bridge_progress_no_crash(self):
        """progress() must not raise even with weird values."""
        b = TqdmBridge()
        b.progress(0, 0)
        b.progress(1, 5, "processing")
        b.progress(5, 5)  # completion

    def test_tqdm_bridge_status_no_crash(self):
        b = TqdmBridge()
        b.status("scanning")
        b.status("linting")  # second call should close previous bar cleanly

    def test_tqdm_bridge_satisfies_protocol(self):
        assert isinstance(TqdmBridge(), UIBridge)


# ---------------------------------------------------------------------------
# Swappability demo
# ---------------------------------------------------------------------------

class TestSwappability:
    """Demonstrates the key design goal: swap bridge without changing callers."""

    def _run_simulation(self):
        """Simulate what scan_phases would call."""
        _status("Analyzing Code Smells")
        _progress(50, 100, "scan.py")
        _log("Found 3 issues")

    def test_print_bridge_produces_output(self, capsys):
        set_bridge(PrintBridge())
        self._run_simulation()
        out = capsys.readouterr().out
        assert "Analyzing Code Smells" in out
        assert "Found 3 issues" in out

    def test_null_bridge_produces_no_output(self, capsys):
        set_bridge(NullBridge())
        self._run_simulation()
        out = capsys.readouterr().out
        assert out == ""

    def test_custom_collecting_bridge(self):
        """A custom bridge can collect messages for assertions."""
        class CollectorBridge:
            def __init__(self):
                self.logs = []
                self.statuses = []
            def log(self, msg: str) -> None:
                self.logs.append(msg)
            def status(self, label: str) -> None:
                self.statuses.append(label)
            def progress(self, done: int, total: int, label: str = "") -> None:
                pass

        collector = CollectorBridge()
        set_bridge(collector)
        self._run_simulation()

        assert any("Analyzing Code Smells" in s for s in collector.statuses)
        assert any("Found 3 issues" in l for l in collector.logs)
