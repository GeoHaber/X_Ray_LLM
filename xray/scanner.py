"""
X-Ray Scanner — Pattern-based code analysis engine.
Scans files against the rule database and reports findings.
"""

import ast
import hashlib
import json
import logging
import os
import re
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from xray.constants import SKIP_DIRS as _SKIP_DIRS

from .rules import ALL_RULES

logger = logging.getLogger(__name__)

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

# Max file size to scan (1 MB)
_MAX_FILE_SIZE = 1_048_576

# ── String/comment region detection ─────────────────────────────────────
# Pre-compiled regex that matches Python comments and string literals
# (triple-quoted strings, single/double quoted strings, and # comments).
# Used to suppress false positives where a rule pattern matches inside
# a string literal or comment rather than in executable code.
_PY_NON_CODE_RE = re.compile(
    r'"""[\s\S]*?"""|'  # triple-double-quoted string
    r"'''[\s\S]*?'''|"  # triple-single-quoted string
    r'"(?:[^"\\]|\\.)*"|'  # double-quoted string
    r"'(?:[^'\\]|\\.)*'|"  # single-quoted string
    r"#[^\n]*",  # comment
)

# Variant that only matches string literals (NOT comments).
# Used for rules like QUAL-007 (TODO/FIXME) that genuinely belong
# in comments but should be suppressed in pattern-definition strings.
_PY_STRING_ONLY_RE = re.compile(
    r'"""[\s\S]*?"""|'  # triple-double-quoted string
    r"'''[\s\S]*?'''|"  # triple-single-quoted string
    r'"(?:[^"\\]|\\.)*"|'  # double-quoted string
    r"'(?:[^'\\]|\\.)*'",  # single-quoted string
)

# Rules whose matches should be suppressed when they fall inside a
# string literal or comment — these rules are prone to false positives.
_STRING_AWARE_RULES: dict[str, str] = {
    # value = "all" → suppress in strings AND comments
    # value = "strings" → suppress in strings only (not comments)
    "PY-004": "all",  # print() — mentioned in strings/comments
    "PY-006": "all",  # global — appears in docstrings
    "PY-007": "all",  # os.environ[] — appears in help strings
    "SEC-007": "all",  # eval/exec — appears in comments explaining checks
    "QUAL-007": "strings",  # TODO/FIXME — suppress in pattern strings, keep in comments
    "QUAL-010": "all",  # localStorage — appears in test/pattern strings
}

# ── Pre-compiled regex cache ────────────────────────────────────────────
_COMPILED_CACHE: dict[str, re.Pattern | None] = {}


def _get_compiled(pattern: str) -> re.Pattern | None:
    """Return a compiled regex, caching results. Returns None on bad patterns."""
    if pattern not in _COMPILED_CACHE:
        try:
            _COMPILED_CACHE[pattern] = re.compile(pattern, re.MULTILINE)
        except re.error:
            _COMPILED_CACHE[pattern] = None
    return _COMPILED_CACHE[pattern]


# ── AST-based validation ────────────────────────────────────────────────
# Post-regex validators that reduce false positives by inspecting the AST.
# Each validator takes (filepath, content, line_num, ast_tree) and returns
# True if the finding is a TRUE positive (should be kept).


def _ast_validate_py001(filepath: str, content: str, line_num: int, tree: ast.AST) -> bool:
    """PY-001: 'def X() -> None' — only flag if the function actually returns
    a non-None value (a real type mismatch)."""
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.lineno != line_num:
            continue
        # Check if the function body has a return with a non-None value
        for child in ast.walk(node):
            if isinstance(child, ast.Return) and child.value is not None:
                # Return of None literal is okay for -> None
                if isinstance(child.value, ast.Constant) and child.value.value is None:
                    continue
                return True  # Real mismatch: returns non-None value
        return False  # No non-None return — annotation is correct
    return True  # Not found in AST, keep the finding as-is


