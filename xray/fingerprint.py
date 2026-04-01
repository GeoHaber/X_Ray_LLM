"""
Fix Fingerprinting — Track which findings have been fixed across code changes.

A fix fingerprint is a stable identifier for a finding that survives:
  - Line number changes (code added/removed above)
  - Minor whitespace changes
  - Variable renaming (partial)
  - File moves within the same project

The fingerprint is based on:
  1. Rule ID (stable)
  2. Surrounding code context hash (5 lines before + after, normalized)
  3. Function/class scope name (if available)
  4. Relative position within scope (1st, 2nd, 3rd occurrence)
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Regex patterns for detecting enclosing scope (function or class)
_FUNC_RE = re.compile(r"^\s*(?:async\s+)?def\s+(\w+)\s*\(")
_CLASS_RE = re.compile(r"^\s*class\s+(\w+)\s*[\(:]")

# Patterns stripped during normalization (comments, extra whitespace)
_COMMENT_RE = re.compile(r"#[^\n]*")
_MULTILINE_STR_RE = re.compile(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'')


@dataclass
class FixFingerprint:
    """Stable identifier for a finding that survives code changes."""
    rule_id: str
    context_hash: str       # SHA256 of normalized surrounding code
    scope_name: str          # enclosing function/class name
    scope_occurrence: int    # nth occurrence within scope
    file_stem: str           # filename without path (for move detection)

    @property
    def key(self) -> str:
        return f"{self.rule_id}:{self.context_hash[:12]}:{self.scope_name}:{self.scope_occurrence}"

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "context_hash": self.context_hash,
            "scope_name": self.scope_name,
            "scope_occurrence": self.scope_occurrence,
            "file_stem": self.file_stem,
        }

    @staticmethod
    def from_dict(d: dict) -> "FixFingerprint":
        return FixFingerprint(
            rule_id=d["rule_id"],
            context_hash=d["context_hash"],
            scope_name=d["scope_name"],
            scope_occurrence=d["scope_occurrence"],
            file_stem=d["file_stem"],
        )


def _normalize_line(line: str) -> str:
    """Normalize a single line: strip whitespace, remove comments, lowercase."""
    line = _COMMENT_RE.sub("", line)
    line = line.strip().lower()
    # Collapse multiple spaces
    line = re.sub(r"\s+", " ", line)
    return line


def _find_scope(lines: list[str], target_line: int) -> str:
    """
    Walk backwards from target_line to find the enclosing function or class name.
    Returns the name, or '<module>' if at module level.
    """
    for i in range(target_line - 1, -1, -1):
        raw = lines[i]
        m = _FUNC_RE.match(raw)
        if m:
            return m.group(1)
        m = _CLASS_RE.match(raw)
        if m:
            return m.group(1)
    return "<module>"


def _count_scope_occurrence(
    lines: list[str],
    scope_start: int,
    target_line: int,
    rule_id: str,
) -> int:
    """
    Count how many findings with the same rule_id appear in this scope
    before (and including) target_line. This gives the 'nth occurrence' value.

    This is a heuristic: we cannot re-run rule matching here, so we count
    lines between scope_start and target_line that look similar to the
    target line (same normalized content).
    """
    target_normalized = _normalize_line(lines[target_line] if target_line < len(lines) else "")
    count = 0
    for i in range(scope_start, min(target_line + 1, len(lines))):
        if _normalize_line(lines[i]) == target_normalized:
            count += 1
    return max(count, 1)


def compute_fingerprint(
    rule_id: str,
    filepath: str,
    line: int,
    content: str,
    context_lines: int = 5,
) -> FixFingerprint:
    """
    Compute a stable fingerprint for a finding.

    Args:
        rule_id: The rule that produced the finding.
        filepath: Path to the file containing the finding.
        line: 1-based line number of the finding.
        content: Full file content.
        context_lines: Number of lines before/after to include in context hash.

    Returns:
        A FixFingerprint with a stable hash.
    """
    lines = content.splitlines()
    idx = line - 1  # convert to 0-based

    # Extract context window
    start = max(0, idx - context_lines)
    end = min(len(lines), idx + context_lines + 1)
    context_raw = lines[start:end]

    # Normalize each line and join for hashing
    normalized = [_normalize_line(ln) for ln in context_raw]
    # Remove empty lines from normalized to tolerate blank-line changes
    normalized = [ln for ln in normalized if ln]
    context_str = "\n".join(normalized)

    context_hash = hashlib.sha256(context_str.encode("utf-8")).hexdigest()

    # Find enclosing scope
    scope_name = _find_scope(lines, idx)

    # Find scope start line for occurrence counting
    scope_start = 0
    for i in range(idx - 1, -1, -1):
        if _FUNC_RE.match(lines[i]) or _CLASS_RE.match(lines[i]):
            scope_start = i
            break

    scope_occurrence = _count_scope_occurrence(lines, scope_start, idx, rule_id)

    file_stem = Path(filepath).stem

    return FixFingerprint(
        rule_id=rule_id,
        context_hash=context_hash,
        scope_name=scope_name,
        scope_occurrence=scope_occurrence,
        file_stem=file_stem,
    )


@dataclass
class FixRecord:
    """Record of a fix that was applied."""
    fingerprint: FixFingerprint
    fix_description: str
    fix_diff: str
    applied_at: str   # ISO timestamp
    applied_by: str   # "auto" | "manual" | "llm"
    verified: bool = False

    def to_dict(self) -> dict:
        return {
            "fingerprint": self.fingerprint.to_dict(),
            "fix_description": self.fix_description,
            "fix_diff": self.fix_diff,
            "applied_at": self.applied_at,
            "applied_by": self.applied_by,
            "verified": self.verified,
        }

    @staticmethod
    def from_dict(d: dict) -> "FixRecord":
        return FixRecord(
            fingerprint=FixFingerprint.from_dict(d["fingerprint"]),
            fix_description=d["fix_description"],
            fix_diff=d["fix_diff"],
            applied_at=d["applied_at"],
            applied_by=d["applied_by"],
            verified=d.get("verified", False),
        )


class FixTracker:
    """
    Track fixes across code changes.

    Answers questions like:
    - "Has this finding been fixed before?"
    - "Did a previous fix regress?"
    - "Which findings are new since the last fix batch?"
    """

    def __init__(self, store_path: str = ".xray_fixes.json"):
        self._path = Path(store_path)
        # key (fingerprint.key) -> FixRecord
        self._fixes: dict[str, FixRecord] = {}
        self._regressions_detected: int = 0
        self.load()

    # ── public API ─────────────────────────────────────────────────────

    def record_fix(
        self, finding_dict: dict, content: str, fix_result: dict
    ) -> FixFingerprint:
        """
        Record that a fix was applied for a finding.

        Args:
            finding_dict: The original finding (must have rule_id, file, line).
            content: The file content *before* the fix.
            fix_result: Dict with at least 'description' and optionally 'diff'.

        Returns:
            The computed fingerprint.
        """
        fp = compute_fingerprint(
            rule_id=finding_dict["rule_id"],
            filepath=finding_dict["file"],
            line=finding_dict["line"],
            content=content,
        )

        record = FixRecord(
            fingerprint=fp,
            fix_description=fix_result.get("description", ""),
            fix_diff=fix_result.get("diff", ""),
            applied_at=datetime.now(timezone.utc).isoformat(),
            applied_by=fix_result.get("applied_by", "auto"),
            verified=fix_result.get("verified", False),
        )

        self._fixes[fp.key] = record
        self.save()
        return fp

    def is_previously_fixed(self, finding_dict: dict, content: str) -> bool:
        """Check if a finding matches a previously fixed fingerprint."""
        fp = compute_fingerprint(
            rule_id=finding_dict["rule_id"],
            filepath=finding_dict["file"],
            line=finding_dict["line"],
            content=content,
        )
        return fp.key in self._fixes

    def detect_regressions(
        self, findings: list[dict], contents: dict[str, str]
    ) -> list[dict]:
        """
        Find findings that match previously-fixed fingerprints (regressions).

        Args:
            findings: List of current finding dicts (rule_id, file, line).
            contents: Map of filepath -> file content for all scanned files.

        Returns:
            List of finding dicts that are regressions, each augmented with
            a 'regression_info' key containing the original fix record.
        """
        regressions: list[dict] = []
        for finding in findings:
            filepath = finding.get("file", "")
            content = contents.get(filepath, "")
            if not content:
                continue

            fp = compute_fingerprint(
                rule_id=finding["rule_id"],
                filepath=filepath,
                line=finding["line"],
                content=content,
            )

            if fp.key in self._fixes:
                previous = self._fixes[fp.key]
                augmented = dict(finding)
                augmented["regression_info"] = {
                    "originally_fixed_at": previous.applied_at,
                    "original_fix_description": previous.fix_description,
                    "applied_by": previous.applied_by,
                    "fingerprint_key": fp.key,
                }
                regressions.append(augmented)

        self._regressions_detected += len(regressions)
        return regressions

    # ── persistence ────────────────────────────────────────────────────

    def save(self) -> None:
        """Persist fix records to disk."""
        data = {key: rec.to_dict() for key, rec in self._fixes.items()}
        try:
            self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass

    def load(self) -> None:
        """Load fix records from disk."""
        if self._path.is_file():
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                self._fixes = {
                    key: FixRecord.from_dict(val) for key, val in raw.items()
                }
            except (json.JSONDecodeError, OSError, KeyError):
                self._fixes = {}
        else:
            self._fixes = {}

    # ── stats ──────────────────────────────────────────────────────────

    @property
    def stats(self) -> dict:
        """Return stats: total fixes, regressions detected, etc."""
        verified = sum(1 for r in self._fixes.values() if r.verified)
        by_method: dict[str, int] = {}
        for r in self._fixes.values():
            by_method[r.applied_by] = by_method.get(r.applied_by, 0) + 1

        return {
            "total_fixes": len(self._fixes),
            "verified_fixes": verified,
            "regressions_detected": self._regressions_detected,
            "fixes_by_method": by_method,
        }
