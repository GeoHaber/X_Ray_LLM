"""
X-Ray SCA — Software Composition Analysis.

Wraps pip-audit to detect known vulnerabilities in Python dependencies.
Integrates results into the X-Ray finding format.
"""

import json
import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def _empty_summary() -> dict:
    return {"total": 0, "critical": 0, "high": 0, "medium": 0, "low": 0}


def _map_severity(aliases: list[str], vuln_id: str) -> str:
    """Heuristic severity mapping based on CVE/GHSA ID patterns."""
    identifier = vuln_id.upper()
    for alias in aliases:
        if alias.upper().startswith("CVE-"):
            return "HIGH"
    if identifier.startswith("GHSA-"):
        return "HIGH"
    if identifier.startswith("PYSEC-"):
        return "MEDIUM"
    return "MEDIUM"


def scan_dependencies(project_root: str) -> dict:
    """Scan Python dependencies for known vulnerabilities.

    Looks for requirements.txt and pyproject.toml, runs pip-audit,
    and returns results in X-Ray compatible format.

    Returns:
        {
            "vulnerabilities": [...],
            "summary": {"total": N, "critical": N, "high": N, "medium": N, "low": N},
            "error": "" or error message
        }
    """
    pip_audit = shutil.which("pip-audit")
    if not pip_audit:
        return {"vulnerabilities": [], "summary": _empty_summary(), "error": "pip-audit not installed"}

    root = Path(project_root)
    req_files = []
    for name in ("requirements.txt", "requirements-dev.txt"):
        candidate = root / name
        if candidate.is_file():
            req_files.append(str(candidate))

    if not req_files:
        pyproject = root / "pyproject.toml"
        if not pyproject.is_file():
            return {"vulnerabilities": [], "summary": _empty_summary(), "error": "No requirements files found"}

    # Run pip-audit with JSON output
    cmd = [pip_audit, "--format", "json", "--output", "-"]
    for rf in req_files:
        cmd.extend(["-r", rf])

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=project_root,
        )
    except subprocess.TimeoutExpired:
        return {"vulnerabilities": [], "summary": _empty_summary(), "error": "pip-audit timed out"}
    except Exception as e:
        return {"vulnerabilities": [], "summary": _empty_summary(), "error": str(e)}

    # Parse output (pip-audit returns JSON on stdout)
    vulns = []
    try:
        data = json.loads(proc.stdout)
        dependencies = data.get("dependencies", [])
        for dep in dependencies:
            for vuln in dep.get("vulns", []):
                severity = _map_severity(vuln.get("aliases", []), vuln.get("id", ""))
                vulns.append(
                    {
                        "rule_id": f"SCA-{vuln.get('id', 'UNKNOWN')[:20]}",
                        "severity": severity,
                        "package": dep.get("name", "unknown"),
                        "installed_version": dep.get("version", "?"),
                        "fixed_versions": vuln.get("fix_versions", []),
                        "description": (
                            f"Vulnerability {vuln.get('id', '')} in {dep.get('name', '')} {dep.get('version', '')}"
                        ),
                        "vuln_id": vuln.get("id", ""),
                        "aliases": vuln.get("aliases", []),
                        "fix_hint": (
                            f"Upgrade {dep.get('name', '')} to {', '.join(vuln.get('fix_versions', ['latest']))}"
                        ),
                    }
                )
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Failed to parse pip-audit output: %s", e)
        if proc.stderr:
            return {"vulnerabilities": [], "summary": _empty_summary(), "error": proc.stderr[:500]}

    summary = {
        "total": len(vulns),
        "critical": sum(1 for v in vulns if v["severity"] == "CRITICAL"),
        "high": sum(1 for v in vulns if v["severity"] == "HIGH"),
        "medium": sum(1 for v in vulns if v["severity"] == "MEDIUM"),
        "low": sum(1 for v in vulns if v["severity"] == "LOW"),
    }

    return {"vulnerabilities": vulns, "summary": summary, "error": ""}
