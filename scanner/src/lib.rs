//! X-Ray Scanner — Full Rust implementation of the X-Ray LLM code analysis tool.
//!
//! This crate provides:
//! - Pattern-based code scanning with 42 rules
//! - String/comment-aware scanning to reduce false positives
//! - Incremental scanning with file-hash cache
//! - SARIF 2.1.0 output generation
//! - Deterministic auto-fixers for 7 rule types
//! - Configuration from pyproject.toml
//! - HTTP server with REST API and UI serving
//! - Code analyzers (smells, health, connections, security)

pub mod rules;
pub mod config;
pub mod constants;
pub mod fixer;
pub mod sarif;
pub mod server;
pub mod analyzers;
pub mod types;
pub mod ast_analysis;

#[cfg(feature = "python")]
pub mod pybridge;

use fancy_regex::Regex;
use serde::{Deserialize, Serialize};
use sha2::{Sha256, Digest};
use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::Path;
use walkdir::WalkDir;

// Re-export key types
pub use config::XRayConfig;
pub use fixer::{FixResult, preview_fix, apply_fix, FIXABLE_RULES};
pub use sarif::findings_to_sarif;

/// Maximum file size to scan (1 MB) — matches Python scanner.
const MAX_FILE_SIZE: u64 = 1_048_576;

/// A single finding from the scanner.
#[derive(Debug, Serialize, Deserialize, Clone)]
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
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub cwe: String,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub owasp: String,
    #[serde(default)]
    pub confidence: f64,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub signal_path: String,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub why_flagged: String,
}

impl std::fmt::Display for Finding {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "[{}] {}: {}:{} — {}",
            self.severity, self.rule_id, self.file, self.line, self.description
        )
    }
}

/// A scanning rule with a compiled regex.
#[derive(Debug, Clone)]
pub struct Rule {
    pub id: String,
    pub severity: String,
    pub langs: Vec<String>,
    pub pattern: Regex,
    pub description: String,
    pub fix_hint: String,
    pub test_hint: String,
    pub cwe: String,
    pub owasp: String,
}

/// Aggregated scan results.
#[derive(Debug, Serialize, Deserialize)]
pub struct ScanResult {
    pub findings: Vec<Finding>,
    pub files_scanned: usize,
    pub rules_checked: usize,
    #[serde(default)]
    pub errors: Vec<String>,
    #[serde(default)]
    pub cached_files: usize,
}

impl ScanResult {
    pub fn high_count(&self) -> usize {
        self.findings.iter().filter(|f| f.severity == "HIGH").count()
    }
    pub fn medium_count(&self) -> usize {
        self.findings.iter().filter(|f| f.severity == "MEDIUM").count()
    }
    pub fn low_count(&self) -> usize {
        self.findings.iter().filter(|f| f.severity == "LOW").count()
    }
    pub fn summary(&self) -> String {
        format!(
            "Scanned {} files against {} rules\nFindings: {} total ({} HIGH, {} MEDIUM, {} LOW)",
            self.files_scanned,
            self.rules_checked,
            self.findings.len(),
            self.high_count(),
            self.medium_count(),
            self.low_count(),
        )
    }
    pub fn grade(&self) -> &'static str {
        let scanned = self.files_scanned.max(1);
        // Weighted score: HIGH=10, MEDIUM=3, LOW=1
        let penalty: usize = self.findings.iter().map(|f| match f.severity.as_str() {
            "HIGH" => 10,
            "MEDIUM" => 3,
            _ => 1,
        }).sum();
        let score = 100usize.saturating_sub(penalty * 100 / (scanned * 10).max(1));
        match score {
            90..=100 => "A",
            70..=89 => "B",
            50..=69 => "C",
            30..=49 => "D",
            _ => "F",
        }
    }
}

// ── File extension → language mapping ──────────────────────────────────

