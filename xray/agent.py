"""
X-Ray Agent — Self-improving code quality loop.

The core loop:
  1. SCAN    → Pattern-match against rule database
  2. TEST    → Generate tests for findings (LLM)
  3. FIX     → Generate patches for findings (LLM)
  4. VERIFY  → Run all tests
  5. LOOP    → If failures → back to 3 (max retries)
  6. REPORT  → Generate summary
"""

import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

from .llm import LLMConfig, LLMEngine
from .runner import TestResult, run_tests
from .scanner import Finding, ScanResult, scan_project


@dataclass
class AgentConfig:
    """Configuration for the X-Ray agent."""

    project_root: str = "."
    test_path: str = "tests/"
    max_fix_retries: int = 3
    auto_fix: bool = True  # generate fixes automatically
    auto_test: bool = True  # generate tests automatically
    dry_run: bool = False  # scan only, no changes
    severity_threshold: str = "MEDIUM"  # skip LOW findings
    exclude_patterns: list[str] = field(default_factory=list)
    python_exe: str | None = None

    @property
    def severity_levels(self) -> list[str]:
        levels = ["HIGH", "MEDIUM", "LOW"]
        idx = levels.index(self.severity_threshold)
        return levels[: idx + 1]


@dataclass
class AgentReport:
    """Final report from an agent run."""

    scan_result: ScanResult | None = None
    tests_generated: int = 0
    fixes_applied: int = 0
    fix_attempts: int = 0
    test_result: TestResult | None = None
    duration_sec: float = 0.0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = ["=" * 60, "  X-Ray Agent Report", "=" * 60, ""]
        if self.scan_result:
            lines.append(self.scan_result.summary())
            lines.append("")
        lines.append(f"Tests generated:  {self.tests_generated}")
        lines.append(f"Fixes applied:    {self.fixes_applied}")
        lines.append(f"Fix attempts:     {self.fix_attempts}")
        if self.test_result:
            lines.append(f"Test result:      {self.test_result.summary()}")
        lines.append(f"Duration:         {self.duration_sec:.1f}s")
        if self.errors:
            lines.append(f"\nErrors ({len(self.errors)}):")
            for e in self.errors:
                lines.append(f"  • {e}")
        lines.append("=" * 60)
        return "\n".join(lines)


def _get_source_context(filepath: str, line: int, context: int = 10) -> str:
    """Extract source code context around a line."""
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        start = max(0, line - context - 1)
        end = min(len(lines), line + context)
        numbered = []
        for i, ln in enumerate(lines[start:end], start=start + 1):
            marker = " >>>" if i == line else "    "
            numbered.append(f"{marker} {i:4d} | {ln.rstrip()}")
        return "\n".join(numbered)
    except (OSError, PermissionError):
        return f"(Could not read {filepath})"


