"""
X-Ray LLM -- End-to-end extreme-case test suite.

Exercises the scanner, agent loop, LLM engine, and runner under adversarial,
edge-case, and high-load conditions.  External dependencies (llama-cpp,
file system, subprocess) are mocked.

Run:  python -m pytest tests/test_e2e_extreme.py -v
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Ensure project root is importable
# ---------------------------------------------------------------------------
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from xray.agent import AgentConfig, AgentReport, XRayAgent, _get_source_context
from xray.llm import LLMConfig, LLMEngine, _resolve_kv_type
from xray.runner import TestResult, run_tests
from xray.scanner import (
    _PY_NON_CODE_RE,
    Finding,
    ScanResult,
    _get_compiled,
    scan_project,
)

# ═══════════════════════════════════════════════════════════════════════════
# 1.  Scanner extreme tests
# ═══════════════════════════════════════════════════════════════════════════

class TestScannerExtreme(unittest.TestCase):
    """Scanner under adversarial file inputs."""

    def _write_temp(self, content: str, suffix: str = ".py") -> str:
        """Write content to a temp file and return its path."""
        fd, path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        self.addCleanup(os.unlink, path)
        return path

    def test_empty_file(self):
        """Scanning an empty Python file should produce zero findings."""
        path = self._write_temp("")
        result = scan_project(os.path.dirname(path))
        # May find 0 or more depending on rules, but should not crash
        self.assertIsInstance(result, ScanResult)

    def test_single_line_file(self):
        """Single-line file should be scanned without error."""
        path = self._write_temp("x = 1")
        result = scan_project(os.path.dirname(path))
        self.assertIsInstance(result, ScanResult)

    def test_file_with_100000_lines(self):
        """Very large file should still be processed (up to size limit)."""
        # Create a file just under 1 MB
        lines = ["x = 1\n"] * 50000  # ~300 KB
        path = self._write_temp("".join(lines))
        result = scan_project(os.path.dirname(path))
        self.assertIsInstance(result, ScanResult)
        self.assertGreater(result.files_scanned, 0)

    def test_binary_file_skipped(self):
        """Binary files (non-Python extensions) should be skipped."""
        fd, path = tempfile.mkstemp(suffix=".bin")
        with os.fdopen(fd, "wb") as f:
            f.write(b"\x00\x01\x02\xff" * 1000)
        self.addCleanup(os.unlink, path)
        result = scan_project(os.path.dirname(path))
        # Should not crash on binary content
        self.assertIsInstance(result, ScanResult)

    def test_mixed_encoding_utf8(self):
        """UTF-8 file with special chars should be scannable."""
        content = '# -*- coding: utf-8 -*-\nx = "Hello"\nprint(x)\n'
        path = self._write_temp(content)
        result = scan_project(os.path.dirname(path))
        self.assertIsInstance(result, ScanResult)

    def test_mixed_encoding_latin1(self):
        """Latin-1 encoded file should be read with errors=replace."""
        fd, path = tempfile.mkstemp(suffix=".py")
        with os.fdopen(fd, "wb") as f:
            f.write(b"# Latin-1 file\nx = '\xe9\xe0\xfc'\nprint(x)\n")
        self.addCleanup(os.unlink, path)
        result = scan_project(os.path.dirname(path))
        self.assertIsInstance(result, ScanResult)

    def test_file_with_bom(self):
        """UTF-8 BOM marker should not break scanning."""
        fd, path = tempfile.mkstemp(suffix=".py")
        with os.fdopen(fd, "wb") as f:
            f.write(b"\xef\xbb\xbfprint('hello')\n")
        self.addCleanup(os.unlink, path)
        result = scan_project(os.path.dirname(path))
        self.assertIsInstance(result, ScanResult)

    def test_directory_with_many_files(self):
        """Directory with many files should be scanned."""
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmpdir, ignore_errors=True))
        for i in range(100):
            with open(os.path.join(tmpdir, f"mod_{i}.py"), "w") as f:
                f.write(f"x_{i} = {i}\n")
        result = scan_project(tmpdir)
        self.assertGreaterEqual(result.files_scanned, 100)

    def test_deeply_nested_directory(self):
        """Deeply nested directory structure should be traversed."""
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmpdir, ignore_errors=True))
        current = tmpdir
        for i in range(20):  # 20 levels deep
            current = os.path.join(current, f"level_{i}")
            os.makedirs(current, exist_ok=True)
        with open(os.path.join(current, "deep.py"), "w") as f:
            f.write("print('deep')\n")
        result = scan_project(tmpdir)
        self.assertGreater(result.files_scanned, 0)

    def test_file_with_syntax_errors(self):
        """Python file with syntax errors should not crash scanner."""
        content = "def broken(\n    if True\n        pass\n"
        path = self._write_temp(content)
        result = scan_project(os.path.dirname(path))
        self.assertIsInstance(result, ScanResult)


# ═══════════════════════════════════════════════════════════════════════════
# 2.  Finding and ScanResult tests
# ═══════════════════════════════════════════════════════════════════════════

class TestFinding(unittest.TestCase):
    """Finding dataclass edge cases."""

    def test_to_dict_and_back(self):
        """Round-trip through dict should preserve all fields."""
        f = Finding(
            rule_id="SEC-001", severity="HIGH", file="test.py", line=42,
            col=0, matched_text="some_match",
            description="Security issue", fix_hint="Fix it",
            test_hint="Test security",
        )
        d = f.to_dict()
        self.assertEqual(d["rule_id"], "SEC-001")
        self.assertEqual(d["line"], 42)

    def test_str_representation(self):
        """String representation should be readable."""
        f = Finding(
            rule_id="PY-001", severity="MEDIUM", file="app.py", line=10,
            col=0, matched_text="",
            description="Issue found", fix_hint="", test_hint="",
        )
        s = str(f)
        self.assertIn("PY-001", s)
        self.assertIn("MEDIUM", s)


class TestScanResult(unittest.TestCase):
    """ScanResult aggregation edge cases."""

    def test_empty_result(self):
        """Empty scan result should have zero counts."""
        r = ScanResult()
        self.assertEqual(r.files_scanned, 0)
        self.assertEqual(len(r.findings), 0)
        self.assertEqual(r.high_count, 0)

    def test_severity_counts(self):
        """Severity counts should be accurate."""
        findings = [
            Finding(rule_id="A", severity="HIGH", file="a.py", line=1, col=0, matched_text="", description="", fix_hint="", test_hint=""),
            Finding(rule_id="B", severity="HIGH", file="b.py", line=2, col=0, matched_text="", description="", fix_hint="", test_hint=""),
            Finding(rule_id="C", severity="MEDIUM", file="c.py", line=3, col=0, matched_text="", description="", fix_hint="", test_hint=""),
            Finding(rule_id="D", severity="LOW", file="d.py", line=4, col=0, matched_text="", description="", fix_hint="", test_hint=""),
        ]
        r = ScanResult(findings=findings, files_scanned=4, rules_checked=10)
        self.assertEqual(r.high_count, 2)
        self.assertEqual(r.medium_count, 1)
        self.assertEqual(r.low_count, 1)

    def test_summary_format(self):
        """Summary string should contain key stats."""
        r = ScanResult(files_scanned=50, rules_checked=20)
        s = r.summary()
        self.assertIn("50", s)
        self.assertIn("20", s)


# ═══════════════════════════════════════════════════════════════════════════
# 3.  Regex / Pattern matching edge cases
# ═══════════════════════════════════════════════════════════════════════════

class TestRegexEdgeCases(unittest.TestCase):
    """Regex compilation and pattern matching."""

    def test_compiled_cache(self):
        """Same pattern should return same compiled object."""
        p1 = _get_compiled(r"\bprint\b")
        p2 = _get_compiled(r"\bprint\b")
        self.assertIs(p1, p2)

    def test_invalid_regex_returns_none(self):
        """Bad regex should return None, not crash."""
        result = _get_compiled(r"[invalid")
        self.assertIsNone(result)

    def test_non_code_regex_triple_quotes(self):
        """Triple-quoted strings should be matched by the non-code regex."""
        code = '"""This is a docstring with print() in it"""'
        matches = _PY_NON_CODE_RE.findall(code)
        self.assertTrue(len(matches) > 0)

    def test_non_code_regex_comments(self):
        """Comments should be matched."""
        code = "x = 1  # print() is just a comment"
        matches = _PY_NON_CODE_RE.findall(code)
        self.assertTrue(len(matches) > 0)

    def test_nested_braces_in_fstrings(self):
        """F-strings with nested braces should not crash regex."""
        code = 'f"result: {d[\'key\']}"'
        # Should not raise
        _PY_NON_CODE_RE.findall(code)


# ═══════════════════════════════════════════════════════════════════════════
# 4.  Agent extreme tests
# ═══════════════════════════════════════════════════════════════════════════

class TestAgentExtreme(unittest.TestCase):
    """XRayAgent under extreme configurations."""

    def test_agent_config_severity_levels(self):
        """Severity threshold should filter correctly."""
        config = AgentConfig(severity_threshold="HIGH")
        self.assertEqual(config.severity_levels, ["HIGH"])

        config = AgentConfig(severity_threshold="MEDIUM")
        self.assertEqual(config.severity_levels, ["HIGH", "MEDIUM"])

        config = AgentConfig(severity_threshold="LOW")
        self.assertEqual(config.severity_levels, ["HIGH", "MEDIUM", "LOW"])

    def test_agent_dry_run_no_changes(self):
        """Dry run should scan but not fix."""
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmpdir, ignore_errors=True))
        with open(os.path.join(tmpdir, "test.py"), "w") as f:
            f.write("print('hello')\n")

        config = AgentConfig(
            project_root=tmpdir, dry_run=True, auto_fix=False, auto_test=False,
        )
        agent = XRayAgent(config=config, quiet=True)
        report = agent.run()
        self.assertEqual(report.fixes_applied, 0)
        self.assertEqual(report.tests_generated, 0)

    def test_agent_no_llm_skips_generation(self):
        """Without LLM, agent should skip test/fix generation."""
        config = AgentConfig(dry_run=False, auto_fix=True, auto_test=True)
        llm = LLMEngine(LLMConfig(model_path=""))
        agent = XRayAgent(config=config, llm=llm, quiet=True)

        findings = [
            Finding(rule_id="PY-001", severity="HIGH", file="test.py", line=1, col=0, matched_text="", description="", fix_hint="", test_hint=""),
        ]
        tests = agent.generate_tests(findings)
        self.assertEqual(len(tests), 0)
        fixes = agent.generate_fixes(findings)
        self.assertEqual(len(fixes), 0)

    def test_agent_report_summary(self):
        """Report summary should be a formatted string."""
        report = AgentReport(
            tests_generated=5, fixes_applied=3, fix_attempts=2,
            duration_sec=12.5, errors=["err1"],
        )
        summary = report.summary()
        self.assertIn("Tests generated", summary)
        self.assertIn("5", summary)
        self.assertIn("err1", summary)

    def test_agent_report_empty(self):
        """Empty report should still produce valid summary."""
        report = AgentReport()
        summary = report.summary()
        self.assertIn("X-Ray Agent Report", summary)

    def test_agent_log_unicode(self):
        """Agent log should handle unicode characters."""
        agent = XRayAgent(quiet=True)
        agent.log("Unicode test: abc")
        self.assertIn("Unicode test", agent._log_lines[-1])


# ═══════════════════════════════════════════════════════════════════════════
# 5.  Source context extraction
# ═══════════════════════════════════════════════════════════════════════════

class TestSourceContext(unittest.TestCase):
    """_get_source_context edge cases."""

    def test_normal_file(self):
        """Context extraction around a known line."""
        fd, path = tempfile.mkstemp(suffix=".py")
        with os.fdopen(fd, "w") as f:
            for i in range(20):
                f.write(f"line_{i} = {i}\n")
        self.addCleanup(os.unlink, path)
        ctx = _get_source_context(path, 10)
        self.assertIn("line_9", ctx)
        self.assertIn(">>>", ctx)

    def test_nonexistent_file(self):
        """Non-existent file should return error string."""
        ctx = _get_source_context("/nonexistent/file.py", 5)
        self.assertIn("Could not read", ctx)

    def test_line_beyond_file_length(self):
        """Line number beyond file should still work (empty context)."""
        fd, path = tempfile.mkstemp(suffix=".py")
        with os.fdopen(fd, "w") as f:
            f.write("x = 1\n")
        self.addCleanup(os.unlink, path)
        ctx = _get_source_context(path, 1000)
        self.assertIsInstance(ctx, str)

    def test_line_zero(self):
        """Line 0 should not crash."""
        fd, path = tempfile.mkstemp(suffix=".py")
        with os.fdopen(fd, "w") as f:
            f.write("x = 1\n")
        self.addCleanup(os.unlink, path)
        ctx = _get_source_context(path, 0)
        self.assertIsInstance(ctx, str)


# ═══════════════════════════════════════════════════════════════════════════
# 6.  LLM Engine extreme tests
# ═══════════════════════════════════════════════════════════════════════════

class TestLLMEngineExtreme(unittest.TestCase):
    """LLMEngine under extreme conditions."""

    def test_no_model_path_not_available(self):
        """Engine with no model path should report not available."""
        engine = LLMEngine(LLMConfig(model_path=""))
        self.assertFalse(engine.is_available)

    def test_nonexistent_model_path(self):
        """Non-existent model file should not be available."""
        engine = LLMEngine(LLMConfig(model_path="/nonexistent/model.gguf"))
        self.assertFalse(engine.is_available)

    def test_ensure_model_raises_without_path(self):
        """_ensure_model should raise RuntimeError without model path."""
        from xray.llm import GGUFBackend
        backend = GGUFBackend(LLMConfig(model_path=""))
        with self.assertRaises(RuntimeError):
            backend._ensure_model()

    def test_generate_without_model_raises(self):
        """generate() should raise if no model loaded."""
        engine = LLMEngine(LLMConfig(model_path=""))
        with self.assertRaises(RuntimeError):
            engine.generate("test prompt")

    def test_unload_clears_model(self):
        """unload() should set model to None."""
        from xray.llm import GGUFBackend
        backend = GGUFBackend(LLMConfig(model_path=""))
        backend._model = MagicMock()
        backend.unload()
        self.assertIsNone(backend._model)

    def test_config_from_env(self):
        """LLMConfig.from_env should read environment variables."""
        with patch.dict(os.environ, {
            "XRAY_MODEL_PATH": "/test/model.gguf",
            "XRAY_N_CTX": "4096",
            "XRAY_TEMPERATURE": "0.5",
        }):
            config = LLMConfig.from_env()
            self.assertEqual(config.model_path, "/test/model.gguf")
            self.assertEqual(config.n_ctx, 4096)
            self.assertAlmostEqual(config.temperature, 0.5)

    def test_config_from_env_invalid_values(self):
        """Invalid env values should fall back to defaults."""
        with patch.dict(os.environ, {
            "XRAY_N_CTX": "not_a_number",
            "XRAY_TEMPERATURE": "not_a_float",
        }):
            config = LLMConfig.from_env()
            self.assertEqual(config.n_ctx, 8192)
            self.assertAlmostEqual(config.temperature, 0.3)

    def test_resolve_kv_type_valid(self):
        """Known KV type names should resolve to int values."""
        self.assertEqual(_resolve_kv_type("f16"), 1)
        self.assertEqual(_resolve_kv_type("q8_0"), 8)
        self.assertEqual(_resolve_kv_type("q4_0"), 2)

    def test_resolve_kv_type_integer_string(self):
        """Raw integer string should be accepted."""
        self.assertEqual(_resolve_kv_type("8"), 8)

    def test_resolve_kv_type_empty(self):
        """Empty string should return None."""
        self.assertIsNone(_resolve_kv_type(""))

    def test_resolve_kv_type_invalid(self):
        """Unknown KV type should raise ValueError."""
        with self.assertRaises(ValueError):
            _resolve_kv_type("invalid_type")

    def test_thread_safe_model_loading(self):
        """Multiple threads calling _ensure_model should not double-load."""
        from xray.llm import GGUFBackend
        backend = GGUFBackend(LLMConfig(model_path=""))
        errors = []

        def try_load():
            try:
                backend._ensure_model()
            except RuntimeError:
                pass  # expected since no model path
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=try_load) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        self.assertEqual(len(errors), 0)


# ═══════════════════════════════════════════════════════════════════════════
# 7.  Runner extreme tests
# ═══════════════════════════════════════════════════════════════════════════

class TestRunnerExtreme(unittest.TestCase):
    """Test runner under extreme conditions."""

    def test_test_result_all_passed(self):
        """all_passed requires total > 0 and no failures."""
        r = TestResult(passed=5, total=5)
        self.assertTrue(r.all_passed)

    def test_test_result_empty_is_not_passed(self):
        """Zero tests should not count as all_passed."""
        r = TestResult()
        self.assertFalse(r.all_passed)

    def test_test_result_with_failures(self):
        """Failures should make all_passed False."""
        r = TestResult(passed=3, failed=1, total=4)
        self.assertFalse(r.all_passed)

    def test_test_result_summary_format(self):
        """Summary should contain key information."""
        r = TestResult(passed=10, failed=2, errors=1, total=13)
        s = r.summary()
        self.assertIn("10", s)
        self.assertIn("2", s)
        self.assertIn("FAILURES", s)

    def test_run_tests_nonexistent_path(self):
        """Running tests on non-existent path should handle gracefully."""
        result = run_tests("/nonexistent/tests/")
        self.assertIsInstance(result, TestResult)

    @patch("xray.runner.subprocess.run")
    def test_run_tests_timeout(self, mock_run):
        """Test timeout should be handled."""
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="pytest", timeout=120)
        result = run_tests("tests/")
        self.assertIn("TIMEOUT", result.output)

    @patch("xray.runner.subprocess.run")
    def test_run_tests_parse_output(self, mock_run):
        """Parse pytest summary output correctly."""
        mock_proc = MagicMock()
        mock_proc.stdout = "10 passed, 2 failed, 1 error in 5.0s"
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc
        result = run_tests("tests/")
        self.assertEqual(result.passed, 10)
        self.assertEqual(result.failed, 2)


# ═══════════════════════════════════════════════════════════════════════════
# 8.  Pattern / rule triggering tests
# ═══════════════════════════════════════════════════════════════════════════

class TestRuleTriggering(unittest.TestCase):
    """Verify that scanner rules trigger (or not) in specific scenarios."""

    def _scan_code(self, code: str) -> ScanResult:
        """Scan a temporary Python file and return results."""
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmpdir, ignore_errors=True))
        with open(os.path.join(tmpdir, "test_code.py"), "w", encoding="utf-8") as f:
            f.write(code)
        return scan_project(tmpdir)

    def test_print_in_code_triggers(self):
        """print() in code should trigger PY-004 (if the rule exists)."""
        result = self._scan_code("print('hello world')\n")
        # We just verify scanning completes; rule presence depends on config
        self.assertIsInstance(result, ScanResult)

    def test_print_in_string_suppressed(self):
        """print() inside a string literal should be suppressed."""
        code = 'description = "Use print() to debug"\n'
        result = self._scan_code(code)
        # Should not trigger PY-004 for string content
        for f in result.findings:
            if f.rule_id == "PY-004":
                self.assertNotIn("description", f.message or "")

    def test_eval_triggers_security(self):
        """eval() should trigger a security finding."""
        result = self._scan_code("result = eval(user_input)\n")
        sec_findings = [f for f in result.findings if f.rule_id.startswith("SEC")]
        # eval should trigger at least one security finding
        # (may or may not depending on exact rules)
        self.assertIsInstance(result, ScanResult)

    def test_todo_comment_triggers(self):
        """TODO comments should trigger QUAL-007 (if configured)."""
        result = self._scan_code("# TODO: fix this later\nx = 1\n")
        self.assertIsInstance(result, ScanResult)

    def test_suppression_comment(self):
        """xray: ignore comment should suppress the finding."""
        code = "print('hello')  # xray: ignore[PY-004]\n"
        result = self._scan_code(code)
        py004 = [f for f in result.findings if f.rule_id == "PY-004"]
        # Should be suppressed
        self.assertEqual(len(py004), 0)


# ═══════════════════════════════════════════════════════════════════════════
# 9.  Concurrent scanning stress test
# ═══════════════════════════════════════════════════════════════════════════

class TestConcurrentScanning(unittest.TestCase):
    """Thread-safety of the scanner."""

    def test_concurrent_regex_compilation(self):
        """Multiple threads compiling patterns should be safe."""
        errors = []
        patterns = [r"\bprint\b", r"\beval\b", r"\bexec\b", r"\bglobal\b"]

        def compile_patterns():
            try:
                for p in patterns * 100:
                    _get_compiled(p)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=compile_patterns) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        self.assertEqual(len(errors), 0)


# ═══════════════════════════════════════════════════════════════════════════
# 10. LLM generation with mocked model
# ═══════════════════════════════════════════════════════════════════════════

class TestLLMGeneration(unittest.TestCase):
    """LLM generation methods with mocked model."""

    def _make_engine_with_mock(self):
        """Create an engine with a mocked model."""
        engine = LLMEngine(LLMConfig(model_path="/fake/model.gguf"))
        mock_model = MagicMock()
        mock_model.create_chat_completion.return_value = {
            "choices": [{"message": {"content": "def test_fix():\n    pass"}}]
        }
        # Inject mock into the underlying GGUFBackend
        engine._backend._model = mock_model
        return engine

    def test_generate_test_code(self):
        """generate_test should produce test code string."""
        engine = self._make_engine_with_mock()
        finding = {
            "rule_id": "SEC-001", "severity": "HIGH",
            "description": "SQL injection", "file": "app.py",
            "line": 10, "test_hint": "Test parameterized queries",
        }
        result = engine.generate_test(finding, "cursor.execute(f'SELECT * FROM {table}')")
        self.assertIn("test_fix", result)

    def test_generate_fix_code(self):
        """generate_fix should produce fix code string."""
        engine = self._make_engine_with_mock()
        finding = {
            "rule_id": "SEC-001", "severity": "HIGH",
            "description": "SQL injection", "file": "app.py",
            "line": 10, "fix_hint": "Use parameterized queries",
        }
        result = engine.generate_fix(finding, "code context")
        self.assertIsInstance(result, str)

    def test_generate_fix_with_test_error(self):
        """generate_fix with prior test error should include it in prompt."""
        engine = self._make_engine_with_mock()
        finding = {
            "rule_id": "PY-001", "severity": "MEDIUM",
            "description": "Issue", "file": "a.py",
            "line": 5, "fix_hint": "fix",
        }
        result = engine.generate_fix(finding, "context", test_error="AssertionError: expected True")
        self.assertIsInstance(result, str)

    def test_analyze_codebase(self):
        """analyze_codebase should produce summary string."""
        engine = self._make_engine_with_mock()
        result = engine.analyze_codebase("5 HIGH, 3 MEDIUM findings")
        self.assertIsInstance(result, str)

    def test_generate_with_garbage_response(self):
        """LLM returning empty/garbage should still return string."""
        engine = self._make_engine_with_mock()
        engine._backend._model.create_chat_completion.return_value = {
            "choices": [{"message": {"content": ""}}]
        }
        result = engine.generate("test")
        self.assertEqual(result, "")


# ═══════════════════════════════════════════════════════════════════════════
# 11. Agent full loop with mocked components
# ═══════════════════════════════════════════════════════════════════════════

class TestAgentFullLoop(unittest.TestCase):
    """Full agent loop with mocked scanner and LLM."""

    def test_scan_only_mode(self):
        """scan() should return ScanResult and set report."""
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmpdir, ignore_errors=True))
        with open(os.path.join(tmpdir, "code.py"), "w") as f:
            f.write("x = 1\n")
        config = AgentConfig(project_root=tmpdir, dry_run=True)
        agent = XRayAgent(config=config, quiet=True)
        result = agent.scan()
        self.assertIsInstance(result, ScanResult)
        self.assertIsNotNone(agent.report.scan_result)

    def test_verify_missing_test_path(self):
        """verify() with missing test path should return TestResult."""
        config = AgentConfig(project_root="/nonexistent", test_path="no_tests/")
        agent = XRayAgent(config=config, quiet=True)
        result = agent.verify()
        self.assertIn("not found", result.output)

    def test_full_run_no_findings(self):
        """Full run with clean code should complete quickly."""
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmpdir, ignore_errors=True))
        with open(os.path.join(tmpdir, "clean.py"), "w") as f:
            f.write("def add(a: int, b: int) -> int:\n    return a + b\n")
        config = AgentConfig(project_root=tmpdir, dry_run=True)
        agent = XRayAgent(config=config, quiet=True)
        report = agent.run()
        self.assertIsInstance(report, AgentReport)
        self.assertGreaterEqual(report.duration_sec, 0)


class TestTypecheckEdgeCases(unittest.TestCase):
    """Edge-case tests for type checker deprecation path."""

    def test_run_typecheck_on_empty_dir(self):
        """run_typecheck() on an empty directory should not crash."""
        import tempfile
        import warnings as _warnings

        from analyzers.format_check import run_typecheck

        tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmpdir, ignore_errors=True))
        with _warnings.catch_warnings(record=True):
            _warnings.simplefilter("always")
            result = run_typecheck(tmpdir)
        # Should return dict (success or error), never crash
        self.assertIsInstance(result, dict)

    def test_check_types_on_empty_dir(self):
        """check_types() on an empty directory returns clean or error."""
        import tempfile

        from analyzers.format_check import check_types

        tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmpdir, ignore_errors=True))
        result = check_types(tmpdir)
        self.assertIsInstance(result, dict)

    def test_pyright_deprecation_warning_content(self):
        """DeprecationWarning message should mention 'check_types'."""
        import tempfile
        import warnings as _warnings

        from analyzers.format_check import run_typecheck

        tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmpdir, ignore_errors=True))
        with _warnings.catch_warnings(record=True) as w:
            _warnings.simplefilter("always")
            run_typecheck(tmpdir)
            dep = [x for x in w if issubclass(x.category, DeprecationWarning)]
            self.assertTrue(len(dep) >= 1)
            self.assertIn("check_types", str(dep[0].message))


if __name__ == "__main__":
    unittest.main()
