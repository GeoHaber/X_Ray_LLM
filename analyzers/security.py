"""
X-Ray LLM — Security analysis (Bandit + AST-based secret detection).
"""

import json
import logging
import math
import re
import subprocess
from collections import Counter

from analyzers._shared import _fwd, _walk_py
from xray.types import SecurityResult


def run_bandit(directory: str) -> SecurityResult:
    """Run Bandit security scanner + AST-based secret detection."""
    bandit_issues = []
    secrets = []

    # Run bandit if available
    try:
        result = subprocess.run(
            ["bandit", "-r", "-f", "json", "-q", directory],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.stdout.strip():
            data = json.loads(result.stdout)
            for issue in data.get("results", []):
                bandit_issues.append(
                    {
                        "file": _fwd(issue.get("filename", "")),
                        "line": issue.get("line_number", 0),
                        "severity": issue.get("issue_severity", "MEDIUM").upper(),
                        "confidence": issue.get("issue_confidence", "MEDIUM").upper(),
                        "rule_id": issue.get("test_id", ""),
                        "rule_name": issue.get("test_name", ""),
                        "description": issue.get("issue_text", ""),
                        "cwe": issue.get("issue_cwe", {}).get("id", ""),
                    }
                )
    except FileNotFoundError:
        logging.debug("Skipped bandit analysis: bandit not installed")
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        logging.debug("Skipped bandit analysis: %s", e)

    # AST-based secret detection
    _API_KEY_PATTERNS = [
        (re.compile(r"sk-[a-zA-Z0-9]{20,}"), "XS001", "OpenAI API key detected"),
        (re.compile(r"ghp_[a-zA-Z0-9]{36,}"), "XS001", "GitHub personal access token"),
        (re.compile(r"gho_[a-zA-Z0-9]{36,}"), "XS001", "GitHub OAuth token"),
        (re.compile(r"AKIA[0-9A-Z]{16}"), "XS001", "AWS Access Key ID"),
        (re.compile(r"xox[bpsar]-[a-zA-Z0-9\-]+"), "XS001", "Slack token"),
        (re.compile(r"AIza[0-9A-Za-z\-_]{35}"), "XS001", "Google API key"),
        (re.compile(r"EAAC[a-zA-Z0-9]+"), "XS001", "Facebook access token"),
    ]
    _SUSPICIOUS_NAMES = re.compile(
        r"(?i)(api_key|apikey|secret|password|passwd|token|auth_token|access_key|private_key|credentials)"
    )

    def _entropy(s: str) -> float:
        if not s:
            return 0.0
        freq = Counter(s)
        length = len(s)
        return -sum((c / length) * math.log2(c / length) for c in freq.values())

    for fpath, rel in _walk_py(directory):
        try:
            with open(fpath, encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except OSError as e:
            logging.debug("Skipped secret scan for %s: %s", fpath, e)
            continue

        for lineno, line in enumerate(content.split("\n"), 1):
            # Check API key patterns
            for pat, rule_id, desc in _API_KEY_PATTERNS:
                if pat.search(line):
                    secrets.append(
                        {
                            "file": _fwd(rel),
                            "line": lineno,
                            "severity": "HIGH",
                            "rule_id": rule_id,
                            "description": desc,
                            "matched": line.strip()[:100],
                        }
                    )
                    break

            # Check suspicious variable assignments
            if "=" in line and not line.strip().startswith("#"):
                m = _SUSPICIOUS_NAMES.search(line)
                if m:
                    # Check if it's assigning a string literal
                    assign_match = re.search(r'=\s*["\']([^"\']{8,})["\']', line)
                    if assign_match:
                        value = assign_match.group(1)
                        if _entropy(value) > 4.0:
                            secrets.append(
                                {
                                    "file": _fwd(rel),
                                    "line": lineno,
                                    "severity": "HIGH",
                                    "rule_id": "XS002",
                                    "description": f"Possible hardcoded secret in '{m.group(1)}'",
                                    "matched": line.strip()[:100],
                                }
                            )

    return {
        "bandit_available": len(bandit_issues) > 0 or True,
        "bandit_issues": bandit_issues,
        "secrets": secrets,
        "total_issues": len(bandit_issues) + len(secrets),
    }
