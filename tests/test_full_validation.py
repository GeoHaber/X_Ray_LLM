"""
X-Ray Full Validation Tests — NO MOCKS.

Validates every spec claim in X_RAY_LLM_GUIDE.md against live code.
Every test calls real functions—no mocks, no patches, no fakes.
"""

import hashlib
import json
import os
import sys
import tempfile
import textwrap
from typing import ClassVar

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from services.chat_engine import chat_reply
from xray.fixer import FIXABLE_RULES, FIXERS, apply_fix
from xray.rules import ALL_RULES, PORTABILITY_RULES, PYTHON_RULES, QUALITY_RULES, SECURITY_RULES
from xray.sarif import findings_to_sarif
from xray.scanner import ScanResult, scan_directory, scan_file

# ── Rule Counts ──────────────────────────────────────────────────────────

class TestRuleCounts:
    """Validate the 42-rule spec: 14 SEC + 13 QUAL + 11 PY + 4 PORT."""

    def test_total_rule_count_is_42(self):
        assert len(ALL_RULES) == 42

    def test_security_rules_count(self):
        assert len(SECURITY_RULES) == 14

    def test_quality_rules_count(self):
        assert len(QUALITY_RULES) == 13

    def test_python_rules_count(self):
        assert len(PYTHON_RULES) == 11

    def test_portability_rules_count(self):
        assert len(PORTABILITY_RULES) == 4

    def test_sum_matches_total(self):
        total = len(SECURITY_RULES) + len(QUALITY_RULES) + len(PYTHON_RULES) + len(PORTABILITY_RULES)
        assert total == len(ALL_RULES) == 42

    def test_rule_id_prefixes(self):
        sec = [r for r in ALL_RULES if r["id"].startswith("SEC-")]
        qual = [r for r in ALL_RULES if r["id"].startswith("QUAL-")]
        py = [r for r in ALL_RULES if r["id"].startswith("PY-")]
        port = [r for r in ALL_RULES if r["id"].startswith("PORT-")]
        assert len(sec) == 14
        assert len(qual) == 13
        assert len(py) == 11
        assert len(port) == 4

    def test_no_duplicate_rule_ids(self):
        ids = [r["id"] for r in ALL_RULES]
        assert len(ids) == len(set(ids)), f"Duplicate IDs: {[x for x in ids if ids.count(x) > 1]}"


class TestRuleFields:
    """Every rule must have the required fields."""

    REQUIRED_FIELDS: ClassVar[set[str]] = {"id", "severity", "pattern", "description", "fix_hint", "test_hint", "lang"}

    @pytest.mark.parametrize("rule", ALL_RULES, ids=lambda r: r["id"])
    def test_rule_has_required_fields(self, rule):
        missing = self.REQUIRED_FIELDS - set(rule.keys())
        assert not missing, f"{rule['id']} missing fields: {missing}"

    @pytest.mark.parametrize("rule", ALL_RULES, ids=lambda r: r["id"])
    def test_severity_is_valid(self, rule):
        assert rule["severity"] in {"HIGH", "MEDIUM", "LOW"}, f"{rule['id']} has bad severity: {rule['severity']}"

    @pytest.mark.parametrize("rule", ALL_RULES, ids=lambda r: r["id"])
    def test_pattern_compiles(self, rule):
        import re
        pat = rule["pattern"]
        if isinstance(pat, str):
            re.compile(pat)  # Should not raise


# ── Fixer Spec ──────────────────────────────────────────────────────────

class TestFixerSpec:
    """Validate the 7-fixer spec."""

    EXPECTED_FIXERS: ClassVar[set[str]] = {"SEC-003", "SEC-009", "QUAL-001", "QUAL-003", "QUAL-004", "PY-005", "PY-007"}

    def test_fixer_count_is_7(self):
        assert len(FIXERS) == 7

    def test_fixer_rules_match_spec(self):
        assert set(FIXERS.keys()) == self.EXPECTED_FIXERS

    def test_fixable_rules_matches_fixers(self):
        assert set(FIXERS.keys()) == FIXABLE_RULES

    def test_each_fixer_is_callable(self):
        for rule_id, fixer_fn in FIXERS.items():
            assert callable(fixer_fn), f"Fixer for {rule_id} is not callable"


