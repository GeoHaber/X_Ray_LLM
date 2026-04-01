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
    - URL is constructed from constants or config, not user input
    """
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


def _validate_sec010(filepath: str, content: str, line_num: int, tree: ast.AST | None) -> bool:
    """SEC-010: Path traversal risk — keep only suspicious path composition uses."""
    lines = content.splitlines()
    if 0 < line_num <= len(lines):
        line_text = lines[line_num - 1]
        _open_paren = "open" + "("   # split to avoid PY-008 self-match
        _path_paren = "Path" + "("   # split to avoid PY-008 self-match
        suspicious = ("..", "../", "..\\", "join(", _open_paren, _path_paren)
        if not any(token in line_text for token in suspicious):
            return False
    return True


_TAINT_NAME_RE = re.compile(
    r"(?:user|input|query|param|body|payload|request|req|url|path|file|name|dest|target)",
    re.IGNORECASE,
)
_TAINT_ATTRS = {
    "args",
    "form",
    "json",
    "GET",
    "POST",
    "values",
    "query_params",
    "path_params",
    "headers",
    "body",
    "data",
    "argv",
    "environ",
}


def _collect_name_ids(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
    return names


def _is_taint_source_expr(node: ast.AST, tainted: set[str]) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            if _TAINT_NAME_RE.search(child.id) or child.id in tainted:
                return True
        elif isinstance(child, ast.Attribute):
            if child.attr in _TAINT_ATTRS:
                return True
        elif isinstance(child, ast.Call):
            if isinstance(child.func, ast.Name) and child.func.id in {"input", "raw_input"}:
                return True
    return False


def _build_taint_scopes(tree: ast.AST) -> list[tuple[int, int, set[str]]]:
    scopes: list[tuple[int, int, set[str]]] = []
    max_line = max((getattr(node, "lineno", 1) for node in ast.walk(tree)), default=1)

    module_taint: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _is_taint_source_expr(node.value, module_taint):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    module_taint.add(target.id)
    scopes.append((1, max_line, module_taint))

    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        fn_taint: set[str] = set()
        for arg in fn.args.args:
            if _TAINT_NAME_RE.search(arg.arg):
                fn_taint.add(arg.arg)

        body_nodes = sorted(ast.walk(fn), key=lambda n: getattr(n, "lineno", 0))
        for node in body_nodes:
            if isinstance(node, ast.Assign) and _is_taint_source_expr(node.value, fn_taint):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        fn_taint.add(target.id)
            elif (isinstance(node, ast.AnnAssign) and node.value is not None and _is_taint_source_expr(node.value, fn_taint)) or (isinstance(node, ast.AugAssign) and _is_taint_source_expr(node.value, fn_taint)):
                if isinstance(node.target, ast.Name):
                    fn_taint.add(node.target.id)

        scopes.append((fn.lineno, fn.end_lineno or fn.lineno, fn_taint))

    return scopes


def _tainted_for_line(line_num: int, scopes: list[tuple[int, int, set[str]]]) -> set[str]:
    tainted: set[str] = set()
    for start, end, names in scopes:
        if start <= line_num <= end:
            tainted.update(names)
    return tainted


def _line_references_tainted(line_text: str, tainted: set[str]) -> bool:
    return any(re.search(rf"\b{re.escape(name)}\b", line_text) for name in tainted)


def _is_test_path(filepath: str) -> bool:
    basename = os.path.basename(filepath)
    norm = filepath.replace(os.sep, "/")
    return (
        "/tests/" in norm
        or basename.startswith("test_")
        or basename.endswith("_test.py")
        or basename == "conftest.py"
    )


_TEST_SUPPRESSED_RULES = {
    "SEC-003",  # shell injection — tests often exercise subprocess
    "SEC-007",  # code execution — tests verify handling
    "SEC-009",  # deserialization — tests verify handling
    "SEC-012",  # debug flag — tests set it intentionally  # xray: ignore[SEC-012]
    "SEC-014",  # TLS skip — tests disable it intentionally  # xray: ignore[SEC-014]
}

# Extended set used by the explicit relaxed-tests profile
_RELAXED_TEST_RULES = _TEST_SUPPRESSED_RULES | {
    "SEC-004",
    "SEC-005",
    "SEC-010",
    "PY-007",
    "PY-008",
}


def _policy_allows(rule_id: str, filepath: str, policy_profile: str, *, include_tests: bool = False) -> bool:
    profile = (policy_profile or "balanced").lower()
    if profile == "strict":
        return True
    if include_tests:
        return True
    if _is_test_path(filepath):
        if profile == "relaxed-tests":
            return rule_id not in _RELAXED_TEST_RULES
        # Default (balanced): auto-suppress common test false-positive rules
        return rule_id not in _TEST_SUPPRESSED_RULES
    return True


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


def _ctx_validate_sec010(filepath: str, content: str, line_num: int) -> bool:
    """SEC-010 context validator wrapper."""
    return _validate_sec010(filepath, content, line_num, None)


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
    "SEC-010": _ctx_validate_sec010,
    "SEC-007": _ctx_validate_sec007,
    "QUAL-010": _ctx_validate_qual010,
}


# ── Inline suppression parsing ──────────────────────────────────────────
_SUPPRESS_RE = re.compile(r"#\s*xray:\s*ignore\[([^\]]+)\]")
_SUPPRESS_NEXT_RE = re.compile(r"#\s*xray:\s*ignore-next\[([^\]]+)\]")
_SUPPRESS_FILE_RE = re.compile(r"#\s*xray:\s*ignore-file\[([^\]]+)\]")
_SUPPRESS_START_RE = re.compile(r"#\s*xray:\s*ignore-start\[([^\]]+)\]")
_SUPPRESS_END_RE = re.compile(r"#\s*xray:\s*ignore-end\[([^\]]+)\]")


def _parse_rule_ids(raw: str) -> set[str]:
    return {rid.strip() for rid in raw.split(",") if rid.strip()}


def _parse_suppressions(content: str) -> tuple[
    dict[int, set[str]],
    dict[int, set[str]],
    set[str],
    dict[str, list[tuple[int, int]]],
]:
    """Parse xray suppression directives with scoped support.

    Supported forms:
      - # xray: ignore[RULE]        (same line)
      - # xray: ignore-next[RULE]   (next line)
      - # xray: ignore-file[RULE]   (entire file)
      - # xray: ignore-start[RULE] / ignore-end[RULE] (line range)
    """
    same_line: dict[int, set[str]] = {}
    next_line: dict[int, set[str]] = {}
    file_rules: set[str] = set()
    ranges_by_rule: dict[str, list[tuple[int, int]]] = {}
    open_ranges: dict[str, list[int]] = {}

    lines = content.splitlines()
    total_lines = len(lines)

    for i, line in enumerate(lines, 1):
        m = _SUPPRESS_RE.search(line)
        if m:
            same_line.setdefault(i, set()).update(_parse_rule_ids(m.group(1)))

        m = _SUPPRESS_NEXT_RE.search(line)
        if m and i < total_lines:
            next_line.setdefault(i + 1, set()).update(_parse_rule_ids(m.group(1)))

        m = _SUPPRESS_FILE_RE.search(line)
        if m:
            file_rules.update(_parse_rule_ids(m.group(1)))

        m = _SUPPRESS_START_RE.search(line)
        if m:
            for rid in _parse_rule_ids(m.group(1)):
                open_ranges.setdefault(rid, []).append(i)

        m = _SUPPRESS_END_RE.search(line)
        if m:
            for rid in _parse_rule_ids(m.group(1)):
                stack = open_ranges.get(rid)
                if stack:
                    start = stack.pop()
                    ranges_by_rule.setdefault(rid, []).append((start, i))

    for rid, starts in open_ranges.items():
        for start in starts:
            ranges_by_rule.setdefault(rid, []).append((start, total_lines))

    return same_line, next_line, file_rules, ranges_by_rule


def _is_suppressed(
    line_num: int,
    rule_id: str,
    same_line: dict[int, set[str]],
    next_line: dict[int, set[str]],
    file_rules: set[str],
    ranges_by_rule: dict[str, list[tuple[int, int]]],
) -> bool:
    if rule_id in file_rules:
        return True
    if rule_id in same_line.get(line_num, set()):
        return True
    if rule_id in next_line.get(line_num, set()):
        return True
    for start, end in ranges_by_rule.get(rule_id, []):
        if start <= line_num <= end:
            return True
    return False


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
    confidence: float = 0.5
    autofix_tier: str = "manual"  # safe | cautious | manual
    signal_path: str = "pattern"
    why_flagged: str = "Matched rule pattern"
    policy_profile: str = "balanced"
    taint_mode: str = "lite"
    taint_matched: bool | None = None
    is_test_file: bool = False
    cwe: str = ""                  # e.g. "CWE-79"
    owasp: str = ""                # e.g. "A03:2021-Injection"
    llm_verdict: str = ""          # "TRUE_POSITIVE" | "FALSE_POSITIVE" | "" (not evaluated)
    llm_reason: str = ""           # one-line explanation from LLM
    llm_suppressed: bool = False   # True if LLM classified as FP

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
            "confidence": self.confidence,
            "autofix_tier": self.autofix_tier,
            "signal_path": self.signal_path,
            "why_flagged": self.why_flagged,
            "policy_profile": self.policy_profile,
            "taint_mode": self.taint_mode,
            "taint_matched": self.taint_matched,
            "is_test_file": self.is_test_file,
            "cwe": self.cwe,
            "owasp": self.owasp,
            "llm_verdict": self.llm_verdict,
            "llm_reason": self.llm_reason,
            "llm_suppressed": self.llm_suppressed,
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
            confidence=float(d.get("confidence", 0.5)),
            autofix_tier=d.get("autofix_tier", "manual"),
            signal_path=d.get("signal_path", "pattern"),
            why_flagged=d.get("why_flagged", "Matched rule pattern"),
            policy_profile=d.get("policy_profile", "balanced"),
            taint_mode=d.get("taint_mode", "lite"),
            taint_matched=d.get("taint_matched"),
            is_test_file=d.get("is_test_file", False),
            cwe=d.get("cwe", ""),
            owasp=d.get("owasp", ""),
            llm_verdict=d.get("llm_verdict", ""),
            llm_reason=d.get("llm_reason", ""),
            llm_suppressed=d.get("llm_suppressed", False),
        )

    def __str__(self) -> str:
        tags = []
        if self.cwe:
            tags.append(self.cwe)
        if self.owasp:
            tags.append(self.owasp)
        tag_str = f" ({', '.join(tags)})" if tags else ""
        return f"[{self.severity}] {self.rule_id}{tag_str}: {self.file}:{self.line} — {self.description}"


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


def _estimate_confidence(rule_id: str, used_ast: bool, used_ctx: bool) -> float:
    if used_ast:
        return 0.95
    if used_ctx:
        return 0.85
    if rule_id.startswith("SEC-"):
        return 0.8
    if rule_id.startswith("QUAL-"):
        return 0.7
    return 0.65


def _autofix_tier(rule_id: str, severity: str) -> str:
    if rule_id in {"PY-004", "QUAL-013", "PY-008", "PY-010"}:
        return "safe"
    if severity == "LOW":
        return "cautious"
    return "manual"


def _build_signal_path(used_ast: bool, used_ctx: bool, used_taint: bool) -> str:
    parts = ["pattern"]
    if used_ast:
        parts.append("ast")
    if used_ctx:
        parts.append("context")
    if used_taint:
        parts.append("taint")
    return " + ".join(parts)


def _build_why_flagged(rule_id: str, used_ast: bool, used_ctx: bool, taint_mode: str, taint_match: bool | None) -> str:
    clauses = [f"Rule {rule_id} pattern matched"]
    if used_ast:
        clauses.append("AST validation passed")
    if used_ctx:
        clauses.append("context validation passed")
    if taint_mode != "off" and taint_match is not None:
        clauses.append(f"taint signal {'present' if taint_match else 'not required'} ({taint_mode})")
    return "; ".join(clauses)


def _should_skip(dirpath: str) -> bool:
    """Check if directory should be skipped."""
    basename = os.path.basename(dirpath)
    return basename in _SKIP_DIRS or basename.startswith(".")


def scan_file(
    filepath: str,
    rules: list[dict] | None = None,
    *,
    policy_profile: str = "balanced",
    taint_mode: str = "lite",
    include_tests: bool = False,
) -> list[Finding]:
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
    file_is_test = _is_test_path(filepath)

    # Build non-code ranges once per file for Python files
    non_code_all: list[tuple[int, int]] | None = None  # strings + comments
    non_code_strings: list[tuple[int, int]] | None = None  # strings only
    same_line_suppressions: dict[int, set[str]] = {}
    next_line_suppressions: dict[int, set[str]] = {}
    file_suppressions: set[str] = set()
    range_suppressions: dict[str, list[tuple[int, int]]] = {}
    ast_tree: ast.AST | None = None
    taint_scopes: list[tuple[int, int, set[str]]] | None = None
    if lang == "python":
        non_code_all = _build_non_code_ranges(content)
        non_code_strings = _build_non_code_ranges(content, strings_only=True)
        (
            same_line_suppressions,
            next_line_suppressions,
            file_suppressions,
            range_suppressions,
        ) = _parse_suppressions(content)
        # Parse AST once for AST-based validators
        try:
            ast_tree = ast.parse(content, filename=filepath)
            if taint_mode.lower() in {"lite", "strict"}:
                taint_scopes = _build_taint_scopes(ast_tree)
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

            # Scoped suppression directives
            if _is_suppressed(
                line_num,
                rule["id"],
                same_line_suppressions,
                next_line_suppressions,
                file_suppressions,
                range_suppressions,
            ):
                continue

            if not _policy_allows(rule["id"], filepath, policy_profile, include_tests=include_tests):
                continue

            line_start = content.rfind("\n", 0, match.start()) + 1
            col = match.start() - line_start + 1

            # AST-based validation: reduce false positives
            ast_validator = _AST_VALIDATORS.get(rule["id"])
            used_ast_validator = False
            if ast_validator and ast_tree is not None:
                used_ast_validator = True
                if not ast_validator(filepath, content, line_num, ast_tree):
                    continue

            # Context-based validation (no AST required — works for all langs)
            ctx_validator = _CTX_VALIDATORS.get(rule["id"])
            used_ctx_validator = False
            if ctx_validator:
                used_ctx_validator = True
                if not ctx_validator(filepath, content, line_num):
                    continue

            taint_matched: bool | None = None
            used_taint_validator = False
            if taint_mode.lower() == "lite" and rule["id"] in {"SEC-004", "SEC-005", "SEC-010"}:
                lines = content.splitlines()
                line_text = lines[line_num - 1] if 0 < line_num <= len(lines) else ""
                tainted = _tainted_for_line(line_num, taint_scopes or [])
                has_taint = _line_references_tainted(line_text, tainted)
                taint_matched = bool(has_taint or re.search(r"(request\.|input\(|sys\.argv|os\.environ|query|path|url|filename)", line_text))
                used_taint_validator = True
                if not taint_matched:
                    continue
            elif taint_mode.lower() in {"strict", "lite"} and rule["id"] in {"SEC-004", "SEC-005", "SEC-010"}:
                lines = content.splitlines()
                line_text = lines[line_num - 1] if 0 < line_num <= len(lines) else ""
                tainted = _tainted_for_line(line_num, taint_scopes or [])
                taint_matched = bool(_line_references_tainted(line_text, tainted))
                used_taint_validator = True

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
                    confidence=_estimate_confidence(rule["id"], used_ast_validator, used_ctx_validator),
                    autofix_tier=_autofix_tier(rule["id"], rule["severity"]),
                    signal_path=_build_signal_path(used_ast_validator, used_ctx_validator, used_taint_validator),
                    why_flagged=_build_why_flagged(
                        rule["id"],
                        used_ast_validator,
                        used_ctx_validator,
                        taint_mode.lower(),
                        taint_matched,
                    ),
                    policy_profile=policy_profile,
                    taint_mode=taint_mode,
                    taint_matched=taint_matched,
                    is_test_file=file_is_test,
                    cwe=rule.get("cwe", ""),
                    owasp=rule.get("owasp", ""),
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
    policy_profile: str = "balanced",
    taint_mode: str = "lite",
    include_tests: bool = False,
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
            futures = {
                pool.submit(scan_file, fp, rules, policy_profile=policy_profile, taint_mode=taint_mode, include_tests=include_tests): fp
                for fp in file_list
            }
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
            file_findings = scan_file(filepath, rules, policy_profile=policy_profile, taint_mode=taint_mode, include_tests=include_tests)
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
    policy_profile = config.get("policy_profile", "balanced") if config else "balanced"
    taint_mode = config.get("taint_mode", "lite") if config else "lite"
    include_tests = bool(config.get("include_tests")) if config else False
    return scan_directory(
        root,
        exclude_patterns=exclude,
        parallel=parallel,
        incremental=incremental,
        since=since,
        policy_profile=policy_profile,
        taint_mode=taint_mode,
        include_tests=include_tests,
    )


def extract_code_slice(
    filepath: str,
    line: int,
    window: int = 15,
    include_imports: bool = True,
) -> str:
    """Extract a minimal code slice around a finding.

    1. The function/class containing the finding line
    2. If the function is short (< window*2 lines), include it fully
    3. Otherwise, center on the finding line with ``window`` lines each side
    4. Optionally prepend import statements from the file

    Returns the slice as a string with line numbers.
    Falls back gracefully for missing files, binary content, or out-of-range lines.
    """
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except (OSError, PermissionError):
        return f"(Could not read {filepath})"

    if not lines:
        return "(empty file)"

    total = len(lines)
    # Clamp line to valid range
    line = max(1, min(line, total))

    # Collect import lines (first contiguous block at top)
    import_lines: list[str] = []
    if include_imports:
        for ln in lines:
            stripped = ln.strip()
            if stripped.startswith(("import ", "from ")) or stripped == "" or stripped.startswith("#"):
                import_lines.append(ln)
            else:
                break

    # Try AST-based function extraction for Python files
    if filepath.endswith(".py"):
        func_slice = _extract_function_slice_impl(lines, line)
        if func_slice is not None:
            func_start, func_end = func_slice
            func_len = func_end - func_start + 1
            if func_len <= window * 2:
                # Short function — include it fully
                start = func_start
                end = func_end
            else:
                # Long function — center on the finding line
                start = max(func_start, line - window - 1)
                end = min(func_end, line + window - 1)

            numbered = _number_lines(lines, start, end, highlight=line)
            if include_imports and import_lines and start > len(import_lines):
                import_block = "".join(import_lines).rstrip() + "\n...\n"
                return import_block + numbered
            return numbered

    # Fallback: simple window around the line
    start = max(0, line - window - 1)
    end = min(total - 1, line + window - 1)
    numbered = _number_lines(lines, start, end, highlight=line)
    if include_imports and import_lines and start > len(import_lines):
        import_block = "".join(import_lines).rstrip() + "\n...\n"
        return import_block + numbered
    return numbered


def _number_lines(lines: list[str], start: int, end: int, highlight: int = -1) -> str:
    """Format lines[start..end] with line numbers (0-indexed start/end)."""
    numbered = []
    for i in range(start, min(end + 1, len(lines))):
        line_num = i + 1
        marker = " >>>" if line_num == highlight else "    "
        numbered.append(f"{marker} {line_num:4d} | {lines[i].rstrip()}")
    return "\n".join(numbered)


def _extract_function_slice_impl(
    lines: list[str], target_line: int
) -> tuple[int, int] | None:
    """Use Python's ast module to find the enclosing function/method
    for the given line number. Returns (start_idx, end_idx) as 0-based
    indices into the lines list, or None if no enclosing function found.
    """
    source = "".join(lines)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    best: tuple[int, int] | None = None
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        start = node.lineno  # 1-based
        end = node.end_lineno or start
        if start <= target_line <= end:
            # Pick the tightest enclosing scope
            if best is None or (end - start) < (best[1] - best[0]):
                best = (start - 1, end - 1)  # convert to 0-based

    return best


def extract_function_slice(filepath: str, line: int) -> str:
    """Use Python's ast module to find the enclosing function/method
    for the given line. Return the full function source + imports.
    Falls back to line-window approach for non-Python files.
    """
    if not filepath.endswith(".py"):
        return extract_code_slice(filepath, line)

    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except (OSError, PermissionError):
        return f"(Could not read {filepath})"

    if not lines:
        return "(empty file)"

    total = len(lines)
    line = max(1, min(line, total))

    # Collect imports
    import_lines: list[str] = []
    for ln in lines:
        stripped = ln.strip()
        if stripped.startswith(("import ", "from ")) or stripped == "" or stripped.startswith("#"):
            import_lines.append(ln)
        else:
            break

    func_slice = _extract_function_slice_impl(lines, line)
    if func_slice is not None:
        start, end = func_slice
        numbered = _number_lines(lines, start, end, highlight=line)
        if import_lines and start > len(import_lines):
            import_block = "".join(import_lines).rstrip() + "\n...\n"
            return import_block + numbered
        return numbered

    # Fallback: window approach
    return extract_code_slice(filepath, line, include_imports=True)


def llm_classify_findings(
    findings: list[Finding],
    llm_generate: Callable[[str], str],
    max_findings: int = 50,
) -> list[Finding]:
    """Stage 5: LLM-based false positive classification.

    For each finding, extract surrounding code context and ask the LLM
    to classify it as TRUE_POSITIVE or FALSE_POSITIVE.

    Adds finding.llm_verdict and finding.llm_reason fields.
    Findings classified as FP get suppressed (not removed -- marked).

    Args:
        findings: List of Finding objects to evaluate.
        llm_generate: Callable that takes a prompt string and returns LLM text.
        max_findings: Limit to avoid excessive LLM calls.

    Returns:
        The same list of findings with llm_verdict, llm_reason, and
        llm_suppressed fields populated.
    """
    for finding in findings[:max_findings]:
        # Extract code context around the finding
        code_context = extract_code_slice(
            finding.file, finding.line, window=7, include_imports=False
        )

        prompt = (
            "You are a security code reviewer. Analyze this finding:\n\n"
            f"Rule: {finding.rule_id} - {finding.description}\n"
            f"File: {finding.file}\n"
            f"Line: {finding.line}\n\n"
            f"Code context:\n```\n{code_context}\n```\n\n"
            f"Matched text: {finding.matched_text[:200]}\n\n"
            "Evaluate:\n"
            "1. Is the matched pattern actually vulnerable in this context?\n"
            "2. Can an attacker control the input that reaches this code?\n"
            "3. Are there sanitizers, validators, or guards that prevent exploitation?\n\n"
            "Respond with EXACTLY two lines:\n"
            "VERDICT: TRUE_POSITIVE | FALSE_POSITIVE\n"
            "REASON: <one sentence explanation>"
        )

        try:
            response = llm_generate(prompt)
            verdict, reason = _parse_llm_verdict(response)
            finding.llm_verdict = verdict
            finding.llm_reason = reason
            if verdict == "FALSE_POSITIVE":
                finding.llm_suppressed = True
        except Exception as exc:
            logger.debug("LLM classify failed for %s:%d: %s", finding.file, finding.line, exc)
            finding.llm_verdict = ""
            finding.llm_reason = f"LLM classification error: {exc}"

    return findings


def _parse_llm_verdict(response: str) -> tuple[str, str]:
    """Parse VERDICT and REASON from LLM response text.

    Returns (verdict, reason) where verdict is 'TRUE_POSITIVE',
    'FALSE_POSITIVE', or '' if parsing fails.
    """
    verdict = ""
    reason = ""
    for line in response.strip().splitlines():
        line = line.strip()
        if line.upper().startswith("VERDICT:"):
            raw = line.split(":", 1)[1].strip().upper()
            if "FALSE_POSITIVE" in raw or "FALSE POSITIVE" in raw:
                verdict = "FALSE_POSITIVE"
            elif "TRUE_POSITIVE" in raw or "TRUE POSITIVE" in raw:
                verdict = "TRUE_POSITIVE"
        elif line.upper().startswith("REASON:"):
            reason = line.split(":", 1)[1].strip()
    return verdict, reason


def suggest_fix_plan(findings: list[Finding], llm_fn: Callable[[str], str] | None = None) -> dict:
    """Create a prioritized remediation plan; optionally enrich with LLM advice."""
    severity_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    ordered = sorted(
        findings,
        key=lambda f: (
            severity_order.get(f.severity, 9),
            -float(getattr(f, "confidence", 0.5)),
            getattr(f, "autofix_tier", "manual") != "safe",
            f.rule_id,
            f.file,
            f.line,
        ),
    )

    top = ordered[:25]
    plan = {
        "counts": {
            "total": len(findings),
            "high": sum(1 for f in findings if f.severity == "HIGH"),
            "medium": sum(1 for f in findings if f.severity == "MEDIUM"),
            "low": sum(1 for f in findings if f.severity == "LOW"),
        },
        "top_findings": [f.to_dict() for f in top],
        "llm_notes": "",
    }

    if llm_fn and top:
        prompt_lines = [
            "You are a senior security and code-quality engineer.",
            "Create a concise remediation plan in 5 bullets.",
            "Prioritize highest risk and highest confidence first.",
            "Findings:",
        ]
        for f in top:
            prompt_lines.append(
                f"- [{f.severity}] {f.rule_id} {f.file}:{f.line} confidence={f.confidence:.2f} tier={f.autofix_tier}"
            )
        try:
            plan["llm_notes"] = llm_fn("\n".join(prompt_lines)).strip()
        except Exception as exc:
            logger.debug("LLM planning failed: %s", exc)

    return plan
