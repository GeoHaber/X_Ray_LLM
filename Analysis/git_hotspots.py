"""
Analysis/git_hotspots.py — Git Churn / Hotspot Analysis (v8.0)
==============================================================

Identifies files with the highest recent commit activity ("churn") and
cross-references them with complexity scores to surface the highest-risk
refactoring candidates — the same insight CodeScene calls "Hotspots."

Usage::

    from Analysis.git_hotspots import HotspotAnalyzer

    analyzer = HotspotAnalyzer(root=Path("/my/project"))
    report   = analyzer.analyze(days=90)
    for hs in report.top_hotspots:
        print(f"{hs.path}: churn={hs.churn}, priority={hs.priority:.1f}")
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# Files containing these strings are skipped (auto-generated / binary)
_SKIP_PATTERNS = (
    "__pycache__",
    ".pyc",
    ".pyo",
    "node_modules/",
    ".min.js",
    ".min.css",
    "package-lock.json",
    "uv.lock",
    "Cargo.lock",
)


@dataclass
class HotspotFile:
    """One file's hotspot metrics."""

    path: str  # Relative to repo root
    churn: int  # Commit count in analysis window
    complexity: float  # Average cyclomatic complexity (0 if unknown)
    loc: int  # Lines of code (0 if unknown)
    priority: float  # churn × (1 + complexity_factor) — higher = worse

    @property
    def badge(self) -> str:
        """Emoji badge based on priority tier."""
        if self.priority >= 20:
            return "🔥"
        if self.priority >= 10:
            return "⚠️"
        return "📄"


@dataclass
class HotspotReport:
    """Aggregate result of hotspot analysis."""

    hotspots: List[HotspotFile] = field(default_factory=list)
    analysis_days: int = 90
    total_commits_scanned: int = 0
    git_available: bool = True
    error: str = ""

    @property
    def top_hotspots(self) -> List[HotspotFile]:
        return sorted(self.hotspots, key=lambda h: h.priority, reverse=True)[:20]

    @property
    def flame_files(self) -> List[HotspotFile]:
        return [h for h in self.hotspots if h.badge == "🔥"]

    def as_dict(self) -> dict:
        return {
            "git_available": self.git_available,
            "analysis_days": self.analysis_days,
            "total_commits": self.total_commits_scanned,
            "total_files": len(self.hotspots),
            "flame_count": len(self.flame_files),
            "error": self.error,
            "top_hotspots": [
                {
                    "path": h.path,
                    "churn": h.churn,
                    "complexity": round(h.complexity, 1),
                    "loc": h.loc,
                    "priority": round(h.priority, 1),
                    "badge": h.badge,
                }
                for h in self.top_hotspots
            ],
        }


class HotspotAnalyzer:
    """Analyze git commit history to find hotspot files."""

    def __init__(self, root: Path):
        self.root = root

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        days: int = 90,
        complexity_map: Optional[Dict[str, float]] = None,
        loc_map: Optional[Dict[str, int]] = None,
    ) -> HotspotReport:
        """
        Run hotspot analysis.

        Args:
            days: Look-back window in days.
            complexity_map: Optional dict mapping relative file path → avg CC.
            loc_map: Optional dict mapping relative file path → line count.
        """
        report = HotspotReport(analysis_days=days)

        # Check git availability
        if not self._is_git_repo():
            report.git_available = False
            report.error = "Not a git repository — skipping hotspot analysis."
            return report

        churn = self._get_churn(days)
        if not churn:
            report.error = "No commit history found in the given window."
            return report

        report.total_commits_scanned = sum(churn.values())

        cx = complexity_map or {}
        lc = loc_map or {}

        for path, count in churn.items():
            complexity = cx.get(path, 0.0)
            loc = lc.get(path, 0)
            # Priority: churn boosted by complexity. Pure churn when no CC data.
            complexity_factor = min(complexity / 10.0, 3.0)  # cap at 3×
            priority = count * (1.0 + complexity_factor)
            report.hotspots.append(
                HotspotFile(
                    path=path,
                    churn=count,
                    complexity=complexity,
                    loc=loc,
                    priority=priority,
                )
            )

        return report

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_git_repo(self) -> bool:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _get_churn(self, days: int) -> Dict[str, int]:
        """Return {relative_path: commit_count} for the last *days* days."""
        try:
            result = subprocess.run(
                [
                    "git",
                    "log",
                    f"--since={days}.days",
                    "--name-only",
                    "--pretty=format:",
                    "--diff-filter=ACMR",
                ],
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return {}

        churn: Dict[str, int] = {}
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            if any(p in line for p in _SKIP_PATTERNS):
                continue
            churn[line] = churn.get(line, 0) + 1

        return churn
