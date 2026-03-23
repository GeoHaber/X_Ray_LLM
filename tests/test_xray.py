"""
X-Ray Self-Tests — The agent tests itself.
================================
Tests cover: scanner, rules, runner, LLM config, agent loop.
Run:  python -m pytest tests/ -v
"""

import os
import re
import sys
import tempfile

import pytest

# Allow importing xray from the project root
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from xray.agent import AgentConfig, XRayAgent, _get_source_context
from xray.llm import LLMConfig, LLMEngine
from xray.rules import ALL_RULES, PORTABILITY_RULES, PYTHON_RULES, QUALITY_RULES, SECURITY_RULES
from xray.runner import TestResult, run_tests
from xray.scanner import Finding, ScanResult, _detect_lang, scan_directory, scan_file

# ═══════════════════════════════════════════════════════════════════════════════
# TEST 1: Rule Database
# ═══════════════════════════════════════════════════════════════════════════════


class TestRuleDatabase:
    """Verify the rule database is well-formed and complete."""

    def test_rules_not_empty(self):
        assert len(ALL_RULES) > 0

    def test_all_rules_have_required_fields(self):
        required = {"id", "severity", "lang", "pattern", "description", "fix_hint", "test_hint"}
        for rule in ALL_RULES:
            missing = required - set(rule.keys())
            assert not missing, f"Rule {rule.get('id', '?')} missing: {missing}"

    def test_rule_ids_are_unique(self):
        ids = [r["id"] for r in ALL_RULES]
        assert len(ids) == len(set(ids)), f"Duplicate IDs: {[i for i in ids if ids.count(i) > 1]}"

    def test_severity_values_valid(self):
        valid = {"HIGH", "MEDIUM", "LOW"}
        for rule in ALL_RULES:
            assert rule["severity"] in valid, f"{rule['id']} has invalid severity: {rule['severity']}"

    def test_patterns_compile(self):
        for rule in ALL_RULES:
            try:
                re.compile(rule["pattern"])
            except re.error as e:
                pytest.fail(f"Rule {rule['id']} has invalid regex: {e}")

    def test_security_rules_exist(self):
        assert len(SECURITY_RULES) >= 5

    def test_quality_rules_exist(self):
        assert len(QUALITY_RULES) >= 5

    def test_python_rules_exist(self):
        assert len(PYTHON_RULES) >= 5

    def test_all_rules_combined(self):
        assert len(ALL_RULES) == len(SECURITY_RULES) + len(QUALITY_RULES) + len(PYTHON_RULES) + len(PORTABILITY_RULES)

    def test_xss_rule_exists(self):
        ids = [r["id"] for r in ALL_RULES]
        assert "SEC-001" in ids

    def test_injection_rule_exists(self):
        ids = [r["id"] for r in ALL_RULES]
        assert "SEC-003" in ids


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 2: Scanner Engine
# ═══════════════════════════════════════════════════════════════════════════════


