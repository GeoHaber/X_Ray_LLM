"""
Analysis/security.py — Bandit Security Scanner Integration for X-Ray
=====================================================================

Wraps ``bandit`` as a subprocess, parses JSON output,
and converts findings into X-Ray SmellIssue objects for
unified reporting.

Best practices (see [tool.bandit] in pyproject.toml):
  - exclude_dirs: venv, __pycache__, build, etc.
  - skips: B101 (assert in tests), B404 (import subprocess)
  - Use # nosec on reviewed false positives; # nosec B602,B607 for specific tests

Requires: bandit (pip install bandit)
"""

from __future__ import annotations

import ast
import math
import re
from collections import Counter as _Counter
from pathlib import Path
from typing import List, Dict, Any, Optional

from Core.types import SmellIssue, Severity
from Core.utils import logger
from Analysis._analyzer_base import BaseStaticAnalyzer, _merged_excludes

# Bandit severity → X-Ray severity
_SEVERITY_MAP: Dict[str, str] = {
    "HIGH": Severity.CRITICAL,
    "MEDIUM": Severity.WARNING,
    "LOW": Severity.INFO,
}

# Well-known Bandit test IDs → human-readable categories
_CATEGORY_MAP: Dict[str, str] = {
    "B101": "assert-used",
    "B102": "exec-used",
    "B104": "bind-all-interfaces",
    "B105": "hardcoded-password",
    "B106": "hardcoded-password-arg",
    "B107": "hardcoded-password-default",
    "B108": "insecure-temp-file",
    "B110": "try-except-pass",
    "B112": "try-except-continue",
    "B113": "request-no-timeout",
    "B201": "flask-debug",
    "B301": "pickle-load",
    "B302": "marshal-load",
    "B303": "insecure-hash-md5",
    "B310": "url-open-audit",
    "B311": "random-not-crypto",
    "B312": "telnet-usage",
    "B320": "xml-bad-parser",
    "B324": "weak-hash",
    "B404": "import-subprocess",
    "B501": "ssl-no-verify",
    "B602": "subprocess-shell",
    "B603": "subprocess-untrusted",
    "B604": "function-call-shell",
    "B605": "os-system-call",
    "B606": "process-no-shell",
    "B607": "partial-executable-path",
    "B608": "sql-injection",
    "B615": "hf-hub-no-revision",
}


# ── Secret / credential detection ────────────────────────────────────────────

_SECRET_NAME_RE = re.compile(
    r"(api_?key|access_?token|secret|credential|passwd|password|"
    r"auth_?token|bearer|private_?key|client_?secret)",
    re.IGNORECASE,
)

_PLACEHOLDER_RE = re.compile(
    r"(?i)^[\s<${\[#]|^(your|change|replace|dummy|test|placeholder|"
    r"example|xxx|todo|fixme|none|null|empty|false|true|0)",
)

# Known API key format patterns: (compiled regex, human label)
_API_KEY_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9]{20,50}"), "OpenAI API key"),
    (re.compile(r"ghp_[A-Za-z0-9]{36}"), "GitHub personal access token"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key ID"),
    (re.compile(r"xox[baprs]-[0-9A-Za-z\-]{10,72}"), "Slack token"),
    (re.compile(r"AIza[0-9A-Za-z\-_]{35}"), "Google API key"),
    (re.compile(r"EAACEdEose0cBA[0-9A-Za-z]+"), "Facebook access token"),
]

_SECRET_ENTROPY_THRESHOLD = 4.5
_SECRET_MIN_LEN = 20
_SECRET_TOKEN_RE = re.compile(r"^[A-Za-z0-9+/=_\-]{20,}$")


def _string_entropy(s: str) -> float:
    """Compute Shannon entropy (bits per character) of a string."""
    if not s:
        return 0.0
    freq = _Counter(s)
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in freq.values() if c > 0)


_CRED_MOVE_HINT = (
    "Move to environment variable: os.environ['KEY_NAME'] or use python-dotenv."
)


def _extract_assignment(node: ast.AST):
    """Return (target_name, value_node) for Assign/AnnAssign, else (None, None)."""
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        t = node.targets[0]
        name = t.id if isinstance(t, ast.Name) else None
        return name, node.value
    if isinstance(node, ast.AnnAssign) and node.value is not None:
        name = node.target.id if isinstance(node.target, ast.Name) else None
        return name, node.value
    return None, None


def _make_secret_issue(
    rel_path: str,
    line: int,
    severity: str,
    name: str,
    message: str,
    rule_code: str,
    metric: int = 0,
) -> SmellIssue:
    return SmellIssue(
        file_path=rel_path,
        line=line,
        end_line=line,
        category="hardcoded-secret",
        severity=severity,
        name=name,
        metric_value=metric,
        message=message,
        suggestion=_CRED_MOVE_HINT,
        source="xray-secrets",
        rule_code=rule_code,
    )


