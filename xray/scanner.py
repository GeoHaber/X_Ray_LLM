"""
X-Ray Scanner — Pattern-based code analysis engine.
Scans files against the rule database and reports findings.
"""

import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

from .rules import ALL_RULES

# File extensions → language mapping
_EXT_LANG = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "javascript",
    ".html": "html",
    ".htm": "html",
    ".jsx": "javascript",
    ".tsx": "javascript",
    ".rs": "rust",
}

# Directories to always skip
_SKIP_DIRS = {
    "__pycache__",
    "node_modules",
    ".git",
    ".venv",
    "venv",
    "target",
    "dist",
    "build",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "env",
    ".env",
    ".tox",
    "eggs",
    "*.egg-info",
}

# Max file size to scan (1 MB)
_MAX_FILE_SIZE = 1_048_576

# ── String/comment region detection ─────────────────────────────────────
# Pre-compiled regex that matches Python comments and string literals
# (triple-quoted strings, single/double quoted strings, and # comments).
# Used to suppress false positives where a rule pattern matches inside
# a string literal or comment rather than in executable code.
_PY_NON_CODE_RE = re.compile(
    r'"""[\s\S]*?"""|'   # triple-double-quoted string
    r"'''[\s\S]*?'''|"   # triple-single-quoted string
    r'"(?:[^"\\]|\\.)*"|'  # double-quoted string
    r"'(?:[^'\\]|\\.)*'|"  # single-quoted string
    r"#[^\n]*",            # comment
)

# Variant that only matches string literals (NOT comments).
# Used for rules like QUAL-007 (TODO/FIXME) that genuinely belong
# in comments but should be suppressed in pattern-definition strings.
_PY_STRING_ONLY_RE = re.compile(
    r'"""[\s\S]*?"""|'   # triple-double-quoted string
    r"'''[\s\S]*?'''|"   # triple-single-quoted string
    r'"(?:[^"\\]|\\.)*"|'  # double-quoted string
    r"'(?:[^'\\]|\\.)*'",  # single-quoted string
)

# Rules whose matches should be suppressed when they fall inside a
# string literal or comment — these rules are prone to false positives.
_STRING_AWARE_RULES: dict[str, str] = {
    # value = "all" → suppress in strings AND comments
    # value = "strings" → suppress in strings only (not comments)
    "PY-004":   "all",      # print() — mentioned in strings/comments
    "PY-006":   "all",      # global — appears in docstrings
    "PY-007":   "all",      # os.environ[] — appears in help strings
    "QUAL-007": "strings",  # TODO/FIXME — suppress in pattern strings, keep in comments
    "QUAL-010": "all",      # localStorage — appears in test/pattern strings
}


def _build_non_code_ranges(content: str, *, strings_only: bool = False) -> list[tuple[int, int]]:
    """Return sorted list of (start, end) byte ranges that are inside
    string literals or comments in Python source.

    If *strings_only* is True, only string literals are matched (comments
    are kept as code)."""
    regex = _PY_STRING_ONLY_RE if strings_only else _PY_NON_CODE_RE
    return [(m.start(), m.end()) for m in regex.finditer(content)]


def _in_non_code(pos: int, ranges: list[tuple[int, int]]) -> bool:
    """Binary search to check if *pos* falls inside a non-code range."""
    lo, hi = 0, len(ranges) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        start, end = ranges[mid]
        if pos < start:
            hi = mid - 1
        elif pos >= end:
            lo = mid + 1
        else:
            return True
    return False


@dataclass
class Finding:
    """A single issue found by the scanner."""

    rule_id: str
    severity: str
    file: str
    line: int
    col: int
    matched_text: str
    description: str
    fix_hint: str
    test_hint: str

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "file": self.file,
            "line": self.line,
            "col": self.col,
            "matched_text": self.matched_text[:200],
            "description": self.description,
            "fix_hint": self.fix_hint,
            "test_hint": self.test_hint,
        }

    def __str__(self) -> str:
        return f"[{self.severity}] {self.rule_id}: {self.file}:{self.line} — {self.description}"


@dataclass
class ScanResult:
    """Aggregated scan results."""

    findings: list[Finding] = field(default_factory=list)
    files_scanned: int = 0
    rules_checked: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def high_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "HIGH")

    @property
    def medium_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "MEDIUM")

    @property
    def low_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "LOW")

    def summary(self) -> str:
        return (
            f"Scanned {self.files_scanned} files against {self.rules_checked} rules\n"
            f"Findings: {len(self.findings)} total "
            f"({self.high_count} HIGH, {self.medium_count} MEDIUM, {self.low_count} LOW)"
        )