/// Detect language from file extension — matches Python `_EXT_LANG`.
fn detect_lang(path: &Path) -> Option<&'static str> {
    match path.extension()?.to_str()? {
        "py" => Some("python"),
        "js" | "jsx" | "ts" | "tsx" => Some("javascript"),
        "html" | "htm" => Some("html"),
        "rs" => Some("rust"),
        _ => None,
    }
}

/// Check if a directory name should be skipped.
fn should_skip(name: &str) -> bool {
    constants::SKIP_DIRS.contains(&name) || name.starts_with('.')
}

// ── String/comment region detection (Python-specific) ──────────────────

/// Build ranges of non-code regions (strings and comments) in Python source.
/// Returns sorted Vec of (start, end) byte offsets.
fn build_non_code_ranges(content: &str, strings_only: bool) -> Vec<(usize, usize)> {
    let pattern = if strings_only {
        // Only string literals
        r#""""[\s\S]*?"""|'''[\s\S]*?'''|"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'"#
    } else {
        // Strings + comments
        r#""""[\s\S]*?"""|'''[\s\S]*?'''|"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|#[^\n]*"#
    };
    let re = match Regex::new(pattern) {
        Ok(r) => r,
        Err(_) => return vec![],
    };
    let mut ranges = Vec::new();
    let mut start = 0;
    while start < content.len() {
        match re.find_from_pos(content, start) {
            Ok(Some(m)) => {
                ranges.push((m.start(), m.end()));
                start = m.end();
            }
            _ => break,
        }
    }
    ranges
}

/// Binary search to check if a byte position falls inside a non-code range.
fn in_non_code(pos: usize, ranges: &[(usize, usize)]) -> bool {
    let mut lo = 0usize;
    let mut hi = ranges.len();
    while lo < hi {
        let mid = (lo + hi) / 2;
        let (start, end) = ranges[mid];
        if pos < start {
            hi = mid;
        } else if pos >= end {
            lo = mid + 1;
        } else {
            return true;
        }
    }
    false
}

// ── String-aware rule suppression ──────────────────────────────────────

/// Rules that should be suppressed when matching inside strings/comments.
/// "all" = suppress in strings AND comments, "strings" = strings only.
fn string_aware_mode(rule_id: &str) -> Option<&'static str> {
    match rule_id {
        "PY-004" | "PY-006" | "PY-007" | "QUAL-010" => Some("all"),
        "QUAL-007" => Some("strings"),
        _ => None,
    }
}

// ── Inline suppression parsing ─────────────────────────────────────────

/// Parse inline `# xray: ignore[RULE-ID, ...]` comments.
/// Returns a map of 1-based line number → set of suppressed rule IDs.
fn parse_suppressions(content: &str) -> HashMap<usize, HashSet<String>> {
    let re = match regex::Regex::new(r"#\s*xray:\s*ignore\[([^\]]+)\]") {
        Ok(r) => r,
        Err(_) => return HashMap::new(),
    };
    let mut result = HashMap::new();
    for (i, line) in content.lines().enumerate() {
        if let Some(caps) = re.captures(line) {
            let ids: HashSet<String> = caps[1]
                .split(',')
                .map(|s| s.trim().to_string())
                .collect();
            result.insert(i + 1, ids);
        }
    }
    result
}

// ── Incremental scan cache ─────────────────────────────────────────────

/// Simple file-hash cache for incremental scanning.
struct ScanCache {
    path: String,
    data: HashMap<String, String>,
}

impl ScanCache {
    fn new(cache_path: Option<&str>) -> Self {
        let path = cache_path.unwrap_or(".xray_cache.json").to_string();
        let data = Self::load_cache(&path);
        ScanCache { path, data }
    }

    fn load_cache(path: &str) -> HashMap<String, String> {
        match fs::read_to_string(path) {
            Ok(content) => serde_json::from_str(&content).unwrap_or_default(),
            Err(_) => HashMap::new(),
        }
    }

    fn save(&self) {
        if let Ok(json) = serde_json::to_string(&self.data) {
            let _ = fs::write(&self.path, json);
        }
    }

