"""
Confidence Calibration Engine — Bayesian-inspired confidence scoring.

Combines multiple signals:
  - Rule category base rate (empirical FP rates per rule)
  - AST validation signal (strong positive)
  - Context validation signal (moderate positive)
  - Taint analysis signal (strong positive for injection rules)
  - String/comment proximity (negative — nearby string patterns lower confidence)
  - Test file context (negative — test files have different base rates)
  - File complexity (more complex files → slightly lower confidence)
  - Historical feedback (user-confirmed TP/FP adjusts future scores)
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# Empirical base false-positive rates per rule (from testing against real codebases)
_BASE_FP_RATES: dict[str, float] = {
    "SEC-001": 0.25,   # XSS template literal — many false positives
    "SEC-002": 0.20,   # XSS concatenation
    "SEC-003": 0.15,   # subprocess shell=True
    "SEC-004": 0.30,   # SQL injection — high FP rate
    "SEC-005": 0.35,   # SSRF — very high FP rate
    "SEC-006": 0.10,   # CORS wildcard
    "SEC-007": 0.40,   # eval/exec — extremely high FP rate
    "SEC-008": 0.20,   # Hardcoded secrets
    "SEC-009": 0.15,   # Deserialization
    "SEC-010": 0.30,   # Path traversal
    "QUAL-001": 0.05,  # Bare except — very reliable
    "QUAL-002": 0.10,  # Silent exception
    "QUAL-003": 0.15,  # Unchecked int()
    "QUAL-004": 0.15,  # Unchecked float()
    "QUAL-005": 0.20,  # .items() on None
    "QUAL-006": 0.10,  # Non-daemon thread
    "QUAL-007": 0.05,  # TODO/FIXME — nearly zero FP
    "QUAL-008": 0.10,  # Long sleep
    "QUAL-009": 0.05,  # Keep-alive header
    "QUAL-010": 0.25,  # localStorage
    "PY-001": 0.10,    # Return type mismatch
    "PY-002": 0.20,    # .items() on None return
    "PY-003": 0.05,    # Wildcard import
    "PY-004": 0.30,    # Debug print — high FP
    "PY-005": 0.15,    # JSON parse
    "PY-006": 0.20,    # Global variable
    "PY-007": 0.15,    # environ access
    "PY-008": 0.25,    # open() without encoding
}


@dataclass
class ConfidenceSignals:
    """All signals that feed into confidence calculation."""
    rule_id: str
    used_ast_validator: bool = False
    used_ctx_validator: bool = False
    used_taint: bool = False
    taint_matched: bool | None = None
    is_test_file: bool = False
    in_string_region: bool = False
    file_complexity: float = 0.0   # 0.0 = simple, 1.0 = very complex
    line_count: int = 0
    nearby_sanitizer: bool = False  # sanitizer function found near the match
    historical_tp_rate: float | None = None  # from feedback store


@dataclass
class CalibrationResult:
    """Result of confidence calibration."""
    confidence: float
    breakdown: dict[str, float]
    explanation: str


def calibrate(signals: ConfidenceSignals) -> CalibrationResult:
    """
    Calculate calibrated confidence score from multiple signals.

    Uses a Bayesian-inspired approach:
    1. Start with base rate (1 - FP rate) for the rule
    2. Apply multiplicative adjustments for each signal
    3. Clamp to [0.05, 0.99]
    """
    breakdown: dict[str, float] = {}
    parts: list[str] = []

    # 1. Base rate
    fp_rate = _BASE_FP_RATES.get(signals.rule_id, 0.15)
    base = 1.0 - fp_rate
    breakdown["base_rate"] = base
    parts.append(f"Base confidence for {signals.rule_id}: {base:.2f} (FP rate {fp_rate:.0%})")

    score = base

    # 2. AST validation
    if signals.used_ast_validator:
        factor = 1.15
        score *= factor
        breakdown["ast_validator"] = factor
        parts.append(f"AST validation confirmed: x{factor}")

    # 3. Context validation
    if signals.used_ctx_validator:
        factor = 1.10
        score *= factor
        breakdown["ctx_validator"] = factor
        parts.append(f"Context validation confirmed: x{factor}")

    # 4. Taint analysis (only meaningful for SEC rules)
    if signals.used_taint and signals.taint_matched is not None:
        if signals.taint_matched:
            factor = 1.20
            score *= factor
            breakdown["taint_matched"] = factor
            parts.append(f"Taint flow confirmed: x{factor}")
        else:
            factor = 0.60
            score *= factor
            breakdown["taint_not_matched"] = factor
            parts.append(f"Taint flow NOT confirmed: x{factor}")

    # 5. Test file penalty
    if signals.is_test_file:
        factor = 0.70
        score *= factor
        breakdown["test_file"] = factor
        parts.append(f"Test file context: x{factor}")

    # 6. String region penalty
    if signals.in_string_region:
        factor = 0.40
        score *= factor
        breakdown["string_region"] = factor
        parts.append(f"Inside string/comment region: x{factor}")

    # 7. File complexity adjustment (slight penalty for very complex files)
    if signals.file_complexity > 0.5:
        # Scale: complexity 0.5 → factor 1.0, complexity 1.0 → factor 0.90
        factor = 1.0 - 0.2 * (signals.file_complexity - 0.5)
        factor = max(factor, 0.80)
        score *= factor
        breakdown["file_complexity"] = factor
        parts.append(f"File complexity {signals.file_complexity:.2f}: x{factor:.2f}")

    # 8. Nearby sanitizer
    if signals.nearby_sanitizer:
        factor = 0.50
        score *= factor
        breakdown["nearby_sanitizer"] = factor
        parts.append(f"Sanitizer found nearby: x{factor}")

    # 9. Historical feedback blending
    if signals.historical_tp_rate is not None:
        weight = 0.3
        blended = score * (1.0 - weight) + signals.historical_tp_rate * weight
        breakdown["historical_blend"] = signals.historical_tp_rate
        parts.append(
            f"Historical TP rate {signals.historical_tp_rate:.2f} blended (weight {weight}): "
            f"{score:.3f} -> {blended:.3f}"
        )
        score = blended

    # 10. Clamp
    clamped = max(0.05, min(0.99, score))
    if clamped != score:
        parts.append(f"Clamped {score:.3f} -> {clamped:.3f}")
    score = clamped

    breakdown["final"] = score
    explanation = "; ".join(parts)

    return CalibrationResult(
        confidence=round(score, 4),
        breakdown=breakdown,
        explanation=explanation,
    )


class FeedbackStore:
    """
    Persistent store for user-confirmed true/false positive feedback.
    Used to improve future confidence scores via historical_tp_rate.
    """

    def __init__(self, path: str = ".xray_feedback.json"):
        self._path = Path(path)
        # rule_id -> list of {"file": str, "line": int, "is_tp": bool}
        self._data: dict[str, list[dict]] = {}
        self.load()

    # ── public API ─────────────────────────────────────────────────────

    def record(self, rule_id: str, file: str, line: int, is_tp: bool) -> None:
        """Record user feedback on a finding."""
        self._data.setdefault(rule_id, []).append(
            {"file": file, "line": line, "is_tp": is_tp}
        )
        log.debug("Recorded feedback for %s in %s:%d — TP=%s", rule_id, file, line, is_tp)
        self.save()

    def tp_rate(self, rule_id: str) -> float | None:
        """
        Get historical true-positive rate for a rule.
        Returns None if fewer than 3 data points (insufficient data).
        """
        entries = self._data.get(rule_id, [])
        if len(entries) < 3:
            return None
        tp_count = sum(1 for e in entries if e["is_tp"])
        return tp_count / len(entries)

    # ── persistence ────────────────────────────────────────────────────

    def save(self) -> None:
        """Persist feedback data to disk."""
        try:
            self._path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        except OSError as exc:
            log.warning("Failed to save feedback store to %s: %s", self._path, exc)

    def load(self) -> None:
        """Load feedback data from disk (silently starts empty if missing)."""
        if self._path.is_file():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
                log.debug("Loaded %d rules from feedback store", len(self._data))
            except (json.JSONDecodeError, OSError) as exc:
                log.warning("Failed to load feedback store from %s: %s", self._path, exc)
                self._data = {}
        else:
            self._data = {}

    # ── helpers ─────────────────────────────────────────────────────────

    @property
    def stats(self) -> dict:
        """Summary statistics."""
        total = sum(len(v) for v in self._data.values())
        tp = sum(1 for entries in self._data.values() for e in entries if e["is_tp"])
        return {
            "total_feedback": total,
            "true_positives": tp,
            "false_positives": total - tp,
            "rules_with_feedback": len(self._data),
        }