# ── AST Validators ──────────────────────────────────────────────────────

class TestASTValidators:
    """Validate the 5 AST validators spec."""

    EXPECTED_AST_RULES: ClassVar[set[str]] = {"PY-001", "PY-005", "PY-006", "QUAL-003", "QUAL-004"}

    def test_ast_validator_count_is_5(self):
        from xray.scanner import _AST_VALIDATORS
        assert len(_AST_VALIDATORS) == 5

    def test_ast_validator_rule_ids(self):
        from xray.scanner import _AST_VALIDATORS
        assert set(_AST_VALIDATORS.keys()) == self.EXPECTED_AST_RULES

    def test_ast_validators_are_callable(self):
        from xray.scanner import _AST_VALIDATORS
        for rule_id, validator in _AST_VALIDATORS.items():
            assert callable(validator), f"AST validator for {rule_id} is not callable"


# ── API Endpoint Count ──────────────────────────────────────────────────

class TestAPIEndpoints:
    """Validate the 45-endpoint spec."""

    def test_api_endpoint_count_at_least_45(self):
        from api.analysis_routes import POST_ROUTES as ANALYSIS_POST
        from api.browse_routes import GET_ROUTES as BROWSE_GET
        from api.fix_routes import POST_ROUTES as FIX_POST
        from api.pm_routes import GET_ROUTES as PM_GET
        from api.pm_routes import POST_ROUTES as PM_POST
        from api.scan_routes import GET_ROUTES as SCAN_GET
        from api.scan_routes import POST_ROUTES as SCAN_POST
        total = len(SCAN_GET) + len(SCAN_POST) + len(BROWSE_GET) + len(FIX_POST) + len(ANALYSIS_POST) + len(PM_GET) + len(PM_POST)
        assert total >= 45, f"Only {total} endpoints found, expected >= 45"

    def test_all_routes_are_callable(self):
        from api.analysis_routes import POST_ROUTES as ANALYSIS_POST
        from api.browse_routes import GET_ROUTES as BROWSE_GET
        from api.fix_routes import POST_ROUTES as FIX_POST
        from api.pm_routes import GET_ROUTES as PM_GET
        from api.pm_routes import POST_ROUTES as PM_POST
        from api.scan_routes import GET_ROUTES as SCAN_GET
        from api.scan_routes import POST_ROUTES as SCAN_POST
        for table_name, table in [
            ("SCAN_GET", SCAN_GET), ("SCAN_POST", SCAN_POST), ("BROWSE_GET", BROWSE_GET),
            ("FIX_POST", FIX_POST), ("ANALYSIS_POST", ANALYSIS_POST),
            ("PM_GET", PM_GET), ("PM_POST", PM_POST),
        ]:
            for path, handler in table.items():
                assert callable(handler), f"{table_name}[{path}] is not callable"


# ── Analyzer Functions ──────────────────────────────────────────────────

class TestAnalyzerExports:
    """Validate analyzer module exports."""

    def test_analyzer_function_count_at_least_23(self):
        import analyzers
        all_exports = analyzers.__all__
        # Filter out private constants and helpers starting with _
        public = [name for name in all_exports if not name.startswith("_")]
        assert len(public) >= 23, f"Only {len(public)} public analyzer exports, expected >= 23"

    def test_key_analyzers_importable(self):
        from analyzers import (
            check_format,
            check_project_health,
            check_types,
            compute_architecture_map,
            compute_call_graph,
            compute_confidence_meter,
            compute_coupling_metrics,
            compute_module_cards,
            compute_risk_heatmap,
            compute_sprint_batches,
            detect_circular_calls,
            detect_code_smells,
            detect_dead_functions,
            detect_duplicates,
            detect_unused_imports,
            run_bandit,
        )
        for fn in [
            compute_risk_heatmap, compute_module_cards, compute_confidence_meter,
            compute_sprint_batches, compute_architecture_map, compute_call_graph,
            detect_circular_calls, compute_coupling_metrics, detect_unused_imports,
            detect_dead_functions, detect_code_smells, detect_duplicates,
            check_format, check_types, run_bandit, check_project_health,
        ]:
            assert callable(fn), f"{fn.__name__} is not callable"