def _ast_validate_py005(filepath: str, content: str, line_num: int, tree: ast.AST) -> bool:
    """PY-005: 'json.loads/load(...)' — suppress if the call is inside a
    try/except block that catches JSONDecodeError or a broad exception."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        # Check if the json call line falls within this try block
        try_start = node.lineno
        # The try body ends at the first handler
        try_end = node.handlers[0].lineno if node.handlers else node.end_lineno or try_start
        if try_start <= line_num < try_end:
            # Check if any handler catches JSONDecodeError or broad exception
            for handler in node.handlers:
                if handler.type is None:
                    return False  # bare except: — json is handled
                if isinstance(handler.type, ast.Name) and handler.type.id in (
                    "Exception",
                    "BaseException",
                    "JSONDecodeError",
                    "ValueError",
                ):
                    return False  # properly handled
                if isinstance(handler.type, ast.Attribute) and handler.type.attr in (
                    "JSONDecodeError",
                    "JSONError",
                ):
                    return False
                if isinstance(handler.type, ast.Tuple):
                    for elt in handler.type.elts:
                        name = getattr(elt, "id", getattr(elt, "attr", ""))
                        if name in ("Exception", "BaseException", "JSONDecodeError", "ValueError"):
                            return False
    return True  # Not inside a try — valid finding


def _ast_validate_py006(filepath: str, content: str, line_num: int, tree: ast.AST) -> bool:
    """PY-006: 'global X' — suppress if it appears at module level (no-op)
    rather than inside a function."""
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.lineno <= line_num <= (node.end_lineno or node.lineno + 1000):
            # Inside a function — legitimate global usage
            return True
    return False  # At module level — no-op, suppress


def _ast_validate_qual003(filepath: str, content: str, line_num: int, tree: ast.AST) -> bool:
    """QUAL-003: 'int(user_input)' — suppress if the call is inside a
    try/except block that catches ValueError, TypeError, or a broad exception."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        try_start = node.lineno
        try_end = node.handlers[0].lineno if node.handlers else node.end_lineno or try_start
        if try_start <= line_num < try_end:
            for handler in node.handlers:
                if handler.type is None:
                    return False  # bare except
                if isinstance(handler.type, ast.Name) and handler.type.id in (
                    "Exception",
                    "BaseException",
                    "ValueError",
                    "TypeError",
                ):
                    return False
                if isinstance(handler.type, ast.Tuple):
                    for elt in handler.type.elts:
                        name = getattr(elt, "id", getattr(elt, "attr", ""))
                        if name in ("Exception", "BaseException", "ValueError", "TypeError"):
                            return False
    return True  # Not inside a try — valid finding


def _ast_validate_qual004(filepath: str, content: str, line_num: int, tree: ast.AST) -> bool:
    """QUAL-004: 'float(user_input)' — suppress if the call is inside a
    try/except block that catches ValueError, TypeError, or a broad exception.
    Also suppress if the argument comes from argparse (args.X) where
    add_argument(type=float) already validates the value."""
    lines = content.splitlines()
    if 0 < line_num <= len(lines):
        line_text = lines[line_num - 1]
        # argparse already validates: float(args.X) is redundant but safe
        if re.search(r"float\(\s*args\.\w+", line_text):
            return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        try_start = node.lineno
        try_end = node.handlers[0].lineno if node.handlers else node.end_lineno or try_start
        if try_start <= line_num < try_end:
            for handler in node.handlers:
                if handler.type is None:
                    return False  # bare except
                if isinstance(handler.type, ast.Name) and handler.type.id in (
                    "Exception",
                    "BaseException",
                    "ValueError",
                    "TypeError",
                ):
                    return False
                if isinstance(handler.type, ast.Tuple):
                    for elt in handler.type.elts:
                        name = getattr(elt, "id", getattr(elt, "attr", ""))
                        if name in ("Exception", "BaseException", "ValueError", "TypeError"):
                            return False
    return True  # Not inside a try — valid finding


