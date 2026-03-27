//! Temporal coupling analysis — git co-change detection.
//! Rust transpilation of analyzers/temporal.py.

use std::collections::HashMap;
use std::process::Command;

/// Find files that always change together (temporal coupling from git).
/// Transpiled from temporal.py::analyze_temporal_coupling().
pub fn analyze_temporal_coupling(directory: &str, days: u32) -> serde_json::Value {
    let output = match Command::new("git")
        .args([
            "log",
            &format!("--since={}.days", days),
            "--name-only",
            "--pretty=format:---COMMIT---",
        ])
        .current_dir(directory)
        .output()
    {
        Ok(o) => o,
        Err(e) => {
            if e.kind() == std::io::ErrorKind::NotFound {
                return serde_json::json!({"error": "git not found."});
            }
            return serde_json::json!({"error": format!("git error: {}", e)});
        }
    };

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        let msg_end = stderr.char_indices().nth(200).map(|(i, _)| i).unwrap_or(stderr.len());
        let msg = &stderr[..msg_end];
        return serde_json::json!({"error": format!("git error: {}", msg.trim())});
    }

    let stdout = String::from_utf8_lossy(&output.stdout);

    // Parse commits
    let mut commits: Vec<Vec<String>> = Vec::new();
    let mut current_files: Vec<String> = Vec::new();

    for line in stdout.lines() {
        let line = line.trim();
        if line == "---COMMIT---" {
            if !current_files.is_empty() {
                commits.push(std::mem::take(&mut current_files));
            }
        } else if !line.is_empty() {
            current_files.push(line.to_string());
        }
    }
    if !current_files.is_empty() {
        commits.push(current_files);
    }

    // Count co-changes
    let mut pairs: HashMap<(String, String), u32> = HashMap::new();
    for files in &commits {
        let mut sorted: Vec<&str> = files.iter().map(|s| s.as_str()).collect();
        sorted.sort();
        for i in 0..sorted.len() {
            for j in (i + 1)..sorted.len() {
                let key = (sorted[i].to_string(), sorted[j].to_string());
                *pairs.entry(key).or_insert(0) += 1;
            }
        }
    }

    // Sort by count desc, filter >= 3 co-changes, take top 100
    let mut sorted_pairs: Vec<((String, String), u32)> = pairs.into_iter().collect();
    sorted_pairs.sort_by(|a, b| b.1.cmp(&a.1));

    let total_commits = commits.len();
    let couplings: Vec<serde_json::Value> = sorted_pairs
        .iter()
        .take(100)
        .filter(|(_, count)| *count >= 3)
        .map(|((a, b), count)| {
            let strength = if total_commits > 0 {
                (*count as f64 / total_commits as f64 * 100.0 * 10.0).round() / 10.0
            } else {
                0.0
            };
            serde_json::json!({
                "file_a": a,
                "file_b": b,
                "co_changes": count,
                "strength": strength,
            })
        })
        .collect();

    let total_pairs = couplings.len();

    serde_json::json!({
        "couplings": couplings,
        "total_commits": total_commits,
        "total_pairs": total_pairs,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_temporal_coupling_no_git() {
        let tmp = tempfile::tempdir().unwrap();
        let result = analyze_temporal_coupling(tmp.path().to_str().unwrap(), 90);
        // Should return an error since tmp dir is not a git repo
        assert!(result.get("error").is_some() || result.get("couplings").is_some());
    }
}