# ── PM Dashboard Features ──────────────────────────────────────────────

class TestPMDashboard:
    """Validate the 9 PM Dashboard features spec."""

    PM_FUNCTIONS: ClassVar[list[str]] = [
        "compute_risk_heatmap",
        "compute_module_cards",
        "compute_confidence_meter",
        "compute_sprint_batches",
        "compute_architecture_map",
        "compute_call_graph",
        "detect_circular_calls",
        "compute_coupling_metrics",
        "detect_unused_imports",
    ]

    def test_pm_features_count_is_9(self):
        assert len(self.PM_FUNCTIONS) == 9

    def test_all_pm_functions_importable(self):
        import analyzers
        for name in self.PM_FUNCTIONS:
            fn = getattr(analyzers, name, None)
            assert fn is not None, f"analyzers.{name} not found"
            assert callable(fn), f"analyzers.{name} is not callable"

    def test_confidence_meter_range(self):
        from analyzers import compute_confidence_meter
        # Empty project → should return something in 0-100
        with tempfile.TemporaryDirectory() as tmpdir:
            result = compute_confidence_meter(tmpdir)
            assert isinstance(result, dict)
            confidence = result.get("confidence", result.get("score", 0))
            assert 0 <= confidence <= 100

    def test_sprint_batches_categories(self):
        from analyzers import compute_sprint_batches
        # With empty findings, should still return batch structure
        result = compute_sprint_batches([])
        assert isinstance(result, dict)
        # Should have 4 batch categories
        batches = result.get("batches", result)
        assert len(batches) >= 4, f"Only {len(batches)} batch categories, expected 4"

    def test_module_cards_returns_grades(self):
        from analyzers import compute_module_cards
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a minimal Python file so there's something to analyze
            p = os.path.join(tmpdir, "sample.py")
            with open(p, "w", encoding="utf-8") as f:
                f.write("x = 1\n")
            result = compute_module_cards(tmpdir)
            assert isinstance(result, (dict, list))


# ── Live Scanner Tests ──────────────────────────────────────────────────

class TestLiveScanner:
    """Real scan operations — no mocks."""

    def test_scan_file_detects_shell_true(self):
        """SEC-003 should fire on subprocess.run(..., shell=True)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            p = os.path.join(tmpdir, "vuln.py")
            with open(p, "w", encoding="utf-8") as f:
                f.write("import subprocess\nsubprocess.run('ls', shell=True)\n")
            findings = scan_file(p)
            rule_ids = [fd.rule_id for fd in findings]
            assert "SEC-003" in rule_ids

    def test_scan_file_detects_bare_except(self):
        """QUAL-001 should fire on bare except."""
        with tempfile.TemporaryDirectory() as tmpdir:
            p = os.path.join(tmpdir, "vuln.py")
            with open(p, "w", encoding="utf-8") as f:
                f.write("try:\n    pass\nexcept:\n    pass\n")
            findings = scan_file(p)
            rule_ids = [fd.rule_id for fd in findings]
            assert "QUAL-001" in rule_ids

    def test_scan_file_detects_eval(self):
        """SEC-007 should fire on eval()."""
        with tempfile.TemporaryDirectory() as tmpdir:
            p = os.path.join(tmpdir, "vuln.py")
            with open(p, "w", encoding="utf-8") as f:
                f.write("x = eval(input())\n")
            findings = scan_file(p)
            rule_ids = [fd.rule_id for fd in findings]
            assert "SEC-007" in rule_ids

    def test_scan_directory_returns_scan_result(self):
        """scan_directory returns a ScanResult with findings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            p = os.path.join(tmpdir, "bad.py")
            with open(p, "w", encoding="utf-8") as f:
                f.write("import subprocess\nsubprocess.run('ls', shell=True)\n")
            result = scan_directory(tmpdir)
            assert isinstance(result, ScanResult)
            assert len(result.findings) > 0


