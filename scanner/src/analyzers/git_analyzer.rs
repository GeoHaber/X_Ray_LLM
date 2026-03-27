//! Git Analyzer — hotspot analysis, import graph parsing, ruff integration.
//! Rust transpilation of services/git_analyzer.py.

use std::collections::{HashMap, HashSet};
use std::path::Path;
use std::process::Command;
use walkdir::WalkDir;

use crate::constants::SKIP_DIRS;

/// Forward-slash normaliser.
fn fwd(p: &str) -> String {
    p.replace('\\', "/")
}

/// Analyze git log to find frequently-changed files (hotspots).
/// Transpiled from git_analyzer.py::analyze_git_hotspots().
pub fn analyze_git_hotspots(directory: &str, days: u32) -> serde_json::Value {
    let output = match Command::new("git")
        .args(["log", &format!("--since={}.days", days), "--name-only", "--pretty=format:", "--diff-filter=ACMR"])
        .current_dir(directory)
        .output()
    {
        Ok(o) => o,
        Err(e) => {
            if e.kind() == std::io::ErrorKind::NotFound {
                return serde_json::json!({"error": "git not found. Install git to use hotspot analysis."});
            }
            return serde_json::json!({"error": format!("git error: {}", e)});
        }
    };

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        let msg = if stderr.len() > 200 { &stderr[..200] } else { &stderr };
        return serde_json::json!({"error": format!("git error: {}", msg.trim())});
    }

    let stdout = String::from_utf8_lossy(&output.stdout);

    let skip_patterns = ["__pycache__", ".min.js", ".min.css", "package-lock.json", "uv.lock", "Cargo.lock", ".pyc"];

    let mut churn: HashMap<String, u32> = HashMap::new();
    for line in stdout.lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        if skip_patterns.iter().any(|s| line.contains(s)) {
            continue;
        }
        *churn.entry(line.to_string()).or_insert(0) += 1;
    }

    let mut hotspots: Vec<(String, u32)> = churn.into_iter().collect();
    hotspots.sort_by(|a, b| b.1.cmp(&a.1));

    let hotspot_list: Vec<serde_json::Value> = hotspots
        .iter()
        .take(100)
        .map(|(path, count)| {
            serde_json::json!({
                "path": path,
                "churn": count,
                "priority": *count as f64,
            })
        })
        .collect();

    serde_json::json!({
        "hotspots": hotspot_list,
        "days": days,
    })
}

/// Parse Python imports to build dependency graph.
/// Transpiled from git_analyzer.py::parse_imports().
pub fn parse_imports(directory: &str) -> serde_json::Value {
    let mut nodes: HashMap<String, serde_json::Value> = HashMap::new();
    let mut edges: Vec<serde_json::Value> = Vec::new();
    let mut seen_edges: HashSet<String> = HashSet::new();

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
        if path.extension().and_then(|e| e.to_str()) != Some("py") {
            continue;
        }

        let rel = path
            .strip_prefix(directory)
            .unwrap_or(path)
            .to_string_lossy()
            .replace('\\', "/");
        let module = rel
            .replace('/', ".")
            .trim_end_matches(".py")
            .trim_end_matches(".__init__")
            .to_string();

        if !nodes.contains_key(&module) {
            let label = module.split('.').last().unwrap_or(&module).to_string();
            nodes.insert(
                module.clone(),
                serde_json::json!({
                    "id": module,
                    "label": label,
                    "external": false,
                    "imports_count": 0,
                }),
            );
        }

        let content = match std::fs::read_to_string(path) {
            Ok(c) => c,
            Err(_) => continue,
        };

        for line in content.lines() {
            let line = line.trim();
            if !line.starts_with("import ") && !line.starts_with("from ") {
                continue;
            }
            let parts: Vec<&str> = line.split_whitespace().collect();
            let target = if parts[0] == "import" && parts.len() >= 2 {
                parts[1].split('.').next().unwrap_or("")
            } else if parts[0] == "from" && parts.len() >= 2 {
                let t = parts[1].split('.').next().unwrap_or("");
                if t == "." {
                    continue;
                }
                t
            } else {
                continue;
            };

            if target.is_empty() || target.starts_with('.') {
                continue;
            }

            if !nodes.contains_key(target) {
                nodes.insert(
                    target.to_string(),
                    serde_json::json!({
                        "id": target,
                        "label": target,
                        "external": true,
                        "imports_count": 0,
                    }),
                );
            }

            // Increment imports_count for the source module
            if let Some(node) = nodes.get_mut(&module) {
                if let Some(count) = node.get("imports_count").and_then(|v| v.as_u64()) {
                    node["imports_count"] = serde_json::json!(count + 1);
                }
            }

            let edge_key = format!("{}->{}", module, target);
            if !seen_edges.contains(&edge_key) {
                seen_edges.insert(edge_key);
                edges.push(serde_json::json!({"from": module, "to": target}));
            }
        }
    }

    serde_json::json!({
        "nodes": nodes.values().collect::<Vec<_>>(),
        "edges": edges,
    })
}

/// Run ruff check --fix on the directory.
/// Transpiled from git_analyzer.py::run_ruff().
pub fn run_ruff(directory: &str) -> serde_json::Value {
    let output = match Command::new("ruff")
        .args(["check", "--fix", directory])
        .output()
    {
        Ok(o) => o,
        Err(e) => {
            if e.kind() == std::io::ErrorKind::NotFound {
                return serde_json::json!({"error": "ruff not found. Install: pip install ruff"});
            }
            return serde_json::json!({"error": format!("ruff failed: {}", e)});
        }
    };

    let stdout = String::from_utf8_lossy(&output.stdout);
    let stdout_str = if stdout.len() > 2000 { &stdout[..2000] } else { &stdout };

    let fixed = stdout.matches("Fixed").count() + stdout.matches("fixed").count();
    let remaining = stdout.matches('[').count();

    serde_json::json!({
        "fixed": fixed,
        "remaining": remaining,
        "output": stdout_str,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_imports_empty() {
        let tmp = tempfile::tempdir().unwrap();
        let result = parse_imports(tmp.path().to_str().unwrap());
        assert_eq!(result["nodes"].as_array().unwrap().len(), 0);
        assert_eq!(result["edges"].as_array().unwrap().len(), 0);
    }

    #[test]
    fn test_parse_imports_basic() {
        let tmp = tempfile::tempdir().unwrap();
        let proj = tmp.path().join("project");
        std::fs::create_dir_all(&proj).unwrap();
        std::fs::write(proj.join("main.py"), "import os\nfrom sys import argv\n").unwrap();
        let result = parse_imports(proj.to_str().unwrap());
        let nodes = result["nodes"].as_array().unwrap();
        assert!(nodes.len() >= 2); // main + os and/or sys
    }

    #[test]
    fn test_run_ruff_not_found() {
        // This test may pass or fail based on ruff availability
        let tmp = tempfile::tempdir().unwrap();
        let result = run_ruff(tmp.path().to_str().unwrap());
        // Should return either a valid result or an error, never panic
        assert!(result.is_object());
    }
}
