// src/ast_parse.rs — Python AST parsing, function/class extraction, file walking
//
// This is the CORE of X-Ray: parse Python files, extract functions and classes
// with all metrics (complexity, nesting, hashes, call graph, etc.)
//
// Uses regex-based structural analysis — fast and dependency-free.

use crate::config;
use crate::types::{ClassRecord, FunctionRecord};
use rayon::prelude::*;
use regex::Regex;
use sha2::{Digest, Sha256};
use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::sync::LazyLock;
use walkdir::WalkDir;

// ── Regexes ────────────────────────────────────────────────────────

static RE_FUNC: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?m)^([ \t]*)(async\s+)?def\s+(\w+)\s*\(([^)]*)\)(?:\s*->\s*([^:]+))?\s*:")
        .unwrap()
});

static RE_CLASS: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?m)^([ \t]*)class\s+(\w+)\s*(?:\(([^)]*)\))?\s*:").unwrap()
});

static RE_DECORATOR: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?m)^([ \t]*)@(\S+)").unwrap()
});

static RE_CALL: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?:\b(\w+)\s*\(|\.(\w+)\s*\()").unwrap()
});

#[allow(dead_code)]
static RE_DOCSTRING: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r#"(?s)^[ \t]*(""".*?"""|'''.*?'''|"[^"]*"|'[^']*')"#).unwrap()
});

// Nesting keywords
static NESTING_KW: LazyLock<HashSet<&'static str>> = LazyLock::new(|| {
    ["if", "for", "while", "try", "with", "except", "elif"]
        .iter()
        .copied()
        .collect()
});

// Complexity keywords
static COMPLEXITY_KW: LazyLock<HashSet<&'static str>> = LazyLock::new(|| {
    [
        "if", "elif", "for", "while", "try", "except", "and", "or",
        "assert", "with",
    ]
    .iter()
    .copied()
    .collect()
});

static RE_KEYWORD_LINE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?m)^\s*(if|elif|else|for|while|try|except|with|assert)\b").unwrap()
});

static RE_RETURN: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?m)^\s*return\b").unwrap()
});

static RE_BRANCH: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?m)^\s*if\b").unwrap()
});

static RE_BOOL_OP: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"\b(and|or)\b").unwrap()
});

// ── File Walking ───────────────────────────────────────────────────

/// Collect all .py files under `root`, respecting exclusions
pub fn collect_py_files(
    root: &Path,
    exclude: &[String],
    include: &[String],
) -> Vec<PathBuf> {
    let skip_dirs = &*config::SKIP_DIRS;
    let skip_files = &*config::SKIP_FILES;
    let mut files = Vec::new();

    for entry in WalkDir::new(root)
        .follow_links(false)
        .into_iter()
        .filter_entry(|e| {
            if e.file_type().is_dir() {
                let name = e.file_name().to_string_lossy();
                if skip_dirs.contains(name.as_ref()) {
                    return false;
                }
                if name.ends_with(".egg-info") {
                    return false;
                }
                // Check user excludes
                let rel = e.path().strip_prefix(root).unwrap_or(e.path());
                for ex in exclude {
                    if rel.to_string_lossy().contains(ex.as_str()) {
                        return false;
                    }
                }
                return true;
            }
            true
        })
    {
        let entry = match entry {
            Ok(e) => e,
            Err(_) => continue,
        };
        if !entry.file_type().is_file() {
            continue;
        }
        let path = entry.path();
        let ext = path.extension().and_then(|e| e.to_str());
        if ext != Some("py") {
            continue;
        }
        let fname = path.file_name().unwrap_or_default().to_string_lossy();
        if skip_files.contains(fname.as_ref()) {
            continue;
        }
        // Include filter
        if !include.is_empty() {
            let rel = path.strip_prefix(root).unwrap_or(path);
            let top = rel
                .components()
                .next()
                .map(|c| c.as_os_str().to_string_lossy().to_string())
                .unwrap_or_default();
            if !include.iter().any(|inc| top == *inc) {
                continue;
            }
        }
        files.push(path.to_path_buf());
    }
    files
}

// ── Indentation helpers ────────────────────────────────────────────