def _ast_validate_py008(filepath: str, content: str, line_num: int, tree: ast.AST) -> bool:
    """PY-008: open() without encoding — suppress for:
    - Binary mode ('rb', 'wb', 'ab', etc.)
    - Already has encoding= keyword
    - Not a builtin open() (e.g. Image.open(), zipfile.open(), tarfile.open())
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if node.lineno != line_num:
            continue
        # Only flag builtin open(), not method calls like Image.open()
        if isinstance(node.func, ast.Attribute):
            return False  # method call: obj.open() — not builtin
        if isinstance(node.func, ast.Name) and node.func.id == "open":
            # Check if encoding= is in keyword arguments
            for kw in node.keywords:
                if kw.arg == "encoding":
                    return False  # already specified
            # Check if mode argument indicates binary
            if len(node.args) >= 2:
                mode_arg = node.args[1]
                if isinstance(mode_arg, ast.Constant) and isinstance(mode_arg.value, str):
                    if "b" in mode_arg.value:
                        return False  # binary mode
            for kw in node.keywords:
                if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                    if isinstance(kw.value.value, str) and "b" in kw.value.value:
                        return False  # binary mode via keyword
            return True  # builtin open() without encoding or binary — real finding
    return True  # line not matched in AST, keep finding


def _ast_validate_py007(filepath: str, content: str, line_num: int, tree: ast.AST) -> bool:
    """PY-007: os.environ[] direct access — suppress if:
    - Inside a try/except (KeyError or broader)
    - The access is os.environ['KEY'] = value (setting, not getting)
    - Inside a test file (test setup commonly manipulates env directly)
    - Preceded by a .get() guard on the same variable
    """
    # Test files legitimately set/get env vars for test setup
    basename = os.path.basename(filepath)
    if basename.startswith("test_") or basename.endswith("_test.py"):
        return False

    lines = content.splitlines()
    if 0 < line_num <= len(lines):
        line_text = lines[line_num - 1].strip()
        # Setting env vars is fine: os.environ['KEY'] = value
        if re.search(r"os\.environ\[[^\]]+\]\s*=", line_text):
            return False
        # Deleting env vars: del os.environ['KEY'] or .pop()
        if line_text.startswith("del ") or ".pop(" in line_text:
            return False

    # Check if inside try/except KeyError
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        try_start = node.lineno
        try_end = node.handlers[0].lineno if node.handlers else node.end_lineno or try_start
        if try_start <= line_num < try_end:
            for handler in node.handlers:
                if handler.type is None:
                    return False  # bare except
                if isinstance(handler.type, ast.Name) and handler.type.id in (
                    "Exception", "BaseException", "KeyError", "OSError",
                ):
                    return False
                if isinstance(handler.type, ast.Tuple):
                    for elt in handler.type.elts:
                        name = getattr(elt, "id", getattr(elt, "attr", ""))
                        if name in ("Exception", "BaseException", "KeyError"):
                            return False
    return True  # unguarded access — valid finding


def _validate_sec004(filepath: str, content: str, line_num: int, tree: ast.AST | None) -> bool:
    """SEC-004: SQL injection — suppress if:
    - The %s is a proper parameterized placeholder with a separate params tuple
      (e.g., cursor.execute("SELECT * FROM t WHERE id = %s", (val,)))
    - Table name is validated against an allowlist before interpolation
    - Table name comes from a hardcoded tuple/set of known table names
    - Table name is regex-validated before use in f-string
    """
    lines = content.splitlines()
    if 0 < line_num <= len(lines):
        line_text = lines[line_num - 1]
        # Detect proper parameterized query: execute("...%s...", (params,))
        # The key signal is: %s in the SQL string AND a second argument (params tuple)
        if re.search(r"execute\(\s*['\"][^'\"]*%s[^'\"]*['\"],\s*[\[(]", line_text):
            return False  # proper parameterized query with params argument
        if re.search(r"execute\(\s*['\"][^'\"]*%s[^'\"]*['\"],\s*\w+", line_text):
            return False  # params passed as variable
        # Multi-line: check next few lines for the params argument
        for offset in range(1, 4):
            if line_num + offset <= len(lines):
                next_line = lines[line_num + offset - 1].strip()
                if re.search(r"^\s*[\[(]", next_line) or re.search(r",\s*[\[(]", next_line):
                    return False

        # Check for f-string with table name from hardcoded source or validated
        # Look backwards for: the variable being iterated from a tuple/set of strings,
        # or a regex validation of the table name
        if re.search(r"execute\(\s*f['\"]", line_text):
            # Find the interpolated variable name (e.g., {t} or {name})
            var_match = re.search(r"\{(\w+)\}", line_text)
            if var_match:
                var_name = var_match.group(1)
                # Search backwards for hardcoded source or validation
                for i in range(line_num - 2, max(line_num - 20, -1), -1):
                    if i < 0 or i >= len(lines):
                        continue
                    prev = lines[i]
                    # Iteration over hardcoded tuple/set: for x in ("a", "b")
                    if re.search(rf"\bfor\s+{re.escape(var_name)}\s+in\s+[\(\[{{]", prev):
                        return False
                    # Allowlist check: if x not in ALLOWED or if x in ALLOWED
                    if re.search(rf"\b{re.escape(var_name)}\b.*\bnot\s+in\s+\w*[Aa]llow", prev):
                        return False
                    if re.search(rf"\b{re.escape(var_name)}\b.*\bin\s+\w*[Aa]llow", prev):
                        return False
                    # Regex validation: re.match(r"...", name)
                    if re.search(rf"re\.match\(.*{re.escape(var_name)}", prev):
                        return False
    return True  # likely real SQL injection


def _validate_sec005(filepath: str, content: str, line_num: int, tree: ast.AST | None) -> bool:
    """SEC-005: SSRF — suppress if:
    - File is in a tests/ directory (test files legitimately hit local servers)
    - URL is constructed from constants or config, not user input
    """
    # Test files hitting localhost are normal
    norm = filepath.replace(os.sep, "/")
    if "/tests/" in norm or "/test_" in os.path.basename(filepath):
        return False

    lines = content.splitlines()
    if 0 < line_num <= len(lines):
        line_text = lines[line_num - 1]
        # Hardcoded localhost URLs are not SSRF
        if re.search(r"(localhost|127\.0\.0\.1|0\.0\.0\.0)", line_text):
            return False
        # URL with scheme allowlist comment
        if "allowlist" in line_text.lower() or "noqa" in line_text.lower():
            return False
    return True  # potential SSRF


# Map rule IDs to their AST validators
_AST_VALIDATORS: dict[str, Callable] = {
    "PY-001": _ast_validate_py001,
    "PY-005": _ast_validate_py005,
    "PY-006": _ast_validate_py006,
    "PY-007": _ast_validate_py007,
    "PY-008": _ast_validate_py008,
    "QUAL-003": _ast_validate_qual003,
    "QUAL-004": _ast_validate_qual004,
}

# ── Context validators (no AST required — work for any language) ────────
# Each takes (filepath, content, line_num) and returns True if finding is valid.


def _ctx_validate_sec004(filepath: str, content: str, line_num: int) -> bool:
    """SEC-004 context validator wrapper (delegates to the function above)."""
    return _validate_sec004(filepath, content, line_num, None)


def _ctx_validate_sec005(filepath: str, content: str, line_num: int) -> bool:
    """SEC-005 context validator wrapper."""
    return _validate_sec005(filepath, content, line_num, None)


def _ctx_validate_sec001(filepath: str, content: str, line_num: int) -> bool:
    """SEC-001: XSS via template literal — suppress if the innerHTML
    assignment's template literal uses sanitizer functions on all dynamic values."""
    lines = content.splitlines()
    if 0 < line_num <= len(lines):
        sanitizers = ("escHtml", "_escHtml", "escapeHtml", "sanitize", "DOMPurify", "textContent")
        # Check the innerHTML line and the next ~20 lines for template content
        block = "\n".join(lines[line_num - 1 : min(line_num + 20, len(lines))])
        # If the template block uses sanitizers, assume it's handled
        if any(s in block for s in sanitizers):
            return False
    return True