class TestScanner:
    """Verify the pattern scanner works correctly."""

    def test_detect_python(self):
        assert _detect_lang("test.py") == "python"

    def test_detect_javascript(self):
        assert _detect_lang("app.js") == "javascript"

    def test_detect_html(self):
        assert _detect_lang("index.html") == "html"

    def test_detect_unknown(self):
        assert _detect_lang("readme.md") is None

    def test_scan_file_finds_xss(self):
        """Create a temp file with XSS vulnerability and verify scanner finds it."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False, encoding="utf-8") as f:
            f.write("<script>el.innerHTML = `<b>${userInput}</b>`;</script>")
            f.flush()
            findings = scan_file(f.name)
        os.unlink(f.name)
        xss_findings = [f for f in findings if f.rule_id == "SEC-001"]
        assert len(xss_findings) > 0, "Should detect XSS in innerHTML template literal"

    def test_scan_file_finds_eval(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write("result = eval(user_input)\n")
            f.flush()
            findings = scan_file(f.name)
        os.unlink(f.name)
        eval_findings = [f for f in findings if f.rule_id == "SEC-007"]
        assert len(eval_findings) > 0, "Should detect eval() usage"

    def test_scan_file_finds_bare_except(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write("try:\n  x = 1\nexcept:\n  pass\n")
            f.flush()
            findings = scan_file(f.name)
        os.unlink(f.name)
        bare = [f for f in findings if f.rule_id == "QUAL-001"]
        assert len(bare) > 0, "Should detect bare except clause"

    def test_scan_clean_file_no_findings(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write("def add(a: int, b: int) -> int:\n    return a + b\n")
            f.flush()
            findings = scan_file(f.name)
        os.unlink(f.name)
        # Clean code should have minimal/no HIGH findings
        high = [f for f in findings if f.severity == "HIGH"]
        assert len(high) == 0, f"Clean code should not have HIGH findings: {high}"

    def test_scan_file_returns_correct_line(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write("line1 = 'ok'\nline2 = 'ok'\nresult = eval('bad')\nline4 = 'ok'\n")
            f.flush()
            findings = scan_file(f.name)
        os.unlink(f.name)
        eval_findings = [f for f in findings if f.rule_id == "SEC-007"]
        assert eval_findings[0].line == 3

    def test_scan_directory_works(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "bad.py"), "w", encoding="utf-8") as f:
                f.write("eval('x')\n")
            result = scan_directory(tmpdir)
            assert isinstance(result, ScanResult)
            assert result.files_scanned >= 1
            assert len(result.findings) >= 1

    def test_scan_respects_skip_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a file in __pycache__ (should be skipped)
            cache_dir = os.path.join(tmpdir, "__pycache__")
            os.makedirs(cache_dir)
            with open(os.path.join(cache_dir, "bad.py"), "w", encoding="utf-8") as f:
                f.write("eval('x')\n")
            result = scan_directory(tmpdir)
            assert result.files_scanned == 0

    def test_finding_to_dict(self):
        f = Finding(
            rule_id="TEST-001",
            severity="HIGH",
            file="test.py",
            line=1,
            col=1,
            matched_text="eval(x)",
            description="test",
            fix_hint="fix",
            test_hint="test",
        )
        d = f.to_dict()
        assert d["rule_id"] == "TEST-001"
        assert d["severity"] == "HIGH"

    def test_finding_str(self):
        f = Finding(
            rule_id="TEST-001",
            severity="HIGH",
            file="test.py",
            line=1,
            col=1,
            matched_text="eval(x)",
            description="test issue",
            fix_hint="fix",
            test_hint="test",
        )
        assert "TEST-001" in str(f)
        assert "HIGH" in str(f)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 3: LLM Engine (config only — no model required)
# ═══════════════════════════════════════════════════════════════════════════════


class TestLLMConfig:
    """Verify LLM configuration without requiring an actual model."""

    def test_default_config(self):
        cfg = LLMConfig()
        assert cfg.n_ctx == 8192
        assert cfg.temperature == 0.3
        assert cfg.max_tokens == 2048

    def test_config_from_env(self):
        os.environ["XRAY_MODEL_PATH"] = "/fake/model.gguf"
        os.environ["XRAY_N_CTX"] = "4096"
        cfg = LLMConfig.from_env()
        assert cfg.model_path == "/fake/model.gguf"
        assert cfg.n_ctx == 4096
        del os.environ["XRAY_MODEL_PATH"]
        del os.environ["XRAY_N_CTX"]

    def test_engine_not_available_without_model(self):
        engine = LLMEngine(config=LLMConfig(model_path=""))
        assert not engine.is_available

    def test_engine_not_available_with_bad_path(self):
        engine = LLMEngine(config=LLMConfig(model_path="/nonexistent/model.gguf"))
        assert not engine.is_available

    def test_engine_raises_without_model(self):
        engine = LLMEngine(config=LLMConfig(model_path=""))
        with pytest.raises(RuntimeError, match="No model path"):
            engine.generate("test")

    def test_unload(self):
        engine = LLMEngine(config=LLMConfig(model_path=""))
        engine._model = "fake"
        engine.unload()
        assert engine._model is None


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 4: Test Runner
# ═══════════════════════════════════════════════════════════════════════════════


class TestTestRunner:
    """Verify the pytest runner wrapper."""

    def test_result_all_passed(self):
        r = TestResult(passed=5, total=5)
        assert r.all_passed

    def test_result_not_all_passed(self):
        r = TestResult(passed=3, failed=2, total=5)
        assert not r.all_passed

    def test_result_empty_not_passed(self):
        r = TestResult()
        assert not r.all_passed

    def test_summary_format(self):
        r = TestResult(passed=10, failed=0, total=10)
        assert "ALL PASSED" in r.summary()

    def test_summary_failures(self):
        r = TestResult(passed=8, failed=2, total=10)
        assert "FAILURES" in r.summary()

    def test_run_tests_invokes_subprocess(self):
        """Verify run_tests creates a subprocess and captures output."""
        # Create a minimal passing test file instead of running ourselves (avoids recursion)
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            delete=False,
            prefix="test_mini_",
            encoding="utf-8",
        ) as f:
            f.write("def test_trivial():\n    assert 1 + 1 == 2\n")
            f.flush()
            result = run_tests(f.name, timeout=30)
        os.unlink(f.name)
        assert result.total >= 1
        assert result.output


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 5: Agent Configuration
# ═══════════════════════════════════════════════════════════════════════════════


class TestAgentConfig:
    """Verify agent configuration."""

    def test_default_config(self):
        cfg = AgentConfig()
        assert cfg.max_fix_retries == 3
        assert cfg.severity_threshold == "MEDIUM"

    def test_severity_levels_high(self):
        cfg = AgentConfig(severity_threshold="HIGH")
        assert cfg.severity_levels == ["HIGH"]

    def test_severity_levels_medium(self):
        cfg = AgentConfig(severity_threshold="MEDIUM")
        assert cfg.severity_levels == ["HIGH", "MEDIUM"]

    def test_severity_levels_low(self):
        cfg = AgentConfig(severity_threshold="LOW")
        assert cfg.severity_levels == ["HIGH", "MEDIUM", "LOW"]


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 6: Agent Core
# ═══════════════════════════════════════════════════════════════════════════════


class TestAgent:
    """Verify the agent orchestrator."""

    def test_agent_creates(self):
        agent = XRayAgent()
        assert agent.config is not None
        assert agent.llm is not None

    def test_get_source_context(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            for i in range(20):
                f.write(f"line_{i + 1} = {i}\n")
            f.flush()
            ctx = _get_source_context(f.name, 10, context=3)
        os.unlink(f.name)
        assert "line_10" in ctx
        assert ">>>" in ctx

    def test_scan_on_temp_project(self):
        """Agent scan on a temp dir with known issues."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "bad.py"), "w", encoding="utf-8") as f:
                f.write("x = eval(input())\n")
            config = AgentConfig(project_root=tmpdir, dry_run=True)
            agent = XRayAgent(config=config)
            result = agent.scan()
            assert len(result.findings) > 0

    def test_dry_run_makes_no_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "test.py")
            code = "x = eval(input())\n"
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(code)
            config = AgentConfig(project_root=tmpdir, dry_run=True)
            agent = XRayAgent(config=config)
            agent.run()
            with open(filepath, encoding="utf-8") as f:
                assert f.read() == code  # unchanged

    def test_report_summary(self):
        from xray.agent import AgentReport

        report = AgentReport(
            tests_generated=3,
            fixes_applied=2,
            fix_attempts=1,
            duration_sec=1.5,
        )
        summary = report.summary()
        assert "Tests generated" in summary
        assert "Fixes applied" in summary


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 7: Self-Scan (X-Ray scans itself!)
# ═══════════════════════════════════════════════════════════════════════════════


class TestSelfScan:
    """X-Ray scans its own codebase — dogfooding at its finest."""

    def test_xray_codebase_scans_clean(self):
        """The X-Ray codebase itself should have no HIGH-severity findings."""
        xray_dir = os.path.join(REPO_ROOT, "xray")
        result = scan_directory(xray_dir)
        high = [f for f in result.findings if f.severity == "HIGH"]
        if high:
            details = "\n".join(str(f) for f in high)
            pytest.fail(f"X-Ray's own code has HIGH findings:\n{details}")

    def test_test_file_scans(self):
        """This test file itself should be scannable without errors."""
        findings = scan_file(__file__)
        # We use eval in test_engine_raises_without_model, so SEC-007 might fire
        # but that's acceptable in test code
        for f in findings:
            assert f.file == __file__
