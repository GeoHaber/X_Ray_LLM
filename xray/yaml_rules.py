"""
X-Ray YAML Rules — Load custom rule definitions from YAML files.

Allows users to define project-specific rules in .xray/rules/ (or a custom
directory via --rules-dir).  Each YAML file may contain one or more rules
under a top-level ``rules:`` key.

Required fields per rule: id, severity, pattern, description.
Optional fields: lang, fix_hint, test_hint, cwe, owasp, taint.
"""

import logging
import re
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _warn(msg: str) -> None:
    """Print warning to stderr (visible without logging config)."""
    print(f"xray: warning: {msg}", file=sys.stderr)

try:
    import yaml  # type: ignore[import-untyped]
except ModuleNotFoundError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

_REQUIRED_FIELDS = {"id", "severity", "pattern", "description"}
_VALID_SEVERITIES = {"HIGH", "MEDIUM", "LOW"}


def _validate_rule(rule: dict, source_file: str) -> str | None:
    """Return an error message if the rule is invalid, else None."""
    missing = _REQUIRED_FIELDS - set(rule.keys())
    if missing:
        return f"rule in {source_file}: missing required fields {sorted(missing)}"

    sev = str(rule["severity"]).upper()
    if sev not in _VALID_SEVERITIES:
        return f"rule '{rule.get('id')}' in {source_file}: invalid severity '{rule['severity']}' (must be HIGH/MEDIUM/LOW)"

    # Validate regex compiles
    try:
        re.compile(rule["pattern"])
    except re.error as exc:
        return f"rule '{rule.get('id')}' in {source_file}: invalid regex pattern: {exc}"

    return None


def _normalise_rule(raw: dict) -> dict:
    """Convert a validated YAML rule dict into the canonical rule format
    used by xray/rules/security.py et al."""
    rule: dict = {
        "id": str(raw["id"]),
        "severity": str(raw["severity"]).upper(),
        "pattern": str(raw["pattern"]),
        "description": str(raw["description"]),
    }

    # Language filter — default to all supported languages when absent
    if "lang" in raw:
        langs = raw["lang"]
        if isinstance(langs, str):
            langs = [langs]
        rule["lang"] = [str(l).lower() for l in langs]
    else:
        rule["lang"] = ["python", "javascript", "html", "go", "rust", "java",
                        "c", "cpp", "csharp", "ruby", "php", "swift",
                        "kotlin", "typescript", "shell"]

    # Optional string fields
    for key in ("fix_hint", "test_hint", "cwe", "owasp"):
        if key in raw:
            rule[key] = str(raw[key])

    # Optional taint config — pass through as-is
    if "taint" in raw and isinstance(raw["taint"], dict):
        rule["taint"] = raw["taint"]

    return rule


def load_yaml_rules(rules_dir: str | Path) -> list[dict]:
    """Load all .yaml/.yml files from *rules_dir*, validate, return rule dicts.

    Rules that fail validation are logged as warnings and skipped.
    If PyYAML is not installed the function returns an empty list with a
    warning.
    """
    rules_dir = Path(rules_dir)
    if not rules_dir.is_dir():
        logger.debug("YAML rules directory does not exist: %s", rules_dir)
        return []

    if yaml is None:
        _warn(
            f"PyYAML is not installed — cannot load custom YAML rules from {rules_dir}. "
            "Install with: pip install pyyaml"
        )
        return []

    loaded: list[dict] = []
    seen_ids: set[str] = set()

    for path in sorted(rules_dir.iterdir()):
        if path.suffix.lower() not in (".yaml", ".yml"):
            continue

        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            _warn(f"Skipping {path.name}: YAML parse error: {exc}")
            continue
        except OSError as exc:
            _warn(f"Skipping {path.name}: {exc}")
            continue

        if not isinstance(data, dict) or "rules" not in data:
            _warn(f"Skipping {path.name}: expected a top-level 'rules' key")
            continue

        raw_rules = data["rules"]
        if not isinstance(raw_rules, list):
            _warn(f"Skipping {path.name}: 'rules' must be a list")
            continue

        for entry in raw_rules:
            if not isinstance(entry, dict):
                _warn(f"Skipping non-dict entry in {path.name}")
                continue

            error = _validate_rule(entry, path.name)
            if error:
                _warn(f"Skipping invalid rule: {error}")
                continue

            rule = _normalise_rule(entry)

            if rule["id"] in seen_ids:
                _warn(f"Duplicate rule id '{rule['id']}' in {path.name} — skipping")
                continue

            seen_ids.add(rule["id"])
            loaded.append(rule)

    if loaded:
        logger.info(
            "Loaded %d custom YAML rule(s) from %s", len(loaded), rules_dir
        )

    return loaded