def _check_secret_value(
    val: str,
    target_name: str | None,
    rel_path: str,
    line: int,
) -> SmellIssue | None:
    """Check one string value for XS001/XS002/XS003 patterns."""
    # XS001 — known API key format (CRITICAL)
    for pattern, label in _API_KEY_PATTERNS:
        if pattern.search(val):
            return _make_secret_issue(
                rel_path,
                line,
                Severity.CRITICAL,
                target_name or "<unknown>",
                f"Hardcoded {label} detected in '{target_name or 'string literal'}'",
                "XS001",
            )
    # XS002 — suspicious variable name
    if target_name and _SECRET_NAME_RE.search(target_name):
        return _make_secret_issue(
            rel_path,
            line,
            Severity.WARNING,
            target_name,
            f"Potential hardcoded credential in variable '{target_name}'",
            "XS002",
        )
    # XS003 — high-entropy token heuristic
    if (
        len(val) >= _SECRET_MIN_LEN
        and _SECRET_TOKEN_RE.match(val)
        and _string_entropy(val) >= _SECRET_ENTROPY_THRESHOLD
    ):
        entropy = _string_entropy(val)
        return _make_secret_issue(
            rel_path,
            line,
            Severity.WARNING,
            target_name or "<literal>",
            f"High-entropy string literal (entropy={entropy:.1f}) may be a hardcoded token or key",
            "XS003",
            metric=int(entropy * 10),
        )
    return None


def _scan_secrets_in_file(fpath: Path, rel_path: str) -> List[SmellIssue]:
    """Scan a single file for hardcoded secrets via AST analysis.

    Detects three classes of secrets:
      XS001 — String matching a known API key format (CRITICAL).
      XS002 — String assigned to a suspiciously named variable (WARNING).
      XS003 — High-entropy string literal that looks like a token (WARNING).
    """
    try:
        source = fpath.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(source, filename=str(fpath))
    except Exception:
        return []

    issues: List[SmellIssue] = []
    for node in ast.walk(tree):
        target_name, value_node = _extract_assignment(node)
        if value_node is None or not isinstance(value_node, ast.Constant):
            continue
        if not isinstance(value_node.value, str):
            continue
        val: str = value_node.value
        if len(val) < 8 or _PLACEHOLDER_RE.match(val):
            continue
        line: int = getattr(value_node, "lineno", 1)
        issue = _check_secret_value(val, target_name, rel_path, line)
        if issue:
            issues.append(issue)
    return issues