def _ctx_validate_sec002(filepath: str, content: str, line_num: int) -> bool:
    """SEC-002: XSS via string concatenation — suppress if line or nearby
    lines use sanitizer functions, or if this is inside a sanitized block."""
    lines = content.splitlines()
    if 0 < line_num <= len(lines):
        sanitizers = ("escHtml", "_escHtml", "escapeHtml", "sanitize", "DOMPurify", "textContent")
        # Check a wider window around the match for sanitizers
        start = max(0, line_num - 6)
        end = min(line_num + 15, len(lines))
        block = "\n".join(lines[start:end])
        if any(s in block for s in sanitizers):
            return False
    return True


def _ctx_validate_sec007(filepath: str, content: str, line_num: int) -> bool:
    """SEC-007: eval/exec — suppress if:
    - Inside a test file that is *checking* for eval/exec (meta-test)
    - The eval/exec is page.evaluate() (Playwright JS context, not Python eval)
    - Function name is ast.literal_eval or json.loads (safe alternatives)
    - JavaScript RegExp .exec() method
    - eval/exec appears inside a regex pattern or string literal being searched
    """
    basename = os.path.basename(filepath)
    lines = content.splitlines()
    if 0 < line_num <= len(lines):
        line_text = lines[line_num - 1]
        # Playwright page.evaluate() is JS context, not Python eval
        if "page.evaluate" in line_text or "page.eval" in line_text:
            return False
        # ast.literal_eval is safe
        if "literal_eval" in line_text:
            return False
        # JavaScript RegExp .exec() method (e.g., pattern.exec(src))
        if re.search(r"\w+\.exec\(", line_text):
            return False
        # eval/exec inside a regex pattern string (e.g., re.search(r"\beval\s*\("))
        if re.search(r"re\.(search|match|findall|sub)\(.*eval", line_text):
            return False
        # eval/exec inside a quoted string (e.g., pytest.fail("eval() found"))
        if re.search(r"['\"].*\beval\b.*['\"]", line_text) and "eval(" not in line_text.split("'")[0].split('"')[0]:
            return False
        # Test file checking for absence of eval (meta-test assertions)
        if re.search(r"(assert|assert_not|not in|should not).*['\"].*eval", line_text):
            return False
        if re.search(r"['\"].*eval.*['\"].*not in", line_text):
            return False
        # In test files, suppress eval inside string patterns being scanned
        norm = filepath.replace(os.sep, "/")
        if ("/tests/" in norm or basename.startswith("test_") or basename.startswith("test-")):
            # Check if eval/exec is inside a string/regex on this line (r-string or quoted)
            if re.search(r'r?["\'].*\beval\b.*["\']', line_text):
                return False
            # pytest.fail with eval message
            if "pytest.fail" in line_text and "eval" in line_text:
                return False
    return True


