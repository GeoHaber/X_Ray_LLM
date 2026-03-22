"""
Tests for xray/sarif.py — SARIF output generation.

Covers:
  - findings_to_sarif structure
  - Severity mapping
  - Rule deduplication
  - write_sarif file output
  - sarif_to_json_string
  - Edge cases (empty findings, missing fields)
"""

import json
import os
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from xray.sarif import (
    _SARIF_SCHEMA,
    _SARIF_VERSION,
    _SEVERITY_MAP,
    _rule_category,
    findings_to_sarif,
    sarif_to_json_string,
    write_sarif,
)

# ── Sample findings ─────────────────────────────────────────────────────

_SAMPLE_FINDINGS = [
    {
        "rule_id": "SEC-001",
        "severity": "HIGH",
        "file": "app.py",
        "line": 10,
        "col": 5,
        "matched_text": "render(template)",
        "description": "XSS via template literal",
        "fix_hint": "Use autoescape",
        "test_hint": "Test with script tags",
    },
    {
        "rule_id": "QUAL-001",
        "severity": "MEDIUM",
        "file": "utils.py",
        "line": 42,
        "col": 1,
        "matched_text": "except:",
        "description": "Bare except catches everything",
        "fix_hint": "Use except Exception",
        "test_hint": "Test error handling",
    },
    {
        "rule_id": "SEC-001",  # Duplicate rule
        "severity": "HIGH",
        "file": "views.py",
        "line": 88,
        "col": 3,
        "matched_text": "render(tpl)",
        "description": "XSS via template literal",
        "fix_hint": "Use autoescape",
        "test_hint": "Test with script tags",
    },
]


class TestRuleCategory:
    def test_security_prefix(self):
        assert _rule_category("SEC-001") == "security"

    def test_quality_prefix(self):
        assert _rule_category("QUAL-003") == "maintainability"

    def test_python_prefix(self):
        assert _rule_category("PY-005") == "correctness"

    def test_portability_prefix(self):
        assert _rule_category("PORT-001") == "portability"

    def test_unknown_prefix(self):
        assert _rule_category("UNKNOWN-01") == "general"

    def test_no_dash(self):
        assert _rule_category("CUSTOM") == "general"


class TestSeverityMap:
    def test_high_maps_to_error(self):
        assert _SEVERITY_MAP["HIGH"] == "error"

    def test_medium_maps_to_warning(self):
        assert _SEVERITY_MAP["MEDIUM"] == "warning"

    def test_low_maps_to_note(self):
        assert _SEVERITY_MAP["LOW"] == "note"


class TestFindingsToSarif:
    def test_basic_structure(self):
        sarif = findings_to_sarif(_SAMPLE_FINDINGS)
        assert sarif["$schema"] == _SARIF_SCHEMA
        assert sarif["version"] == _SARIF_VERSION
        assert len(sarif["runs"]) == 1

    def test_tool_info(self):
        sarif = findings_to_sarif(_SAMPLE_FINDINGS, tool_name="test-tool", tool_version="1.0.0")
        driver = sarif["runs"][0]["tool"]["driver"]
        assert driver["name"] == "test-tool"
        assert driver["version"] == "1.0.0"

    def test_rules_deduplicated(self):
        sarif = findings_to_sarif(_SAMPLE_FINDINGS)
        rules = sarif["runs"][0]["tool"]["driver"]["rules"]
        rule_ids = [r["id"] for r in rules]
        assert rule_ids == ["SEC-001", "QUAL-001"]  # SEC-001 only once

    def test_results_count(self):
        sarif = findings_to_sarif(_SAMPLE_FINDINGS)
        results = sarif["runs"][0]["results"]
        assert len(results) == 3

    def test_result_severity_mapping(self):
        sarif = findings_to_sarif(_SAMPLE_FINDINGS)
        results = sarif["runs"][0]["results"]
        assert results[0]["level"] == "error"   # HIGH
        assert results[1]["level"] == "warning"  # MEDIUM

    def test_result_location(self):
        sarif = findings_to_sarif(_SAMPLE_FINDINGS)
        result = sarif["runs"][0]["results"][0]
        loc = result["locations"][0]["physicalLocation"]
        assert loc["artifactLocation"]["uri"] == "app.py"
        assert loc["region"]["startLine"] == 10
        assert loc["region"]["startColumn"] == 5

    def test_fixes_present(self):
        sarif = findings_to_sarif(_SAMPLE_FINDINGS)
        result = sarif["runs"][0]["results"][0]
        assert "fixes" in result
        assert result["fixes"][0]["description"]["text"] == "Use autoescape"

    def test_rule_index_matches(self):
        sarif = findings_to_sarif(_SAMPLE_FINDINGS)
        results = sarif["runs"][0]["results"]
        assert results[0]["ruleIndex"] == 0  # SEC-001 first
        assert results[1]["ruleIndex"] == 1  # QUAL-001 second
        assert results[2]["ruleIndex"] == 0  # SEC-001 duplicate

    def test_invocations(self):
        sarif = findings_to_sarif(_SAMPLE_FINDINGS)
        invocations = sarif["runs"][0]["invocations"]
        assert len(invocations) == 1
        assert invocations[0]["executionSuccessful"] is True
        assert "endTimeUtc" in invocations[0]

    def test_empty_findings(self):
        sarif = findings_to_sarif([])
        assert sarif["runs"][0]["results"] == []
        assert sarif["runs"][0]["tool"]["driver"]["rules"] == []

    def test_missing_fields_handled(self):
        minimal = [{"rule_id": "X", "description": "test"}]
        sarif = findings_to_sarif(minimal)
        result = sarif["runs"][0]["results"][0]
        assert result["ruleId"] == "X"
        loc = result["locations"][0]["physicalLocation"]["region"]
        assert loc["startLine"] >= 1
        assert loc["startColumn"] >= 1

    def test_backslash_normalized(self):
        finding = [{
            "rule_id": "T-001",
            "severity": "LOW",
            "file": "src\\utils\\helper.py",
            "line": 5,
            "col": 1,
            "description": "test",
        }]
        sarif = findings_to_sarif(finding)
        uri = sarif["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
        assert "\\" not in uri
        assert uri == "src/utils/helper.py"


class TestWriteSarif:
    def test_writes_valid_json(self):
        fd, path = tempfile.mkstemp(suffix=".sarif")
        os.close(fd)
        try:
            write_sarif(_SAMPLE_FINDINGS, path)
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            assert data["version"] == _SARIF_VERSION
            assert len(data["runs"][0]["results"]) == 3
        finally:
            os.unlink(path)


class TestSarifToJsonString:
    def test_returns_valid_json_string(self):
        s = sarif_to_json_string(_SAMPLE_FINDINGS)
        data = json.loads(s)
        assert data["version"] == _SARIF_VERSION

    def test_empty_findings(self):
        s = sarif_to_json_string([])
        data = json.loads(s)
        assert data["runs"][0]["results"] == []