class XRayAgent:
    """The main self-improving code quality agent."""

    def __init__(self, config: AgentConfig | None = None, llm: LLMEngine | None = None, quiet: bool = False):
        self.config = config or AgentConfig()
        self.llm = llm or LLMEngine()
        self.report = AgentReport()
        self._log_lines: list[str] = []
        self._quiet = quiet

    def log(self, msg: str):
        """Log a message to both the logger and internal log."""
        self._log_lines.append(msg)
        if not self._quiet:
            try:
                logger.info(msg)
            except UnicodeEncodeError:
                logger.info(msg.encode("ascii", errors="replace").decode("ascii"))

    # ── Step 1: SCAN ────────────────────────────────────────────────────────

    def scan(self) -> ScanResult:
        """Run the pattern scanner on the project."""
        self.log("\n🔍 Step 1: SCANNING project...")
        result = scan_project(
            self.config.project_root,
            config={"exclude_patterns": self.config.exclude_patterns},
        )
        # Filter by severity threshold
        allowed = self.config.severity_levels
        result.findings = [f for f in result.findings if f.severity in allowed]

        self.report.scan_result = result
        self.log(result.summary())

        if result.findings:
            self.log("\nFindings:")
            for f in result.findings:
                self.log(f"  {f}")
        else:
            self.log("  ✅ No issues found!")

        return result

    # ── Step 2: GENERATE TESTS ──────────────────────────────────────────────

    def generate_tests(self, findings: list[Finding]) -> list[str]:
        """Generate test code for each finding using the LLM."""
        if not self.config.auto_test:
            self.log("⏭  Skipping test generation (auto_test=False)")
            return []

        if not self.llm.is_available:
            self.log("⚠️  LLM not available — skipping test generation")
            self.log("   Set XRAY_MODEL_PATH to enable LLM features")
            return []

        self.log(f"\n🧪 Step 2: GENERATING tests for {len(findings)} findings...")
        tests = []
        for finding in findings:
            context = _get_source_context(finding.file, finding.line)
            try:
                test_code = self.llm.generate_test(finding.to_dict(), context)
                tests.append(test_code)
                self.report.tests_generated += 1
                self.log(f"  ✅ Generated test for {finding.rule_id}")
            except Exception as e:
                self.report.errors.append(f"Test gen failed for {finding.rule_id}: {e}")
                self.log(f"  ❌ Failed to generate test for {finding.rule_id}: {e}")

        return tests

    # ── Step 3: GENERATE FIXES ──────────────────────────────────────────────

    def generate_fixes(self, findings: list[Finding], test_error: str = "") -> list[dict]:
        """Generate code fixes for findings using the LLM."""
        if not self.config.auto_fix:
            self.log("⏭  Skipping fix generation (auto_fix=False)")
            return []

        if not self.llm.is_available:
            self.log("⚠️  LLM not available — skipping fix generation")
            return []

        self.log(f"\n🔧 Step 3: GENERATING fixes for {len(findings)} findings...")
        fixes = []
        for finding in findings:
            context = _get_source_context(finding.file, finding.line)
            try:
                fix_code = self.llm.generate_fix(finding.to_dict(), context, test_error=test_error)
                fixes.append(
                    {
                        "finding": finding,
                        "fix": fix_code,
                    }
                )
                self.report.fixes_applied += 1
                self.log(f"  ✅ Generated fix for {finding.rule_id}")
            except Exception as e:
                self.report.errors.append(f"Fix gen failed for {finding.rule_id}: {e}")
                self.log(f"  ❌ Failed to generate fix for {finding.rule_id}: {e}")

        return fixes

    # ── Step 4: VERIFY ──────────────────────────────────────────────────────

    def verify(self) -> TestResult:
        """Run the test suite and return results."""
        test_path = os.path.join(self.config.project_root, self.config.test_path)
        if not os.path.exists(test_path):
            self.log(f"⚠️  Test path not found: {test_path}")
            return TestResult(output="Test path not found")

        self.log("\n✅ Step 4: VERIFYING (running tests)...")
        result = run_tests(
            test_path,
            python_exe=self.config.python_exe,
        )
        self.report.test_result = result
        self.log(f"  {result.summary()}")
        return result

    # ── Step 5: THE LOOP ────────────────────────────────────────────────────

    def run(self) -> AgentReport:
        """Execute the full X-Ray agent loop."""
        start = time.time()
        self.log("=" * 60)
        self.log("  🔬 X-Ray Agent — Self-Improving Code Quality")
        self.log("=" * 60)
        self.log(f"  Project: {os.path.abspath(self.config.project_root)}")
        self.log(f"  Mode:    {'Dry Run (scan only)' if self.config.dry_run else 'Full (scan + fix)'}")
        self.log(f"  LLM:     {'Available' if self.llm.is_available else 'Not configured'}")
        self.log("")

        # Step 1: Scan
        scan_result = self.scan()

        if not scan_result.findings:
            self.report.duration_sec = time.time() - start
            self.log("\n" + self.report.summary())
            return self.report

        if self.config.dry_run:
            self.report.duration_sec = time.time() - start
            self.log("\n🏁 Dry run complete — no changes made.")
            self.log("\n" + self.report.summary())
            return self.report

        # Steps 2-5: Generate tests, fix, verify, loop
        remaining = list(scan_result.findings)
        retries = 0
        last_error = ""

        while remaining and retries < self.config.max_fix_retries:
            retries += 1
            self.report.fix_attempts = retries
            self.log(f"\n{'─' * 40}")
            self.log(f"  Iteration {retries}/{self.config.max_fix_retries}")
            self.log(f"  {len(remaining)} findings remaining")
            self.log(f"{'─' * 40}")

            # Generate tests
            self.generate_tests(remaining)

            # Generate fixes
            self.generate_fixes(remaining, test_error=last_error)

            # Verify
            test_result = self.verify()

            if test_result.all_passed:
                self.log("\n🎉 All tests passed!")
                break

            # Collect failure info for next retry
            last_error = "\n".join(f"{f['test']}: {f['output'][:500]}" for f in test_result.failures)

            # Re-scan to check if findings were resolved
            new_scan = scan_project(
                self.config.project_root,
                config={"exclude_patterns": self.config.exclude_patterns},
            )
            allowed = self.config.severity_levels
            remaining = [f for f in new_scan.findings if f.severity in allowed]

        self.report.duration_sec = time.time() - start
        self.log("\n" + self.report.summary())
        return self.report


