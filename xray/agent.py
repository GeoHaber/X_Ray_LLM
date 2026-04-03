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
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field

# Fix Windows console encoding for Unicode output (ruff, emoji, etc.)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logger = logging.getLogger(__name__)

from .llm import LLMConfig, LLMEngine, create_backend, list_backends
from .runner import TestResult, run_tests
from .scanner import (
    Finding,
    ScanResult,
    extract_code_slice,
    filter_new_findings,
    llm_classify_findings,
    load_baseline,
    scan_directory,
    suggest_fix_plan,
)
from .yaml_rules import load_yaml_rules


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
    since: str = ""  # git ref for diff-only scanning
    llm_triage: bool = False
    policy_profile: str = "balanced"
    taint_mode: str = "lite"
    include_tests: bool = False
    llm_fp_filter: bool = False  # Stage 5: LLM-based FP classification (opt-in)
    extra_rules: list[dict] = field(default_factory=list)

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

        # Merge built-in + custom YAML rules when extra rules are present
        self._rules: list[dict] | None = None
        if self.config.extra_rules:
            from .rules import ALL_RULES
            self._rules = ALL_RULES + self.config.extra_rules

    def log(self, msg: str):
        """Log a message to both the logger and internal log."""
        self._log_lines.append(msg)
        if not self._quiet:
            try:
                print(msg)
                logger.info(msg)
            except UnicodeEncodeError:
                safe = msg.encode("ascii", errors="replace").decode("ascii")
                print(safe)
                logger.info(safe)

    # ── Step 1: SCAN ────────────────────────────────────────────────────────

    def scan(self) -> ScanResult:
        """Run the pattern scanner on the project."""
        self.log("\n🔍 Step 1: SCANNING project...")

        result = scan_directory(
            self.config.project_root,
            rules=self._rules,
            exclude_patterns=self.config.exclude_patterns or None,
            since=self.config.since,
            policy_profile=self.config.policy_profile,
            taint_mode=self.config.taint_mode,
            include_tests=self.config.include_tests,
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

        if self.config.llm_triage and result.findings:
            self.log("\n🧠 LLM triage plan:")
            llm_fn = self.llm.analyze_codebase if self.llm.is_available else None
            plan = suggest_fix_plan(result.findings, llm_fn=llm_fn)
            c = plan["counts"]
            self.log(f"  total={c['total']} high={c['high']} medium={c['medium']} low={c['low']}")
            if plan.get("llm_notes"):
                for line in plan["llm_notes"].splitlines()[:8]:
                    self.log(f"  {line}")

        # Stage 5: LLM-based false positive classification (opt-in)
        if self.config.llm_fp_filter and result.findings and self.llm.is_available:
            high_findings = [f for f in result.findings if f.severity == "HIGH"]
            if high_findings:
                self.log(f"\n🧠 Stage 5: LLM false-positive filter on {len(high_findings)} HIGH findings...")
                llm_classify_findings(
                    high_findings,
                    llm_generate=self.llm.generate,
                )
                suppressed = [f for f in high_findings if f.llm_suppressed]
                self.log(
                    f"  Stage 5 LLM filter: {len(suppressed)} of {len(high_findings)} "
                    f"findings reclassified as false positives"
                )
                if suppressed:
                    self.log("  LLM classified as likely false positive:")
                    for f in suppressed:
                        self.log(f"    {f} — {f.llm_reason}")
                # Remove suppressed findings from main results
                suppressed_set = {id(f) for f in suppressed}
                result.findings = [f for f in result.findings if id(f) not in suppressed_set]
        elif self.config.llm_fp_filter and not self.llm.is_available:
            self.log("⚠️  --llm-fp-filter requires an LLM — skipping Stage 5")

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
            context = extract_code_slice(finding.file, finding.line)
            try:
                test_code = self.llm.generate_test(finding.to_dict(), context)
                tests.append(test_code)
                self.report.tests_generated += 1
                self.log(f"  ✅ Generated test for {finding.rule_id}")
            except Exception as e:
                self.report.errors.append(f"Test gen failed for {finding.rule_id}: {e}")
                self.log(f"  ❌ Failed to generate test for {finding.rule_id}: {e}")

        return tests

    # ── Step 2b: DETERMINISTIC FIXES ──────────────────────────────────────

    def apply_deterministic_fixes(self, findings: list[Finding]) -> tuple[int, list[Finding]]:
        """Apply rule-based auto-fixes (no LLM needed). Returns (count_fixed, remaining)."""
        from .fixer import FIXABLE_RULES, apply_fix

        fixable = [f for f in findings if f.rule_id in FIXABLE_RULES]
        if not fixable:
            return 0, findings

        self.log(f"\n🔧 Step 2b: DETERMINISTIC fixes for {len(fixable)} findings...")
        fixed_count = 0
        for finding in fixable:
            result = apply_fix(finding.to_dict())
            if result.get("ok"):
                fixed_count += 1
                self.report.fixes_applied += 1
                self.log(f"  ✅ Fixed {finding.rule_id} at {finding.file}:{finding.line} — {result.get('description', '')}")
            else:
                self.log(f"  ⏭  {finding.rule_id} at {finding.file}:{finding.line} — {result.get('error', 'not fixable')}")

        remaining = [f for f in findings if f.rule_id not in FIXABLE_RULES or f not in fixable]
        if fixed_count:
            self.log(f"  Applied {fixed_count}/{len(fixable)} deterministic fixes")
        return fixed_count, remaining

    # ── Step 3: GENERATE FIXES (LLM) ──────────────────────────────────────

    def generate_fixes(self, findings: list[Finding], test_error: str = "") -> list[dict]:
        """Generate code fixes for findings using the LLM."""
        if not self.config.auto_fix:
            self.log("⏭  Skipping fix generation (auto_fix=False)")
            return []

        if not self.llm.is_available:
            self.log("⚠️  LLM not available — skipping LLM fix generation")
            return []

        self.log(f"\n🔧 Step 3: LLM fixes for {len(findings)} findings...")
        fixes = []
        for finding in findings:
            context = extract_code_slice(finding.file, finding.line)
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
        backend = self.llm._backend
        if self.llm.is_available:
            self.log(f"  LLM:     {backend.backend_name}")
        else:
            self.log(f"  LLM:     Not configured ({backend.backend_type})")
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

        # Step 2b: Apply deterministic fixes first (no LLM needed)
        if self.config.auto_fix:
            det_fixed, remaining = self.apply_deterministic_fixes(remaining)

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

            # Generate LLM fixes for remaining findings
            self.generate_fixes(remaining, test_error=last_error)

            # Verify
            test_result = self.verify()

            if test_result.all_passed:
                self.log("\n🎉 All tests passed!")
                break

            # Collect failure info for next retry
            last_error = "\n".join(f"{f['test']}: {f['output'][:500]}" for f in test_result.failures)

            # Re-scan to check if findings were resolved
            new_scan = scan_directory(
                self.config.project_root,
                rules=self._rules,
                exclude_patterns=self.config.exclude_patterns or None,
                policy_profile=self.config.policy_profile,
                taint_mode=self.config.taint_mode,
                include_tests=self.config.include_tests,
            )
            allowed = self.config.severity_levels
            remaining = [f for f in new_scan.findings if f.severity in allowed]

        self.report.duration_sec = time.time() - start
        self.log("\n" + self.report.summary())
        return self.report


def _run_ruff_autofix(project_root: str, mode: str) -> bool:
    """Run Ruff autofix in safe/unsafe/dry-run modes."""
    if mode == "off":
        return True

    ruff = shutil.which("ruff")
    if not ruff:
        print("WARNING: Ruff not found in PATH; skipping autofix.")
        return False

    cmd = [ruff, "check", project_root]
    if mode == "safe":
        cmd.append("--fix")
    elif mode == "unsafe":
        cmd.extend(["--fix", "--unsafe-fixes"])
    elif mode == "dry-run":
        cmd.extend(["--fix", "--diff"])

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if out:
        try:
            print(out)
        except UnicodeEncodeError:
            print(out.encode("ascii", errors="replace").decode("ascii"))
    if err:
        try:
            print(err, file=sys.stderr)
        except UnicodeEncodeError:
            print(err.encode("ascii", errors="replace").decode("ascii"), file=sys.stderr)

    # In dry-run mode, non-zero means findings exist, not a pipeline failure.
    if mode == "dry-run":
        return True
    return proc.returncode == 0


def _quality_score(summary: dict[str, int], files_scanned: int) -> int:
    # Keep this score stable and deterministic for CI usage.
    high = int(summary.get("high", 0))
    medium = int(summary.get("medium", 0))
    low = int(summary.get("low", 0))
    density_penalty = int((high + medium + low) / max(files_scanned, 1) * 8)
    score = 100 - (high * 25) - (medium * 8) - (low * 2) - density_penalty
    return max(0, min(100, score))


def _evaluate_ci_gate(
    summary: dict[str, int],
    files_scanned: int,
    max_high: int,
    max_medium: int,
    min_score: int,
) -> dict[str, object]:
    score = _quality_score(summary, files_scanned)
    high = int(summary.get("high", 0))
    medium = int(summary.get("medium", 0))
    failures: list[str] = []
    if high > max_high:
        failures.append(f"high findings {high} > allowed {max_high}")
    if medium > max_medium:
        failures.append(f"medium findings {medium} > allowed {max_medium}")
    if score < min_score:
        failures.append(f"quality score {score} < minimum {min_score}")
    return {
        "passed": not failures,
        "score": score,
        "thresholds": {
            "max_high": max_high,
            "max_medium": max_medium,
            "min_score": min_score,
        },
        "failures": failures,
    }


def _load_snapshot(path: str) -> dict[str, object]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Snapshot must be a JSON object: {path}")
    findings = data.get("findings", [])
    if not isinstance(findings, list):
        raise ValueError(f"Snapshot 'findings' must be an array: {path}")
    summary = data.get("summary", {})
    if not isinstance(summary, dict):
        summary = {}
    return {"findings": findings, "summary": summary}


def _finding_key(item: dict[str, object]) -> tuple[str, str, int]:
    return (
        str(item.get("rule_id", "")),
        str(item.get("file", "")),
        int(item.get("line", 0) or 0),
    )


def _compare_snapshots(old_path: str, new_path: str) -> dict[str, object]:
    old = _load_snapshot(old_path)
    new = _load_snapshot(new_path)
    old_findings = [f for f in old["findings"] if isinstance(f, dict)]
    new_findings = [f for f in new["findings"] if isinstance(f, dict)]
    old_set = {_finding_key(f): f for f in old_findings}
    new_set = {_finding_key(f): f for f in new_findings}

    new_keys = sorted(set(new_set.keys()) - set(old_set.keys()))
    resolved_keys = sorted(set(old_set.keys()) - set(new_set.keys()))

    return {
        "old": {
            "path": old_path,
            "total": len(old_findings),
            "summary": old.get("summary", {}),
        },
        "new": {
            "path": new_path,
            "total": len(new_findings),
            "summary": new.get("summary", {}),
        },
        "delta": {
            "total_change": len(new_findings) - len(old_findings),
            "new_findings": [new_set[k] for k in new_keys],
            "resolved_findings": [old_set[k] for k in resolved_keys],
            "new_count": len(new_keys),
            "resolved_count": len(resolved_keys),
        },
    }


RECIPES = {
    "security-audit": {
        "severity": "MEDIUM",
        "policy_profile": "strict",
        "taint_mode": "strict",
        "include_tests": False,
        "description": "Deep security scan with strict taint analysis",
    },
    "pre-commit": {
        "severity": "HIGH",
        "policy_profile": "balanced",
        "taint_mode": "lite",
        "include_tests": False,
        "incremental": True,
        "description": "Fast scan for pre-commit hooks (HIGH only, incremental)",
    },
    "compliance": {
        "severity": "LOW",
        "policy_profile": "strict",
        "taint_mode": "strict",
        "include_tests": True,
        "description": "Full compliance scan with all rules, SARIF output recommended",
    },
    "code-review": {
        "severity": "MEDIUM",
        "policy_profile": "balanced",
        "taint_mode": "lite",
        "include_tests": False,
        "description": "Balanced scan for code review",
    },
    "quick": {
        "severity": "HIGH",
        "policy_profile": "relaxed-tests",
        "taint_mode": "off",
        "include_tests": False,
        "description": "Fastest possible scan (HIGH only, no taint)",
    },
}


def main():
    """CLI entry point."""
    import argparse
    from pathlib import Path

    from .compat import check_environment
    from .config import XRayConfig
    from .sarif import write_sarif

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
            "  python -m xray .                              # scan current dir\n"
            "  python -m xray ./src --dry-run                # scan only, no fixes\n"
            "  python -m xray . --severity HIGH              # only HIGH severity\n"
            "  python -m xray . --fix                        # scan + auto-fix\n"
            "  python -m xray . --format sarif -o out.sarif  # SARIF output\n"
            "  python -m xray . --incremental                # incremental scan\n"
            "  python -m xray . --baseline prev.json         # show new findings only\n"
            "  python -m xray . --since HEAD~5                # scan only files changed in last 5 commits\n"
        ),
    )
    parser.add_argument("project", nargs="?", default=".", help="Project root directory to scan")
    parser.add_argument("--test-path", default="tests/", help="Path to test directory (default: tests/)")
    parser.add_argument("--dry-run", action="store_true", help="Scan only, no fixes")
    parser.add_argument("--fix", action="store_true", help="Enable auto-fix mode (requires LLM)")
    parser.add_argument(
        "--severity",
        default="",
        choices=["HIGH", "MEDIUM", "LOW"],
        help="Minimum severity to report (overrides pyproject.toml)",
    )
    parser.add_argument("--max-retries", type=int, default=3, help="Max fix retries (default: 3)")
    parser.add_argument("--model", default="", help="Path to GGUF model file")
    parser.add_argument(
        "--llm-backend",
        choices=["auto", "zen_core", "gguf", "openai", "anthropic"],
        default="auto",
        help="LLM backend to use (default: auto — tries zen_core/gguf/openai/anthropic). Use --list-backends to see status.",
    )
    parser.add_argument("--exclude", nargs="*", default=[], help="Regex patterns to exclude from scan")
    parser.add_argument(
        "--format",
        dest="output_format",
        default="",
        choices=["text", "json", "sarif"],
        help="Output format (default: text)",
    )
    parser.add_argument("-o", "--output", default="", help="Write report to file")
    parser.add_argument("--baseline", default="", help="Baseline JSON to filter out known findings")
    parser.add_argument("--incremental", action="store_true", help="Skip files unchanged since last scan")
    parser.add_argument("--no-parallel", action="store_true", help="Disable parallel scanning")
    parser.add_argument("--since", default="", help="Git ref — only scan files changed since (e.g. HEAD~5, main)")
    parser.add_argument(
        "--policy-profile",
        choices=["strict", "balanced", "relaxed-tests"],
        default="",
        help="Policy profile for noise-vs-signal tuning.",
    )
    parser.add_argument(
        "--taint-mode",
        choices=["off", "lite", "strict"],
        default="",
        help="Taint analysis depth for SEC-004/005/010.",
    )
    parser.add_argument(
        "--ruff-fix",
        choices=["off", "safe", "unsafe", "dry-run"],
        default="off",
        help="Run Ruff autofix before scanning.",
    )
    parser.add_argument(
        "--llm-triage",
        action="store_true",
        help="Use LLM to generate prioritized remediation guidance after scan.",
    )
    parser.add_argument(
        "--llm-fp-filter",
        action="store_true",
        help="Stage 5: Use LLM to classify HIGH-severity findings as true/false positives (requires LLM).",
    )
    parser.add_argument(
        "--compare",
        nargs=2,
        metavar=("OLD_JSON", "NEW_JSON"),
        help="Compare two scan JSON snapshots and report new/resolved findings.",
    )
    parser.add_argument(
        "--include-tests",
        action="store_true",
        help="Re-enable all rules for test files (overrides default test-file suppression).",
    )
    parser.add_argument("--ci-gate", action="store_true", help="Enable CI quality gate checks.")
    parser.add_argument("--ci-max-high", type=int, default=0, help="Max allowed HIGH findings for --ci-gate.")
    parser.add_argument("--ci-max-medium", type=int, default=25, help="Max allowed MEDIUM findings for --ci-gate.")
    parser.add_argument("--ci-min-score", type=int, default=70, help="Minimum quality score for --ci-gate.")

    parser.add_argument(
        "--recipe",
        choices=list(RECIPES.keys()),
        default="",
        help="Apply a preset scan recipe. Use --list-recipes to see available presets. Recipe settings are applied before other CLI args, so explicit flags override.",
    )
    parser.add_argument(
        "--list-recipes",
        action="store_true",
        help="Print available scan recipes with descriptions and exit.",
    )
    parser.add_argument(
        "--list-backends",
        action="store_true",
        help="Print available LLM backends with their status and exit.",
    )
    parser.add_argument(
        "--rules-dir",
        default="",
        help="Directory containing custom YAML rule files (default: .xray/rules/ in project root).",
    )

    # Keep legacy --json flag for backwards compatibility
    parser.add_argument("--json", action="store_true", help=argparse.SUPPRESS)

    args = parser.parse_args()

    # ── --list-recipes: print and exit ──────────────────────────────────────
    if args.list_recipes:
        print("Available scan recipes:\n")
        for name, recipe in RECIPES.items():
            desc = recipe["description"]
            sev = recipe["severity"]
            taint = recipe.get("taint_mode", "lite")
            profile = recipe.get("policy_profile", "balanced")
            extras = []
            if recipe.get("incremental"):
                extras.append("incremental")
            if recipe.get("include_tests"):
                extras.append("include-tests")
            flags = f"severity={sev}, policy={profile}, taint={taint}"
            if extras:
                flags += ", " + ", ".join(extras)
            print(f"  {name:20s} {desc}")
            print(f"  {'':<20s} [{flags}]")
            print()
        raise SystemExit(0)

    # ── --list-backends: print and exit ──────────────────────────────────────
    if args.list_backends:
        print(list_backends())
        raise SystemExit(0)

    # ── Apply recipe defaults BEFORE other CLI overrides ────────────────────
    if args.recipe:
        recipe = RECIPES[args.recipe]
        if not args.severity:
            args.severity = recipe["severity"]
        if not args.policy_profile:
            args.policy_profile = recipe.get("policy_profile", "")
        if not args.taint_mode:
            args.taint_mode = recipe.get("taint_mode", "")
        if recipe.get("include_tests") and not args.include_tests:
            args.include_tests = True
        if recipe.get("incremental") and not args.incremental:
            args.incremental = True

    if args.compare:
        comparison = _compare_snapshots(args.compare[0], args.compare[1])
        if args.output_format == "json" or args.json:
            body = json.dumps(comparison, indent=2)
        else:
            delta = comparison["delta"]
            body = "\n".join(
                [
                    f"Compared: {comparison['old']['path']} -> {comparison['new']['path']}",
                    f"Totals: {comparison['old']['total']} -> {comparison['new']['total']} (delta {delta['total_change']:+d})",
                    f"New findings: {delta['new_count']}",
                    f"Resolved findings: {delta['resolved_count']}",
                ]
            )
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(body + "\n")
            print(f"Comparison written to {args.output}")
        else:
            print(body)
        raise SystemExit(0)

    # Load pyproject.toml config, then merge CLI overrides
    xray_config = XRayConfig.from_pyproject(args.project)
    xray_config.merge_cli(
        severity=args.severity,
        exclude=args.exclude or None,
        output_format=args.output_format or ("json" if args.json else ""),
        incremental=args.incremental or None,
        parallel=False if args.no_parallel else None,
        policy_profile=args.policy_profile,
        taint_mode=args.taint_mode,
    )

    effective_severity = xray_config.severity
    effective_format = xray_config.output_format

    # ── Load custom YAML rules ──────────────────────────────────────────────
    rules_dir = args.rules_dir or xray_config.rules_dir
    if not rules_dir:
        rules_dir = str(Path(args.project) / ".xray" / "rules")
    yaml_rules = load_yaml_rules(rules_dir)

    # Fix 5: Print custom rule count
    if yaml_rules:
        print(f"Custom rules: {len(yaml_rules)} loaded from {rules_dir}")
    elif args.rules_dir and not Path(args.rules_dir).is_dir():
        print(f"Warning: --rules-dir '{args.rules_dir}' does not exist", file=sys.stderr)

    config = AgentConfig(
        project_root=args.project,
        test_path=args.test_path,
        dry_run=args.dry_run or not args.fix,
        auto_fix=args.fix,
        auto_test=args.fix,
        severity_threshold=effective_severity,
        max_fix_retries=args.max_retries,
        exclude_patterns=xray_config.exclude_patterns,
        since=args.since,
        llm_triage=args.llm_triage,
        llm_fp_filter=args.llm_fp_filter,
        policy_profile=xray_config.policy_profile,
        taint_mode=xray_config.taint_mode,
        include_tests=args.include_tests,
        extra_rules=yaml_rules,
    )

    if args.ruff_fix != "off":
        ok = _run_ruff_autofix(args.project, args.ruff_fix)
        if not ok:
            print("ERROR: Ruff autofix failed.", file=sys.stderr)
            raise SystemExit(1)

    backend_type = args.llm_backend
    if backend_type in ("auto", "gguf"):
        # For GGUF / auto, honour --model flag and env vars via LLMConfig.
        llm_config = LLMConfig(model_path=args.model or os.environ.get("XRAY_MODEL_PATH", ""))
        backend = create_backend(backend_type, config=llm_config)
    else:
        backend = create_backend(backend_type)
    llm = LLMEngine(backend=backend)

    quiet = effective_format in ("json", "sarif")

    # ── Print effective configuration block (Fix 8 + Fix 10) ───────────────
    if not quiet:
        from .rules import ALL_RULES
        builtin_count = len(ALL_RULES)
        custom_count = len(yaml_rules)

        print()
        print("--- Configuration " + "-" * 27)
        print(f"Severity: {effective_severity}")
        print(f"Policy:   {xray_config.policy_profile}")
        print(f"Taint:    {xray_config.taint_mode}")
        print(f"Backend:  {backend.backend_name}")
        rules_str = f"{builtin_count} built-in"
        if custom_count > 0:
            rules_str += f" + {custom_count} custom"
        print(f"Rules:    {rules_str}")
        if args.recipe:
            recipe_info = RECIPES[args.recipe]
            print(f"Recipe:   {args.recipe} -- {recipe_info['description']}")
        print("-" * 45)
        print()

    agent = XRayAgent(config=config, llm=llm, quiet=quiet)

    if effective_format in ("json", "sarif"):
        # Structured output mode: scan and output data
        result = agent.scan()

        # Apply baseline filtering
        if args.baseline:
            baseline = load_baseline(args.baseline)
            result.findings = filter_new_findings(result.findings, baseline)

        if effective_format == "sarif":
            from . import __version__

            if args.output:
                write_sarif(
                    [f.to_dict() for f in result.findings],
                    args.output,
                    tool_version=__version__,
                )
                print(f"SARIF report written to {args.output}")
            else:
                from .sarif import sarif_to_json_string

                sys.stdout.write(
                    sarif_to_json_string(
                        [f.to_dict() for f in result.findings],
                        tool_version=__version__,
                    )
                    + "\n"
                )
        else:
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
            gate_result = None
            if args.ci_gate:
                gate_result = _evaluate_ci_gate(
                    output["summary"],
                    result.files_scanned,
                    args.ci_max_high,
                    args.ci_max_medium,
                    args.ci_min_score,
                )
                output["quality_gate"] = gate_result
            json_str = json.dumps(output, indent=2)
            if args.output:
                with open(args.output, "w", encoding="utf-8") as f:
                    f.write(json_str)
                print(f"JSON report written to {args.output}")
            else:
                sys.stdout.write(json_str + "\n")
            if gate_result and not gate_result["passed"]:
                raise SystemExit(2)
    else:
        report = agent.run()

        # Write text report to file if requested
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(report.summary())
            print(f"Report written to {args.output}")
        else:
            # Ensure summary is visible even without --output
            print(report.summary())

        if args.ci_gate and report.scan_result:
            summary = {
                "total": len(report.scan_result.findings),
                "high": report.scan_result.high_count,
                "medium": report.scan_result.medium_count,
                "low": report.scan_result.low_count,
            }
            gate_result = _evaluate_ci_gate(
                summary,
                report.scan_result.files_scanned,
                args.ci_max_high,
                args.ci_max_medium,
                args.ci_min_score,
            )
            print(f"CI gate score: {gate_result['score']} (pass={gate_result['passed']})")
            if gate_result["failures"]:
                print("CI gate failures:")
                for failure in gate_result["failures"]:
                    print(f"  - {failure}")
            if not gate_result["passed"]:
                raise SystemExit(2)


if __name__ == "__main__":
    main()
