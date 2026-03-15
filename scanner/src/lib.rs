//! X-Ray Scanner — High-performance Rust code analysis engine.
//!
//! Port of the Python scanner with exact regex parity.
//! Uses fancy-regex for negative lookaheads (SEC-001, SEC-009, PY-005, PY-008, QUAL-010).

pub mod rules;

use fancy_regex::Regex;
use serde::{Deserialize, Serialize};
use std::path::Path;
use walkdir::WalkDir;

/// Maximum file size to scan (1 MB) — matches Python scanner.
const MAX_FILE_SIZE: u64 = 1_048_576;

/// Directories to skip — matches Python `_SKIP_DIRS`.
const SKIP_DIRS: &[&str] = &[
    "__pycache__",
    "node_modules",
    ".git",
    ".venv",
    "venv",
    "target",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
    ".tox",
    "htmlcov",
    "eggs",
    "*.egg-info",
];

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
}

/// Aggregated scan results.
#[derive(Debug, Serialize, Deserialize)]
pub struct ScanResult {
    pub findings: Vec<Finding>,
    pub files_scanned: usize,
    pub rules_checked: usize,
    #[serde(default)]
    pub errors: Vec<String>,
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
            "Scanned {} files | {} findings (HIGH:{} MED:{} LOW:{})",
            self.files_scanned,
            self.findings.len(),
            self.high_count(),
            self.medium_count(),
            self.low_count(),
        )
    }
}

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
    SKIP_DIRS.contains(&name) || name.starts_with('.')
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

    // Check file size before reading
    if let Ok(meta) = std::fs::metadata(path) {
        if meta.len() > MAX_FILE_SIZE {
            return vec![];
        }
    }

    // Read with lossy UTF-8 (matches Python errors="replace")
    let bytes = match std::fs::read(path) {
        Ok(b) => b,
        Err(_) => return vec![],
    };
    let content = String::from_utf8_lossy(&bytes);

    let mut findings = Vec::new();
    let file_str = path.to_string_lossy().to_string();

    for rule in &applicable {
        // fancy-regex find_iter returns Result
        let mut start = 0;
        while start < content.len() {
            let slice = &content[start..];
            match rule.pattern.find(slice) {
                Ok(Some(mat)) => {
                    let abs_start = start + mat.start();
                    let line = content[..abs_start].matches('\n').count() + 1;
                    let line_start = content[..abs_start].rfind('\n').map_or(0, |i| i + 1);
                    let col = abs_start - line_start + 1;

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

                    // Advance past this match to find next
                    start = abs_start + mat.end().max(1) - mat.start();
                }
                Ok(None) => break,
                Err(_) => break,
            }
        }
    }

    findings
}

/// Scan an entire directory tree with optional exclude patterns.
pub fn scan_directory(root: &Path, rules: &[Rule]) -> ScanResult {
    scan_directory_with_excludes(root, rules, &[])
}

