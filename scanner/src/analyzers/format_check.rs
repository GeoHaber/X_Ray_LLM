//! Format-checking & type-checking stubs.
//! Rust port of analyzers/format_check.py.
//!
//! These shell out to `ruff` / `ty` / `pyright` — exactly like the Python version.

use std::process::Command;

/// Check formatting with `ruff format --check`.
pub fn check_format(directory: &str) -> serde_json::Value {
    let output = Command::new("ruff")
        .args(["format", "--check", directory])
        .output();

    match output {
        Err(_) => serde_json::json!({"error": "ruff not found. Install: uv tool install ruff"}),
        Ok(out) => {
            let stdout = String::from_utf8_lossy(&out.stdout);
            let stderr = String::from_utf8_lossy(&out.stderr);
            let mut files: Vec<String> = Vec::new();

            for line in stdout.lines() {
                let trimmed = line.trim();
                if !trimmed.is_empty() && std::path::Path::new(trimmed).is_file() {
                    if let Ok(rel) = pathdiff(trimmed, directory) {
                        files.push(fwd(&rel));
                    }
                }
            }
            for line in stderr.lines() {
                let trimmed = line.trim();
                if let Some(rest) = trimmed.strip_prefix("Would reformat:") {
                    let fname = rest.trim();
                    if !fname.is_empty() {
                        files.push(fwd(fname));
                    }
                }
            }

            serde_json::json!({
                "needs_format": files.len(),
                "files": &files[..std::cmp::min(files.len(), 500)],
                "all_formatted": out.status.success(),
            })
        }
    }
}

/// Run `ty` type checker.
pub fn check_types(directory: &str) -> serde_json::Value {
    let output = Command::new("ty")
        .args(["check", "--output-format", "concise", directory])
        .output();

    match output {
        Err(_) => serde_json::json!({"error": "ty not found. Install: uv tool install ty"}),
        Ok(out) => {
            let combined = format!(
                "{}\n{}",
                String::from_utf8_lossy(&out.stdout),
                String::from_utf8_lossy(&out.stderr)
            );
            let mut diagnostics: Vec<serde_json::Value> = Vec::new();
            let mut total_from_summary = 0usize;

            for line in combined.lines() {
                let line = line.trim();
                if line.is_empty() || line.starts_with("Found ") || line.starts_with("info:") {
                    if line.starts_with("Found ") {
                        if let Some(num_str) = line.split_whitespace().nth(1) {
                            if let Ok(n) = num_str.parse::<usize>() {
                                total_from_summary = n;
                            }
                        }
                    }
                    continue;
                }
                if let Some((location, rest)) = line.split_once(": ") {
                    let file_path = location.rsplit_once(':').map_or(location, |(f, _)| f);
                    let severity = if rest.contains("error[") {
                        "error"
                    } else if rest.contains("warning[") {
                        "warning"
                    } else {
                        "info"
                    };
                    diagnostics.push(serde_json::json!({
                        "file": fwd(file_path),
                        "location": location,
                        "message": rest,
                        "severity": severity,
                    }));
                }
            }

            let total = if total_from_summary > 0 {
                total_from_summary
            } else {
                diagnostics.len()
            };
            let errors = diagnostics
                .iter()
                .filter(|d| d["severity"] == "error")
                .count();
            let warnings = diagnostics
                .iter()
                .filter(|d| d["severity"] == "warning")
                .count();

            serde_json::json!({
                "total_diagnostics": total,
                "errors": errors,
                "warnings": warnings,
                "diagnostics": &diagnostics[..std::cmp::min(diagnostics.len(), 500)],
                "clean": out.status.success(),
            })
        }
    }
}

/// Forward-slash normaliser.
fn fwd(p: &str) -> String {
    p.replace('\\', "/")
}

/// Simple path difference.
fn pathdiff(path: &str, base: &str) -> Result<String, ()> {
    let p = std::path::Path::new(path);
    if let Ok(rel) = p.strip_prefix(base) {
        Ok(rel.to_string_lossy().into_owned())
    } else {
        Ok(path.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_fwd() {
        assert_eq!(fwd("a\\b\\c"), "a/b/c");
    }
}