def _ctx_validate_qual010(filepath: str, content: str, line_num: int) -> bool:
    """QUAL-010: localStorage access — suppress if the call is inside
    a try/catch block or in a test file."""
    # Test files accessing localStorage are expected in assertions
    basename = os.path.basename(filepath)
    norm = filepath.replace(os.sep, "/")
    if "/tests/" in norm or basename.startswith("test_") or basename.startswith("test-"):
        return False

    lines = content.splitlines()
    if 0 < line_num <= len(lines):
        # Quick same-line check: try{...localStorage...}catch
        line_text = lines[line_num - 1]
        if "try" in line_text and "catch" in line_text:
            return False

    # Search backwards from the match line for a 'try' or 'try{'
    for i in range(line_num - 2, max(line_num - 40, -1), -1):
        if i < 0 or i >= len(lines):
            continue
        line = lines[i].strip()
        if re.search(r"\btry\s*\{?$", line) or line.startswith("try{") or line == "try {":
            # Found a try — verify there's a matching catch downstream
            for j in range(line_num, min(line_num + 40, len(lines))):
                if "catch" in lines[j]:
                    return False  # inside try/catch — false positive
            break
        # If we hit a function/class boundary, stop looking
        if re.search(r"\b(function|class|=>)\b", line) and "{" in line:
            break

    return True  # not inside try/catch — valid finding


_CTX_VALIDATORS: dict[str, Callable[[str, str, int], bool]] = {
    "SEC-001": _ctx_validate_sec001,
    "SEC-002": _ctx_validate_sec002,
    "SEC-004": _ctx_validate_sec004,
    "SEC-005": _ctx_validate_sec005,
    "SEC-007": _ctx_validate_sec007,
    "QUAL-010": _ctx_validate_qual010,
}


# ── Inline suppression parsing ──────────────────────────────────────────
_SUPPRESS_RE = re.compile(r"#\s*xray:\s*ignore\[([^\]]+)\]")