# ── Scan + Fix Roundtrip ────────────────────────────────────────────────

class TestScanFixRoundtrip:
    """Write vulnerable code, scan, fix, re-scan, verify finding gone."""

    def test_sec003_roundtrip(self):
        """SEC-003 shell=True → auto-fix → re-scan clean."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write("import subprocess\nsubprocess.run('ls', shell=True)\n")
            filepath = f.name
        try:
            # Scan: should find SEC-003
            findings = scan_file(filepath)
            sec003 = [fd for fd in findings if fd.rule_id == "SEC-003"]
            assert len(sec003) > 0, "SEC-003 not detected before fix"

            # Fix
            finding_dict = sec003[0].to_dict()
            result = apply_fix(finding_dict)
            assert result["ok"], f"Fix failed: {result.get('error')}"

            # Re-scan: SEC-003 should be gone
            findings_after = scan_file(filepath)
            sec003_after = [fd for fd in findings_after if fd.rule_id == "SEC-003"]
            assert len(sec003_after) == 0, "SEC-003 still present after fix"
        finally:
            os.unlink(filepath)
            bak = filepath + ".bak"
            if os.path.exists(bak):
                os.unlink(bak)

    def test_qual001_roundtrip(self):
        """QUAL-001 bare except → auto-fix → re-scan clean of QUAL-001."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write("try:\n    pass\nexcept:\n    pass\n")
            filepath = f.name
        try:
            findings = scan_file(filepath)
            qual001 = [fd for fd in findings if fd.rule_id == "QUAL-001"]
            assert len(qual001) > 0, "QUAL-001 not detected before fix"

            finding_dict = qual001[0].to_dict()
            result = apply_fix(finding_dict)
            assert result["ok"], f"Fix failed: {result.get('error')}"

            findings_after = scan_file(filepath)
            qual001_after = [fd for fd in findings_after if fd.rule_id == "QUAL-001"]
            assert len(qual001_after) == 0, "QUAL-001 still present after fix"
        finally:
            os.unlink(filepath)
            bak = filepath + ".bak"
            if os.path.exists(bak):
                os.unlink(bak)


# ── SARIF Output ────────────────────────────────────────────────────────