def main():
    """CLI entry point."""
    import argparse

    from .compat import check_environment, environment_summary

    ok, problems = check_environment()
    if not ok:
        for p in problems:
            print(p, file=sys.stderr)
        raise SystemExit(1)

    parser = argparse.ArgumentParser(
        description="X-Ray LLM — Self-improving code quality agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m xray.agent .                    # scan current dir\n"
            "  python -m xray.agent ./src --dry-run      # scan only, no fixes\n"
            "  python -m xray.agent . --severity HIGH    # only HIGH severity\n"
            "  python -m xray.agent . --fix              # scan + auto-fix\n"
        ),
    )
    parser.add_argument("project", nargs="?", default=".", help="Project root directory to scan")
    parser.add_argument("--test-path", default="tests/", help="Path to test directory (default: tests/)")
    parser.add_argument("--dry-run", action="store_true", help="Scan only, no fixes")
    parser.add_argument("--fix", action="store_true", help="Enable auto-fix mode (requires LLM)")
    parser.add_argument(
        "--severity",
        default="MEDIUM",
        choices=["HIGH", "MEDIUM", "LOW"],
        help="Minimum severity to report (default: MEDIUM)",
    )
    parser.add_argument("--max-retries", type=int, default=3, help="Max fix retries (default: 3)")
    parser.add_argument("--model", default="", help="Path to GGUF model file")
    parser.add_argument("--exclude", nargs="*", default=[], help="Regex patterns to exclude from scan")
    parser.add_argument("--json", action="store_true", help="Output findings as JSON")

    args = parser.parse_args()

    config = AgentConfig(
        project_root=args.project,
        test_path=args.test_path,
        dry_run=args.dry_run or not args.fix,
        auto_fix=args.fix,
        auto_test=args.fix,
        severity_threshold=args.severity,
        max_fix_retries=args.max_retries,
        exclude_patterns=args.exclude,
    )

    llm_config = LLMConfig(model_path=args.model or os.environ.get("XRAY_MODEL_PATH", ""))
    llm = LLMEngine(config=llm_config)

    agent = XRayAgent(config=config, llm=llm, quiet=args.json)

    if args.json:
        # JSON mode: scan and output structured data
        result = agent.scan()
        output = {
            "files_scanned": result.files_scanned,
            "rules_checked": result.rules_checked,
            "findings": [f.to_dict() for f in result.findings],
            "summary": {
                "total": len(result.findings),
                "high": result.high_count,
                "medium": result.medium_count,
                "low": result.low_count,
            },
        }
        sys.stdout.write(json.dumps(output, indent=2) + "\n")
    else:
        agent.run()


if __name__ == "__main__":
    main()