    fn is_changed(&mut self, filepath: &str) -> bool {
        let bytes = match fs::read(filepath) {
            Ok(b) => b,
            Err(_) => return true,
        };
        let mut hasher = Sha256::new();
        hasher.update(&bytes);
        let hash = hex::encode(hasher.finalize());
        let old = self.data.get(filepath).cloned();
        self.data.insert(filepath.to_string(), hash.clone());
        old.as_deref() != Some(&hash)
    }
}

// ── Baseline / diff filtering ──────────────────────────────────────────

/// Load a baseline JSON and return a set of (rule_id, file, line) tuples.
pub fn load_baseline(path: &str) -> HashSet<(String, String, usize)> {
    let content = match fs::read_to_string(path) {
        Ok(c) => c,
        Err(_) => return HashSet::new(),
    };
    let data: serde_json::Value = match serde_json::from_str(&content) {
        Ok(v) => v,
        Err(_) => return HashSet::new(),
    };
    let findings = if data.is_array() {
        data.as_array().unwrap()
    } else {
        match data.get("findings").and_then(|f| f.as_array()) {
            Some(arr) => arr,
            None => return HashSet::new(),
        }
    };
    findings
        .iter()
        .map(|item| {
            (
                item.get("rule_id").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                item.get("file").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                item.get("line").and_then(|v| v.as_u64()).unwrap_or(0) as usize,
            )
        })
        .collect()
}

/// Remove findings that already exist in the baseline.
pub fn filter_new_findings(
    findings: Vec<Finding>,
    baseline: &HashSet<(String, String, usize)>,
) -> Vec<Finding> {
    findings
        .into_iter()
        .filter(|f| !baseline.contains(&(f.rule_id.clone(), f.file.clone(), f.line)))
        .collect()
}

// ── Core scanning functions ────────────────────────────────────────────

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

    if let Ok(meta) = fs::metadata(path) {
        if meta.len() > MAX_FILE_SIZE {
            return vec![];
        }
    }

    let bytes = match fs::read(path) {
        Ok(b) => b,
        Err(_) => return vec![],
    };
    let content = String::from_utf8_lossy(&bytes);

    let mut findings = Vec::new();
    let file_str = path.to_string_lossy().to_string();

    // Build non-code ranges for Python files (false-positive reduction)
    let non_code_all = if lang == "python" {
        Some(build_non_code_ranges(&content, false))
    } else {
        None
    };
    let non_code_strings = if lang == "python" {
        Some(build_non_code_ranges(&content, true))
    } else {
        None
    };
    let suppressions = if lang == "python" {
        parse_suppressions(&content)
    } else {
        HashMap::new()
    };

    // Parse AST once per file using rustpython-parser — fail-open: None skips checks
    let py_ast = if lang == "python" {
        ast_analysis::parse_python(&content)
    } else {
        None
    };

    for rule in &applicable {
        // Determine which non-code ranges to use for this rule
        let active_ranges = match string_aware_mode(&rule.id) {
            Some("all") => non_code_all.as_deref(),
            Some("strings") => non_code_strings.as_deref(),
            _ => None,
        };

        let mut start = 0;
        while start < content.len() {
            let slice = &content[start..];
            match rule.pattern.find(slice) {
                Ok(Some(mat)) => {
                    let abs_start = start + mat.start();

                    // Check if match falls in non-code region
                    if let Some(ranges) = active_ranges {
                        if in_non_code(abs_start, ranges) {
                            start = abs_start + mat.end().max(1) - mat.start();
                            continue;
                        }
                    }

                    let line = content[..abs_start].matches('\n').count() + 1;

                    // Inline suppression check
                    if let Some(suppressed) = suppressions.get(&line) {
                        if suppressed.contains(&rule.id) {
                            start = abs_start + mat.end().max(1) - mat.start();
                            continue;
                        }
                    }

                    // AST-based validation: reduce false positives (ruff parser)
                    let mut used_ast = false;
                    if let Some(ref py) = py_ast {
                        if let Some(validator) = ast_analysis::get_validator(&rule.id) {
                            used_ast = true;
                            if !validator(py, &content, line) {
                                // AST says suppress — skip this finding
                                start = abs_start + mat.end().max(1) - mat.start();
                                continue;
                            }
                        }
                    }

                    let line_start = content[..abs_start].rfind('\n').map_or(0, |i| i + 1);
                    let col = abs_start - line_start + 1;

                    let matched = mat.as_str();
                    let truncated = if matched.chars().count() > 200 {
                        let end = matched.char_indices().nth(200).map(|(i, _)| i).unwrap_or(matched.len());
                        &matched[..end]
                    } else {
                        matched
                    };

                    // Confidence: higher when AST confirmed, lower when regex-only
                    let confidence = if used_ast { 0.95 } else { 0.7 };
                    let signal_path = if used_ast {
                        "regex+ast".to_string()
                    } else {
                        "regex".to_string()
                    };
                    let why_flagged = if used_ast {
                        format!("Matched regex pattern and confirmed by AST analysis ({})", rule.id)
                    } else {
                        format!("Matched regex pattern ({})", rule.id)
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
                        cwe: rule.cwe.clone(),
                        owasp: rule.owasp.clone(),
                        confidence,
                        signal_path,
                        why_flagged,
                    });

                    start = abs_start + mat.end().max(1) - mat.start();
                }
                Ok(None) => break,
                Err(_) => break,
            }
        }
    }

    findings
}

