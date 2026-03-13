"""
Analysis/temporal_coupling.py — Temporal / Change Coupling Analysis (v8.0)
==========================================================================

Identifies files that frequently change together across git commits
("temporal coupling" or "change coupling"). High coupling between files
that appear architecturally unrelated reveals hidden dependencies and is
a strong predictor of cascading bugs.

This is the open-source equivalent of CodeScene's most powerful feature —
built purely from ``git log`` output with zero ML dependencies.

Usage::

    from Analysis.temporal_coupling import TemporalCouplingAnalyzer

    analyzer = TemporalCouplingAnalyzer(root=Path("/my/project"))
    report = analyzer.analyze(days=180, min_commits=3, min_coupling=0.25)
    for pair in report.top_pairs:
        print(f"{pair.file_a} ↔ {pair.file_b}: {pair.coupling_pct:.0%}")
"""

from __future__ import annotations

import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Dict, List, Set, Tuple

_SKIP_PATTERNS = (
    "__pycache__",
    ".pyc",
    ".min.js",
    ".min.css",
    "package-lock.json",
    "uv.lock",
    "Cargo.lock",
    "xray_scan_history",
    ".json",  # skip generated JSON outputs
)


@dataclass
class CoupledPair:
    """Two files that change together frequently."""

    file_a: str
    file_b: str
    cochange_count: int  # Times changed in same commit
    total_commits_a: int  # Total commits touching file_a
    total_commits_b: int  # Total commits touching file_b
    coupling_pct: float  # cochange / max(commits_a, commits_b)

    @property
    def strength(self) -> str:
        if self.coupling_pct >= 0.75:
            return "strong"
        if self.coupling_pct >= 0.50:
            return "moderate"
        return "weak"

    @property
    def badge(self) -> str:
        return {"strong": "🔴", "moderate": "🟡", "weak": "🟢"}[self.strength]


@dataclass
class TemporalCouplingReport:
    """Full result of temporal coupling analysis."""

    pairs: List[CoupledPair] = field(default_factory=list)
    analysis_days: int = 180
    commits_analyzed: int = 0
    git_available: bool = True
    error: str = ""

    @property
    def top_pairs(self) -> List[CoupledPair]:
        return sorted(self.pairs, key=lambda p: p.coupling_pct, reverse=True)[:30]

    @property
    def strong_pairs(self) -> List[CoupledPair]:
        return [p for p in self.pairs if p.strength == "strong"]

    def as_dict(self) -> dict:
        return {
            "git_available": self.git_available,
            "analysis_days": self.analysis_days,
            "commits_analyzed": self.commits_analyzed,
            "total_pairs": len(self.pairs),
            "strong_pairs": len(self.strong_pairs),
            "error": self.error,
            "top_pairs": [
                {
                    "file_a": p.file_a,
                    "file_b": p.file_b,
                    "cochange_count": p.cochange_count,
                    "coupling_pct": round(p.coupling_pct * 100, 1),
                    "strength": p.strength,
                    "badge": p.badge,
                }
                for p in self.top_pairs
            ],
        }


class TemporalCouplingAnalyzer:
    """Parse git history to find change-coupled file pairs."""

    def __init__(self, root: Path):
        self.root = root

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        days: int = 180,
        min_commits: int = 3,
        min_coupling: float = 0.25,
    ) -> TemporalCouplingReport:
        """
        Run temporal coupling analysis.

        Args:
            days: Look-back window in days.
            min_commits: Minimum co-change count to surface a pair.
            min_coupling: Minimum coupling ratio (0–1) to include a pair.
        """
        report = TemporalCouplingReport(analysis_days=days)

        if not self._is_git_repo():
            report.git_available = False
            report.error = "Not a git repository."
            return report

        commits = self._get_commit_groups(days)
        if not commits:
            report.error = "No commits found in the given window."
            return report

        report.commits_analyzed = len(commits)

        # Count co-changes and per-file total commits
        cochange: Dict[Tuple[str, str], int] = defaultdict(int)
        file_commits: Dict[str, int] = defaultdict(int)

        for files in commits:
            for f in files:
                file_commits[f] += 1
            for fa, fb in combinations(sorted(files), 2):
                cochange[(fa, fb)] += 1

        # Build pairs
        pairs: List[CoupledPair] = []
        for (fa, fb), count in cochange.items():
            if count < min_commits:
                continue
            ca = file_commits[fa]
            cb = file_commits[fb]
            pct = count / max(ca, cb)
            if pct < min_coupling:
                continue
            pairs.append(
                CoupledPair(
                    file_a=fa,
                    file_b=fb,
                    cochange_count=count,
                    total_commits_a=ca,
                    total_commits_b=cb,
                    coupling_pct=pct,
                )
            )

        report.pairs = pairs
        return report

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_git_repo(self) -> bool:
        try:
            r = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=5,
            )
            return r.returncode == 0
        except Exception:
            return False

    def _get_commit_groups(self, days: int) -> List[Set[str]]:
        """Return a list of file-sets, one per commit."""
        try:
            result = subprocess.run(
                [
                    "git",
                    "log",
                    f"--since={days}.days",
                    "--name-only",
                    "--pretty=format:COMMIT_BOUNDARY",
                    "--diff-filter=ACMR",
                ],
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except Exception:
            return []

        commits: List[Set[str]] = []
        current: Set[str] = set()

        for line in result.stdout.splitlines():
            line = line.strip()
            if line == "COMMIT_BOUNDARY":
                if current:
                    commits.append(current)
                current = set()
            elif line and not any(p in line for p in _SKIP_PATTERNS):
                current.add(line)

        if current:
            commits.append(current)

        return [c for c in commits if len(c) >= 2]  # only multi-file commits
