"""
X-Ray LLM — Format checking, type checking analyzers.
"""

import contextlib
import os
import subprocess

from analyzers._shared import _fwd
from xray.types import FormatResult, TypeCheckResult


def check_format(directory: str) -> FormatResult:
    """Run ruff format --check to find files needing reformatting."""
    try:
        result = subprocess.run(
            ["ruff", "format", "--check", directory],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError:
        return {"error": "ruff not found. Install: uv tool install ruff"}
    except subprocess.TimeoutExpired:
        return {"error": "ruff format check timed out."}

    files = []
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if line and os.path.isfile(line):
            files.append(_fwd(os.path.relpath(line, directory)))
    for line in result.stderr.strip().split("\n"):
        line = line.strip()
        if line.startswith("Would reformat:"):
            fname = line.replace("Would reformat:", "").strip()
            if fname:
                files.append(_fwd(fname))

    return {
        "needs_format": len(files),
        "files": files[:500],
        "all_formatted": result.returncode == 0,
    }


def check_types(directory: str) -> TypeCheckResult:
    """Run ty type checker on Python files for type-safety diagnostics."""
    try:
        result = subprocess.run(
            ["ty", "check", "--output-format", "concise", directory],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError:
        return {"error": "ty not found. Install: uv tool install ty"}
    except subprocess.TimeoutExpired:
        return {"error": "ty type check timed out."}

    diagnostics = []
    raw = (result.stdout + "\n" + result.stderr).strip()
    for line in raw.split("\n"):
        line = line.strip()
        if not line or line.startswith("Found ") or line.startswith("info:"):
            continue
        # Format: file:line:col: severity[rule] message
        parts = line.split(": ", 1)
        if len(parts) >= 2:
            location = parts[0]
            rest = parts[1]
            loc_parts = location.rsplit(":", 2)
            file_path = loc_parts[0] if loc_parts else location
            diag = {
                "file": _fwd(file_path),
                "location": location,
                "message": rest,
            }
            if "error[" in rest:
                diag["severity"] = "error"
            elif "warning[" in rest:
                diag["severity"] = "warning"
            else:
                diag["severity"] = "info"
            diagnostics.append(diag)

    # Extract summary line ("Found N diagnostics")
    total = len(diagnostics)
    for line in raw.split("\n"):
        if line.strip().startswith("Found "):
            with contextlib.suppress(ValueError, IndexError):
                total = int(line.strip().split()[1])
            break

    return {
        "total_diagnostics": total,
        "errors": sum(1 for d in diagnostics if d["severity"] == "error"),
        "warnings": sum(1 for d in diagnostics if d["severity"] == "warning"),
        "diagnostics": diagnostics[:500],
        "clean": result.returncode == 0,
    }


def run_typecheck(directory: str) -> dict:
    """Run pyright type checker if available."""
    try:
        result = subprocess.run(
            ["pyright", "--outputjson", directory],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError:
        return {"error": "pyright not found. Install: npm install -g pyright"}
    except subprocess.TimeoutExpired:
        return {"error": "pyright timed out."}

    try:
        import json

        data = json.loads(result.stdout)
    except (ImportError, json.JSONDecodeError):
        return {"error": f"pyright output error: {result.stderr[:300]}"}

    diagnostics = data.get("generalDiagnostics", [])
    issues = []
    for d in diagnostics[:500]:
        issues.append(
            {
                "file": _fwd(d.get("file", "")),
                "line": d.get("range", {}).get("start", {}).get("line", 0) + 1,
                "severity": d.get("severity", "information").upper(),
                "rule": d.get("rule", ""),
                "message": d.get("message", ""),
            }
        )

    summary = data.get("summary", {})
    return {
        "issues": issues,
        "total": len(issues),
        "errors": summary.get("errorCount", 0),
        "warnings": summary.get("warningCount", 0),
        "informations": summary.get("informationCount", 0),
    }
