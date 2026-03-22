"""
Tests for xray/sca.py — Software Composition Analysis.

Covers:
  - _empty_summary structure
  - _map_severity heuristics
  - scan_dependencies with pip-audit mocked
  - Missing pip-audit handling
  - Missing requirements handling
  - Timeout handling
  - JSON parse failure handling
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from xray.sca import _empty_summary, _map_severity, scan_dependencies


class TestEmptySummary:
    def test_structure(self):
        s = _empty_summary()
        assert s == {"total": 0, "critical": 0, "high": 0, "medium": 0, "low": 0}

    def test_returns_new_dict(self):
        a = _empty_summary()
        b = _empty_summary()
        a["total"] = 99
        assert b["total"] == 0


class TestMapSeverity:
    def test_cve_alias_maps_high(self):
        assert _map_severity(["CVE-2024-1234"], "GHSA-xxx") == "HIGH"

    def test_ghsa_maps_high(self):
        assert _map_severity([], "GHSA-abc-def") == "HIGH"

    def test_pysec_maps_medium(self):
        assert _map_severity([], "PYSEC-2024-001") == "MEDIUM"

    def test_unknown_maps_medium(self):
        assert _map_severity([], "SOMETHING-ELSE") == "MEDIUM"

    def test_cve_case_insensitive(self):
        assert _map_severity(["cve-2024-5678"], "whatever") == "HIGH"


class TestScanDependencies:
    def test_no_pip_audit(self, tmp_path):
        """Should return error when pip-audit is not installed."""
        with patch("xray.sca.shutil.which", return_value=None):
            result = scan_dependencies(str(tmp_path))
        assert result["error"] == "pip-audit not installed"
        assert result["vulnerabilities"] == []

    def test_no_requirements_files(self, tmp_path):
        """Should return error when no requirements files exist."""
        with patch("xray.sca.shutil.which", return_value="/usr/bin/pip-audit"):
            result = scan_dependencies(str(tmp_path))
        assert "No requirements" in result["error"]

    def test_successful_scan(self, tmp_path):
        """Simulates a successful pip-audit scan with vulnerabilities."""
        (tmp_path / "requirements.txt").write_text("flask==2.0.0\n")
        mock_output = json.dumps({
            "dependencies": [
                {
                    "name": "flask",
                    "version": "2.0.0",
                    "vulns": [
                        {
                            "id": "CVE-2023-12345",
                            "aliases": ["CVE-2023-12345"],
                            "fix_versions": ["2.3.3"],
                        }
                    ],
                }
            ]
        })
        mock_proc = MagicMock()
        mock_proc.stdout = mock_output
        mock_proc.stderr = ""

        with (
            patch("xray.sca.shutil.which", return_value="/usr/bin/pip-audit"),
            patch("xray.sca.subprocess.run", return_value=mock_proc),
        ):
            result = scan_dependencies(str(tmp_path))

        assert result["error"] == ""
        assert len(result["vulnerabilities"]) == 1
        vuln = result["vulnerabilities"][0]
        assert vuln["package"] == "flask"
        assert vuln["severity"] == "HIGH"
        assert "2.3.3" in vuln["fixed_versions"]
        assert result["summary"]["total"] == 1
        assert result["summary"]["high"] == 1

    def test_clean_scan(self, tmp_path):
        """Simulates a clean pip-audit scan with no vulnerabilities."""
        (tmp_path / "requirements.txt").write_text("pytest==7.0.0\n")
        mock_proc = MagicMock()
        mock_proc.stdout = json.dumps({"dependencies": [{"name": "pytest", "version": "7.0.0", "vulns": []}]})
        mock_proc.stderr = ""

        with (
            patch("xray.sca.shutil.which", return_value="/usr/bin/pip-audit"),
            patch("xray.sca.subprocess.run", return_value=mock_proc),
        ):
            result = scan_dependencies(str(tmp_path))

        assert result["error"] == ""
        assert result["vulnerabilities"] == []
        assert result["summary"]["total"] == 0

    def test_timeout(self, tmp_path):
        """Should handle pip-audit timeout."""
        (tmp_path / "requirements.txt").write_text("foo\n")
        import subprocess

        with (
            patch("xray.sca.shutil.which", return_value="/usr/bin/pip-audit"),
            patch("xray.sca.subprocess.run", side_effect=subprocess.TimeoutExpired("pip-audit", 120)),
        ):
            result = scan_dependencies(str(tmp_path))

        assert "timed out" in result["error"]

    def test_invalid_json_output(self, tmp_path):
        """Should handle invalid JSON from pip-audit."""
        (tmp_path / "requirements.txt").write_text("foo\n")
        mock_proc = MagicMock()
        mock_proc.stdout = "not valid json"
        mock_proc.stderr = "some error"

        with (
            patch("xray.sca.shutil.which", return_value="/usr/bin/pip-audit"),
            patch("xray.sca.subprocess.run", return_value=mock_proc),
        ):
            result = scan_dependencies(str(tmp_path))

        assert result["vulnerabilities"] == []
        assert "some error" in result["error"]

    def test_multiple_requirements_files(self, tmp_path):
        """Should pass both requirements files to pip-audit."""
        (tmp_path / "requirements.txt").write_text("flask\n")
        (tmp_path / "requirements-dev.txt").write_text("pytest\n")
        mock_proc = MagicMock()
        mock_proc.stdout = json.dumps({"dependencies": []})
        mock_proc.stderr = ""

        with (
            patch("xray.sca.shutil.which", return_value="/usr/bin/pip-audit"),
            patch("xray.sca.subprocess.run", return_value=mock_proc) as mock_run,
        ):
            scan_dependencies(str(tmp_path))

        # Verify both -r flags in the command
        cmd = mock_run.call_args[0][0]
        r_flags = [i for i, arg in enumerate(cmd) if arg == "-r"]
        assert len(r_flags) == 2
