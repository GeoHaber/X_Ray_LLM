//! Typed structures for X-Ray API and analyzer responses.
//! Rust port of xray/types.py.

use serde::{Deserialize, Serialize};

// ── Browse / File browser ──────────────────────────────────────────────

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct FileItem {
    pub name: String,
    pub path: String,
    pub is_dir: bool,
    pub size: Option<u64>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct BrowseResult {
    pub current: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub parent: Option<String>,
    #[serde(default)]
    pub items: Vec<FileItem>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct DriveInfo {
    pub name: String,
    pub path: String,
    pub is_dir: bool,
}

// ── Scanner findings ───────────────────────────────────────────────────

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct FindingDict {
    pub rule_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub rule_name: Option<String>,
    pub severity: String,
    pub file: String,
    pub line: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub message: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub suggestion: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub category: Option<String>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct ScanSummary {
    pub total: usize,
    pub high: usize,
    pub medium: usize,
    pub low: usize,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct ApiScanResult {
    pub files_scanned: usize,
    pub findings: Vec<FindingDict>,
    pub summary: ScanSummary,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub grade: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub elapsed_ms: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

// ── Format / Type checking ─────────────────────────────────────────────

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct FormatResult {
    pub needs_format: usize,
    pub files: Vec<String>,
    pub all_formatted: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct TypeDiagnostic {
    pub file: String,
    pub location: String,
    pub message: String,
    pub severity: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct TypeCheckResult {
    pub total_diagnostics: usize,
    pub errors: usize,
    pub warnings: usize,
    pub diagnostics: Vec<TypeDiagnostic>,
    pub clean: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

// ── Project health ─────────────────────────────────────────────────────

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct HealthCheck {
    pub name: String,
    pub status: String,
    pub file: String,
    pub description: String,
    pub severity: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct HealthResult {
    pub score: usize,
    pub passed: usize,
    pub total: usize,
    pub checks: Vec<HealthCheck>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct RemediationEstimate {
    pub total_minutes: usize,
    pub total_hours: f64,
    pub per_finding: Vec<String>,
}

// ── Code smells ────────────────────────────────────────────────────────

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct SmellItem {
    pub file: String,
    pub line: usize,
    pub severity: String,
    pub smell: String,
    pub description: String,
    pub metric: f64,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct SmellResult {
    pub smells: Vec<SmellItem>,
    pub total: usize,
    pub by_type: std::collections::HashMap<String, usize>,
}

// ── Dead functions ─────────────────────────────────────────────────────

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct DeadFunction {
    pub name: String,
    pub file: String,
    pub line: usize,
    pub lines: usize,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct DeadFunctionResult {
    pub dead_functions: Vec<DeadFunction>,
    pub total_defined: usize,
    pub total_dead: usize,
    pub total_called: usize,
}

// ── Security (Bandit-style) ────────────────────────────────────────────

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct SecurityIssue {
    pub file: String,
    pub line: usize,
    pub severity: String,
    pub confidence: String,
    pub issue: String,
    pub cwe: Option<String>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct SecurityResult {
    pub issues: Vec<SecurityIssue>,
    pub total: usize,
    pub by_severity: std::collections::HashMap<String, usize>,
}

// ── Duplicate detection ────────────────────────────────────────────────

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct DuplicateBlock {
    pub file_a: String,
    pub line_a: usize,
    pub file_b: String,
    pub line_b: usize,
    pub lines: usize,
    pub similarity: f64,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct DuplicateResult {
    pub duplicates: Vec<DuplicateBlock>,
    pub total_blocks: usize,
    pub total_duplicate_lines: usize,
}

// ── PM Dashboard ───────────────────────────────────────────────────────

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct RiskHeatmapEntry {
    pub file: String,
    pub risk_score: f64,
    pub findings: usize,
    pub complexity: f64,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct ModuleCard {
    pub name: String,
    pub files: usize,
    pub lines: usize,
    pub findings: usize,
    pub health_score: usize,
}
