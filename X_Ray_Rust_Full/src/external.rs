// src/external.rs — Unified external tool integration (lint + security)
//
// ZERO DUPLICATION: lint (ruff) and security (bandit) share the same
// analyze → subprocess → parse → to_smell_issue → summary pipeline.
// This is the optimized version that X-Ray's own scan identified as
// duplicate (Groups 20-24).

use crate::config;
use crate::types::{Severity, SmellIssue};
use std::collections::HashMap;
use std::path::Path;
use std::process::Command;

// ── Tool Enum ──────────────────────────────────────────────────────

#[derive(Debug, Clone, Copy)]
pub enum Tool {
    Ruff,
    Bandit,
}

impl Tool {
    fn name(&self) -> &'static str {
        match self { Tool::Ruff => "ruff", Tool::Bandit => "bandit" }
    }

    fn binary(&self) -> &'static str {
        match self { Tool::Ruff => "ruff", Tool::Bandit => "bandit" }
    }

    fn source(&self) -> &'static str {
        match self { Tool::Ruff => "ruff", Tool::Bandit => "bandit" }
    }
}

// ── Unified Analysis ───────────────────────────────────────────────

/// Check if an external tool is available on PATH
pub fn is_available(tool: Tool) -> bool {
    which(tool.binary())
}

/// Run analysis with an external tool, returning SmellIssues
pub fn analyze(tool: Tool, root: &Path, exclude: &[String]) -> Vec<SmellIssue> {
    if !is_available(tool) {
        return vec![];
    }

    let output = match run_subprocess(tool, root, exclude) {
        Some(o) => o,
        None => return vec![],
    };

    parse_results(tool, &output, root)
}

/// Summary counts for a set of issues
pub fn summary(issues: &[SmellIssue]) -> HashMap<String, usize> {
    let mut m = HashMap::new();
    m.insert("total".to_string(), issues.len());
    m.insert("critical".to_string(), issues.iter().filter(|i| i.severity == Severity::Critical).count());
    m.insert("warning".to_string(), issues.iter().filter(|i| i.severity == Severity::Warning).count());
    m.insert("info".to_string(), issues.iter().filter(|i| i.severity == Severity::Info).count());
    m.insert("fixable".to_string(), issues.iter().filter(|i| i.fixable).count());
    m
}

// ── Internal: Subprocess ───────────────────────────────────────────

