"""
X-Ray Config — Project-level configuration from pyproject.toml.

Reads [tool.xray] section from pyproject.toml for per-project settings.
Falls back to CLI args / environment variables.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Use tomllib (3.11+) with tomli fallback
try:
    import tomllib
except ModuleNotFoundError:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError:
        tomllib = None  # type: ignore[assignment]


@dataclass
class XRayConfig:
    """Project-level X-Ray configuration."""

    severity: str = "MEDIUM"
    exclude_patterns: list[str] = field(default_factory=list)
    output_format: str = "text"  # text, json, sarif
    incremental: bool = False
    parallel: bool = True
    rules_dir: str = ""
    suppress_rules: list[str] = field(default_factory=list)
    max_file_size: int = 1_048_576

    @staticmethod
    def from_pyproject(project_root: str) -> "XRayConfig":
        """Load config from [tool.xray] in pyproject.toml."""
        config = XRayConfig()
        pyproject_path = Path(project_root) / "pyproject.toml"

        if not pyproject_path.is_file():
            return config

        if tomllib is None:
            logger.debug("tomllib not available — skipping pyproject.toml config")
            return config

        try:
            with open(pyproject_path, "rb") as f:
                data = tomllib.load(f)
        except Exception as e:
            logger.warning("Failed to parse pyproject.toml: %s", e)
            return config

        xray_config = data.get("tool", {}).get("xray", {})
        if not xray_config:
            return config

        if "severity" in xray_config:
            sev = str(xray_config["severity"]).upper()
            if sev in ("HIGH", "MEDIUM", "LOW"):
                config.severity = sev

        if "exclude" in xray_config:
            config.exclude_patterns = list(xray_config["exclude"])

        if "output-format" in xray_config:
            fmt = str(xray_config["output-format"]).lower()
            if fmt in ("text", "json", "sarif"):
                config.output_format = fmt

        if "incremental" in xray_config:
            config.incremental = bool(xray_config["incremental"])

        if "parallel" in xray_config:
            config.parallel = bool(xray_config["parallel"])

        if "rules-dir" in xray_config:
            config.rules_dir = str(xray_config["rules-dir"])

        if "suppress" in xray_config:
            config.suppress_rules = list(xray_config["suppress"])

        if "max-file-size" in xray_config:
            config.max_file_size = int(xray_config["max-file-size"])

        return config

    def merge_cli(
        self,
        *,
        severity: str = "",
        exclude: list[str] | None = None,
        output_format: str = "",
        incremental: bool | None = None,
        parallel: bool | None = None,
    ):
        """Merge CLI overrides (CLI takes precedence over pyproject.toml)."""
        if severity:
            self.severity = severity
        if exclude:
            self.exclude_patterns.extend(exclude)
        if output_format:
            self.output_format = output_format
        if incremental is not None:
            self.incremental = incremental
        if parallel is not None:
            self.parallel = parallel
