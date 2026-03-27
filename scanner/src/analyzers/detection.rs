//! Detection utilities — function/class/import counting, AI detection, web smells, test stubs.
//! Rust transpilation of analyzers/detection.py.

use fancy_regex::Regex as FancyRegex;
use regex::Regex;
use std::collections::HashMap;
use walkdir::WalkDir;

use crate::constants::{SKIP_DIRS, WEB_EXTS};

/// File statistics.
#[derive(Debug, Clone, serde::Serialize)]
pub struct FileStats {
    pub file: String,
    pub lines: usize,
    pub functions: usize,
    pub classes: usize,
    pub imports: usize,
}

/// Count code elements across a directory.
pub fn count_elements(directory: &str) -> serde_json::Value {
    let func_re = Regex::new(r"^\s*(?:async\s+)?def\s+\w+").unwrap();
    let class_re = Regex::new(r"^\s*class\s+\w+").unwrap();
    let import_re = Regex::new(r"^\s*(?:import|from)\s+").unwrap();

    let mut total_files = 0usize;
    let mut total_lines = 0usize;
    let mut total_functions = 0usize;
    let mut total_classes = 0usize;
    let mut total_imports = 0usize;
    let mut file_stats: Vec<FileStats> = Vec::new();
    let mut lang_counts: HashMap<String, usize> = HashMap::new();

    for entry in WalkDir::new(directory)
        .into_iter()
        .filter_entry(|e| {
            if e.file_type().is_dir() {
                let name = e.file_name().to_str().unwrap_or("");
                !SKIP_DIRS.contains(&name) && !name.starts_with('.')
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
        let ext = path.extension().and_then(|e| e.to_str()).unwrap_or("");
        let lang = match ext {
            "py" => "python",
            "js" | "jsx" | "ts" | "tsx" => "javascript",
            "html" | "htm" => "html",
            "rs" => "rust",
            _ => continue,
        };

        *lang_counts.entry(lang.to_string()).or_insert(0) += 1;

        let content = match std::fs::read_to_string(path) {
            Ok(c) => c,
            Err(_) => continue,
        };
        let rel = path
            .strip_prefix(directory)
            .unwrap_or(path)
            .to_string_lossy()
            .replace('\\', "/");

        let lines = content.lines().count();
        let functions = content.lines().filter(|l| func_re.is_match(l)).count();
        let classes = content.lines().filter(|l| class_re.is_match(l)).count();
        let imports = content.lines().filter(|l| import_re.is_match(l)).count();

        total_files += 1;
        total_lines += lines;
        total_functions += functions;
        total_classes += classes;
        total_imports += imports;

        file_stats.push(FileStats {
            file: rel,
            lines,
            functions,
            classes,
            imports,
        });
    }

    // Sort by lines desc
    file_stats.sort_by(|a, b| b.lines.cmp(&a.lines));

    serde_json::json!({
        "total_files": total_files,
        "total_lines": total_lines,
        "total_functions": total_functions,
        "total_classes": total_classes,
        "total_imports": total_imports,
        "by_language": lang_counts,
        "top_files": file_stats.iter().take(20).collect::<Vec<_>>(),
    })
}

/// Forward-slash normaliser.
fn fwd(p: &str) -> String {
    p.replace('\\', "/")
}

/// Walk Python files, yielding (path, relative_path).
fn walk_py(directory: &str) -> Vec<(std::path::PathBuf, String)> {
    let mut results = Vec::new();
    for entry in WalkDir::new(directory)
        .into_iter()
        .filter_entry(|e| {
            if e.file_type().is_dir() {
                let name = e.file_name().to_str().unwrap_or("");
                !SKIP_DIRS.contains(&name) && !name.starts_with('.')
            } else {
                true
            }
        })
        .filter_map(|e| e.ok())
    {
        if !entry.file_type().is_file() {
            continue;
        }
        let path = entry.path().to_path_buf();
        if path.extension().and_then(|e| e.to_str()) != Some("py") {
            continue;
        }
        let rel = path
            .strip_prefix(directory)
            .unwrap_or(&path)
            .to_string_lossy()
            .replace('\\', "/");
        results.push((path, rel));
    }
    results
}

/// Walk files with given extensions.
fn walk_ext(directory: &str, exts: &[&str]) -> Vec<(std::path::PathBuf, String)> {
    let mut results = Vec::new();
    for entry in WalkDir::new(directory)
        .into_iter()
        .filter_entry(|e| {
            if e.file_type().is_dir() {
                let name = e.file_name().to_str().unwrap_or("");
                !SKIP_DIRS.contains(&name) && !name.starts_with('.')
            } else {
                true
            }
        })
        .filter_map(|e| e.ok())
    {
        if !entry.file_type().is_file() {
            continue;
        }
        let path = entry.path().to_path_buf();
        let ext = path
            .extension()
            .and_then(|e| e.to_str())
            .map(|e| format!(".{}", e));
        let ext_str = ext.as_deref().unwrap_or("");
        if !exts.contains(&ext_str) {
            continue;
        }
        let rel = path
            .strip_prefix(directory)
            .unwrap_or(&path)
            .to_string_lossy()
            .replace('\\', "/");
        results.push((path, rel));
    }
    results
}

/// Heuristic detection of AI-generated code patterns.
/// Transpiled from detection.py::detect_ai_code().
pub fn detect_ai_code(directory: &str) -> serde_json::Value {
    let ai_patterns: Vec<(Regex, &str)> = vec![
        (
            Regex::new(r"(?i)#\s*(Generated by|Auto-generated|AI-generated|Created by ChatGPT|Created by Copilot|Generated with)").unwrap(),
            "AI generation comment",
        ),
        (
            Regex::new(r"(?i)#\s*TODO:?\s*(implement|add|fill|complete)\s+(this|the|your)").unwrap(),
            "Placeholder TODO (common in AI output)",
        ),
        (
            Regex::new(r#"(?i)"""[\s\S]{0,20}(Args|Returns|Raises|Example|Note):"#).unwrap(),
            "Formulaic docstring (common in AI output)",
        ),
        (
            Regex::new(r"(?i)pass\s*#\s*(placeholder|implement|todo)").unwrap(),
            "Pass-with-placeholder pattern",
        ),
    ];

    let mut indicators: Vec<serde_json::Value> = Vec::new();

    for (path, rel) in walk_py(directory) {
        let content = match std::fs::read_to_string(&path) {
            Ok(c) => c,
            Err(_) => continue,
        };

        for (lineno, line) in content.lines().enumerate() {
            let lineno = lineno + 1;
            for (pat, desc) in &ai_patterns {
                if pat.is_match(line) {
                    let evidence = line.trim();
                    // Truncate at a char boundary to avoid panicking on multi-byte UTF-8
                    let evidence_truncated: String;
                    let evidence = if evidence.chars().count() > 120 {
                        let end = evidence.char_indices().nth(120).map(|(i, _)| i).unwrap_or(evidence.len());
                        evidence_truncated = evidence[..end].to_string();
                        evidence_truncated.as_str()
                    } else {
                        evidence
                    };
                    indicators.push(serde_json::json!({
                        "file": fwd(&rel),
                        "line": lineno,
                        "pattern": desc,
                        "evidence": evidence,
                    }));
                    break;
                }
            }
        }
    }

    let total = indicators.len();
    indicators.truncate(500);

    serde_json::json!({
        "indicators": indicators,
        "total": total,
        "note": "Heuristic detection \u{2014} false positives possible",
    })
}

/// Detect common web development anti-patterns in JS/TS/HTML/CSS.
/// Transpiled from detection.py::detect_web_smells().
pub fn detect_web_smells(directory: &str) -> serde_json::Value {
    let web_patterns: Vec<(FancyRegex, &str, &str)> = vec![
        (FancyRegex::new(r"\bdocument\.write\b").unwrap(), "HIGH", "document.write() \u{2014} XSS risk and performance issue"),
        (FancyRegex::new(r"\beval\s*\(").unwrap(), "HIGH", "eval() \u{2014} code injection risk"),
        (FancyRegex::new(r"\binnerHTML\s*=").unwrap(), "MEDIUM", "innerHTML assignment \u{2014} XSS risk, use textContent"),
        (FancyRegex::new(r"console\.(log|debug|info|warn|error)\s*\(").unwrap(), "LOW", "Console statement left in code"),
        (FancyRegex::new(r"font-size:\s*\d+px").unwrap(), "LOW", "Pixel font-size \u{2014} use rem/em for accessibility"),
        (FancyRegex::new(r"!important").unwrap(), "LOW", "!important in CSS \u{2014} specificity issue"),
        (FancyRegex::new(r"\bvar\s+").unwrap(), "MEDIUM", "var keyword \u{2014} use let/const instead"),
        (FancyRegex::new(r"==(?!=)").unwrap(), "MEDIUM", "Loose equality (==) \u{2014} use strict equality (===)"),
        (FancyRegex::new(r"\.then\s*\(.*\.then\s*\(").unwrap(), "MEDIUM", "Nested .then() \u{2014} use async/await"),
        (FancyRegex::new(r"setTimeout\s*\([^,]+,\s*0\s*\)").unwrap(), "LOW", "setTimeout(fn, 0) \u{2014} use queueMicrotask"),
        (FancyRegex::new(r#"<script\s+src\s*=\s*["']http:"#).unwrap(), "HIGH", "HTTP script src \u{2014} use HTTPS"),
        (FancyRegex::new(r"<img(?![^>]*alt\s*=)[^>]*>").unwrap(), "MEDIUM", "Missing alt attribute on img \u{2014} accessibility"),
    ];

    let mut smells: Vec<serde_json::Value> = Vec::new();

    for (path, rel) in walk_ext(directory, WEB_EXTS) {
        let content = match std::fs::read_to_string(&path) {
            Ok(c) => c,
            Err(_) => continue,
        };

        for (lineno, line) in content.lines().enumerate() {
            let lineno = lineno + 1;
            for (pat, severity, desc) in &web_patterns {
                if pat.is_match(line).unwrap_or(false) {
                    let evidence = line.trim();
                    // Truncate at a char boundary to avoid panicking on multi-byte UTF-8
                    let evidence = if evidence.chars().count() > 120 {
                        let end = evidence.char_indices().nth(120).map(|(i, _)| i).unwrap_or(evidence.len());
                        &evidence[..end]
                    } else {
                        evidence
                    };
                    smells.push(serde_json::json!({
                        "file": fwd(&rel),
                        "line": lineno,
                        "severity": severity,
                        "description": desc,
                        "evidence": evidence,
                    }));
                }
            }
        }
    }

    smells.truncate(1000);

    let mut by_severity: HashMap<String, usize> = HashMap::new();
    for s in &smells {
        let sev = s["severity"].as_str().unwrap_or("LOW").to_string();
        *by_severity.entry(sev).or_insert(0) += 1;
    }

    serde_json::json!({
        "smells": smells,
        "total": smells.len(),
        "by_severity": by_severity,
    })
}

/// Generate pytest test stubs for untested functions.
/// Transpiled from detection.py::generate_test_stubs().
pub fn generate_test_stubs(directory: &str) -> serde_json::Value {
    let func_re = Regex::new(r"^\s*(?:async\s+)?def\s+(\w+)\s*\(([^)]*)\)").unwrap();
    let mut functions: Vec<serde_json::Value> = Vec::new();
    let mut test_files: Vec<String> = Vec::new();

    // Find existing test files
    for (_, rel) in walk_py(directory) {
        if rel.to_lowercase().contains("test") {
            test_files.push(rel);
        }
    }

    // Find functions that likely need tests
    for (path, rel) in walk_py(directory) {
        if rel.to_lowercase().contains("test") {
            continue;
        }

        let content = match std::fs::read_to_string(&path) {
            Ok(c) => c,
            Err(_) => continue,
        };

        let lines: Vec<&str> = content.lines().collect();

        // Simple function extraction (no full AST in Rust, but close enough)
        for (i, line) in lines.iter().enumerate() {
            if let Some(caps) = func_re.captures(line) {
                let name = caps.get(1).map(|m| m.as_str()).unwrap_or("");
                if name.starts_with('_') {
                    continue;
                }
                let params_str = caps.get(2).map(|m| m.as_str()).unwrap_or("");

                // Estimate function length: find next def or end of file at same/lower indent
                let indent = line.len() - line.trim_start().len();
                let mut end_line = i + 1;
                for j in (i + 1)..lines.len() {
                    let l = lines[j];
                    if l.trim().is_empty() {
                        continue;
                    }
                    let l_indent = l.len() - l.trim_start().len();
                    if l_indent <= indent
                        && (l.trim_start().starts_with("def ")
                            || l.trim_start().starts_with("async def ")
                            || l.trim_start().starts_with("class "))
                    {
                        break;
                    }
                    end_line = j + 1;
                }
                let line_count = end_line - i;
                if line_count < 3 {
                    continue;
                }

                // Check if there's a test for this function
                let has_test = test_files
                    .iter()
                    .any(|tf| tf.contains(&format!("test_{}", name)) || tf.contains(name));

                // Parse params (exclude self, cls)
                let params: Vec<String> = params_str
                    .split(',')
                    .map(|p| p.trim().split(':').next().unwrap_or("").trim().to_string())
                    .filter(|p| !p.is_empty() && p != "self" && p != "cls")
                    .collect();

                functions.push(serde_json::json!({
                    "name": name,
                    "file": fwd(&rel),
                    "line": i + 1,
                    "lines": line_count,
                    "has_test": has_test,
                    "params": params,
                }));
            }
        }
    }

    // Generate stubs for untested functions
    let untested: Vec<&serde_json::Value> = functions
        .iter()
        .filter(|f| !f["has_test"].as_bool().unwrap_or(true))
        .collect();
    let untested_count = untested.len();
    let tested_count = functions.iter().filter(|f| f["has_test"].as_bool().unwrap_or(false)).count();

    let stubs: Vec<serde_json::Value> = untested
        .iter()
        .take(50)
        .map(|func| {
            let name = func["name"].as_str().unwrap_or("");
            let file = func["file"].as_str().unwrap_or("");
            let module = file.replace('/', ".").trim_end_matches(".py").to_string();
            let params: Vec<String> = func["params"]
                .as_array()
                .map(|a| a.iter().take(3).filter_map(|p| p.as_str().map(String::from)).collect())
                .unwrap_or_default();
            let params_str = params.join(", ");
            let stub = format!(
                "def test_{}():\n    \"\"\"Test {} from {}\"\"\"\n    from {} import {}\n    result = {}({})\n    assert result is not None\n",
                name, name, file, module, name, name, params_str
            );
            serde_json::json!({
                "function": name,
                "file": file,
                "stub": stub,
            })
        })
        .collect();

    let total = functions.len();
    let coverage_pct = if total > 0 {
        (tested_count as f64 / total as f64 * 1000.0).round() / 10.0
    } else {
        0.0
    };

    serde_json::json!({
        "total_functions": total,
        "tested": tested_count,
        "untested": untested_count,
        "coverage_pct": coverage_pct,
        "stubs": stubs,
    })
}