def _parse_suppressions(content: str) -> dict[int, set[str]]:
    """Parse inline ``# xray: ignore[RULE-ID, ...]`` comments.

    Returns a dict mapping 1-based line numbers to sets of suppressed rule IDs.
    """
    suppressions: dict[int, set[str]] = {}
    for i, line in enumerate(content.splitlines(), 1):
        m = _SUPPRESS_RE.search(line)
        if m:
            ids = {rid.strip() for rid in m.group(1).split(",")}
            suppressions[i] = ids
    return suppressions


# ── Incremental scan cache ──────────────────────────────────────────────
class _ScanCache:
    """Simple file-hash cache for incremental scanning."""

    def __init__(self, cache_path: str | None = None):
        self._path = cache_path or ".xray_cache.json"
        self._data: dict[str, str] = {}
        self._load()

    def _load(self):
        try:
            with open(self._path, encoding="utf-8") as f:
                self._data = json.load(f)
        except (OSError, json.JSONDecodeError):
            self._data = {}

    def save(self):
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._data, f)

    def is_changed(self, filepath: str) -> bool:
        """Return True if file changed since last scan."""
        try:
            h = hashlib.sha256(Path(filepath).read_bytes()).hexdigest()
        except OSError:
            return True
        old = self._data.get(filepath)
        self._data[filepath] = h
        return old != h


