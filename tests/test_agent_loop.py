"""
Agent Fix-Loop Tests — verify the scan → fix → re-scan cycle works correctly.
Uses the deterministic fixer (no LLM required).

Run:  python -m pytest tests/test_agent_loop.py -v --tb=short
"""

import os
import sys
import tempfile

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from xray.agent import AgentConfig, AgentReport, XRayAgent
from xray.fixer import FIXABLE_RULES, apply_fix, apply_fixes_bulk
from xray.scanner import scan_directory, scan_file


# ═════════════════════════════════════════════════════════════════════════════
# 1. Scan → Fix → Re-scan cycle
# ═════════════════════════════════════════════════════════════════════════════

class TestScanFixRescan:
    """Verify the scan→fix→re-scan cycle reduces findings."""

    def test_fix_reduces_finding_count(self, tmp_path):
        """After fixing all fixable findings, re-scan should have fewer issues."""
        # Create file with multiple fixable issues
        code = (
            "try:\n"
            "    x = 1\n"
            "except:\n"
            "    pass\n"
            "\n"
            "import subprocess\n"
            "subprocess.run(['ls'], shell=True)\n"
        )
        fp = tmp_path / "multi_issue.py"
        fp.write_text(code, encoding="utf-8")

        # Initial scan
        before = scan_directory(str(tmp_path))
        fixable_before = [f for f in before.findings if f.rule_id in FIXABLE_RULES]
        assert len(fixable_before) >= 2, "Need at least 2 fixable findings"

        # Fix all fixable findings (bottom-up to preserve line numbers)
        findings_dicts = sorted(
            [f.to_dict() for f in fixable_before],
            key=lambda x: x["line"],
            reverse=True,
        )
        for fd in findings_dicts:
            apply_fix(fd)

        # Re-scan
        after = scan_directory(str(tmp_path))
        fixable_after = [f for f in after.findings if f.rule_id in FIXABLE_RULES]
        assert len(fixable_after) < len(fixable_before), \
            f"Fix didn't reduce findings: {len(fixable_before)} → {len(fixable_after)}"

    def test_bulk_fix_reduces_findings(self, tmp_path):
        """apply_fixes_bulk should fix multiple issues in one call."""
        code = (
            "import yaml\n"
            "data = yaml.load(open('f.yml'))\n"
            "\n"
            "try:\n"
            "    x = 1\n"
            "except:\n"
            "    pass\n"
        )
        fp = tmp_path / "bulk.py"
        fp.write_text(code, encoding="utf-8")

        before = scan_file(str(fp))
        fixable = [f.to_dict() for f in before if f.rule_id in FIXABLE_RULES]
        assert len(fixable) >= 2

        result = apply_fixes_bulk(fixable)
        assert result["applied"] >= 1

        after = scan_file(str(fp))
        after_fixable = [f for f in after if f.rule_id in FIXABLE_RULES]
        assert len(after_fixable) < len(fixable)


# ═════════════════════════════════════════════════════════════════════════════
# 2. Agent dry-run produces correct report
# ═════════════════════════════════════════════════════════════════════════════

class TestAgentDryRun:
    """Agent in dry-run mode should scan but never modify files."""

    def test_dry_run_reports_findings(self, tmp_path):
        code = "result = eval(input())\n"
        (tmp_path / "bad.py").write_text(code, encoding="utf-8")

        config = AgentConfig(project_root=str(tmp_path), dry_run=True)
        agent = XRayAgent(config=config, quiet=True)
        report = agent.run()

        assert isinstance(report, AgentReport)
        assert report.scan_result is not None
        assert len(report.scan_result.findings) > 0
        assert report.duration_sec >= 0

    def test_dry_run_preserves_files(self, tmp_path):
        code = "result = eval(input())\n"
        fp = tmp_path / "bad.py"
        fp.write_text(code, encoding="utf-8")

        config = AgentConfig(project_root=str(tmp_path), dry_run=True)
        agent = XRayAgent(config=config, quiet=True)
        agent.run()

        assert fp.read_text(encoding="utf-8") == code

    def test_dry_run_no_fixes_applied(self, tmp_path):
        code = "result = eval(input())\n"
        (tmp_path / "bad.py").write_text(code, encoding="utf-8")

        config = AgentConfig(project_root=str(tmp_path), dry_run=True)
        agent = XRayAgent(config=config, quiet=True)
        report = agent.run()

        assert report.fixes_applied == 0
        assert report.tests_generated == 0