fn indent_level(line: &str) -> usize {
    let mut spaces = 0;
    for ch in line.chars() {
        match ch {
            ' ' => spaces += 1,
            '\t' => spaces += 4,
            _ => break,
        }
    }
    spaces
}

/// Get the body of a definition starting at `start_line` with the given indent
fn extract_body(lines: &[&str], start_line: usize, def_indent: usize) -> (usize, String) {
    let mut end = start_line + 1;
    let body_indent = def_indent + 1; // at least one more level
    while end < lines.len() {
        let line = lines[end];
        if line.trim().is_empty() {
            end += 1;
            continue;
        }
        let ind = indent_level(line);
        if ind <= def_indent && !line.trim().is_empty() {
            break;
        }
        // Accept lines that are deeper or at body_indent
        if ind >= body_indent || line.trim().starts_with('#') {
            end += 1;
        } else {
            break;
        }
    }
    let body: String = lines[start_line..end].join("\n");
    (end, body)
}

// ── Metric Computation ─────────────────────────────────────────────

/// Compute max nesting depth of a code block
fn compute_nesting_depth(code: &str) -> u32 {
    let mut max_depth: u32 = 0;
    let mut current_depth: u32 = 0;
    let mut indent_stack: Vec<usize> = Vec::new();

    for line in code.lines() {
        let trimmed = line.trim();
        if trimmed.is_empty() || trimmed.starts_with('#') {
            continue;
        }
        let ind = indent_level(line);

        // Pop back to current indentation
        while let Some(&top) = indent_stack.last() {
            if ind <= top {
                indent_stack.pop();
                current_depth = current_depth.saturating_sub(1);
            } else {
                break;
            }
        }

        // Check if this line starts a nesting block
        let first_word = trimmed.split_whitespace().next().unwrap_or("");
        let kw = first_word.trim_end_matches(':');
        if NESTING_KW.contains(kw) {
            indent_stack.push(ind);
            current_depth += 1;
            max_depth = max_depth.max(current_depth);
        }
    }
    max_depth
}

/// Compute cyclomatic complexity of a code block
fn compute_complexity(code: &str) -> u32 {
    let mut complexity: u32 = 1; // base complexity
    for line in code.lines() {
        let trimmed = line.trim();
        if trimmed.is_empty() || trimmed.starts_with('#') {
            continue;
        }
        // Count keywords
        if let Some(cap) = RE_KEYWORD_LINE.captures(line) {
            let kw = cap.get(1).unwrap().as_str();
            if COMPLEXITY_KW.contains(kw) {
                complexity += 1;
            }
        }
        // Count boolean operators
        complexity += RE_BOOL_OP.find_iter(trimmed).count() as u32;
    }
    // Count list/dict/set comprehensions (heuristic: `for` inside [...], {...})
    complexity
}

/// Extract docstring from body lines (first triple-quoted string)
fn extract_docstring(body: &str) -> Option<String> {
    let trimmed = body.trim_start();
    // Check for triple-quoted docstring
    for prefix in &["\"\"\"", "'''"] {
        if trimmed.starts_with(prefix) {
            let rest = &trimmed[3..];
            if let Some(end) = rest.find(prefix) {
                return Some(rest[..end].trim().to_string());
            }
        }
    }
    None
}

/// Extract function calls from code
fn extract_calls(code: &str) -> Vec<String> {
    let mut calls = HashSet::new();
    for cap in RE_CALL.captures_iter(code) {
        if let Some(m) = cap.get(1) {
            let name = m.as_str();
            // Skip keywords and builtins like if, for, while, print, etc.
            if !NESTING_KW.contains(name) && !["else", "return", "yield", "raise", "del", "pass"].contains(&name) {
                calls.insert(name.to_string());
            }
        }
        if let Some(m) = cap.get(2) {
            calls.insert(m.as_str().to_string());
        }
    }
    let mut result: Vec<String> = calls.into_iter().collect();
    result.sort();
    result
}

/// SHA-256 hash of code text
fn sha256_hex(text: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(text.as_bytes());
    format!("{:x}", hasher.finalize())
}

