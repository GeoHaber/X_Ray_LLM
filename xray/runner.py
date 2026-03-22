"""
X-Ray Test Runner — Executes pytest and captures results.
"""

import logging
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class TestResult:
    """Result of a pytest execution."""

    __test__ = False  # Prevent pytest from collecting this dataclass

    passed: int = 0
    failed: int = 0
    errors: int = 0
    total: int = 0
    output: str = ""
    failures: list[dict] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return self.failed == 0 and self.errors == 0 and self.total > 0

    def summary(self) -> str:
        status = "✅ ALL PASSED" if self.all_passed else "❌ FAILURES"
        return f"{status}: {self.passed}/{self.total} passed, {self.failed} failed, {self.errors} errors"


def run_tests(test_path: str, timeout: int = 120, python_exe: str | None = None) -> TestResult:
    """Run pytest on the given path and return structured results."""
    exe = python_exe or sys.executable
    cmd = [
        exe,
        "-m",
        "pytest",
        test_path,
        "-v",
        "--timeout",
        str(timeout),
        "--tb=short",
        "-q",
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 30,
            cwd=str(Path(test_path).parent.parent) if "/" in test_path or "\\" in test_path else ".",
        )
        output = proc.stdout + proc.stderr
    except subprocess.TimeoutExpired:
        logger.debug("Test run timed out for %s", test_path)
        return TestResult(output="TIMEOUT: Tests exceeded time limit")
    except FileNotFoundError:
        logger.debug("Python executable not found: %s", exe)
        return TestResult(output=f"ERROR: Python executable not found: {exe}")

    result = TestResult(output=output)

    # Parse the summary line: "X passed, Y failed, Z errors"
    for line in output.split("\n"):
        line = line.strip()
        if "passed" in line or "failed" in line or "error" in line:
            import re

            m_passed = re.search(r"(\d+)\s+passed", line)
            m_failed = re.search(r"(\d+)\s+failed", line)
            m_errors = re.search(r"(\d+)\s+error", line)
            if m_passed:
                result.passed = int(m_passed.group(1))
            if m_failed:
                result.failed = int(m_failed.group(1))
            if m_errors:
                result.errors = int(m_errors.group(1))
            result.total = result.passed + result.failed + result.errors

    # Extract failure details
    if result.failed > 0:
        in_failure = False
        current_failure: dict = {}
        for line in output.split("\n"):
            if line.startswith("FAILED"):
                if current_failure:
                    result.failures.append(current_failure)
                test_name = line.split(" ")[1] if len(line.split(" ")) > 1 else line
                current_failure = {"test": test_name, "output": ""}
                in_failure = True
            elif in_failure and line.strip():
                current_failure["output"] += line + "\n"
        if current_failure:
            result.failures.append(current_failure)

    return result
