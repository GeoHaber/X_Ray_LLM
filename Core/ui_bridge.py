"""
Core/ui_bridge.py — UI-Agnostic Output Bridge for X-Ray
=========================================================

All status messages, progress updates, and log lines that scan/analysis
modules want to surface are routed through this bridge.  Swapping the
active bridge (``set_bridge``) is all it takes to change the UI:

    # CLI (default — plain print)
    from Core.ui_bridge import set_bridge, PrintBridge
    set_bridge(PrintBridge())

    # Flet GUI
    from Core.ui_bridge import set_bridge, UIBridge
    class FletBridge(UIBridge):
        ...
    set_bridge(FletBridge(page, progress_cb))

    # Tests — suppress all output
    from Core.ui_bridge import set_bridge, NullBridge
    set_bridge(NullBridge())

    # tqdm progress bars (optional)
    from Core.ui_bridge import set_bridge, TqdmBridge
    set_bridge(TqdmBridge())

Supported UI targets (via custom subclass):
    - Flet / Flutter desktop
    - Streamlit (st.progress / st.write)
    - NiceGUI  (ui.notify / ui.linear_progress)
    - PyQt / tkinter
    - Any future framework

The bridge module itself has NO UI-framework imports — it stays lean
and importable in headless / test environments.
"""

from __future__ import annotations

import sys
from typing import Optional, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Protocol — the contract every bridge must satisfy
# ---------------------------------------------------------------------------


@runtime_checkable
class UIBridge(Protocol):
    """
    Minimal interface for all UI bridges.

    Scan/analysis code calls these three methods instead of ``print()``
    or any framework-specific API.

    Methods
    -------
    log(msg)
        A plain informational line (replaces ``print(msg)``).
    status(label)
        The name of the current phase / step being executed.
    progress(done, total, label)
        Update a progress indicator.
        ``done`` and ``total`` are item counts (use 0,0 for indeterminate).
        ``label`` is a short description of the item being processed.
    """

    def log(self, msg: str) -> None: ...

    def status(self, label: str) -> None: ...

    def progress(self, done: int, total: int, label: str = "") -> None: ...


# ---------------------------------------------------------------------------
# PrintBridge — default; keeps existing CLI output unchanged
# ---------------------------------------------------------------------------


class PrintBridge:
    """Default bridge: routes everything to stdout via ``print()``.

    This is a drop-in replacement for the bare ``print()`` calls that
    used to be scattered across modules.  CLI behaviour is identical.
    """

    def log(self, msg: str) -> None:
        print(msg, flush=True)

    def status(self, label: str) -> None:
        print(f"\n  >> {label}", flush=True)

    def progress(self, done: int, total: int, label: str = "") -> None:
        if total > 0:
            pct = done * 100 // total
            suffix = f"  {label[:60]}" if label else ""
            line = f"\r    [{pct:3d}%] {done}/{total} files{suffix}"
            # Overwrite in place on terminals; fall back to newline otherwise
            if sys.stdout.isatty():
                print(line, end="", flush=True)
                if done >= total:
                    print()  # final newline
            else:
                print(line.strip(), flush=True)
        elif label:
            print(f"    {label}", flush=True)


# ---------------------------------------------------------------------------
# NullBridge — silent; perfect for unit tests and headless jobs
# ---------------------------------------------------------------------------


class NullBridge:
    """Silent bridge — swallows all output.

    Use in tests to stop library code from printing to stdout/stderr::

        from Core.ui_bridge import set_bridge, NullBridge
        set_bridge(NullBridge())
    """

    def log(self, msg: str) -> None:  # noqa: ARG002
        pass

    def status(self, label: str) -> None:  # noqa: ARG002
        pass

    def progress(self, done: int, total: int, label: str = "") -> None:  # noqa: ARG002
        pass


# ---------------------------------------------------------------------------
# TqdmBridge — rich progress bars when tqdm is installed
# ---------------------------------------------------------------------------


class TqdmBridge:
    """Bridge that uses tqdm for progress bars.

    Falls back to ``PrintBridge`` if tqdm is not installed.

    Parameters
    ----------
    desc_width : int
        Maximum width for the tqdm description string.
    """

    def __init__(self, desc_width: int = 50) -> None:
        self._desc_width = desc_width
        self._bar: Optional[object] = None
        try:
            import tqdm as _tqdm  # noqa: F401  # pyright: ignore[reportUnusedImport]

            self._has_tqdm = True
        except ImportError:
            self._has_tqdm = False
            self._fallback = PrintBridge()

    def log(self, msg: str) -> None:
        if self._has_tqdm:
            try:
                from tqdm import tqdm

                tqdm.write(msg)
                return
            except Exception:
                pass
        if hasattr(self, "_fallback"):
            self._fallback.log(msg)
        else:
            print(msg, flush=True)

    def status(self, label: str) -> None:
        """Close any open bar and open a fresh one for the new phase."""
        self._close_bar()
        self.log(f"\n  >> {label}")

    def progress(self, done: int, total: int, label: str = "") -> None:
        if not self._has_tqdm:
            if hasattr(self, "_fallback"):
                self._fallback.progress(done, total, label)
            return
        try:
            from tqdm import tqdm

            if self._bar is None or getattr(self._bar, "total", 0) != total:
                self._close_bar()
                self._bar = tqdm(
                    total=max(total, 1),
                    desc=label[: self._desc_width] or "Scanning",
                    unit="file",
                    dynamic_ncols=True,
                )
            if done > getattr(self._bar, "n", 0):
                self._bar.update(done - self._bar.n)
            if label:
                self._bar.set_postfix_str(label[-self._desc_width :], refresh=False)
            if done >= total:
                self._close_bar()
        except Exception:
            pass

    def _close_bar(self) -> None:
        if self._bar is not None:
            try:
                self._bar.close()
            except Exception:
                pass
            self._bar = None


# ---------------------------------------------------------------------------
# Global accessor — single active bridge for the process
# ---------------------------------------------------------------------------

_bridge_ref: list = [PrintBridge()]  # mutable container — avoids global keyword


def get_bridge() -> UIBridge:
    """Return the currently active UI bridge."""
    return _bridge_ref[0]


def set_bridge(bridge: UIBridge) -> None:
    """Set the active UI bridge.

    Call this once at application startup before any scans begin::

        from Core.ui_bridge import set_bridge, NullBridge
        set_bridge(NullBridge())   # silence all output in tests

    Parameters
    ----------
    bridge : UIBridge
        Any object that implements ``log``, ``status``, and ``progress``.
    """
    _bridge_ref[0] = bridge


# ---------------------------------------------------------------------------
# Convenience shorthands (optional; keeps call sites terse)
# ---------------------------------------------------------------------------


def log(msg: str) -> None:
    """Shorthand: ``get_bridge().log(msg)``."""
    _bridge_ref[0].log(msg)


def status(label: str) -> None:
    """Shorthand: ``get_bridge().status(label)``."""
    _bridge_ref[0].status(label)


def progress(done: int, total: int, label: str = "") -> None:
    """Shorthand: ``get_bridge().progress(done, total, label)``."""
    _bridge_ref[0].progress(done, total, label)
