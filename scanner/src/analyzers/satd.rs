//! SATD Scanner — Self-Admitted Technical Debt analysis.
//! Rust port of services/satd_scanner.py.

use regex::Regex;
use std::collections::HashMap;
use walkdir::WalkDir;

use crate::constants::{SKIP_DIRS, TEXT_EXTS};

struct SatdMarker {
    pattern: Regex,
    category: &'static str,
    hours: f64,
}

fn satd_markers() -> Vec<SatdMarker> {
    vec![
        SatdMarker { pattern: Regex::new(r"(?i)\b(FIXME)\b").unwrap(), category: "defect", hours: 1.0 },
        SatdMarker { pattern: Regex::new(r"(?i)\b(BUG|BUGFIX)\b").unwrap(), category: "defect", hours: 1.0 },
        SatdMarker { pattern: Regex::new(r"(?i)\b(XXX)\b").unwrap(), category: "defect", hours: 1.0 },
        SatdMarker { pattern: Regex::new(r"(?i)\b(SECURITY)\b").unwrap(), category: "defect", hours: 1.0 },
        SatdMarker { pattern: Regex::new(r"(?i)\b(HACK)\b").unwrap(), category: "design", hours: 2.0 },
        SatdMarker { pattern: Regex::new(r"(?i)\b(WORKAROUND)\b").unwrap(), category: "design", hours: 2.0 },
        SatdMarker { pattern: Regex::new(r"(?i)\b(KLUDGE)\b").unwrap(), category: "design", hours: 2.0 },
        SatdMarker { pattern: Regex::new(r"(?i)\b(TODO)\b").unwrap(), category: "design", hours: 2.0 },
        SatdMarker { pattern: Regex::new(r"(?i)\b(OPTIMIZE|PERF)\b").unwrap(), category: "design", hours: 2.0 },
        SatdMarker { pattern: Regex::new(r"(?i)\b(TECH.?DEBT|DEBT)\b").unwrap(), category: "debt", hours: 3.0 },
        SatdMarker { pattern: Regex::new(r"(?i)\b(NOQA|type:\s*ignore)\b").unwrap(), category: "test", hours: 0.5 },
        SatdMarker { pattern: Regex::new(r"(?i)\b(DOCME|DOCUMENT|UNDOCUMENTED)\b").unwrap(), category: "documentation", hours: 0.25 },
    ]
}

/// Forward-slash path normaliser.
fn fwd(p: &str) -> String {
    p.replace('\\', "/")
}

/// Scan for Self-Admitted Technical Debt markers (TODO, FIXME, HACK, etc.).
pub fn scan_satd(directory: &str) -> serde_json::Value {
    let markers = satd_markers();
    let comment_re = Regex::new(r"#\s*(.*)").unwrap();

    let mut items: Vec<serde_json::Value> = Vec::new();
    let mut by_category: HashMap<String, Vec<serde_json::Value>> = HashMap::new();
    let mut total_hours: f64 = 0.0;

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
        let ext = path.extension().and_then(|e| e.to_str()).map(|e| format!(".{}", e));
        let ext_str = ext.as_deref().unwrap_or("");
        if !TEXT_EXTS.contains(&ext_str) {
            continue;
        }

        let content = match std::fs::read_to_string(path) {
            Ok(c) => c,
            Err(_) => continue,
        };
        let rel = path.strip_prefix(directory).unwrap_or(path)
            .to_string_lossy().to_string();

        for (lineno, line) in content.lines().enumerate() {
            let lineno = lineno + 1;
            for marker in &markers {
                if let Some(m) = marker.pattern.find(line) {
                    let text = if let Some(cm) = comment_re.captures(line) {
                        cm.get(1).map(|x| x.as_str().trim()).unwrap_or(line.trim())
                    } else {
                        line.trim()
                    };
                    let text = if text.len() > 200 { &text[..200] } else { text };
                    let matched_marker = m.as_str().to_uppercase();
                    let item = serde_json::json!({
                        "file": fwd(&rel),
                        "line": lineno,
                        "category": marker.category,
                        "marker": matched_marker,
                        "text": text,
                        "hours": marker.hours,
                    });
                    total_hours += marker.hours;
                    by_category.entry(marker.category.to_string()).or_default().push(item.clone());
                    items.push(item);
                    break; // first match wins per line
                }
            }
        }
    }

    serde_json::json!({
        "total_items": items.len(),
        "total_hours": (total_hours * 10.0).round() / 10.0,
        "items": items,
        "by_category": by_category,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_scan_satd_finds_markers() {
        let tmp = tempfile::tempdir().unwrap();
        let proj = tmp.path().join("project");
        std::fs::create_dir_all(&proj).unwrap();
        std::fs::write(proj.join("main.py"), "# TODO: fix this\n# FIXME: urgent\ncode = 1\n").unwrap();
        let result = scan_satd(proj.to_str().unwrap());
        assert!(result["total_items"].as_u64().unwrap() >= 2);
    }

    #[test]
    fn test_scan_satd_empty_dir() {
        let tmp = tempfile::tempdir().unwrap();
        let proj = tmp.path().join("project");
        std::fs::create_dir_all(&proj).unwrap();
        let result = scan_satd(proj.to_str().unwrap());
        assert_eq!(result["total_items"].as_u64().unwrap(), 0);
    }
}
