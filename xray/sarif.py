"""
X-Ray SARIF — Static Analysis Results Interchange Format (v2.1.0) output.

Generates SARIF JSON compatible with:
  - GitHub Code Scanning (upload via actions/upload-sarif)
  - VS Code SARIF Viewer extension
  - Azure DevOps Advanced Security
"""

import json
from datetime import datetime, timezone

_SARIF_VERSION = "2.1.0"
_SARIF_SCHEMA = "https://docs.oasis-open.org/sarif/sarif/v2.1.0/errata01/os/schemas/sarif-schema-2.1.0.json"

_SEVERITY_MAP = {
    "HIGH": "error",
    "MEDIUM": "warning",
    "LOW": "note",
}


def _rule_category(rule_id: str) -> str:
    """Map rule ID prefix to SARIF tag category."""
    prefix = rule_id.split("-")[0] if "-" in rule_id else rule_id
    return {
        "SEC": "security",
        "QUAL": "maintainability",
        "PY": "correctness",
        "PORT": "portability",
    }.get(prefix, "general")


def findings_to_sarif(
    findings: list[dict],
    *,
    tool_name: str = "xray-llm",
    tool_version: str = "0.3.0",
) -> dict:
    """Convert X-Ray findings to SARIF 2.1.0 format.

    Args:
        findings: List of finding dicts (from Finding.to_dict())
        tool_name: Name of the tool in SARIF output
        tool_version: Version string

    Returns:
        SARIF 2.1.0 compliant dict
    """
    seen_rules: dict[str, int] = {}
    sarif_rules: list[dict] = []
    results: list[dict] = []

    for finding in findings:
        rule_id = finding.get("rule_id", "UNKNOWN")

        # Register rule if not seen
        if rule_id not in seen_rules:
            seen_rules[rule_id] = len(sarif_rules)
            rule_entry: dict = {
                "id": rule_id,
                "shortDescription": {"text": finding.get("description", rule_id)},
                "properties": {
                    "tags": [_rule_category(rule_id)],
                },
            }
            if finding.get("fix_hint"):
                rule_entry["help"] = {"text": finding["fix_hint"]}
            sarif_rules.append(rule_entry)

        # Build result
        severity = _SEVERITY_MAP.get(finding.get("severity", ""), "warning")
        filepath = finding.get("file", "").replace("\\", "/")
        line = max(finding.get("line", 1), 1)
        col = max(finding.get("col", 1), 1)

        result: dict = {
            "ruleId": rule_id,
            "ruleIndex": seen_rules[rule_id],
            "level": severity,
            "message": {"text": finding.get("description", "")},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": filepath, "uriBaseId": "%SRCROOT%"},
                        "region": {
                            "startLine": line,
                            "startColumn": col,
                        },
                    }
                }
            ],
        }

        if finding.get("fix_hint"):
            result["fixes"] = [
                {
                    "description": {"text": finding["fix_hint"]},
                }
            ]

        results.append(result)

    sarif = {
        "$schema": _SARIF_SCHEMA,
        "version": _SARIF_VERSION,
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": tool_name,
                        "version": tool_version,
                        "rules": sarif_rules,
                    }
                },
                "results": results,
                "invocations": [
                    {
                        "executionSuccessful": True,
                        "endTimeUtc": datetime.now(timezone.utc).isoformat(),
                    }
                ],
            }
        ],
    }

    return sarif


def write_sarif(findings: list[dict], output_path: str, **kwargs) -> None:
    """Write SARIF output to a file."""
    sarif = findings_to_sarif(findings, **kwargs)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(sarif, f, indent=2)


def sarif_to_json_string(findings: list[dict], **kwargs) -> str:
    """Return SARIF as a JSON string."""
    sarif = findings_to_sarif(findings, **kwargs)
    return json.dumps(sarif, indent=2)