/// Compute structure hash: normalize names, then hash
fn compute_structure_hash(code: &str) -> String {
    static RE_IDENT: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(r"\b([a-zA-Z_]\w*)\b").unwrap()
    });

    // Normalize: replace all identifiers with placeholders
    let mut var_map = std::collections::HashMap::new();
    let mut counter = 0u32;

    let builtins = &*config::PYTHON_BUILTINS;
    let keywords = &*config::PYTHON_KEYWORDS;

    let normalized = RE_IDENT.replace_all(code, |caps: &regex::Captures| {
        let name = &caps[1];
        // Preserve keywords and builtins
        if keywords.contains(name) || builtins.contains(name) {
            return name.to_string();
        }
        let entry = var_map.entry(name.to_string()).or_insert_with(|| {
            let id = format!("v{}", counter);
            counter += 1;
            id
        });
        entry.clone()
    });

    sha256_hex(&normalized)
}

/// Parse parameters, stripping `self` and type annotations
fn parse_params(params_str: &str) -> Vec<String> {
    if params_str.trim().is_empty() {
        return vec![];
    }
    params_str
        .split(',')
        .map(|p| {
            let p = p.trim();
            // Strip type annotation
            let name = p.split(':').next().unwrap_or(p).trim();
            // Strip default value
            let name = name.split('=').next().unwrap_or(name).trim();
            // Strip * and **
            let name = name.trim_start_matches('*');
            name.to_string()
        })
        .filter(|p| !p.is_empty() && p != "self" && p != "cls")
        .collect()
}

// ── Function & Class Extraction ────────────────────────────────────

