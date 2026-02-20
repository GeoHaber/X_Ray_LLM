// src/config.rs — Configuration constants
use std::collections::{HashMap, HashSet};

pub const VERSION: &str = "5.0.0";

pub const BANNER: &str = r#"
================================================================
  X-RAY v5.0.0 — Unified Code Quality Scanner (Rust)
  AST Smells + Ruff Lint + Bandit Security
================================================================
"#;

/// Smell thresholds
pub struct SmellThresholds {
    pub long_function: u32,
    pub very_long_function: u32,
    pub deep_nesting: u32,
    pub very_deep_nesting: u32,
    pub high_complexity: u32,
    pub very_high_complexity: u32,
    pub too_many_params: u32,
    pub god_class: u32,
    pub large_class: u32,
    pub missing_docstring_size: u32,
    pub too_many_returns: u32,
    pub too_many_branches: u32,
}

impl Default for SmellThresholds {
    fn default() -> Self {
        Self {
            long_function: 60,
            very_long_function: 120,
            deep_nesting: 4,
            very_deep_nesting: 6,
            high_complexity: 10,
            very_high_complexity: 20,
            too_many_params: 6,
            god_class: 15,
            large_class: 500,
            missing_docstring_size: 15,
            too_many_returns: 5,
            too_many_branches: 8,
        }
    }
}

/// Directories to always skip during file walk
pub fn always_skip_dirs() -> HashSet<&'static str> {
    [
        ".git", "__pycache__", ".venv", "venv", "env", ".env",
        "node_modules", ".tox", ".mypy_cache", ".pytest_cache",
        ".ruff_cache", "dist", "build", ".eggs", "target",
        ".idea", ".vscode", ".vs", "site-packages",
    ].iter().copied().collect()
}

/// Files to always skip
pub fn always_skip_files() -> HashSet<&'static str> {
    ["smell_factory.py", "bad_code_sample.py"].iter().copied().collect()
}

/// Stop words for tokenization
pub fn stop_words() -> HashSet<&'static str> {
    [
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "being", "have", "has", "had", "do", "does", "did", "will",
        "would", "could", "should", "may", "might", "shall", "can",
        "to", "of", "in", "for", "on", "with", "at", "by", "from",
        "as", "into", "through", "during", "before", "after", "and",
        "but", "or", "not", "no", "if", "then", "else", "when",
        "while", "this", "that", "it", "its", "self",
    ].iter().copied().collect()
}

/// Ruff severity map
pub fn ruff_severity_map() -> HashMap<&'static str, &'static str> {
    let mut m = HashMap::new();
    m.insert("F811", "critical");
    m.insert("E999", "critical");
    m.insert("F821", "critical");
    m.insert("F401", "warning");
    m.insert("F841", "warning");
    m.insert("E722", "warning");
    m.insert("E741", "warning");
    m.insert("E402", "warning");
    m.insert("F541", "info");
    m.insert("E701", "info");
    m
}

/// Bandit severity map
pub fn bandit_severity(sev: &str) -> &'static str {
    match sev {
        "HIGH" => "critical",
        "MEDIUM" => "warning",
        _ => "info",
    }
}

/// Python keywords (preserved during AST normalization)
pub fn python_keywords() -> HashSet<&'static str> {
    [
        "False", "None", "True", "and", "as", "assert", "async", "await",
        "break", "class", "continue", "def", "del", "elif", "else", "except",
        "finally", "for", "from", "global", "if", "import", "in", "is",
        "lambda", "nonlocal", "not", "or", "pass", "raise", "return", "try",
        "while", "with", "yield",
    ].iter().copied().collect()
}

/// Python builtins (preserved during AST normalization)
pub fn python_builtins() -> HashSet<&'static str> {
    [
        "print", "len", "range", "int", "str", "float", "bool", "list",
        "dict", "set", "tuple", "type", "isinstance", "issubclass",
        "hasattr", "getattr", "setattr", "delattr", "callable", "super",
        "property", "classmethod", "staticmethod", "enumerate", "zip",
        "map", "filter", "sorted", "reversed", "any", "all", "min", "max",
        "sum", "abs", "round", "hash", "id", "repr", "format", "open",
        "input", "iter", "next", "object", "Exception", "ValueError",
        "TypeError", "KeyError", "IndexError", "AttributeError",
        "RuntimeError", "StopIteration", "OSError", "IOError",
        "FileNotFoundError", "NotImplementedError", "ImportError",
    ].iter().copied().collect()
}