/// Scan a directory tree, skipping paths matching exclude patterns.
pub fn scan_directory_with_excludes(
    root: &Path,
    rules: &[Rule],
    exclude_patterns: &[String],
) -> ScanResult {
    let mut result = ScanResult {
        findings: Vec::new(),
        files_scanned: 0,
        rules_checked: rules.len(),
        errors: Vec::new(),
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

        // Check exclude patterns against relative path (forward slashes for cross-platform)
        if let Ok(rel) = path.strip_prefix(root) {
            let rel_str = rel.to_string_lossy().replace('\\', "/");
            if exclude_res.iter().any(|re| re.is_match(&rel_str)) {
                continue;
            }
        }

        result.files_scanned += 1;
        let file_findings = scan_file(path, rules);
        result.findings.extend(file_findings);
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
    fn test_scan_file_detects_eval() {
        let rules = rules::get_all_rules();
        let (_f, path) = write_temp(".py", "result = eval(user_input)\n");
        let findings = scan_file(&path, &rules);
        assert!(findings.iter().any(|f| f.rule_id == "SEC-007"));
    }

    #[test]
    fn test_sec001_xss_template() {
        let rules = rules::get_all_rules();
        let (_f, path) = write_temp(".html", "<script>el.innerHTML = `<b>${name}</b>`;</script>");
        let findings = scan_file(&path, &rules);
        assert!(findings.iter().any(|f| f.rule_id == "SEC-001"),
                "Should detect SEC-001 XSS template literal");
    }

    #[test]
    fn test_sec001_safe_sanitized() {
        let rules = rules::get_all_rules();
        let (_f, path) = write_temp(".html", "<script>el.innerHTML = `<b>${_escHtml(name)}</b>`;</script>");
        let findings = scan_file(&path, &rules);
        assert!(!findings.iter().any(|f| f.rule_id == "SEC-001"),
                "SEC-001 should NOT fire on sanitized code");
    }

    #[test]
    fn test_sec002_xss_concat() {
        let rules = rules::get_all_rules();
        let (_f, path) = write_temp(".html", r#"<script>el.innerHTML = "<b>" + userInput</script>"#);
        let findings = scan_file(&path, &rules);
        assert!(findings.iter().any(|f| f.rule_id == "SEC-002"),
                "Should detect SEC-002 XSS concatenation");
    }

    #[test]
    fn test_sec004_sql_injection() {
        let rules = rules::get_all_rules();
        let (_f, path) = write_temp(".py", "cursor.execute(f\"SELECT * FROM users WHERE id={uid}\")\n");
        let findings = scan_file(&path, &rules);
        assert!(findings.iter().any(|f| f.rule_id == "SEC-004"),
                "Should detect SEC-004 SQL injection");
    }

    #[test]
    fn test_sec004_no_false_positive() {
        let rules = rules::get_all_rules();
        let (_f, path) = write_temp(".py", "msg = f\"Hello {name}, welcome!\"\n");
        let findings = scan_file(&path, &rules);
        assert!(!findings.iter().any(|f| f.rule_id == "SEC-004"),
                "SEC-004 should NOT fire on regular f-strings");
    }

    #[test]
    fn test_py008_open_without_encoding() {
        let rules = rules::get_all_rules();
        let (_f, path) = write_temp(".py", "f = open('data.txt', 'r')\n");
        let findings = scan_file(&path, &rules);
        assert!(findings.iter().any(|f| f.rule_id == "PY-008"),
                "Should detect PY-008 open without encoding");
    }

    #[test]
    fn test_py008_safe_with_encoding() {
        let rules = rules::get_all_rules();
        let (_f, path) = write_temp(".py", "f = open('data.txt', 'r', encoding='utf-8')\n");
        let findings = scan_file(&path, &rules);
        assert!(!findings.iter().any(|f| f.rule_id == "PY-008"),
                "PY-008 should NOT fire when encoding present");
    }

    #[test]
    fn test_py008_safe_binary_mode() {
        let rules = rules::get_all_rules();
        let (_f, path) = write_temp(".py", "f = open('data.bin', 'rb')\n");
        let findings = scan_file(&path, &rules);
        assert!(!findings.iter().any(|f| f.rule_id == "PY-008"),
                "PY-008 should NOT fire on binary mode");
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
        std::fs::write(
            dir.path().join("app.py"),
            "eval(input())\n",
        ).unwrap();
        std::fs::write(
            vendor.join("lib.py"),
            "eval(input())\n",
        ).unwrap();

        let rules = rules::get_all_rules();
        let result = scan_directory_with_excludes(
            dir.path(),
            &rules,
            &["vendor/".to_string()],
        );
        assert!(!result.findings.iter().any(|f| f.file.contains("vendor")),
                "Excluded vendor dir was scanned");
        assert!(result.files_scanned > 0, "Nothing was scanned");
    }
}
