"""
Analysis/security.py — Bandit Security Scanner Integration for X-Ray
=====================================================================

Wraps ``bandit`` as a subprocess, parses JSON output,
and converts findings into X-Ray SmellIssue objects for
unified reporting.

Requires: bandit (pip install bandit)
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Dict, Any, Optional

from Core.types import SmellIssue, Severity
from Core.utils import logger
from Analysis._analyzer_base import BaseStaticAnalyzer


# Bandit severity → X-Ray severity
_SEVERITY_MAP: Dict[str, str] = {
    "HIGH":   Severity.CRITICAL,
    "MEDIUM": Severity.WARNING,
    "LOW":    Severity.INFO,
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

    def __init__(self, severity_threshold: str = "low",
                 extra_args: Optional[List[str]] = None):
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

    # -- overrides ---------------------------------------------------------

    def _build_command(self, root: Path,
                       exclude: Optional[List[str]]) -> List[str]:
        """Assemble the bandit CLI command list."""
        cmd = [self._tool_path, "-r", str(root), "-f", "json"]

        sev = self.severity_threshold.lower()
        if sev == "high":
            cmd.append("-lll")
        elif sev == "medium":
            cmd.append("-ll")
        else:
            cmd.append("-l")

        # Auto-exclude common non-project directories
        from Analysis._analyzer_base import _merged_excludes
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

        Filters out B101 (assert-used) in test files and B404 (import-subprocess)
        since these are universally considered false positives.
        """
        test_id = item.get("test_id", "")
        test_name = item.get("test_name", "")
        filename = item.get("filename", "")

        # Skip B101 (assert-used) in test files — asserts are expected in tests
        if test_id == "B101":
            fn_lower = filename.replace("\\", "/").lower()
            if "/test" in fn_lower or fn_lower.startswith("test") or "conftest" in fn_lower:
                return None

        # Skip B404 (import-subprocess) — importing is not a vulnerability
        if test_id == "B404":
            return None

        sev = item.get("issue_severity", "LOW")
        conf = item.get("issue_confidence", "LOW")
        text = item.get("issue_text", "")
        filename = item.get("filename", "")
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

    @staticmethod
    def _suggest_fix(test_id: str, text: str) -> str:
        """Return an actionable fix suggestion for common Bandit findings."""
        suggestions = {
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
        return suggestions.get(test_id, "Review and apply security best practice.")

    def summary(self, issues: List[SmellIssue]) -> Dict[str, Any]:
        """Build summary with additional ``by_confidence`` breakdown."""
        from collections import Counter
        result = super().summary(issues)
        by_confidence = Counter(s.confidence for s in issues)
        result["by_confidence"] = dict(by_confidence)
        return result
