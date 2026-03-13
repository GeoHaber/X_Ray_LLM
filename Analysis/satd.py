"""
Analysis/satd.py — Self-Admitted Technical Debt (SATD) Scanner (v8.0)
======================================================================

Scans Python source files for SATD markers in comments and docstrings
(TODO, FIXME, HACK, XXX, DEBT, WORKAROUND, BUG, NOQA) and classifies
them by type with estimated remediation hours.

Usage::

    from Analysis.satd import SATDScanner, SATDItem

    scanner = SATDScanner()
    items = scanner.scan_directory(Path("/some/project"))
    total_hours = sum(i.hours for i in items)

Research basis:
    DebtViz (arXiv 2023), Transformer-based SATD classifiers (arXiv 2024-2025).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# ── Marker patterns → SATD category ──────────────────────────────────────────

_MARKERS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(FIXME)\b|\b(BUGFIX|BUG)\s*:", re.IGNORECASE), "defect"),
    (re.compile(r"\b(HACK|WORKAROUND|KLUDGE|KLUGE)\b", re.IGNORECASE), "design"),
    (re.compile(r"\b(TODO|TO-DO|TO DO)\b", re.IGNORECASE), "design"),
    (re.compile(r"\b(DEBT|TECH-DEBT|TECHNICAL DEBT)\b", re.IGNORECASE), "debt"),
    (re.compile(r"\b(XXX)\b"), "defect"),
    (re.compile(r"\b(NOQA|TYPE:\s*IGNORE)\b", re.IGNORECASE), "test"),
    (re.compile(r"\b(REMOVEME|DEPRECATED|REMOVE ME)\b", re.IGNORECASE), "design"),
    (re.compile(r"\b(OPTIMIZE|PERF|PERFORMANCE)\b", re.IGNORECASE), "design"),
    (re.compile(r"\b(SECURITY|SEC ISSUE)\b", re.IGNORECASE), "defect"),
    (re.compile(r"\b(DOCME|DOCUMENT|UNDOCUMENTED)\b", re.IGNORECASE), "documentation"),
]

# Estimated remediation hours per SATD category (conservative)
_HOURS: dict[str, float] = {
    "defect": 1.0,
    "design": 2.0,
    "debt": 3.0,
    "test": 0.5,
    "documentation": 0.25,
}

# Comment patterns (single-line and inline)
_COMMENT_RE = re.compile(r"#\s*(.*)")
_DOCSTRING_RE = re.compile(r'"""(.*?)"""|\'\'\'(.*?)\'\'\'', re.DOTALL)

# Skip non-source directories
_SKIP_DIRS = frozenset(
    {
        "__pycache__",
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "build",
        ".mypy_cache",
        ".pytest_cache",
        "_rustified",
        "_training_ground",
        "_mothership",
        "_verify_crate",
    }
)


@dataclass
class SATDItem:
    """A single self-admitted technical debt occurrence."""

    file: str
    line: int
    category: str  # defect / design / debt / test / documentation
    marker: str  # The matched keyword (e.g. "TODO")
    text: str  # Full comment text (stripped)
    hours: float  # Estimated remediation hours
    severity: str = "warning"

    @property
    def short_text(self) -> str:
        """Return text capped at 120 chars."""
        return self.text[:120] + ("…" if len(self.text) > 120 else "")


@dataclass
class SATDSummary:
    """Aggregate result of a SATD scan."""

    items: List[SATDItem] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.items)

    @property
    def total_hours(self) -> float:
        return round(sum(i.hours for i in self.items), 1)

    @property
    def by_category(self) -> dict[str, list[SATDItem]]:
        cats: dict[str, list[SATDItem]] = {}
        for item in self.items:
            cats.setdefault(item.category, []).append(item)
        return cats

    @property
    def by_file(self) -> dict[str, list[SATDItem]]:
        files: dict[str, list[SATDItem]] = {}
        for item in self.items:
            files.setdefault(item.file, []).append(item)
        return files

    @property
    def top_files(self) -> list[tuple[str, int, float]]:
        """Return list of (file, count, hours) sorted by count desc."""
        result = []
        for f, items in self.by_file.items():
            result.append((f, len(items), sum(i.hours for i in items)))
        return sorted(result, key=lambda x: x[1], reverse=True)

    def as_dict(self) -> dict:
        return {
            "total": self.total,
            "total_hours": self.total_hours,
            "by_category": {cat: len(items) for cat, items in self.by_category.items()},
            "top_files": [
                {"file": f, "count": c, "hours": round(h, 1)}
                for f, c, h in self.top_files[:10]
            ],
            "items": [
                {
                    "file": i.file,
                    "line": i.line,
                    "category": i.category,
                    "marker": i.marker,
                    "text": i.short_text,
                    "hours": i.hours,
                }
                for i in self.items
            ],
        }


class SATDScanner:
    """Scan a directory tree for self-admitted technical debt comments."""

    def __init__(self, extensions: tuple[str, ...] = (".py",)):
        self.extensions = extensions

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan_directory(self, root: Path) -> SATDSummary:
        """Recursively scan *root* for SATD and return a SATDSummary."""
        summary = SATDSummary()
        for path in self._walk(root):
            summary.items.extend(self._scan_file(path, root))
        return summary

    def scan_files(self, files: list[Path], root: Optional[Path] = None) -> SATDSummary:
        """Scan an explicit list of files."""
        summary = SATDSummary()
        for path in files:
            summary.items.extend(self._scan_file(path, root or path.parent))
        return summary

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _walk(self, root: Path):
        for path in root.rglob("*"):
            if any(part in _SKIP_DIRS for part in path.parts):
                continue
            if path.suffix in self.extensions and path.is_file():
                yield path

    def _scan_file(self, path: Path, root: Path) -> list[SATDItem]:
        items: list[SATDItem] = []
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return items

        rel = str(path.relative_to(root)) if root else str(path)

        for lineno, line in enumerate(text.splitlines(), start=1):
            comment_match = _COMMENT_RE.search(line)
            if comment_match:
                comment_text = comment_match.group(1).strip()
                item = self._classify(rel, lineno, comment_text)
                if item:
                    items.append(item)

        return items

    @staticmethod
    def _classify(file: str, line: int, text: str) -> Optional[SATDItem]:
        """Return a SATDItem if *text* contains a marker, else None."""
        for pattern, category in _MARKERS:
            m = pattern.search(text)
            if m:
                marker = m.group(0).upper().strip()
                hours = _HOURS.get(category, 1.0)
                return SATDItem(
                    file=file,
                    line=line,
                    category=category,
                    marker=marker,
                    text=text,
                    hours=hours,
                )
        return None