fn which(name: &str) -> bool {
    Command::new("where")
        .arg(name)
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

fn run_subprocess(tool: Tool, root: &Path, exclude: &[String]) -> Option<String> {
    let mut cmd = Command::new(tool.binary());

    match tool {
        Tool::Ruff => {
            cmd.arg("check")
                .arg(root)
                .arg("--output-format=json")
                .arg("--no-fix");
            if !exclude.is_empty() {
                cmd.arg("--exclude").arg(exclude.join(","));
            }
        }
        Tool::Bandit => {
            cmd.arg("-r")
                .arg(root)
                .arg("-f").arg("json")
                .arg("-ll"); // medium+ severity
            if !exclude.is_empty() {
                cmd.arg("--exclude").arg(exclude.join(","));
            }
        }
    }

    match cmd.output() {
        Ok(output) => {
            let stdout = String::from_utf8_lossy(&output.stdout).to_string();
            if stdout.trim().is_empty() { None } else { Some(stdout) }
        }
        Err(_) => None,
    }
}

// ── Internal: Parse Results ────────────────────────────────────────

fn parse_results(tool: Tool, output: &str, root: &Path) -> Vec<SmellIssue> {
    // Strip any non-JSON prefix (bandit prints progress bars)
    let json_start = output.find('[').or_else(|| output.find('{'));
    let json_str = match json_start {
        Some(pos) => &output[pos..],
        None => return vec![],
    };

    match tool {
        Tool::Ruff => parse_ruff(json_str, root),
        Tool::Bandit => parse_bandit(json_str, root),
    }
}

fn parse_ruff(json_str: &str, root: &Path) -> Vec<SmellIssue> {
    let items: Vec<serde_json::Value> = match serde_json::from_str(json_str) {
        Ok(v) => v,
        Err(_) => return vec![],
    };

    let severity_map = config::ruff_severity_map();
    let root_str = root.to_string_lossy();

    items
        .iter()
        .filter_map(|item| {
            let code = item.get("code")?.as_str().unwrap_or("");
            let msg = item.get("message")?.as_str().unwrap_or("");
            let filename = item.get("filename")?.as_str().unwrap_or("");
            let line = item.get("location")
                .and_then(|l| l.get("row"))
                .and_then(|r| r.as_u64())
                .unwrap_or(0) as u32;
            let end_line = item.get("end_location")
                .and_then(|l| l.get("row"))
                .and_then(|r| r.as_u64())
                .unwrap_or(line as u64) as u32;

            // Determine severity
            let sev_str = severity_map.get(code).copied()
                .unwrap_or_else(|| {
                    if code.starts_with('F') { "warning" }
                    else if code.starts_with('E') || code.starts_with('W') { "info" }
                    else { "info" }
                });
            let severity = match sev_str {
                "critical" => Severity::Critical,
                "warning" => Severity::Warning,
                _ => Severity::Info,
            };

            // Make path relative
            let rel_path = filename.strip_prefix(&*root_str)
                .unwrap_or(filename)
                .trim_start_matches(['/', '\\'])
                .replace('\\', "/");

            let fixable = item.get("fix")
                .and_then(|f| f.get("applicability"))
                .and_then(|a| a.as_str())
                .map(|a| a != "Unsafe")
                .unwrap_or(false);

            Some(SmellIssue {
                file_path: rel_path,
                line,
                end_line,
                category: ruff_category(code),
                severity,
                message: format!("[{}] {}", code, msg),
                suggestion: ruff_suggestion(code),
                name: String::new(),
                metric_value: 0,
                source: "ruff".to_string(),
                rule_code: code.to_string(),
                fixable,
                confidence: String::new(),
            })
        })
        .collect()
}

fn parse_bandit(json_str: &str, root: &Path) -> Vec<SmellIssue> {
    let parsed: serde_json::Value = match serde_json::from_str(json_str) {
        Ok(v) => v,
        Err(_) => return vec![],
    };

    let results = match parsed.get("results").and_then(|r| r.as_array()) {
        Some(arr) => arr,
        None => return vec![],
    };

    let root_str = root.to_string_lossy();

    results
        .iter()
        .filter_map(|item| {
            let test_id = item.get("test_id")?.as_str().unwrap_or("");
            let test_name = item.get("test_name")?.as_str().unwrap_or("");
            let sev = item.get("issue_severity")?.as_str().unwrap_or("LOW");
            let confidence = item.get("issue_confidence")?.as_str().unwrap_or("LOW");
            let msg = item.get("issue_text")?.as_str().unwrap_or("");
            let filename = item.get("filename")?.as_str().unwrap_or("");
            let line = item.get("line_number")?.as_u64().unwrap_or(0) as u32;
            let end_line = item.get("end_col_offset") // bandit doesn't always have end_line
                .and_then(|e| e.as_u64())
                .unwrap_or(line as u64) as u32;

            // Skip B101 in test files, always skip B404
            if test_id == "B404" { return None; }
            if test_id == "B101" && filename.contains("test") { return None; }

            let severity = match config::bandit_severity(sev) {
                "critical" => Severity::Critical,
                "warning" => Severity::Warning,
                _ => Severity::Info,
            };

            let rel_path = filename.strip_prefix(&*root_str)
                .unwrap_or(filename)
                .trim_start_matches(['/', '\\'])
                .replace('\\', "/");

            Some(SmellIssue {
                file_path: rel_path,
                line,
                end_line,
                category: bandit_category(test_id),
                severity,
                message: format!("[{}] {}: {}", test_id, test_name, msg),
                suggestion: bandit_suggestion(test_id),
                name: String::new(),
                metric_value: 0,
                source: "bandit".to_string(),
                rule_code: test_id.to_string(),
                fixable: false,
                confidence: confidence.to_string(),
            })
        })
        .collect()
}

// ── Category & Suggestion Mappings ─────────────────────────────────

fn ruff_category(code: &str) -> String {
    match code {
        "F401" => "unused-import".to_string(),
        "F811" => "redefined-unused".to_string(),
        "F821" => "undefined-name".to_string(),
        "F841" => "unused-variable".to_string(),
        "E501" => "line-too-long".to_string(),
        "E711" | "E712" => "comparison-style".to_string(),
        "E722" => "bare-except".to_string(),
        "E741" => "ambiguous-name".to_string(),
        "E402" => "import-order".to_string(),
        _ => "lint".to_string(),
    }
}

fn ruff_suggestion(code: &str) -> String {
    match code {
        "F401" => "Remove the unused import.".to_string(),
        "F811" => "Remove the duplicate definition.".to_string(),
        "F821" => "Fix the undefined name reference.".to_string(),
        "F841" => "Remove or use the assigned variable.".to_string(),
        "E501" => "Break the line or disable this rule.".to_string(),
        "E722" => "Use specific exception types instead of bare except.".to_string(),
        _ => "See ruff documentation for this rule.".to_string(),
    }
}

fn bandit_category(test_id: &str) -> String {
    match test_id {
        "B101" => "assert-used".to_string(),
        "B102" => "exec-used".to_string(),
        "B301" | "B302" => "pickle".to_string(),
        "B501" | "B502" | "B503" => "ssl-insecure".to_string(),
        "B601" | "B602" | "B603" | "B604" | "B605" | "B607" => "shell-injection".to_string(),
        "B608" => "sql-injection".to_string(),
        "B701" | "B702" | "B703" => "template-injection".to_string(),
        _ => "security".to_string(),
    }
}

fn bandit_suggestion(test_id: &str) -> String {
    match test_id {
        "B101" => "Remove assert from production code; use proper validation.".to_string(),
        "B102" => "Replace exec() with safer alternatives.".to_string(),
        "B301" | "B302" => "Use json/msgpack instead of pickle for untrusted data.".to_string(),
        "B601" | "B602" => "Avoid shell=True; use subprocess with argument list.".to_string(),
        "B603" => "Validate inputs before passing to subprocess.".to_string(),
        "B608" => "Use parameterized queries instead of string formatting.".to_string(),
        _ => "Consult bandit documentation for remediation.".to_string(),
    }
}
