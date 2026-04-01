"""Feedback storage and insight generation for X-Ray review learning loop."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_FEEDBACK_FILE = ".xray_feedback.json"


def _feedback_path(directory: str) -> Path:
    return Path(directory).resolve() / _FEEDBACK_FILE


def _read_feedback(path: Path) -> dict[str, list[dict[str, Any]]]:
    if not path.exists():
        return {"entries": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"entries": []}
    if not isinstance(payload, dict):
        return {"entries": []}
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return {"entries": []}
    return {"entries": entries}


def _write_feedback(path: Path, data: dict[str, list[dict[str, Any]]]) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def record_feedback(directory: str, entry: dict[str, Any]) -> dict[str, Any]:
    """Persist one feedback event for a finding review."""
    path = _feedback_path(directory)
    store = _read_feedback(path)
    verdict = str(entry.get("verdict", "")).lower()
    if verdict not in {"useful", "noisy"}:
        return {"ok": False, "error": "verdict must be useful or noisy"}

    normalized = {
        "rule_id": str(entry.get("rule_id", "UNKNOWN")),
        "file": str(entry.get("file", "")),
        "line": int(entry.get("line", 0) or 0),
        "severity": str(entry.get("severity", "LOW")),
        "verdict": verdict,
        "note": str(entry.get("note", "")).strip(),
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    store["entries"].append(normalized)
    _write_feedback(path, store)
    return {"ok": True, "saved": normalized}


def build_feedback_insights(directory: str) -> dict[str, Any]:
    """Summarize historical review feedback into actionable tuning recommendations."""
    path = _feedback_path(directory)
    store = _read_feedback(path)
    entries: list[dict[str, Any]] = store.get("entries", [])

    by_rule: dict[str, dict[str, int]] = {}
    for e in entries:
        rule_id = str(e.get("rule_id", "UNKNOWN"))
        verdict = str(e.get("verdict", "")).lower()
        if verdict not in {"useful", "noisy"}:
            continue
        row = by_rule.setdefault(rule_id, {"useful": 0, "noisy": 0})
        row[verdict] += 1

    suppress_rules: list[dict[str, Any]] = []
    prioritize_rules: list[dict[str, Any]] = []
    for rule_id, stats in sorted(by_rule.items()):
        useful = stats["useful"]
        noisy = stats["noisy"]
        total = useful + noisy
        if total < 3:
            continue
        noisy_ratio = noisy / total
        useful_ratio = useful / total
        if noisy_ratio >= 0.7:
            suppress_rules.append({
                "rule_id": rule_id,
                "noisy": noisy,
                "useful": useful,
                "ratio": round(noisy_ratio, 2),
            })
        if useful_ratio >= 0.7:
            prioritize_rules.append({
                "rule_id": rule_id,
                "useful": useful,
                "noisy": noisy,
                "ratio": round(useful_ratio, 2),
            })

    yaml_lines = ["xray:"]
    if suppress_rules:
        yaml_lines.append("  suppress:")
        for row in suppress_rules[:10]:
            yaml_lines.append(f"    - rule: {row['rule_id']}")
            yaml_lines.append("      reason: noisy_in_repo_feedback")
    if prioritize_rules:
        yaml_lines.append("  prioritize:")
        for row in prioritize_rules[:10]:
            yaml_lines.append(f"    - rule: {row['rule_id']}")
            yaml_lines.append("      reason: high_signal_in_repo_feedback")

    return {
        "entries": len(entries),
        "by_rule": by_rule,
        "suppress_rules": suppress_rules,
        "prioritize_rules": prioritize_rules,
        "suggested_yaml": "\n".join(yaml_lines),
    }
