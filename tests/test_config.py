"""
Tests for xray/config.py — Project-level configuration.

Covers:
  - XRayConfig defaults
  - from_pyproject loading
  - Missing/invalid pyproject.toml
  - merge_cli overrides
  - All config fields
"""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from xray.config import XRayConfig


class TestXRayConfigDefaults:
    def test_default_severity(self):
        c = XRayConfig()
        assert c.severity == "MEDIUM"

    def test_default_output_format(self):
        c = XRayConfig()
        assert c.output_format == "text"

    def test_default_parallel(self):
        c = XRayConfig()
        assert c.parallel is True

    def test_default_incremental(self):
        c = XRayConfig()
        assert c.incremental is False

    def test_default_max_file_size(self):
        c = XRayConfig()
        assert c.max_file_size == 1_048_576

    def test_default_exclude_patterns(self):
        c = XRayConfig()
        assert c.exclude_patterns == []

    def test_default_suppress_rules(self):
        c = XRayConfig()
        assert c.suppress_rules == []


class TestFromPyproject:
    def test_missing_file(self, tmp_path):
        """Should return defaults if pyproject.toml doesn't exist."""
        config = XRayConfig.from_pyproject(str(tmp_path))
        assert config.severity == "MEDIUM"
        assert config.parallel is True

    def test_no_xray_section(self, tmp_path):
        """Should return defaults if [tool.xray] section doesn't exist."""
        (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nline-length = 120\n")
        config = XRayConfig.from_pyproject(str(tmp_path))
        assert config.severity == "MEDIUM"

    def test_reads_severity(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[tool.xray]\nseverity = "HIGH"\n')
        config = XRayConfig.from_pyproject(str(tmp_path))
        assert config.severity == "HIGH"

    def test_reads_exclude(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[tool.xray]\nexclude = ["tests/*", "docs/*"]\n')
        config = XRayConfig.from_pyproject(str(tmp_path))
        assert config.exclude_patterns == ["tests/*", "docs/*"]

    def test_reads_output_format(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[tool.xray]\noutput-format = "sarif"\n')
        config = XRayConfig.from_pyproject(str(tmp_path))
        assert config.output_format == "sarif"

    def test_reads_incremental(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[tool.xray]\nincremental = true\n")
        config = XRayConfig.from_pyproject(str(tmp_path))
        assert config.incremental is True

    def test_reads_parallel(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[tool.xray]\nparallel = false\n")
        config = XRayConfig.from_pyproject(str(tmp_path))
        assert config.parallel is False

    def test_reads_rules_dir(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[tool.xray]\nrules-dir = "custom_rules"\n')
        config = XRayConfig.from_pyproject(str(tmp_path))
        assert config.rules_dir == "custom_rules"

    def test_reads_suppress(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[tool.xray]\nsuppress = ["PY-004", "QUAL-007"]\n')
        config = XRayConfig.from_pyproject(str(tmp_path))
        assert config.suppress_rules == ["PY-004", "QUAL-007"]

    def test_reads_max_file_size(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[tool.xray]\nmax-file-size = 2097152\n")
        config = XRayConfig.from_pyproject(str(tmp_path))
        assert config.max_file_size == 2_097_152

    def test_invalid_severity_ignored(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[tool.xray]\nseverity = "CRITICAL"\n')
        config = XRayConfig.from_pyproject(str(tmp_path))
        assert config.severity == "MEDIUM"  # Default - invalid value ignored

    def test_invalid_output_format_ignored(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[tool.xray]\noutput-format = "xml"\n')
        config = XRayConfig.from_pyproject(str(tmp_path))
        assert config.output_format == "text"  # Default

    def test_corrupt_toml(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("not a [valid toml file !!!!\n")
        config = XRayConfig.from_pyproject(str(tmp_path))
        assert config.severity == "MEDIUM"  # Falls back to defaults


class TestMergeCli:
    def test_cli_overrides_severity(self):
        config = XRayConfig()
        config.merge_cli(severity="HIGH")
        assert config.severity == "HIGH"

    def test_cli_extends_exclude(self):
        config = XRayConfig()
        config.exclude_patterns = ["a/*"]
        config.merge_cli(exclude=["b/*"])
        assert "a/*" in config.exclude_patterns
        assert "b/*" in config.exclude_patterns

    def test_cli_overrides_format(self):
        config = XRayConfig()
        config.merge_cli(output_format="json")
        assert config.output_format == "json"

    def test_cli_overrides_incremental(self):
        config = XRayConfig()
        config.merge_cli(incremental=True)
        assert config.incremental is True

    def test_cli_overrides_parallel(self):
        config = XRayConfig()
        config.merge_cli(parallel=False)
        assert config.parallel is False

    def test_empty_overrides_keep_defaults(self):
        config = XRayConfig()
        config.merge_cli()
        assert config.severity == "MEDIUM"
        assert config.output_format == "text"
        assert config.parallel is True
