//! X-Ray Scanner — High-performance Rust code analysis engine.
//!
//! Scans source files against pattern rules and outputs JSON findings.
//! ~100x faster than the Python scanner for large codebases.

pub mod rules;

use regex::Regex;
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use walkdir::WalkDir;

/// A single finding from the scanner.
#[derive(Debug, Serialize, Deserialize)]
pub struct Finding {
    pub rule_id: String,
    pub severity: String,
    pub file: String,
    pub line: usize,
    pub col: usize,
    pub matched_text: String,
    pub description: String,
    pub fix_hint: String,
    pub test_hint: String,
}

/// A scanning rule.
#[derive(Debug, Clone)]
pub struct Rule {
    pub id: String,
    pub severity: String,
    pub langs: Vec<String>,
    pub pattern: Regex,
    pub description: String,
    pub fix_hint: String,
    pub test_hint: String,
}

/// Aggregated scan results.
#[derive(Debug, Serialize, Deserialize)]
pub struct ScanResult {
    pub findings: Vec<Finding>,
    pub files_scanned: usize,
    pub rules_checked: usize,
}

/// Detect language from file extension.
fn detect_lang(path: &Path) -> Option<&'static str> {
    match path.extension()?.to_str()? {
        "py" => Some("python"),
        "js" | "jsx" | "ts" | "tsx" => Some("javascript"),
        "html" | "htm" => Some("html"),
        "rs" => Some("rust"),
        _ => None,
    }
}

/// Check if a directory should be skipped.
fn should_skip(name: &str) -> bool {
    matches!(
        name,
        "__pycache__"
            | "node_modules"
            | ".git"
            | ".venv"
            | "venv"
            | "target"
            | "dist"
            | "build"
    ) || name.starts_with('.')
}

/// Scan a single file against the given rules.
pub fn scan_file(path: &Path, rules: &[Rule]) -> Vec<Finding> {
    let lang = match detect_lang(path) {
        Some(l) => l,
        None => return vec![],
    };

    let applicable: Vec<&Rule> = rules
        .iter()
        .filter(|r| r.langs.iter().any(|l| l == lang))
        .collect();

    if applicable.is_empty() {
        return vec![];
    }

    let content = match std::fs::read_to_string(path) {
        Ok(c) => c,
        Err(_) => return vec![],
    };

    // Skip very large files (1 MB)
    if content.len() > 1_048_576 {
        return vec![];
    }

    let mut findings = Vec::new();
    let file_str = path.to_string_lossy().to_string();

    for rule in &applicable {
        for mat in rule.pattern.find_iter(&content) {
            let line = content[..mat.start()].matches('\n').count() + 1;
            let line_start = content[..mat.start()].rfind('\n').map_or(0, |i| i + 1);
            let col = mat.start() - line_start + 1;

            let matched = mat.as_str();
            let truncated = if matched.len() > 200 {
                &matched[..200]
            } else {
                matched
            };

            findings.push(Finding {
                rule_id: rule.id.clone(),
                severity: rule.severity.clone(),
                file: file_str.clone(),
                line,
                col,
                matched_text: truncated.to_string(),
                description: rule.description.clone(),
                fix_hint: rule.fix_hint.clone(),
                test_hint: rule.test_hint.clone(),
            });
        }
    }

    findings
}

/// Scan an entire directory tree.
pub fn scan_directory(root: &Path, rules: &[Rule]) -> ScanResult {
    let mut result = ScanResult {
        findings: Vec::new(),
        files_scanned: 0,
        rules_checked: rules.len(),
    };

    for entry in WalkDir::new(root)
        .into_iter()
        .filter_entry(|e| {
            if e.file_type().is_dir() {
                !should_skip(e.file_name().to_str().unwrap_or(""))
            } else {
                true
            }
        })
        .filter_map(|e| e.ok())
    {
        if !entry.file_type().is_file() {
            continue;
        }

        let path = entry.path();
        if detect_lang(path).is_none() {
            continue;
        }

        result.files_scanned += 1;
        let file_findings = scan_file(path, rules);
        result.findings.extend(file_findings);
    }

    result
}
