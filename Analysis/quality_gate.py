"""
Analysis/quality_gate.py — Quality Gate / CI Pass-Fail (v8.0)
=============================================================

Evaluates a completed X-Ray scan against user-defined thresholds and
returns a structured PASS / FAIL result suitable for CI pipeline
consumption via ``xray_gate_result.json``.

Default threshold configuration (written to ``xray_settings.json`` if
the ``gate`` key is missing)::

    {
      "gate": {
        "min_score": 70,
        "max_critical_smells": 0,
        "max_critical_security": 0,
        "max_debt_hours": 80,
        "max_duplicate_groups": 20
      }
    }

Usage::

    from Analysis.quality_gate import QualityGate
    gate = QualityGate(settings_path=Path("xray_settings.json"))
    result = gate.evaluate(scan_results, satd_summary)
    print("PASSED" if result.passed else "FAILED")
    result.write_json(Path("xray_gate_result.json"))
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

_DEFAULT_GATE: Dict[str, Any] = {
    "min_score": 70,
    "max_critical_smells": 0,
    "max_critical_security": 0,
    "max_debt_hours": 80,
    "max_duplicate_groups": 20,
}


@dataclass
class GateViolation:
    """One rule that failed a gate check."""

    rule: str
    expected: Any
    actual: Any
    message: str


@dataclass
class GateResult:
    """Full quality gate evaluation result."""

    passed: bool
    score: float
    grade: str
    violations: List[GateViolation] = field(default_factory=list)
    thresholds: Dict[str, Any] = field(default_factory=dict)

    @property
    def badge(self) -> str:
        return "✅ PASSED" if self.passed else "❌ FAILED"

    @property
    def violation_messages(self) -> List[str]:
        return [v.message for v in self.violations]

    def as_dict(self) -> dict:
        return {
            "passed": self.passed,
            "badge": self.badge,
            "score": self.score,
            "grade": self.grade,
            "violations": [
                {
                    "rule": v.rule,
                    "expected": v.expected,
                    "actual": v.actual,
                    "message": v.message,
                }
                for v in self.violations
            ],
            "thresholds": self.thresholds,
        }

    def write_json(self, path: Path) -> None:
        """Write gate result to *path* for CI consumption."""
        path.write_text(
            json.dumps(self.as_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


class QualityGate:
    """Evaluate scan results against configurable thresholds."""

    def __init__(self, settings_path: Optional[Path] = None):
        self._settings_path = settings_path or Path("xray_settings.json")
        self._thresholds = self._load_thresholds()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        results: Dict[str, Any],
        satd_summary: Optional[Any] = None,
    ) -> GateResult:
        """
        Evaluate *results* against gate thresholds.

        Args:
            results: The full X-Ray scan result dict.
            satd_summary: Optional SATDSummary object (from Analysis.satd).
        """
        grade_data = results.get("grade", {})
        score = float(grade_data.get("score", 0))
        letter = grade_data.get("letter", "?")

        th = self._thresholds
        violations: List[GateViolation] = []

        # ── Rule: minimum quality score ───────────────────────────────
        min_score = th.get("min_score", 70)
        if score < min_score:
            violations.append(
                GateViolation(
                    rule="min_score",
                    expected=f">= {min_score}",
                    actual=round(score, 1),
                    message=f"Score {score:.1f} is below minimum {min_score}",
                )
            )

        # ── Rule: no critical smells ──────────────────────────────────
        max_crit_smells = th.get("max_critical_smells", 0)
        crit_smells = results.get("smells", {}).get("critical", 0)
        if crit_smells > max_crit_smells:
            violations.append(
                GateViolation(
                    rule="max_critical_smells",
                    expected=f"<= {max_crit_smells}",
                    actual=crit_smells,
                    message=f"{crit_smells} critical smell(s) found (max {max_crit_smells})",
                )
            )

        # ── Rule: no critical security issues ─────────────────────────
        max_crit_sec = th.get("max_critical_security", 0)
        crit_sec = results.get("security", {}).get("critical", 0)
        if crit_sec > max_crit_sec:
            violations.append(
                GateViolation(
                    rule="max_critical_security",
                    expected=f"<= {max_crit_sec}",
                    actual=crit_sec,
                    message=f"{crit_sec} critical security issue(s) found (max {max_crit_sec})",
                )
            )

        # ── Rule: max duplicate groups ────────────────────────────────
        max_dups = th.get("max_duplicate_groups", 20)
        dup_groups = results.get("duplicates", {}).get("total_groups", 0)
        if dup_groups > max_dups:
            violations.append(
                GateViolation(
                    rule="max_duplicate_groups",
                    expected=f"<= {max_dups}",
                    actual=dup_groups,
                    message=f"{dup_groups} duplicate groups found (max {max_dups})",
                )
            )

        # ── Rule: max SATD debt hours ─────────────────────────────────
        if satd_summary is not None:
            max_debt = th.get("max_debt_hours", 80)
            debt_hours = getattr(satd_summary, "total_hours", 0)
            if debt_hours > max_debt:
                violations.append(
                    GateViolation(
                        rule="max_debt_hours",
                        expected=f"<= {max_debt}h",
                        actual=f"{debt_hours}h",
                        message=f"SATD debt hours {debt_hours}h exceed maximum {max_debt}h",
                    )
                )

        return GateResult(
            passed=len(violations) == 0,
            score=round(score, 1),
            grade=letter,
            violations=violations,
            thresholds=th,
        )

    # ------------------------------------------------------------------
    # Settings helpers
    # ------------------------------------------------------------------

    def _load_thresholds(self) -> Dict[str, Any]:
        """Load gate thresholds from settings file, writing defaults if missing."""
        try:
            raw = json.loads(self._settings_path.read_text(encoding="utf-8"))
        except Exception:
            raw = {}

        if "gate" not in raw:
            raw["gate"] = _DEFAULT_GATE
            try:
                self._settings_path.write_text(
                    json.dumps(raw, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
            except Exception:
                pass

        return raw.get("gate", _DEFAULT_GATE)

    def update_thresholds(self, new_thresholds: Dict[str, Any]) -> None:
        """Persist updated thresholds to the settings file."""
        self._thresholds.update(new_thresholds)
        try:
            raw = json.loads(self._settings_path.read_text(encoding="utf-8"))
        except Exception:
            raw = {}
        raw["gate"] = self._thresholds
        self._settings_path.write_text(
            json.dumps(raw, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
