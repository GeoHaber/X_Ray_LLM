// src/types.rs — Core data structures
use serde::{Deserialize, Serialize};

/// Severity levels for issues
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Severity {
    Critical,
    Warning,
    Info,
}

impl Severity {
    pub fn as_str(&self) -> &'static str {
        match self {
            Severity::Critical => "critical",
            Severity::Warning => "warning",
            Severity::Info => "info",
        }
    }
    pub fn icon(&self) -> &'static str {
        match self {
            Severity::Critical => "\u{1f534}",
            Severity::Warning => "\u{1f7e1}",
            Severity::Info => "\u{1f535}",
        }
    }
}

impl std::fmt::Display for Severity {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}

/// A single extracted function from the Python codebase
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FunctionRecord {
    pub name: String,
    pub file_path: String,
    pub line_start: u32,
    pub line_end: u32,
    pub size_lines: u32,
    pub parameters: Vec<String>,
    pub return_type: Option<String>,
    pub decorators: Vec<String>,
    pub docstring: Option<String>,
    pub calls_to: Vec<String>,
    pub complexity: u32,
    pub nesting_depth: u32,
    pub code_hash: String,
    pub structure_hash: String,
    pub code: String,
    pub return_count: u32,
    pub branch_count: u32,
    pub is_async: bool,
}

impl FunctionRecord {
    pub fn key(&self) -> String {
        let stem = std::path::Path::new(&self.file_path)
            .file_stem()
            .map(|s| s.to_string_lossy().to_string())
            .unwrap_or_default();
        format!("{}::{}", stem, self.name)
    }

    pub fn location(&self) -> String {
        format!("{}:{}", self.file_path, self.line_start)
    }
}

/// A single extracted class
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ClassRecord {
    pub name: String,
    pub file_path: String,
    pub line_start: u32,
    pub line_end: u32,
    pub size_lines: u32,
    pub method_count: u32,
    pub base_classes: Vec<String>,
    pub docstring: Option<String>,
    pub methods: Vec<String>,
    pub has_init: bool,
}

/// A code quality issue (smell, lint, or security finding)
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SmellIssue {
    pub file_path: String,
    pub line: u32,
    pub end_line: u32,
    pub category: String,
    pub severity: Severity,
    pub message: String,
    pub suggestion: String,
    pub name: String,
    pub metric_value: u32,
    pub source: String,
    pub rule_code: String,
    pub fixable: bool,
    pub confidence: String,
}

/// A group of duplicate/similar functions
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DuplicateGroup {
    pub group_id: u32,
    pub similarity_type: String,
    pub avg_similarity: f64,
    pub functions: Vec<serde_json::Value>,
    pub merge_suggestion: String,
}

/// Full scan results
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ScanResults {
    pub functions: Vec<FunctionRecord>,
    pub classes: Vec<ClassRecord>,
    pub errors: Vec<String>,
    pub smells: Vec<SmellIssue>,
    pub duplicates: Vec<DuplicateGroup>,
    pub lint_issues: Vec<SmellIssue>,
    pub security_issues: Vec<SmellIssue>,
}

impl ScanResults {
    pub fn new() -> Self {
        Self {
            functions: vec![],
            classes: vec![],
            errors: vec![],
            smells: vec![],
            duplicates: vec![],
            lint_issues: vec![],
            security_issues: vec![],
        }
    }

    /// Total issue count
    pub fn total_issues(&self) -> usize {
        self.smells.len() + self.duplicates.len() + self.lint_issues.len() + self.security_issues.len()
    }

    /// Compute unified grade A-F
    pub fn grade(&self) -> &'static str {
        let n = self.total_issues();
        let funcs = self.functions.len().max(1);
        let ratio = n as f64 / funcs as f64;
        if ratio < 0.05 { "A" }
        else if ratio < 0.15 { "B" }
        else if ratio < 0.30 { "C" }
        else if ratio < 0.50 { "D" }
        else { "F" }
    }
}
