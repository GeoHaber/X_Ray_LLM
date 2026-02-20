// src/library_advisor.rs — Suggests shared library modules from duplicate groups
//
// Port of Analysis/library_advisor.py

use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};

use crate::types::{DuplicateGroup, FunctionRecord};

/// A suggestion to extract functions into a shared module.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LibrarySuggestion {
    pub module_name: String,
    pub description: String,
    pub functions: Vec<serde_json::Value>,
    pub unified_api: String,
    pub rationale: String,
}

/// Analyzes duplication groups and function names to suggest potential shared libraries.
pub fn analyze(
    duplicates: &[DuplicateGroup],
    functions: &[FunctionRecord],
) -> Vec<LibrarySuggestion> {
    let mut suggestions = Vec::new();

    // 1. Suggestions from explicit duplicate groups
    from_duplicates(duplicates, &mut suggestions);

    // 2. Collect covered keys from duplicate-based suggestions
    let covered: HashSet<String> = suggestions
        .iter()
        .flat_map(|s| {
            s.functions.iter().filter_map(|f| {
                f.get("key").and_then(|k| k.as_str()).map(String::from)
            })
        })
        .collect();

    // 3. Cross-file name suggestions
    let name_suggestions = name_repetition_suggestions(functions, &covered);
    suggestions.extend(name_suggestions);

    suggestions
}

/// Create suggestions from explicit duplicate groups.
fn from_duplicates(duplicates: &[DuplicateGroup], suggestions: &mut Vec<LibrarySuggestion>) {
    for group in duplicates {
        if group.functions.len() < 2 && group.similarity_type != "exact" {
            continue;
        }

        let names: Vec<String> = group
            .functions
            .iter()
            .filter_map(|f| f.get("name").and_then(|n| n.as_str()).map(String::from))
            .collect();

        if names.is_empty() {
            continue;
        }

        // Find most common name
        let mut counts: HashMap<&str, usize> = HashMap::new();
        for n in &names {
            *counts.entry(n.as_str()).or_insert(0) += 1;
        }
        let most_common = counts
            .into_iter()
            .max_by_key(|(_, c)| *c)
            .map(|(n, _)| n.to_string())
            .unwrap_or_default();

        let module_name = suggest_module_name(&most_common);

        suggestions.push(LibrarySuggestion {
            module_name,
            description: format!(
                "Cluster of {} similar functions ({})",
                group.functions.len(),
                most_common
            ),
            functions: group.functions.clone(),
            unified_api: format!("def {}(...):", most_common),
            rationale: format!(
                "Found {} {} duplicates.",
                group.functions.len(),
                group.similarity_type
            ),
        });
    }
}

/// Create suggestions from cross-file name repetition.
fn name_repetition_suggestions(
    functions: &[FunctionRecord],
    covered_keys: &HashSet<String>,
) -> Vec<LibrarySuggestion> {
    let mut suggestions = Vec::new();

    // Group functions by name (excluding dunders)
    let mut name_map: HashMap<&str, Vec<&FunctionRecord>> = HashMap::new();
    for f in functions {
        if !(f.name.starts_with("__") && f.name.ends_with("__")) {
            name_map.entry(&f.name).or_default().push(f);
        }
    }

    for (name, funcs) in &name_map {
        if funcs.len() < 2 {
            continue;
        }

        // Must span multiple files
        let files: HashSet<&str> = funcs.iter().map(|f| f.file_path.as_str()).collect();
        if files.len() < 2 {
            continue;
        }

        // Skip if already covered by duplicate-based suggestions
        if funcs.iter().any(|f| covered_keys.contains(&f.key())) {
            continue;
        }

        let module_name = suggest_module_name(name);
        let func_dicts: Vec<serde_json::Value> = funcs
            .iter()
            .map(|f| {
                serde_json::json!({
                    "name": f.name,
                    "file": f.file_path,
                    "line": f.line_start,
                    "key": f.key(),
                })
            })
            .collect();

        suggestions.push(LibrarySuggestion {
            module_name,
            description: format!(
                "Multiple functions named '{}' across {} files",
                name,
                files.len()
            ),
            functions: func_dicts,
            unified_api: format!("def {}(...):", name),
            rationale: "Identical naming suggests shared concept.".to_string(),
        });
    }

    suggestions
}

/// Heuristic to name the suggested module based on function names.
fn suggest_module_name(func_name: &str) -> String {
    let name = func_name.to_lowercase();
    if name.contains("parse") {
        "utils".to_string()
    } else if name.contains("read") || name.contains("write") || name.contains("load") {
        "io_helpers".to_string()
    } else if name.contains("validate") || name.contains("check") {
        "validators".to_string()
    } else if name.contains("search") || name.contains("find") {
        "search".to_string()
    } else {
        "shared_utils".to_string()
    }
}

/// Summary of advisory results.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AdvisorSummary {
    pub total_suggestions: usize,
    pub total_functions: usize,
    pub modules_proposed: Vec<String>,
}

pub fn summary(suggestions: &[LibrarySuggestion], total_functions: usize) -> AdvisorSummary {
    let mut modules: Vec<String> = suggestions
        .iter()
        .map(|s| s.module_name.clone())
        .collect::<HashSet<_>>()
        .into_iter()
        .collect();
    modules.sort();

    AdvisorSummary {
        total_suggestions: suggestions.len(),
        total_functions,
        modules_proposed: modules,
    }
}
