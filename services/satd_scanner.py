"""
SATD Scanner — Self-Admitted Technical Debt analysis.

Extracted from ui_server.py.
"""

import os
import re

from xray.constants import SKIP_DIRS as _SATD_SKIP_DIRS
from xray.constants import TEXT_EXTS as _TEXT_EXTENSIONS
from xray.constants import fwd as _fwd

_SATD_MARKERS = [
    (re.compile(r"\b(FIXME)\b", re.IGNORECASE), "defect", 1.0),
    (re.compile(r"\b(BUG|BUGFIX)\b", re.IGNORECASE), "defect", 1.0),
    (re.compile(r"\b(XXX)\b", re.IGNORECASE), "defect", 1.0),
    (re.compile(r"\b(SECURITY)\b", re.IGNORECASE), "defect", 1.0),
    (re.compile(r"\b(HACK)\b", re.IGNORECASE), "design", 2.0),
    (re.compile(r"\b(WORKAROUND)\b", re.IGNORECASE), "design", 2.0),
    (re.compile(r"\b(KLUDGE)\b", re.IGNORECASE), "design", 2.0),
    (re.compile(r"\b(TODO)\b", re.IGNORECASE), "design", 2.0),
    (re.compile(r"\b(OPTIMIZE|PERF)\b", re.IGNORECASE), "design", 2.0),
    (re.compile(r"\b(TECH.?DEBT|DEBT)\b", re.IGNORECASE), "debt", 3.0),
    (re.compile(r"\b(NOQA|type:\\s*ignore)\b", re.IGNORECASE), "test", 0.5),
    (re.compile(r"\b(DOCME|DOCUMENT|UNDOCUMENTED)\b", re.IGNORECASE), "documentation", 0.25),
]

_COMMENT_RE = re.compile(r"#\s*(.*)")


def scan_satd(directory: str) -> dict:
    """Scan for Self-Admitted Technical Debt markers (TODO, FIXME, HACK, etc.)."""
    items = []
    by_category: dict[str, list] = {}
    total_hours = 0.0

    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames[:] = [d for d in dirnames if d not in _SATD_SKIP_DIRS]
        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in _TEXT_EXTENSIONS:
                continue
            fpath = os.path.join(dirpath, fname)
            try:
                with open(fpath, encoding="utf-8", errors="ignore") as fh:
                    for lineno, line in enumerate(fh, 1):
                        for pat, category, hours in _SATD_MARKERS:
                            m = pat.search(line)
                            if m:
                                text = line.strip()
                                cm = _COMMENT_RE.search(line)
                                if cm:
                                    text = cm.group(1).strip()
                                items.append(
                                    {
                                        "file": _fwd(fpath),
                                        "line": lineno,
                                        "category": category,
                                        "marker": m.group(1).upper(),
                                        "text": text[:200],
                                        "hours": hours,
                                    }
                                )
                                total_hours += hours
                                by_category.setdefault(category, []).append(items[-1])
                                break
            except (OSError, UnicodeDecodeError):
                continue

    return {
        "total_items": len(items),
        "total_hours": round(total_hours, 1),
        "items": items,
        "by_category": {k: v for k, v in by_category.items()},
    }