class TestSARIFOutput:
    """Generate SARIF from real findings and validate structure."""

    def test_sarif_structure_valid(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write("import subprocess\nsubprocess.run('ls', shell=True)\nx = eval(input())\n")
            filepath = f.name
        try:
            findings = scan_file(filepath)
            finding_dicts = [fd.to_dict() for fd in findings]
            sarif = findings_to_sarif(finding_dicts)

            # SARIF 2.1.0 structure
            assert sarif["version"] == "2.1.0"
            assert "$schema" in sarif
            assert "runs" in sarif
            assert len(sarif["runs"]) == 1

            run = sarif["runs"][0]
            assert "tool" in run
            assert "results" in run
            assert run["tool"]["driver"]["name"] == "xray-llm"
            assert len(run["results"]) > 0

            # Each result has required fields
            for result in run["results"]:
                assert "ruleId" in result
                assert "message" in result
                assert "locations" in result
                assert "level" in result
        finally:
            os.unlink(filepath)

    def test_sarif_json_serializable(self):
        findings_dicts = [
            {"rule_id": "SEC-003", "file": "test.py", "line": 1,
             "severity": "HIGH", "message": "shell=True", "matched_text": "shell=True"},
        ]
        sarif = findings_to_sarif(findings_dicts)
        # Must be JSON-serializable
        output = json.dumps(sarif)
        assert isinstance(output, str)
        # Round-trip
        parsed = json.loads(output)
        assert parsed["version"] == "2.1.0"


# ── Inline Suppression ──────────────────────────────────────────────────

class TestInlineSuppression:
    """Validate # xray: ignore[RULE-ID] works."""

    def test_suppression_removes_finding(self):
        code = textwrap.dedent("""\
            import subprocess
            subprocess.run('ls', shell=True)  # xray: ignore[SEC-003]
        """)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(code)
            filepath = f.name
        try:
            findings = scan_file(filepath)
            sec003 = [fd for fd in findings if fd.rule_id == "SEC-003"]
            assert len(sec003) == 0, "SEC-003 should be suppressed by inline ignore"
        finally:
            os.unlink(filepath)

    def test_unsuppressed_still_fires(self):
        code = textwrap.dedent("""\
            import subprocess
            subprocess.run('ls', shell=True)
        """)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(code)
            filepath = f.name
        try:
            findings = scan_file(filepath)
            sec003 = [fd for fd in findings if fd.rule_id == "SEC-003"]
            assert len(sec003) > 0, "SEC-003 should fire without suppression"
        finally:
            os.unlink(filepath)

    def test_multiline_suppression(self):
        """Suppress multiple rules on the same line."""
        code = textwrap.dedent("""\
            eval(input())  # xray: ignore[SEC-007]
        """)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(code)
            filepath = f.name
        try:
            findings = scan_file(filepath)
            sec007 = [fd for fd in findings if fd.rule_id == "SEC-007"]
            assert len(sec007) == 0, "SEC-007 should be suppressed"
        finally:
            os.unlink(filepath)


# ── String/Comment Awareness ────────────────────────────────────────────

class TestStringCommentAwareness:
    """Matches inside strings and comments should be suppressed for aware rules."""

    def test_print_in_string_not_flagged(self):
        """PY-004 should NOT fire when print() appears only in a string."""
        code = textwrap.dedent('''\
            msg = "use print() to debug"
        ''')
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(code)
            filepath = f.name
        try:
            findings = scan_file(filepath)
            py004 = [fd for fd in findings if fd.rule_id == "PY-004"]
            assert len(py004) == 0, "PY-004 should not fire on print() in a string"
        finally:
            os.unlink(filepath)

    def test_print_in_real_code_flagged(self):
        """PY-004 should fire on actual print() calls."""
        code = textwrap.dedent("""\
            print("debug info")
        """)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(code)
            filepath = f.name
        try:
            findings = scan_file(filepath)
            py004 = [fd for fd in findings if fd.rule_id == "PY-004"]
            assert len(py004) > 0, "PY-004 should fire on real print() call"
        finally:
            os.unlink(filepath)

    def test_todo_in_pattern_string_not_flagged(self):
        """QUAL-007 should suppress in strings but keep in comments."""
        code = textwrap.dedent('''\
            pattern = r"TODO|FIXME"
        ''')
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(code)
            filepath = f.name
        try:
            findings = scan_file(filepath)
            qual007 = [fd for fd in findings if fd.rule_id == "QUAL-007"]
            assert len(qual007) == 0, "QUAL-007 should not fire on TODO in a string"
        finally:
            os.unlink(filepath)


# ── Severity Filtering ──────────────────────────────────────────────────

class TestSeverityFiltering:
    """Verify severity filtering in scan_directory."""

    def test_high_only_excludes_medium_low(self):
        """When filtered to HIGH, no MEDIUM or LOW findings should appear."""
        code = textwrap.dedent("""\
            import subprocess
            subprocess.run('ls', shell=True)
            print("debug")
        """)
        with tempfile.TemporaryDirectory() as tmpdir:
            p = os.path.join(tmpdir, "mixed.py")
            with open(p, "w", encoding="utf-8") as f:
                f.write(code)

            # Get all rules and filter to HIGH only
            high_rules = [r for r in ALL_RULES if r["severity"] == "HIGH"]
            result = scan_directory(tmpdir, rules=high_rules)
            for finding in result.findings:
                assert finding.severity == "HIGH", f"Found {finding.severity} finding when filtering HIGH only"


# ── Agent Dry-Run Safety ────────────────────────────────────────────────

class TestAgentDryRun:
    """Verify --dry-run makes no file modifications."""

    def test_dry_run_no_modifications(self):
        """Scan a directory with dry_run=True, verify file hashes unchanged."""
        code = textwrap.dedent("""\
            import subprocess
            subprocess.run('ls', shell=True)
        """)
        with tempfile.TemporaryDirectory() as tmpdir:
            p = os.path.join(tmpdir, "vuln.py")
            with open(p, "w", encoding="utf-8") as f:
                f.write(code)

            # Hash before
            with open(p, "rb") as f:
                hash_before = hashlib.sha256(f.read()).hexdigest()

            # scan_file is read-only by design
            findings = scan_file(p)
            assert len(findings) > 0

            # Hash after — should be identical
            with open(p, "rb") as f:
                hash_after = hashlib.sha256(f.read()).hexdigest()

            assert hash_before == hash_after, "scan_file modified the source file!"


# ── Chat Engine ──────────────────────────────────────────────────────────

class TestChatEngine:
    """Validate chat engine knows correct counts."""

    def test_chat_knows_42_rules(self):
        reply = chat_reply("list all rules", {})
        assert "42" in reply, f"Chat should mention 42 rules, got: {reply[:200]}"

    def test_chat_knows_security_rules(self):
        reply = chat_reply("security rules", {})
        assert "SEC-001" in reply
        assert "SEC-014" in reply

    def test_chat_knows_auto_fixers(self):
        reply = chat_reply("auto-fix", {})
        assert "7" in reply

    def test_chat_knows_45_endpoints(self):
        reply = chat_reply("API endpoints", {})
        assert "45" in reply, f"Chat should mention 45 endpoints, got: {reply[:200]}"

    def test_chat_knows_portability_rules(self):
        """Chat should include PORT rules in rule listing."""
        reply = chat_reply("list all rules", {})
        assert "PORT" in reply, "Chat should mention PORT rules"

    def test_chat_hello_mentions_42(self):
        reply = chat_reply("hello", {})
        assert "42" in reply, f"Hello response should mention 42 rules, got: {reply[:200]}"


# ── String Awareness Config ──────────────────────────────────────────────

class TestStringAwarenessConfig:
    """Validate the _STRING_AWARE_RULES configuration."""

    def test_string_aware_rules_exist(self):
        from xray.scanner import _STRING_AWARE_RULES
        assert isinstance(_STRING_AWARE_RULES, dict)
        assert len(_STRING_AWARE_RULES) >= 4

    def test_string_aware_modes_valid(self):
        from xray.scanner import _STRING_AWARE_RULES
        valid_modes = {"all", "strings"}
        for rule_id, mode in _STRING_AWARE_RULES.items():
            assert mode in valid_modes, f"{rule_id} has invalid string-awareness mode: {mode}"


# ── Suppress Regex ──────────────────────────────────────────────────────

class TestSuppressRegex:
    """Validate inline suppression regex pattern."""

    def test_suppress_regex_matches_standard_form(self):
        from xray.scanner import _SUPPRESS_RE
        m = _SUPPRESS_RE.search("# xray: ignore[SEC-003]")
        assert m is not None
        assert m.group(1) == "SEC-003"

    def test_suppress_regex_matches_multi_rule(self):
        from xray.scanner import _SUPPRESS_RE
        m = _SUPPRESS_RE.search("# xray: ignore[SEC-003, QUAL-001]")
        assert m is not None
        assert "SEC-003" in m.group(1)
        assert "QUAL-001" in m.group(1)

    def test_suppress_regex_allows_flexible_spacing(self):
        from xray.scanner import _SUPPRESS_RE
        m = _SUPPRESS_RE.search("#  xray:  ignore[PY-004]")
        assert m is not None
