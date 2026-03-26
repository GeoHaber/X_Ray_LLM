//! Detection utilities — function/class/import counting.
//! Rust port of analyzers/detection.py (simplified).

use regex::Regex;
use std::collections::HashMap;
use walkdir::WalkDir;

use crate::constants::SKIP_DIRS;

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