/// Extract all functions and classes from a single Python file
pub fn extract_from_file(
    path: &Path,
    root: &Path,
) -> (Vec<FunctionRecord>, Vec<ClassRecord>, Option<String>) {
    let content = match std::fs::read_to_string(path) {
        Ok(c) => c,
        Err(e) => return (vec![], vec![], Some(format!("{}: {}", path.display(), e))),
    };

    let rel_path = path
        .strip_prefix(root)
        .unwrap_or(path)
        .to_string_lossy()
        .replace('\\', "/");

    let lines: Vec<&str> = content.lines().collect();
    let mut functions = Vec::new();
    let mut classes = Vec::new();

    // Find all class definitions and their ranges
    let mut class_ranges: Vec<(String, usize, usize, usize)> = Vec::new(); // (name, start, end, indent)
    for cap in RE_CLASS.captures_iter(&content) {
        let full_match = cap.get(0).unwrap();
        let line_num = content[..full_match.start()].matches('\n').count();
        let indent = indent_level(cap.get(1).unwrap().as_str());
        let name = cap.get(2).unwrap().as_str().to_string();
        let (end_line, _) = extract_body(&lines, line_num, indent);
        class_ranges.push((name, line_num, end_line, indent));
    }

    // Extract classes
    for cap in RE_CLASS.captures_iter(&content) {
        let full_match = cap.get(0).unwrap();
        let line_num = content[..full_match.start()].matches('\n').count();
        let indent = indent_level(cap.get(1).unwrap().as_str());

        // Only top-level classes (indent == 0)
        if indent > 0 {
            continue;
        }

        let name = cap.get(2).unwrap().as_str().to_string();
        let bases_str = cap.get(3).map_or("", |m| m.as_str());
        let base_classes: Vec<String> = if bases_str.is_empty() {
            vec![]
        } else {
            bases_str.split(',').map(|b| b.trim().to_string()).filter(|b| !b.is_empty()).collect()
        };

        let (end_line, body) = extract_body(&lines, line_num, indent);
        let docstring = extract_docstring(&body.split_once('\n').map(|(_, b)| b).unwrap_or(""));
        let size = (end_line - line_num) as u32;

        // Count methods
        let mut methods = Vec::new();
        let mut has_init = false;
        for m_cap in RE_FUNC.captures_iter(&body) {
            let m_indent = indent_level(m_cap.get(1).unwrap().as_str());
            if m_indent > indent {
                let mname = m_cap.get(3).unwrap().as_str().to_string();
                if mname == "__init__" {
                    has_init = true;
                }
                methods.push(mname);
            }
        }

        classes.push(ClassRecord {
            name,
            file_path: rel_path.clone(),
            line_start: (line_num + 1) as u32,
            line_end: end_line as u32,
            size_lines: size,
            method_count: methods.len() as u32,
            base_classes,
            docstring,
            methods,
            has_init,
        });
    }

    // Extract decorators map: line -> decorators above it
    let mut decorators_map: std::collections::HashMap<usize, Vec<String>> =
        std::collections::HashMap::new();
    for cap in RE_DECORATOR.captures_iter(&content) {
        let full_match = cap.get(0).unwrap();
        let line_num = content[..full_match.start()].matches('\n').count();
        let dec_name = cap.get(2).unwrap().as_str().to_string();
        decorators_map
            .entry(line_num)
            .or_default()
            .push(dec_name);
    }

    // Extract functions
    for cap in RE_FUNC.captures_iter(&content) {
        let full_match = cap.get(0).unwrap();
        let line_num = content[..full_match.start()].matches('\n').count();
        let indent = indent_level(cap.get(1).unwrap().as_str());
        let is_async = cap.get(2).is_some();
        let name = cap.get(3).unwrap().as_str().to_string();
        let params_str = cap.get(4).map_or("", |m| m.as_str());
        let return_type = cap.get(5).map(|m| m.as_str().trim().to_string());

        // Skip nested functions (indent > 4 unless inside a class)
        let is_method = class_ranges
            .iter()
            .any(|(_, start, end, ci)| line_num > *start && line_num < *end && indent > *ci);
        let is_top_level = indent == 0;
        if !is_top_level && !is_method {
            continue; // skip nested functions
        }

        let parameters = parse_params(params_str);
        let (end_line, body) = extract_body(&lines, line_num, indent);
        let size = (end_line - line_num) as u32;

        // Get the raw code
        let code_lines = &lines[line_num..end_line.min(lines.len())];
        let code = code_lines.join("\n");

        let docstring = extract_docstring(
            &body.split_once('\n').map(|(_, b)| b).unwrap_or(""),
        );

        // Gather decorators from lines above
        let mut decorators = Vec::new();
        for check_line in (0..line_num).rev() {
            if let Some(decs) = decorators_map.get(&check_line) {
                decorators.extend(decs.iter().cloned());
            } else {
                let line_text = lines.get(check_line).unwrap_or(&"").trim();
                if !line_text.starts_with('@') && !line_text.is_empty() {
                    break;
                }
            }
        }

        let calls_to = extract_calls(&code);
        let return_count = RE_RETURN.find_iter(&code).count() as u32;
        let branch_count = RE_BRANCH.find_iter(&code).count() as u32;
        let complexity = compute_complexity(&code);
        let nesting_depth = compute_nesting_depth(&code);
        let code_hash = sha256_hex(&code);
        let structure_hash = compute_structure_hash(&code);

        functions.push(FunctionRecord {
            name,
            file_path: rel_path.clone(),
            line_start: (line_num + 1) as u32,
            line_end: end_line as u32,
            size_lines: size,
            parameters,
            return_type,
            decorators,
            docstring,
            calls_to,
            complexity,
            nesting_depth,
            code_hash,
            structure_hash,
            code,
            return_count,
            branch_count,
            is_async,
        });
    }

    (functions, classes, None)
}

/// Parallel scan of entire codebase
pub fn scan_codebase(
    root: &Path,
    exclude: &[String],
    include: &[String],
) -> (Vec<FunctionRecord>, Vec<ClassRecord>, Vec<String>) {
    let py_files = collect_py_files(root, exclude, include);
    let results: Vec<_> = py_files
        .par_iter()
        .map(|f| extract_from_file(f, root))
        .collect();

    let mut all_funcs = Vec::new();
    let mut all_classes = Vec::new();
    let mut errors = Vec::new();

    for (funcs, classes, err) in results {
        all_funcs.extend(funcs);
        all_classes.extend(classes);
        if let Some(e) = err {
            errors.push(e);
        }
    }

    (all_funcs, all_classes, errors)
}
