//! X-Ray SARIF — Static Analysis Results Interchange Format (v2.1.0) output.
//! Rust port of xray/sarif.py.
//!
//! Generates SARIF JSON compatible with:
//!   - GitHub Code Scanning (upload via actions/upload-sarif)
//!   - VS Code SARIF Viewer extension
//!   - Azure DevOps Advanced Security

use chrono::Utc;
use serde_json::{json, Value};
use std::collections::HashMap;

const SARIF_VERSION: &str = "2.1.0";
const SARIF_SCHEMA: &str =
    "https://docs.oasis-open.org/sarif/sarif/v2.1.0/errata01/os/schemas/sarif-schema-2.1.0.json";

/// Map severity to SARIF level.
fn severity_to_level(severity: &str) -> &'static str {
    match severity {
        "HIGH" => "error",
        "MEDIUM" => "warning",
        "LOW" => "note",
        _ => "warning",
    }
}

/// Map rule ID prefix to SARIF tag category.
fn rule_category(rule_id: &str) -> &'static str {
    let prefix = rule_id.split('-').next().unwrap_or(rule_id);
    match prefix {
        "SEC" => "security",
        "QUAL" => "maintainability",
        "PY" => "correctness",
        "PORT" => "portability",
        _ => "general",
    }
}

/// Convert X-Ray findings to SARIF 2.1.0 format.
pub fn findings_to_sarif(
    findings: &[Value],
    tool_name: &str,
    tool_version: &str,
) -> Value {
    let mut seen_rules: HashMap<String, usize> = HashMap::new();
    let mut sarif_rules: Vec<Value> = Vec::new();
    let mut results: Vec<Value> = Vec::new();

    for finding in findings {
        let rule_id = finding.get("rule_id").and_then(|v| v.as_str()).unwrap_or("UNKNOWN");

        // Register rule if not seen
        if !seen_rules.contains_key(rule_id) {
            let idx = sarif_rules.len();
            seen_rules.insert(rule_id.to_string(), idx);

            let description = finding.get("description").and_then(|v| v.as_str()).unwrap_or(rule_id);
            let mut rule_entry = json!({
                "id": rule_id,
                "shortDescription": { "text": description },
                "properties": {
                    "tags": [rule_category(rule_id)],
                },
            });

            if let Some(fix_hint) = finding.get("fix_hint").and_then(|v| v.as_str()) {
                if !fix_hint.is_empty() {
                    rule_entry["help"] = json!({ "text": fix_hint });
                }
            }

            sarif_rules.push(rule_entry);
        }

        let level = severity_to_level(
            finding.get("severity").and_then(|v| v.as_str()).unwrap_or("MEDIUM"),
        );

        let filepath = finding
            .get("file")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .replace('\\', "/");

        let line = finding.get("line").and_then(|v| v.as_u64()).unwrap_or(1).max(1);
        let col = finding.get("col").and_then(|v| v.as_u64()).unwrap_or(1).max(1);

        let description = finding.get("description").and_then(|v| v.as_str()).unwrap_or("");

        let mut result = json!({
            "ruleId": rule_id,
            "ruleIndex": seen_rules[rule_id],
            "level": level,
            "message": { "text": description },
            "locations": [{
                "physicalLocation": {
                    "artifactLocation": {
                        "uri": filepath,
                        "uriBaseId": "%SRCROOT%",
                    },
                    "region": {
                        "startLine": line,
                        "startColumn": col,
                    },
                }
            }],
        });

        if let Some(fix_hint) = finding.get("fix_hint").and_then(|v| v.as_str()) {
            if !fix_hint.is_empty() {
                result["fixes"] = json!([{
                    "description": { "text": fix_hint },
                }]);
            }
        }

        results.push(result);
    }

    json!({
        "$schema": SARIF_SCHEMA,
        "version": SARIF_VERSION,
        "runs": [{
            "tool": {
                "driver": {
                    "name": tool_name,
                    "version": tool_version,
                    "rules": sarif_rules,
                }
            },
            "results": results,
            "invocations": [{
                "executionSuccessful": true,
                "endTimeUtc": Utc::now().to_rfc3339(),
            }],
        }],
    })
}

/// Write SARIF output to a file.
pub fn write_sarif(findings: &[Value], output_path: &str) -> Result<(), String> {
    let sarif = findings_to_sarif(findings, "xray-llm", "1.0.0");
    let json_str = serde_json::to_string_pretty(&sarif)
        .map_err(|e| format!("JSON serialization failed: {e}"))?;
    std::fs::write(output_path, json_str)
        .map_err(|e| format!("Failed to write SARIF: {e}"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_severity_to_level() {
        assert_eq!(severity_to_level("HIGH"), "error");
        assert_eq!(severity_to_level("MEDIUM"), "warning");
        assert_eq!(severity_to_level("LOW"), "note");
    }

    #[test]
    fn test_rule_category() {
        assert_eq!(rule_category("SEC-001"), "security");
        assert_eq!(rule_category("QUAL-003"), "maintainability");
        assert_eq!(rule_category("PY-005"), "correctness");
        assert_eq!(rule_category("PORT-001"), "portability");
    }

    #[test]
    fn test_findings_to_sarif_structure() {
        let findings = vec![json!({
            "rule_id": "SEC-001",
            "severity": "HIGH",
            "file": "test.py",
            "line": 5,
            "col": 1,
            "description": "Hardcoded secret",
            "fix_hint": "Use env vars",
            "matched_text": "password = 'abc'",
        })];
        let sarif = findings_to_sarif(&findings, "xray-llm", "1.0.0");
        assert_eq!(sarif["version"], "2.1.0");
        assert_eq!(sarif["runs"][0]["results"][0]["ruleId"], "SEC-001");
        assert_eq!(sarif["runs"][0]["results"][0]["level"], "error");
    }
}