/// Scan an entire directory tree.
pub fn scan_directory(root: &Path, rules: &[Rule]) -> ScanResult {
    scan_directory_with_options(root, rules, &[], false, None)
}

/// Scan a directory tree with exclude patterns (convenience wrapper).
pub fn scan_directory_with_excludes<S: AsRef<str>>(
    root: &Path,
    rules: &[Rule],
    excludes: &[S],
) -> ScanResult {
    let patterns: Vec<String> = excludes.iter().map(|s| s.as_ref().to_string()).collect();
    scan_directory_with_options(root, rules, &patterns, false, None)
}

/// Scan a directory tree with options.
pub fn scan_directory_with_options(
    root: &Path,
    rules: &[Rule],
    exclude_patterns: &[String],
    incremental: bool,
    on_progress: Option<&dyn Fn(usize, usize, &str)>,
) -> ScanResult {
    let mut result = ScanResult {
        findings: Vec::new(),
        files_scanned: 0,
        rules_checked: rules.len(),
        errors: Vec::new(),
        cached_files: 0,
    };

    let mut cache = if incremental {
        Some(ScanCache::new(None))
    } else {
        None
    };

    // Compile exclude patterns
    let exclude_res: Vec<regex::Regex> = exclude_patterns
        .iter()
        .filter_map(|pat| match regex::Regex::new(pat) {
            Ok(re) => Some(re),
            Err(e) => {
                result.errors.push(format!("Invalid exclude pattern: {pat}: {e}"));
                None
            }
        })
        .collect();

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

        // Check exclude patterns
        if let Ok(rel) = path.strip_prefix(root) {
            let rel_str = rel.to_string_lossy().replace('\\', "/");
            if exclude_res.iter().any(|re| re.is_match(&rel_str)) {
                continue;
            }
        }

        // Incremental cache check
        let file_str = path.to_string_lossy().to_string();
        if let Some(ref mut c) = cache {
            if !c.is_changed(&file_str) {
                result.cached_files += 1;
                continue;
            }
        }

        result.files_scanned += 1;
        let file_findings = scan_file(path, rules);

        if let Some(cb) = on_progress {
            cb(result.files_scanned, result.findings.len() + file_findings.len(), &file_str);
        }

        result.findings.extend(file_findings);
    }

    // Save cache
    if let Some(c) = cache {
        c.save();
    }

    result
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use std::path::PathBuf;

    fn write_temp(ext: &str, content: &str) -> (tempfile::NamedTempFile, PathBuf) {
        let mut f = tempfile::Builder::new()
            .suffix(ext)
            .tempfile()
            .unwrap();
        f.write_all(content.as_bytes()).unwrap();
        f.flush().unwrap();
        let path = f.path().to_path_buf();
        (f, path)
    }

    #[test]
    fn test_detect_lang() {
        assert_eq!(detect_lang(Path::new("foo.py")), Some("python"));
        assert_eq!(detect_lang(Path::new("bar.js")), Some("javascript"));
        assert_eq!(detect_lang(Path::new("baz.html")), Some("html"));
        assert_eq!(detect_lang(Path::new("qux.rs")), Some("rust"));
        assert_eq!(detect_lang(Path::new("nope.txt")), None);
    }

    #[test]
    fn test_should_skip() {
        assert!(should_skip("__pycache__"));
        assert!(should_skip(".git"));
        assert!(should_skip("node_modules"));
        assert!(!should_skip("src"));
    }

    #[test]
    fn test_in_non_code() {
        let ranges = vec![(5, 10), (20, 30)];
        assert!(!in_non_code(3, &ranges));
        assert!(in_non_code(7, &ranges));
        assert!(!in_non_code(15, &ranges));
        assert!(in_non_code(25, &ranges));
    }

    #[test]
    fn test_parse_suppressions() {
        let content = "x = 1  # xray: ignore[PY-004, PY-005]\ny = 2\n";
        let sup = parse_suppressions(content);
        assert!(sup.get(&1).unwrap().contains("PY-004"));
        assert!(sup.get(&1).unwrap().contains("PY-005"));
        assert!(sup.get(&2).is_none());
    }

    #[test]
    fn test_scan_result_grade() {
        let result = ScanResult {
            findings: vec![],
            files_scanned: 10,
            rules_checked: 42,
            errors: vec![],
            cached_files: 0,
        };
        assert_eq!(result.grade(), "A");
    }

    #[test]
    fn test_scan_file_basic() {
        let rules = rules::get_all_rules();
        let (_tmp, path) = write_temp(".py", "import os\npassword = 'secret123'\n");
        let findings = scan_file(&path, &rules);
        // Should find SEC-008 (hardcoded secret)
        assert!(!findings.is_empty());
        assert!(findings.iter().any(|f| f.rule_id == "SEC-008"));
    }

    #[test]
    fn test_scan_file_detects_eval() {
        let rules = rules::get_all_rules();
        let (_f, path) = write_temp(".py", "result = eval(user_input)\n");
        let findings = scan_file(&path, &rules);
        assert!(findings.iter().any(|f| f.rule_id == "SEC-007"));
    }

    #[test]
    fn test_scan_file_does_not_flag_create_subprocess_exec() {
        let rules = rules::get_all_rules();
        let (_f, path) = write_temp(
            ".py",
            "import asyncio\nproc = asyncio.create_subprocess_exec('python', '-V')\n",
        );
        let findings = scan_file(&path, &rules);
        assert!(
            !findings.iter().any(|f| f.rule_id == "SEC-007"),
            "SEC-007 should not fire for asyncio.create_subprocess_exec()"
        );
    }

    #[test]
    fn test_sec001_xss_template() {
        let rules = rules::get_all_rules();
        let (_f, path) = write_temp(".html", "<script>el.innerHTML = `<b>${name}</b>`;</script>");
        let findings = scan_file(&path, &rules);
        assert!(
            findings.iter().any(|f| f.rule_id == "SEC-001"),
            "Should detect SEC-001 XSS template literal"
        );
    }

    #[test]
    fn test_sec001_safe_sanitized() {
        let rules = rules::get_all_rules();
        let (_f, path) =
            write_temp(".html", "<script>el.innerHTML = `<b>${_escHtml(name)}</b>`;</script>");
        let findings = scan_file(&path, &rules);
        assert!(
            !findings.iter().any(|f| f.rule_id == "SEC-001"),
            "SEC-001 should NOT fire on sanitized code"
        );
    }

    #[test]
    fn test_sec002_xss_concat() {
        let rules = rules::get_all_rules();
        let (_f, path) =
            write_temp(".html", r#"<script>el.innerHTML = "<b>" + userInput</script>"#);
        let findings = scan_file(&path, &rules);
        assert!(
            findings.iter().any(|f| f.rule_id == "SEC-002"),
            "Should detect SEC-002 XSS concatenation"
        );
    }

    #[test]
    fn test_sec004_sql_injection() {
        let rules = rules::get_all_rules();
        let (_f, path) =
            write_temp(".py", "cursor.execute(f\"SELECT * FROM users WHERE id={uid}\")\n");
        let findings = scan_file(&path, &rules);
        assert!(
            findings.iter().any(|f| f.rule_id == "SEC-004"),
            "Should detect SEC-004 SQL injection"
        );
    }

    #[test]
    fn test_sec004_no_false_positive() {
        let rules = rules::get_all_rules();
        let (_f, path) = write_temp(".py", "msg = f\"Hello {name}, welcome!\"\n");
        let findings = scan_file(&path, &rules);
        assert!(
            !findings.iter().any(|f| f.rule_id == "SEC-004"),
            "SEC-004 should NOT fire on regular f-strings"
        );
    }

    #[test]
    fn test_py008_open_without_encoding() {
        let rules = rules::get_all_rules();
        let (_f, path) = write_temp(".py", "f = open('data.txt', 'r')\n");
        let findings = scan_file(&path, &rules);
        assert!(
            findings.iter().any(|f| f.rule_id == "PY-008"),
            "Should detect PY-008 open without encoding"
        );
    }

    #[test]
    fn test_py008_safe_with_encoding() {
        let rules = rules::get_all_rules();
        let (_f, path) = write_temp(".py", "f = open('data.txt', 'r', encoding='utf-8')\n");
        let findings = scan_file(&path, &rules);
        assert!(
            !findings.iter().any(|f| f.rule_id == "PY-008"),
            "PY-008 should NOT fire when encoding present"
        );
    }

    #[test]
    fn test_py008_safe_binary_mode() {
        let rules = rules::get_all_rules();
        let (_f, path) = write_temp(".py", "f = open('data.bin', 'rb')\n");
        let findings = scan_file(&path, &rules);
        assert!(
            !findings.iter().any(|f| f.rule_id == "PY-008"),
            "PY-008 should NOT fire on binary mode"
        );
    }

    #[test]
    fn test_empty_file() {
        let rules = rules::get_all_rules();
        let (_f, path) = write_temp(".py", "");
        let findings = scan_file(&path, &rules);
        assert!(findings.is_empty());
    }

    #[test]
    fn test_unknown_extension() {
        let rules = rules::get_all_rules();
        let (_f, path) = write_temp(".txt", "eval(input())\n");
        let findings = scan_file(&path, &rules);
        assert!(findings.is_empty());
    }

    #[test]
    fn test_line_col_accuracy() {
        let rules = rules::get_all_rules();
        let code = "x = 1\ny = 2\nresult = eval(user_input)\n";
        let (_f, path) = write_temp(".py", code);
        let findings = scan_file(&path, &rules);
        let eval_f: Vec<_> = findings.iter().filter(|f| f.rule_id == "SEC-007").collect();
        assert!(!eval_f.is_empty());
        assert_eq!(eval_f[0].line, 3);
    }

    #[test]
    fn test_exclude_patterns() {
        let dir = tempfile::Builder::new()
            .prefix("xray_test_")
            .tempdir()
            .unwrap();
        let vendor = dir.path().join("vendor");
        std::fs::create_dir_all(&vendor).unwrap();
        std::fs::write(dir.path().join("app.py"), "eval(input())\n").unwrap();
        std::fs::write(vendor.join("lib.py"), "eval(input())\n").unwrap();

        let rules = rules::get_all_rules();
        let result =
            scan_directory_with_excludes(dir.path(), &rules, &["vendor/".to_string()]);
        assert!(
            !result.findings.iter().any(|f| f.file.contains("vendor")),
            "Excluded vendor dir was scanned"
        );
        assert!(result.files_scanned > 0, "Nothing was scanned");
    }
}