class SecurityAnalyzer(BaseStaticAnalyzer):
    """
    Runs Bandit security scanner and converts results to X-Ray SmellIssue format.

    Usage::

        analyzer = SecurityAnalyzer()
        if analyzer.available:
            issues = analyzer.analyze(Path("/my/project"))
    """

    TOOL_NAME = "bandit"
    TOOL_TIMEOUT = 300
    TOOL_LOG_NAME = "Bandit"

    def __init__(
        self, severity_threshold: str = "low", extra_args: Optional[List[str]] = None
    ):
        """
        Parameters
        ----------
        severity_threshold : str
            Minimum Bandit severity to report: "low", "medium", or "high".
        extra_args : list[str], optional
            Extra CLI args passed to bandit.
        """
        self.severity_threshold = severity_threshold
        super().__init__(extra_args=extra_args)

    # -- public entry point ------------------------------------------------

    def analyze(
        self, root: Path, exclude: Optional[List[str]] = None
    ) -> List[SmellIssue]:
        """Run AST-based secret detection then Bandit; return merged SmellIssue list.

        Secret issues (XS001-XS003) are prepended to Bandit results.  The
        combined list is re-sorted by severity, file path, and line number.
        """
        from Analysis.ast_utils import collect_py_files

        # ── AST-based secret scan ──────────────────────────────────────────
        secret_issues: List[SmellIssue] = []
        for fpath in collect_py_files(root, exclude):
            try:
                rel = str(fpath.relative_to(root)).replace("\\", "/")
            except ValueError:
                rel = str(fpath).replace("\\", "/")
            secret_issues.extend(_scan_secrets_in_file(fpath, rel))

        logger.info(f"xray-secrets found {len(secret_issues)} secret issue(s).")

        # ── Bandit scan (via base template method) ─────────────────────────
        bandit_issues = super().analyze(root, exclude)

        # ── Merge and re-sort ──────────────────────────────────────────────
        all_issues = secret_issues + bandit_issues
        all_issues.sort(
            key=lambda s: (
                0
                if s.severity == Severity.CRITICAL
                else 1
                if s.severity == Severity.WARNING
                else 2,
                s.file_path,
                s.line,
            )
        )
        return all_issues

    # -- overrides ---------------------------------------------------------

    def _build_command(self, root: Path, exclude: Optional[List[str]]) -> List[str]:
        """Assemble the bandit CLI command list."""
        cmd = [str(self._tool_path), "-r", str(root), "-f", "json"]

        sev = self.severity_threshold.lower()
        if sev == "high":
            cmd.append("-lll")
        elif sev == "medium":
            cmd.append("-ll")
        else:
            cmd.append("-l")

        # Auto-exclude common non-project directories
        all_exclude = _merged_excludes(exclude)

        exclude_paths = []
        for pat in all_exclude:
            full = root / pat
            exclude_paths.append(str(full) if full.exists() else pat)
        if exclude_paths:
            cmd.extend(["-x", ",".join(exclude_paths)])

        cmd.extend(self.extra_args)
        return cmd

    def _preprocess_output(self, raw: str) -> Optional[str]:
        """Strip bandit's progress-bar prefix before JSON."""
        json_start = raw.find("{")
        if json_start > 0:
            raw = raw[json_start:]
        elif json_start < 0:
            logger.error("Bandit output contains no JSON object.")
            return None
        return raw

    def _extract_items(self, data: Any) -> list:
        """Bandit wraps results inside a ``results`` key."""
        return data.get("results", [])

    def _to_smell_issue(self, item: Dict[str, Any], root: Path) -> Optional[SmellIssue]:
        """Convert a single Bandit result to SmellIssue.

        Filters B101 in test files and B404 (import-subprocess) as common FPs.
        """
        test_id = item.get("test_id", "")
        test_name = item.get("test_name", "")
        filename = item.get("filename", "")

        if test_id == "B101":
            fn = filename.replace("\\", "/").lower()
            if "/test" in fn or fn.startswith("test") or "conftest" in fn:
                return None
        if test_id == "B404":
            return None

        sev = item.get("issue_severity", "LOW")
        conf = item.get("issue_confidence", "LOW")
        text = item.get("issue_text", "")
        line = item.get("line_number", 0)
        line_range = item.get("line_range", [line])

        # Make path relative to root
        try:
            rel_path = str(Path(filename).relative_to(root))
        except ValueError:
            rel_path = filename

        end_line = max(line_range) if line_range else line

        severity = _SEVERITY_MAP.get(sev, Severity.INFO)
        category = _CATEGORY_MAP.get(test_id, f"security-{test_id}")

        suggestion = self._suggest_fix(test_id, text)

        return SmellIssue(
            file_path=rel_path,
            line=line,
            end_line=end_line,
            category=category,
            severity=severity,
            message=f"[{test_id}:{test_name}] {text}",
            suggestion=suggestion,
            name="",
            metric_value=0,
            source="bandit",
            rule_code=test_id,
            fixable=False,
            confidence=conf,
        )

    _FIX_SUGGESTIONS: Dict[str, str] = {
        "B101": "Remove assert from production code or use proper validation.",
        "B102": "Replace exec() with a safer alternative (importlib, ast.literal_eval).",
        "B104": "Bind to specific IP instead of 0.0.0.0.",
        "B105": "Move password to environment variable or secrets manager.",
        "B110": "Log the exception instead of silently passing.",
        "B113": "Add timeout= parameter to requests call.",
        "B301": "Use json instead of pickle, or validate input source.",
        "B303": "Use hashlib.sha256() instead of md5().",
        "B324": "Use SHA-256 or add usedforsecurity=False.",
        "B311": "Use secrets module instead of random for security contexts.",
        "B501": "Enable SSL certificate verification (verify=True).",
        "B602": "Use subprocess.run([...]) without shell=True.",
        "B603": "Validate all input passed to subprocess calls.",
        "B605": "Replace os.system() with subprocess.run().",
        "B607": "Use absolute path for executable.",
        "B608": "Use parameterized queries instead of string formatting.",
        "B615": "Pin revision hash in hf_hub_download().",
    }

    @staticmethod
    def _suggest_fix(test_id: str, text: str) -> str:
        """Return actionable fix suggestion for Bandit finding."""
        return SecurityAnalyzer._FIX_SUGGESTIONS.get(
            test_id, "Review and apply security best practice."
        )

    def summary(self, issues: List[SmellIssue]) -> Dict[str, Any]:
        """Build summary with additional ``by_confidence`` breakdown."""
        from collections import Counter

        result = super().summary(issues)
        by_confidence = Counter(s.confidence for s in issues)
        result["by_confidence"] = dict(by_confidence)
        return result


# Module-level API for test compatibility
_default_analyzer = SecurityAnalyzer()


def analyze(source_code: str, project_root: str = None) -> List[SmellIssue]:
    """Analyze source code for security issues. Wrapper for SecurityAnalyzer.analyze()."""
    if source_code is None:
        raise ValueError("source_code cannot be None")
    return _default_analyzer.analyze(source_code, project_root)


def summary(issues: List[SmellIssue]) -> Dict[str, Any]:
    """Build summary with security issue breakdown. Wrapper for SecurityAnalyzer.summary()."""
    if issues is None:
        raise ValueError("issues cannot be None")
    return _default_analyzer.summary(issues)
