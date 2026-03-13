"""
Analysis/coverage.py — Code Coverage Overlay (v8.0)
====================================================

Runs ``pytest --cov --cov-report=json`` in a subprocess and parses the
resulting coverage data to produce a per-file coverage map that can be
overlaid on the X-Ray heatmap. Files with low coverage AND high
complexity are flagged as "danger zones."

Usage::

    from Analysis.coverage import CoverageRunner

    runner = CoverageRunner(root=Path("/my/project"))
    report = runner.run()
    for f in report.danger_zones:
        print(f"{f.path}: cov={f.coverage_pct:.0%}, complexity={f.complexity:.1f}")
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

_LOW_COVERAGE_THRESHOLD = 0.60   # < 60% = low
_HIGH_COMPLEXITY_THRESHOLD = 8   # CC >= 8 = high


@dataclass
class FileCoverage:
    """Coverage data for a single file."""

    path: str                     # Relative file path
    covered_lines: int
    total_lines: int
    coverage_pct: float           # 0–1
    complexity: float = 0.0       # Will be populated by caller if available

    @property
    def is_low_coverage(self) -> bool:
        return self.total_lines > 0 and self.coverage_pct < _LOW_COVERAGE_THRESHOLD

    @property
    def is_danger(self) -> bool:
        return self.is_low_coverage and self.complexity >= _HIGH_COMPLEXITY_THRESHOLD

    @property
    def badge(self) -> str:
        if self.is_danger:
            return "☠️"
        if self.is_low_coverage:
            return "⚠️"
        return "✅"


@dataclass
class CoverageReport:
    """Aggregate coverage results."""

    files: List[FileCoverage] = field(default_factory=list)
    total_coverage_pct: float = 0.0
    pytest_available: bool = True
    error: str = ""

    @property
    def danger_zones(self) -> List[FileCoverage]:
        return [f for f in self.files if f.is_danger]

    @property
    def low_coverage_files(self) -> List[FileCoverage]:
        return sorted(
            [f for f in self.files if f.is_low_coverage],
            key=lambda f: f.coverage_pct,
        )

    def as_dict(self) -> dict:
        return {
            "pytest_available": self.pytest_available,
            "total_coverage_pct": round(self.total_coverage_pct * 100, 1),
            "total_files": len(self.files),
            "danger_zones": len(self.danger_zones),
            "low_coverage_count": len(self.low_coverage_files),
            "error": self.error,
            "files": [
                {
                    "path": f.path,
                    "covered": f.covered_lines,
                    "total": f.total_lines,
                    "coverage_pct": round(f.coverage_pct * 100, 1),
                    "complexity": round(f.complexity, 1),
                    "badge": f.badge,
                }
                for f in sorted(self.files, key=lambda x: x.coverage_pct)[:50]
            ],
        }

    def file_map(self) -> Dict[str, float]:
        """Return {file_path: coverage_pct} for heatmap overlay."""
        return {f.path: f.coverage_pct for f in self.files}


class CoverageRunner:
    """Run pytest with coverage and parse results."""

    def __init__(self, root: Path):
        self.root = root

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        complexity_map: Optional[Dict[str, float]] = None,
        timeout: int = 120,
    ) -> CoverageReport:
        """
        Execute pytest with coverage and return a CoverageReport.

        Args:
            complexity_map: Optional dict of file → avg complexity
                            for danger-zone detection.
            timeout: Max seconds to wait for pytest to complete.
        """
        report = CoverageReport()

        # Check pytest availability
        if not self._pytest_available():
            report.pytest_available = False
            report.error = "pytest not found — install it to enable coverage analysis."
            return report

        with tempfile.TemporaryDirectory() as tmp:
            cov_json = Path(tmp) / "coverage.json"
            ok = self._run_pytest(cov_json, timeout)
            if not ok or not cov_json.exists():
                report.error = "pytest --cov run did not produce coverage.json. Ensure pytest-cov is installed."
                return report

            report = self._parse_coverage(cov_json, complexity_map or {})

        return report

    def parse_existing(
        self,
        coverage_json: Path,
        complexity_map: Optional[Dict[str, float]] = None,
    ) -> CoverageReport:
        """Parse an already-generated coverage.json without re-running pytest."""
        if not coverage_json.exists():
            r = CoverageReport()
            r.error = f"Coverage file not found: {coverage_json}"
            return r
        return self._parse_coverage(coverage_json, complexity_map or {})

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _pytest_available(self) -> bool:
        try:
            result = subprocess.run(
                ["python", "-m", "pytest", "--version"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _run_pytest(self, output_path: Path, timeout: int) -> bool:
        try:
            subprocess.run(
                [
                    "python", "-m", "pytest",
                    "--cov=.",
                    "--cov-report=json:" + str(output_path),
                    "-q", "--tb=no", "--no-header",
                ],
                cwd=self.root,
                capture_output=True,
                timeout=timeout,
            )
            return True
        except subprocess.TimeoutExpired:
            return False
        except Exception:
            return False

    def _parse_coverage(
        self,
        cov_json: Path,
        complexity_map: Dict[str, float],
    ) -> CoverageReport:
        report = CoverageReport()
        try:
            data: Dict[str, Any] = json.loads(cov_json.read_text(encoding="utf-8"))
        except Exception as exc:
            report.error = f"Failed to parse coverage.json: {exc}"
            return report

        totals = data.get("totals", {})
        covered_total = totals.get("covered_lines", 0)
        stmts_total = totals.get("num_statements", 1)
        report.total_coverage_pct = covered_total / max(stmts_total, 1)

        for file_path, file_data in data.get("files", {}).items():
            summary = file_data.get("summary", {})
            covered = summary.get("covered_lines", 0)
            total = summary.get("num_statements", 0)
            pct = covered / max(total, 1)

            # Normalise path to forward slashes for consistent keys
            norm = file_path.replace("\\", "/")

            fc = FileCoverage(
                path=norm,
                covered_lines=covered,
                total_lines=total,
                coverage_pct=pct,
                complexity=complexity_map.get(norm, 0.0),
            )
            report.files.append(fc)

        return report
