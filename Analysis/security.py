"""
Analysis/security.py — Bandit Security Scanner Integration for X-Ray
=====================================================================

Wraps ``bandit`` as a subprocess, parses JSON output,
and converts findings into X-Ray SmellIssue objects for
unified reporting.

Requires: bandit (pip install bandit)
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional

from Core.types import SmellIssue, Severity
from Core.utils import logger


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


class SecurityAnalyzer:
    """
    Runs Bandit security scanner and converts results to X-Ray SmellIssue format.

    Usage::

        analyzer = SecurityAnalyzer()
        if analyzer.available:
            issues = analyzer.analyze(Path("/my/project"))
    """

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
        self.extra_args = extra_args or []
        self._bandit_path = shutil.which("bandit")

    @property
    def available(self) -> bool:
        """Check if bandit is installed and executable."""
        return self._bandit_path is not None

    def analyze(self, root: Path, exclude: Optional[List[str]] = None) -> List[SmellIssue]:
        """
        Run ``bandit -r`` on `root` and return SmellIssue list.

        Parameters
        ----------
        root : Path
            Directory to scan.
        exclude : list[str], optional
            Directory names to exclude.

        Returns
        -------
        list[SmellIssue]
            Security issues found, mapped to X-Ray severity.
        """
        if not self.available:
            logger.warning("Bandit is not installed. Run: pip install bandit")
            return []

        cmd = [
            self._bandit_path, "-r", str(root),
            "-f", "json",
        ]

        # Severity threshold flag
        sev = self.severity_threshold.lower()
        if sev == "high":
            cmd.append("-lll")
        elif sev == "medium":
            cmd.append("-ll")
        else:
            cmd.append("-l")

        # Auto-exclude common non-project directories
        auto_exclude = [".venv", "venv", ".env", "__pycache__", "node_modules",
                        ".git", "target", ".mypy_cache", ".pytest_cache",
                        "dist", "build", ".eggs", "*.egg-info",
                        "_scratch", ".github"]
        all_exclude = list(auto_exclude)
        if exclude:
            all_exclude.extend(exclude)
        # Bandit -x needs comma-separated paths
        # Convert relative names to absolute paths under root
        exclude_paths = []
        for pat in all_exclude:
            full = root / pat
            if full.exists():
                exclude_paths.append(str(full))
            else:
                exclude_paths.append(pat)
        if exclude_paths:
            cmd.extend(["-x", ",".join(exclude_paths)])

        cmd.extend(self.extra_args)

        logger.info(f"Running Bandit: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
                cwd=str(root),
            )
        except FileNotFoundError:
            logger.error("Bandit executable not found.")
            return []
        except subprocess.TimeoutExpired:
            logger.error("Bandit timed out after 300s.")
            return []

        # Bandit exits with 1 when issues found — expected
        raw = (result.stdout or "").strip()
        if not raw:
            logger.info("Bandit returned no output (clean or empty project).")
            return []

        # Bandit may prepend a progress bar ("Working... ---- 100% ...") before
        # the JSON.  Strip everything before the first '{'.
        json_start = raw.find("{")
        if json_start > 0:
            raw = raw[json_start:]
        elif json_start < 0:
            logger.error("Bandit output contains no JSON object.")
            return []

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Bandit JSON output: {e}")
            logger.debug(f"Raw output (first 500 chars): {raw[:500]}")
            return []

        results = data.get("results", [])
        issues = []
        for item in results:
            issue = self._to_smell_issue(item, root)
            if issue is not None:
                issues.append(issue)

        # Sort: critical first
        issues.sort(key=lambda s: (
            0 if s.severity == Severity.CRITICAL else
            1 if s.severity == Severity.WARNING else 2,
            s.file_path, s.line
        ))

        logger.info(f"Bandit found {len(issues)} security issues.")
        return issues

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
        """Build a summary dict from security issues."""
        from collections import Counter
        by_severity = Counter(s.severity for s in issues)
        by_rule = Counter(s.rule_code for s in issues)
        by_file = Counter(s.file_path for s in issues)
        by_confidence = Counter(s.confidence for s in issues)

        return {
            "total": len(issues),
            "critical": by_severity.get(Severity.CRITICAL, 0),
            "warning": by_severity.get(Severity.WARNING, 0),
            "info": by_severity.get(Severity.INFO, 0),
            "by_rule": dict(by_rule.most_common(20)),
            "by_confidence": dict(by_confidence),
            "worst_files": dict(by_file.most_common(10)),
            "source": "bandit",
        }
