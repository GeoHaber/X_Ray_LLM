"""
Analysis/trend.py — Scan-to-Scan Delta Reporting (v6.0.0)
==========================================================

Compares two X-Ray result dicts (``prev`` from a previous JSON report,
``curr`` from the current scan) and returns per-category deltas so the
grade report can show a one-line "▲/▼ N pts vs previous scan" indicator.

Usage::

    from Analysis.trend import compare_scans, load_prev_results

    prev = load_prev_results("xray_last.json")  # returns None if file missing
    delta = compare_scans(prev, curr_results)   # returns {} if prev is None
    # delta = {"grade": {"score": -2.1, "letter": "B→B-"},
    #          "smells": {"total": +3, "critical": -1}, ...}
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


def load_prev_results(path: str | Path) -> Optional[Dict[str, Any]]:
    """Load a previous scan result dict from *path*.

    Returns ``None`` silently if the file does not exist or is unreadable.
    """
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


def _delta_int(prev_val: Any, curr_val: Any) -> Optional[int]:
    """Return integer delta if both values are numeric, else None."""
    try:
        return int(curr_val) - int(prev_val)
    except (TypeError, ValueError):
        return None


def _delta_float(prev_val: Any, curr_val: Any, ndigits: int = 1) -> Optional[float]:
    """Return rounded float delta if both values are numeric, else None."""
    try:
        return round(float(curr_val) - float(prev_val), ndigits)
    except (TypeError, ValueError):
        return None


def _smells_delta(prev: Dict, curr: Dict) -> Dict[str, Any]:
    """Compare smell summaries."""
    out: Dict[str, Any] = {}
    for key in ("total", "critical", "warning", "info"):
        d = _delta_int(prev.get(key), curr.get(key))
        if d is not None:
            out[key] = d
    return out


def _duplicates_delta(prev: Dict, curr: Dict) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key in ("total_groups", "total_functions_involved"):
        d = _delta_int(prev.get(key), curr.get(key))
        if d is not None:
            out[key] = d
    return out


def _lint_security_delta(prev: Dict, curr: Dict) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key in ("total", "critical", "warning", "info", "fixable"):
        d = _delta_int(prev.get(key), curr.get(key))
        if d is not None:
            out[key] = d
    return out


def _grade_delta(prev: Dict, curr: Dict) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    d_score = _delta_float(prev.get("score"), curr.get("score"))
    if d_score is not None:
        out["score"] = d_score
    p_letter = prev.get("letter", "")
    c_letter = curr.get("letter", "")
    if p_letter and c_letter and p_letter != c_letter:
        out["letter"] = f"{p_letter}→{c_letter}"
    return out


_CATEGORY_HANDLERS = {
    "smells": _smells_delta,
    "duplicates": _duplicates_delta,
    "lint": _lint_security_delta,
    "security": _lint_security_delta,
    "grade": _grade_delta,
}


def compare_scans(
    prev: Optional[Dict[str, Any]],
    curr: Dict[str, Any],
) -> Dict[str, Any]:
    """Compare *prev* and *curr* scan result dicts.

    Returns a nested delta dict with the same top-level keys as the
    scan results dict.  Missing keys in either dict are skipped.
    Returns ``{}`` when *prev* is ``None``.
    """
    if not prev:
        return {}

    delta: Dict[str, Any] = {}
    for category, handler in _CATEGORY_HANDLERS.items():
        p = prev.get(category)
        c = curr.get(category)
        if isinstance(p, dict) and isinstance(c, dict):
            cat_delta = handler(p, c)
            if cat_delta:
                delta[category] = cat_delta

    return delta


def format_grade_delta(delta: Dict[str, Any]) -> str:
    """Return a human-readable one-liner for the grade delta.

    Examples::

        "▲ +3.5 pts vs previous scan (B→A-)"
        "▼ -2.1 pts vs previous scan"
        ""  (when *delta* is empty)
    """
    if not delta:
        return ""
    grade_d = delta.get("grade", {})
    score_d = grade_d.get("score")
    if score_d is None:
        return ""
    arrow = "▲" if score_d >= 0 else "▼"
    sign = "+" if score_d >= 0 else ""
    letter_note = ""
    if "letter" in grade_d:
        letter_note = f" ({grade_d['letter']})"
    return f"{arrow} {sign}{score_d} pts vs previous scan{letter_note}"