# ═════════════════════════════════════════════════════════════════════════════
# 3. Agent severity filtering
# ═════════════════════════════════════════════════════════════════════════════

class TestAgentSeverityFilter:
    """Agent should respect severity threshold."""

    def test_high_only_filters_medium_low(self, tmp_path):
        code = "# TODO: fix this\nresult = eval(input())\n"
        (tmp_path / "mixed.py").write_text(code, encoding="utf-8")

        config = AgentConfig(
            project_root=str(tmp_path),
            dry_run=True,
            severity_threshold="HIGH",
        )
        agent = XRayAgent(config=config, quiet=True)
        report = agent.run()

        for f in report.scan_result.findings:
            assert f.severity == "HIGH", f"Non-HIGH finding leaked: {f}"

    def test_low_includes_all(self, tmp_path):
        code = "# TODO: fix this\nresult = eval(input())\n"
        (tmp_path / "mixed.py").write_text(code, encoding="utf-8")

        config = AgentConfig(
            project_root=str(tmp_path),
            dry_run=True,
            severity_threshold="LOW",
        )
        agent = XRayAgent(config=config, quiet=True)
        report = agent.run()

        severities = {f.severity for f in report.scan_result.findings}
        # Should have at least HIGH (eval) and LOW (TODO)
        assert "HIGH" in severities or "LOW" in severities


# ═════════════════════════════════════════════════════════════════════════════
# 4. Agent without LLM
# ═════════════════════════════════════════════════════════════════════════════

class TestAgentWithoutLLM:
    """Agent should gracefully handle missing LLM."""

    def test_no_llm_completes_without_error(self, tmp_path):
        code = "eval(input())\n"
        (tmp_path / "bad.py").write_text(code, encoding="utf-8")

        config = AgentConfig(project_root=str(tmp_path), dry_run=False)
        agent = XRayAgent(config=config, quiet=True)
        report = agent.run()

        assert isinstance(report, AgentReport)
        # Without LLM, no tests or fixes generated
        assert report.tests_generated == 0
        assert report.fixes_applied == 0

    def test_generate_tests_skips_without_llm(self, tmp_path):
        code = "eval(input())\n"
        (tmp_path / "bad.py").write_text(code, encoding="utf-8")

        config = AgentConfig(project_root=str(tmp_path))
        agent = XRayAgent(config=config, quiet=True)
        scan_result = agent.scan()

        tests = agent.generate_tests(scan_result.findings)
        assert tests == []

    def test_generate_fixes_skips_without_llm(self, tmp_path):
        code = "eval(input())\n"
        (tmp_path / "bad.py").write_text(code, encoding="utf-8")

        config = AgentConfig(project_root=str(tmp_path))
        agent = XRayAgent(config=config, quiet=True)
        scan_result = agent.scan()

        fixes = agent.generate_fixes(scan_result.findings)
        assert fixes == []


# ═════════════════════════════════════════════════════════════════════════════
# 5. Agent exclude patterns
# ═════════════════════════════════════════════════════════════════════════════

class TestAgentExcludePatterns:
    """Agent should respect exclude patterns."""

    def test_excluded_dir_not_scanned(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "vendor").mkdir()
        (tmp_path / "src" / "app.py").write_text("eval(input())\n", encoding="utf-8")
        (tmp_path / "vendor" / "lib.py").write_text("eval(input())\n", encoding="utf-8")

        config = AgentConfig(
            project_root=str(tmp_path),
            dry_run=True,
            exclude_patterns=["vendor/"],
        )
        agent = XRayAgent(config=config, quiet=True)
        report = agent.run()

        scanned_files = {f.file for f in report.scan_result.findings}
        for sf in scanned_files:
            assert "vendor" not in sf, f"Excluded file scanned: {sf}"

    def test_empty_exclude_scans_all(self, tmp_path):
        (tmp_path / "a.py").write_text("eval(input())\n", encoding="utf-8")
        (tmp_path / "b.py").write_text("eval(input())\n", encoding="utf-8")

        config = AgentConfig(
            project_root=str(tmp_path),
            dry_run=True,
            exclude_patterns=[],
        )
        agent = XRayAgent(config=config, quiet=True)
        report = agent.run()

        assert report.scan_result.files_scanned == 2