# ── Baseline / diff filtering ───────────────────────────────────────────
def load_baseline(path: str) -> set[tuple[str, str, int]]:
    """Load a baseline JSON and return a set of (rule_id, file, line) tuples."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return set()
    baseline = set()
    findings = data if isinstance(data, list) else data.get("findings", [])
    for item in findings:
        baseline.add((item.get("rule_id", ""), item.get("file", ""), item.get("line", 0)))
    return baseline


def filter_new_findings(findings: list, baseline: set[tuple[str, str, int]]) -> list:
    """Remove findings that already exist in the baseline."""
    return [f for f in findings if (f.rule_id, f.file, f.line) not in baseline]


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

    @staticmethod
    def from_dict(d: dict) -> "Finding":
        return Finding(
            rule_id=d.get("rule_id", ""),
            severity=d.get("severity", ""),
            file=d.get("file", ""),
            line=d.get("line", 0),
            col=d.get("col", 0),
            matched_text=d.get("matched_text", ""),
            description=d.get("description", ""),
            fix_hint=d.get("fix_hint", ""),
            test_hint=d.get("test_hint", ""),
        )

    def __str__(self) -> str:
        return f"[{self.severity}] {self.rule_id}: {self.file}:{self.line} — {self.description}"


@dataclass
class ScanResult:
    """Aggregated scan results."""

    findings: list[Finding] = field(default_factory=list)
    files_scanned: int = 0
    rules_checked: int = 0
    errors: list[str] = field(default_factory=list)
    cached_files: int = 0

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
    non_code_all: list[tuple[int, int]] | None = None  # strings + comments
    non_code_strings: list[tuple[int, int]] | None = None  # strings only
    suppressions: dict[int, set[str]] = {}
    ast_tree: ast.AST | None = None
    if lang == "python":
        non_code_all = _build_non_code_ranges(content)
        non_code_strings = _build_non_code_ranges(content, strings_only=True)
        suppressions = _parse_suppressions(content)
        # Parse AST once for AST-based validators
        try:
            ast_tree = ast.parse(content, filename=filepath)
        except SyntaxError:
            pass

    for rule in applicable:
        pattern = _get_compiled(rule["pattern"])
        if pattern is None:
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

            # Inline suppression: # xray: ignore[RULE-ID]
            if suppressions and rule["id"] in suppressions.get(line_num, set()):
                continue

            line_start = content.rfind("\n", 0, match.start()) + 1
            col = match.start() - line_start + 1

            # AST-based validation: reduce false positives
            ast_validator = _AST_VALIDATORS.get(rule["id"])
            if ast_validator and ast_tree is not None:
                if not ast_validator(filepath, content, line_num, ast_tree):
                    continue

            # Context-based validation (no AST required — works for all langs)
            ctx_validator = _CTX_VALIDATORS.get(rule["id"])
            if ctx_validator:
                if not ctx_validator(filepath, content, line_num):
                    continue

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


def git_changed_files(root: str, since: str) -> list[str] | None:
    """Return files changed since a git ref/commit. None if git unavailable."""
    import subprocess

    try:
        proc = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=ACMR", since, "--", "."],
            capture_output=True,
            text=True,
            cwd=root,
            timeout=30,
        )
        if proc.returncode != 0:
            return None
        files = []
        for line in proc.stdout.strip().splitlines():
            line = line.strip()
            if line:
                full = os.path.join(root, line)
                if os.path.isfile(full):
                    files.append(full)
        return files
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def scan_directory(
    root: str,
    rules: list[dict] | None = None,
    exclude_patterns: list[str] | None = None,
    on_progress: Callable | None = None,
    *,
    parallel: bool = False,
    incremental: bool = False,
    since: str = "",
) -> ScanResult:
    """Recursively scan a directory for code issues.

    Args:
        on_progress: Optional callback(files_scanned, findings_count, current_file)
        parallel: Use ProcessPoolExecutor for CPU-bound regex work.
        incremental: Skip files unchanged since last scan.
        since: Git ref/commit — only scan files changed since that ref.
    """
    result = ScanResult()
    if rules is None:
        rules = ALL_RULES
    result.rules_checked = len(rules)

    cache = _ScanCache() if incremental else None

    exclude_res = []
    if exclude_patterns:
        for pat in exclude_patterns:
            try:
                exclude_res.append(re.compile(pat))
            except re.error:
                result.errors.append(f"Invalid exclude pattern: {pat}")

    # Git-aware diff scanning: only files changed since a ref
    diff_set: set[str] | None = None
    if since:
        changed = git_changed_files(root, since)
        if changed is not None:
            diff_set = {os.path.normpath(f) for f in changed}
        else:
            result.errors.append(f"git diff failed for --since={since}")

    # Collect files to scan
    file_list: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Skip hidden and generated directories
        dirnames[:] = [d for d in dirnames if not _should_skip(os.path.join(dirpath, d))]

        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            try:
                rel_path = os.path.relpath(filepath, root).replace(os.sep, "/")
            except ValueError:
                logger.debug("Skipped non-relative path: %s", filepath)
                continue

            # Check exclude patterns
            if any(r.search(rel_path) for r in exclude_res):
                continue

            lang = _detect_lang(filepath)
            if lang is None:
                continue

            # Git diff filter
            if diff_set is not None and os.path.normpath(filepath) not in diff_set:
                continue

            if cache and not cache.is_changed(filepath):
                result.cached_files += 1
                continue

            file_list.append(filepath)

    # Scan files (parallel or sequential)
    if parallel and len(file_list) > 4:
        workers = min(os.cpu_count() or 1, 8)
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(scan_file, fp, rules): fp for fp in file_list}
            for future in as_completed(futures):
                result.files_scanned += 1
                try:
                    file_findings = future.result()
                    result.findings.extend(file_findings)
                except Exception as exc:
                    result.errors.append(f"{futures[future]}: {exc}")
                if on_progress:
                    rel = os.path.relpath(futures[future], root).replace(os.sep, "/")
                    on_progress(result.files_scanned, len(result.findings), rel)
    else:
        for filepath in file_list:
            result.files_scanned += 1
            file_findings = scan_file(filepath, rules)
            result.findings.extend(file_findings)
            if on_progress:
                rel = os.path.relpath(filepath, root).replace(os.sep, "/")
                on_progress(result.files_scanned, len(result.findings), rel)

    if cache:
        cache.save()

    return result


def scan_project(root: str, config: dict | None = None) -> ScanResult:
    """High-level project scan with optional config."""
    exclude = []
    if config:
        exclude = config.get("exclude_patterns", [])
    parallel = bool(config.get("parallel")) if config else False
    incremental = bool(config.get("incremental")) if config else False
    since = config.get("since", "") if config else ""
    return scan_directory(
        root,
        exclude_patterns=exclude,
        parallel=parallel,
        incremental=incremental,
        since=since,
    )
