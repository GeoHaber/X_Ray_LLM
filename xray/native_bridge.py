"""
Native bridge -- tries to use the Rust scanner via PyO3.
Falls back to pure-Python scanner if the native extension is not built.

Build the extension with::

    pip install maturin
    python build_native.py
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

_NATIVE_AVAILABLE = False
_native: Any = None

try:
    import xray_native as _native  # type: ignore[import-not-found]
    _NATIVE_AVAILABLE = True
    log.info("Rust native scanner loaded (xray_native v%s)", _native.version())
except ImportError:
    log.debug("Native extension not available -- using pure-Python scanner")


def is_available() -> bool:
    """Return True if the native Rust scanner extension is loaded."""
    return _NATIVE_AVAILABLE


def scan_file(path: str) -> list[dict[str, Any]]:
    """Scan a single file using the native Rust scanner."""
    if not _NATIVE_AVAILABLE:
        raise RuntimeError("Native extension not available -- build with: python build_native.py")
    return _native.py_scan_file(path)


def scan_directory(
    root: str,
    exclude_patterns: list[str] | None = None,
    incremental: bool = False,
) -> dict[str, Any]:
    """Scan a directory using the native Rust scanner."""
    if not _NATIVE_AVAILABLE:
        raise RuntimeError("Native extension not available -- build with: python build_native.py")
    return _native.py_scan_directory(root, exclude_patterns, incremental)


def preview_fix(filepath: str, rule_id: str, line: int) -> dict[str, Any]:
    """Preview a fix using the native Rust fixer."""
    if not _NATIVE_AVAILABLE:
        raise RuntimeError("Native extension not available -- build with: python build_native.py")
    return _native.py_preview_fix(filepath, rule_id, line)


def apply_fix(filepath: str, rule_id: str, line: int) -> dict[str, Any]:
    """Apply a fix using the native Rust fixer."""
    if not _NATIVE_AVAILABLE:
        raise RuntimeError("Native extension not available -- build with: python build_native.py")
    return _native.py_apply_fix(filepath, rule_id, line)


def fixable_rules() -> list[str]:
    """Return the list of rule IDs that have auto-fixers in the Rust scanner."""
    if not _NATIVE_AVAILABLE:
        raise RuntimeError("Native extension not available -- build with: python build_native.py")
    return _native.py_fixable_rules()