def _detect_lang(filepath: str) -> str | None:
    """Detect language from file extension."""
    ext = os.path.splitext(filepath)[1].lower()
    return _EXT_LANG.get(ext)


def _should_skip(dirpath: str) -> bool:
    """Check if directory should be skipped."""
    basename = os.path.basename(dirpath)
    return basename in _SKIP_DIRS or basename.startswith(".")


def scan_file(filepath: str, rules: list[dict] | None = None) -> list[Finding]:
    """Scan a single file against all applicable rules."""
    lang = _detect_lang(filepath)
    if lang is None:
        return []

    if rules is None:
        rules = ALL_RULES

    applicable = [r for r in rules if lang in r["lang"]]
    if not applicable:
        return []

    try:
        size = os.path.getsize(filepath)
        if size > _MAX_FILE_SIZE:
            return []
        with open(filepath, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except (OSError, PermissionError):
        return []

    findings: list[Finding] = []

    # Build non-code ranges once per file for Python files
    non_code_all: list[tuple[int, int]] | None = None     # strings + comments
    non_code_strings: list[tuple[int, int]] | None = None  # strings only
    if lang == "python":
        non_code_all = _build_non_code_ranges(content)
        non_code_strings = _build_non_code_ranges(content, strings_only=True)

    for rule in applicable:
        try:
            pattern = re.compile(rule["pattern"], re.MULTILINE)
        except re.error:
            continue

        # Determine which non-code range set to use for this rule
        suppression = _STRING_AWARE_RULES.get(rule["id"])
        if suppression == "all" and non_code_all is not None:
            active_ranges = non_code_all
        elif suppression == "strings" and non_code_strings is not None:
            active_ranges = non_code_strings
        else:
            active_ranges = None

        for match in pattern.finditer(content):
            if active_ranges and _in_non_code(match.start(), active_ranges):
                continue

            line_num = content[: match.start()].count("\n") + 1
            line_start = content.rfind("\n", 0, match.start()) + 1
            col = match.start() - line_start + 1

            findings.append(
                Finding(
                    rule_id=rule["id"],
                    severity=rule["severity"],
                    file=filepath,
                    line=line_num,
                    col=col,
                    matched_text=match.group(0),
                    description=rule["description"],
                    fix_hint=rule["fix_hint"],
                    test_hint=rule["test_hint"],
                )
            )

    return findings


def scan_directory(
    root: str,
    rules: list[dict] | None = None,
    exclude_patterns: list[str] | None = None,
    on_progress: Callable | None = None,
) -> ScanResult:
    """Recursively scan a directory for code issues.

    Args:
        on_progress: Optional callback(files_scanned, findings_count, current_file)
    """
    result = ScanResult()
    if rules is None:
        rules = ALL_RULES
    result.rules_checked = len(rules)

    exclude_res = []
    if exclude_patterns:
        for pat in exclude_patterns:
            try:
                exclude_res.append(re.compile(pat))
            except re.error:
                result.errors.append(f"Invalid exclude pattern: {pat}")

    for dirpath, dirnames, filenames in os.walk(root):
        # Skip hidden and generated directories
        dirnames[:] = [d for d in dirnames if not _should_skip(os.path.join(dirpath, d))]

        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            try:
                rel_path = os.path.relpath(filepath, root).replace(os.sep, "/")
            except ValueError:
                # Windows reserved device names (NUL, CON, …) can't be
                # made relative — skip them.
                logger.debug("Skipped non-relative path: %s", filepath)
                continue

            # Check exclude patterns
            if any(r.search(rel_path) for r in exclude_res):
                continue

            lang = _detect_lang(filepath)
            if lang is None:
                continue

            result.files_scanned += 1
            file_findings = scan_file(filepath, rules)
            result.findings.extend(file_findings)

            if on_progress:
                on_progress(result.files_scanned, len(result.findings), rel_path)

    return result


def scan_project(root: str, config: dict | None = None) -> ScanResult:
    """High-level project scan with optional config."""
    exclude = []
    if config:
        exclude = config.get("exclude_patterns", [])
    return scan_directory(root, exclude_patterns=exclude)
